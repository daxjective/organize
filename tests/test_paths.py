from pathlib import Path

import pytest

from organize.core.paths import move_file, same_drive, unique_path


def test_unique_path_returns_input_when_free(tmp_path):
    p = tmp_path / "a.txt"
    assert unique_path(p) == p


def test_unique_path_adds_a_number(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x")
    assert unique_path(tmp_path / "a.txt") == tmp_path / "a_(1).txt"


def test_unique_path_keeps_counting(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x")
    (tmp_path / "a_(1).txt").write_bytes(b"x")
    assert unique_path(tmp_path / "a.txt") == tmp_path / "a_(2).txt"


def test_unique_path_handles_no_extension(tmp_path):
    (tmp_path / "README").write_bytes(b"x")
    assert unique_path(tmp_path / "README") == tmp_path / "README_(1)"


def test_move_file_moves_and_creates_parent(tmp_path):
    src = tmp_path / "a.txt"
    src.write_bytes(b"DATA")
    dst = tmp_path / "깊은" / "폴더" / "a.txt"
    final = move_file(src, dst)
    assert final == dst
    assert dst.read_bytes() == b"DATA"
    assert not src.exists()


def test_move_file_avoids_overwriting(tmp_path):
    (tmp_path / "기존.txt").write_bytes(b"OLDFILE")
    src = tmp_path / "새것.txt"
    src.write_bytes(b"NEWFILE")
    final = move_file(src, tmp_path / "기존.txt")
    assert final == tmp_path / "기존_(1).txt"
    assert (tmp_path / "기존.txt").read_bytes() == b"OLDFILE"     # 원본이 살아있다
    assert final.read_bytes() == b"NEWFILE"


def test_same_drive_is_true_within_one_tree(tmp_path):
    assert same_drive(tmp_path / "a", tmp_path / "b" / "c")


def test_cross_drive_path_uses_copy_then_delete(tmp_path, monkeypatch):
    """다른 드라이브면 copy2 로 복사하고 크기를 확인한 뒤 원본을 지운다."""
    import organize.core.paths as paths
    monkeypatch.setattr(paths, "same_drive", lambda a, b: False)
    src = tmp_path / "a.txt"
    src.write_bytes(b"DATA")
    dst = tmp_path / "다른곳" / "a.txt"
    assert move_file(src, dst) == dst
    assert dst.read_bytes() == b"DATA"
    assert not src.exists()


def test_missing_source_is_a_friendly_error(tmp_path):
    from organize.errors import OrganizeError
    with pytest.raises(OrganizeError):
        move_file(tmp_path / "없음.txt", tmp_path / "b.txt")
