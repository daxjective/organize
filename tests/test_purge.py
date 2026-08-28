"""보류한 파일 지우기.

**폴더를 통째로 지우지 않는다.** executor.py 의 실측 주석대로 같은 초의 두
실행은 보류 폴더를 공유한다(기록 파일만 `-2` 로 비켜 간다). 통째로 비우면
다른 실행이 넣어 둔 파일까지 날아간다.

**관문은 「보류 폴더 안」이다.** 「정리 대상 폴더 안」으로는 부족하다 — 손상된
기록 하나가 이 함수를 정리 대상 폴더 안 임의 파일 삭제기로 만든다(스펙 실측,
커밋 9e8ca5c). `trash_id` 도, 검사와 삭제가 보는 대상(심볼릭 링크)도 믿지
않는다.
"""

import json
import os
from pathlib import Path

import pytest

from organize.core.purge import purge_run
from organize.errors import OrganizeError


def _기록을_쓴다(root: Path, run_id: str, done: list[dict], trash_id: str | None = None) -> None:
    runs = root / ".organize" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{run_id}.json").write_text(
        json.dumps({"run_id": run_id, "trash_id": trash_id or run_id, "complete": True,
                    "finished_at": "2026-08-28T10:00:00", "done": done},
                   ensure_ascii=False), encoding="utf-8")


def _기록을_직접_쓴다(root: Path, run_id: str, payload: dict) -> None:
    """`_기록을_쓴다` 는 `done` 이 리스트라고 가정한다 — 형이 틀린 기록을 쓸 때 쓴다."""
    runs = root / ".organize" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{run_id}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


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
    """목적이 이미 이뤄졌다. 실패로 세면 사용자가 겁먹는다.

    이미 없는 항목 하나만 두면 "아무 일도 안 하는 스텁" 도 우연히 통과한다.
    실제로 지울 것도 하나 같이 둬서, 진짜로 지우는지까지 본다.
    """
    있는것 = _보류시킨다(tmp_path, "r1", "있는것.pdf")
    없는것 = tmp_path / ".organize" / "trash" / "r1" / "사라짐.pdf"
    _기록을_쓴다(tmp_path, "r1", [
        {"kind": "quarantine", "src": str(tmp_path / "x.pdf"), "final": str(없는것)},
        {"kind": "quarantine", "src": str(tmp_path / "y.pdf"), "final": str(있는것)},
    ])

    out = purge_run(tmp_path, "r1")

    assert out.failed == 0
    assert out.removed == 1, "실제로 있는 파일은 지워야 한다 — 스텁이면 여기서 걸린다"
    assert not 있는것.exists()


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

    out = purge_run(tmp_path, "r1")

    assert out.removed == 1 and not a.exists(), "내 것은 실제로 지워야 한다"
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


def test_없는_기록과_손상된_기록은_다른_문구다(tmp_path):
    """"기록" 이라는 단어만 같으면 되는 게 아니다 — 무엇이 문제인지 구분돼야 한다."""
    with pytest.raises(OrganizeError) as e1:
        purge_run(tmp_path, "없는실행")
    없는_메시지, 없는_힌트 = e1.value.message, e1.value.hint

    a = _보류시킨다(tmp_path, "r1", "a.pdf")
    runs = tmp_path / ".organize" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "r1.json").write_text("{망가진", encoding="utf-8")
    with pytest.raises(OrganizeError) as e2:
        purge_run(tmp_path, "r1")
    손상_메시지, 손상_힌트 = e2.value.message, e2.value.hint
    assert a.exists()

    assert 없는_메시지 != 손상_메시지
    assert "없습니다" in 없는_메시지 and "손상" not in 없는_메시지
    assert "손상" in 손상_메시지
    # 손상된 기록의 힌트는 실제로 망가진 자리(runs 폴더의 이 파일)를 짚어야
    # 한다 — trash 얘기만 하면 정작 원인이 있는 곳을 안 알려주는 셈이다.
    assert "r1.json" in 손상_힌트 or "runs" in 손상_힌트
    assert 없는_힌트 != 손상_힌트


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


def test_root_안이지만_보류_폴더_밖이면_지우지_않는다(tmp_path):
    """C1 — 관문은 「보류 폴더 안」이다. 「정리 대상 폴더(root) 안」으로는 부족하다.

    손상된 기록 하나가 `root/01_Docs/보고서.pdf` 를 quarantine 으로 담으면,
    "root 안이면 지운다" 는 검사로는 사용자의 진짜 문서가 지워진다 — 실측했다
    (스펙 9e8ca5c).
    """
    진짜문서 = tmp_path / "01_Docs" / "보고서.pdf"
    진짜문서.parent.mkdir(parents=True)
    진짜문서.write_bytes(b"DOC")
    _기록을_쓴다(tmp_path, "r1", [
        {"kind": "quarantine", "src": "x", "final": str(진짜문서)},
    ])

    out = purge_run(tmp_path, "r1")

    assert 진짜문서.exists(), "root 안이라는 이유만으로 사용자의 진짜 파일을 지웠다"
    assert out.failed == 1 and out.messages


def test_절대경로_trash_id는_root_밖을_건드리지_않는다(tmp_path):
    """C2 — `trash_id` 가 절대경로면 pathlib 이 앞부분을 버려 root 밖으로 튄다.

    실측: `root / ".organize" / "trash" / trash_id` 에서 trash_id 가
    절대경로면 root 밖 폴더의 `_manifest.json` 을 지우고 그 폴더까지
    `rmdir` 했다.
    """
    밖 = tmp_path.parent / "밖트래시"
    밖.mkdir()
    (밖 / "_manifest.json").write_text("[]", encoding="utf-8")
    # 실제 정리 완료 상황과 같은 모양(장부만 남음)이어야 "비었으면 치운다"
    # 분기가 실제로 동작해 버그가 재현된다 — 남의 파일이 섞여 있으면 기존의
    # "남의 파일이 있으면 안 건드린다" 보호막이 우연히 이 버그도 가려 버린다.

    _기록을_쓴다(tmp_path, "r1", [], trash_id=str(밖))

    purge_run(tmp_path, "r1")

    assert 밖.is_dir(), "trash_id 가 절대경로라서 root 밖 폴더가 통째로 지워졌다"
    assert (밖 / "_manifest.json").exists(), "trash_id 가 절대경로라서 root 밖 장부가 지워졌다"


def test_보류폴더_밖의_심볼릭링크는_지우지_않는다(tmp_path):
    """I3 — 검사(realpath)와 삭제(unlink)가 심볼릭 링크를 다르게 다룬다.

    심볼릭 링크 파일 자체는 보류 폴더 밖에 있으면서, 그 링크가 보류 폴더 안의
    실제 파일을 가리키면: 끝까지 풀어서 검사하면 "보류 폴더 안" 이라고
    오판하고, 그 오판을 믿고 `unlink()` 를 부르면 실제로 지워지는 건 보류
    폴더 밖의 링크 파일 자신이다.
    """
    실제 = _보류시킨다(tmp_path, "r1", "실제.pdf")
    밖의링크 = tmp_path.parent / "밖의링크.pdf"
    try:
        os.symlink(실제, 밖의링크)
    except (OSError, NotImplementedError):
        pytest.skip("이 플랫폼에서는 심볼릭 링크를 만들 수 없습니다")

    _기록을_쓴다(tmp_path, "r1", [
        {"kind": "quarantine", "src": "x", "final": str(밖의링크)},
    ])

    out = purge_run(tmp_path, "r1")

    assert 밖의링크.is_symlink(), "보류 폴더 밖의 링크 파일을 지웠다"
    assert 실제.exists()
    assert out.failed == 1


def test_done이_null이면_빈_것으로_본다(tmp_path):
    """I4 — `done: null` 이 파이썬 `TypeError` 로 새면 안 된다."""
    _기록을_직접_쓴다(tmp_path, "r1", {
        "run_id": "r1", "trash_id": "r1", "complete": True, "done": None,
    })

    out = purge_run(tmp_path, "r1")   # TypeError 가 새면 여기서 그대로 실패한다

    assert out.removed == 0 and out.failed == 0


def test_done이_리스트가_아니면_한국어로_알린다(tmp_path):
    """I4 — `done: 5` 는 `for x in 5` 라서 파이썬 `TypeError` 가 그대로 샌다."""
    _기록을_직접_쓴다(tmp_path, "r1", {
        "run_id": "r1", "trash_id": "r1", "complete": True, "done": 5,
    })

    with pytest.raises(OrganizeError) as e:
        purge_run(tmp_path, "r1")

    assert e.value.hint


def test_final이_문자열이_아니면_건너뛴다(tmp_path):
    """I4 — `final: 123` 은 `Path(123)` 에서 파이썬 `TypeError` 가 그대로 샌다."""
    _기록을_직접_쓴다(tmp_path, "r1", {
        "run_id": "r1", "trash_id": "r1", "complete": True,
        "done": [{"kind": "quarantine", "src": "x", "final": 123}],
    })

    out = purge_run(tmp_path, "r1")   # TypeError 가 새면 여기서 그대로 실패한다

    assert out.removed == 0 and out.failed == 0


def test_trash_id가_숫자면_정리를_건너뛴다(tmp_path):
    """I4 — `trash_id: 5` 는 `root / ... / 5` 에서 파이썬 `TypeError` 가 그대로 샌다.

    지우는 것 자체는 trash_id 와 무관하다 — 정리 정돈 단계만 건너뛰어야 한다.
    """
    a = _보류시킨다(tmp_path, "r1", "a.pdf")
    _기록을_직접_쓴다(tmp_path, "r1", {
        "run_id": "r1", "trash_id": 5, "complete": True,
        "done": [{"kind": "quarantine", "src": str(tmp_path / "a.pdf"), "final": str(a)}],
    })

    out = purge_run(tmp_path, "r1")   # TypeError 가 새면 여기서 그대로 실패한다

    assert out.removed == 1


def test_trash_id가_run_id와_다르면_그_폴더를_치운다(tmp_path):
    """`undo.py` 와 같은 이유: 기록 파일 이름은 충돌을 피해 `-2` 로 비켜 가도,
    격리 폴더 이름(trash_id)은 계획 때의 run_id 그대로다. 둘이 다를 수 있다."""
    a = _보류시킨다(tmp_path, "다른트래시", "a.pdf")
    (a.parent / "_manifest.json").write_text("[]", encoding="utf-8")
    _기록을_쓴다(tmp_path, "r1-2", [
        {"kind": "quarantine", "src": str(tmp_path / "a.pdf"), "final": str(a)},
    ], trash_id="다른트래시")

    purge_run(tmp_path, "r1-2")

    assert not a.parent.exists(), "trash_id 가 다른 폴더가 안 치워졌다"


def test_final이_폴더면_폴더라고_알린다(tmp_path):
    """M5 — `IsADirectoryError` 를 일반 OSError 문구로 알리면 "다른 프로그램이
    열고 있다" 는 거짓 안내가 된다. 기록이 잘못됐다고 알려야 한다."""
    trash = tmp_path / ".organize" / "trash" / "r1"
    trash.mkdir(parents=True)
    폴더 = trash / "폴더"
    폴더.mkdir()
    _기록을_쓴다(tmp_path, "r1", [
        {"kind": "quarantine", "src": "x", "final": str(폴더)},
    ])

    out = purge_run(tmp_path, "r1")

    assert 폴더.exists(), "폴더를 지우면 안 된다(디렉터리 unlink 는 애초에 안 되지만)"
    assert out.failed == 1
    assert any("폴더" in m for m in out.messages), "다른 프로그램이 열고 있다는 거짓 안내면 안 된다"
    assert not any("다른 프로그램" in m for m in out.messages)
