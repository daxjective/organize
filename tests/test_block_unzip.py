import zipfile
from datetime import date
from pathlib import Path

from organize.blocks import BlockConfig
from organize.blocks.by_date import build as build_by_date
from organize.blocks.unzip import _member_mtime, build, recover_name
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


def make_zip_with_time(path: Path, name: str, date_time: tuple, data: bytes = b"DATA") -> Path:
    """압축 안 항목의 수정시각(date_time)을 직접 지정해 zip 을 만든다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        info = zipfile.ZipInfo(name)
        info.date_time = date_time
        z.writestr(info, data)
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


# --- [1 · Critical] unzip -> by_date 사슬이 실제 zip 안 날짜를 써야 한다 ---
# 고치기 전에는 Context.apply() 의 extract 분기가 가상 엔트리를 size=0,
# mtime=0.0 으로 하드코딩해 EXIF·파일명에 날짜가 없는 파일이 전부 1970 폴더로
# 갔다. unzip -> route -> by_date 사슬이 이 블록의 존재 이유이므로 실제로
# 끝까지 태워서 확인한다.

def test_unzip_to_by_date_chain_uses_the_real_zip_member_date(tmp_path):
    make_zip_with_time(tmp_path / "자료.zip", "메모.txt", (2024, 3, 15, 10, 30, 0))
    ctx = ctx_for(tmp_path)
    plan = build(ctx, BlockConfig())
    ctx.apply(plan)

    date_plan = build_by_date(ctx, BlockConfig())
    move = next(a for a in date_plan.actions
                if a.kind == "move" and a.src.name == "메모.txt")
    assert move.dst.parent.name == "2024"
    assert "1970" not in move.dst.parts


def test_member_mtime_returns_zero_instead_of_raising_on_broken_date(tmp_path):
    """zip 시각은 1980 년부터만 표현되고 깨진 파일도 있다. 예외 없이 0 을 준다."""
    make_zip_with_time(tmp_path / "자료.zip", "메모.txt", (1990, 0, 0, 0, 0, 0))
    with zipfile.ZipFile(tmp_path / "자료.zip") as z:
        info = z.infolist()[0]
    assert _member_mtime(info) == 0.0


def test_unzip_to_by_date_chain_falls_back_to_filename_when_zip_time_is_broken(tmp_path):
    """zip 안 시각이 깨져도 크래시하지 않고, by_date 는 파일명 날짜를 쓴다."""
    make_zip_with_time(tmp_path / "자료.zip", "2024-03-15_메모.txt", (1990, 0, 0, 0, 0, 0))
    ctx = ctx_for(tmp_path)
    plan = build(ctx, BlockConfig())
    extract = next(a for a in plan.actions if a.kind == "extract")
    assert extract.mtime == 0.0        # 못 읽으면 0 을 준다 — 크래시하지 않는다

    ctx.apply(plan)
    date_plan = build_by_date(ctx, BlockConfig())
    move = next(a for a in date_plan.actions if a.kind == "move")
    assert move.dst.parent.name == "2024"
    assert "파일명" in move.reason


# --- [2 · Important] unzip 만 cfg.when 을 조용히 무시하던 것 ---

def test_when_filter_skips_non_matching_zip(tmp_path):
    make_zip(tmp_path / "자료.zip", ["문서.pdf"])
    plan = build(ctx_for(tmp_path), BlockConfig(when={"ext": [".rar"]}))
    assert plan.actions == []
    assert [p.name for p, _ in plan.skipped] == ["자료.zip"]
    assert plan.skipped[0][1] == "이 작업의 대상이 아님"


def test_when_filter_still_extracts_a_matching_zip(tmp_path):
    make_zip(tmp_path / "자료.zip", ["문서.pdf"])
    plan = build(ctx_for(tmp_path), BlockConfig(when={"ext": [".zip"]}))
    assert extracts(plan) == ["문서.pdf"]


# --- [3 · Important] 대소문자만 다른 이름이 서로를 덮어쓰던 것 ---

def test_case_only_difference_does_not_overwrite_on_windows(tmp_path):
    """압축 안에 A.txt 와 a.txt 가 같이 있으면 윈도우에서 하나가 사라졌었다."""
    make_zip(tmp_path / "자료.zip", ["A.txt", "a.txt"])
    result = extracts(build(ctx_for(tmp_path), BlockConfig()))
    assert len(result) == 2
    assert len({n.casefold() for n in result}) == 2
    assert any("_(1)" in n for n in result)


# --- [4 · Minor M2] 빈 이름 멤버의 skip 메시지가 콜론 뒤에 아무것도 없던 것 ---

def test_empty_member_name_gets_a_readable_skip_message(tmp_path):
    make_zip(tmp_path / "자료.zip", ["정상.txt"])
    with zipfile.ZipFile(tmp_path / "자료.zip", "a") as z:
        z.writestr("", b"DATA")   # 이름이 아예 빈 항목
    plan = build(ctx_for(tmp_path), BlockConfig())
    assert extracts(plan) == ["정상.txt"]
    reasons = [why for _, why in plan.skipped]
    assert len(reasons) == 1
    assert not reasons[0].endswith(": ")
    assert "비어" in reasons[0]


def test_which_file_gets_the_suffix_does_not_depend_on_zip_order(tmp_path):
    """압축한 순서가 달라도 결과가 같아야 한다.

    `A.txt` 와 `a.txt` 는 윈도우에서 같은 이름이라 한쪽이 `_(1)` 을 받는다.
    정렬하지 않으면 **어느 쪽이 받는지가 압축한 순서에 좌우된다** — 같은
    내용물인데 압축을 다시 뜨면 결과가 바뀐다. 계획서의 "결정적이어야 한다"에
    어긋난다.
    """
    a = make_zip(tmp_path / "먼저" / "묶음.zip", ["A.txt", "a.txt"])
    b = make_zip(tmp_path / "나중" / "묶음.zip", ["a.txt", "A.txt"])

    def names(zip_root):
        plan = build(ctx_for(zip_root), BlockConfig())
        return [x.dst.name for x in plan.actions if x.kind == "extract"]

    assert names(a.parent) == names(b.parent) == ["A.txt", "a_(1).txt"]
