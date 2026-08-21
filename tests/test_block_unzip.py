import zipfile
from datetime import date
from pathlib import Path

from organize.blocks import BlockConfig
from organize.blocks.unzip import build, recover_name
from organize.core.context import Context
from organize.core.scanner import scan

TODAY = date(2026, 8, 21)


def ctx_for(tmp_path):
    entries = scan(tmp_path, now=1e12).entries
    return Context(root=tmp_path, entries=entries, today=TODAY, run_id="r1")


def make_zip(path: Path, names: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for n in names:
            z.writestr(n, b"DATA")
    return path


def extracts(plan):
    return sorted(a.dst.name for a in plan.actions if a.kind == "extract")


def test_no_zip_means_no_actions(tmp_path):
    (tmp_path / "그냥.txt").write_bytes(b"x")
    assert build(ctx_for(tmp_path), BlockConfig()).actions == []


def test_members_are_flattened_into_the_target(tmp_path):
    make_zip(tmp_path / "자료.zip", ["문서.pdf", "안쪽폴더/사진.png"])
    plan = build(ctx_for(tmp_path), BlockConfig())
    assert extracts(plan) == ["문서.pdf", "사진.png"]
    assert all(a.dst.parent == tmp_path for a in plan.actions if a.kind == "extract")


def test_extract_action_remembers_the_original_member_name(tmp_path):
    """실행기가 ZipFile.open(member) 로 찾을 수 있어야 한다."""
    make_zip(tmp_path / "자료.zip", ["안쪽폴더/사진.png"])
    a = next(x for x in build(ctx_for(tmp_path), BlockConfig()).actions if x.kind == "extract")
    assert a.member == "안쪽폴더/사진.png"
    assert a.dst.name == "사진.png"


def test_directory_entries_are_ignored(tmp_path):
    make_zip(tmp_path / "자료.zip", ["폴더/", "폴더/문서.pdf"])
    assert extracts(build(ctx_for(tmp_path), BlockConfig())) == ["문서.pdf"]


def test_name_collision_inside_one_zip_gets_a_number(tmp_path):
    make_zip(tmp_path / "자료.zip", ["a/문서.pdf", "b/문서.pdf"])
    assert extracts(build(ctx_for(tmp_path), BlockConfig())) == ["문서.pdf", "문서_(1).pdf"]


def test_collision_with_an_existing_file_gets_a_number(tmp_path):
    (tmp_path / "문서.pdf").write_bytes(b"OLDFILE")
    make_zip(tmp_path / "자료.zip", ["문서.pdf"])
    assert extracts(build(ctx_for(tmp_path), BlockConfig())) == ["문서_(1).pdf"]


def test_path_traversal_is_refused(tmp_path):
    make_zip(tmp_path / "나쁜.zip", ["../탈출.txt", "정상.txt"])
    plan = build(ctx_for(tmp_path), BlockConfig())
    assert extracts(plan) == ["정상.txt"]
    assert any("압축 안의 경로가 대상 폴더를 벗어남" in why for _, why in plan.skipped)


def test_cp949_name_is_recovered():
    raw = "한글파일.txt".encode("cp949").decode("cp437")
    assert recover_name(raw, flag_bits=0) == "한글파일.txt"


def test_utf8_flagged_name_is_left_alone():
    assert recover_name("한글파일.txt", flag_bits=0x800) == "한글파일.txt"


def test_original_zip_is_kept_by_default(tmp_path):
    make_zip(tmp_path / "자료.zip", ["문서.pdf"])
    plan = build(ctx_for(tmp_path), BlockConfig())
    assert [a for a in plan.actions if a.kind == "quarantine"] == []


def test_original_zip_can_be_quarantined(tmp_path):
    make_zip(tmp_path / "자료.zip", ["문서.pdf"])
    plan = build(ctx_for(tmp_path), BlockConfig(options={"delete_original": True}))
    q = [a for a in plan.actions if a.kind == "quarantine"]
    assert len(q) == 1 and q[0].src.name == "자료.zip"
    assert q[0].dst.parent == tmp_path / ".organize" / "trash" / "r1"


def test_broken_zip_is_skipped_not_crashed(tmp_path):
    (tmp_path / "깨진.zip").write_bytes(b"not a zip file")
    plan = build(ctx_for(tmp_path), BlockConfig())
    assert plan.actions == []
    assert "열 수 없습니다" in plan.skipped[0][1]
