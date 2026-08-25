"""블록들이 함께 쓰는 것들 — 특히 목적지 판정(dest_folder)."""

from datetime import date

import pytest

from organize.blocks import dest_folder
from organize.core.context import Context
from organize.errors import OrganizeError

TODAY = date(2026, 8, 25)

# ── 다른 드라이브로 보내기 ─────────────────────────────────────────
# 이 도구를 만든 이유가 백업이다. SD카드·USB 로 내보내는 것이 포함된다.
# 다만 **손으로 쓴 경로로는 못 나간다** — 등록한 이름으로만 나간다.
# 오타 하나로 파일이 흩어지는 사고를 원천적으로 막기 위해서다.

def test_a_registered_name_can_send_files_outside_the_root(tmp_path):
    """`@백업` 처럼 등록된 이름은 정리 대상 폴더 밖을 가리킬 수 있다."""
    root = tmp_path / "작업"
    root.mkdir()
    백업 = tmp_path / "USB" / "정리"
    ctx = Context(root=root, entries=[], today=TODAY, run_id="r1",
                  external={"백업": 백업})

    got = dest_folder(ctx, "@백업", block="route")

    assert got == 백업
    assert not got.is_relative_to(root), "밖으로 나가는 것이 이 기능의 목적이다"


def test_a_registered_name_can_have_a_subfolder(tmp_path):
    root = tmp_path / "작업"
    root.mkdir()
    ctx = Context(root=root, entries=[], today=TODAY, run_id="r1",
                  external={"백업": tmp_path / "USB"})
    assert dest_folder(ctx, "@백업/2026", block="by_date") == tmp_path / "USB" / "2026"


def test_an_unregistered_name_is_refused_with_how_to_register(tmp_path):
    """등록 안 한 이름은 거부한다 — 등록하는 법을 알려준다."""
    root = tmp_path / "작업"
    root.mkdir()
    ctx = Context(root=root, entries=[], today=TODAY, run_id="r1", external={})

    with pytest.raises(OrganizeError) as ex:
        dest_folder(ctx, "@없는것", block="route")

    assert "없는것" in ex.value.message
    assert "paths --set" in (ex.value.hint or ""), "등록하는 명령을 알려줘야 한다"


@pytest.mark.parametrize("나쁜값", ["/etc", "../밖", "~/집", "C:/Windows", "..\\밖"])
def test_a_hand_written_path_still_cannot_escape(tmp_path, 나쁜값):
    """**손으로 쓴 경로로는 여전히 못 나간다.** 이걸 열어 주면 오타 하나로
    파일이 엉뚱한 곳에 흩어진다. 등록이라는 한 단계가 곧 안전장치다."""
    root = tmp_path / "작업"
    root.mkdir()
    ctx = Context(root=root, entries=[], today=TODAY, run_id="r1",
                  external={"백업": tmp_path / "USB"})

    # 지켜야 할 성질은 "예외가 난다" 가 아니라 **밖으로 못 나간다** 이다.
    # `..\\밖` 은 윈도우에서만 탈출이 되고 리눅스에서는 그냥 이상한 폴더
    # 이름이 된다 — 어느 쪽이든 root 밖으로 나가지 않아야 한다.
    try:
        got = dest_folder(ctx, 나쁜값, block="route")
    except OrganizeError as ex:
        assert "밖" in ex.value.message if hasattr(ex, "value") else True
        return
    assert got.is_relative_to(root), f"손으로 쓴 경로가 밖으로 나갔다: {got}"
    assert got != tmp_path / "USB", "등록된 곳으로도 새면 안 된다"


def test_the_at_sign_alone_is_not_a_name(tmp_path):
    root = tmp_path / "작업"
    root.mkdir()
    ctx = Context(root=root, entries=[], today=TODAY, run_id="r1", external={})
    with pytest.raises(OrganizeError):
        dest_folder(ctx, "@", block="route")
