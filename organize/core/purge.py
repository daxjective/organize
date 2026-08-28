"""보류한 파일을 지운다.

`undo.py` 첫 줄이 "파일을 지우지 않았기 때문에 되돌릴 수 있다" 인 도구에서,
**여기만이 사용자 파일을 진짜로 지우는 자리**다. 그래서 규칙이 있다.

1. **폴더를 통째로 지우지 않는다.** `executor.py` 의 실측 주석대로 같은 초의 두
   실행은 보류 폴더를 공유한다(기록 파일만 `-2` 로 비켜 간다). 통째로 비우면
   다른 실행이 넣어 둔 파일까지 날아간다. 기록에 적힌 경로만 하나씩 지운다.
2. **`quarantine` 만 지운다.** 옮긴 파일은 사용자가 원해서 옮긴 것이다.
3. **관문은 「보류 폴더(`.organize/trash/`) 안」이다 — 「정리 대상 폴더 안」으로는
   부족하다.** 기록이 손상되었거나 손으로 고쳐졌을 때의 마지막 관문인데,
   "정리 대상 폴더 안이면 지운다" 로 두면 손상된 기록 하나가 이 함수를
   **정리 대상 폴더 안 임의 파일 삭제기**로 만든다 — 리뷰에서 실측했다
   (스펙 `2026-08-28-보류-무리보기-design.md`, 커밋 9e8ca5c).
4. **검사와 삭제가 같은 대상을 봐야 한다.** `os.path.realpath` 는 심볼릭 링크를
   풀고 `unlink()` 는 풀지 않는다 — 부모까지만 풀고 마지막 이름은 그대로 두어,
   검사를 통과한 바로 그 자리를 지운다. 아니면 보류 폴더 밖의 링크 파일이
   "보류 폴더 안을 가리킨다" 는 이유만으로 검사를 통과하고, 실제로 지워지는 건
   그 링크 파일 자신(보류 폴더 밖)이 된다 — 실측했다.
5. **`trash_id` 도 신뢰하지 않는다.** 기록에서 그대로 온 값이 경로에 이어
   붙는다. 절대경로면 `root / ".organize" / "trash" / trash_id` 에서 pathlib 이
   앞부분을 버려 **root 밖으로 튄다** — 실측: root 밖 폴더의 `_manifest.json`
   을 지우고 그 폴더까지 `rmdir` 했다. 문자열 모양부터 걸러내고, 이어붙인
   뒤에도 다시 한 번 보류 폴더 안인지 본다.

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


def _runs_dir(root: Path) -> Path:
    return root / ".organize" / "runs"


def _trash_root(root: Path) -> Path:
    return root / ".organize" / "trash"


def purge_run(root: Path, run_id: str) -> PurgeResult:
    """`run_id` 실행이 보류시킨 파일만, 보류 폴더 안에서만 지운다."""
    root = Path(root)
    data = _기록을_읽는다(root, run_id)
    out = PurgeResult()
    trash_root = _trash_root(root)

    items = data.get("done")
    if items is None:
        items = []          # 예전 기록이거나 아무것도 안 한 실행 — 빈 것으로 본다
    if not isinstance(items, list):
        # 파이썬은 `for x in 5` 에서 TypeError 를 그대로 던진다 — 전역 규칙 위반이다.
        raise OrganizeError(
            f"'{run_id}' 실행 기록의 모양이 이상해 무엇을 지울지 알 수 없습니다.",
            hint=f"'{_runs_dir(root) / f'{run_id}.json'}' 파일이 손으로 고쳐졌을 수 있습니다.")

    for item in items:
        if not isinstance(item, dict) or item.get("kind") != "quarantine":
            continue
        final = item.get("final")
        if not isinstance(final, str) or not final:
            continue          # 손상된 항목이다 — 조용히 건너뛴다(형이 달라도 TypeError 는 안 낸다)
        path = Path(final)
        real = _보류폴더_안이면_실제경로를(path, trash_root)
        if real is None:
            # 조용히 넘기지 않는다 — 기록이 이상하다는 것 자체가 알릴 일이다.
            out.failed += 1
            out.messages.append(f"보류 폴더 밖이라 지우지 않았습니다: {path}")
            continue
        try:
            real.unlink()
            out.removed += 1
        except FileNotFoundError:
            pass          # 이미 없다 — 목적이 이뤄졌다. 실패가 아니다
        except IsADirectoryError:
            # 다른 OSError 와 같은 문구를 쓰면 "다른 프로그램이 열고 있다" 는
            # 거짓 안내가 된다 — 여기는 기록 자체가 잘못됐다는 뜻이다.
            out.failed += 1
            out.messages.append(
                f"파일이 아니라 폴더라서 지우지 않았습니다 — 기록이 잘못된 것 같습니다: {path}")
        except OSError:
            out.failed += 1
            out.messages.append(f"지우지 못했습니다: {path}"
                                "  다른 프로그램이 열고 있을 수 있습니다.")

    _빈_보류_폴더를_치운다(root, data.get("trash_id") or run_id)
    return out


def _기록을_읽는다(root: Path, run_id: str) -> dict:
    path = _runs_dir(root) / f"{run_id}.json"
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
            # 무엇이 망가졌는지 볼 자리는 trash 가 아니라 이 기록 파일이 있는
            # runs 폴더다(undo.py 도 손상 기록에서 두 자리를 같이 짚는다) —
            # trash 만 짚으면 정작 원인이 있는 자리를 안 알려주는 셈이다.
            hint=f"'{path}' 파일이 손상되었을 수 있습니다. "
                 f"'{_trash_root(root)}' 에 무엇이 보류돼 있었는지도 같이 확인해 주세요.") from e
    return data


def _보류폴더_안이면_실제경로를(path: Path, trash_root: Path) -> Path | None:
    """`path` 가 보류 폴더(`trash_root`) 안이면, 검사·삭제가 같은 대상을 보도록
    정리한 실제 경로를 돌려준다. 밖이거나 확인할 수 없으면 `None`.

    "정리 대상 폴더 안이면 지운다" 로는 부족하다 — 손상된 기록 하나가 이 함수를
    "정리 대상 폴더 안 임의 파일 삭제기" 로 만든다(스펙 실측, 9e8ca5c). 보류
    폴더 안일 때만 지운다.

    부모만 `realpath` 로 풀고 마지막 이름은 그대로 둔다. 전부 풀면(심볼릭 링크
    끝까지 따라가면) 보류 폴더 밖에 있는 링크 파일이 "보류 폴더 안의 무언가를
    가리킨다" 는 이유만으로 검사를 통과하고, 그 판정을 믿고 `unlink()` 를
    부르면 실제로 지워지는 건 그 링크 파일 자신(보류 폴더 밖)이다 — 검사와
    삭제가 다른 대상을 보면 검사가 무의미해진다.
    """
    try:
        real = Path(os.path.realpath(path.parent)) / path.name
        real_trash_root = Path(os.path.realpath(trash_root))
    except OSError:
        return None
    return real if real.is_relative_to(real_trash_root) else None


def _안전한_트래시ID인가(trash_id: object) -> bool:
    """`trash_id` 를 경로 조각으로 그대로 이어 붙여도 되는가.

    기록에서 그대로 온 값이라 믿을 수 없다. 문자열이 아니거나, 비었거나,
    경로 구분자(`/`, `\\`)를 담고 있거나, `.`/`..` 면 거부한다 — 절대경로가
    오면 `root / ".organize" / "trash" / trash_id` 에서 pathlib 이 앞부분을
    버려 **root 밖으로 튄다**(스펙 실측, 9e8ca5c: root 밖 폴더의
    `_manifest.json` 을 지우고 그 폴더까지 `rmdir` 했다).
    """
    return (isinstance(trash_id, str) and trash_id not in ("", ".", "..")
            and "/" not in trash_id and "\\" not in trash_id)


def _빈_보류_폴더를_치운다(root: Path, trash_id: object) -> None:
    """우리가 만든 장부와 빈 폴더만 치운다. `undo.py` 의 규칙 그대로다.

    사용자 파일이 하나라도 남아 있으면 **아무것도 건드리지 않는다** — 그 장부가
    그 파일이 무엇이고 어디서 왔는지 적힌 유일한 기록이기 때문이다.

    정리 정돈은 청소일 뿐이다 — `trash_id` 가 의심스러우면(문자열이 아니거나,
    경로 조각을 담고 있거나, 보류 폴더 밖으로 새면) 그냥 아무것도 안 한다.
    그게 항상 안전하다.
    """
    if not _안전한_트래시ID인가(trash_id):
        return
    trash_root = _trash_root(root)
    trash = _보류폴더_안이면_실제경로를(trash_root / trash_id, trash_root)
    if trash is None:
        return  # 문자열 검증을 통과했어도 다시 한 번 확인한다 — 마지막 관문
    try:
        if trash.is_symlink():
            return  # 격리 폴더 이름 자리에 심볼릭 링크가 있으면 의심스럽다 — 손대지 않는다
        if not trash.is_dir():
            return
        if any(p.name != "_manifest.json" for p in trash.iterdir()):
            return
        (trash / "_manifest.json").unlink(missing_ok=True)
        trash.rmdir()
        trash.parent.rmdir()
    except OSError:
        pass                 # 못 치워도 지우기 자체는 성공이다
