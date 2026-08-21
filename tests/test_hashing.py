import os
import time
from pathlib import Path

from organize.core.hashing import find_duplicate_groups, has_copy_marker, pick_original
from organize.core.scanner import FileEntry


def entry(path: Path, mtime: float | None = None) -> FileEntry:
    st = path.stat()
    return FileEntry(path=path, size=st.st_size, mtime=mtime if mtime is not None else st.st_mtime)


def write(p: Path, data: bytes, mtime: float | None = None) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def test_copy_markers():
    assert has_copy_marker("가이드 (1).pdf")
    assert has_copy_marker("가이드 (12).pdf")
    assert has_copy_marker("가이드_1.pdf")
    assert has_copy_marker("가이드 - 복사본.pdf")
    assert has_copy_marker("guide - Copy.pdf")
    assert has_copy_marker("guide_copy.pdf")
    assert not has_copy_marker("가이드.pdf")
    assert not has_copy_marker("2026-06-02 17 47 38.png")


def test_files_of_different_size_are_never_hashed(tmp_path):
    a = write(tmp_path / "a.txt", b"1234")
    b = write(tmp_path / "b.txt", b"12345")
    assert find_duplicate_groups([entry(a), entry(b)]) == []


def test_same_size_different_content_is_not_a_duplicate(tmp_path):
    a = write(tmp_path / "a.txt", b"1234")
    b = write(tmp_path / "b.txt", b"5678")
    assert find_duplicate_groups([entry(a), entry(b)]) == []


def test_identical_content_with_different_names_is_a_duplicate(tmp_path):
    """실제 PicPick 폴더에서 나온 형태 — 이름이 전혀 다른데 내용이 같다."""
    a = write(tmp_path / "2026-06-05 09 59 20.png", b"SAME-CONTENT", mtime=1000.0)
    b = write(tmp_path / "2026-06-06 00 33 58.png", b"SAME-CONTENT", mtime=2000.0)
    groups = find_duplicate_groups([entry(a, 1000.0), entry(b, 2000.0)])
    assert len(groups) == 1
    assert groups[0][0].name == "2026-06-05 09 59 20.png"     # 오래된 쪽을 남긴다


def test_large_files_needing_full_hash(tmp_path):
    head = b"H" * 9000
    a = write(tmp_path / "a.bin", head + b"A")
    b = write(tmp_path / "b.bin", head + b"B")     # 앞 8KB 는 같고 뒤가 다르다
    c = write(tmp_path / "c.bin", head + b"A")
    groups = find_duplicate_groups([entry(a), entry(b), entry(c)])
    assert len(groups) == 1
    assert sorted(e.name for e in groups[0]) == ["a.bin", "c.bin"]


def test_original_prefers_name_without_copy_marker(tmp_path):
    a = write(tmp_path / "가이드 (1).pdf", b"SAME", mtime=1000.0)
    b = write(tmp_path / "가이드.pdf", b"SAME", mtime=2000.0)
    assert pick_original([entry(a, 1000.0), entry(b, 2000.0)]).name == "가이드.pdf"


def test_original_prefers_shallower_path(tmp_path):
    a = write(tmp_path / "깊이" / "자료.pdf", b"SAME", mtime=1000.0)
    b = write(tmp_path / "자료.pdf", b"SAME", mtime=2000.0)
    assert pick_original([entry(a, 1000.0), entry(b, 2000.0)]).path == b


def test_original_prefers_older_when_tied(tmp_path):
    a = write(tmp_path / "가.pdf", b"SAME", mtime=2000.0)
    b = write(tmp_path / "나.pdf", b"SAME", mtime=1000.0)
    assert pick_original([entry(a, 2000.0), entry(b, 1000.0)]).name == "나.pdf"


def test_result_is_deterministic_regardless_of_input_order(tmp_path):
    a = write(tmp_path / "가.pdf", b"SAME", mtime=1000.0)
    b = write(tmp_path / "나.pdf", b"SAME", mtime=1000.0)
    forward = find_duplicate_groups([entry(a, 1000.0), entry(b, 1000.0)])
    backward = find_duplicate_groups([entry(b, 1000.0), entry(a, 1000.0)])
    assert [e.name for e in forward[0]] == [e.name for e in backward[0]]


def test_unreadable_file_is_skipped_not_crashed(tmp_path):
    a = write(tmp_path / "a.txt", b"1234")
    ghost = FileEntry(path=tmp_path / "없는파일.txt", size=4, mtime=0.0)
    assert find_duplicate_groups([entry(a), ghost]) == []
