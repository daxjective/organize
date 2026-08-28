"""보류한 파일 지우기.

**폴더를 통째로 지우지 않는다.** executor.py 의 실측 주석대로 같은 초의 두
실행은 보류 폴더를 공유한다(기록 파일만 `-2` 로 비켜 간다). 통째로 비우면
다른 실행이 넣어 둔 파일까지 날아간다.
"""

import json
from pathlib import Path

import pytest

from organize.core.purge import purge_run
from organize.errors import OrganizeError


def _기록을_쓴다(root: Path, run_id: str, done: list[dict]) -> None:
    runs = root / ".organize" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{run_id}.json").write_text(
        json.dumps({"run_id": run_id, "trash_id": run_id, "complete": True,
                    "finished_at": "2026-08-28T10:00:00", "done": done},
                   ensure_ascii=False), encoding="utf-8")


def _보류시킨다(root: Path, run_id: str, 이름: str) -> Path:
    trash = root / ".organize" / "trash" / run_id
    trash.mkdir(parents=True, exist_ok=True)
    path = trash / 이름
    path.write_bytes(b"DATA")
    return path


def test_그_실행이_보류시킨_파일을_지운다(tmp_path):
    a = _보류시킨다(tmp_path, "r1", "a.pdf")
    b = _보류시킨다(tmp_path, "r1", "b.pdf")
    _기록을_쓴다(tmp_path, "r1", [
        {"kind": "quarantine", "src": str(tmp_path / "a.pdf"), "final": str(a)},
        {"kind": "quarantine", "src": str(tmp_path / "b.pdf"), "final": str(b)},
    ])

    out = purge_run(tmp_path, "r1")

    assert out.removed == 2 and out.failed == 0
    assert not a.exists() and not b.exists()


def test_옮긴_파일은_지우지_않는다(tmp_path):
    """quarantine 만 지운다. move 는 사용자가 원해서 옮긴 것이다."""
    옮긴것 = tmp_path / "01_Docs" / "보고서.pdf"
    옮긴것.parent.mkdir(parents=True)
    옮긴것.write_bytes(b"KEEP")
    보류 = _보류시킨다(tmp_path, "r1", "a.pdf")
    _기록을_쓴다(tmp_path, "r1", [
        {"kind": "move", "src": str(tmp_path / "보고서.pdf"), "final": str(옮긴것)},
        {"kind": "quarantine", "src": str(tmp_path / "a.pdf"), "final": str(보류)},
    ])

    out = purge_run(tmp_path, "r1")

    assert out.removed == 1
    assert 옮긴것.exists(), "옮긴 파일을 지우면 안 된다"


def test_다른_실행이_넣어_둔_파일은_남는다(tmp_path):
    """같은 초의 두 실행은 보류 폴더를 공유한다 — 폴더를 통째로 비우면 안 된다."""
    내것 = _보류시킨다(tmp_path, "r1", "a.pdf")
    남의것 = _보류시킨다(tmp_path, "r1", "남의것.pdf")   # 같은 폴더, 다른 실행
    _기록을_쓴다(tmp_path, "r1", [
        {"kind": "quarantine", "src": str(tmp_path / "a.pdf"), "final": str(내것)},
    ])

    out = purge_run(tmp_path, "r1")

    assert out.removed == 1
    assert 남의것.exists(), "다른 실행이 넣은 파일이 날아갔다"


def test_이미_없는_파일은_실패가_아니다(tmp_path):
    """목적이 이미 이뤄졌다. 실패로 세면 사용자가 겁먹는다."""
    없는것 = tmp_path / ".organize" / "trash" / "r1" / "사라짐.pdf"
    _기록을_쓴다(tmp_path, "r1", [
        {"kind": "quarantine", "src": str(tmp_path / "x.pdf"), "final": str(없는것)},
    ])

    out = purge_run(tmp_path, "r1")

    assert out.failed == 0
    assert out.removed == 0


def test_다_지우면_빈_보류_폴더를_치운다(tmp_path):
    a = _보류시킨다(tmp_path, "r1", "a.pdf")
    (a.parent / "_manifest.json").write_text("[]", encoding="utf-8")
    _기록을_쓴다(tmp_path, "r1", [
        {"kind": "quarantine", "src": str(tmp_path / "a.pdf"), "final": str(a)},
    ])

    purge_run(tmp_path, "r1")

    assert not a.parent.exists(), "우리가 만든 장부와 빈 폴더는 치운다"


def test_남의_파일이_남아_있으면_폴더를_안_치운다(tmp_path):
    a = _보류시킨다(tmp_path, "r1", "a.pdf")
    남의것 = _보류시킨다(tmp_path, "r1", "남의것.pdf")
    _기록을_쓴다(tmp_path, "r1", [
        {"kind": "quarantine", "src": str(tmp_path / "a.pdf"), "final": str(a)},
    ])

    purge_run(tmp_path, "r1")

    assert 남의것.exists() and 남의것.parent.is_dir()


def test_없는_기록이면_한국어로_알린다(tmp_path):
    with pytest.raises(OrganizeError) as e:
        purge_run(tmp_path, "없는실행")

    assert "기록" in e.value.message
    assert e.value.hint


def test_손상된_기록이면_아무것도_안_지운다(tmp_path):
    a = _보류시킨다(tmp_path, "r1", "a.pdf")
    runs = tmp_path / ".organize" / "runs"
    runs.mkdir(parents=True)
    (runs / "r1.json").write_text("{망가진", encoding="utf-8")

    with pytest.raises(OrganizeError):
        purge_run(tmp_path, "r1")

    assert a.exists(), "못 읽는 기록으로 파일을 지우면 안 된다"


def test_정리_대상_폴더_밖은_지우지_않는다(tmp_path):
    """기록이 손상되었거나 조작되었을 때의 마지막 관문."""
    밖 = tmp_path.parent / "밖에있는것.pdf"
    밖.write_bytes(b"KEEP")
    _기록을_쓴다(tmp_path, "r1", [
        {"kind": "quarantine", "src": "x", "final": str(밖)},
    ])

    out = purge_run(tmp_path, "r1")

    assert 밖.exists(), "정리 대상 폴더 밖의 파일을 지웠다"
    assert out.failed == 1 and out.messages
