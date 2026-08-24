"""실행 로그를 역순으로 재생해 되돌린다.

파일을 지우지 않았기 때문에 되돌릴 수 있다. 격리 폴더에 있는 것은 제자리로,
옮긴 것은 원래 위치로 돌린다. 압축을 푼 파일만은 되돌릴 곳이 없으므로
격리 폴더로 보낸다.

폴더는 "비어 있으면 지운다" 만 본다 — 이 실행이 그 폴더를 만들었는지는
따로 추적하지 않는다. 비어 있다는 것 자체가 잃을 내용이 없다는 뜻이므로
안전하다. 사용자가 뭔가 넣어 뒀다면(비어 있지 않다면) 손대지 않는다.
"""

import json
from datetime import datetime
from pathlib import Path

from organize.core.executor import ExecResult
from organize.core.paths import move_file
from organize.errors import OrganizeError


def _runs_dir(root: Path) -> Path:
    return root / ".organize" / "runs"


def list_runs(root: Path) -> list[dict]:
    runs_dir = _runs_dir(root)
    if not runs_dir.is_dir():
        return []
    rows = []
    for path in sorted(runs_dir.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows.append({
            "run_id": data.get("run_id", path.stem),
            "finished_at": data.get("finished_at"),
            "undone_at": data.get("undone_at"),
            "count": len(data.get("done", [])),
        })
    return rows


def latest_run_id(root: Path) -> str | None:
    for row in list_runs(root):
        if row["undone_at"] is None and row["count"]:
            return row["run_id"]
    return None


def undo(root: Path, run_id: str | None = None) -> ExecResult:
    resolved_id = run_id or latest_run_id(root)
    if resolved_id is None:
        raise OrganizeError(
            "되돌릴 실행 기록이 없습니다.",
            hint="organize run <레시피> --apply 로 한 번 실행한 뒤에 쓸 수 있습니다.",
        )

    log_path = _runs_dir(root) / f"{resolved_id}.json"
    if not log_path.is_file():
        # Task 18 리뷰 Minor #1 — organize trash 커맨드는 존재하지 않는다
        # (Task 19 범위). 실제로 있는 명령과, 기록이 어디 있는지로 안내한다.
        raise OrganizeError(
            f"'{resolved_id}' 실행 기록을 찾을 수 없습니다.",
            hint=f"'{_runs_dir(root)}' 에 남은 실행 기록을 확인해 주세요. "
                 "organize undo --root <폴더> 로 가장 최근 실행을 되돌릴 수 있습니다.",
        )

    data = json.loads(log_path.read_text(encoding="utf-8"))
    if data.get("undone_at"):
        # 두 번 되돌리는 경우: 이미 restore 된 파일은 옮긴 자리에 없으므로
        # 그대로 진행하면 "옮기려는 파일이 없습니다" 가 항목마다 실패로
        # 쌓여 사용자를 혼란스럽게 한다. 시도 자체를 막고 이유를 알려준다.
        raise OrganizeError(
            f"'{resolved_id}' 실행은 이미 되돌렸습니다 ({data['undone_at']}).",
            hint="같은 실행을 두 번 되돌릴 수는 없습니다. "
                 f"'{_runs_dir(root)}' 에서 다른 실행 ID 를 찾아 "
                 "organize undo <실행ID> --root <폴더> 로 되돌려 주세요.",
        )

    result = ExecResult()
    undo_trash = root / ".organize" / "trash" / f"{resolved_id}-undo"

    # 마지막에 한 일부터 되돌려야 경로가 맞는다 — route 뒤에 by_date 가
    # 한 번 더 옮겼다면, by_date 부터 풀어야 route 가 남긴 자리로 돌아간다.
    for item in reversed(data.get("done", [])):
        kind = item["kind"]
        try:
            if kind == "mkdir":
                folder = Path(item["final"])
                if folder.is_dir() and not any(folder.iterdir()):
                    folder.rmdir()                       # 비어 있을 때만 지운다
                    result.done.append({"kind": "rmdir", "final": str(folder)})
                continue

            final = Path(item["final"])
            if kind in ("move", "quarantine"):
                back = move_file(final, Path(item["src"]))
                result.done.append({"kind": "restore", "src": str(final), "final": str(back)})
            elif kind == "extract":
                # 압축을 푼 파일은 되돌릴 자리가 없다(원본은 zip 안이다).
                # 그대로 두면 되돌린 뒤에도 폴더가 되돌리기 전보다 어수선해지므로
                # 격리 폴더로 보낸다 — 원본 zip 은 건드리지 않는다.
                moved = move_file(final, undo_trash / final.name)
                result.done.append({"kind": "quarantine", "src": str(final), "final": str(moved)})

        except OrganizeError as e:
            # hint 를 버리지 않는다 — executor.py 와 같은 이유다.
            result.failed.append({
                "kind": kind, "src": item.get("final"), "why": e.message, "hint": e.hint,
            })
        except OSError:
            # 파이썬 예외 원문을 그대로 보여주지 않는다 — hint 자리에 예외
            # 원문을 넣지 말라는 전역 규칙과 같은 이유다.
            name = Path(item.get("final") or "").name
            result.failed.append({
                "kind": kind, "src": item.get("final"),
                "why": f"되돌리지 못했습니다: {name}",
                "hint": "대상 위치의 쓰기 권한이나 파일이 다른 프로그램에서 열려있는지 확인해 주세요.",
            })

    data["undone_at"] = datetime.now().isoformat(timespec="seconds")
    log_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
