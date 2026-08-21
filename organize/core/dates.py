"""파일 하나에서 날짜 하나를 뽑는다.

우선순위: EXIF 촬영일 → 파일명 날짜 → 파일 수정시각.

파일명 패턴을 엄격히 한정하는 이유: 기존 스크립트의 `(19|20)\\d{2}` 는
`screenshot_1920x1080.png` 를 1920년으로 보냈다. 월·일까지 있고
유효한 날짜여야만 인정한다.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from organize.core.scanner import FileEntry

try:
    from PIL import ExifTags, Image
    HAS_PILLOW = True
except ImportError:                     # Pillow 는 선택 의존성이다
    HAS_PILLOW = False

_MIN_DATE = date(1990, 1, 1)

# YYYYMMDD / YYYY-MM-DD / YYYY_MM_DD / YYYY.MM.DD  (앞뒤가 숫자가 아닐 것)
_NUMERIC = re.compile(
    r"(?<!\d)(19\d{2}|20\d{2})([-_.])?(0[1-9]|1[0-2])([-_.])?(0[1-9]|[12]\d|3[01])(?!\d)"
)
# 2023년12월15일
_KOREAN = re.compile(r"(19\d{2}|20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")


def _in_range(d: date, today: date) -> bool:
    return _MIN_DATE <= d <= today + timedelta(days=1)


def date_from_name(name: str, today: date) -> date | None:
    m = _NUMERIC.search(name)
    if m:
        # 구분자를 썼다면 앞뒤가 같아야 한다 (2023-12_15 같은 혼용을 막는다)
        if m.group(2) == m.group(4):
            try:
                d = date(int(m.group(1)), int(m.group(3)), int(m.group(5)))
            except ValueError:
                d = None
            if d and _in_range(d, today):
                return d

    m = _KOREAN.search(name)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
        if _in_range(d, today):
            return d
    return None


def date_from_exif(path: Path) -> date | None:
    if not HAS_PILLOW:
        return None
    try:
        exif = Image.open(path).getexif()
    except Exception:                   # 이미지가 아니거나 깨졌으면 조용히 넘어간다
        return None
    if not exif:
        return None
    tag = {v: k for k, v in ExifTags.TAGS.items()}
    raw = exif.get(tag.get("DateTimeOriginal")) or exif.get(tag.get("DateTime"))
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw)[:10], "%Y:%m:%d").date()
    except ValueError:
        return None


@dataclass(frozen=True)
class DateHit:
    source: str
    value: date


def resolve_date(entry: FileEntry, today: date) -> DateHit | None:
    found = date_from_exif(entry.path)
    if found:
        return DateHit("EXIF 촬영일", found)

    found = date_from_name(entry.name, today)
    if found:
        return DateHit("파일명 날짜", found)

    if entry.mtime:
        return DateHit("수정시각", datetime.fromtimestamp(entry.mtime).date())

    return None
