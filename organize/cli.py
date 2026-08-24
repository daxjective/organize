"""명령줄. 출력 끝에는 항상 다음에 칠 명령어를 그대로 보여준다."""

import argparse
import json
import os
import sys
import traceback
from datetime import date, datetime
from pathlib import Path

from organize import __version__
from organize.aliases import BUILTIN
from organize.core.executor import (execute, prepare_runlog, write_json_atomic,
                                    write_runlog)
from organize.core.runner import build_plan, make_run_id
from organize.core.undo import list_runs
from organize.core.undo import undo as undo_run
from organize.core.undo import unreadable_runs
from organize.errors import OrganizeError
from organize.profiles import normalize_ext
from organize.recipes import Recipe, find_recipe, list_recipes, load_recipe
from organize.userconfig import (AliasNotDefined, load_config, refuse_unsupported,
                                 resolve_alias, save_local_path, unsupported_notes)

_KIND_LABEL = {"mkdir": "폴더 생성", "move": "이동", "quarantine": "격리", "extract": "압축 해제"}

_ALIAS_LABEL = {"home": "홈", "desktop": "바탕화면", "downloads": "다운로드",
                "documents": "문서", "pictures": "사진", "music": "음악", "videos": "영상"}


def _count_files(path: Path) -> str:
    if not path.is_dir():
        # "파일 없음!" 은 바로 옆 줄의 "파일 0" 과 같은 뜻으로 읽힌다.
        # 실제로는 폴더 자체가 없다는 뜻이므로 그대로 말한다.
        return "— 폴더 없음"
    try:
        return str(sum(1 for p in path.iterdir() if p.is_file()))
    except OSError:
        return "읽을 수 없음"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


_RECENT_LIMIT = 20          # 이보다 오래된 것은 잊는다. 목록이 화면을 덮지 않게.


def _recent_file() -> Path:
    return repo_root() / ".organize" / "recent-roots.json"


def _recent_roots() -> list[Path]:
    """`--apply` 를 실제로 돌린 적 있는 폴더들. 최근 것이 앞이다."""
    try:
        data = json.loads(_recent_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []                      # 없거나 깨졌으면 그냥 비어 있는 것으로 본다
    if not isinstance(data, list):
        return []
    return [Path(s) for s in data if isinstance(s, str)]


def _remember_root(root: Path) -> str | None:
    """`--apply` 대상 폴더를 기억해 둔다. 실패하면 그 사실을 돌려준다(삼키지 않는다).

    `do --root <폴더>` 로 정리한 폴더는 어느 레시피에도 없어서 `doctor` 의
    점검 대상에 아예 안 들어갔다. 실행이 중간에 끊기면 파일은 옮겨졌는데
    **사용자가 그 사실을 알 방법이 한 군데도 없었다.** 실측한 결함이다.

    실행 **전에** 기록해야 의미가 있다 — 끊긴 뒤에 기록할 기회는 없다.
    """
    path = _recent_file()
    keep = [root] + [p for p in _recent_roots()
                     if os.path.realpath(p) != os.path.realpath(root)]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, [str(p) for p in keep[:_RECENT_LIMIT]])
    except OSError:
        return (f"이 폴더를 doctor 점검 목록에 기억하지 못했습니다({path.parent} 쓰기 실패)."
                f" 문제가 생기면 organize doctor --root {root} 로 직접 확인해 주세요.")
    return None


def _resolve_roots(recipe, override: str | None) -> list[Path]:
    """레시피의 폴더 목록을 실제 경로로 바꾼다. **같은 폴더는 한 번만 돌려준다.**

    별칭 두 개가 같은 곳을 가리키는 것은 흔하다 — 이 저장소가 싣고 있는
    `config.default.json` 만 봐도 `"work": "@documents"` 다.
    `roots: ["@documents", "@work"]` 는 사용자가 쓸 법한 레시피인데, 한 번의
    실행에서 같은 폴더를 두 번 정리하는 것은 **의도된 적이 없다.** 게다가 두
    통과가 같은 run_id 를 공유해 뒤 통과가 앞 통과의 실행 기록을 지웠다.

    비교는 `os.path.realpath` 로 한다 — 심볼릭 링크나 `..` 가 섞여 문자열이
    달라도 같은 폴더면 같다고 봐야 한다. **순서는 처음 나온 대로 유지한다**
    (결정적이어야 한다).
    """
    cfg = load_config(repo_root())
    specs = [override] if override else recipe.roots
    if not specs:
        raise OrganizeError("정리할 폴더가 지정되지 않았습니다.",
                            hint='레시피의 "roots" 에 폴더를 적거나 --root 를 쓰세요.')
    roots: list[Path] = []
    seen: set[str] = set()
    for spec in specs:
        path = resolve_alias(spec, cfg)
        key = os.path.realpath(path)
        if key in seen:
            continue
        seen.add(key)
        roots.append(path)
    return roots


def _print_plan(built, verbose: bool) -> dict:
    counts = built.plan.counts()
    for i, (block, n) in enumerate(built.per_block, 1):
        note = "해당 없음" if n == 0 else f"{n}건"
        print(f"  [{i}/{len(built.per_block)}] {block:<9} {note}")

    if verbose:
        print()
        for a in built.plan.actions:
            label = _KIND_LABEL.get(a.kind, a.kind)
            name = a.src.name if a.src else ""
            print(f"    {label:<6} {name} → {a.dst}    {a.reason}")

    print()
    print(f"  총계  이동 {counts.get('move', 0)} · 격리 {counts.get('quarantine', 0)}"
          f" · 폴더 생성 {counts.get('mkdir', 0)} · 압축 해제 {counts.get('extract', 0)}"
          f" · 손대지 않음 {len(built.plan.skipped)}")
    return counts


def _cmd_preview(args) -> int:
    recipe = load_recipe(find_recipe(repo_root() / "recipes", args.recipe))
    return _run_recipe(recipe, args, apply=False, label=args.recipe)


def _cmd_run(args) -> int:
    recipe = load_recipe(find_recipe(repo_root() / "recipes", args.recipe))
    return _run_recipe(recipe, args, apply=bool(args.apply), label=args.recipe)


def _run_recipe(recipe, args, *, apply: bool, label: str) -> int:
    """레시피 하나를 미리보거나 실행한다. `preview`/`run`/`do` 가 모두 이걸 쓴다.

    `do` 는 레시피 파일 없이 블록 하나짜리 임시 레시피를 만들어 넘긴다 —
    그때 `args.recipe` 는 일부러 None 이다(아래 `is_do` 판정에 쓴다). `label` 은
    화면 맨 끝에 "다음에 그대로 칠 명령"을 고를 때만 쓴다: 레시피 모드에서는
    레시피 이름("t")이고, `do` 모드에서는 재실행에 필요한 인자를 다 담은
    문구("route --profile desktop")다 — 여기서 --profile 이나 --only 를
    빠뜨리면, 미리보기 때는 걸러졌던 파일이 사용자가 그대로 복사한 명령에서는
    안 걸러진 채로 옮겨진다. 미리보기가 보장하는 것과 실제로 벌어지는 일이
    달라지는 조용한 사고이므로, 브리프의 `label=args.block` 보다 넓게 잡았다.
    """
    is_do = getattr(args, "recipe", None) is None
    # 미리보기도 여기서 막는다 — 사용자가 미리보기 화면을 믿고 --apply 를
    # 치기 때문이다. `undo`·`doctor`·`paths` 는 이 검사를 하지 않는다.
    refuse_unsupported(load_config(repo_root()))
    roots = _resolve_roots(recipe, args.root)
    run_id = make_run_id(datetime.now())

    applied_roots: list[Path] = []     # apply 가 기록까지 완전히 끝난 root — 되돌리기 제안 대상
    failed_roots: list[Path] = []      # 예외로 중단됐거나 기록을 못 남긴 root
    failed_items = 0                   # root 는 살았지만 항목 단위로 실패한 것
    planned_actions = 0                # 계획된 동작 총합 — 0건이면 권할 명령이 없다

    for root in roots:
        print(f"\n■ {root}")
        if not root.is_dir():
            print("  폴더를 찾을 수 없어 건너뜁니다.")
            continue

        # root 하나가 죽어도 나머지 root 는 계속 처리한다. 여기서 조용히
        # 빠져나가는 게 이 프로젝트의 고질병("조용한 무작동")이었다
        # (Task 18 리뷰 Critical #2).
        #
        # **예외 종류를 열거하지 않는다.** 예전에는 (OrganizeError, OSError) 로
        # 못박아 뒀는데, 레시피의 정규식 오타가 내는 `re.error` 는 ValueError 의
        # 자식이라 그 그물을 그냥 빠져나갔다 — 앞 폴더에서 이미 옮긴 것의
        # 되돌리기 안내가 통째로 사라졌다. 격리의 목적은 "무엇이 터지든 나머지
        # 폴더는 살린다" 이므로 Exception 을 통째로 받는다. KeyboardInterrupt 와
        # SystemExit 은 Exception 의 자식이 아니라 그대로 새어 나간다 — Ctrl-C 는
        # 여전히 통해야 한다.
        try:
            built = build_plan(root, recipe.steps, today=date.today(), run_id=run_id,
                               profiles_dir=repo_root() / "profiles")
            _print_plan(built, args.verbose)
            planned_actions += len(built.plan.actions)

            if not apply:
                continue

            # execute() 를 부르기 전에 기록 자리를 먼저 마련한다 — 여기서
            # 죽으면 파일이 하나도 안 움직인 상태다(Task 18 리뷰 Critical #1).
            prepare_runlog(built)
            # 실행 **전에** 기억해 둔다. 도중에 끊기면 기록할 기회가 없다.
            forgot = _remember_root(root)
            if forgot:
                print(f"  {forgot}")      # 삼키지 않는다
            result = execute(built)

            try:
                log = write_runlog(built, result)
            except OrganizeError as e:
                # 이 시점엔 이미 파일이 옮겨졌다. 기록을 못 남겼어도 최소한
                # 무엇을 어디로 옮겼는지 화면에 통째로 남긴다 — 사람이 손으로
                # 되돌릴 수 있는 유일한 근거다. 대체 위치에 다시 써 보는
                # 안전망은 만들지 않는다 — undo 는 <root>/.organize/runs 만
                # 보므로, 못 찾을 자리에 기록을 흩어 두는 것은 화면에 정직하게
                # 찍는 것보다 못하다.
                print(f"\n  {e.message}")
                if e.hint:
                    print(f"  {e.hint}")
                print("  아래가 이번에 실제로 옮긴 전부입니다."
                      " 되돌리려면 이 목록을 보고 직접 옮겨 주세요.")
                for row in result.done:
                    if row["kind"] == "mkdir":
                        print(f"      (새 폴더) {row['final']}")
                    else:
                        print(f"      {row['src']}  ->  {row['final']}")
                failed_roots.append(root)
                continue

            print(f"\n  완료. 처리 {len(result.done)} · 실패 {len(result.failed)}"
                  f" · 건너뜀 {len(result.stale)}")
            print(f"  기록: {log}")
            for row in result.failed:
                print(f"    실패  {Path(row['src']).name} — {row['why']}")
                # executor 가 hint 를 일부러 보존하는데(errors.py 가 메시지와
                # 힌트를 같이 들고 다니게 만든 이유) 화면에서 버리면 그 설계가
                # 사용자에게 닿지 않는다. 실행 기록에는 답이 들어 있는데
                # 사용자만 못 보는 상태였다.
                if row.get("hint"):
                    print(f"          → {row['hint']}")
            for row in result.stale:
                # 개수만 알리면 어떤 파일인지 끝내 알 수 없다(--verbose 도
                # 계획만 보여줄 뿐 결과는 안 보여준다).
                print(f"    건너뜀  {Path(row['src']).name} — {row['why']}")
            failed_items += len(result.failed)
            if result.done:
                # **실제로 옮긴 것이 있을 때만** 되돌리기 제안 대상이다.
                # 항목이 전부 실패한 실행까지 넣으면, 도구가 직접 권한
                # `organize undo --root ...` 가 "기록이 없습니다" 로 답한다.
                applied_roots.append(root)

        except OrganizeError as e:
            print(f"\n  실패: {e.message}")
            if e.hint:
                print(f"  {e.hint}")
            failed_roots.append(root)
            continue
        except Exception as e:
            # 순정 파이썬 예외를 그대로 노출하지 않는다(전역 규칙). 삼키지도
            # 않는다: 화면에 남기고 아래에서 종료 코드 1 로 반영한다.
            #
            # **`apply` 중이었으면 "건너뜁니다" 라고 말하면 안 된다.** 그
            # 시점엔 이미 파일을 옮기고 폴더를 만든 뒤일 수 있는데, 사용자는
            # 안 건드렸다는 뜻으로 읽는다. 실측한 결함이다.
            if apply:
                print(f"\n  실패: '{root}' 폴더를 정리하다 도중에 멈췄습니다 "
                      f"({type(e).__name__}).")
                print("  이미 옮긴 것이 있을 수 있습니다. 무엇이 옮겨졌는지는")
                print(f"      {root / '.organize' / 'runs'}")
                print("  의 실행 기록과, 그 폴더에 새로 생긴 폴더를 확인해 주세요.")
                print(f"      organize undo --root {root}")
            else:
                print(f"\n  실패: '{root}' 폴더를 살펴보다 예상치 못한 오류가 "
                      f"났습니다 ({type(e).__name__}). 이 폴더는 건너뜁니다.")
                print("  파일은 하나도 건드리지 않았습니다.")
            # 예외의 정체를 통째로 지우면 신고가 들어와도 손댈 단서가 0 이다.
            # 클래스 이름은 위에 남기고, 전체 자취는 요청할 때만 흘린다.
            if os.environ.get("ORGANIZE_DEBUG"):
                traceback.print_exc()
            else:
                print("  자세한 오류 내용을 보려면 ORGANIZE_DEBUG=1 을 붙여 다시 실행해 주세요.")
            failed_roots.append(root)
            continue

    print()
    if failed_roots:
        print(f"  폴더 {len(roots)}곳 중 {len(failed_roots)}곳에서 문제가 생겼습니다: "
              + ", ".join(str(r) for r in failed_roots))

    # --root 로 대상을 바꿔서 봤으면 제안하는 명령에도 그대로 넣는다.
    # 안 넣으면 미리보기는 이 폴더를 보여주고, 복사한 명령은 레시피에 적힌
    # 원래 폴더(예: 진짜 다운로드 폴더)를 --apply 로 정리해 버린다.
    root_opt = f" --root {args.root}" if getattr(args, "root", None) else ""
    if apply:
        if applied_roots:
            print("  되돌리려면:")
            if len(applied_roots) == 1:
                print(f"      organize undo --root {applied_roots[0]}")
            elif len(applied_roots) == len(roots) and not failed_roots and not is_do:
                # root 가 여러 개면 roots[0] 만 알려주지 않는다(Task 18 리뷰
                # Important #1) — 전부 성공했을 때는 _cmd_undo 가 --root 없이
                # 레시피의 roots 를 전부 순회하므로 --recipe 하나로 끝난다.
                # `do` 는 항상 root 가 하나뿐이라 이 분기는 안 타지만(len(roots)==1
                # 에서 이미 걸린다), args.recipe 가 None 인 do 에서 실수로
                # 이 줄을 타는 일이 생겨도 "organize undo --recipe None" 같은
                # 못 쓰는 명령을 보여주지 않도록 방어한다.
                print(f"      organize undo --recipe {args.recipe}")
            else:
                # 일부 root 만 성공했을 때는 --recipe 를 권하지 않는다.
                # organize undo --recipe 는 레시피의 root 를 전부(실패한
                # root 포함) 순회한다. 그 반복문은 이제 root 단위로 격리돼
                # 있어서 중간에 멈추지는 않지만(커밋 bde2f85), 되돌릴 기록이
                # 없는 root 마다 "되돌리지 못했습니다" 를 찍고 종료 코드가
                # 1 이 된다 — 실제로는 되돌릴 게 없어서 정상인데 실패처럼
                # 보인다. 성공한 root 만 하나씩 짚어 주는 쪽이 정직하다.
                for r in applied_roots:
                    print(f"      organize undo --root {r}")
                rest = [r for r in roots if r not in applied_roots]
                if rest:
                    print("      (되돌릴 것이 없는 폴더: "
                          + ", ".join(str(r) for r in rest) + ")")
        else:
            print("  되돌릴 수 있는 실행이 없습니다.")
    elif not planned_actions:
        # 방금 안 된다고 말한 명령을, 또는 아무 일도 안 일어날 명령을 그대로
        # 권하면 안 된다. 실측했다 — 없는 블록 이름으로 실패한 미리보기가
        # `organize do 없는것 --apply` 를 그대로 제안했다.
        if failed_roots:
            print("  문제를 고친 뒤 다시 미리보기부터 해 주세요.")
        else:
            print("  정리할 것이 없습니다. 실행할 필요도 없습니다.")
    else:
        print("  실제로 실행하려면:")
        if is_do:
            print(f"      organize do {label}{root_opt} --apply")
        else:
            print(f"      organize run {label}{root_opt} --apply")
        if not args.verbose:
            print("\n  무엇이 어디로 가는지 전부 보려면:")
            if is_do:
                print(f"      organize do {label}{root_opt} --verbose")
            else:
                print(f"      organize preview {label}{root_opt} --verbose")
    # 항목 하나가 실패해도 종료 코드에 드러나야 한다 — 자동화(배치 파일·작업
    # 스케줄러)가 "다 됐다" 로 읽으면 안 된다.
    return 1 if (failed_roots or failed_items) else 0


def _warn_unsupported_config() -> None:
    """`undo`·`doctor`·`paths` 용 — 알리되 **멈추지 않는다.**

    되돌리기는 사용자의 마지막 안전줄이고 `doctor` 는 무엇이 잘못됐는지
    알아내는 도구다. 아직 만들지 않은 설정 키 하나 때문에 그 둘이 잠기면,
    설정이 이상할수록 손쓸 방법이 없어진다. 실측한 결함이다.
    """
    for message, hint in unsupported_notes(load_config(repo_root())):
        print(f"  경고: {message}")
        print(f"  {hint}")


def _report_unusable_runs(root: Path) -> None:
    """되돌릴 수 없는 실행 기록이 남아 있으면 어느 것인지 알린다.

    끊긴 실행(`complete: false`)과 못 읽는 기록이 여기 해당한다. 되돌리기가
    거부하는 기록들이므로, 그것이 옮겨 놓은 파일은 제자리로 돌아오지 않는다.
    """
    try:
        rows = list_runs(root)
    except OSError:
        return                       # 기록을 못 읽어도 되돌리기 자체는 끝났다
    남은것 = [r for r in rows
             if r["undone_at"] is None and (r["unreadable"] or r.get("complete") is False)]
    if not 남은것:
        return
    print(f"    되돌릴 수 없는 기록이 {len(남은것)}개 남아 있습니다"
          " — 그 실행이 옮긴 파일은 제자리로 오지 않습니다:")
    for r in 남은것:
        왜 = "읽을 수 없음" if r["unreadable"] else "중간에 끊김"
        print(f"      {r['run_id']}  ({왜})")
    print(f"      organize doctor --root {root}  로 자세히 볼 수 있습니다.")


def _cmd_undo(args) -> int:
    _warn_unsupported_config()
    recipes_dir = repo_root() / "recipes"
    if args.root:
        roots = [resolve_alias(args.root, load_config(repo_root()))]
    else:
        recipe = load_recipe(find_recipe(recipes_dir, args.recipe)) if args.recipe else None
        if recipe is None:
            raise OrganizeError("어느 폴더를 되돌릴지 알 수 없습니다.",
                                hint="organize undo --root @downloads 처럼 폴더를 지정해 주세요.")
        roots = _resolve_roots(recipe, None)

    failed_roots: list[Path] = []

    for root in roots:
        print(f"■ {root}")
        # 폴더 하나가 죽어도 나머지는 계속 되돌린다. 되돌릴 기록이 없는 폴더는
        # 흔하다 — 이번에 처리되지 않은 폴더, 이미 되돌린 폴더가 그렇다.
        # 예전에는 여기서 통째로 죽어 **뒤 폴더가 옮겨진 채 남았다.**
        # 실행 쪽 Critical #2 와 같은 부류다. KeyboardInterrupt 는 그대로 새게 둔다.
        try:
            result = undo_run(root, args.run_id)
        except OrganizeError as e:
            print(f"  되돌리지 못했습니다: {e.message}")
            if e.hint:
                print(f"  {e.hint}")
            failed_roots.append(root)
            continue
        except Exception:
            # 예외 종류를 열거하지 않는다 — 실행 쪽과 같은 이유다(무엇이 터지든
            # 나머지 폴더는 되돌린다). KeyboardInterrupt 는 그대로 새어 나간다.
            # 순정 파이썬 예외를 그대로 노출하지 않는다(전역 규칙).
            print(f"  '{root}' 폴더를 되돌리는 동안 예상치 못한 오류가 났습니다.")
            print("  디스크 상태나 쓰기 권한을 확인해 주세요.")
            failed_roots.append(root)
            continue

        print(f"  되돌림 {len(result.done)} · 실패 {len(result.failed)}")
        # 되돌리기가 성공해도 **옆에 못 쓰는 기록이 남아 있으면 말한다.**
        # 그 기록이 옮겨 놓은 파일은 그대로 남아 있는데 화면이 "되돌림 N · 실패 0"
        # 만 보여주면, 사용자는 다 정리됐다고 믿는다. 도구는 알면서 말하지 않는
        # 셈이고, 그게 이 프로젝트가 여덟 번 물린 "조용한 무작동" 이다.
        _report_unusable_runs(root)
        for row in result.done:
            if row.get("renamed"):
                # 원래 자리에 다른 것이 생겨서 비켜 놓았다. 덮어쓰지 않은 것은
                # 옳지만, 이름이 바뀐 사실을 안 알리면 사용자는 제자리로 온 줄 안다.
                print(f"    이름 바뀜  {Path(row['intended']).name}"
                      f" → {Path(row['final']).name}"
                      f"  (원래 자리에 다른 것이 있었습니다)")
        for row in result.failed:
            print(f"    실패  {row['why']}")
            if row.get("hint"):
                print(f"          → {row['hint']}")
        if result.failed:
            # 항목별로 되돌림 여부를 기록해 두므로, 원인을 고치고 다시 부르면
            # 못 되돌린 것만 이어서 처리한다.
            print("\n  원인을 고친 뒤 같은 명령을 다시 실행하면 남은 것만 되돌립니다:")
            print(f"      organize undo --root {root}")
            failed_roots.append(root)

    if failed_roots:
        print(f"\n  폴더 {len(roots)}곳 중 {len(failed_roots)}곳에서 문제가 생겼습니다: "
              + ", ".join(str(r) for r in failed_roots))
        return 1
    return 0


_HIDDEN_CAVEAT = "숨김 폴더는 보지 않았습니다"
_ZERO_BYTE_SHOWN = 10        # 화면을 덮지 않게 이만큼만 보이고 나머지는 개수로 알린다


def organized_before(folder: Path) -> bool:
    """이 폴더에서 정리를 돌린 적이 있는가.

    `prepare_runlog` 이 `execute()` **전에** `.organize/` 를 만든다. 그리고
    `claim_path` 가 빈 자리를 잡는 것은 `execute()` **안에서만** 일어난다.
    그러므로 잔해를 남길 수 있었던 실행은 반드시 `.organize/` 를 먼저 만들었다
    — 이 폴더만 봐도 **빠뜨리는 것이 없다.**
    """
    return (folder / ".organize").is_dir()


def _find_zero_byte_files(folders: list[Path]) -> list[Path]:
    """`claim_path`(organize/core/paths.py) 가 이름을 먼저 잡으려고 만든 빈
    파일이, 그 직후 강제 종료로 남았을 수 있다. **찾기만 하고 지우지 않는다**
    — 사용자가 일부러 만든 빈 파일일 수도 있다("파일을 삭제하지 않는다"
    는 이 프로젝트의 절대 규칙이다).

    **아무 폴더나 뒤지지 않는다.** 실제로 홈 폴더를 통째로 훑게 두었더니
    1081개가 나왔다 — `LOCK`, `LOG`, `-journal`, 빈 `__init__.py` 처럼 다른
    프로그램이 정상적으로 만든 것들이었다. 그걸 잔해라고 알리면 소음이고,
    지우라고 안내하면 남의 프로그램을 망가뜨린다. 실측하고 좁혔다.

    그래서 두 가지로 거른다.
      - **정리를 돌린 적 있는 폴더만** 본다(`organized_before`).
      - 숨김 폴더(`.` 로 시작)는 뒤지지 않는다 — 우리 장부 폴더도 여기 걸린다.
    """
    found: list[Path] = []
    for folder in folders:
        if not folder.is_dir() or not organized_before(folder):
            continue
        try:
            for p in folder.rglob("*"):
                rel = p.relative_to(folder).parts
                if any(part.startswith(".") for part in rel):
                    continue                       # 숨김 폴더·숨김 파일은 남의 것이다
                if not p.is_file():
                    continue
                try:
                    if p.stat().st_size == 0:
                        found.append(p)
                except OSError:
                    continue                       # 그 사이 사라졌으면 확인할 게 없다
        except OSError:
            continue                               # 폴더를 못 읽어도 나머지는 계속 본다
    return sorted(set(found), key=str)


def _find_unreadable_runs(folders: list[Path]) -> list[tuple[str, Path]]:
    """읽지 못한 실행 기록. **"없음 (확인함)" 으로 뭉개면 안 되는 것들이다.**

    기록이 쓰다 만 상태면 `undo` 는 그 기록을 되돌릴 대상으로 집지 못한다.
    파일은 옮겨져 있는데 도구는 "되돌릴 실행 기록이 없습니다" 라고 답한다 —
    사용자가 그 사실을 알 방법은 doctor 뿐이다.
    """
    found: list[tuple[str, Path]] = []
    for folder in folders:
        for path in unreadable_runs(folder):
            found.append((Path(path).name, folder))
    return found


def _find_incomplete_runs(folders: list[Path]) -> list[tuple[str, Path]]:
    """`prepare_runlog`(organize/core/executor.py) 가 실행 **전에** 남긴
    뼈대(`complete: false`)가 `write_runlog` 로 덮어써지지 않은 채 남아 있으면,
    실행이 중간에 끊겨 무엇을 옮겼는지 아무 데도 안 적힌 상태다.
    `organize/core/undo.py::undo` 는 이런 기록을 거부하기만 할 뿐 알리지
    않으므로, 사용자가 이걸 알 방법은 doctor 뿐이다.
    """
    found: list[tuple[str, Path]] = []
    for folder in folders:
        runs_dir = folder / ".organize" / "runs"
        if not runs_dir.is_dir():
            continue
        for path in sorted(runs_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue                           # 못 읽은 기록은 _find_unreadable_runs 가 알린다
            if isinstance(data, dict) and data.get("complete") is False:
                found.append((data.get("run_id", path.stem), folder))
    return found


def _cmd_doctor(args) -> int:
    root = repo_root()
    cfg = load_config(root)
    _warn_unsupported_config()

    print(f"  Python          {sys.version.split()[0]:<18}"
          f"{'OK' if sys.version_info >= (3, 11) else '3.11 이상이 필요합니다'}")
    try:
        import tkinter
        print(f"  tkinter         {tkinter.TkVersion:<18}OK")
    except ImportError:
        print("  tkinter         없음              선택  GUI 를 쓰려면 필요합니다")
    try:
        import PIL  # noqa: F401
        print("  Pillow          있음              OK   EXIF 촬영일을 읽습니다")
    except ImportError:
        # "대체합니다" 는 `by_date` 에만 참이다. `route --profile photos` 는
        # **대체가 없다** — has_exif_camera 가 판정 불가(None)를 주면 그 규칙은
        # 불일치로 처리되므로, 사진·캡처 규칙에 걸리는 파일이 하나도 없다.
        # 실측했다: 영상만 옮겨지고 사진1.jpg·캡처.png 는 그대로 남았다.
        # 사용자가 그 이유를 알 방법이 doctor 뿐이다.
        print("  Pillow          없음              선택  EXIF 촬영일을 못 읽습니다.")
        print("                                        by_date 는 파일명과 수정시각으로 대체합니다.")
        print("                                        photos 프로파일의 '사진'·'캡처' 규칙은")
        print("                                        아무 파일도 분류하지 못합니다(대체 없음).")
        print("                                        쓰려면: pip install Pillow")

    print("\n  폴더 위치")
    checked_folders: list[Path] = []               # 아래 두 점검이 볼 대상 — 실제로 확인된 폴더만
    for name in BUILTIN:
        try:
            p = resolve_alias(f"@{name}", cfg)
        except AliasNotDefined:
            continue
        print(f"    {_ALIAS_LABEL.get(name, name):<10} {str(p):<44} 파일 {_count_files(p)}")
        if p not in checked_folders:
            checked_folders.append(p)
    for name in sorted(cfg.paths):
        p = resolve_alias(f"@{name}", cfg)
        print(f"    @{name:<9} {str(p):<44} 파일 {_count_files(p)}")
        if p not in checked_folders:
            checked_folders.append(p)

    # `do --root <폴더>` 로 정리한 폴더는 어느 레시피에도 없다. 그걸 안 보면
    # 실행이 끊겼을 때 사용자가 그 사실을 알 방법이 한 군데도 없다.
    extra: list[Path] = []
    if getattr(args, "root", None):
        extra.append(resolve_alias(args.root, cfg))
    extra.extend(_recent_roots())
    shown = 0
    for p in extra:
        if p not in checked_folders:
            checked_folders.append(p)
            if shown == 0:
                print("\n  최근에 정리한 폴더")
            print(f"    {str(p):<54} 파일 {_count_files(p)}")
            shown += 1

    recipes_dir = root / "recipes"
    names = list_recipes(recipes_dir)
    print(f"\n  레시피 {len(names)}개 · 프로파일 {len(list((root / 'profiles').glob('*.toml')))}개")

    missing: set[str] = set()
    for name in names:
        try:
            recipe = load_recipe(find_recipe(recipes_dir, name))
        except OrganizeError:
            continue
        for spec in recipe.roots:
            if not spec.startswith("@"):
                # 생짜 경로다. 별칭이 아니라고 넘겨 버리면 **사용자가 실제로
                # 정리하는 폴더**를 doctor 가 아예 안 보게 된다 — 잔해도
                # 끊긴 기록도 거기 생기는데 말이다. 점검 대상에 넣는다.
                try:
                    raw = resolve_alias(spec, cfg)
                except (OrganizeError, AliasNotDefined):
                    continue
                if raw not in checked_folders:
                    checked_folders.append(raw)
                continue
            head = spec[1:].split("/")[0]
            if head not in BUILTIN and head not in cfg.paths:
                missing.add(head)

    if missing:
        print()
        for head in sorted(missing):
            print(f"  '@{head}' 위치가 정해져 있지 않습니다. 지정하려면:")
            print(f"      organize paths --set {head}=<경로>")

    # 아래 두 점검은 브리프에는 없지만, claim_path 와 prepare_runlog 가 남길 수
    # 있는 흔적을 사용자가 doctor 밖에서는 알 방법이 없어서 넣었다(컨트롤러
    # 지시). "확인 안 한 것을 됐다고 말하지 않는다" 는 규칙에 따라, 대상
    # 폴더가 하나도 안 잡혔을 때는 "없음"이 아니라 그 사실을 그대로 밝힌다.
    print("\n  0바이트 파일 (강제 종료 후 남은 잔해일 수 있습니다 — 지우지 않았습니다)")
    looked_at = [f for f in checked_folders if f.is_dir() and organized_before(f)]
    if not looked_at:
        # "확인 안 한 것을 됐다고 말하지 않는다" — 볼 폴더가 없었다는 사실을
        # "없음" 으로 뭉개지 않는다.
        print("    정리를 돌린 적 있는 폴더가 없어 볼 것이 없습니다.")
    else:
        zero_byte = _find_zero_byte_files(looked_at)
        if zero_byte:
            print(f"    {len(zero_byte)}개 발견 (정리를 돌린 적 있는 폴더 {len(looked_at)}곳에서)")
            for p in zero_byte[:_ZERO_BYTE_SHOWN]:
                print(f"      {p}")
            if len(zero_byte) > _ZERO_BYTE_SHOWN:
                print(f"      … 그 외 {len(zero_byte) - _ZERO_BYTE_SHOWN}개")
            # 지우라고 말하지 않는다 — 빈 파일을 정상적으로 쓰는 프로그램이 많다.
            print("      정리가 중간에 끊긴 적이 있는지 확인해 보세요."
                  " 우리가 남긴 것이 아니면 그대로 두면 됩니다.")
            print(f"      ({_HIDDEN_CAVEAT})")
        else:
            # "없음" 이라고만 하면 **확인 안 한 것을 됐다고 말하는 것**이 된다.
            # 목적지 폴더 이름을 숨김(`to = ".백업"`)으로 적는 것을 막는 코드가
            # 없어서, 정리 결과가 숨김 폴더로 갈 수 있다. 어디까지 봤는지 밝힌다.
            print(f"    없음 (폴더 {len(looked_at)}곳 확인함 · {_HIDDEN_CAVEAT})")

    print("\n  완료되지 않은 실행 기록 (undo 가 거부합니다 — 무엇을 옮겼는지 알 수 없습니다)")
    if not checked_folders:
        print("    확인할 폴더가 없어 못 봤습니다.")
    else:
        incomplete = _find_incomplete_runs(checked_folders)
        if incomplete:
            print(f"    {len(incomplete)}개 발견 — 아래 폴더 안 새로 생긴 폴더와"
                  " .organize/trash 를 직접 확인해 주세요.")
            for run_id, folder in incomplete:
                print(f"      {run_id}  ({folder})")
        else:
            print("    없음 (확인함)")

    print("\n  읽지 못한 실행 기록 (무엇을 옮겼는지 알 수 없어 되돌리기가 거부합니다)")
    if not checked_folders:
        print("    확인할 폴더가 없어 못 봤습니다.")
    else:
        broken = _find_unreadable_runs(checked_folders)
        if broken:
            print(f"    {len(broken)}개 발견 — 기록이 쓰다 만 상태입니다."
                  " 아래 폴더 안 새로 생긴 폴더와 .organize/trash 를 직접 확인해 주세요.")
            for name, folder in broken:
                print(f"      {name}  ({folder / '.organize' / 'runs'})")
        else:
            print("    없음 (확인함)")

    return 0


def _cmd_paths(args) -> int:
    root = repo_root()
    _warn_unsupported_config()
    if args.set:
        if "=" not in args.set:
            raise OrganizeError(f"형식이 올바르지 않습니다: {args.set}",
                                hint="organize paths --set archive=D:/보관  처럼 적어 주세요.")
        name, value = args.set.split("=", 1)
        name, value = name.strip(), value.strip()
        if not value:
            # 빈 값을 그대로 저장하면 Path("") 가 "." 이 되어 그 별칭이 **현재
            # 작업 폴더**를 가리킨다. 나중에 `--root @이름 --apply` 로 쓰면
            # 의도하지 않은 폴더를 정리해 버린다. 여기서 막는다.
            raise OrganizeError(
                f"'@{name}' 에 넣을 경로가 비어 있습니다.",
                hint="organize paths --set archive=D:/보관  처럼 경로까지 적어 주세요.")
        if not name:
            raise OrganizeError(
                "별칭 이름이 비어 있습니다.",
                hint="organize paths --set archive=D:/보관  처럼 이름을 적어 주세요.")
        save_local_path(root, name, value)
        print(f"  @{name} → {value} 로 저장했습니다.")
        return 0

    cfg = load_config(root)
    for name in BUILTIN:
        print(f"  @{name:<10} {resolve_alias(f'@{name}', cfg)}")
    for name in sorted(cfg.paths):
        print(f"  @{name:<10} {resolve_alias(f'@{name}', cfg)}")
    print("\n  위치를 바꾸려면:")
    print("      organize paths --set <이름>=<경로>")
    return 0


def _cmd_list(args) -> int:
    root = repo_root()
    print("  레시피")
    for name in list_recipes(root / "recipes"):
        print(f"    {name}")
    print("\n  분류 설정")
    for p in sorted((root / "profiles").glob("*.toml")):
        print(f"    {p.stem}")
    print("\n  미리보려면:")
    print("      organize preview <레시피>")
    return 0


def _quoted(value: str) -> str:
    """공백이 든 값은 큰따옴표로 감싼다 — 제안한 명령을 그대로 복사해 붙였을 때
    깨지지 않게. 작은따옴표가 아니라 큰따옴표인 이유는, 이 도구의 주 사용처인
    윈도우 `cmd.exe` 가 작은따옴표를 따옴표로 보지 않기 때문이다. 큰따옴표는
    cmd.exe · PowerShell · 리눅스 셸에서 모두 통한다.
    """
    # 공백뿐 아니라 셸이 펼치는 글자(*, ?, [ ])도 감싼다. 실측 — pdf 가 있는
    # 폴더에서 `--only *.pdf` 를 그대로 붙여넣으면 리눅스 셸이
    # `--only invoice.pdf report.pdf` 로 펼쳐서 argparse 오류가 났다.
    return f'"{value}"' if any(c.isspace() or c in '*?[]' for c in value) else value


def _do_label(args) -> str:
    """`do` 를 그대로 다시 부를 때 필요한 인자를 전부 담는다. `--root` 는
    `_run_recipe` 가 root_opt 로 따로 붙이므로 여기엔 넣지 않는다.

    `--only`/`--profile` 등을 빠뜨리면, 미리보기에서 걸러졌던 파일이 사용자가
    그대로 복사한 "실제로 실행하려면" 명령에서는 안 걸러진 채 옮겨진다 —
    미리보기가 보여준 것과 다른 일이 실제로 벌어지는, 이 프로젝트가 가장
    경계하는 종류의 사고다.
    """
    parts = [args.block]
    if args.profile:
        parts += ["--profile", _quoted(args.profile)]
    if args.layout:
        parts += ["--layout", _quoted(args.layout)]
    if args.dest:
        parts += ["--dest", _quoted(args.dest)]
    if args.only:
        parts += ["--only", _quoted(args.only)]
    return " ".join(parts)


def _cmd_do(args) -> int:
    step: dict = {"block": args.block}
    if args.profile:
        step["profile"] = args.profile
    if args.layout:
        step["layout"] = args.layout
    if args.dest:
        step["dest"] = args.dest
    if args.only:
        # 레시피·프로파일의 `ext` 와 **같은 함수**를 쓴다. 예전에는 여기만
        # 점을 붙여 줘서, `--only pdf` 가 되는 걸 본 사용자가 프로파일에
        # `ext = "pdf"` 를 쓰면 아무 일도 안 일어났다(오류도 없이).
        step["when"] = {"ext": [normalize_ext(args.only, "--only")]}

    recipe = Recipe(name=f"즉석 {args.block}", roots=[args.root], steps=[step])
    fake = argparse.Namespace(recipe=None, root=args.root, verbose=args.verbose,
                              apply=args.apply)
    return _run_recipe(recipe, fake, apply=bool(args.apply), label=_do_label(args))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="organize", description="파일 정리 자동화")
    p.add_argument("--version", action="version", version=f"organize {__version__}")
    sub = p.add_subparsers(dest="command")

    def add_common(sp):
        sp.add_argument("--root", help="레시피의 대상 폴더를 덮어씁니다 (@downloads 등)")
        sp.add_argument("--verbose", action="store_true", help="모든 항목을 나열합니다")

    sp = sub.add_parser("preview", help="미리보기 (파일을 건드리지 않음)")
    sp.add_argument("recipe")
    add_common(sp)
    sp.set_defaults(func=_cmd_preview)

    sp = sub.add_parser("run", help="실행")
    sp.add_argument("recipe")
    sp.add_argument("--apply", action="store_true", help="실제로 실행합니다")
    add_common(sp)
    sp.set_defaults(func=_cmd_run)

    sp = sub.add_parser("undo", help="되돌리기")
    sp.add_argument("run_id", nargs="?")
    sp.add_argument("--recipe")
    sp.add_argument("--root")
    sp.set_defaults(func=_cmd_undo)

    sp = sub.add_parser("doctor", help="환경 점검")
    sp.add_argument("--root", help="레시피에 없는 폴더도 함께 점검합니다")
    sp.set_defaults(func=_cmd_doctor)

    sp = sub.add_parser("paths", help="폴더 위치 확인·지정")
    sp.add_argument("--set", help="이름=경로")
    sp.set_defaults(func=_cmd_paths)

    sp = sub.add_parser("list", help="레시피와 분류 설정 목록")
    sp.set_defaults(func=_cmd_list)

    sp = sub.add_parser("do", help="레시피 없이 작업 하나만 실행")
    sp.add_argument("block")
    sp.add_argument("--root", required=True)
    sp.add_argument("--profile")
    sp.add_argument("--layout")
    sp.add_argument("--dest")
    sp.add_argument("--only",
                    help='확장자 하나만 고릅니다. md · .md · "*.md" 모두 됩니다')
    sp.add_argument("--apply", action="store_true")
    sp.add_argument("--verbose", action="store_true")
    sp.set_defaults(func=_cmd_do)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)

    if not getattr(args, "func", None):
        parser.print_help()
        return 0

    try:
        return args.func(args)
    except OrganizeError as e:
        print(f"\n{e.message}")
        if e.hint:
            print(f"\n{e.hint}")
        return 1
