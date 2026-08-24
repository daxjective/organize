from datetime import date
from pathlib import Path

import pytest

from organize.core.action import Action, Plan
from organize.core.context import Context
from organize.core.scanner import FileEntry
from organize.errors import OrganizeError

TODAY = date(2026, 8, 21)
ROOT = Path("/작업")


def e(rel_path, size=10):
    return FileEntry(path=ROOT / rel_path, size=size, mtime=0.0)


def ctx(*entries):
    return Context(root=ROOT, entries=list(entries), today=TODAY)


def move(entry, dst_rel, block="route", src=None):
    # 실제 블록은 언제나 ctx.current_path(entry) 를 넘긴다. 이미 한 번 옮겨진 파일에
    # 원래 경로를 넘기면 Context 가 못 찾아 이동이 무시된다 — 그게 정상 동작이다.
    # 두 번째 이동을 시험하는 테스트는 반드시 src= 를 명시해야 한다.
    return Action(kind="move", src=src or entry.path, dst=ROOT / dst_rel,
                  reason="테스트", block=block)


def test_files_at_root_are_direct_children_only():
    c = ctx(e("a.png"), e("하위/b.png"))
    assert [x.name for x in c.files_at("")] == ["a.png"]


def test_files_at_subfolder():
    c = ctx(e("a.png"), e("하위/b.png"))
    assert [x.name for x in c.files_at("하위")] == ["b.png"]


def test_apply_move_changes_where_the_file_is():
    a = e("a.png")
    c = ctx(a)
    plan = Plan(actions=[move(a, "02_Media/a.png")])
    c.apply(plan)
    assert c.files_at("") == []
    assert [x.name for x in c.files_at("02_Media")] == ["a.png"]
    assert c.rel_of(a) == "02_Media"
    assert c.current_path(a) == ROOT / "02_Media" / "a.png"


def test_two_moves_in_a_row_chain():
    a = e("a.png")
    c = ctx(a)
    c.apply(Plan(actions=[move(a, "02_Media/a.png")]))
    c.apply(Plan(actions=[move(a, "02_Media/캡처/a.png", block="route2",
                              src=c.current_path(a))]))
    assert c.rel_of(a) == "02_Media/캡처"
    assert c.current_path(a) == ROOT / "02_Media" / "캡처" / "a.png"


def test_quarantined_file_disappears_from_the_view():
    a = e("a.png")
    c = ctx(a)
    c.apply(Plan(actions=[Action(kind="quarantine", src=a.path,
                                 dst=ROOT / ".organize/trash/x/a.png",
                                 reason="중복", block="dedup")]))
    assert c.files_at("") == []
    assert c.all_files() == []


def test_extract_adds_a_virtual_file():
    c = ctx(e("묶음.zip"))
    c.apply(Plan(actions=[Action(kind="extract", src=ROOT / "묶음.zip",
                                 dst=ROOT / "사진.png", reason="압축 해제", block="unzip")]))
    names = [x.name for x in c.files_at("")]
    assert "사진.png" in names
    assert next(x for x in c.files_at("") if x.name == "사진.png").virtual is True


def test_mkdir_does_not_change_the_file_view():
    a = e("a.png")
    c = ctx(a)
    c.apply(Plan(actions=[Action(kind="mkdir", src=None, dst=ROOT / "02_Media",
                                 reason="폴더", block="route")]))
    assert [x.name for x in c.files_at("")] == ["a.png"]


def test_files_are_returned_in_a_stable_order():
    c = ctx(e("나.png"), e("가.png"), e("다.png"))
    assert [x.name for x in c.files_at("")] == ["가.png", "나.png", "다.png"]


def test_a_file_can_be_moved_more_than_once():
    """route → by_date 처럼 블록이 이어질 때 두 번째 이동이 반영되어야 한다.

    Action.src 는 '지금 위치' 이고 내부 장부의 키는 '원래 위치' 다.
    둘을 잇는 표가 없으면 두 번째 이동부터 조용히 무시된다.
    """
    entry = e("사진.png")
    c = ctx(entry)

    c.apply(Plan(actions=[Action("move", ROOT / "사진.png",
                                 ROOT / "02_Media" / "사진.png", "route", "route")]))
    assert c.rel_of(entry) == "02_Media"

    c.apply(Plan(actions=[Action("move", ROOT / "02_Media" / "사진.png",
                                 ROOT / "02_Media" / "2026" / "사진.png", "by_date", "by_date")]))
    assert c.rel_of(entry) == "02_Media/2026"
    assert c.current_path(entry) == ROOT / "02_Media" / "2026" / "사진.png"
    assert c.files_at("02_Media/2026") == [entry]
    assert c.files_at("02_Media") == []


def test_move_that_renames_is_tracked():
    """이름 충돌로 _(1) 이 붙어도 그 파일을 계속 따라가야 한다."""
    entry = e("a.png")
    c = ctx(entry)
    c.apply(Plan(actions=[Action("move", ROOT / "a.png",
                                 ROOT / "02_Media" / "a_(1).png", "충돌", "route")]))
    assert c.current_path(entry) == ROOT / "02_Media" / "a_(1).png"


def test_quarantine_after_a_move_removes_the_file():
    entry = e("b.png")
    c = ctx(entry)
    c.apply(Plan(actions=[Action("move", ROOT / "b.png",
                                 ROOT / "02_Media" / "b.png", "route", "route")]))
    c.apply(Plan(actions=[Action("quarantine", ROOT / "02_Media" / "b.png",
                                 ROOT / ".organize" / "trash" / "b.png", "중복", "dedup")]))
    assert c.all_files() == []


def test_extracted_virtual_file_can_then_be_routed():
    c = ctx()
    c.apply(Plan(actions=[Action("extract", ROOT / "자료.zip",
                                 ROOT / "문서.pdf", "압축 해제", "unzip")]))
    virtual = c.files_at("")[0]
    assert virtual.virtual is True
    c.apply(Plan(actions=[Action("move", ROOT / "문서.pdf",
                                 ROOT / "01_Docs" / "문서.pdf", "route", "route")]))
    assert c.rel_of(virtual) == "01_Docs"


def test_context_without_run_id_can_still_be_built():
    """run_id 는 trash_dir 을 쓸 때만 필요하다. Context 생성 자체는 막지 않는다."""
    c = ctx(e("a.png"))
    assert c.run_id == ""
    assert [x.name for x in c.files_at("")] == ["a.png"]


def test_trash_dir_without_run_id_is_a_friendly_error():
    """빈 run_id 로 trash_dir 을 만들면 pathlib 이 조각을 접어 '.organize/trash' 자체가
    되어버린다 — 실행마다 같은 폴더에 쌓여 undo 가 어느 실행 것인지 알 수 없다."""
    c = ctx(e("a.png"))
    with pytest.raises(OrganizeError) as ex:
        c.trash_dir
    assert "실행 번호" in ex.value.message


def test_trash_dir_with_run_id_is_the_run_folder():
    c = Context(root=ROOT, entries=[], today=TODAY, run_id="20260821-143210")
    assert c.trash_dir == ROOT / ".organize" / "trash" / "20260821-143210"


# --- 수정 라운드 1/5: claim_name — 블록이 같은 dst 를 가리키는 동작을 두 개
# 만들지 못하게 이름을 미리 잡는다 (Task 16 리뷰 Critical) ---


def test_claim_name_keeps_the_name_when_the_folder_is_free():
    c = ctx()
    assert c.claim_name("02_Media", "사진.png") == "사진.png"


def test_claim_name_avoids_collision_with_an_existing_file():
    c = ctx(e("02_Media/사진.png"))
    assert c.claim_name("02_Media", "사진.png") == "사진_(1).png"


def test_claim_name_ignores_case_like_windows_does():
    """윈도우가 주 사용 환경이다 — A.PNG 와 a.png 는 같은 파일로 본다."""
    c = ctx(e("02_Media/사진.PNG"))
    assert c.claim_name("02_Media", "사진.png") == "사진_(1).png"


def test_claim_name_remembers_names_it_already_gave_out_in_this_plan():
    c = ctx()
    first = c.claim_name("02_Media", "사진.png")
    second = c.claim_name("02_Media", "사진.png")
    assert first == "사진.png"
    assert second == "사진_(1).png"


def test_claim_name_is_independent_per_folder():
    c = ctx()
    assert c.claim_name("02_Media", "사진.png") == "사진.png"
    assert c.claim_name("03_Docs", "사진.png") == "사진.png"


def test_claim_name_does_not_know_about_moves_not_yet_applied_in_this_plan():
    """claim_name 은 Context 의 '지금' 상태만 본다. 같은 폴더를 떠날 예정인
    파일이 있어도 apply() 전이라면 여전히 그 폴더를 차지한 것으로 본다 —
    보수적인 쪽으로 치우친 선택이다(안전하게 _(1) 을 더 붙이는 쪽이지,
    이름을 잘못 비워주는 쪽이 아니다). route/by_date 는 목적지(rel)를 항상
    target 의 진짜 하위 경로로만 만들어서(같은 값이 될 수 없다) 이 상황
    자체가 안 생긴다 — 여기서는 Context 단독 동작만 기록해 둔다."""
    leaving = e("02_Media/사진.png")     # 곧 다른 곳으로 옮겨질 예정(아직 미적용)
    c = ctx(leaving)
    assert c.claim_name("02_Media", "사진.png") == "사진_(1).png"


def test_claim_name_treats_the_same_folder_as_one_ledger():
    """같은 폴더를 가리키는 문자열이 여러 가지다 — 이름표가 갈라지면 안 된다.

    `02_Media`, `02_Media/`, `./02_Media`, 그리고 윈도우에서는 `02_media` 까지
    전부 같은 폴더다. 정규화하지 않으면 한 폴더에 이름표가 여러 개 생겨
    서로를 못 보고, 미리보기에 같은 목적지가 두 번 나온다.
    """
    ctx = Context(root=Path("/작업"), entries=[], today=date(2026, 8, 21))
    spellings = ["02_Media", "02_Media/", "./02_Media", "02_media",
                 "02_Media\\", "02_Media/../02_Media"]
    got = [ctx.claim_name(rel, "사진.png") for rel in spellings]
    assert len(set(got)) == len(got), f"이름표가 갈라졌다: {got}"


def test_claim_name_keeps_different_folders_apart():
    """반대로 진짜 다른 폴더끼리는 서로 영향을 주면 안 된다."""
    ctx = Context(root=Path("/작업"), entries=[], today=date(2026, 8, 21))
    assert ctx.claim_name("01_Docs", "a.txt") == "a.txt"
    assert ctx.claim_name("02_Media", "a.txt") == "a.txt"


def test_claim_name_handles_the_root_folder():
    ctx = Context(root=Path("/작업"), entries=[], today=date(2026, 8, 21))
    assert ctx.claim_name("", "a.txt") == "a.txt"
    assert ctx.claim_name(".", "a.txt") == "a_(1).txt"
