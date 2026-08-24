import json
from pathlib import Path

import pytest

from organize.core.action import Action, Plan
from organize.core.executor import execute, write_runlog
from organize.core.runner import BuiltPlan
from organize.core.undo import latest_run_id, list_runs, undo
from organize.errors import OrganizeError


def run_plan(root, actions, run_id="r1"):
    b = BuiltPlan(root=root, run_id=run_id, plan=Plan(actions=list(actions)))
    result = execute(b)
    write_runlog(b, result)
    return result


def test_move_is_reversed(tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"DATA")
    run_plan(tmp_path, [
        Action("mkdir", None, tmp_path / "01_Docs", "폴더", "route"),
        Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route"),
    ])
    assert not src.exists()

    undo(tmp_path)
    assert src.read_bytes() == b"DATA"
    assert not (tmp_path / "01_Docs" / "a.pdf").exists()


def test_empty_folder_is_removed_but_a_used_one_is_kept(tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"DATA")
    run_plan(tmp_path, [
        Action("mkdir", None, tmp_path / "01_Docs", "폴더", "route"),
        Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route"),
    ])
    (tmp_path / "01_Docs" / "사용자가둔파일.txt").write_bytes(b"KEEP")

    undo(tmp_path)
    assert (tmp_path / "01_Docs").is_dir()               # 비어있지 않으니 남긴다
    assert (tmp_path / "01_Docs" / "사용자가둔파일.txt").exists()


def test_quarantine_is_restored(tmp_path):
    src = tmp_path / "중복.pdf"
    src.write_bytes(b"DATA")
    trash = tmp_path / ".organize" / "trash" / "r1"
    run_plan(tmp_path, [Action("quarantine", src, trash / "중복.pdf", "중복", "dedup")])
    assert not src.exists()

    undo(tmp_path)
    assert src.read_bytes() == b"DATA"


def test_extracted_file_goes_to_the_undo_trash(tmp_path):
    import zipfile
    z = tmp_path / "자료.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("문서.pdf", b"ZIPPED")
    run_plan(tmp_path, [Action("extract", z, tmp_path / "문서.pdf", "꺼냄", "unzip",
                               member="문서.pdf")])
    assert (tmp_path / "문서.pdf").exists()

    undo(tmp_path)
    assert not (tmp_path / "문서.pdf").exists()
    assert (tmp_path / ".organize" / "trash" / "r1-undo" / "문서.pdf").exists()
    assert z.exists()                                    # 원본 zip 은 그대로


def test_round_trip_leaves_the_folder_as_it_was(tmp_path):
    for name in ["a.pdf", "b.png", "c.md"]:
        (tmp_path / name).write_bytes(name.encode())
    before = sorted(p.name for p in tmp_path.iterdir())

    run_plan(tmp_path, [
        Action("mkdir", None, tmp_path / "01_Docs", "폴더", "route"),
        Action("move", tmp_path / "a.pdf", tmp_path / "01_Docs" / "a.pdf", "이동", "route"),
        Action("move", tmp_path / "c.md", tmp_path / "01_Docs" / "c.md", "이동", "route"),
    ])
    undo(tmp_path)

    after = sorted(p.name for p in tmp_path.iterdir() if p.name != ".organize")
    assert after == before


def test_undo_marks_the_run_and_does_not_repeat(tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"DATA")
    run_plan(tmp_path, [Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route")])
    undo(tmp_path)

    assert latest_run_id(tmp_path) is None
    log = json.loads((tmp_path / ".organize" / "runs" / "r1.json").read_text(encoding="utf-8"))
    assert log["undone_at"]


def test_latest_picks_the_newest_run(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"DATA")
    (tmp_path / "b.pdf").write_bytes(b"DATA")
    run_plan(tmp_path, [Action("move", tmp_path / "a.pdf", tmp_path / "x" / "a.pdf", "이동", "route")],
             run_id="20260821-100000")
    run_plan(tmp_path, [Action("move", tmp_path / "b.pdf", tmp_path / "x" / "b.pdf", "이동", "route")],
             run_id="20260821-110000")
    assert latest_run_id(tmp_path) == "20260821-110000"


def test_list_runs_reports_state(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"DATA")
    run_plan(tmp_path, [Action("move", tmp_path / "a.pdf", tmp_path / "x" / "a.pdf", "이동", "route")])
    rows = list_runs(tmp_path)
    assert rows[0]["run_id"] == "r1" and rows[0]["undone_at"] is None
    undo(tmp_path)
    assert list_runs(tmp_path)[0]["undone_at"] is not None


def test_nothing_to_undo_is_a_friendly_error(tmp_path):
    with pytest.raises(OrganizeError) as ex:
        undo(tmp_path)
    assert "되돌릴" in ex.value.message


# --- 실패 주입: 부분 실패해도 나머지는 계속 진행하고, 무엇이 안 됐는지 남긴다 ---

def test_missing_target_file_is_reported_but_other_items_still_undo(tmp_path):
    """되돌리려는 파일이 undo 시점에 이미 없다 — 다른 항목은 계속 되돌아간다."""
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    a.write_bytes(b"A")
    b.write_bytes(b"B")
    run_plan(tmp_path, [
        Action("mkdir", None, tmp_path / "01_Docs", "폴더", "route"),
        Action("move", a, tmp_path / "01_Docs" / "a.pdf", "이동", "route"),
        Action("move", b, tmp_path / "01_Docs" / "b.pdf", "이동", "route"),
    ])
    # a.pdf 가 undo 시도 전에 없어졌다고 가정한다(사용자가 지웠거나 옮겼거나).
    (tmp_path / "01_Docs" / "a.pdf").unlink()

    result = undo(tmp_path)

    assert len(result.failed) == 1
    assert result.failed[0]["kind"] == "move"
    assert "옮기려는 파일이 없습니다" in result.failed[0]["why"]
    assert result.failed[0]["hint"]                       # hint 를 버리지 않는다
    # b.pdf 는 정상적으로 되돌아갔다 — 부분 실패가 나머지를 막지 않는다
    assert b.read_bytes() == b"B"
    assert not (tmp_path / "01_Docs" / "b.pdf").exists()
    # 폴더에는 a.pdf 가 아직 없어진 채 남아 있어(원래 있던 자리가 아니므로)
    # 실제로는 비어 있으니 지워진다 — 사용자 파일을 잃은 게 아니라
    #애초에 없던 자리다.
    assert not (tmp_path / "01_Docs").exists()


def test_oserror_during_restore_is_reported_in_korean_without_raw_exception_text(tmp_path, monkeypatch):
    """되돌리기 도중 OSError 가 나면 한국어 메시지로 남고, 파이썬 예외 원문을 노출하지 않는다."""
    src = tmp_path / "a.pdf"
    src.write_bytes(b"DATA")
    run_plan(tmp_path, [Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route")])

    import organize.core.undo as undo_mod

    def _boom(_src, _dst):
        raise OSError(13, "Permission denied")   # 권한 없음을 흉내낸다

    monkeypatch.setattr(undo_mod, "move_file", _boom)

    result = undo(tmp_path)

    assert len(result.failed) == 1
    why = result.failed[0]["why"]
    assert "되돌리지 못했습니다" in why
    assert "Permission denied" not in why                 # 예외 원문을 그대로 보여주지 않는다
    assert "Permission denied" not in (result.failed[0].get("hint") or "")
    # 고칠 수 있는 실패(권한 등)는 **재시도할 수 있게 남는다.** 예전에는 여기서
    # "다 되돌렸다" 도장을 찍어 이 항목을 영원히 못 돌렸다. 다시 시도해도 소용없는
    # 경우(되돌릴 파일이 아예 없어진 경우)는 따로 '끝난 것'으로 처리하므로,
    # 고칠 수 없는 항목 하나가 실행을 영원히 붙드는 일은 생기지 않는다.
    assert latest_run_id(tmp_path) == "r1"


def test_undoing_an_already_undone_run_is_a_friendly_error(tmp_path):
    """두 번 되돌리면? — 이미 되돌린 실행을 다시 지정하면, 사라진 파일을 찾아
    항목마다 실패로 쌓는 대신 시도 자체를 막고 이유를 알려준다."""
    src = tmp_path / "a.pdf"
    src.write_bytes(b"DATA")
    run_plan(tmp_path, [Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route")])
    undo(tmp_path, run_id="r1")

    with pytest.raises(OrganizeError) as ex:
        undo(tmp_path, run_id="r1")
    assert "이미 되돌렸습니다" in ex.value.message
    assert src.read_bytes() == b"DATA"                     # 이미 되돌린 상태는 그대로 유지된다


def test_restore_never_overwrites_a_file_that_reappeared_at_the_original_spot(tmp_path):
    """되돌릴 자리에 다른 파일이 이미 생겼으면 그걸 덮지 않고 옆 이름으로 놓는다."""
    src = tmp_path / "a.pdf"
    src.write_bytes(b"ORIGINAL")
    run_plan(tmp_path, [
        Action("mkdir", None, tmp_path / "01_Docs", "폴더", "route"),
        Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route"),
    ])
    assert not src.exists()

    # undo 시도 전, 원래 자리에 전혀 다른 파일이 새로 생겼다.
    src.write_bytes(b"NEW FILE, NOT THE ORIGINAL")

    result = undo(tmp_path)

    # 새로 생긴 파일은 그대로 있다 — 덮어쓰지 않는다.
    assert src.read_bytes() == b"NEW FILE, NOT THE ORIGINAL"
    # 되돌린 원본은 옆 이름으로 살아남는다 — 잃지 않는다.
    sibling = tmp_path / "a_(1).pdf"
    assert sibling.exists()
    assert sibling.read_bytes() == b"ORIGINAL"
    assert not result.failed


# ---------------------------------------------------------------------------
# 수정 라운드 1(Task 18 리뷰) Minor #1 — hint 가 존재하지 않는
# `organize trash --list` 를 안내하던 것. 두 발생 지점 모두 확인한다.
# ---------------------------------------------------------------------------


def test_undo_unknown_run_id_hint_has_no_trash_command(tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"DATA")
    run_plan(tmp_path, [
        Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route"),
    ])
    with pytest.raises(OrganizeError) as ex:
        undo(tmp_path, run_id="있지도-않는-id")
    assert "trash" not in (ex.value.hint or "")


def test_undo_already_undone_hint_has_no_trash_command(tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"DATA")
    run_plan(tmp_path, [
        Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route"),
    ])
    undo(tmp_path, run_id="r1")
    with pytest.raises(OrganizeError) as ex:
        undo(tmp_path, run_id="r1")
    assert "trash" not in (ex.value.hint or "")


# --- 항목별 되돌림 기록: 부분 실패해도 재시도할 수 있어야 한다 ---

def _flaky_move(monkeypatch, fail_for: str):
    """`fail_for` 이름의 파일만 실패시키고 나머지는 진짜로 옮긴다."""
    import organize.core.undo as undo_mod
    real = undo_mod.move_file

    def flaky(src, dst):
        if Path(src).name == fail_for:
            raise OSError(13, "Permission denied")
        return real(src, dst)

    monkeypatch.setattr(undo_mod, "move_file", flaky)
    return real


def test_a_failed_item_can_be_retried_after_the_cause_is_fixed(tmp_path, monkeypatch):
    """되돌리기가 부분 실패하면, 원인을 고친 뒤 **다시 되돌릴 수 있어야 한다.**

    예전에는 실패가 있어도 실행 로그에 "다 되돌렸다" 도장을 찍어서, 실패한
    항목을 영원히 못 돌렸다. 권한 하나 때문에 파일이 옮겨진 자리에 갇혔다.
    """
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    a.write_bytes(b"A")
    b.write_bytes(b"B")
    run_plan(tmp_path, [
        Action("move", a, tmp_path / "01_Docs" / "a.pdf", "이동", "route"),
        Action("move", b, tmp_path / "01_Docs" / "b.pdf", "이동", "route"),
    ])

    import organize.core.undo as undo_mod
    real = _flaky_move(monkeypatch, fail_for="a.pdf")

    first = undo(tmp_path)
    assert len(first.failed) == 1
    assert b.read_bytes() == b"B"                  # b 는 돌아왔고
    assert not a.exists()                          # a 는 아직 못 돌아왔다

    monkeypatch.setattr(undo_mod, "move_file", real)   # 원인을 고쳤다
    second = undo(tmp_path)

    assert not second.failed
    assert a.read_bytes() == b"A"                  # 이제 돌아왔다
    # 이미 되돌린 b 를 두 번 건드리지 않았다
    assert [r["kind"] for r in second.done] == ["restore"]


def test_a_partly_undone_run_is_not_marked_finished(tmp_path, monkeypatch):
    """아직 못 되돌린 항목이 있으면 '다 되돌렸다' 도장을 찍지 않는다."""
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    a.write_bytes(b"A")
    b.write_bytes(b"B")
    run_plan(tmp_path, [
        Action("move", a, tmp_path / "01_Docs" / "a.pdf", "이동", "route"),
        Action("move", b, tmp_path / "01_Docs" / "b.pdf", "이동", "route"),
    ])
    _flaky_move(monkeypatch, fail_for="a.pdf")

    undo(tmp_path)

    log = json.loads((tmp_path / ".organize" / "runs" / "r1.json").read_text(encoding="utf-8"))
    assert log.get("undone_at") is None, "남은 게 있는데 다 되돌렸다고 하면 재시도가 막힌다"
    assert latest_run_id(tmp_path) == "r1", "되돌릴 게 남았으니 다시 집혀야 한다"


def test_a_target_that_vanished_does_not_hold_the_run_forever(tmp_path):
    """되돌릴 파일이 그 자리에 아예 없으면 다시 시도해도 결과가 같다.

    그런 항목까지 '아직 남았다' 로 붙들면 그 실행이 영원히 되돌릴 게 남은
    실행으로 남아, `organize undo` 가 **이전 실행을 영영 못 보게 가린다.**
    """
    src = tmp_path / "a.pdf"
    src.write_bytes(b"DATA")
    run_plan(tmp_path, [Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route")])
    (tmp_path / "01_Docs" / "a.pdf").unlink()      # 사용자가 지웠거나 옮겼다

    result = undo(tmp_path)

    assert result.failed                            # 무슨 일이 있었는지는 알린다
    assert latest_run_id(tmp_path) is None, \
        "다시 시도해도 소용없는 항목이 실행을 붙들면 안 된다"


# --- 되돌린 뒤 우리가 만든 장부만 치운다 ---

def test_undo_tidies_our_own_manifest_but_never_user_files(tmp_path):
    """되돌리고 나면 격리 폴더에 우리가 쓴 `_manifest.json` 과 빈 폴더가 남았다.

    이건 사용자 파일이 아니라 **우리 장부**다. 파일이 전부 제자리로 돌아가
    폴더에 장부만 남았을 때에만 치운다.
    """
    src = tmp_path / "중복.pdf"
    src.write_bytes(b"DATA")
    trash = tmp_path / ".organize" / "trash" / "r1"
    run_plan(tmp_path, [Action("quarantine", src, trash / "중복.pdf", "중복", "dedup")])
    assert (trash / "_manifest.json").is_file()

    undo(tmp_path)

    assert src.read_bytes() == b"DATA"
    assert not (trash / "_manifest.json").exists(), "우리가 쓴 장부는 치운다"
    assert not trash.exists(), "빈 격리 폴더도 치운다"


def test_the_manifest_is_kept_when_a_quarantined_file_could_not_be_restored(tmp_path, monkeypatch):
    """격리에 사용자 파일이 아직 남아 있으면 장부를 지우지 않는다.

    그 파일이 무엇이고 어디서 왔는지 적힌 유일한 기록이다.
    """
    src = tmp_path / "중복.pdf"
    src.write_bytes(b"DATA")
    trash = tmp_path / ".organize" / "trash" / "r1"
    run_plan(tmp_path, [Action("quarantine", src, trash / "중복.pdf", "중복", "dedup")])
    _flaky_move(monkeypatch, fail_for="중복.pdf")

    undo(tmp_path)

    assert (trash / "중복.pdf").exists(), "사용자 파일이 아직 격리에 남아 있다"
    assert (trash / "_manifest.json").is_file(), \
        "격리에 사용자 파일이 남아 있으면 그게 무엇인지 적힌 장부를 지우면 안 된다"
