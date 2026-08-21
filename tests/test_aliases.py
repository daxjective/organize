from pathlib import Path

from organize import aliases


def test_builtin_names_are_the_seven_standard_folders():
    assert aliases.BUILTIN == (
        "home", "desktop", "downloads", "documents", "pictures", "music", "videos",
    )


def test_unknown_name_returns_none():
    assert aliases.builtin_path("archive") is None


def test_home_uses_pathlib_home(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert aliases.builtin_path("home") == tmp_path


def test_windows_asks_the_os_not_the_home_folder(monkeypatch, tmp_path):
    """OneDrive 로 리디렉션된 경로가 나와도 그대로 써야 한다."""
    redirected = tmp_path / "OneDrive" / "바탕 화면"
    monkeypatch.setattr(aliases.sys, "platform", "win32")
    monkeypatch.setattr(aliases, "_windows_known_folder", lambda guid: redirected)
    assert aliases.builtin_path("desktop") == redirected


def test_windows_falls_back_to_home_when_os_call_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(aliases.sys, "platform", "win32")
    monkeypatch.setattr(aliases, "_windows_known_folder", lambda guid: None)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert aliases.builtin_path("desktop") == tmp_path / "Desktop"


def test_posix_uses_xdg_lookup(monkeypatch, tmp_path):
    monkeypatch.setattr(aliases.sys, "platform", "linux")
    monkeypatch.setattr(aliases, "_posix_path", lambda name: tmp_path / "내려받기")
    assert aliases.builtin_path("downloads") == tmp_path / "내려받기"
