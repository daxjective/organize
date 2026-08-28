"""보류한 파일을 지운다.

`undo.py` 첫 줄이 "파일을 지우지 않았기 때문에 되돌릴 수 있다" 인 도구에서,
**여기만이 사용자 파일을 진짜로 지우는 자리**다. 그래서 규칙이 셋 있다.

1. **폴더를 통째로 지우지 않는다.** `executor.py` 의 실측 주석대로 같은 초의 두
   실행은 보류 폴더를 공유한다(기록 파일만 `-2` 로 비켜 간다). 통째로 비우면
   다른 실행이 넣어 둔 파일까지 날아간다. 기록에 적힌 경로만 하나씩 지운다.
2. **`quarantine` 만 지운다.** 옮긴 파일은 사용자가 원해서 옮긴 것이다.
3. **정리 대상 폴더 밖은 지우지 않는다.** 기록이 손상되었거나 손으로 고쳐졌을
   때의 마지막 관문이다 — `dest_folder` 가 목적지를 막는 것과 같은 이유다.

부르기 전에 사용자에게 물어보는 일은 창이 한다. 여기는 묻지 않는다.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from organize.errors import OrganizeError


@dataclass
class PurgeResult:
    removed: int = 0
    failed: int = 0
    messages: list[str] = field(default_factory=list)


def purge_run(root: Path, run_id: str) -> PurgeResult:
    """`run_id` 실행이 보류시킨 파일만 지운다."""
    root = Path(root)
    data = _기록을_읽는다(root, run_id)
    out = PurgeResult()

    for item in data.get("done", []):
        if not isinstance(item, dict) or item.get("kind") != "quarantine":
            continue
        final = item.get("final")
        if not final:
            continue
        path = Path(final)
        if not _안쪽인가(path, root):
            # 조용히 넘기지 않는다 — 기록이 이상하다는 것 자체가 알릴 일이다.
            out.failed += 1
            out.messages.append(f"정리 대상 폴더 밖이라 지우지 않았습니다: {path}")
            continue
        try:
            path.unlink()
            out.removed += 1
        except FileNotFoundError:
            pass          # 이미 없다 — 목적이 이뤄졌다. 실패가 아니다
        except OSError:
            out.failed += 1
            out.messages.append(f"지우지 못했습니다: {path}"
                                "  다른 프로그램이 열고 있을 수 있습니다.")

    _빈_보류_폴더를_치운다(root, data.get("trash_id") or run_id)
    return out


def _기록을_읽는다(root: Path, run_id: str) -> dict:
    path = root / ".organize" / "runs" / f"{run_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("기록의 모양이 다르다")
    except FileNotFoundError as e:
        raise OrganizeError(
            f"'{run_id}' 실행 기록이 없습니다.",
            hint="한 번 실행한 뒤에 쓸 수 있습니다.") from e
    except (OSError, ValueError) as e:
        # 파이썬 예외 원문을 그대로 보여주지 않는다(전역 규칙).
        raise OrganizeError(
            f"'{run_id}' 실행 기록이 손상되어 읽을 수 없습니다.",
            hint=f"'{root / '.organize' / 'trash'}' 를 직접 열어 확인해 주세요.") from e
    return data


def _안쪽인가(path: Path, root: Path) -> bool:
    """정리 대상 폴더 안인가. 심볼릭 링크까지 따져 실제 자리로 본다."""
    try:
        return Path(os.path.realpath(path)).is_relative_to(
            Path(os.path.realpath(root)))
    except OSError:
        return False


def _빈_보류_폴더를_치운다(root: Path, trash_id: str) -> None:
    """우리가 만든 장부와 빈 폴더만 치운다. `undo.py` 의 규칙 그대로다.

    사용자 파일이 하나라도 남아 있으면 **아무것도 건드리지 않는다** — 그 장부가
    그 파일이 무엇이고 어디서 왔는지 적힌 유일한 기록이기 때문이다.
    """
    trash = root / ".organize" / "trash" / trash_id
    try:
        if not trash.is_dir():
            return
        if any(p.name != "_manifest.json" for p in trash.iterdir()):
            return
        (trash / "_manifest.json").unlink(missing_ok=True)
        trash.rmdir()
        trash.parent.rmdir()
    except OSError:
        pass                 # 못 치워도 지우기 자체는 성공이다
