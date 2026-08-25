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


def test_broken_regex_in_a_recipe_when_is_rejected_at_plan_time(tmp_path, profiles_dir):
    """Critical #2 — 계획 시점에 막아야 한다. 실행 중에 터지면 이미 옮긴
    폴더의 되돌리기 안내가 통째로 사라진다."""
    root = tmp_path / "작업"
    root.mkdir()
    with pytest.raises(OrganizeError) as ex:
        build_plan(root, [{"block": "route", "profile": "desktop",
                           "when": {"name_regex": "[불완전"}}],
                   today=date(2026, 8, 21), run_id="r1", profiles_dir=profiles_dir)
    assert "name_regex" in ex.value.message
    assert "1번째" in ex.value.message


def test_string_condition_value_in_a_recipe_is_normalized_not_walked(tmp_path, profiles_dir):
    """Important #1 — 레시피의 `when` 값도 타입을 봐야 한다."""
    root = tmp_path / "작업"
    root.mkdir()
    (root / "보고서.pdf").write_bytes(b"A")
    (root / "사진.png").write_bytes(b"B")
    import os, time
    past = time.time() - 3600
    for p in root.iterdir():
        os.utime(p, (past, past))
    built = build_plan(root, [{"block": "route", "profile": "desktop",
                               "when": {"ext": ".pdf"}}],
                       today=date(2026, 8, 21), run_id="r1", profiles_dir=profiles_dir)
    moved = [a for a in built.plan.actions if a.kind == "move"]
    assert [a.src.name for a in moved] == ["보고서.pdf"]


# ── Task 10: 파일 하나만 이번 실행에서 빼기 (exclude) ──────────────────────
#
# 스캐너는 **1분 안에 바뀐 파일**을 "받는 중" 으로 보고 걸러낸다. 방금 만든
# 테스트 파일이 전부 거기 걸리면 계획이 통째로 비고, 그러면 테스트는 아무것도
# 확인하지 않은 채 초록불이 된다(이 프로젝트가 여러 번 물린 자리다).
# 그래서 아래 테스트는 파일 시각을 되돌리는 대신 **가짜 현재 시각**을 넘긴다.
NOW = 1e12

ROUTE = {"block": "route", "profile": "desktop"}


def new_file(path: Path, data: bytes = b"DATA") -> Path:
    """시각을 손대지 않은 파일. 대신 build_plan 에 now=NOW 를 넘겨서 통과시킨다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_excluded_file_gets_no_action(tmp_path, profiles_dir):
    """뺀 파일을 src 로 삼는 동작이 하나도 없어야 한다."""
    root = work(tmp_path)
    빼기 = new_file(root / "가이드.pdf")
    new_file(root / "보고서.pdf")

    built = build_plan(root, [ROUTE], today=TODAY, run_id="r1",
                       profiles_dir=profiles_dir, now=NOW, exclude={빼기})

    srcs = [a.src for a in built.plan.actions if a.src is not None]
    assert srcs, "다른 파일은 계획에 남아 있어야 한다(계획이 통째로 비면 확인한 것이 없다)"
    assert 빼기 not in srcs
    assert root / "보고서.pdf" in srcs


def test_folder_for_an_excluded_file_is_not_created(tmp_path, profiles_dir):
    """그 폴더로 갈 파일이 그것뿐이면 **폴더 생성도 함께 사라져야** 한다.

    만들어진 Plan 에서 동작만 골라내는 방식으로는 mkdir 이 남아 빈 폴더가 생긴다.
    """
    root = work(tmp_path)
    사진 = new_file(root / "사진.png")            # 이 파일만 02_Media 로 간다
    new_file(root / "보고서.pdf")

    before = build_plan(root, [ROUTE], today=TODAY, run_id="r1",
                        profiles_dir=profiles_dir, now=NOW)
    assert sorted(a.dst.name for a in before.plan.actions if a.kind == "mkdir") \
        == ["01_Docs", "02_Media"]

    after = build_plan(root, [ROUTE], today=TODAY, run_id="r1",
                       profiles_dir=profiles_dir, now=NOW, exclude={사진})
    assert [a.dst.name for a in after.plan.actions if a.kind == "mkdir"] == ["01_Docs"]


def test_excluding_the_first_file_frees_the_name_for_the_second(tmp_path, profiles_dir):
    """앞 파일을 빼면 뒤 파일은 `_(1)` 을 달 이유가 없어진다.

    이것이 "만든 Plan 에서 골라내기" 로는 절대 안 되는 것이다 — 골라내면
    이름이 `사진_(1).png` 로 그대로 남아, 사용자가 본 적 없는 이름이 생긴다.
    """
    root = work(tmp_path)
    앞 = new_file(root / "하위1" / "사진.png", b"AAAA")
    new_file(root / "하위2" / "사진.png", b"BBBB")
    steps = [{"block": "route", "profile": "desktop", "target": "하위1", "dest": ""},
             {"block": "route", "profile": "desktop", "target": "하위2", "dest": ""}]

    before = build_plan(root, steps, today=TODAY, run_id="r1",
                        profiles_dir=profiles_dir, now=NOW)
    assert [a.dst.name for a in before.plan.actions if a.kind == "move"] \
        == ["사진.png", "사진_(1).png"]

    after = build_plan(root, steps, today=TODAY, run_id="r1",
                       profiles_dir=profiles_dir, now=NOW, exclude={앞})
    moves = [a for a in after.plan.actions if a.kind == "move"]
    assert [a.src for a in moves] == [root / "하위2" / "사진.png"]
    assert [a.dst.name for a in moves] == ["사진.png"], "앞 것을 뺐으니 이름이 비었다"


def test_excluded_file_is_reported_as_skipped_with_a_reason(tmp_path, profiles_dir):
    """조용히 사라지면 안 된다 — '손대지 않음' 숫자에 잡혀야 사용자가 확인한다."""
    root = work(tmp_path)
    빼기 = new_file(root / "가이드.pdf")
    new_file(root / "보고서.pdf")

    built = build_plan(root, [ROUTE], today=TODAY, run_id="r1",
                       profiles_dir=profiles_dir, now=NOW, exclude={빼기})

    assert (빼기, "제외함") in built.plan.skipped


def test_exclude_none_and_empty_behave_exactly_like_before(tmp_path, profiles_dir):
    """CLI 는 이 인자를 안 쓴다. 안 넘겼을 때 동작이 조금이라도 달라지면 안 된다."""
    root = work(tmp_path)
    new_file(root / "보고서.pdf")
    new_file(root / "사진.png")
    kw = dict(today=TODAY, run_id="r1", profiles_dir=profiles_dir, now=NOW)

    기본 = build_plan(root, [ROUTE], **kw)
    없음 = build_plan(root, [ROUTE], **kw, exclude=None)
    빈것 = build_plan(root, [ROUTE], **kw, exclude=set())

    # 계획이 비어 있으면 "빈 것 == 빈 것" 이라 아무것도 확인하지 못한다.
    assert len(기본.plan.actions) == 4          # mkdir 2 + move 2
    assert 기본.plan.actions == 없음.plan.actions == 빈것.plan.actions
    assert 기본.plan.skipped == 없음.plan.skipped == 빈것.plan.skipped
    assert 기본.per_block == 빈것.per_block
    assert 기본.snapshot == 빈것.snapshot


def test_origins_line_up_one_for_one_with_actions(tmp_path, profiles_dir):
    """길이가 어긋나면 화면이 **엉뚱한 파일에 체크를 붙인다.**"""
    root = work(tmp_path)
    new_file(root / "보고서.pdf")
    new_file(root / "사진.png")

    built = build_plan(root, [ROUTE], today=TODAY, run_id="r1",
                       profiles_dir=profiles_dir, now=NOW)

    assert len(built.plan.actions) == 4, "계획이 비면 길이가 같아도 확인한 것이 없다"
    assert len(built.origins) == len(built.plan.actions)
    for action, origin in zip(built.plan.actions, built.origins):
        if action.kind == "mkdir":
            assert origin is None, "폴더 생성은 어느 파일 것도 아니다"
        else:
            assert origin is not None


def test_origin_of_a_second_move_is_the_original_file(tmp_path, profiles_dir):
    """route → by_date 로 두 번 옮겨지는 파일. 두 번째 이동의 src 는 중간 경로지만
    origin 은 **원본 경로**여야 한다 — 그래야 체크박스 한 개가 사슬 전체를 묶는다."""
    root = work(tmp_path)
    원본 = new_file(root / "2023-12-15.png")

    built = build_plan(
        root,
        [ROUTE, {"block": "by_date", "target": "02_Media", "layout": "{year}"}],
        today=TODAY, run_id="r1", profiles_dir=profiles_dir, now=NOW)

    moves = [(a, o) for a, o in zip(built.plan.actions, built.origins)
             if a.kind == "move"]
    assert len(moves) == 2
    assert moves[0][0].src == 원본 and moves[0][1] == 원본
    assert moves[1][0].src == root / "02_Media" / "2023-12-15.png"
    assert moves[1][1] == 원본, "중간 경로가 아니라 원본이어야 한다"


def test_excluding_a_file_removes_its_whole_chain(tmp_path, profiles_dir):
    """사슬로 두 번 옮겨지는 파일을 빼면 두 동작이 **모두** 사라진다."""
    root = work(tmp_path)
    원본 = new_file(root / "2023-12-15.png")
    steps = [ROUTE, {"block": "by_date", "target": "02_Media", "layout": "{year}"}]

    before = build_plan(root, steps, today=TODAY, run_id="r1",
                        profiles_dir=profiles_dir, now=NOW)
    assert len([a for a in before.plan.actions if a.kind == "move"]) == 2, \
        "빼기 전에 이동이 둘이어야 이 테스트가 뭔가를 확인한다"

    built = build_plan(root, steps, today=TODAY, run_id="r1",
                       profiles_dir=profiles_dir, now=NOW, exclude={원본})

    assert [a for a in built.plan.actions if a.kind == "move"] == []


def test_the_origin_of_an_extraction_is_the_zip_itself(tmp_path, profiles_dir):
    """압축 해제 동작의 원본은 **압축 파일 자신**이다.

    그래서 zip 하나의 체크를 끄면 그 zip 을 아예 안 푼다 — 의도한 동작이다.
    """
    import zipfile
    root = work(tmp_path)
    zpath = root / "묶음.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("안.txt", "hi")
        z.writestr("사진.png", "x")

    built = build_plan(root, [{"block": "unzip", "delete_original": True}],
                       today=TODAY, run_id="r1", profiles_dir=profiles_dir, now=NOW)
    assert built.plan.actions, "계획이 비면 확인한 것이 없다"
    assert set(built.origins) == {zpath}

    뺐을때 = build_plan(root, [{"block": "unzip", "delete_original": True}],
                        today=TODAY, run_id="r1", profiles_dir=profiles_dir,
                        now=NOW, exclude={zpath})
    assert 뺐을때.plan.actions == [], "zip 체크를 끄면 그 zip 을 안 푼다"


def test_a_file_the_plan_will_create_has_no_origin(tmp_path, profiles_dir):
    """압축에서 나올 파일은 아직 디스크에 없다 — 그 경로로는 뺄 수가 없다.

    origin 을 주면 화면에 **눌러도 아무 일 없는 체크박스**가 생긴다.
    빼려면 그 zip 의 체크를 꺼야 한다.
    """
    import zipfile
    root = work(tmp_path)
    zpath = root / "묶음.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("안.md", "hi")

    built = build_plan(root, [{"block": "unzip"}, ROUTE], today=TODAY, run_id="r1",
                       profiles_dir=profiles_dir, now=NOW)

    옮김 = {a.src.name: o for a, o in zip(built.plan.actions, built.origins)
           if a.kind == "move"}
    assert "안.md" in 옮김, "압축에서 나온 파일이 분류돼야 한다"
    assert 옮김["안.md"] is None
    assert 옮김["묶음.zip"] == zpath, "디스크에 있는 zip 자신은 열쇠를 가진다"
    # 그 경로로 빼 달라고 해도 계획은 그대로다 — 그래서 열쇠를 주지 않는다.
    같음 = build_plan(root, [{"block": "unzip"}, ROUTE], today=TODAY, run_id="r1",
                     profiles_dir=profiles_dir, now=NOW, exclude={root / "안.md"})
    assert 같음.plan.actions == built.plan.actions


# ── 리뷰 1건(Major): 뺀 파일도, 스캐너가 거른 파일도 **이름은 차지하고 있다** ──
#
# 그 파일들은 계획에서 빠질 뿐 디스크에서 사라지지 않는다. 이름표에서까지
# 빼 버리면 미리보기가 "사진.png 로 간다" 고 약속하고 실행기는 덮어쓰지
# 않으려고 `사진_(1).png` 에 놓는다 — 데이터는 안전하지만 화면이 거짓말한다.


def test_an_excluded_file_still_holds_its_name_at_the_destination(
        tmp_path, profiles_dir):
    """미리보기에서 뺀 파일이 목적지에 앉아 있으면 그 이름은 차 있는 것이다."""
    root = work(tmp_path)
    옛것 = new_file(root / "02_Media" / "사진.png", b"OLD")
    new_file(root / "사진.png", b"NEW")

    안뺐을때 = build_plan(root, [ROUTE], today=TODAY, run_id="r1",
                          profiles_dir=profiles_dir, now=NOW)
    뺐을때 = build_plan(root, [ROUTE], today=TODAY, run_id="r1",
                        profiles_dir=profiles_dir, now=NOW, exclude={옛것})

    옮김 = [a for a in 뺐을때.plan.actions if a.kind == "move"]
    assert [a.src for a in 옮김] == [root / "사진.png"], \
        "계획이 비면 확인한 것이 없다"
    assert 옮김[0].dst == root / "02_Media" / "사진_(1).png"
    assert [a.dst for a in 옮김] == \
        [a.dst for a in 안뺐을때.plan.actions if a.kind == "move"
         and a.src == root / "사진.png"], "빼도 목적지 이름이 달라지면 안 된다"


def test_a_file_the_scanner_filtered_still_holds_its_name(tmp_path, profiles_dir):
    """exclude 를 안 써도 같은 병이다 — 스캐너가 거른 파일도 디스크에 있다.

    여기서만 `now` 가 NOW(1e12)가 아니다. 이 테스트는 스캐너가 **정말로 거르는**
    파일이 필요한데, 파일 시각을 1e12 로 밀어 넣을 수는 없다(파일 시스템이
    그 값을 못 담는다 — 실측했다). 그래서 목적지 파일의 진짜 시각에 10초를
    더한 값을 가짜 현재 시각으로 쓴다. 목적지 파일만 '1분 안' 에 들어오고,
    한 시간 전으로 돌린 원본은 정상적으로 스캔된다. 계획이 통째로 비는
    사고는 아래 두 assert 가 막는다.
    """
    root = work(tmp_path)
    방금 = new_file(root / "02_Media" / "사진.png", b"OLD")   # 시각 = 진짜 지금
    old_file(root / "사진.png", b"NEW")                        # 시각 = 한 시간 전
    지금 = 방금.stat().st_mtime + 10

    built = build_plan(root, [ROUTE], today=TODAY, run_id="r1",
                       profiles_dir=profiles_dir, now=지금)

    assert any(p == 방금 for p, _ in built.plan.skipped), \
        "스캐너가 정말로 거르는 파일이어야 이 테스트가 뭔가를 확인한다"
    옮김 = [a for a in built.plan.actions if a.kind == "move"]
    assert [a.src for a in 옮김] == [root / "사진.png"]
    assert 옮김[0].dst == root / "02_Media" / "사진_(1).png"


# ── 리뷰 3건(Minor): 스캔에 없는 제외 경로를 **드러낸다** ────────────────────
#
# 계획도 안 바뀌고 skipped 에도 안 남는 조용한 무작동이 이 프로젝트의 금기다.
# 거부하지는 않는다 — 파일은 두 미리보기 사이에 진짜로 사라질 수 있다.


def test_an_exclude_path_that_is_not_in_the_scan_is_carried_out(
        tmp_path, profiles_dir):
    root = work(tmp_path)
    new_file(root / "보고서.pdf")
    사라진것 = root / "이미지워짐.pdf"

    built = build_plan(root, [ROUTE], today=TODAY, run_id="r1",
                       profiles_dir=profiles_dir, now=NOW, exclude={사라진것})

    assert len(built.plan.actions) == 2, "계획이 비면 확인한 것이 없다(mkdir+move)"
    assert built.missing_excluded == [사라진것]


def test_exclude_paths_that_were_found_are_not_reported_as_missing(
        tmp_path, profiles_dir):
    root = work(tmp_path)
    빼기 = new_file(root / "가이드.pdf")
    new_file(root / "보고서.pdf")

    built = build_plan(root, [ROUTE], today=TODAY, run_id="r1",
                       profiles_dir=profiles_dir, now=NOW, exclude={빼기})

    assert (빼기, "제외함") in built.plan.skipped, "정말 빠진 것이어야 한다"
    assert built.missing_excluded == []


def test_not_excluding_anything_reports_nothing_missing(tmp_path, profiles_dir):
    root = work(tmp_path)
    new_file(root / "보고서.pdf")
    kw = dict(today=TODAY, run_id="r1", profiles_dir=profiles_dir, now=NOW)

    셋 = [build_plan(root, [ROUTE], **kw),
          build_plan(root, [ROUTE], **kw, exclude=None),
          build_plan(root, [ROUTE], **kw, exclude=set())]

    for built in 셋:
        # 계획이 비면 "빈 것 == 빈 것" 이라 아무것도 확인하지 못한다.
        assert len(built.plan.actions) == 2, "mkdir + move 가 있어야 한다"
        assert built.missing_excluded == []
