"""폴더를 읽어 FileEntry 목록을 만든다.

세 종류를 규칙보다 먼저 걸러낸다.

1. 시스템 파일    옮기면 폴더 아이콘·이름 설정이 깨진다
2. 받는 중인 파일  옮기면 다운로드가 깨진다
3. 온라인 전용    열면 클라우드 다운로드가 시작된다. 그래서 읽지도 않는다
"""

import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

_SYSTEM_NAMES = {"desktop.ini", "thumbs.db", ".ds_store", "ehthumbs.db"}
_IN_PROGRESS_EXT = {".crdownload", ".part", ".partial", ".tmp", ".download"}
_SETTLE_SECONDS = 60          # 이보다 최근에 바뀐 파일은 아직 작업 중으로 본다
_ALWAYS_EXCLUDE_DIRS = {".organize"}


@dataclass(frozen=True)
class FileEntry:
    path: Path
    size: int
    mtime: float

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def ext(self) -> str:
        return self.path.suffix.lower()


@dataclass
class ScanResult:
    entries: list[FileEntry] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)


def is_system_file(name: str) -> bool:
    return name.lower() in _SYSTEM_NAMES or name.startswith("~$")


def is_in_progress(name: str, mtime: float, now: float) -> bool:
    if Path(name).suffix.lower() in _IN_PROGRESS_EXT:
        return True
    return (now - mtime) < _SETTLE_SECONDS


def is_cloud_only(path: Path) -> bool:
    """디스크에 실제 내용이 없는 파일인지. Windows 밖에서는 항상 False."""
    if sys.platform != "win32":
        return False
    import ctypes

    FILE_ATTRIBUTE_OFFLINE = 0x00001000
    FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
    FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000
    INVALID = 0xFFFFFFFF

    attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    if attrs == INVALID:
        return False
    mask = (FILE_ATTRIBUTE_OFFLINE
            | FILE_ATTRIBUTE_RECALL_ON_OPEN
            | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS)
    return bool(attrs & mask)


def scan(
    root: Path,
    *,
    recursive: bool = False,
    now: float | None = None,
    exclude_dirs: frozenset[str] = frozenset(),
) -> ScanResult:
    now = time.time() if now is None else now
    skip_dirs = _ALWAYS_EXCLUDE_DIRS | set(exclude_dirs)
    result = ScanResult()

    if not root.is_dir():
        return result

    paths: list[Path] = []
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in skip_dirs)
            for fn in filenames:
                paths.append(Path(dirpath) / fn)
    else:
        paths = [p for p in root.iterdir() if p.is_file()]

    for path in sorted(paths):                      # 항상 같은 순서 = 결정적
        name = path.name
        if is_system_file(name):
            result.skipped.append((path, "시스템 파일 · 옮기면 폴더 설정이 깨진다"))
            continue
        if is_cloud_only(path):
            result.skipped.append((path, "OneDrive 에만 있음 · 내려받아야 처리할 수 있다"))
            continue
        try:
            st = path.stat()
        except OSError:
            result.skipped.append((path, "파일 정보를 읽을 수 없다"))
            continue
        if is_in_progress(name, st.st_mtime, now):
            result.skipped.append((path, "받는 중이거나 방금 바뀐 파일"))
            continue
        result.entries.append(FileEntry(path=path, size=st.st_size, mtime=st.st_mtime))

    return result
