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


def test_dest_with_absolute_path_is_rejected():
    """dest='/etc' 처럼 절대경로를 쓰면 root 밖을 가리키게 된다."""
    c = ctx(e("보고서.pdf"))
    with pytest.raises(OrganizeError) as ex:
        build(c, cfg(dest="/etc"))
    assert "정리 대상 폴더 밖" in ex.value.message
    assert "route" in ex.value.message


def test_dest_with_dotdot_escape_is_rejected():
    """'../..' 로 상위 폴더를 타고 올라가는 것도 같은 이유로 막혀야 한다."""
    c = ctx(e("보고서.pdf"))
    with pytest.raises(OrganizeError) as ex:
        build(c, cfg(dest="../../etc"))
    assert "정리 대상 폴더 밖" in ex.value.message


def test_normal_relative_dest_still_works():
    """탈출 방지 검증이 정상적인 상대경로 dest 까지 막으면 안 된다."""
    c = ctx(e("보고서.pdf"))
    plan = build(c, cfg(dest="보관/2023"))
    move = next(a for a in plan.actions if a.kind == "move")
    assert move.dst == ROOT / "보관" / "2023" / "01_Docs" / "보고서.pdf"


def test_missing_profile_option_is_a_friendly_error():
    """options 에 profile 이 아예 없으면 KeyError 가 아니라 한국어 오류여야 한다."""
    c = ctx(e("보고서.pdf"))
    with pytest.raises(OrganizeError) as ex:
        build(c, BlockConfig())
    assert "route" in ex.value.message
    assert ex.value.hint and "profile" in ex.value.hint


def test_no_suffix_when_names_do_not_collide():
    """[B] 과잉 _(1) 방지 — 이름이 안 겹치는 평범한 경우엔 붙으면 안 된다."""
    c = ctx(e("보고서.pdf"), e("사진.png"))
    plan = build(c, cfg())
    names = {a.dst.name for a in plan.actions if a.kind == "move"}
    assert names == {"보고서.pdf", "사진.png"}


def test_first_file_into_an_empty_destination_keeps_its_name():
    """[B] 목적지 폴더가 비어 있으면 첫 파일은 원래 이름 그대로여야 한다."""
    c = ctx(e("사진.png"))
    plan = build(c, cfg())
    move = next(a for a in plan.actions if a.kind == "move")
    assert move.dst.name == "사진.png"


def test_two_files_with_the_same_name_from_different_folders_get_distinct_destinations():
    """Task 16 리뷰 Critical 재현: 같은 이름 파일 둘을 같은 폴더로 보내면
    실행기의 remap(경로 하나당 값 하나) 이 둘을 구분하지 못한다. 미리보기
    Plan 자체가 서로 다른 dst 를 가리켜야 한다.

    runner.build_plan 과 똑같이, 첫 route 의 결과를 ctx.apply() 로 반영한
    뒤 두 번째 route 를 빌드해야 두 번째 호출이 첫 번째의 결과를 본다."""
    c = ctx(e("하위1/사진.png"), e("하위2/사진.png"))
    plan1 = build(c, cfg(target="하위1", dest=""))
    c.apply(plan1)
    plan2 = build(c, cfg(target="하위2", dest=""))

    dst1 = next(a.dst for a in plan1.actions if a.kind == "move")
    dst2 = next(a.dst for a in plan2.actions if a.kind == "move")
    assert dst1 == ROOT / "02_Media" / "사진.png"
    assert dst2 == ROOT / "02_Media" / "사진_(1).png"
    assert dst1 != dst2


def test_profile_to_with_absolute_path_is_rejected():
    """프로파일의 to='/etc' 도 같은 구멍이다 — dest 뿐 아니라 to 도 사용자가 손으로 쓴다."""
    escape_profile = Profile(name="탈출", rules=[
        Rule(to="/etc", conditions={}, is_default=True),
    ])
    c = ctx(e("보고서.pdf"))
    with pytest.raises(OrganizeError) as ex:
        build(c, BlockConfig(options={"profile": escape_profile}))
    assert "정리 대상 폴더 밖" in ex.value.message
