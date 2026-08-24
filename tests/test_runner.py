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


# --- 수정 라운드 1/5: 레시피 오타 4종이 조용히 무시되지 않고 거부되는지 ---


def test_typo_in_when_key_is_rejected(tmp_path, profiles_dir):
    """'when' 을 'whne' 로 오타 내면 필터가 조용히 사라지면 안 된다."""
    root = work(tmp_path)
    old_file(root / "문서.pdf")
    old_file(root / "사진.png")
    with pytest.raises(OrganizeError) as ex:
        build_plan(
            root,
            [{"block": "route", "profile": "desktop", "whne": {"ext": [".pdf"]}}],
            today=TODAY, run_id="r1", profiles_dir=profiles_dir,
        )
    assert "whne" in ex.value.message
    assert "1번째" in ex.value.message
    assert ex.value.hint and "profile" in ex.value.hint


def test_typo_in_condition_key_is_rejected(tmp_path, profiles_dir):
    """when 안의 조건 키를 'exts' 로 오타 내면 조건이 조용히 사라지면 안 된다."""
    root = work(tmp_path)
    old_file(root / "문서.pdf")
    old_file(root / "사진.png")
    with pytest.raises(OrganizeError) as ex:
        build_plan(
            root,
            [{"block": "route", "profile": "desktop", "when": {"exts": [".pdf"]}}],
            today=TODAY, run_id="r1", profiles_dir=profiles_dir,
        )
    assert "exts" in ex.value.message
    assert "1번째" in ex.value.message
    assert ex.value.hint and "ext" in ex.value.hint


def test_typo_in_block_option_is_rejected(tmp_path, profiles_dir):
    """'profile' 을 'profil' 로 오타 내면 KeyError 가 아니라 한국어 오류여야 한다."""
    root = work(tmp_path)
    old_file(root / "문서.pdf")
    with pytest.raises(OrganizeError) as ex:
        build_plan(root, [{"block": "route", "profil": "desktop"}],
                   today=TODAY, run_id="r1", profiles_dir=profiles_dir)
    assert "profil" in ex.value.message
    assert "1번째" in ex.value.message
    assert ex.value.hint and "profile" in ex.value.hint


def test_typo_in_reserved_key_target_is_rejected(tmp_path, profiles_dir):
    """예약어 'target' 을 'tagret' 으로 오타 내면 엉뚱한 범위(루트 전체)에서
    조용히 동작하면 안 된다."""
    root = work(tmp_path)
    old_file(root / "02_Media" / "사진.png")
    with pytest.raises(OrganizeError) as ex:
        build_plan(
            root,
            [{"block": "by_date", "tagret": "02_Media", "layout": "{year}"}],
            today=TODAY, run_id="r1", profiles_dir=profiles_dir,
        )
    assert "tagret" in ex.value.message
    assert "1번째" in ex.value.message


def test_error_message_names_the_offending_step_order(tmp_path, profiles_dir):
    """오타가 두 번째 작업에 있으면 오류 메시지도 '2번째' 를 가리켜야 한다."""
    root = work(tmp_path)
    old_file(root / "문서.pdf")
    with pytest.raises(OrganizeError) as ex:
        build_plan(
            root,
            [{"block": "route", "profile": "desktop"},
             {"block": "route", "profil": "desktop"}],
            today=TODAY, run_id="r1", profiles_dir=profiles_dir,
        )
    assert "2번째" in ex.value.message


# --- 정상 레시피는 여전히 통과해야 한다 (과잉 차단 방지) ---


def test_valid_recipe_with_when_target_dest_still_works(tmp_path, profiles_dir):
    root = work(tmp_path)
    old_file(root / "하위" / "문서.pdf")
    old_file(root / "하위" / "사진.png")
    built = build_plan(
        root,
        [{"block": "route", "profile": "desktop", "when": {"ext": [".pdf"]},
          "target": "하위", "dest": "보관"}],
        today=TODAY, run_id="r1", profiles_dir=profiles_dir,
    )
    moves = [a for a in built.plan.actions if a.kind == "move"]
    assert [a.src.name for a in moves] == ["문서.pdf"]
    assert moves[0].dst == root / "보관" / "01_Docs" / "문서.pdf"


def test_valid_by_date_recipe_still_works(tmp_path, profiles_dir):
    root = work(tmp_path)
    old_file(root / "2023-12-15.png")
    built = build_plan(root, [{"block": "by_date", "layout": "{year}/{month}"}],
                       today=TODAY, run_id="r1", profiles_dir=profiles_dir)
    moves = [a for a in built.plan.actions if a.kind == "move"]
    assert moves[0].dst == root / "2023" / "12" / "2023-12-15.png"


def test_valid_unzip_recipe_still_works(tmp_path, profiles_dir):
    import zipfile
    root = work(tmp_path)
    root.mkdir(exist_ok=True)
    zpath = root / "묶음.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("안.txt", "hi")
    past = __import__("time").time() - 3600
    __import__("os").utime(zpath, (past, past))
    built = build_plan(root, [{"block": "unzip", "delete_original": True}],
                       today=TODAY, run_id="r1", profiles_dir=profiles_dir)
    kinds = {a.kind for a in built.plan.actions}
    assert "extract" in kinds
    assert "quarantine" in kinds


def test_valid_dedup_recipe_still_works(tmp_path, profiles_dir):
    root = work(tmp_path)
    old_file(root / "a.bin", "동일내용".encode("utf-8"))
    old_file(root / "b.bin", "동일내용".encode("utf-8"))
    built = build_plan(root, [{"block": "dedup", "when": {"larger_than": "1"}}],
                       today=TODAY, run_id="r1", profiles_dir=profiles_dir)
    assert dict(built.per_block)["dedup"] >= 0  # 오류 없이 통과하는 것 자체가 목적
