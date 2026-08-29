from datetime import date
from pathlib import Path

from organize.blocks import BlockConfig
from organize.blocks.empty_files import build
from organize.core.context import Context
from organize.core.scanner import scan

TODAY = date(2026, 8, 29)


def ctx_for(tmp_path, run_id="20260829-120000"):
    entries = scan(tmp_path, recursive=True, now=1e12).entries
    return Context(root=tmp_path, entries=entries, today=TODAY, run_id=run_id)


def write(p: Path, data: bytes) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def quarantined(plan):
    return sorted(a.src.name for a in plan.actions if a.kind == "quarantine")


def test_no_empty_files_means_no_actions(tmp_path):
    write(tmp_path / "a.png", b"AAA")
    write(tmp_path / "b.png", b"BBB")
    assert build(ctx_for(tmp_path), BlockConfig()).actions == []


def test_zero_byte_file_is_quarantined(tmp_path):
    write(tmp_path / "껍데기.txt", b"")
    plan = build(ctx_for(tmp_path), BlockConfig())
    assert quarantined(plan) == ["껍데기.txt"]


def test_two_empty_files_are_both_quarantined(tmp_path):
    """빈 파일은 무리를 짓지 않는다 — 남기는 파일이 없다. 전부 치운다."""
    write(tmp_path / "a.dat", b"")
    write(tmp_path / "b.dat", b"")
    plan = build(ctx_for(tmp_path), BlockConfig())
    assert quarantined(plan) == ["a.dat", "b.dat"]
    assert all(a.keeper is None for a in plan.actions)


def test_non_empty_file_is_left_alone(tmp_path):
    write(tmp_path / "문서.pdf", b"CONTENT")
    assert build(ctx_for(tmp_path), BlockConfig()).actions == []


def test_files_inside_subfolders_are_never_touched(tmp_path):
    write(tmp_path / "6월" / "껍데기.txt", b"")
    plan = build(ctx_for(tmp_path), BlockConfig())
    assert plan.actions == []


def test_quarantine_destination_is_the_run_trash_folder(tmp_path):
    write(tmp_path / "껍데기.txt", b"")
    plan = build(ctx_for(tmp_path), BlockConfig())
    a = plan.actions[0]
    assert a.dst == tmp_path / ".organize" / "trash" / "20260829-120000" / "껍데기.txt"


def test_reason_says_zero_bytes(tmp_path):
    write(tmp_path / "껍데기.txt", b"")
    plan = build(ctx_for(tmp_path), BlockConfig())
    assert "0바이트" in plan.actions[0].reason


def test_when_filter_limits_the_files(tmp_path):
    write(tmp_path / "a.dat", b"")
    write(tmp_path / "b.log", b"")
    plan = build(ctx_for(tmp_path), BlockConfig(when={"ext": [".dat"]}))
    assert quarantined(plan) == ["a.dat"]


def test_when_filter_does_not_report_non_empty_files_as_skipped(tmp_path):
    """`when` 에 안 맞는 **0바이트가 아닌** 파일은 애초에 이 블록의 대상이

    아니므로 skipped 에도 나오면 안 된다 — 이 블록과 무관한 파일까지 "이
    작업의 대상이 아님" 이라고 시끄럽게 알리면 미리보기가 무의미해진다.
    """
    write(tmp_path / "무관.pdf", b"CONTENT")
    write(tmp_path / "a.dat", b"")
    plan = build(ctx_for(tmp_path), BlockConfig(when={"ext": [".dat"]}))
    assert quarantined(plan) == ["a.dat"]
    assert not any(p.name == "무관.pdf" for p, _ in plan.skipped)
