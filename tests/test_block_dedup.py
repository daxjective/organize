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


def test_when_filter_does_not_pull_in_unrelated_files(tmp_path):
    """[A] `when` 으로 걸러진 파일은 참고용으로도 쓰지 않는다 — 아예 뺀다.

    라운드 1 판정 오류의 재발 방지 테스트. `when={"ext": [".png"]}` 인데
    무관한 `.txt` 를 "참고용(protected)" 취급했더니, 그 `.txt` 가 남길 파일로
    뽑히면서 정작 대상인 png 두 개가 **전부** 치워지는 사고가 났다.
    `.txt` 는 하위 폴더 파일과 처지가 다르다 — 사용자가 "이 작업의 대상이
    아니다"라고 명시한 것이므로 중복 판정에서 통째로 빠져야 한다.
    """
    write(tmp_path / "메모.txt", b"SAME")
    write(tmp_path / "사진.png", b"SAME")
    write(tmp_path / "사진 (1).png", b"SAME")
    plan = build(ctx_for(tmp_path), BlockConfig(when={"ext": [".png"]}))
    assert quarantined(plan) == ["사진 (1).png"]     # 복사본 표식 있는 쪽만 치운다
    a = next(x for x in plan.actions if x.kind == "quarantine")
    assert "메모.txt" not in a.reason                # 무관한 파일이 이유에 등장하면 안 된다


def test_when_filter_still_allows_subfolder_reference(tmp_path):
    """[B] `when` 을 통과하는 하위 폴더 파일은 여전히 대조 대상이다.

    [A] 를 고치다가 하위 폴더 대조 기능 자체를 죽이면 안 된다 — `when` 으로
    빠지는 건 조건에 안 맞는 파일뿐이고, 조건을 통과하는 하위 폴더 파일은
    그대로 `readable` 에 남아 원본 대접(protected)을 받아야 한다.
    """
    write(tmp_path / "정리됨" / "여행사진.png", b"SAME")
    write(tmp_path / "사진.png", b"SAME")
    plan = build(ctx_for(tmp_path), BlockConfig(when={"ext": [".png"]}))
    assert quarantined(plan) == ["사진.png"]
    assert all(a.dst.parent.name == "20260821-120000" for a in plan.actions)


def test_virtual_files_are_skipped_with_a_clear_reason(tmp_path):
    entries = [FileEntry(path=tmp_path / "압축안.pdf", size=0, mtime=0.0, virtual=True)]
    c = Context(root=tmp_path, entries=entries, today=TODAY, run_id="r")
    plan = build(c, BlockConfig())
    assert plan.actions == []
    assert "압축을 푼 뒤" in plan.skipped[0][1]


def test_when_is_checked_only_on_files_that_formed_a_duplicate_group(tmp_path,
                                                                    monkeypatch):
    """`when` 판정을 무리 지은 뒤로 미룬다 — 하위 폴더 전체를 훑지 않는다.

    `when` 에 `has_exif_camera` 같은 조건이 끼면 `matches` 가 파일을 연다.
    무리 짓기 전에 걸러 버리면 사진 폴더의 파일을 전부 열게 된다. 무리 짓기는
    내용만 보므로 나중에 걸러도 결과가 같고, 여는 파일 수만 줄어든다.
    """
    import organize.blocks.dedup as dedup_module

    write(tmp_path / "메모.txt", b"SAME")
    write(tmp_path / "사진.png", b"SAME")
    write(tmp_path / "사진 (1).png", b"SAME")
    for i in range(20):                      # 중복이 아닌 하위 폴더 사진들
        write(tmp_path / "사진첩" / f"기타{i}.png", f"다르다{i}".encode())

    seen = []
    real = dedup_module.matches
    monkeypatch.setattr(dedup_module, "matches",
                        lambda e, w, t: (seen.append(e.path.name), real(e, w, t))[1])

    plan = build(ctx_for(tmp_path), BlockConfig(when={"ext": [".png"]}))

    assert quarantined(plan) == ["사진 (1).png"]
    # 무리를 이룬 세 파일에만 물었다. 하위 폴더 사진 20개는 건드리지 않는다.
    assert sorted(seen) == ["메모.txt", "사진 (1).png", "사진.png"]


def test_quarantine_carries_the_keeper_path(tmp_path):
    """`reason` 글자를 파싱하지 않고도 남기는 파일을 알 수 있어야 한다.

    이름만으로는 부족하다. 같은 이름이 여러 폴더에 있으면 어느 것인지 알 수
    없고, 화면이 「어느 자리를 남길까」를 보여줄 수 없다.
    """
    write(tmp_path / "가이드.pdf", b"SAME-CONTENT")
    write(tmp_path / "가이드 (1).pdf", b"SAME-CONTENT")

    plan = build(ctx_for(tmp_path), BlockConfig())

    보류 = [a for a in plan.actions if a.kind == "quarantine"]
    assert 보류, "이 테스트는 보류가 하나는 나와야 의미가 있다"
    for a in 보류:
        assert a.keeper is not None and a.keeper.is_absolute()
        assert a.keeper != a.src, "자기 자신을 남길 파일로 가리킬 수 없다"
        assert a.keeper.name == "가이드.pdf", "복사본 표식이 없는 쪽이 남는다"


def test_one_group_points_at_one_keeper(tmp_path):
    for 이름 in ("가이드.pdf", "가이드 (1).pdf", "가이드 (2).pdf"):
        write(tmp_path / 이름, b"SAME-CONTENT")

    plan = build(ctx_for(tmp_path), BlockConfig())

    보류 = [a for a in plan.actions if a.kind == "quarantine"]
    assert len(보류) == 2, "셋 중 하나만 남는다"
    assert len({a.keeper for a in 보류}) == 1, "한 무리는 keeper 가 하나다"
