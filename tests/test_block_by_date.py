from datetime import date, datetime
from pathlib import Path

from organize.blocks import BlockConfig
from organize.blocks.by_date import build
from organize.core.context import Context
from organize.core.scanner import FileEntry

TODAY = date(2026, 8, 21)
ROOT = Path("/작업")


def e(rel, mtime_date=(2024, 3, 9)):
    stamp = datetime(*mtime_date).timestamp()
    return FileEntry(path=ROOT / rel, size=10, mtime=stamp)


def ctx(*entries):
    return Context(root=ROOT, entries=list(entries), today=TODAY)


def moves(plan):
    return {a.src.name: a.dst.parent.relative_to(ROOT).as_posix()
            for a in plan.actions if a.kind == "move"}


def test_year_layout_uses_name_date():
    plan = build(ctx(e("2023-12-15 회의록.md")), BlockConfig())
    assert moves(plan) == {"2023-12-15 회의록.md": "2023"}


def test_year_month_layout():
    plan = build(ctx(e("2023-12-15 회의록.md")), BlockConfig(options={"layout": "{year}/{month}"}))
    assert moves(plan) == {"2023-12-15 회의록.md": "2023/12"}


def test_falls_back_to_mtime_when_name_has_no_date():
    plan = build(ctx(e("회의록.md", mtime_date=(2024, 3, 9))), BlockConfig())
    assert moves(plan) == {"회의록.md": "2024"}


def test_resolution_in_filename_is_not_a_year():
    """기존 스크립트가 1920년 폴더로 보내던 파일."""
    plan = build(ctx(e("screenshot_1920x1080.png", mtime_date=(2025, 5, 5))), BlockConfig())
    assert moves(plan) == {"screenshot_1920x1080.png": "2025"}


def test_reason_says_where_the_date_came_from():
    plan = build(ctx(e("2023-12-15.md")), BlockConfig())
    move = next(a for a in plan.actions if a.kind == "move")
    assert "파일명 날짜" in move.reason and "2023-12-15" in move.reason


def test_dest_sends_year_folders_elsewhere():
    plan = build(ctx(e("2023-12-15.md")), BlockConfig(dest="보관"))
    move = next(a for a in plan.actions if a.kind == "move")
    assert move.dst == ROOT / "보관" / "2023" / "2023-12-15.md"


def test_when_filter_limits_the_files():
    plan = build(ctx(e("2023-12-15.md"), e("2023-12-15.png")),
                 BlockConfig(when={"ext": [".md"]}))
    assert list(moves(plan)) == ["2023-12-15.md"]


def test_files_already_in_their_year_folder_are_left_alone():
    """재실행해도 2026/2026 처럼 중첩되지 않아야 한다."""
    plan = build(ctx(e("2023/2023-12-15.md")), BlockConfig(target="2023"))
    assert moves(plan) == {}


def test_virtual_files_use_name_or_mtime_without_crashing():
    v = FileEntry(path=ROOT / "2023-12-15 문서.pdf", size=0, mtime=0.0, virtual=True)
    plan = build(ctx(v), BlockConfig())
    assert moves(plan) == {"2023-12-15 문서.pdf": "2023"}


def test_mkdir_precedes_moves():
    plan = build(ctx(e("2023-12-15.md")), BlockConfig())
    kinds = [a.kind for a in plan.actions]
    assert kinds.index("mkdir") < kinds.index("move")
