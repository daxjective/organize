"""명령줄. 출력 끝에는 항상 다음에 칠 명령어를 그대로 보여준다."""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

from organize import __version__
from organize.aliases import BUILTIN
from organize.core.executor import execute, prepare_runlog, write_runlog
from organize.core.runner import build_plan, make_run_id
from organize.core.undo import undo as undo_run
from organize.errors import OrganizeError
from organize.recipes import Recipe, find_recipe, list_recipes, load_recipe
from organize.userconfig import AliasNotDefined, load_config, resolve_alias, save_local_path

_KIND_LABEL = {"mkdir": "폴더 생성", "move": "이동", "quarantine": "격리", "extract": "압축 해제"}

_ALIAS_LABEL = {"home": "홈", "desktop": "바탕화면", "downloads": "다운로드",
                "documents": "문서", "pictures": "사진", "music": "음악", "videos": "영상"}


def _count_files(path: Path) -> str:
    if not path.is_dir():
        return "없음!"
    try:
        return str(sum(1 for p in path.iterdir() if p.is_file()))
    except OSError:
        return "읽을 수 없음"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_roots(recipe, override: str | None) -> list[Path]:
    cfg = load_config(repo_root())
    specs = [override] if override else recipe.roots
    if not specs:
        raise OrganizeError("정리할 폴더가 지정되지 않았습니다.",
                            hint='레시피의 "roots" 에 폴더를 적거나 --root 를 쓰세요.')
    return [resolve_alias(s, cfg) for s in specs]


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
    roots = _resolve_roots(recipe, args.root)
    run_id = make_run_id(datetime.now())

    applied_roots: list[Path] = []     # apply 가 기록까지 완전히 끝난 root — 되돌리기 제안 대상
    failed_roots: list[Path] = []      # 예외로 중단됐거나 기록을 못 남긴 root

    for root in roots:
        print(f"\n■ {root}")
        if not root.is_dir():
            print("  폴더를 찾을 수 없어 건너뜁니다.")
            continue

        # root 하나가 죽어도 나머지 root 는 계속 처리한다. 여기서 조용히
        # 빠져나가는 게 이 프로젝트의 고질병("조용한 무작동")이었다
        # (Task 18 리뷰 Critical #2). OrganizeError·OSError 를 둘 다 넓게
        # 잡되 KeyboardInterrupt 는 그대로 새게 둔다.
        try:
            built = build_plan(root, recipe.steps, today=date.today(), run_id=run_id,
                               profiles_dir=repo_root() / "profiles")
            _print_plan(built, args.verbose)

            if not apply:
                continue

            # execute() 를 부르기 전에 기록 자리를 먼저 마련한다 — 여기서
            # 죽으면 파일이 하나도 안 움직인 상태다(Task 18 리뷰 Critical #1).
            prepare_runlog(built)
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
            applied_roots.append(root)

        except (OrganizeError, OSError) as e:
            if isinstance(e, OrganizeError):
                print(f"\n  실패: {e.message}")
                if e.hint:
                    print(f"  {e.hint}")
            else:
                # 순정 파이썬 예외를 그대로 노출하지 않는다(전역 규칙) — 어느
                # 폴더가 실패했는지만 한국어로 알린다.
                print(f"\n  실패: '{root}' 폴더를 처리하는 동안 예상치 못한 "
                      "오류가 났습니다.")
                print("  디스크 상태나 쓰기 권한을 확인해 주세요.")
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
            if len(roots) == 1:
                print(f"      organize undo --root {applied_roots[0]}")
            elif not failed_roots and not is_do:
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
                print("      (처리되지 못한 폴더는 되돌릴 것이 없습니다: "
                      + ", ".join(str(r) for r in failed_roots) + ")")
        else:
            print("  되돌릴 수 있는 실행이 없습니다.")
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
    return 1 if failed_roots else 0


def _cmd_undo(args) -> int:
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
        except OSError:
            # 순정 파이썬 예외를 그대로 노출하지 않는다(전역 규칙).
            print(f"  '{root}' 폴더를 되돌리는 동안 예상치 못한 오류가 났습니다.")
            print("  디스크 상태나 쓰기 권한을 확인해 주세요.")
            failed_roots.append(root)
            continue

        print(f"  되돌림 {len(result.done)} · 실패 {len(result.failed)}")
        for row in result.failed:
            print(f"    실패  {row['why']}")
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
            except (OSError, json.JSONDecodeError):
                continue                           # 손상된 기록은 list_runs 도 건너뛴다
            if data.get("complete") is False:
                found.append((data.get("run_id", path.stem), folder))
    return found


def _cmd_doctor(args) -> int:
    root = repo_root()
    cfg = load_config(root)

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
        print("  Pillow          없음              선택  EXIF 촬영일을 못 읽습니다.")
        print("                                        파일명과 수정시각으로 대체합니다.")
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
        else:
            print(f"    없음 (폴더 {len(looked_at)}곳 확인함)")

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

    return 0


def _cmd_paths(args) -> int:
    root = repo_root()
    if args.set:
        if "=" not in args.set:
            raise OrganizeError(f"형식이 올바르지 않습니다: {args.set}",
                                hint="organize paths --set archive=D:/보관  처럼 적어 주세요.")
        name, value = args.set.split("=", 1)
        save_local_path(root, name.strip(), value.strip())
        print(f"  @{name.strip()} → {value.strip()} 로 저장했습니다.")
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
        parts += ["--profile", args.profile]
    if args.layout:
        parts += ["--layout", args.layout]
    if args.dest:
        parts += ["--dest", args.dest]
    if args.only:
        parts += ["--only", f'"{args.only}"']
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
        step["when"] = {"ext": [Path(args.only).suffix.lower()]}

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
    sp.add_argument("--only", help='확장자만 고릅니다. 예: "*.md"')
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
