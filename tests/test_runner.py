from datetime import date, datetime
from pathlib import Path

import pytest

from organize.core.runner import build_plan, make_run_id
from organize.errors import OrganizeError

TODAY = date(2026, 8, 21)


@pytest.fixture
def profiles_dir(tmp_path):
    d = tmp_path / "profiles"
    d.mkdir()
    (d / "desktop.toml").write_text(
        'name = "테스트"\n'
        '[[rules]]\n to = "01_Docs"\n ext = [".pdf", ".md"]\n'
        '[[rules]]\n to = "02_Media"\n ext = [".png"]\n'
        '[[rules]]\n to = "99_Unsorted"\n default = true\n',
        encoding="utf-8",
    )
    return d


def work(tmp_path):
    root = tmp_path / "작업"
    root.mkdir()
    return root


def old_file(path: Path, data: bytes = b"DATA") -> Path:
    """방금 만든 파일은 '작업 중' 으로 걸러지므로 수정시각을 한 시간 전으로 돌린다."""
    import os, time
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    past = time.time() - 3600
    os.utime(path, (past, past))
    return path


def test_run_id_format():
    assert make_run_id(datetime(2026, 8, 21, 14, 32, 10)) == "20260821-143210"


def test_single_step(tmp_path, profiles_dir):
    root = work(tmp_path)
    old_file(root / "보고서.pdf")
    built = build_plan(root, [{"block": "route", "profile": "desktop"}],
                       today=TODAY, run_id="r1", profiles_dir=profiles_dir)
    moves = [a for a in built.plan.actions if a.kind == "move"]
    assert [a.dst.parent.name for a in moves] == ["01_Docs"]
    assert built.per_block == [("route", 2)]        # mkdir 1 + move 1


def test_chained_steps_see_the_previous_result(tmp_path, profiles_dir):
    """route 가 02_Media 를 만들면 by_date 가 그 안을 대상으로 잡는다."""
    root = work(tmp_path)
    old_file(root / "2023-12-15.png")
    built = build_plan(
        root,
        [{"block": "route", "profile": "desktop"},
         {"block": "by_date", "target": "02_Media", "layout": "{year}"}],
        today=TODAY, run_id="r1", profiles_dir=profiles_dir,
    )
    dsts = [a.dst for a in built.plan.actions if a.kind == "move"]
    assert dsts[0] == root / "02_Media" / "2023-12-15.png"
    assert dsts[1] == root / "02_Media" / "2023" / "2023-12-15.png"


def test_wrong_order_produces_zero_actions_for_the_later_block(tmp_path, profiles_dir):
    """연도별을 먼저 돌리면 파일이 2023/ 안으로 들어가 route 대상이 사라진다."""
    root = work(tmp_path)
    old_file(root / "2023-12-15.png")
    built = build_plan(
        root,
        [{"block": "by_date"}, {"block": "route", "profile": "desktop"}],
        today=TODAY, run_id="r1", profiles_dir=profiles_dir,
    )
    assert dict(built.per_block)["route"] == 0


def test_scanner_skips_are_carried_into_the_plan(tmp_path, profiles_dir):
    root = work(tmp_path)
    old_file(root / "desktop.ini")
    old_file(root / "보고서.pdf")
    built = build_plan(root, [{"block": "route", "profile": "desktop"}],
                       today=TODAY, run_id="r1", profiles_dir=profiles_dir)
    assert any("시스템 파일" in why for _, why in built.plan.skipped)


def test_snapshot_records_size_and_mtime(tmp_path, profiles_dir):
    root = work(tmp_path)
    f = old_file(root / "보고서.pdf", b"12345")
    built = build_plan(root, [{"block": "route", "profile": "desktop"}],
                       today=TODAY, run_id="r1", profiles_dir=profiles_dir)
    assert built.snapshot[str(f)][0] == 5


def test_nothing_is_moved_on_disk(tmp_path, profiles_dir):
    """계획을 세우는 동안에는 파일이 하나도 움직이지 않아야 한다."""
    root = work(tmp_path)
    old_file(root / "보고서.pdf")
    build_plan(root, [{"block": "route", "profile": "desktop"}],
               today=TODAY, run_id="r1", profiles_dir=profiles_dir)
    assert (root / "보고서.pdf").exists()
    assert not (root / "01_Docs").exists()


def test_unknown_block_is_a_friendly_error(tmp_path, profiles_dir):
    root = work(tmp_path)
    with pytest.raises(OrganizeError):
        build_plan(root, [{"block": "없는것"}], today=TODAY, run_id="r1",
                   profiles_dir=profiles_dir)


def test_unknown_profile_is_a_friendly_error(tmp_path, profiles_dir):
    root = work(tmp_path)
    with pytest.raises(OrganizeError) as ex:
        build_plan(root, [{"block": "route", "profile": "없는설정"}],
                   today=TODAY, run_id="r1", profiles_dir=profiles_dir)
    assert "없는설정" in ex.value.message
