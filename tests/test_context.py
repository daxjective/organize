from datetime import date
from pathlib import Path

from organize.core.action import Action, Plan
from organize.core.context import Context
from organize.core.scanner import FileEntry

TODAY = date(2026, 8, 21)
ROOT = Path("/작업")


def e(rel_path, size=10):
    return FileEntry(path=ROOT / rel_path, size=size, mtime=0.0)


def ctx(*entries):
    return Context(root=ROOT, entries=list(entries), today=TODAY)


def move(entry, dst_rel, block="route"):
    return Action(kind="move", src=entry.path, dst=ROOT / dst_rel, reason="테스트", block=block)


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
    c.apply(Plan(actions=[move(a, "02_Media/캡처/a.png", block="route2")]))
    assert c.rel_of(a) == "02_Media/캡처"


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
