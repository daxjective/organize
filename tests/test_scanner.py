import time
from pathlib import Path

from organize.core import scanner
from organize.core.scanner import FileEntry, is_in_progress, is_system_file, scan


def touch(p: Path, content: bytes = b"x", age_seconds: float = 3600) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    old = time.time() - age_seconds
    import os
    os.utime(p, (old, old))
    return p


def test_system_files_are_recognised():
    assert is_system_file("desktop.ini")
    assert is_system_file("Desktop.INI")          # 대소문자 무관
    assert is_system_file("Thumbs.db")
    assert is_system_file(".DS_Store")
    assert is_system_file("~$보고서.docx")         # Office 임시 파일
    assert not is_system_file("보고서.docx")


def test_in_progress_by_extension():
    now = time.time()
    assert is_in_progress("영화.mp4.crdownload", now - 9999, now)
    assert is_in_progress("자료.part", now - 9999, now)
    assert not is_in_progress("자료.pdf", now - 9999, now)


def test_in_progress_by_recent_modification():
    now = time.time()
    assert is_in_progress("자료.pdf", now - 10, now)      # 10초 전 = 작업 중일 수 있음
    assert not is_in_progress("자료.pdf", now - 120, now)  # 2분 전 = 안정


def test_scan_returns_sorted_entries(tmp_path):
    touch(tmp_path / "b.txt")
    touch(tmp_path / "a.txt")
    result = scan(tmp_path)
    assert [e.name for e in result.entries] == ["a.txt", "b.txt"]


def test_scan_excludes_system_files_with_reason(tmp_path):
    touch(tmp_path / "보고서.pdf")
    touch(tmp_path / "desktop.ini")
    result = scan(tmp_path)
    assert [e.name for e in result.entries] == ["보고서.pdf"]
    assert len(result.skipped) == 1
    assert "시스템 파일" in result.skipped[0][1]


def test_scan_excludes_in_progress_downloads(tmp_path):
    touch(tmp_path / "영화.mp4.crdownload")
    result = scan(tmp_path)
    assert result.entries == []
    assert "받는 중" in result.skipped[0][1]


def test_scan_excludes_cloud_only_files(tmp_path, monkeypatch):
    touch(tmp_path / "온라인.jpg")
    touch(tmp_path / "로컬.jpg")
    monkeypatch.setattr(scanner, "is_cloud_only", lambda p: p.name == "온라인.jpg")
    result = scan(tmp_path)
    assert [e.name for e in result.entries] == ["로컬.jpg"]
    assert "OneDrive" in result.skipped[0][1]


def test_scan_is_not_recursive_by_default(tmp_path):
    touch(tmp_path / "위.txt")
    touch(tmp_path / "하위" / "아래.txt")
    assert [e.name for e in scan(tmp_path).entries] == ["위.txt"]


def test_scan_recursive_reaches_subfolders(tmp_path):
    touch(tmp_path / "위.txt")
    touch(tmp_path / "하위" / "아래.txt")
    names = sorted(e.name for e in scan(tmp_path, recursive=True).entries)
    assert names == ["아래.txt", "위.txt"]


def test_scan_never_enters_organize_folder(tmp_path):
    touch(tmp_path / ".organize" / "trash" / "지운것.png")
    touch(tmp_path / "정상.png")
    assert [e.name for e in scan(tmp_path, recursive=True).entries] == ["정상.png"]


def test_scan_skips_named_exclude_dirs(tmp_path):
    touch(tmp_path / "01_Docs" / "이미정리됨.pdf")
    touch(tmp_path / "새파일.pdf")
    result = scan(tmp_path, recursive=True, exclude_dirs=frozenset({"01_Docs"}))
    assert [e.name for e in result.entries] == ["새파일.pdf"]


def test_file_entry_ext_is_lowercase_with_dot(tmp_path):
    p = touch(tmp_path / "사진.PNG")
    e = FileEntry(path=p, size=1, mtime=0.0)
    assert e.ext == ".png"
    assert e.name == "사진.PNG"


def test_cloud_attribute_bits(tmp_path):
    from organize.core.scanner import _is_cloud_attrs
    assert _is_cloud_attrs(0x00400000)
    assert _is_cloud_attrs(0x00040000)
    assert _is_cloud_attrs(0x00001000)
    assert not _is_cloud_attrs(0x20)        # ARCHIVE 뿐이면 로컬 파일이다
    assert not _is_cloud_attrs(0xFFFFFFFF)  # 읽기 실패는 클라우드가 아니다
    assert not _is_cloud_attrs(-1)          # 부호 있는 해석으로 들어와도 마찬가지


def test_unreadable_entry_is_reported_not_dropped(tmp_path):
    import os
    touch(tmp_path / "정상.txt")
    os.symlink(tmp_path / "없는대상.txt", tmp_path / "깨진링크.txt")
    result = scan(tmp_path)
    assert [e.name for e in result.entries] == ["정상.txt"]
    assert [p.name for p, _ in result.skipped] == ["깨진링크.txt"]
    assert "읽을 수 없다" in result.skipped[0][1]


def test_symlink_to_a_directory_is_not_a_file(tmp_path):
    """폴더를 가리키는 링크는 폴더로 취급해야 한다. 파일로 새면 그 폴더의
    크기·수정시각을 가진 항목이 정리 대상이 된다.

    **대상 폴더의 mtime 도 과거로 돌려야 한다.** 갓 만든 폴더는 "최근 1분 내 수정"
    필터에 걸리므로, 링크가 파일로 새어나와도 entries 가 아니라 skipped 로 빠진다.
    그러면 버그가 있는 코드에서도 이 테스트가 통과해 버린다 — 실측으로 확인했다.
    회귀 테스트는 옛 코드에서 반드시 실패해야 한다.
    """
    import os
    inner = tmp_path / "실제폴더"
    inner.mkdir()
    touch(inner / "안쪽.txt")
    touch(tmp_path / "정상.txt")
    os.symlink(inner, tmp_path / "폴더링크")
    past = time.time() - 3600
    os.utime(inner, (past, past))          # 폴더 자체도 과거로 돌린다

    result = scan(tmp_path)
    assert [e.name for e in result.entries] == ["정상.txt"]
    assert result.skipped == []            # 링크는 건너뛴 게 아니라 아예 대상이 아니다
