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


def test_unknown_command_is_friendly(capsys):
    code = main(["아무거나"])
    err = capsys.readouterr().out + capsys.readouterr().err
    assert code != 0


def test_organize_error_carries_hint():
    e = OrganizeError("경로를 찾을 수 없습니다.", hint="organize paths 로 확인하세요.")
    assert e.hint == "organize paths 로 확인하세요."
    assert "경로를 찾을 수 없습니다." in str(e)
