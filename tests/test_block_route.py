from datetime import date
from pathlib import Path

import pytest

from organize.blocks import BlockConfig, get_block
from organize.blocks.route import build
from organize.core.context import Context
from organize.core.scanner import FileEntry
from organize.errors import OrganizeError
from organize.profiles import Profile, Rule

TODAY = date(2026, 8, 21)
ROOT = Path("/작업")

PROFILE = Profile(name="테스트", rules=[
    Rule(to="01_Docs", conditions={"ext": [".pdf", ".md"]}),
    Rule(to="02_Media", conditions={"ext": [".png", ".jpg"]}),
    Rule(to="99_Unsorted", conditions={}, is_default=True),
])


def e(rel, size=10):
    return FileEntry(path=ROOT / rel, size=size, mtime=0.0)


def ctx(*entries):
    return Context(root=ROOT, entries=list(entries), today=TODAY)


def cfg(**kw):
    kw.setdefault("options", {"profile": PROFILE})
    return BlockConfig(**kw)


def test_registry_has_route():
    assert get_block("route") is not None


def test_unknown_block_is_a_friendly_error():
    with pytest.raises(OrganizeError) as ex:
        get_block("없는블록")
    assert "없는블록" in ex.value.message


def test_files_go_to_their_category():
    c = ctx(e("보고서.pdf"), e("사진.png"))
    plan = build(c, cfg())
    moves = {a.src.name: a.dst.parent.name for a in plan.actions if a.kind == "move"}
    assert moves == {"보고서.pdf": "01_Docs", "사진.png": "02_Media"}


def test_unmatched_file_goes_to_default():
    c = ctx(e("무엇.xyz"))
    plan = build(c, cfg())
    assert [a.dst.parent.name for a in plan.actions if a.kind == "move"] == ["99_Unsorted"]


def test_mkdir_actions_come_before_moves_and_are_unique():
    c = ctx(e("a.pdf"), e("b.pdf"), e("c.png"))
    plan = build(c, cfg())
    kinds = [a.kind for a in plan.actions]
    assert kinds.index("mkdir") < kinds.index("move")
    mkdirs = sorted(a.dst.name for a in plan.actions if a.kind == "mkdir")
    assert mkdirs == ["01_Docs", "02_Media"]


def test_reason_explains_why():
    c = ctx(e("사진.png"))
    plan = build(c, cfg())
    move = next(a for a in plan.actions if a.kind == "move")
    assert ".png" in move.reason and "02_Media" in move.reason


def test_when_filter_limits_the_files():
    c = ctx(e("보고서.pdf"), e("사진.png"))
    plan = build(c, cfg(when={"ext": [".pdf"]}))
    assert [a.src.name for a in plan.actions if a.kind == "move"] == ["보고서.pdf"]
    assert [p.name for p, _ in plan.skipped] == ["사진.png"]


def test_only_files_at_target_are_touched():
    c = ctx(e("위.pdf"), e("하위/아래.pdf"))
    plan = build(c, cfg())
    assert [a.src.name for a in plan.actions if a.kind == "move"] == ["위.pdf"]


def test_dest_sends_results_elsewhere():
    c = ctx(e("보고서.pdf"))
    plan = build(c, cfg(dest="보관"))
    move = next(a for a in plan.actions if a.kind == "move")
    assert move.dst == ROOT / "보관" / "01_Docs" / "보고서.pdf"


def test_file_already_in_its_category_is_left_alone():
    """재실행해도 폴더가 중첩되지 않아야 한다."""
    c = ctx(e("01_Docs/보고서.pdf"))
    plan = build(c, BlockConfig(target="01_Docs", options={"profile": PROFILE}))
    assert [a for a in plan.actions if a.kind == "move"] == []


def test_dest_still_moves_a_file_that_is_already_in_that_category():
    """dest 를 콕 집어 말했으면, 같은 이름 폴더에 있더라도 그리로 옮긴다.

    '이미 제자리' 판정이 dest 를 안 보면 이 파일은 영영 안 움직인다.
    """
    c = ctx(e("01_Docs/보고서.pdf"))
    plan = build(c, cfg(target="01_Docs", dest="보관"))
    move = next(a for a in plan.actions if a.kind == "move")
    assert move.src == ROOT / "01_Docs" / "보고서.pdf"
    assert move.dst == ROOT / "보관" / "01_Docs" / "보고서.pdf"


def test_dest_leaves_a_file_that_is_already_at_the_destination():
    """반대로 이미 목적지에 도착해 있으면 건드리지 않는다."""
    c = ctx(e("보관/01_Docs/보고서.pdf"))
    plan = build(c, cfg(target="보관/01_Docs", dest="보관"))
    assert [a for a in plan.actions if a.kind == "move"] == []
