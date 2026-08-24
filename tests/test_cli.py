import json
from pathlib import Path

import pytest

from organize import cli


def old_file(path: Path, data: bytes = b"DATA") -> Path:
    """방금 만든 파일은 '작업 중' 으로 걸러지므로 수정시각을 한 시간 전으로 돌린다."""
    import os, time
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    past = time.time() - 3600
    os.utime(path, (past, past))
    return path


@pytest.fixture
def project(tmp_path, monkeypatch):
    """저장소 구조와 대상 폴더를 통째로 흉내낸다."""
    repo = tmp_path / "repo"
    (repo / "profiles").mkdir(parents=True)
    (repo / "recipes").mkdir()
    (repo / "profiles" / "desktop.toml").write_text(
        'name = "테스트"\n'
        '[[rules]]\n to = "01_Docs"\n ext = [".pdf", ".md"]\n'
        '[[rules]]\n to = "02_Media"\n ext = [".png"]\n'
        '[[rules]]\n to = "99_Unsorted"\n default = true\n', encoding="utf-8")

    work = tmp_path / "작업"
    work.mkdir()
    (repo / "recipes" / "t.json").write_text(json.dumps({
        "name": "테스트", "roots": [str(work)],
        "steps": [{"block": "route", "profile": "desktop"}],
    }, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(cli, "repo_root", lambda: repo)
    return repo, work


def test_preview_does_not_touch_files(project, capsys):
    _, work = project
    old_file(work / "보고서.pdf")
    assert cli.main(["preview", "t"]) == 0
    out = capsys.readouterr().out
    assert "이동 1" in out
    assert (work / "보고서.pdf").exists()
    assert not (work / "01_Docs").exists()


def test_preview_suggests_the_next_command(project, capsys):
    _, work = project
    old_file(work / "보고서.pdf")
    cli.main(["preview", "t"])
    assert "organize run t --apply" in capsys.readouterr().out


def test_run_without_apply_is_only_a_preview(project, capsys):
    _, work = project
    old_file(work / "보고서.pdf")
    assert cli.main(["run", "t"]) == 0
    assert (work / "보고서.pdf").exists()
    assert "--apply" in capsys.readouterr().out


def test_run_with_apply_moves_files(project, capsys):
    _, work = project
    old_file(work / "보고서.pdf")
    assert cli.main(["run", "t", "--apply"]) == 0
    assert (work / "01_Docs" / "보고서.pdf").read_bytes() == b"DATA"
    out = capsys.readouterr().out
    assert "organize undo" in out


def test_run_with_apply_writes_a_runlog(project, capsys):
    """execute() 는 실행 로그를 스스로 쓰지 않는다 — 부르는 쪽(CLI)이
    write_runlog(built, result) 을 따로 불러야 한다. CLI 가 그걸 빠뜨리면
    파일은 옮겨졌는데 되돌릴 방법이 없다. 그 계약을 여기서 직접 못박는다."""
    _, work = project
    old_file(work / "보고서.pdf")
    cli.main(["run", "t", "--apply"])
    capsys.readouterr()

    logs = list((work / ".organize" / "runs").glob("*.json"))
    assert len(logs) == 1, "run --apply 뒤에는 실행 기록이 정확히 하나 남아야 한다"

    data = json.loads(logs[0].read_text(encoding="utf-8"))
    assert any(d["kind"] == "move" for d in data["done"]), \
        "실행 기록에 실제로 옮긴 항목이 담겨 있어야 되돌릴 수 있다"


def test_undo_restores(project, capsys):
    _, work = project
    old_file(work / "보고서.pdf")
    cli.main(["run", "t", "--apply"])
    assert cli.main(["undo", "--root", str(work)]) == 0
    assert (work / "보고서.pdf").read_bytes() == b"DATA"


def test_unknown_recipe_is_a_friendly_error(project, capsys):
    assert cli.main(["preview", "없는것"]) == 1
    out = capsys.readouterr().out
    assert "없는것" in out and "t" in out


def test_verbose_lists_every_action(project, capsys):
    _, work = project
    old_file(work / "보고서.pdf")
    cli.main(["preview", "t", "--verbose"])
    assert "보고서.pdf" in capsys.readouterr().out
