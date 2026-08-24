import pytest
from organize.cli import main
from organize.errors import OrganizeError


def test_version_prints_and_exits_zero(capsys):
    code = main(["--version"])
    out = capsys.readouterr().out
    assert code == 0
    assert "organize" in out


def test_no_args_shows_help_and_exits_zero(capsys):
    code = main([])
    out = capsys.readouterr().out
    assert code == 0
    assert "preview" in out          # 사용 가능한 명령이 안내되어야 한다
    assert "run" in out
    assert "undo" in out


def test_unknown_command_is_friendly(capsys):
    code = main(["아무거나"])
    captured = capsys.readouterr()   # out+err 는 한 번만 읽을 수 있다
    combined = captured.out + captured.err
    assert code == 2                 # argparse 가 잘못된 서브커맨드로 돌려주는 종료 코드
    # 완전히 모르는 명령은 argparse 의 표준 오류로 처리한다 — 어떤 명령을
    # 쓸 수 있는지는 여전히 안내되어야 한다(무엇을 치면 되는지 알 수 있게).
    assert "아무거나" in combined
    assert "preview" in combined and "run" in combined and "undo" in combined


def test_organize_error_carries_hint():
    e = OrganizeError("경로를 찾을 수 없습니다.", hint="organize paths 로 확인하세요.")
    assert e.hint == "organize paths 로 확인하세요."
    assert "경로를 찾을 수 없습니다." in str(e)
