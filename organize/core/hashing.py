"""내용이 같은 파일을 찾는다.

이름으로 판정하지 않는다. 실제 폴더에서 확인한 결과, 중복인 파일들은
`(1)`, `(2)` 가 붙은 것들이 아니라 이름이 전혀 다른 파일들이었다
(같은 화면을 다른 날 다시 캡처한 것). 반대로 `(2)`, `(3)` 파일들은
서로 다른 이미지였다. 내용 해시가 유일하게 옳은 방법이다.

계산은 3단계로 줄인다. 크기가 다르면 내용이 같을 수 없다.
"""

import hashlib
from collections import defaultdict
from pathlib import Path
import re

from organize.core.scanner import FileEntry

_HEAD_BYTES = 8192
_CHUNK = 65536
_COPY_MARKER = re.compile(r"\(\d+\)|_\d{1,2}(?=\.[^.]+$)|-\s*복사본|-\s*Copy|_copy", re.IGNORECASE)


def has_copy_marker(name: str) -> bool:
    return _COPY_MARKER.search(name) is not None


def _digest(path: Path, limit: int | None = None) -> str | None:
    h = hashlib.md5()
    try:
        with path.open("rb") as f:
            if limit is not None:
                h.update(f.read(limit))
            else:
                while chunk := f.read(_CHUNK):
                    h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _same_bytes(a: Path, b: Path) -> bool:
    """파일을 지우는 작업이므로 마지막에 바이트로 확인한다."""
    try:
        with a.open("rb") as fa, b.open("rb") as fb:
            while True:
                ca, cb = fa.read(_CHUNK), fb.read(_CHUNK)
                if ca != cb:
                    return False
                if not ca:
                    return True
    except OSError:
        return False


def pick_original(group: list[FileEntry]) -> FileEntry:
    """남길 파일 하나를 고른다. 완전히 결정적이어야 한다."""
    return min(group, key=_rank)


def _rank(e: FileEntry) -> tuple:
    return (
        1 if has_copy_marker(e.name) else 0,   # 복사본 표식이 없는 쪽
        len(e.path.parts),                     # 상위 폴더에 있는 쪽
        e.mtime,                               # 오래된 쪽
        str(e.path),                           # 마지막은 사전순
    )


def find_duplicate_groups(entries: list[FileEntry]) -> list[list[FileEntry]]:
    by_size: dict[int, list[FileEntry]] = defaultdict(list)
    for e in entries:
        by_size[e.size].append(e)

    stage2: dict[tuple[int, str], list[FileEntry]] = defaultdict(list)
    for size, group in by_size.items():
        if len(group) < 2:
            continue                                   # 1단계: 해시 계산 없음
        for e in group:
            head = _digest(e.path, _HEAD_BYTES)        # 2단계: 앞 8KB
            if head is not None:
                stage2[(size, head)].append(e)

    result: list[list[FileEntry]] = []
    for group in stage2.values():
        if len(group) < 2:
            continue
        by_full: dict[str, list[FileEntry]] = defaultdict(list)
        for e in group:
            full = _digest(e.path)                     # 3단계: 전체
            if full is not None:
                by_full[full].append(e)
        for same in by_full.values():
            if len(same) < 2:
                continue
            same.sort(key=_rank)
            keeper = same[0]
            confirmed = [keeper] + [e for e in same[1:] if _same_bytes(keeper.path, e.path)]
            if len(confirmed) > 1:
                result.append(confirmed)

    result.sort(key=lambda g: str(g[0].path))          # 결정적 순서
    return result
