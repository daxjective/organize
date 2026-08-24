import json
import os
import zipfile
from datetime import date
from pathlib import Path

import pytest

from organize.core.action import Action, Plan
from organize.core.executor import execute, prepare_runlog, write_runlog
from organize.core.runner import BuiltPlan
from organize.errors import OrganizeError

TODAY = date(2026, 8, 21)


def built_for(root, actions, snapshot=None):
    return BuiltPlan(root=root, run_id="r1", plan=Plan(actions=list(actions)),
                     snapshot=snapshot or {})


def test_mkdir_creates_the_folder(tmp_path):
    b = built_for(tmp_path, [Action("mkdir", None, tmp_path / "01_Docs", "폴더", "route")])
    r = execute(b)
    assert (tmp_path / "01_Docs").is_dir()
    assert len(r.done) == 1 and not r.failed


def test_move_moves_the_file(tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"DATA")
    b = built_for(tmp_path, [Action("move", src, tmp_path / "01_Docs" / "a.pdf", "확장자", "route")])
    execute(b)
    assert (tmp_path / "01_Docs" / "a.pdf").read_bytes() == b"DATA"
    assert not src.exists()


def test_chained_moves_follow_a_rename(tmp_path):
    """첫 이동에서 이름이 바뀌면 두 번째 이동의 원본도 따라가야 한다."""
    (tmp_path / "01_Docs").mkdir()
    (tmp_path / "01_Docs" / "a.pdf").write_bytes(b"OLDFILE")
    src = tmp_path / "a.pdf"
    src.write_bytes(b"NEWFILE")
    b = built_for(tmp_path, [
        Action("move", src, tmp_path / "01_Docs" / "a.pdf", "1차", "route"),
        Action("move", tmp_path / "01_Docs" / "a.pdf",
               tmp_path / "01_Docs" / "2023" / "a.pdf", "2차", "by_date"),
    ])
    r = execute(b)
    assert not r.failed
    # 1차에서 a_(1).pdf 로 밀렸지만, 2차 이동은 그 파일을 따라가 최종적으로 a.pdf 가 된다
    assert (tmp_path / "01_Docs" / "2023" / "a.pdf").read_bytes() == b"NEWFILE"
    assert (tmp_path / "01_Docs" / "a.pdf").read_bytes() == b"OLDFILE"
    assert not (tmp_path / "01_Docs" / "a_(1).pdf").exists()


def test_quarantine_moves_into_the_trash_folder(tmp_path):
    src = tmp_path / "중복.pdf"
    src.write_bytes(b"x")
    trash = tmp_path / ".organize" / "trash" / "r1"
    b = built_for(tmp_path, [Action("quarantine", src, trash / "중복.pdf", "중복", "dedup")])
    execute(b)
    assert (trash / "중복.pdf").exists()
    assert not src.exists()


def test_quarantine_writes_a_manifest(tmp_path):
    src = tmp_path / "중복.pdf"
    src.write_bytes(b"x")
    trash = tmp_path / ".organize" / "trash" / "r1"
    b = built_for(tmp_path, [Action("quarantine", src, trash / "중복.pdf", "중복", "dedup")])
    execute(b)
    manifest = json.loads((trash / "_manifest.json").read_text(encoding="utf-8"))
    assert manifest[0]["from"] == str(src)


def test_extract_pulls_the_named_member(tmp_path):
    z = tmp_path / "자료.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("안쪽/문서.pdf", b"ZIPPED")
    b = built_for(tmp_path, [Action("extract", z, tmp_path / "문서.pdf",
                                    "꺼냄", "unzip", member="안쪽/문서.pdf")])
    execute(b)
    assert (tmp_path / "문서.pdf").read_bytes() == b"ZIPPED"


def test_changed_file_is_reported_as_stale_and_not_moved(tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"SHORT")
    snapshot = {str(src): (999, 0.0)}                   # 계획 시점과 크기가 다르다
    b = built_for(tmp_path, [Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route")],
                  snapshot)
    r = execute(b)
    assert src.exists()
    assert not r.done and len(r.stale) == 1
    assert "바뀌었" in r.stale[0]["why"]


def test_one_failure_does_not_stop_the_rest(tmp_path):
    ok = tmp_path / "있음.pdf"
    ok.write_bytes(b"x")
    b = built_for(tmp_path, [
        Action("move", tmp_path / "없음.pdf", tmp_path / "01_Docs" / "없음.pdf", "이동", "route"),
        Action("move", ok, tmp_path / "01_Docs" / "있음.pdf", "이동", "route"),
    ])
    r = execute(b)
    assert len(r.failed) == 1
    assert (tmp_path / "01_Docs" / "있음.pdf").exists()


def test_runlog_is_written_and_readable(tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"x")
    b = built_for(tmp_path, [Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route")])
    r = execute(b)
    log_path = write_runlog(b, r)
    assert log_path == tmp_path / ".organize" / "runs" / "r1.json"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["run_id"] == "r1"
    assert data["done"][0]["kind"] == "move"
    assert data["done"][0]["final"].endswith("a.pdf")


# ---------------------------------------------------------------------------
# 아래는 브리프 Step 1 에는 없지만, 브리프 본문과 컨트롤러 지시가 "반드시
# 테스트할 것"으로 못박은 항목들이다. 격리 폴더 이름 충돌, 심볼릭 링크를
# 통한 root 탈출, 부분 실패 주입(권한 거부/디스크 오류/사라진 파일),
# 그리고 "hint 자리에 파이썬 예외 원문을 넣지 않는다"는 전역 규칙 위반 여부.
# ---------------------------------------------------------------------------


def test_quarantine_name_collision_both_files_survive(tmp_path):
    """target 이 다른 두 dedup step 이 같은 이름의 파일을 치우면 dst 가 같아진다.
    미리보기와 실제 이름이 갈릴 수 있지만, 두 파일 다 남아야 하고 실행 로그의
    `final` 로 undo 가 둘 다 되돌릴 수 있는 실제 위치를 알 수 있어야 한다."""
    src1 = tmp_path / "a" / "중복.pdf"
    src1.parent.mkdir()
    src1.write_bytes(b"AAA")
    src2 = tmp_path / "b" / "중복.pdf"
    src2.parent.mkdir()
    src2.write_bytes(b"BBB")
    trash = tmp_path / ".organize" / "trash" / "r1"
    dst = trash / "중복.pdf"
    b = built_for(tmp_path, [
        Action("quarantine", src1, dst, "중복1", "dedup"),
        Action("quarantine", src2, dst, "중복2", "dedup"),
    ])
    r = execute(b)
    assert not r.failed
    assert len(r.done) == 2
    finals = {Path(d["final"]) for d in r.done}
    assert len(finals) == 2                    # 서로 다른 자리를 잡았다
    contents = {p.read_bytes() for p in finals}
    assert contents == {b"AAA", b"BBB"}         # 파일을 잃지 않았다
    assert not src1.exists() and not src2.exists()
    manifest = json.loads((trash / "_manifest.json").read_text(encoding="utf-8"))
    assert len(manifest) == 2


def test_symlinked_dest_folder_is_blocked(tmp_path, tmp_path_factory):
    """블록의 dest_folder() 는 문자열만 정규화하므로 '보관' 이 root 밖을
    가리키는 심볼릭 링크면 통과한다. 실행 직전에 실제 경로를 확인해서 막아야 한다."""
    outside = tmp_path_factory.mktemp("outside")
    link = tmp_path / "보관"
    link.symlink_to(outside, target_is_directory=True)
    src = tmp_path / "a.pdf"
    src.write_bytes(b"x")
    b = built_for(tmp_path, [Action("move", src, link / "a.pdf", "이동", "route")])
    r = execute(b)
    assert not (outside / "a.pdf").exists()     # 링크 너머로 나가지 않았다
    assert src.exists()                          # 옮겨지지 않고 원본이 남는다
    assert len(r.failed) == 1


def test_symlinked_quarantine_folder_is_blocked(tmp_path, tmp_path_factory):
    """격리 폴더 경로 자체가 링크로 root 밖을 가리켜도 막는다."""
    outside = tmp_path_factory.mktemp("outside2")
    link = tmp_path / "링크trash"
    link.symlink_to(outside, target_is_directory=True)
    src = tmp_path / "중복.pdf"
    src.write_bytes(b"x")
    b = built_for(tmp_path, [Action("quarantine", src, link / "중복.pdf", "중복", "dedup")])
    r = execute(b)
    assert not (outside / "중복.pdf").exists()
    assert src.exists()
    assert len(r.failed) == 1


def test_file_deleted_after_scan_is_reported_as_stale_not_crash(tmp_path):
    """스캔 이후 사람이 파일을 지운 경우 — 실패가 아니라 stale 로 조용히 보고해야 한다."""
    src = tmp_path / "a.pdf"
    src.write_bytes(b"x")
    snapshot = {str(src): (1, 0.0)}    # 스캔 당시엔 있었다(크기 다르게 기록)
    src.unlink()                       # 실행 전에 사라짐
    b = built_for(tmp_path, [Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route")],
                  snapshot)
    r = execute(b)
    assert not r.done and not r.failed
    assert len(r.stale) == 1


def test_permission_denied_leaves_source_untouched(tmp_path):
    """권한 거부를 실제로 주입한다 — move_file 의 OrganizeError 가 executor 를
    깨뜨리지 않고 실패로 기록되며, 원본 파일은 그대로 남아야 한다."""
    if os.name == "nt":
        pytest.skip("permission bits don't apply the same way on Windows")
    if os.geteuid() == 0:
        pytest.skip("root 로 실행 중이라 권한 검사가 의미 없다")
    src = tmp_path / "a.pdf"
    src.write_bytes(b"x")
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)                # 쓰기 금지
    try:
        b = built_for(tmp_path, [Action("move", src, locked / "sub" / "a.pdf", "이동", "route")])
        r = execute(b)
        assert src.exists()
        assert len(r.failed) == 1
    finally:
        locked.chmod(0o700)


def test_disk_error_injected_via_move_file_is_recorded_and_does_not_stop_the_rest(
        tmp_path, monkeypatch):
    """move_file 이 던지는 OrganizeError(디스크 오류 등을 흉내)가 그 항목만
    실패시키고 나머지 작업은 계속 진행되는지 확인한다."""
    import organize.core.executor as executor_mod

    def boom(src, dst):
        raise OrganizeError("디스크에 쓰지 못했습니다(시뮬레이션)", hint="디스크 공간 확인")

    monkeypatch.setattr(executor_mod, "move_file", boom)

    bad = tmp_path / "a.pdf"
    bad.write_bytes(b"x")
    b = built_for(tmp_path, [Action("move", bad, tmp_path / "01_Docs" / "a.pdf", "이동", "route")])
    r = execute(b)
    assert len(r.failed) == 1
    assert bad.exists()                # 원본은 그대로 남는다


# --- 수정 라운드 1/5: Task 16 리뷰 Minor #1 — hint 가 실패 로그에서 버려지지 않는지 ---


def test_organize_error_hint_is_kept_in_the_failed_entry(tmp_path):
    """OrganizeError 의 hint(사람이 다음에 뭘 하면 되는지)가 실행 결과에서
    사라지면 안 된다 — why 만 남기고 버리던 것이 결함이었다."""
    missing = tmp_path / "없음.pdf"           # 계획 시점 이후 사라진 것으로 흉내
    b = built_for(tmp_path, [
        Action("move", missing, tmp_path / "01_Docs" / "없음.pdf", "이동", "route"),
    ])
    r = execute(b)
    assert len(r.failed) == 1
    assert r.failed[0]["hint"]
    assert "미리보기" in r.failed[0]["hint"]


def test_os_error_message_never_leaks_raw_python_exception_text(tmp_path, monkeypatch):
    """전역 규칙: 오류 문구에 파이썬 예외 원문을 그대로 넣지 않는다.
    strerror 가 없는 OSError 를 주입해, 그 원문이 사용자 메시지에 새지 않는지 확인한다."""
    secret = "OSError raw internal detail 0xdeadbeef"

    def boom(self, *a, **k):
        raise OSError(secret)

    monkeypatch.setattr(Path, "mkdir", boom)
    b = built_for(tmp_path, [Action("mkdir", None, tmp_path / "새폴더", "폴더", "route")])
    r = execute(b)
    assert len(r.failed) == 1
    assert secret not in r.failed[0]["why"]
    assert secret not in json.dumps(r.failed)


def test_extract_missing_member_is_reported_and_leaves_no_stray_file(tmp_path):
    """압축 안 항목이 미리보기 이후 사라진 경우(zip 이 바뀜) — 전체 실행이
    죽지 않고 그 항목만 실패로 기록돼야 하며, claim_path 로 잡아 둔 빈 자리가
    치워지지 않은 채 남아서는 안 된다."""
    z = tmp_path / "자료.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("있음.txt", b"DATA")
    dst = tmp_path / "문서.pdf"
    b = built_for(tmp_path, [Action("extract", z, dst, "꺼냄", "unzip", member="없는이름.pdf")])
    r = execute(b)
    assert len(r.failed) == 1
    assert not dst.exists()            # claim_path 로 잡아 둔 빈 파일이 남지 않았다


def test_extract_corrupt_zip_is_reported_and_leaves_no_stray_file(tmp_path):
    """zip 자체가 미리보기 이후 깨진 경우도 실패로만 기록되고 실행 전체가
    죽지 않아야 한다."""
    z = tmp_path / "자료.zip"
    z.write_bytes(b"NOT A ZIP FILE")
    dst = tmp_path / "문서.pdf"
    b = built_for(tmp_path, [Action("extract", z, dst, "꺼냄", "unzip", member="아무거나")])
    r = execute(b)
    assert len(r.failed) == 1
    assert not dst.exists()


# --- 수정 라운드 1(Task 18 리뷰) — Critical #1: write_runlog 가 실패하면 방금
# 옮긴 파일이 영원히 미아가 된다. 핵심은 "아무것도 건드리기 전에 실패하게
# 만드는 것" — prepare_runlog 가 execute() 앞에서 자리를 미리 마련한다. ---


def test_prepare_runlog_raises_organize_error_when_runs_path_is_blocked(tmp_path):
    """`.organize/runs` 자리에 파일이 이미 있으면(디스크 풀/권한 거부와 같은
    부류) execute() 를 부르기도 전에 한국어 오류로 막혀야 한다. 여기서
    막히면 파일이 하나도 안 움직인 상태라는 게 이 함수의 존재 이유다."""
    organize_dir = tmp_path / ".organize"
    organize_dir.mkdir()
    (organize_dir / "runs").write_text("나는 파일입니다", encoding="utf-8")

    b = built_for(tmp_path, [])
    with pytest.raises(OrganizeError) as ex:
        prepare_runlog(b)
    # 순정 파이썬 예외 원문이 새면 안 된다(전역 규칙).
    assert "FileExistsError" not in (ex.value.message + (ex.value.hint or ""))
    assert "Errno" not in (ex.value.message + (ex.value.hint or ""))


def test_prepare_runlog_writes_a_valid_empty_skeleton(tmp_path):
    """뼈대는 유효한 JSON 이어야 한다 — 강제 종료돼도 list_runs 가 깨지지
    않는다. done 이 비어 있으므로 latest_run_id 는 이 기록을 집지 않는다."""
    b = built_for(tmp_path, [])
    path = prepare_runlog(b)
    assert path == tmp_path / ".organize" / "runs" / "r1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["run_id"] == "r1"
    assert data["done"] == [] and data["failed"] == [] and data["stale"] == []
    assert data["complete"] is False

    from organize.core.undo import latest_run_id
    assert latest_run_id(tmp_path) is None      # 뼈대만으론 되돌릴 대상으로 안 잡힌다


def test_write_runlog_os_error_is_wrapped_as_organize_error(tmp_path, monkeypatch):
    """write_runlog 자체가 실패해도(디스크 풀 등) 파이썬 traceback 이 그대로
    새면 안 된다 — 한국어 OrganizeError 로 바뀌어야 사용자가 읽을 수 있고,
    호출부(CLI)가 '그래도 파일은 옮겨졌다'는 안내를 붙일 수 있다."""
    src = tmp_path / "a.pdf"
    src.write_bytes(b"x")
    b = built_for(tmp_path, [Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route")])
    r = execute(b)
    assert (tmp_path / "01_Docs" / "a.pdf").exists()   # 실제로 이미 옮겨졌다

    secret = "raw OSError internal 0xdeadbeef"

    def boom(self, *a, **k):
        raise OSError(secret)

    monkeypatch.setattr(Path, "write_text", boom)
    with pytest.raises(OrganizeError) as ex:
        write_runlog(b, r)
    assert secret not in (ex.value.message + (ex.value.hint or ""))


def test_a_failed_quarantine_manifest_never_costs_us_the_run_record(tmp_path):
    """격리 목록을 못 써도 실행 기록은 반드시 남아야 한다.

    `_manifest.json` 은 "무엇이 왜 격리됐는지" 를 사람이 보라고 남기는 참고
    자료다. 되돌리기는 이걸 **읽지 않는다** — 실행 로그만 본다. 그런데 예전에는
    이 장부를 못 쓰면 예외가 execute() 밖으로 새어 나가, 부르는 쪽이 실행 로그를
    아예 못 썼다. 파일은 격리 폴더에 있는데 `organize undo` 는 "되돌릴 기록이
    없습니다" 라고 답했다 — 실측했다. 참고 자료 하나 때문에 되돌리기를 통째로
    잃는 것은 이 프로젝트가 정의한 최악의 실패다.
    """
    src = tmp_path / "중복.pdf"
    src.write_bytes(b"DATA")
    trash = tmp_path / ".organize" / "trash" / "r1"
    # _manifest.json 자리를 폴더로 막는다 — 파일이 열려 있거나 디스크가 꽉 찬
    # 것과 같은 부류의 실패를 결정적으로 재현한다.
    (trash / "_manifest.json").mkdir(parents=True)

    b = BuiltPlan(root=tmp_path, run_id="r1", plan=Plan(actions=[
        Action("quarantine", src, trash / "중복.pdf", "중복", "dedup")]))

    result = execute(b)                    # 예외가 새어 나오면 안 된다

    assert (trash / "중복.pdf").exists()    # 격리는 실제로 됐고
    assert any(r["kind"] == "quarantine" for r in result.done), \
        "격리한 사실이 done 에 남아야 되돌릴 수 있다"
    # 조용히 넘어가지도 않는다 — 무엇이 안 됐는지 사람이 볼 수 있어야 한다
    assert any("격리 목록" in r["why"] for r in result.failed)

    # 그리고 실행 기록이 실제로 써진다 — 되돌릴 수 있다
    log = write_runlog(b, result)
    assert log.is_file()
