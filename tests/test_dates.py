from datetime import date
from pathlib import Path

import pytest

from organize.core import dates
from organize.core.dates import date_from_name, resolve_date
from organize.core.scanner import FileEntry

TODAY = date(2026, 8, 21)


@pytest.mark.parametrize("name,expected", [
    ("IMG_20231215.jpg",            date(2023, 12, 15)),
    ("20231215_120000.jpg",         date(2023, 12, 15)),
    ("2023-12-15 회의록.md",         date(2023, 12, 15)),
    ("2023_12_15.png",              date(2023, 12, 15)),
    ("2023.12.15 자료.pdf",          date(2023, 12, 15)),
    ("2026-06-02 17 47 38.png",     date(2026, 6, 2)),
    ("2023년12월15일.hwp",           date(2023, 12, 15)),
    ("sitewalk_20260818.md",        date(2026, 8, 18)),
])
def test_recognised_date_patterns(name, expected):
    assert date_from_name(name, TODAY) == expected


@pytest.mark.parametrize("name", [
    "screenshot_1920x1080.png",     # 해상도 — 기존 정규식이 1920년으로 오인하던 것
    "capture_1248x702.png",
    "영상 [ID - 1383x778 - 1m29s].png",
    "보고서_v2019_최종.docx",         # 연도만 있고 월일이 없다
    "20231340.jpg",                 # 13월 40일 — 유효하지 않다
    "20230000.jpg",
    "1h00m38s.png",
    "회의록.md",
])
def test_rejected_patterns(name):
    assert date_from_name(name, TODAY) is None


def test_dates_outside_the_allowed_range_are_rejected():
    assert date_from_name("19891231.jpg", TODAY) is None     # 1990 이전
    assert date_from_name("20991231.jpg", TODAY) is None     # 오늘+1일 이후


def test_tomorrow_is_allowed_for_timezone_slack():
    assert date_from_name("20260822.jpg", TODAY) == date(2026, 8, 22)


def test_resolve_prefers_exif_over_name(monkeypatch, tmp_path):
    p = tmp_path / "20231215.jpg"
    p.write_bytes(b"x")
    monkeypatch.setattr(dates, "date_from_exif", lambda path: date(2020, 1, 1))
    hit = resolve_date(FileEntry(path=p, size=1, mtime=0.0), TODAY)
    assert hit.value == date(2020, 1, 1)
    assert hit.source == "EXIF 촬영일"


def test_resolve_falls_back_to_name(monkeypatch, tmp_path):
    p = tmp_path / "20231215.jpg"
    p.write_bytes(b"x")
    monkeypatch.setattr(dates, "date_from_exif", lambda path: None)
    hit = resolve_date(FileEntry(path=p, size=1, mtime=0.0), TODAY)
    assert hit.value == date(2023, 12, 15)
    assert hit.source == "파일명 날짜"


def test_resolve_falls_back_to_mtime(monkeypatch, tmp_path):
    import datetime
    p = tmp_path / "회의록.md"
    p.write_bytes(b"x")
    monkeypatch.setattr(dates, "date_from_exif", lambda path: None)
    stamp = datetime.datetime(2024, 3, 9, 12, 0).timestamp()
    hit = resolve_date(FileEntry(path=p, size=1, mtime=stamp), TODAY)
    assert hit.value == date(2024, 3, 9)
    assert hit.source == "수정시각"


def test_exif_returns_none_without_pillow(monkeypatch, tmp_path):
    monkeypatch.setattr(dates, "HAS_PILLOW", False)
    p = tmp_path / "사진.jpg"
    p.write_bytes(b"x")
    assert dates.date_from_exif(p) is None
