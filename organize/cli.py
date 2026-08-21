import argparse
import sys

from organize import __version__
from organize.errors import OrganizeError

USAGE = """사용 가능한 명령

  organize preview <레시피>          미리보기 (파일을 건드리지 않음)
  organize run <레시피> --apply      실행
  organize undo                      되돌리기
  organize doctor                    환경 점검

자세히 보려면:
    organize <명령> --help
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="organize", add_help=True)
    p.add_argument("--version", action="store_true", help="버전 출력")
    p.add_argument("command", nargs="?", help="실행할 명령")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:            # argparse 가 종료하려 할 때 코드만 넘긴다
        return int(e.code or 0)

    if args.version:
        print(f"organize {__version__}")
        return 0

    if args.command is None:
        print(USAGE)
        return 0

    try:
        print(f"'{args.command}' 는 아직 없는 명령입니다.\n")
        print(USAGE)
        return 2
    except OrganizeError as e:
        print(f"{e.message}")
        if e.hint:
            print(f"\n{e.hint}")
        return 1
