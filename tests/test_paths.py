import errno
import os
from pathlib import Path, PureWindowsPath

import pytest

from organize.core.paths import claim_path, move_file, same_drive, unique_path
from organize.errors import OrganizeError


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


# --- claim_path: 이름 잡기와 없음 확인을 한 동작으로 합친다 (Critical #1) ---


def test_claim_path_returns_input_when_free(tmp_path):
    p = tmp_path / "a.txt"
    claimed = claim_path(p)
    assert claimed == p
    assert p.exists()          # 자리를 잡으면서 빈 파일이 생긴다
    assert p.read_bytes() == b""


def test_claim_path_bumps_number_when_taken(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"OLD")
    claimed = claim_path(tmp_path / "a.txt")
    assert claimed == tmp_path / "a_(1).txt"
    assert claimed.exists()
    assert (tmp_path / "a.txt").read_bytes() == b"OLD"     # 기존 파일은 안 건드림


def test_claim_path_wraps_oserror_as_organize_error(tmp_path):
    """O_EXCL 이 아닌 다른 이유(권한 등)로 열기가 실패하면 예외 원문이 아니라
    한국어 OrganizeError 여야 한다."""
    from organize.errors import OrganizeError

    readonly_dir = tmp_path / "readonly"
    readonly_dir.mkdir()
    target = readonly_dir / "a.txt"
    os.chmod(readonly_dir, 0o500)      # 쓰기 금지
    try:
        with pytest.raises(OrganizeError) as exc_info:
            claim_path(target)
        assert "PermissionError" not in str(exc_info.value)
    finally:
        os.chmod(readonly_dir, 0o700)   # tmp_path 정리를 위해 되돌림


def test_move_file_uses_claim_path_not_unique_path(tmp_path, monkeypatch):
    """move_file 이 unique_path 대신 claim_path 를 쓰는지 직접 확인한다."""
    import organize.core.paths as paths

    called = []
    real_claim_path = paths.claim_path

    def spy_claim_path(dst):
        called.append(dst)
        return real_claim_path(dst)

    def boom_unique_path(dst):
        raise AssertionError("move_file 은 unique_path 를 호출하면 안 된다")

    monkeypatch.setattr(paths, "claim_path", spy_claim_path)
    monkeypatch.setattr(paths, "unique_path", boom_unique_path)

    src = tmp_path / "a.txt"
    src.write_bytes(b"DATA")
    final = paths.move_file(src, tmp_path / "b.txt")

    assert final == tmp_path / "b.txt"
    assert called == [tmp_path / "b.txt"]


def test_move_file_survives_race_at_chosen_name(tmp_path, monkeypatch):
    """이름을 고른 직후 다른 프로그램이 같은 이름의 파일을 만들어도 덮어쓰지 않는다.

    수정 전 컨트롤러의 재현 방법은 `unique_path` 를 monkeypatch 해서 "비어있다"고
    판정한 직후 그 경로에 파일을 쓰는 것이었다 — move_file 이 그 뒤 shutil.move 로
    조용히 덮어썼다. 지금은 move_file 이 unique_path 를 아예 안 쓰므로 그 수법
    자체가 더는 걸릴 자리가 없다. 대신 claim_path 가 실제로 여는 os.open 호출,
    즉 "이름 잡기"와 "없음 확인"이 하나로 합쳐진 바로 그 지점에서 경쟁을 흉내낸다:
    우리가 후보 이름을 열려는 순간 그 직전에 다른 프로그램이 먼저 같은 이름으로
    파일을 만들어버린 상황."""
    import organize.core.paths as paths

    real_open = os.open
    calls = []

    def racing_open(path, flags, mode=0o777, *args, **kwargs):
        calls.append(path)
        if len(calls) == 1:
            # 다른 프로그램이 우리보다 한 발 먼저 그 이름을 차지했다고 흉내낸다
            with open(path, "wb") as f:
                f.write(b"VICTIM")
        return real_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(paths.os, "open", racing_open)

    src = tmp_path / "새것.txt"
    src.write_bytes(b"MOVER-DATA")
    target = tmp_path / "새로온.txt"

    final = paths.move_file(src, target)

    assert target.read_bytes() == b"VICTIM"            # 남의 파일 내용이 살아남는다
    assert final == tmp_path / "새로온_(1).txt"          # 다음 번호로 밀려서 이동했다
    assert final.read_bytes() == b"MOVER-DATA"
    assert not src.exists()


# --- same_drive 오판이 크기 검증을 건너뛰게 하지 않는다 (Important #2) ---


def test_same_drive_misjudgment_does_not_skip_size_check(tmp_path, monkeypatch):
    """same_drive 가 틀리게 "같다"고 오판해도, move_file 은 그 판정을 이동 여부
    분기에 쓰지 않는다 — 실제로 os.replace 가 EXDEV 를 던지면 그대로 복사
    경로로 넘어간다. 판정은 운영체제 몫이다."""
    import organize.core.paths as paths

    monkeypatch.setattr(paths, "same_drive", lambda a, b: True)   # 일부러 오판시킨다

    def fake_replace(a, b):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(paths.os, "replace", fake_replace)

    src = tmp_path / "a.txt"
    src.write_bytes(b"DATA")
    dst = tmp_path / "다른곳" / "a.txt"
    final = paths.move_file(src, dst)

    assert final == dst
    assert dst.read_bytes() == b"DATA"
    assert not src.exists()


# --- 실패 주입: 파일을 잃지 않는지 확인한다 ---


def test_replace_failure_not_exdev_keeps_source_and_cleans_claimed_slot(tmp_path, monkeypatch):
    """os.replace 가 EXDEV 가 아닌 이유로 실패하면: 원본은 남고, 우리가 만든
    빈 자리(claim_path 로 예약한 파일)는 치워진다."""
    import organize.core.paths as paths
    from organize.errors import OrganizeError

    def fake_replace(a, b):
        raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(paths.os, "replace", fake_replace)

    src = tmp_path / "a.txt"
    src.write_bytes(b"DATA")
    dst = tmp_path / "b.txt"

    with pytest.raises(OrganizeError) as exc_info:
        paths.move_file(src, dst)

    assert "PermissionError" not in str(exc_info.value)
    assert "Errno" not in str(exc_info.value)
    assert src.exists() and src.read_bytes() == b"DATA"    # 원본이 남아있다
    assert not dst.exists()                                # 우리가 만든 빈 자리는 치워졌다


def test_cross_drive_copy_failure_keeps_source_and_cleans_dest_fragment(tmp_path, monkeypatch):
    """드라이브를 넘는 복사 도중 실패하면: 원본은 남고, 목적지에 남은 조각은
    치워진다."""
    import organize.core.paths as paths
    from organize.errors import OrganizeError

    def fake_replace(a, b):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    def fake_copy2(a, b):
        Path(b).write_bytes(b"PART")     # 복사가 절반쯤 진행됐다고 흉내낸다
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(paths.os, "replace", fake_replace)
    monkeypatch.setattr(paths.shutil, "copy2", fake_copy2)

    src = tmp_path / "a.txt"
    src.write_bytes(b"DATA")
    dst = tmp_path / "다른곳" / "a.txt"

    with pytest.raises(OrganizeError) as exc_info:
        paths.move_file(src, dst)

    assert "OSError" not in str(exc_info.value)
    assert src.exists() and src.read_bytes() == b"DATA"    # 원본이 남아있다
    assert not dst.exists()                                # 목적지 조각이 치워졌다


def test_cross_drive_size_mismatch_keeps_source(tmp_path, monkeypatch):
    """복사는 끝났는데(예외 없이) 크기가 어긋나면: 원본이 남는다."""
    import organize.core.paths as paths
    from organize.errors import OrganizeError

    def fake_replace(a, b):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    def fake_copy2(a, b):
        Path(b).write_bytes(b"SHORT")    # 원본(b"DATA-FULL")보다 짧게 잘려서 "성공"한다

    monkeypatch.setattr(paths.os, "replace", fake_replace)
    monkeypatch.setattr(paths.shutil, "copy2", fake_copy2)

    src = tmp_path / "a.txt"
    src.write_bytes(b"DATA-FULL")
    dst = tmp_path / "다른곳" / "a.txt"

    with pytest.raises(OrganizeError):
        paths.move_file(src, dst)

    assert src.exists() and src.read_bytes() == b"DATA-FULL"   # 원본이 남아있다


def test_unlink_failure_after_copy_is_a_friendly_error_and_keeps_both_files(tmp_path, monkeypatch):
    """복사·검증 다 끝났는데 원본 삭제만 실패하면: 복사본과 원본이 둘 다 남는다
    (파일을 잃지 않았다). 안내는 한국어이고 복사본 위치를 알려준다 (Important #3)."""
    import organize.core.paths as paths
    from organize.errors import OrganizeError

    def fake_replace(a, b):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(paths.os, "replace", fake_replace)

    src = tmp_path / "a.txt"
    src.write_bytes(b"DATA")
    dst = tmp_path / "다른곳" / "a.txt"

    real_unlink = Path.unlink

    def failing_unlink(self, missing_ok=False):
        if self == src:
            raise PermissionError(13, "Permission denied")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    with pytest.raises(OrganizeError) as exc_info:
        paths.move_file(src, dst)

    err = exc_info.value
    assert "PermissionError" not in err.message
    assert "PermissionError" not in (err.hint or "")
    final = tmp_path / "다른곳" / "a.txt"
    assert src.exists() and src.read_bytes() == b"DATA"           # 원본도 남아있다
    assert final.exists() and final.read_bytes() == b"DATA"        # 사본도 남아있다 — 안 잃었다
    assert str(final) in (err.hint or "")                           # 안내가 사본 위치를 알려준다


def test_same_drive_is_not_a_safety_check(tmp_path):
    """`same_drive` 는 WSL 마운트 경로를 오판한다 — 알고 쓰라는 뜻으로 못박는다.

    `/mnt/c` 와 `/mnt/d` 는 실제로 다른 드라이브인데 `Path.drive` 가 둘 다
    빈 문자열이라 "같다" 고 답한다. 이 답을 믿고 안전 검사를 건너뛰면 그
    검사가 통째로 사라진다. `move_file` 이 이 함수를 안 쓰는 이유다.
    """
    assert same_drive(Path("/mnt/c/사진.png"), Path("/mnt/d/사진.png")) is True
    assert same_drive(PureWindowsPath("C:/사진.png"),
                      PureWindowsPath("D:/사진.png")) is False


def test_move_file_keeps_the_original_when_it_cannot_verify_the_copy(tmp_path,
                                                                    monkeypatch):
    """복사한 파일을 확인조차 못 하면 원본을 지우지 않는다.

    크기 비교의 `stat()` 이 감싸여 있지 않으면 파이썬 예외가 그대로 새고,
    무엇보다 "확인 못 했으니 안전한 쪽" 이라는 판단을 못 하게 된다.
    """
    src = tmp_path / "원본.txt"
    src.write_bytes(b"SOURCE-DATA")
    dst = tmp_path / "목적지" / "원본.txt"

    def fake_replace(a, b):
        raise OSError(errno.EXDEV, "cross-device")

    real_stat = Path.stat

    def flaky_stat(self, **kw):
        if self.parent.name == "목적지":
            raise OSError(errno.EIO, "I/O error")
        return real_stat(self, **kw)

    monkeypatch.setattr(os, "replace", fake_replace)
    monkeypatch.setattr(Path, "stat", flaky_stat)

    with pytest.raises(OrganizeError) as exc:
        move_file(src, dst)

    monkeypatch.undo()
    assert "확인하지 못했습니다" in exc.value.message
    assert src.exists()                      # 원본은 그대로다 — 이게 핵심이다
    assert not dst.exists()                  # 우리가 만든 자리는 치웠다


def test_interrupt_does_not_leave_an_empty_file_behind(tmp_path, monkeypatch):
    """Ctrl-C 로 끊겨도 잡아 둔 빈 자리가 남지 않는다.

    남으면 사용자 폴더에 0바이트 파일이 생기고, 다음 실행 때 그 이름이 막혀
    `_(1)` 이 계속 밀린다. 60초가 지나면 스캐너가 그걸 진짜 파일로 잡는다.
    """
    src = tmp_path / "원본.txt"
    src.write_bytes(b"SOURCE-DATA")
    dst = tmp_path / "목적지" / "원본.txt"

    def interrupted(a, b):
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", interrupted)
    with pytest.raises(KeyboardInterrupt):
        move_file(src, dst)
    monkeypatch.undo()

    assert src.exists()                       # 원본 그대로
    assert not dst.exists()                   # 빈 자리도 안 남는다
    assert list((tmp_path / "목적지").iterdir()) == []
