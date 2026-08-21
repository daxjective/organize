import os
from datetime import date
from pathlib import Path

from organize.blocks import BlockConfig
from organize.blocks.dedup import build
from organize.core.context import Context
from organize.core.scanner import FileEntry, scan

TODAY = date(2026, 8, 21)


def ctx_for(tmp_path, run_id="20260821-120000"):
    entries = scan(tmp_path, recursive=True, now=1e12).entries
    return Context(root=tmp_path, entries=entries, today=TODAY, run_id=run_id)


def write(p: Path, data: bytes) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def quarantined(plan):
    return sorted(a.src.name for a in plan.actions if a.kind == "quarantine")


def test_no_duplicates_means_no_actions(tmp_path):
    write(tmp_path / "a.png", b"AAA")
    write(tmp_path / "b.png", b"BBB")
    assert build(ctx_for(tmp_path), BlockConfig()).actions == []


def test_duplicate_at_root_is_quarantined(tmp_path):
    write(tmp_path / "가이드.pdf", b"SAME-CONTENT")
    write(tmp_path / "가이드 (1).pdf", b"SAME-CONTENT")
    plan = build(ctx_for(tmp_path), BlockConfig())
    assert quarantined(plan) == ["가이드 (1).pdf"]     # 복사본 표식이 있는 쪽을 치운다


def test_files_inside_subfolders_are_never_touched(tmp_path):
    """하위 폴더는 참고만 한다. 거기 있는 파일은 절대 옮기지 않는다."""
    write(tmp_path / "6월" / "사진.png", b"SAME-CONTENT")
    write(tmp_path / "6월" / "사진 복사.png", b"SAME-CONTENT")
    plan = build(ctx_for(tmp_path), BlockConfig())
    assert plan.actions == []


def test_root_file_matching_a_subfolder_file_is_quarantined(tmp_path):
    """이미 정리해 둔 폴더에 같은 게 있으면, 새로 들어온 직속 파일을 치운다."""
    write(tmp_path / "6월" / "사진.png", b"SAME-CONTENT")
    write(tmp_path / "사진.png", b"SAME-CONTENT")
    plan = build(ctx_for(tmp_path), BlockConfig())
    assert quarantined(plan) == ["사진.png"]
    assert all(a.dst.parent.name == "20260821-120000" for a in plan.actions)


def test_quarantine_destination_is_the_run_trash_folder(tmp_path):
    write(tmp_path / "a.pdf", b"SAME")
    write(tmp_path / "a (1).pdf", b"SAME")
    plan = build(ctx_for(tmp_path), BlockConfig())
    a = next(x for x in plan.actions if x.kind == "quarantine")
    assert a.dst == tmp_path / ".organize" / "trash" / "20260821-120000" / "a (1).pdf"


def test_reason_names_the_file_that_was_kept(tmp_path):
    write(tmp_path / "가이드.pdf", b"SAME")
    write(tmp_path / "가이드 (1).pdf", b"SAME")
    plan = build(ctx_for(tmp_path), BlockConfig())
    a = next(x for x in plan.actions if x.kind == "quarantine")
    assert "가이드.pdf" in a.reason


def test_when_filter_limits_the_files(tmp_path):
    write(tmp_path / "a.pdf", b"SAME")
    write(tmp_path / "a (1).pdf", b"SAME")
    write(tmp_path / "b.png", b"EQUAL")
    write(tmp_path / "b (1).png", b"EQUAL")
    plan = build(ctx_for(tmp_path), BlockConfig(when={"ext": [".pdf"]}))
    assert quarantined(plan) == ["a (1).pdf"]


def test_when_excluded_duplicate_always_wins_the_keeper_role(tmp_path):
    """when 범위 밖 파일과 내용이 같으면, 범위 안 후보는 이름·나이와 무관하게 치워진다.

    범위 밖 파일은 이 스텝이 건드릴 수 없다 — 하위 폴더 파일과 같은 처지다
    ("읽기 범위엔 있지만 치울 수는 없다"). 그러니 그 파일이 이미 있는 이상
    범위 안 파일은 내용이 이미 다른 곳에 있는 여분이라 남길 이유가 없다.
    이걸 확인하려고 범위 안 파일을 일부러 더 오래된 것으로 만들었다 — 이름이나
    나이가 우연히 유리해도(옛 코드처럼 그룹 전체를 한 번에 랭킹하면) 결과가
    달라지면 안 된다는 뜻이다.
    """
    a = write(tmp_path / "in_scope.png", b"SAME")
    b = write(tmp_path / "out_of_scope.txt", b"SAME")
    os.utime(a, (1000.0, 1000.0))   # 범위 안 파일이 훨씬 오래됨 — 옛 랭킹이면 이게 이긴다
    os.utime(b, (2000.0, 2000.0))
    plan = build(ctx_for(tmp_path), BlockConfig(when={"ext": [".png"]}))
    assert quarantined(plan) == ["in_scope.png"]
    a = next(x for x in plan.actions if x.kind == "quarantine")
    assert "out_of_scope.txt" in a.reason


def test_virtual_files_are_skipped_with_a_clear_reason(tmp_path):
    entries = [FileEntry(path=tmp_path / "압축안.pdf", size=0, mtime=0.0, virtual=True)]
    c = Context(root=tmp_path, entries=entries, today=TODAY, run_id="r")
    plan = build(c, BlockConfig())
    assert plan.actions == []
    assert "압축을 푼 뒤" in plan.skipped[0][1]
