import json
from pathlib import Path

import pytest

from organize import cli, userconfig


@pytest.fixture
def project(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "profiles").mkdir(parents=True)
    (repo / "recipes").mkdir()
    (repo / "profiles" / "desktop.toml").write_text(
        'name = "테스트"\n[[rules]]\n to = "01_Docs"\n ext = [".pdf"]\n', encoding="utf-8")
    work = tmp_path / "작업"
    work.mkdir()
    import os, time
    a = work / "a.pdf"
    a.write_bytes(b"DATA")
    past = time.time() - 3600
    os.utime(a, (past, past))
    (repo / "recipes" / "t.json").write_text(json.dumps({
        "name": "테스트", "roots": ["@archive"],
        "steps": [{"block": "route", "profile": "desktop"}],
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cli, "repo_root", lambda: repo)
    monkeypatch.setattr(userconfig, "builtin_path", lambda name: work if name == "downloads" else None)
    return repo, work


def test_doctor_reports_python_and_folders(project, capsys):
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "Python" in out
    assert "다운로드" in out or "downloads" in out


def test_doctor_shows_file_counts(project, capsys):
    """경로 문자열만으로는 맞는 폴더인지 알 수 없다. 개수를 보여줘야 한다."""
    cli.main(["doctor"])
    assert "1" in capsys.readouterr().out


def test_doctor_warns_about_aliases_a_recipe_needs(project, capsys):
    cli.main(["doctor"])
    out = capsys.readouterr().out
    assert "archive" in out
    assert "organize paths --set" in out


def test_doctor_exit_code_is_zero_even_with_warnings(project):
    assert cli.main(["doctor"]) == 0


def test_paths_set_writes_local_config(project, tmp_path, capsys):
    repo, _ = project
    target = tmp_path / "보관"
    target.mkdir()
    assert cli.main(["paths", "--set", f"archive={target}"]) == 0
    saved = json.loads((repo / "config.local.json").read_text(encoding="utf-8"))
    assert saved["paths"]["archive"] == str(target)


def test_paths_set_rejects_bad_format(project):
    assert cli.main(["paths", "--set", "형식없음"]) == 1


def test_list_shows_recipes_and_profiles(project, capsys):
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "t" in out and "desktop" in out


def test_do_runs_one_block_as_preview(project, capsys):
    _, work = project
    assert cli.main(["do", "route", "--root", str(work), "--profile", "desktop"]) == 0
    out = capsys.readouterr().out
    assert "이동 1" in out
    assert (work / "a.pdf").exists()          # 미리보기이므로 그대로


def test_do_with_apply_moves(project):
    _, work = project
    assert cli.main(["do", "route", "--root", str(work), "--profile", "desktop", "--apply"]) == 0
    assert (work / "01_Docs" / "a.pdf").exists()


def test_do_only_filters_by_extension(project, capsys):
    _, work = project
    import os, time
    b = work / "b.png"
    b.write_bytes(b"IMG")
    past = time.time() - 3600
    os.utime(b, (past, past))
    cli.main(["do", "route", "--root", str(work), "--profile", "desktop", "--only", "*.pdf"])
    assert "이동 1" in capsys.readouterr().out


# ── 컨트롤러 지시 사항 ──────────────────────────────────────────────
# 브리프에는 없지만 Task 14·18 이후에 생긴 사정 때문에 doctor 에 반드시
# 있어야 하는 두 가지. 둘 다 "찾아서 알리기" 만 한다 — 지우거나 손대지 않는다.

def test_doctor_finds_zero_byte_leftovers(project, capsys):
    """claim_path 가 강제 종료로 남긴 0바이트 잔해를 doctor 가 찾아 알려야 한다.
    지우면 안 된다 — 사용자가 일부러 만든 빈 파일일 수도 있다."""
    _, work = project
    (work / ".organize" / "runs").mkdir(parents=True)   # 이 폴더에서 정리를 돌린 적이 있다
    leftover = work / "leftover.hwp"
    leftover.touch()
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "leftover.hwp" in out
    assert leftover.exists()                  # 찾기만 하고 지우지 않는다


def test_doctor_says_none_found_when_no_zero_byte_files(project, capsys):
    """확인은 했지만 없었다 — '확인 안 함' 과 구분되게 정직하게 알린다."""
    cli.main(["doctor"])
    out = capsys.readouterr().out
    assert "0바이트" in out


def test_doctor_reports_incomplete_runlog(project, capsys):
    """prepare_runlog 가 남긴 complete:false 기록은 undo 가 거부한다.
    doctor 밖에는 사용자가 그 사실을 알 방법이 없다."""
    _, work = project
    runs = work / ".organize" / "runs"
    runs.mkdir(parents=True)
    (runs / "20260101-000000.json").write_text(json.dumps({
        "run_id": "20260101-000000", "root": str(work),
        "started_at": "2026-01-01T00:00:00",
        "done": [], "failed": [], "stale": [], "complete": False,
    }, ensure_ascii=False), encoding="utf-8")
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "20260101-000000" in out


def test_do_preview_suggestion_keeps_profile_and_only(project, capsys):
    """do 의 '실제로 실행하려면' 제안에서 --profile/--only 를 빠뜨리면, 미리보기
    때 걸러졌던 파일이 사용자가 그대로 복사한 명령에서는 안 걸러진 채 옮겨진다
    — 브리프의 label=args.block 그대로는 이 사고를 못 막아 범위를 넓혔다."""
    _, work = project
    cli.main(["do", "route", "--root", str(work), "--profile", "desktop", "--only", "*.pdf"])
    out = capsys.readouterr().out
    assert "--profile desktop" in out
    assert "--only" in out


def test_doctor_does_not_warn_about_complete_runlog(project, capsys):
    """정상 종료된 기록(complete: true)까지 잡으면 잡음이 되어 진짜 경고가 묻힌다."""
    _, work = project
    runs = work / ".organize" / "runs"
    runs.mkdir(parents=True)
    (runs / "20260101-000000.json").write_text(json.dumps({
        "run_id": "20260101-000000", "root": str(work),
        "finished_at": "2026-01-01T00:00:00",
        "done": [], "failed": [], "stale": [], "complete": True,
    }, ensure_ascii=False), encoding="utf-8")
    cli.main(["doctor"])
    out = capsys.readouterr().out
    assert "20260101-000000" not in out


def test_doctor_only_looks_where_organize_has_actually_run(project, capsys):
    """0바이트 파일을 **아무 폴더에서나 찾으면 안 된다.**

    실제로 홈 폴더를 통째로 훑게 두었더니 1081개가 나왔다 — `LOCK`, `LOG`,
    `-journal`, 빈 `__init__.py` 처럼 **다른 프로그램이 정상적으로 만든** 빈
    파일들이었다. 그걸 "지우세요" 라고 안내하면 남의 프로그램을 망가뜨린다.

    우리가 찾는 것은 `claim_path` 가 강제 종료로 남긴 잔해뿐이다. 그건
    `execute()` 안에서만 생기고, `prepare_runlog` 이 그 **전에** 이미
    `.organize/` 를 만든다. 그러니 **정리를 돌린 적 있는 폴더**만 보면
    빠뜨리는 것 없이 소음만 걷어낼 수 있다.
    """
    _, work = project
    (work / "__init__.py").touch()          # 아직 정리를 돌린 적 없는 폴더다

    cli.main(["doctor"])
    assert "__init__.py" not in capsys.readouterr().out, \
        "정리를 돌린 적 없는 폴더까지 뒤지면 소음만 나온다"

    # 같은 폴더라도 정리를 돌린 적이 있으면 본다
    (work / ".organize" / "runs").mkdir(parents=True)
    cli.main(["doctor"])
    assert "__init__.py" in capsys.readouterr().out


def test_doctor_skips_hidden_folders_when_hunting_leftovers(project, capsys):
    """숨김 폴더(.cache 등)는 뒤지지 않는다 — 전부 남의 프로그램 것이다."""
    _, work = project
    (work / ".organize" / "runs").mkdir(parents=True)
    (work / ".cache").mkdir()
    (work / ".cache" / "남의LOCK").touch()

    cli.main(["doctor"])
    assert "남의LOCK" not in capsys.readouterr().out


def test_doctor_does_not_flood_the_screen_with_leftovers(project, capsys):
    """수십 개가 나와도 화면을 다 덮지 않는다 — 몇 개만 보이고 총 개수를 알린다."""
    _, work = project
    (work / ".organize" / "runs").mkdir(parents=True)
    for i in range(40):
        (work / f"빈파일{i:02d}.txt").touch()

    cli.main(["doctor"])
    out = capsys.readouterr().out

    shown = sum(1 for line in out.splitlines() if "빈파일" in line)
    assert shown <= 12, f"화면에 {shown}줄이나 찍혔다 — 너무 많다"
    assert "40" in out, "총 몇 개인지는 알려야 한다"


def test_doctor_never_tells_you_to_just_delete_them(project, capsys):
    """'필요 없으면 지우세요' 는 위험한 안내다 — 남의 프로그램 파일일 수 있다."""
    _, work = project
    (work / ".organize" / "runs").mkdir(parents=True)
    (work / "빈파일.txt").touch()

    cli.main(["doctor"])
    out = capsys.readouterr().out
    assert "지워 주세요" not in out and "지우세요" not in out
