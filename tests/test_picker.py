"""폴더 고르기 — 창 없이 테스트되는 부분."""

import json
import os
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


# ── 폴더를 탐색기로 열기 ─────────────────────────────────────────
# 실제로 탐색기를 띄우는 부분은 자동으로 확인할 수 없다. **무엇을 부를지**와
# **못 열 때 어떻게 알리는지**만 여기서 확인한다.

def test_open_command_는_OS_마다_다른_것을_부른다():
    assert picker.open_command("Darwin") == ["open"]
    assert picker.open_command("Linux") == ["xdg-open"]


def test_open_command_WSL_은_윈도우_탐색기를_부른다():
    """WSL 의 xdg-open 은 리눅스 파일 관리자를 찾는다 — 눌러도 아무 일이 없다."""
    assert picker.open_command("Linux", wsl=True) == ["explorer.exe"]


def test_open_folder_없는_폴더는_열지_않고_한국어로_알린다(tmp_path):
    """부르는 쪽이 링크를 안 그려도, 그 사이에 USB 가 뽑혔을 수 있다."""
    with pytest.raises(OrganizeError) as ex:
        picker.open_folder(tmp_path / "없는폴더")
    assert "찾을 수 없습니다" in ex.value.message
    assert "USB" in (ex.value.hint or ""), "왜 없을 수 있는지 짚어 줘야 한다"


def _리눅스인_척(monkeypatch, 부른것):
    """윈도우도 WSL 도 아닌 척한다.

    셋을 갈라 두지 않으면 테스트가 **개발한 PC 에서만** 도는 것을 확인하게 된다
    (여기는 WSL 이라 `wslpath` 를 부르러 간다).
    """
    monkeypatch.delattr(os, "startfile", raising=False)
    monkeypatch.setattr(picker, "is_wsl", lambda: False)
    monkeypatch.setattr(picker.subprocess, "Popen",
                        lambda cmd, **kw: 부른것.append(cmd))


def test_open_folder_여는_프로그램이_없으면_경로를_알려_준다(tmp_path, monkeypatch):
    """못 열면 손으로라도 갈 수 있어야 한다 — 그러려면 경로가 보여야 한다."""
    def 없는척(*a, **kw):
        raise FileNotFoundError("xdg-open")

    monkeypatch.delattr(os, "startfile", raising=False)
    monkeypatch.setattr(picker, "is_wsl", lambda: False)
    monkeypatch.setattr(picker.subprocess, "Popen", 없는척)

    with pytest.raises(OrganizeError) as ex:
        picker.open_folder(tmp_path)
    assert str(tmp_path) in (ex.value.hint or "")


def test_open_folder_열었으면_조용히_돌아온다(tmp_path, monkeypatch):
    부른것 = []
    _리눅스인_척(monkeypatch, 부른것)

    picker.open_folder(tmp_path)

    assert 부른것 == [["xdg-open", str(tmp_path)]]


def test_open_folder_윈도우에서는_startfile_을_쓴다(tmp_path, monkeypatch):
    """`explorer` 는 **성공해도 종료 코드 1** 이라 명령으로 부르면 구별이 안 된다."""
    연것 = []
    monkeypatch.setattr(os, "startfile", 연것.append, raising=False)
    monkeypatch.setattr(picker.subprocess, "Popen",
                        lambda *a, **kw: pytest.fail("startfile 이 있으면 명령을 부르지 않는다"))

    picker.open_folder(tmp_path)

    assert 연것 == [str(tmp_path)]


# ── 파일을 탐색기에서 골라서 열기 ────────────────────────────────
# **파일을 실행하지 않는다.** 다운로드 폴더를 정리하면 중복 .exe 가 나오는데,
# 확인하려고 누른 것이 설치 프로그램을 띄우면 안 된다.

def test_reveal_command_윈도우는_select_로_고른다():
    assert picker.reveal_command("Windows") == ["explorer", "/select,"]


def test_reveal_command_wsl_은_exe_를_부른다():
    assert picker.reveal_command("Linux", wsl=True) == ["explorer.exe", "/select,"]


def test_reveal_command_그_외에는_선택_없이_폴더만():
    """맥·리눅스에는 '그 파일을 골라서' 를 시키는 표준이 없다."""
    assert picker.reveal_command("Darwin") == ["open"]
    assert picker.reveal_command("Linux") == ["xdg-open"]


def test_reveal_file_없는_파일이면_한국어로_알린다(tmp_path):
    with pytest.raises(OrganizeError) as e:
        picker.reveal_file(tmp_path / "없는파일.pdf")

    assert "찾을 수 없" in e.value.message
    assert e.value.hint


def test_reveal_file_폴더를_주면_거절한다(tmp_path):
    """폴더는 open_folder 가 연다. 여기로 오면 부르는 쪽이 틀린 것이다."""
    with pytest.raises(OrganizeError):
        picker.reveal_file(tmp_path)


def test_reveal_file_그_외_OS_에서는_부모_폴더를_연다(tmp_path, monkeypatch):
    파일 = tmp_path / "보고서.pdf"
    파일.write_bytes(b"X")
    부른것 = {}
    monkeypatch.setattr(picker, "is_wsl", lambda: False)
    monkeypatch.setattr(picker.platform, "system", lambda: "Linux")
    monkeypatch.delattr(picker.os, "startfile", raising=False)

    class Shim:
        Popen = staticmethod(lambda cmd, **kw: 부른것.update(cmd=cmd))
        DEVNULL = None
    monkeypatch.setattr(picker, "subprocess", Shim)

    picker.reveal_file(파일)

    assert 부른것["cmd"] == ["xdg-open", str(tmp_path)], "부모 폴더를 연다"
