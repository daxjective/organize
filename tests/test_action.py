from pathlib import Path

import pytest

from organize.core.action import Action, Plan


def make(kind="move", src="a.png", dst="02_Media/a.png"):
    return Action(kind=kind, src=Path(src) if src is not None else None, dst=Path(dst) if dst is not None else None, reason="확장자 .png", block="route")


def test_action_is_immutable():
    a = make()
    with pytest.raises(Exception):
        a.reason = "다른 이유"


def test_counts_groups_by_kind():
    plan = Plan()
    plan.actions.extend([make(), make(), make(kind="quarantine")])
    assert plan.counts() == {"move": 2, "quarantine": 1}


def test_counts_of_empty_plan_is_empty():
    assert Plan().counts() == {}


def test_extend_merges_actions_and_skipped():
    a, b = Plan(), Plan()
    a.actions.append(make())
    a.skipped.append((Path("x.txt"), "대상이 아님"))
    b.actions.append(make(kind="mkdir", src=None, dst="02_Media"))
    b.skipped.append((Path("y.txt"), "시스템 파일"))
    a.extend(b)
    assert len(a.actions) == 2
    assert len(a.skipped) == 2


def test_mkdir_action_has_no_src():
    a = Action(kind="mkdir", src=None, dst=Path("02_Media"), reason="분류 결과를 담을 폴더", block="route")
    assert a.src is None
    assert a.member is None


def test_extract_action_carries_the_member_name():
    a = Action(kind="extract", src=Path("자료.zip"), dst=Path("문서.pdf"),
               reason="자료.zip 에서 꺼냄", block="unzip", member="안쪽폴더/문서.pdf")
    assert a.member == "안쪽폴더/문서.pdf"
