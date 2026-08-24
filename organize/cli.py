"""명령줄. 출력 끝에는 항상 다음에 칠 명령어를 그대로 보여준다."""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from organize import __version__
from organize.core.executor import execute, write_runlog
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

    for root in roots:
        print(f"\n■ {root}")
        if not root.is_dir():
            print("  폴더를 찾을 수 없어 건너뜁니다.")
            continue

        built = build_plan(root, recipe.steps, today=date.today(), run_id=run_id,
                           profiles_dir=repo_root() / "profiles")
        _print_plan(built, args.verbose)

        if not apply:
            continue

        result = execute(built)
        log = write_runlog(built, result)
        print(f"\n  완료. 처리 {len(result.done)} · 실패 {len(result.failed)}"
              f" · 건너뜀 {len(result.stale)}")
        print(f"  기록: {log}")
        for row in result.failed:
            print(f"    실패  {Path(row['src']).name} — {row['why']}")

    print()
    if apply:
        print("  되돌리려면:")
        print(f"      organize undo --root {roots[0]}")
    else:
        print("  실제로 실행하려면:")
        print(f"      organize run {args.recipe} --apply")
        if not args.verbose:
            print("\n  무엇이 어디로 가는지 전부 보려면:")
            print(f"      organize preview {args.recipe} --verbose")
    return 0


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
