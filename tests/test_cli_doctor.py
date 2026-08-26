import json
from pathlib import Path

import pytest

from organize import cli, userconfig
from organize.errors import OrganizeError


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


def test_paths_set_refuses_an_empty_value(project, capsys):
    """`organize paths --set 이름=` 을 그대로 저장하면 그 별칭이 **현재 작업
    폴더**를 가리킨다(`Path("")` 는 `.` 이다). 나중에 `--root @이름 --apply`
    로 쓰면 의도하지 않은 폴더를 정리해 버린다. 받아 주면 안 된다.
    """
    repo, _ = project
    assert cli.main(["paths", "--set", "보관="]) == 1
    assert "경로" in capsys.readouterr().out
    assert not (repo / "config.local.json").exists(), "거부했으면 저장도 하지 않는다"


def test_paths_set_refuses_a_blank_name(project):
    """이름 쪽이 비어도 마찬가지다 — 부를 수 없는 별칭이 생긴다."""
    assert cli.main(["paths", "--set", "=/tmp/어딘가"]) == 1


def test_doctor_admits_it_did_not_look_inside_hidden_folders(project, capsys):
    """숨김 폴더를 안 봤으면 "없음(확인함)" 이라고만 말하면 안 된다.

    목적지 폴더 이름을 숨김(`to = ".백업"`)으로 적는 것을 막는 코드가 없다.
    그러면 정리 결과가 숨김 폴더로 가는데 doctor 는 그 안을 안 본다. 그러고도
    "없음" 이라고 하면 **확인 안 한 것을 됐다고 말하는 것**이다 — 이 프로젝트가
    여섯 번 물린 고질병이다. 숨김 폴더는 계속 건너뛰되(안 그러면 남의
    프로그램 파일 1081개가 다시 쏟아진다) 안 봤다는 사실은 밝힌다.
    """
    _, work = project
    (work / ".organize" / "runs").mkdir(parents=True)

    cli.main(["doctor"])
    out = capsys.readouterr().out
    assert "숨김" in out, "숨김 폴더를 안 봤다는 사실이 화면에 있어야 한다"


def test_doctor_also_checks_raw_paths_written_in_recipes(project, capsys):
    """레시피의 대상 폴더가 `@별칭` 이 아니라 생짜 경로면 doctor 가 아예 안 봤다.

    그 폴더야말로 사용자가 실제로 정리하는 곳이다.
    """
    repo, work = project
    생짜 = work.parent / "생짜폴더"
    (생짜 / ".organize" / "runs").mkdir(parents=True)
    (생짜 / "잔해.pdf").touch()
    (repo / "recipes" / "t.json").write_text(json.dumps({
        "name": "테스트", "roots": [str(생짜)],
        "steps": [{"block": "route", "profile": "desktop"}],
    }, ensure_ascii=False), encoding="utf-8")

    cli.main(["doctor"])
    assert "잔해.pdf" in capsys.readouterr().out


def test_do_suggestion_survives_a_value_with_a_space(project, capsys):
    """제안한 명령을 그대로 복사해 붙였을 때 깨지면 안 된다."""
    _, work = project
    old = work / "보고서.pdf"
    old.write_bytes(b"DATA")
    import os, time
    past = time.time() - 3600
    os.utime(old, (past, past))

    cli.main(["do", "route", "--profile", "desktop", "--dest", "내 보관함",
              "--root", str(work)])
    out = capsys.readouterr().out
    suggested = [ln for ln in out.splitlines() if "organize do" in ln]
    assert suggested
    for line in suggested:
        assert '"내 보관함"' in line or "'내 보관함'" in line, \
            f"공백이 든 값이 따옴표 없이 나갔다: {line.strip()}"


def test_doctor_reports_records_it_could_not_read(project, capsys):
    """Critical #3 — 못 읽은 기록을 조용히 건너뛰면 doctor 가 "없음 (확인함)"
    이라고 답한다. 사용자가 그 사실을 알 방법은 doctor 뿐이다."""
    _, work = project
    runs = work / ".organize" / "runs"
    runs.mkdir(parents=True)
    (runs / "20260101-000000.json").write_text('{"run_id": "20260101-0', encoding="utf-8")

    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "20260101-000000.json" in out, "어느 파일인지 알려줘야 한다"
    assert "읽지" in out or "손상" in out


def test_doctor_says_exactly_what_stops_working_without_pillow(project, capsys, monkeypatch):
    """Important #6 — Pillow 가 없으면 `photos` 프로파일의 사진/캡처 규칙이
    **하나도 안 걸린다.** 그런데 doctor 는 "파일명과 수정시각으로 대체합니다"
    라고만 했다 — 그 대체는 `by_date` 에만 참이고 `route --profile photos` 에는
    대체가 없다. 사용자는 사진 정리가 아무것도 안 하는 이유를 알 길이 없다."""
    import sys
    monkeypatch.setitem(sys.modules, "PIL", None)      # import PIL 이 ImportError 를 낸다

    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "Pillow          없음" in out
    assert "photos" in out
    assert "캡처" in out


def test_doctor_says_folder_missing_not_file_missing(project, tmp_path, capsys, monkeypatch):
    """Minor #6 — 폴더가 아예 없을 때와 파일이 0개일 때를 나란히 찍는데
    "파일 없음!" 이 후자("파일 0")로 읽힌다. "폴더 없음" 이 맞다."""
    _, work = project
    gone = tmp_path / "없는폴더"
    monkeypatch.setattr(userconfig, "builtin_path",
                        lambda name: work if name == "downloads"
                        else (gone if name == "desktop" else None))
    cli.main(["doctor"])
    out = capsys.readouterr().out
    assert "폴더 없음" in out
    assert "파일 없음!" not in out


# --- 마지막 라운드 — `do --root <폴더>` 로 쓴 폴더를 doctor 가 못 봤다.
# 실행이 끊기면 사용자가 그 사실을 알 방법이 한 군데도 없었다. ---


def test_doctor_sees_a_folder_that_was_only_touched_by_do_root(project, tmp_path, capsys):
    """레시피에 없는 폴더라도 `--apply` 를 돌렸으면 나중에 doctor 가 봐야 한다.

    **대상 폴더는 어느 별칭도 아니어야 한다** — 픽스처의 `work` 는 `@downloads`
    라서 doctor 가 원래 보던 폴더다. 그걸로 시험하면 새 동작을 하나도 안 덮는다.
    """
    import os, time
    outside = tmp_path / "레시피에없는폴더"
    outside.mkdir()
    f = outside / "a.pdf"
    f.write_bytes(b"DATA")
    past = time.time() - 3600
    os.utime(f, (past, past))

    assert cli.main(["doctor"]) == 0
    assert str(outside) not in capsys.readouterr().out, \
        "아직 정리한 적 없는 폴더는 doctor 가 볼 이유가 없다"

    assert cli.main(["do", "route", "--root", str(outside),
                     "--profile", "desktop", "--apply"]) == 0
    capsys.readouterr()

    # 그 실행이 중간에 끊긴 것처럼 뼈대만 남긴다
    (outside / ".organize" / "runs" / "20260101-000000.json").write_text(json.dumps({
        "run_id": "20260101-000000", "root": str(outside), "done": [], "failed": [],
        "stale": [], "complete": False,
    }, ensure_ascii=False), encoding="utf-8")

    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert str(outside) in out, "정리를 돌린 폴더는 doctor 가 볼 수 있어야 한다"
    assert "20260101-000000" in out


def test_doctor_accepts_an_explicit_root(project, tmp_path, capsys):
    """레시피에 없고 기억에도 없는 폴더를 직접 짚어서 점검할 수 있어야 한다."""
    other = tmp_path / "직접짚은폴더"
    (other / ".organize" / "runs").mkdir(parents=True)
    (other / ".organize" / "runs" / "20260101-000000.json").write_text(json.dumps({
        "run_id": "20260101-000000", "root": str(other), "done": [], "failed": [],
        "stale": [], "complete": False,
    }, ensure_ascii=False), encoding="utf-8")

    assert cli.main(["doctor", "--root", str(other)]) == 0
    out = capsys.readouterr().out
    assert "20260101-000000" in out


def test_doctor_and_paths_still_work_when_the_config_has_pins(
        project, tmp_path, capsys, monkeypatch):
    """I-2 — 진단 도구가 진단할 내용을 못 띄우고 자기가 죽으면 안 된다."""
    repo, work = project
    # 내장 별칭이 전부 풀리게 해 둔다 — 이 테스트가 보는 것은 pins 뿐이다.
    monkeypatch.setattr(userconfig, "builtin_path",
                        lambda name: work if name == "downloads" else tmp_path / name)
    (repo / "config.local.json").write_text('{"pins": ["세금.pdf"]}', encoding="utf-8")

    assert cli.main(["doctor"]) == 0
    assert "pins" in capsys.readouterr().out
    assert cli.main(["paths"]) == 0
    assert "pins" in capsys.readouterr().out


def test_doctor_survives_a_circular_alias_and_still_runs_every_check(
        project, tmp_path, capsys, monkeypatch):
    """**doctor 는 복구 도구다.** 설정 한 줄이 깨졌다고 진단이 죽으면 안 된다.

    손편집 설정에 `{"desktop": ["@desktop"]}` 을 넣으면 그 자리에서 죽어,
    0바이트 잔해 점검·미완료 기록 점검이 **실행조차 되지 않았다.** 실측한 결함이다.
    """
    repo, work = project
    monkeypatch.setattr(userconfig, "builtin_path",
                        lambda name: work if name == "downloads" else tmp_path / name)
    (repo / "config.local.json").write_text(
        '{"paths": {"desktop": ["@desktop"], "보관": "%s"}}' % (tmp_path / "보관"),
        encoding="utf-8")

    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "돌고" in out, "어느 이름이 문제인지 조용히 넘어가면 안 된다"
    assert "@desktop" in out
    assert "보관" in out, "문제 뒤의 줄도 계속 나와야 한다"
    assert "0바이트" in out, "뒤쪽 점검이 통째로 안 도는 것이 이 결함의 핵심이었다"
    assert "완료되지 않은 실행 기록" in out


def test_paths_survives_a_circular_alias_and_lists_every_name(
        project, tmp_path, capsys, monkeypatch):
    """`organize paths` 가 **첫 줄에서** 죽던 자리."""
    repo, work = project
    monkeypatch.setattr(userconfig, "builtin_path",
                        lambda name: work if name == "downloads" else tmp_path / name)
    (repo / "config.local.json").write_text(
        '{"paths": {"desktop": ["@desktop"], "보관": "%s"}}' % (tmp_path / "보관"),
        encoding="utf-8")

    assert cli.main(["paths"]) == 0
    out = capsys.readouterr().out
    assert "@downloads" in out, "첫 줄에서 죽으면 안 된다"
    assert "돌고" in out and "@desktop" in out
    assert "보관" in out
    줄머리 = [ln for ln in out.splitlines() if ln.startswith("  @desktop")]
    assert len(줄머리) == 1, f"같은 이름을 두 번 찍지 않는다: {줄머리}"
