"""내장 별칭을 OS 에 물어 실제 경로로 바꾼다.

하드코딩하지 않는 이유: Windows 에서 OneDrive 백업을 켜면
바탕화면이 `C:\\Users\\<이름>\\OneDrive\\바탕 화면` 으로 리디렉션된다.
`~/Desktop` 을 쓰면 그 PC 에서 엉뚱한 빈 폴더를 정리하게 된다.
"""

import os
import sys
from pathlib import Path

# Windows KNOWNFOLDERID
_FOLDERID = {
    "desktop":   "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "pictures":  "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "music":     "{4BD8D571-6D19-48D3-BE97-422220080E43}",
    "videos":    "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
}

# XDG 이름과 홈 아래 기본 폴더명
_XDG = {
    "desktop":   ("XDG_DESKTOP_DIR",   "Desktop"),
    "downloads": ("XDG_DOWNLOAD_DIR",  "Downloads"),
    "documents": ("XDG_DOCUMENTS_DIR", "Documents"),
    "pictures":  ("XDG_PICTURES_DIR",  "Pictures"),
    "music":     ("XDG_MUSIC_DIR",     "Music"),
    "videos":    ("XDG_VIDEOS_DIR",    "Videos"),
}

BUILTIN: tuple[str, ...] = (
    "home", "desktop", "downloads", "documents", "pictures", "music", "videos",
)


def _windows_known_folder(guid: str) -> Path | None:
    """Windows 셸에 알려진 폴더의 실제 경로를 묻는다. 실패하면 None."""
    import ctypes
    from ctypes import wintypes

    class _GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_byte * 8),
        ]

    try:
        ole32 = ctypes.windll.ole32
        shell32 = ctypes.windll.shell32
    except (AttributeError, OSError):
        return None

    g = _GUID()
    if ole32.CLSIDFromString(ctypes.c_wchar_p(guid), ctypes.byref(g)) != 0:
        return None
    out = ctypes.c_wchar_p()
    if shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) != 0:
        return None
    try:
        return Path(out.value) if out.value else None
    finally:
        ole32.CoTaskMemFree(out)


def _posix_path(name: str) -> Path | None:
    """XDG 환경변수 → 홈 아래 기본 폴더명 순으로 찾는다."""
    env, default = _XDG[name]
    raw = os.environ.get(env)
    if raw:
        return Path(os.path.expandvars(raw)).expanduser()
    candidate = Path.home() / default
    return candidate if candidate.is_dir() else None


def builtin_path(name: str) -> Path | None:
    """내장 별칭 이름을 실제 경로로. 내장이 아니면 None."""
    if name not in BUILTIN:
        return None
    if name == "home":
        return Path.home()

    if sys.platform == "win32":
        found = _windows_known_folder(_FOLDERID[name])
        if found is not None:
            return found
    else:
        found = _posix_path(name)
        if found is not None:
            return found

    # OS 가 답하지 못하면 홈 아래 영문 기본 폴더명으로 폴백한다
    return Path.home() / _XDG[name][1]
