import json
from pathlib import Path

import pytest

from organize.core.action import Action, Plan
from organize.core.executor import execute, prepare_runlog, write_runlog
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


# --- 매체(USB·외장하드)가 없어서 못 한 것은 '끝난 것' 이 아니다 ---

def _run_onto(root, medium, name="중요문서.pdf"):
    """`root` 의 파일 하나를 `medium`(등록된 바깥 위치) 안으로 내보낸다.

    `external` 을 줘야 실행기가 root 밖 목적지를 허락한다 — 이 도구를 만든
    이유가 USB·외장하드로 내보내는 백업이다.
    """
    src = root / name
    src.write_bytes(b"DATA")
    b = BuiltPlan(root=root, run_id="r1", external=[medium], plan=Plan(actions=[
        Action("mkdir", None, medium / "01_Docs", "폴더", "route"),
        Action("move", src, medium / "01_Docs" / name, "이동", "route"),
    ]))
    result = execute(b)
    assert not result.failed, result.failed
    write_runlog(b, result)
    return src


def test_a_run_onto_a_missing_medium_can_still_be_undone_after_it_comes_back(tmp_path):
    """USB 를 뽑은 채 되돌리면 **실패로 남아야 한다** — 도장을 찍으면 안 된다.

    예전에는 `Path(final).exists()` 만 봤다. 매체가 안 보이면 항목마다
    `undone` 이 찍히고, 모두 찍히면 `undone_at` 까지 박혀 그 실행은 **영영**
    되돌릴 수 없었다. 파일은 USB 안에 멀쩡히 있는데도. 실측한 결함이다.
    """
    root = tmp_path / "정리대상"
    root.mkdir()
    usb = tmp_path / "usb"
    (usb / "백업").mkdir(parents=True)
    src = _run_onto(root, usb / "백업")
    assert not src.exists()

    usb.rename(tmp_path / "뽑힘")                    # USB 를 뽑았다
    result = undo(root)
    assert not result.done and result.failed
    assert latest_run_id(root) is not None, \
        "매체가 없어서 못 한 것뿐인데 '되돌릴 것이 없다' 로 만들면 안 된다"

    (tmp_path / "뽑힘").rename(usb)                  # 다시 꽂았다
    result = undo(root)
    assert not result.failed
    assert src.read_bytes() == b"DATA"
    assert latest_run_id(root) is None               # 이번엔 정말로 끝났다


def test_a_missing_medium_is_not_reported_as_a_deleted_file(tmp_path):
    """"옮기려는 파일이 없습니다" 는 사용자가 지웠다는 뜻으로 읽힌다.

    USB 를 뽑아 뒀을 뿐인데 그렇게 말하면 파일이 사라진 줄 안다. 안내는
    **무엇을 다시 꽂아야 하는지**(마운트 지점)를 가리켜야 한다.
    """
    root = tmp_path / "정리대상"
    root.mkdir()
    usb = tmp_path / "usb"
    (usb / "백업" / "깊은곳").mkdir(parents=True)
    _run_onto(root, usb / "백업" / "깊은곳")
    usb.rename(tmp_path / "뽑힘")

    why = [row["why"] for row in undo(root).failed]
    assert any("저장 매체를 찾을 수 없습니다" in w for w in why), why
    assert not any("옮기려는 파일이 없습니다" in w for w in why), why
    hint = undo(root).failed[0]["hint"]
    assert str(usb) in hint, "안 보이는 것 중 가장 위(마운트 지점)를 짚어야 한다"


# --- root **안쪽** 하위폴더를 지운 것은 매체 없음이 아니다 ---

def test_deleting_a_subfolder_inside_root_is_not_a_missing_medium(tmp_path):
    """`root/01_Docs` 를 지운 것을 "USB 를 다시 꽂아 주세요" 로 안내하면 안 된다.

    매체 판정을 넣으면서 "안 보이는 최상단이 root 안쪽인지" 를 안 봤다.
    그래서 정리가 만든 평범한 하위폴더를 사용자가 지우기만 해도 undo 가
    **영영** 막혔다 — `undone` 이 안 찍히니 `latest_run_id` 가 계속 그
    실행을 집어 이전 실행까지 가린다. 꽂을 USB 도 없다. 실측한 결함이다.

    옳은 동작은 옛 코드와 같다: 그 항목만 "옮기려는 파일이 없습니다" 로 닫고
    나머지는 정상 되돌린다.
    """
    import shutil

    a, c = tmp_path / "a.pdf", tmp_path / "c.jpg"
    a.write_bytes(b"A")
    c.write_bytes(b"C")
    run_plan(tmp_path, [
        Action("mkdir", None, tmp_path / "01_Docs", "폴더", "route"),
        Action("move", a, tmp_path / "01_Docs" / "a.pdf", "이동", "route"),
        Action("mkdir", None, tmp_path / "02_Media", "폴더", "route"),
        Action("move", c, tmp_path / "02_Media" / "c.jpg", "이동", "route"),
    ])
    shutil.rmtree(tmp_path / "01_Docs")            # 사용자가 폴더째 지웠다

    result = undo(tmp_path)

    why = [row["why"] for row in result.failed]
    assert any("옮기려는 파일이 없습니다" in w for w in why), why
    assert not any("저장 매체를 찾을 수 없습니다" in w for w in why), why
    assert c.read_bytes() == b"C", "나머지 항목은 정상 되돌아가야 한다"
    assert not (tmp_path / "02_Media").exists()
    log = json.loads((tmp_path / ".organize" / "runs" / "r1.json").read_text(encoding="utf-8"))
    assert log.get("undone_at"), "다시 해 봐야 소용없는 항목이 실행을 붙들면 안 된다"
    assert latest_run_id(tmp_path) is None, \
        "root 안쪽을 지운 것 때문에 undo 가 영영 막히면 안 된다"


def test_a_nested_folder_deleted_inside_root_is_also_not_a_missing_medium(tmp_path):
    """두 단계 안쪽(`root/02_Media/사진`)이 통째로 사라져도 마찬가지다."""
    import shutil

    src = tmp_path / "사진.jpg"
    src.write_bytes(b"IMG")
    run_plan(tmp_path, [
        Action("mkdir", None, tmp_path / "02_Media" / "사진", "폴더", "route"),
        Action("move", src, tmp_path / "02_Media" / "사진" / "사진.jpg", "이동", "route"),
    ])
    shutil.rmtree(tmp_path / "02_Media")           # 위 단계까지 통째로 지웠다

    why = [row["why"] for row in undo(tmp_path).failed]
    assert not any("저장 매체를 찾을 수 없습니다" in w for w in why), why
    assert latest_run_id(tmp_path) is None


def test_a_folder_the_run_created_on_a_missing_medium_is_removed_on_retry(tmp_path):
    """매체가 없을 때 mkdir 항목에 도장을 찍으면, 다시 꽂아도 빈 폴더가 남는다."""
    root = tmp_path / "정리대상"
    root.mkdir()
    usb = tmp_path / "usb"
    (usb / "백업").mkdir(parents=True)
    _run_onto(root, usb / "백업")

    usb.rename(tmp_path / "뽑힘")
    undo(root)
    (tmp_path / "뽑힘").rename(usb)
    undo(root)

    assert not (usb / "백업" / "01_Docs").exists(), \
        "되돌리기가 끝났으면 이 실행이 만든 빈 폴더도 없어야 한다"


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


def test_an_incomplete_run_record_is_never_read_as_nothing_to_undo(tmp_path):
    """뼈대 기록(`complete: false`)은 "되돌릴 게 없다" 가 **아니다.**

    `prepare_runlog` 이 실행 *전에* 써 두는 뼈대는 `done` 이 비어 있다. 실행
    중 기록을 못 남기면 그 뼈대만 남는데 — 그때가 바로 **파일은 옮겨졌는데
    무엇을 옮겼는지 모르는** 상황이다. 이걸 "되돌릴 게 없다" 로 읽으면
    `all([])` 이 참이라 되돌렸다고 도장을 찍어 버리고, 옮겨진 파일은 영영
    갇히고 재시도까지 "이미 되돌렸습니다" 로 막힌다. 실측한 결함이다.
    """
    src = tmp_path / "보고서.pdf"
    src.write_bytes(b"DATA")
    b = BuiltPlan(root=tmp_path, run_id="r1", plan=Plan(actions=[
        Action("move", src, tmp_path / "01_Docs" / "보고서.pdf", "이동", "route")]))
    prepare_runlog(b)
    execute(b)                         # 파일은 실제로 옮겨졌다
    # write_runlog 이 실패했다고 가정 — 뼈대만 남았다
    assert (tmp_path / "01_Docs" / "보고서.pdf").exists()

    with pytest.raises(OrganizeError) as ex:
        undo(tmp_path, run_id="r1")    # 사용자가 run_id 를 직접 지정한 경우

    assert "완전하지 않" in ex.value.message
    assert ex.value.hint                # 무엇을 확인하면 되는지 알려준다

    log = json.loads((tmp_path / ".organize" / "runs" / "r1.json").read_text(encoding="utf-8"))
    assert log.get("undone_at") is None, \
        "되돌린 게 없는데 도장을 찍으면 재시도가 영원히 막힌다"


def test_a_corrupted_log_entry_is_reported_in_korean_without_a_traceback(tmp_path):
    """실행 기록이 손상돼도 파이썬 예외 원문이 화면에 새면 안 된다."""
    src = tmp_path / "a.pdf"
    src.write_bytes(b"DATA")
    run_plan(tmp_path, [Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route")])

    log_path = tmp_path / ".organize" / "runs" / "r1.json"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    del data["done"][0]["kind"]        # 항목이 손상됐다
    log_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    result = undo(tmp_path)            # KeyError 가 새어 나오면 안 된다

    assert result.failed
    assert "실행 기록" in result.failed[0]["why"]


# --- 수정 라운드 2(최종 리뷰) — Critical #3: 못 읽은 기록을 없는 척했다. ---


def test_list_runs_reports_a_record_it_could_not_read(tmp_path):
    """조용히 `continue` 하면 깨진 기록이 **없는 것처럼** 취급된다.
    doctor 가 "없음 (확인함)" 이라고 답한 뿌리다."""
    runs = tmp_path / ".organize" / "runs"
    runs.mkdir(parents=True)
    (runs / "20260101-000000.json").write_text('{"run_id": "20260101-0', encoding="utf-8")

    rows = list_runs(tmp_path)
    assert len(rows) == 1
    assert rows[0]["unreadable"] is True
    assert rows[0]["path"] == str(runs / "20260101-000000.json")


def test_latest_run_id_never_picks_an_unreadable_record(tmp_path):
    runs = tmp_path / ".organize" / "runs"
    runs.mkdir(parents=True)
    (runs / "20260101-000000.json").write_text('{"run_id": "20260101-0', encoding="utf-8")
    assert latest_run_id(tmp_path) is None


def test_undo_with_no_run_id_says_the_record_is_unreadable(tmp_path):
    """파일은 옮겨져 있는데 "되돌릴 실행 기록이 없습니다" 는 거짓말이다."""
    runs = tmp_path / ".organize" / "runs"
    runs.mkdir(parents=True)
    broken = runs / "20260101-000000.json"
    broken.write_text('{"run_id": "20260101-0', encoding="utf-8")

    with pytest.raises(OrganizeError) as ex:
        undo(tmp_path)
    text = ex.value.message + (ex.value.hint or "")
    assert "없습니다" not in ex.value.message or "읽지" in text
    assert broken.name in text


def test_undo_by_run_id_on_a_corrupted_record_raises_a_korean_error(tmp_path):
    runs = tmp_path / ".organize" / "runs"
    runs.mkdir(parents=True)
    (runs / "20260101-000000.json").write_text('{"run_id": "20260101-0', encoding="utf-8")

    with pytest.raises(OrganizeError) as ex:
        undo(tmp_path, "20260101-000000")
    text = ex.value.message + (ex.value.hint or "")
    assert "JSONDecodeError" not in text and "Expecting" not in text


def test_undo_bookkeeping_write_never_destroys_the_record(tmp_path, monkeypatch):
    """되돌리기의 마지막 쓰기도 원자적이어야 한다 — 여기서 반쯤 쓰이면
    '어디까지 되돌렸는지' 가 사라져 재시도가 불가능해진다."""
    from organize.core import undo as undo_mod

    src = tmp_path / "a.pdf"
    src.write_bytes(b"DATA")
    run_plan(tmp_path, [
        Action("mkdir", None, tmp_path / "01_Docs", "폴더", "route"),
        Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route"),
    ])
    log = tmp_path / ".organize" / "runs" / "r1.json"
    before = log.read_text(encoding="utf-8")

    def boom(a, b):
        raise OSError("갈아끼우기 실패(시뮬레이션)")

    monkeypatch.setattr(undo_mod.os, "replace", boom)
    with pytest.raises(OrganizeError):
        undo(tmp_path)
    assert log.read_text(encoding="utf-8") == before, \
        "기록을 갈아끼우다 실패해도 이전 내용이 남아 있어야 한다"


# --- 수정 라운드 2(최종 리뷰) — Important #2: 되돌린 뒤 빈 폴더가 남는데
# "실패 0" 이라고 말했다. 조합 1092개 중 748개(68%)에서 났다. ---


def test_undo_removes_the_intermediate_folders_the_run_created(tmp_path):
    """`mkdir` Action 은 **잎 폴더 하나만** 담는데 실행기는
    `mkdir(parents=True)` 로 중간 폴더까지 만들었다. 그 중간 폴더는 실행
    기록에 없으니 undo 가 볼 수도 없었다 — `보관`, `02_Media/2023` 이 그렇게 남았다."""
    src = tmp_path / "사진.jpg"
    src.write_bytes(b"IMG")
    run_plan(tmp_path, [
        Action("mkdir", None, tmp_path / "보관" / "2023", "폴더", "by_date"),
        Action("move", src, tmp_path / "보관" / "2023" / "사진.jpg", "이동", "by_date"),
    ])
    assert not src.exists()

    result = undo(tmp_path)
    assert not result.failed
    assert src.read_bytes() == b"IMG"
    assert not (tmp_path / "보관" / "2023").exists()
    assert not (tmp_path / "보관").exists(), "중간 폴더도 우리가 만든 것이므로 치운다"


def test_undo_keeps_a_folder_that_already_existed_before_the_run(tmp_path):
    """비어 있다고 아무거나 지우면 안 된다 — **우리가 만든 것만** 지운다."""
    (tmp_path / "보관").mkdir()                      # 사용자가 이미 만들어 둔 폴더
    src = tmp_path / "사진.jpg"
    src.write_bytes(b"IMG")
    run_plan(tmp_path, [
        Action("mkdir", None, tmp_path / "보관" / "2023", "폴더", "by_date"),
        Action("move", src, tmp_path / "보관" / "2023" / "사진.jpg", "이동", "by_date"),
    ])

    undo(tmp_path)
    assert not (tmp_path / "보관" / "2023").exists()
    assert (tmp_path / "보관").is_dir(), "우리가 만든 폴더가 아니면 비어 있어도 남긴다"


def test_undo_says_when_a_file_came_back_under_a_different_name(tmp_path):
    """Minor #4 — 원래 자리를 쓸 수 없어 `a_(1).pdf` 로 돌려놓고도
    "되돌림 5 · 실패 0" 이라고만 했다. 덮어쓰지 않는 것은 옳지만
    이름이 바뀐 사실은 알려야 한다."""
    src = tmp_path / "a.pdf"
    src.write_bytes(b"DATA")
    run_plan(tmp_path, [
        Action("mkdir", None, tmp_path / "01_Docs", "폴더", "route"),
        Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route"),
    ])
    (tmp_path / "a.pdf").mkdir()                     # 원래 자리를 막는다

    result = undo(tmp_path)
    renamed = [r for r in result.done if r.get("renamed")]
    assert renamed, "이름이 바뀐 사실이 결과에 남아야 한다"
    assert renamed[0]["intended"] == str(tmp_path / "a.pdf")


# --- 수정 라운드 2 재수정 — C1 의 `-2` 접미사가 최신순 정렬을 깨뜨렸다.
# '-'(45) < '.'(46) 이라 '20260824-193928.json' 이 '20260824-193928-2.json' 보다
# 뒤로 정렬되고, reverse 하면 **옛 기록이 맨 앞**에 온다. 되돌리기는 반드시
# 시간 역순이어야 한다 — 컨트롤러가 실측으로 잡았다. ---


def _two_runs_in_one_second(root: Path, stamp: str = "20260824-193928"):
    """같은 초에 두 번 실행한 상태를 만든다. 두 번째 기록은 `-2` 로 비켜 간다."""
    a = root / "a.pdf"
    a.write_bytes(b"A")
    first = BuiltPlan(root=root, run_id=stamp, plan=Plan(actions=[
        Action("mkdir", None, root / "01_Docs", "폴더", "route"),
        Action("move", a, root / "01_Docs" / "a.pdf", "이동", "route"),
    ]))
    prepare_runlog(first)
    write_runlog(first, execute(first))

    c = root / "c.pdf"
    c.write_bytes(b"C")
    second = BuiltPlan(root=root, run_id=stamp, plan=Plan(actions=[
        Action("move", c, root / "01_Docs" / "c.pdf", "이동", "route"),
    ]))
    prepare_runlog(second)
    write_runlog(second, execute(second))
    return first, second


def test_list_runs_is_ordered_by_when_it_happened_not_by_file_name(tmp_path):
    """파일명 문자열 정렬은 `-2` 접미사에서 뒤집힌다. 실제 생성 순서를 따라야 한다."""
    _two_runs_in_one_second(tmp_path)
    rows = list_runs(tmp_path)
    assert [r["run_id"] for r in rows] == ["20260824-193928-2", "20260824-193928"], \
        "맨 앞이 가장 나중에 만든 기록이어야 한다"


def test_latest_run_id_picks_the_later_of_two_runs_in_the_same_second(tmp_path):
    _two_runs_in_one_second(tmp_path)
    assert latest_run_id(tmp_path) == "20260824-193928-2"


def test_two_runs_in_one_second_undo_newest_first_and_leave_no_empty_folder(tmp_path):
    """옛 기록을 먼저 되돌리면 그때 `01_Docs` 안에 새 기록의 파일이 남아 있어
    "비어있지 않다" 로 판정돼 안 지워지고, 새 기록에는 mkdir 항목이 없어서
    나중에 아무도 안 지운다 — Important #2 가 이 경로로 되살아났다."""
    _two_runs_in_one_second(tmp_path)
    undo(tmp_path)
    undo(tmp_path)

    left = sorted(p.name for p in tmp_path.iterdir() if p.name != ".organize")
    assert left == ["a.pdf", "c.pdf"], f"되돌린 뒤 없던 폴더가 남았다: {left}"


def test_a_file_moved_by_two_runs_comes_back_to_its_original_spot(tmp_path):
    """더 위험한 쪽 — 한 파일을 두 실행이 이어서 옮겼다면, 옛 실행을 먼저
    되돌릴 때 그 자리에 파일이 없다. `undo` 의 주석이 스스로 말하는
    "마지막에 한 일부터" 가 **실행 사이에서도** 지켜져야 한다."""
    stamp = "20260824-193928"
    src = tmp_path / "a.pdf"
    src.write_bytes(b"DATA")

    first = BuiltPlan(root=tmp_path, run_id=stamp, plan=Plan(actions=[
        Action("mkdir", None, tmp_path / "01_Docs", "폴더", "route"),
        Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route"),
    ]))
    prepare_runlog(first)
    write_runlog(first, execute(first))

    second = BuiltPlan(root=tmp_path, run_id=stamp, plan=Plan(actions=[
        Action("mkdir", None, tmp_path / "보관", "폴더", "route"),
        Action("move", tmp_path / "01_Docs" / "a.pdf", tmp_path / "보관" / "a.pdf",
               "이동", "route"),
    ]))
    prepare_runlog(second)
    write_runlog(second, execute(second))
    assert (tmp_path / "보관" / "a.pdf").exists()

    r2 = undo(tmp_path)
    r1 = undo(tmp_path)
    assert not r2.failed and not r1.failed, "시간 역순이면 실패할 항목이 없다"
    assert src.read_bytes() == b"DATA", "원래 자리로 돌아와야 한다"
    left = sorted(p.name for p in tmp_path.iterdir() if p.name != ".organize")
    assert left == ["a.pdf"], f"잔해가 남았다: {left}"


# --- 마지막 라운드 — C3 의 "없는 척하지 않는다" 분기가 두 갈래 중 하나에만 달렸다.
# 끊긴 실행의 뼈대(done: [])는 latest_run_id 가 절대 안 집으므로, `undo` 를
# **run_id 없이** 치면 "한 번 실행한 뒤에 쓸 수 있습니다" 로 빠졌다. 파일은
# 옮겨져 있는데 말이다. 이 테스트들의 축은 **run_id 를 주지 않는 경로**다. ---


def _skeleton(root: Path, run_id: str = "20260824-200028") -> Path:
    """실행이 중간에 끊긴 상태 — prepare_runlog 이 남긴 뼈대만 있다."""
    runs = root / ".organize" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    path = runs / f"{run_id}.json"
    path.write_text(json.dumps({
        "run_id": run_id, "trash_id": run_id, "root": str(root),
        "started_at": "2026-08-24T20:00:28",
        "done": [], "failed": [], "stale": [], "complete": False,
    }, ensure_ascii=False), encoding="utf-8")
    return path


def test_list_runs_carries_whether_the_record_is_complete(tmp_path):
    """`undo` 가 판단하려면 이 정보가 행에 실려야 한다."""
    _skeleton(tmp_path)
    rows = list_runs(tmp_path)
    assert rows[0]["complete"] is False


def test_undo_without_a_run_id_reports_the_interrupted_run(tmp_path):
    """**이 테스트의 축은 run_id 를 주지 않는 것이다.** run_id 를 콕 집으면
    옛 코드도 올바른 말을 했다 — 사람이 실제로 치는 `undo --root` 만 몰랐다."""
    log = _skeleton(tmp_path)
    with pytest.raises(OrganizeError) as ex:
        undo(tmp_path)                     # run_id 없이 — 이게 핵심이다
    text = ex.value.message + (ex.value.hint or "")
    assert "한 번 실행한 뒤에" not in text, "실행한 적 없다고 말하면 안 된다"
    assert log.name in text, "어느 기록인지 알려줘야 한다"
    assert "완전하지 않" in text or "끊" in text


def test_undo_without_a_run_id_does_not_say_never_ran_when_all_runs_are_undone(tmp_path):
    """이미 되돌린 기록만 남은 경우도 "한 번 실행한 뒤에" 는 거짓말이다."""
    src = tmp_path / "a.pdf"
    src.write_bytes(b"DATA")
    run_plan(tmp_path, [Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route")])
    undo(tmp_path)

    with pytest.raises(OrganizeError) as ex:
        undo(tmp_path)
    text = ex.value.message + (ex.value.hint or "")
    assert "한 번 실행한 뒤에" not in text
    assert "이미 되돌린" in text


def test_undo_still_says_nothing_was_ever_run_when_there_is_no_record(tmp_path):
    """정말로 기록이 하나도 없을 때만 그 문구를 쓴다 — 그때는 사실이다."""
    with pytest.raises(OrganizeError) as ex:
        undo(tmp_path)
    assert "한 번 실행한 뒤에" in (ex.value.hint or "")


def test_an_interrupted_run_does_not_hide_an_older_undoable_run(tmp_path):
    """반대 방향 축 — 끊긴 기록을 알리게 만들면서, 그것 때문에 **되돌릴 수 있는
    옛 실행까지 가려지면** 안 된다. 되돌릴 수 있으면 되돌리는 것이 먼저다."""
    src = tmp_path / "a.pdf"
    src.write_bytes(b"DATA")
    good = BuiltPlan(root=tmp_path, run_id="20260824-120000", plan=Plan(actions=[
        Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route")]))
    prepare_runlog(good)
    write_runlog(good, execute(good))
    _skeleton(tmp_path, "20260824-130000")          # 그 뒤에 끊긴 실행이 하나 더

    result = undo(tmp_path)                          # run_id 없이
    assert not result.failed
    assert src.read_bytes() == b"DATA"

    with pytest.raises(OrganizeError) as ex:         # 이제는 끊긴 것만 남았다
        undo(tmp_path)
    assert "완전하지 않" in ex.value.message
