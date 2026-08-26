"""실행 로그를 역순으로 재생해 되돌린다.

파일을 지우지 않았기 때문에 되돌릴 수 있다. 격리 폴더에 있는 것은 제자리로,
옮긴 것은 원래 위치로 돌린다. 압축을 푼 파일만은 되돌릴 곳이 없으므로
격리 폴더로 보낸다.

폴더는 "비어 있으면 지운다" 만 본다 — 이 실행이 그 폴더를 만들었는지는
따로 추적하지 않는다. 비어 있다는 것 자체가 잃을 내용이 없다는 뜻이므로
안전하다. 사용자가 뭔가 넣어 뒀다면(비어 있지 않다면) 손대지 않는다.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

from organize.core.executor import ExecResult, write_json_atomic
from organize.core.paths import move_file
from organize.errors import OrganizeError


def _runs_dir(root: Path) -> Path:
    return root / ".organize" / "runs"


# `make_run_id` 가 만드는 모양(`%Y%m%d-%H%M%S`)과, 이름이 겹쳐 비켜 갈 때
# `_claim_runlog_path` 가 붙이는 접미사(`-2`, `-3` …).
_RUN_STEM = re.compile(r"(?P<stamp>\d{8}-\d{6})(?:-(?P<n>\d+))?")


def _run_order(stem: str) -> tuple[str, int]:
    """실행 기록 파일 이름을 **실제 순서**로 비교할 수 있는 키로 바꾼다.

    파일 이름 문자열을 그대로 정렬하면 안 된다. `'-'`(45) 가 `'.'`(46) 보다
    작아서 이렇게 갈린다:

        sorted(['20260824-193928.json', '20260824-193928-2.json'], reverse=True)
        -> ['20260824-193928.json', '20260824-193928-2.json']
              ^ 먼저 만든 기록이 맨 앞

    그러면 `latest_run_id` 가 **옛 기록**을 집는다. 되돌리기는 반드시 시간
    역순이어야 한다 — 한 파일을 두 실행이 이어서 옮겼다면(실행1: `a.pdf →
    01_Docs`, 실행2: `01_Docs/a.pdf → 보관`) 옛 실행을 먼저 되돌릴 때 그
    자리에 파일이 없다. 실측했다: "옮기려는 파일이 없습니다: a.pdf".
    덤으로 빈 폴더도 남는다(옛 실행이 만든 폴더 안에 아직 새 실행의 파일이
    있어 "비어있지 않다" 로 판정되고, 새 기록에는 그 폴더의 mkdir 항목이 없다).

    그래서 **시각과 접미사 번호를 따로** 본다. 시각 부분은 고정폭이라
    문자열 비교가 곧 시간 비교다. 접미사가 없으면 0 — 같은 초의 첫 기록이
    `-2` 보다 앞선다는 뜻이고, 실제로 그렇다.

    우리가 만든 형식이 아닌 이름(테스트의 `r1`, 사람이 손으로 만든 파일)도
    죽지 않아야 하므로, 일반적인 `-숫자` 접미사만 떼어 보고 못 떼면 이름 그대로 쓴다.
    """
    m = _RUN_STEM.fullmatch(stem)
    if m:
        return m["stamp"], int(m["n"] or 0)
    base, _, tail = stem.rpartition("-")
    if base and tail.isdigit():
        return base, int(tail)
    return stem, 0


def list_runs(root: Path) -> list[dict]:
    """실행 기록 목록. **못 읽은 기록도 빠뜨리지 않고 알린다.**

    예전에는 깨진 기록을 조용히 `continue` 했다. 그래서 그 기록은 **없는 것처럼**
    취급됐고, 파일은 옮겨져 있는데 `undo` 는 "되돌릴 실행 기록이 없습니다",
    `doctor` 는 "없음 (확인함)" 이라고 답했다 — 이 프로젝트가 여덟 번 물린
    "조용한 무작동" 의 가장 순수한 형태다. 실측했다.

    되돌릴 대상으로 집지 않는 것은 그대로다(`latest_run_id` 가 거른다).
    **없는 척하지 않는 것**이 요점이다.
    """
    runs_dir = _runs_dir(root)
    if not runs_dir.is_dir():
        return []
    rows = []
    # 파일 이름 문자열이 아니라 (시각, 접미사 번호) 로 내림차순 정렬한다.
    # 이 목록의 맨 앞이 곧 `latest_run_id` 가 집는 기록이다 — 순서가 틀리면
    # 되돌리기가 시간 역순이 아니게 된다(_run_order 참고).
    # 못 읽는 기록도 이름만으로 키가 나오므로 정렬이 죽지 않는다.
    for path in sorted(runs_dir.glob("*.json"),
                       key=lambda p: _run_order(p.stem), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("기록의 모양이 다르다")
        except (OSError, ValueError):
            # JSONDecodeError 는 ValueError 의 자식이다. 내용이 dict 가 아닌
            # 경우도 같이 받는다 — 아래 .get 이 AttributeError 로 터진다.
            rows.append({
                "run_id": path.stem, "finished_at": None, "undone_at": None,
                "count": 0, "unreadable": True, "path": str(path),
            })
            continue
        rows.append({
            "run_id": data.get("run_id", path.stem),
            "finished_at": data.get("finished_at"),
            "undone_at": data.get("undone_at"),
            "count": len(data.get("done", [])),
            # 뼈대(prepare_runlog 이 실행 **전에** 쓴 것)인가. 옛 기록에는 이
            # 키가 아예 없다 — 그건 write_runlog 이 쓴 완전한 기록이다.
            # 이 정보가 행에 없어서 `undo` 가 끊긴 실행을 알아보지 못했다.
            "complete": data.get("complete"),
            "unreadable": False,
            "path": str(path),
        })
    return rows


def unreadable_runs(root: Path) -> list[str]:
    """읽지 못한 실행 기록의 파일 경로. doctor 와 undo 가 사람에게 알릴 때 쓴다."""
    return [row["path"] for row in list_runs(root) if row["unreadable"]]


def latest_run_id(root: Path) -> str | None:
    for row in list_runs(root):
        if row["unreadable"] or row["complete"] is False:
            # 무엇을 옮겼는지 모르는 기록은 되돌릴 수 없다. **없는 척하지도
            # 않는다** — 부르는 쪽(undo)이 _unusable_runs 로 사실대로 알린다.
            continue
        if row["undone_at"] is None and row["count"]:
            return row["run_id"]
    return None


def _no_run_to_undo(root: Path) -> OrganizeError:
    """되돌릴 대상을 못 고른 이유를 **사실대로** 말한다.

    예전에는 여기서 무조건 "되돌릴 실행 기록이 없습니다 / organize run --apply 로
    한 번 실행한 뒤에 쓸 수 있습니다" 가 나왔다. 실행이 중간에 끊긴 뒤라면
    **새빨간 거짓말이다** — 사용자는 방금 실행했고 파일은 옮겨져 있다.
    C3 수정이 "못 읽은 기록" 갈래에만 분기를 달아서, 훨씬 흔한
    "완전하지 않은 기록" 갈래가 그 옆을 그대로 빠져나갔다. 실측한 결함이다.

    `undo <실행ID>` 로 콕 집으면 옛 코드도 올바른 말을 했다 — 사람이 실제로
    치는 `undo --root` 만 몰랐다. 그래서 이 함수의 자리는
    **run_id 를 주지 않은 경로**다.
    """
    rows = list_runs(root)
    if not rows:
        # 정말로 기록이 하나도 없다 — 이때만 "실행한 적 없다" 가 사실이다.
        return OrganizeError(
            "되돌릴 실행 기록이 없습니다.",
            hint="organize run <레시피> --apply 로 한 번 실행한 뒤에 쓸 수 있습니다.")

    unreadable = [r for r in rows if r["unreadable"]]
    incomplete = [r for r in rows if not r["unreadable"] and r["complete"] is False]
    if incomplete or unreadable:
        parts = []
        if incomplete:
            parts.append(f"기록이 완전하지 않은 실행 {len(incomplete)}개")
        if unreadable:
            parts.append(f"읽지 못한 기록 {len(unreadable)}개")
        names = ", ".join(Path(r["path"]).name for r in incomplete + unreadable)
        return OrganizeError(
            "되돌릴 수 있는 실행 기록이 없습니다 — " + " · ".join(parts) + f": {names}",
            hint="실행이 중간에 끊겼거나 기록을 남기지 못한 경우입니다. 무엇을 옮겼는지 "
                 f"알 수 없으니 '{root}' 안에 새로 생긴 폴더와 "
                 f"'{root / '.organize' / 'trash'}' 를 직접 확인해 주세요.")

    undone = [r for r in rows if r["undone_at"]]
    empty = [r for r in rows if not r["undone_at"] and not r["count"]]
    return OrganizeError(
        f"되돌릴 것이 남아 있지 않습니다 (실행 기록 {len(rows)}개 · "
        f"이미 되돌린 실행 {len(undone)}개 · 옮긴 것이 없는 실행 {len(empty)}개).",
        hint=f"'{_runs_dir(root)}' 에서 실행 ID 를 고른 뒤 "
             "organize undo <실행ID> --root <폴더> 로 특정 실행을 지정할 수 있습니다.")


def undo(root: Path, run_id: str | None = None) -> ExecResult:
    resolved_id = run_id or latest_run_id(root)
    if resolved_id is None:
        raise _no_run_to_undo(root)

    log_path = _runs_dir(root) / f"{resolved_id}.json"
    if not log_path.is_file():
        # Task 18 리뷰 Minor #1 — organize trash 커맨드는 존재하지 않는다
        # (Task 19 범위). 실제로 있는 명령과, 기록이 어디 있는지로 안내한다.
        raise OrganizeError(
            f"'{resolved_id}' 실행 기록을 찾을 수 없습니다.",
            hint=f"'{_runs_dir(root)}' 에 남은 실행 기록을 확인해 주세요. "
                 "organize undo --root <폴더> 로 가장 최근 실행을 되돌릴 수 있습니다.",
        )

    try:
        data = json.loads(log_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("기록의 모양이 다르다")
    except (OSError, ValueError) as e:
        # JSONDecodeError(ValueError 의 자식)가 그대로 새면 파이썬 트레이스백이
        # 화면에 뜬다 — 전역 규칙 위반이자, 사용자가 다음에 뭘 해야 할지
        # 알 수 없게 만드는 자리다.
        raise OrganizeError(
            f"'{resolved_id}' 실행 기록이 손상되어 읽을 수 없습니다: {log_path.name}",
            hint=f"쓰는 도중에 끊긴 기록일 수 있습니다. '{root}' 안에 새로 생긴 폴더와 "
                 f"'{root / '.organize' / 'trash'}' 를 직접 확인해 주세요.",
        ) from e

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

    if data.get("complete") is False:
        # 뼈대 기록이다 — prepare_runlog 이 실행 **전에** 써 두고, execute() 가
        # 끝난 뒤 write_runlog 이 진짜 결과로 덮어쓴다. 덮어쓰이지 않았다는 것은
        # **실행 중에 끊겼거나 기록을 못 남겼다**는 뜻이고, 그때가 바로 파일은
        # 옮겨졌는데 무엇을 옮겼는지 모르는 상황이다.
        # done 이 비어 있다고 "되돌릴 게 없다" 로 읽으면 all([]) 이 참이라
        # 되돌렸다고 도장을 찍어 버려, 옮겨진 파일이 영영 갇히고 재시도까지
        # 막힌다. 실측한 결함이다. 아무것도 건드리지 않고 사실대로 알린다.
        # (옛 기록에는 'complete' 자체가 없다 — 그건 write_runlog 이 쓴 것이므로
        #  완전한 기록이다. `is False` 로만 걸러 하위 호환을 지킨다.)
        raise OrganizeError(
            f"'{resolved_id}' 실행은 기록이 완전하지 않아 되돌릴 수 없습니다 "
            "— 무엇을 옮겼는지 알 수 없습니다.",
            hint="실행이 중간에 끊겼거나 기록을 남기지 못한 경우입니다. "
                 f"'{root}' 안에 새로 생긴 폴더와 "
                 f"'{root / '.organize' / 'trash'}' 를 직접 확인해 주세요.",
        )

    result = ExecResult()
    undo_trash = root / ".organize" / "trash" / f"{resolved_id}-undo"
    items = data.get("done", [])

    try:
        # 마지막에 한 일부터 되돌려야 경로가 맞는다 — route 뒤에 by_date 가
        # 한 번 더 옮겼다면, by_date 부터 풀어야 route 가 남긴 자리로 돌아간다.
        for item in reversed(items):
            if item.get("undone"):
                continue                 # 앞선 시도에서 이미 되돌렸다
            kind = item.get("kind", "")
            if kind not in ("mkdir", "move", "quarantine", "extract"):
                # 손상됐거나 우리가 모르는 항목이다. 예전에는 여기서 item["kind"]
                # 가 KeyError 를 내고 그 파이썬 예외가 화면까지 그대로 샜다.
                # 더 해 볼 수 있는 게 없으므로 '끝난 것' 으로 보되, 조용히
                # 넘기지 않고 무엇이 이상한지 남긴다.
                item["undone"] = True
                result.failed.append({
                    "kind": kind or "?", "src": item.get("final"),
                    "why": "실행 기록의 항목을 알아볼 수 없어 건너뜁니다",
                    "hint": f"'{log_path}' 파일이 손상되었을 수 있습니다.",
                })
                continue
            try:
                if kind == "mkdir":
                    folder = Path(item["final"])
                    if folder.is_dir():
                        if not any(folder.iterdir()):
                            folder.rmdir()               # 비어 있을 때만 지운다
                            result.done.append({"kind": "rmdir", "final": str(folder)})
                    elif _missing_medium(folder) is not None:
                        # 폴더가 없는 게 아니라 **매체가 통째로 안 보인다.** 여기서
                        # '끝났다' 고 찍으면 매체를 다시 꽂아도 이 폴더는 영영
                        # 안 치워지고, 되돌리기가 끝난 자리에 빈 폴더만 남는다.
                        result.failed.append(_failure(kind, item, "", None))
                        continue                         # undone 을 찍지 않는다
                    item["undone"] = True
                    continue

                final = Path(item["final"])
                if kind in ("move", "quarantine"):
                    intended = Path(item["src"])
                    back = move_file(final, intended)
                    # 원래 자리를 쓸 수 없으면 move_file 이 `a_(1).pdf` 로 비켜
                    # 놓는다(덮어쓰지 않는 것이 옳다). 그 사실을 안 알리면
                    # "되돌림 5 · 실패 0" 만 보고 사용자는 제자리로 온 줄 안다.
                    result.done.append({
                        "kind": "restore", "src": str(final), "final": str(back),
                        "intended": str(intended), "renamed": back != intended,
                    })
                elif kind == "extract":
                    # 압축을 푼 파일은 되돌릴 자리가 없다(원본은 zip 안이다).
                    # 그대로 두면 되돌린 뒤에도 폴더가 되돌리기 전보다 어수선해지므로
                    # 격리 폴더로 보낸다 — 원본 zip 은 건드리지 않는다.
                    moved = move_file(final, undo_trash / final.name)
                    result.done.append({"kind": "quarantine", "src": str(final), "final": str(moved)})
                item["undone"] = True

            except OrganizeError as e:
                # hint 를 버리지 않는다 — executor.py 와 같은 이유다.
                item["undone"] = _nothing_left_to_undo(item)
                result.failed.append(_failure(kind, item, e.message, e.hint))
            except (OSError, KeyError):
                # 손상된 기록(필요한 키가 없음)도 여기서 받는다. 파이썬 예외
                # 원문을 그대로 보여주지 않는다 — hint 자리에 예외 원문을 넣지
                # 말라는 전역 규칙과 같은 이유다.
                name = Path(item.get("final") or "").name
                item["undone"] = _nothing_left_to_undo(item)
                result.failed.append(_failure(
                    kind, item, f"되돌리지 못했습니다: {name}",
                    "대상 위치의 쓰기 권한이나 파일이 다른 프로그램에서 열려있는지 확인해 주세요."))
    finally:
        # 예상 못 한 예외로 빠져나가더라도 **어디까지 되돌렸는지는 반드시 남긴다.**
        # 안 남기면 다음 시도가 이미 되돌린 것을 또 되돌리려 들어 실패만 쌓인다.
        if all(i.get("undone") for i in items):
            data["undone_at"] = datetime.now().isoformat(timespec="seconds")
            # 격리 폴더 이름은 계획 때의 run_id 로 정해졌다. 기록 파일 이름이
            # 충돌을 피해 `-2` 로 비켜 갔을 수 있으므로 둘을 따로 들고 다닌다.
            _tidy_our_own_bookkeeping(root, data.get("trash_id") or resolved_id)
        try:
            write_json_atomic(log_path, data)
        except OSError as e:
            # 통째 덮어쓰기가 아니라 갈아끼우기이므로 여기서 실패해도 **이전
            # 기록은 그대로 남는다.** 다만 어디까지 되돌렸는지는 못 적었으므로
            # 조용히 넘어가지 않고 사실대로 알린다.
            raise OrganizeError(
                f"되돌리기는 했지만 그 사실을 기록에 남기지 못했습니다: {log_path.name}",
                hint=f"'{_runs_dir(root)}' 의 쓰기 권한과 디스크 남은 공간을 확인해 주세요. "
                     "같은 명령을 다시 실행하면 이미 되돌린 것을 또 되돌리려 할 수 있습니다.",
            ) from e
    return result


def _missing_medium(final: Path) -> Path | None:
    """되돌릴 자리의 **부모 폴더가 통째로 안 보이는가.** 보이면 None.

    "파일이 지워졌다" 와 "USB 를 뽑았다" 는 전혀 다른 일인데, 그 자리에 파일이
    없다는 사실만으로는 구분이 안 된다. 부모 폴더까지 같이 없어졌다면 그건
    사용자가 파일 하나를 지운 것이 아니라 **매체가 통째로 안 보이는 것**이다.

    안 보일 때는 '안 보이는 것 중 가장 위' 를 돌려준다. USB 를 뽑으면 마운트
    지점부터 통째로 사라지므로, 그 지점을 알려 줘야 사용자가 **무엇을 다시
    꽂아야 하는지** 안다 — 맨 안쪽 폴더 이름만 보여 주면 알 수 없다.
    """
    parent = final.parent
    try:
        if parent.exists():
            return None                  # 매체는 있다 — 파일만 없는 것이다
    except OSError:
        return None                      # 확인조차 못 했으면 매체 탓으로 돌리지 않는다
    top = parent
    for ancestor in parent.parents:
        try:
            if ancestor.exists():
                break
        except OSError:
            break
        top = ancestor
    return top


def _failure(kind: str, item: dict, why: str, hint: str | None) -> dict:
    """실패 한 줄. **매체가 통째로 안 보이는 경우만은 다른 말을 한다.**

    "옮기려는 파일이 없습니다 / 미리보기 이후에 파일이 지워졌을 수 있습니다" 는
    사용자가 파일을 지웠다는 뜻으로 읽힌다. USB 를 뽑아 뒀을 뿐인데 그렇게
    말하면 파일이 사라진 줄 안다 — 실제로는 매체 안에 멀쩡히 있다.
    """
    final = item.get("final")
    try:
        medium = _missing_medium(Path(final)) if final else None
    except (TypeError, ValueError, OSError):
        medium = None
    if medium is None:
        return {"kind": kind, "src": final, "why": why, "hint": hint}
    return {
        "kind": kind, "src": final,
        "why": f"저장 매체를 찾을 수 없습니다: {Path(final).name}",
        "hint": f"'{medium}' 이 보이지 않습니다. USB·외장하드라면 다시 꽂은 뒤 "
                "같은 명령을 한 번 더 실행하면 남은 것만 되돌립니다.",
    }


def _nothing_left_to_undo(item: dict) -> bool:
    """되돌릴 대상이 그 자리에 아예 없는가 — 그렇다면 다시 시도해도 결과가 같다.

    실패한 항목을 무조건 "아직 남았다" 로 붙들면, 고칠 수 없는 항목 하나가
    그 실행을 영원히 '되돌릴 게 남은 실행' 으로 만든다. 그러면 `organize undo`
    가 매번 그 실행만 집어 **이전 실행을 영영 못 보게 가린다.** 다시 해 봐야
    소용없는 항목은 '끝난 것' 으로 기록한다.

    **그러나 매체가 없어서 못 한 것은 '끝난 것' 이 아니다.** 예전에는 파일이
    그 자리에 있는지만 봤다. USB 를 뽑은 채 되돌리면 항목마다 도장이 찍히고,
    모두 찍히면 `undone_at` 까지 박혀 그 실행은 **영영 되돌릴 수 없게** 된다 —
    파일은 USB 안에 멀쩡히 있는데도. 실측한 결함이다. 매체가 안 보이면
    '아직 남았다' 로 두어 다시 꽂고 한 번 더 시도할 수 있게 한다.
    """
    try:
        final = Path(item["final"])
    except (KeyError, TypeError, ValueError):
        return True                      # 경로조차 알 수 없으면 더 할 수 있는 게 없다
    try:
        if final.exists():
            return False                 # 아직 그 자리에 있다 — 원인을 고치면 된다
    except OSError:
        return True
    return _missing_medium(final) is None


def _tidy_our_own_bookkeeping(root: Path, run_id: str) -> None:
    """되돌리기가 끝난 뒤 **우리가 만든 장부만** 치운다.

    격리 폴더에는 사용자 파일이 들어간다. 그건 절대 지우지 않는다("파일을
    삭제하지 않는다" 는 전역 제약은 사용자 파일 얘기다). 파일이 전부 제자리로
    돌아가 폴더에 우리가 쓴 `_manifest.json` 만 남았을 때에만, 그 장부와 빈
    폴더를 치운다. 되돌리기가 부분 실패해 아직 격리에 남은 사용자 파일이
    있으면 **아무것도 건드리지 않는다** — 그 장부가 그 파일이 무엇이고 어디서
    왔는지 적힌 유일한 기록이기 때문이다.
    """
    trash = root / ".organize" / "trash" / run_id
    try:
        if not trash.is_dir():
            return
        if any(p.name != "_manifest.json" for p in trash.iterdir()):
            return                       # 사용자 파일이 남아 있다 — 손대지 않는다
        (trash / "_manifest.json").unlink(missing_ok=True)
        trash.rmdir()
        trash.parent.rmdir()             # .organize/trash 도 비었으면 같이 치운다
    except OSError:
        pass                             # 못 치워도 되돌리기 자체는 성공이다
