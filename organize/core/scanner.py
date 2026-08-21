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
_INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
_CLOUD_MASK = (0x00001000      # FILE_ATTRIBUTE_OFFLINE
               | 0x00040000    # FILE_ATTRIBUTE_RECALL_ON_OPEN
               | 0x00400000)   # FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS


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


def _is_cloud_attrs(attrs: int) -> bool:
    if attrs < 0 or attrs == _INVALID_FILE_ATTRIBUTES:
        return False
    return bool(attrs & _CLOUD_MASK)


def is_cloud_only(path: Path) -> bool:
    """디스크에 실제 내용이 없는 파일인지. Windows 밖에서는 항상 False."""
    if sys.platform != "win32":
        return False
    import ctypes

    get_attrs = ctypes.windll.kernel32.GetFileAttributesW
    get_attrs.restype = ctypes.c_uint32
    get_attrs.argtypes = [ctypes.c_wchar_p]

    try:
        return _is_cloud_attrs(get_attrs(str(path)))
    except OSError:
        return False


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
        try:
            with os.scandir(root) as it:
                for e in it:
                    try:
                        # 기본값(follow_symlinks=True)을 쓴다. False 로 두면 폴더를
                        # 가리키는 심볼릭 링크가 파일로 새어나가고, 그 폴더의 크기와
                        # 수정시각을 가진 FileEntry 가 만들어진다.
                        # 깨진 링크는 기본값에서도 예외 없이 False 를 돌려주므로
                        # 아래 stat 에서 사유가 남는다.
                        if e.is_dir():
                            continue
                    except OSError:
                        pass          # 판정 못 하면 파일로 보고 아래에서 사유를 남긴다
                    paths.append(Path(e.path))
        except OSError:
            return result

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
