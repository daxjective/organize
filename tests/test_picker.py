"""폴더 고르기 — 창 없이 테스트되는 부분."""

import json
from pathlib import Path

import pytest

from organize import picker
from organize.errors import OrganizeError


def test_a_picked_folder_is_stored_under_its_name(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    usb = tmp_path / "USB"
    usb.mkdir()

    picker.store_picked_path(repo, "백업", usb)

    saved = json.loads((repo / "config.local.json").read_text(encoding="utf-8"))
    assert saved["paths"]["백업"] == str(usb)


def test_storing_keeps_what_was_already_there(tmp_path):
    """이미 등록한 다른 위치를 날리지 않는다."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "config.local.json").write_text(
        json.dumps({"paths": {"사진": "/어딘가"}}, ensure_ascii=False), encoding="utf-8")
    usb = tmp_path / "USB"
    usb.mkdir()

    picker.store_picked_path(repo, "백업", usb)

    saved = json.loads((repo / "config.local.json").read_text(encoding="utf-8"))
    assert saved["paths"]["사진"] == "/어딘가"
    assert saved["paths"]["백업"] == str(usb)


def test_a_folder_that_vanished_between_picking_and_saving_is_refused(tmp_path):
    """USB 는 고르고 저장하는 사이에 뽑힐 수 있다. 없는 곳을 등록하면 안 된다."""
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(OrganizeError) as ex:
        picker.store_picked_path(repo, "백업", tmp_path / "뽑힌USB")
    assert "찾을 수 없" in ex.value.message
    assert not (repo / "config.local.json").exists(), "거부했으면 저장도 안 한다"


@pytest.mark.parametrize("이름", ["", "   "])
def test_an_empty_name_is_refused(tmp_path, 이름):
    repo = tmp_path / "repo"
    repo.mkdir()
    usb = tmp_path / "USB"
    usb.mkdir()
    with pytest.raises(OrganizeError):
        picker.store_picked_path(repo, 이름, usb)


def test_can_open_window_never_raises():
    """tkinter 가 없어도 이 검사 자체는 죽지 않아야 한다."""
    assert isinstance(picker.can_open_window(), bool)


def test_asking_without_tkinter_is_a_korean_message(monkeypatch):
    """tkinter 가 없는 PC 에서도 파이썬 예외가 아니라 한국어로 안내한다."""
    import builtins
    real = builtins.__import__

    def 없는척(name, *a, **kw):
        if name.startswith("tkinter"):
            raise ImportError("no tkinter")
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", 없는척)

    with pytest.raises(OrganizeError) as ex:
        picker.ask_folder()
    assert "tkinter" in ex.value.message
    assert "paths --set" in (ex.value.hint or ""), "창 없이 하는 법을 알려줘야 한다"
