"""명령줄. 출력 끝에는 항상 다음에 칠 명령어를 그대로 보여준다."""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from organize import __version__
from organize.core.executor import execute, prepare_runlog, write_runlog
from organize.core.runner import build_plan, make_run_id
from organize.core.undo import undo as undo_run
from organize.errors import OrganizeError
from organize.recipes import find_recipe, list_recipes, load_recipe
from organize.userconfig import load_config, resolve_alias

_KIND_LABEL = {"mkdir": "폴더 생성", "move": "이동", "quarantine": "격리", "extract": "압축 해제"}


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
    return _preview_or_run(args, apply=False)


def _cmd_run(args) -> int:
    return _preview_or_run(args, apply=bool(args.apply))


def _preview_or_run(args, *, apply: bool) -> int:
    recipes_dir = repo_root() / "recipes"
    recipe = load_recipe(find_recipe(recipes_dir, args.recipe))
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
            elif not failed_roots:
                # root 가 여러 개면 roots[0] 만 알려주지 않는다(Task 18 리뷰
                # Important #1) — 전부 성공했을 때는 _cmd_undo 가 --root 없이
                # 레시피의 roots 를 전부 순회하므로 --recipe 하나로 끝난다.
                print(f"      organize undo --recipe {args.recipe}")
            else:
                # 일부 root 만 성공했을 때는 --recipe 를 권하지 않는다.
                # organize undo --recipe 는 레시피의 root 를 전부(실패한
                # root 포함) 순회하는데, _cmd_undo 의 그 반복문은 root 단위로
                # 격리돼 있지 않아(Task 19 로 넘긴 범위) 실패한 root 에서
                # "되돌릴 기록이 없습니다" 로 멈추면 그 뒤 root 는 시도조차
                # 안 된다 — 실측으로 확인했다. 성공한 root 만 하나씩 짚어
                # 줘야 전부 안전하게 되돌아간다.
                for r in applied_roots:
                    print(f"      organize undo --root {r}")
                print("      (처리되지 못한 폴더는 되돌릴 것이 없습니다: "
                      + ", ".join(str(r) for r in failed_roots) + ")")
        else:
            print("  되돌릴 수 있는 실행이 없습니다.")
    else:
        print("  실제로 실행하려면:")
        print(f"      organize run {args.recipe}{root_opt} --apply")
        if not args.verbose:
            print("\n  무엇이 어디로 가는지 전부 보려면:")
            print(f"      organize preview {args.recipe}{root_opt} --verbose")
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

    for root in roots:
        result = undo_run(root, args.run_id)
        print(f"■ {root}")
        print(f"  되돌림 {len(result.done)} · 실패 {len(result.failed)}")
        for row in result.failed:
            print(f"    실패  {row['why']}")
    return 0


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
