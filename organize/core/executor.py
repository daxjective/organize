"""Plan 을 실제로 수행하고 되돌릴 수 있는 기록을 남긴다.

네 가지를 지킨다.

1. 실행 직전 재검증 — 계획 시점의 크기·수정시각과 다르면 그 항목만 건너뛴다.
   미리보기와 실행 사이에 사람이 파일을 건드렸을 수 있다.
   **다만 대상은 스캐너가 처음 본 경로뿐이다**(`built.snapshot` 에 그것만 있다).
   한 파일이 두 번 옮겨지는 사슬에서 두 번째 이동은 재검증하지 않는다 —
   그 자리는 우리가 방금 만든 자리여서 비교할 "계획 시점의 값" 이 없다.
2. 부분 실패 — 하나가 실패해도 멈추지 않는다. 이미 한 일은 로그에 남아 되돌릴 수 있다.
3. 이름 바뀜 추적 — 한 파일이 여러 번 옮겨질 때, 앞 이동에서 _(1) 이 붙으면
   뒤 이동의 원본 경로가 어긋난다. 대응표(remap)로 이어 붙인다.
4. root 탈출 방지 — 블록의 dest_folder() 는 문자열만 정규화하므로 목적지
   폴더 자체가 root 밖을 가리키는 심볼릭 링크면 통과해 버린다. 실제로
   파일을 쓰기 직전에 실제 경로(symlink 를 다 푼 경로)가 root 안인지
   다시 확인한다.
"""

import json
import os
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from organize.core.paths import claim_path, move_file
from organize.core.runner import BuiltPlan
from organize.errors import OrganizeError


@dataclass
class ExecResult:
    done: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    stale: list[dict] = field(default_factory=list)


def _changed(path: Path, expected: tuple[int, float]) -> bool:
    try:
        st = path.stat()
    except OSError:
        return True
    size, mtime = expected
    return st.st_size != size or abs(st.st_mtime - mtime) > 1.0


def _guard_within_root(dst: Path, real_root: str, *, block: str) -> None:
    """`dst` 가 실제로도(심볼릭 링크를 다 푼 뒤에도) root 안인지 확인한다.

    `os.path.realpath` 는 존재하는 구간까지는 심볼릭 링크를 따라가고, 아직
    없는 나머지 구간은 그대로 이어붙인다. 그래서 아직 만들어지지 않은
    목적지 폴더/파일도 정확히 판정할 수 있다.

    `dest_folder()` 가 이미 문자열 기준으로는 막아 뒀지만, 그 사이의 폴더
    하나가 root 밖을 가리키는 심볼릭 링크면 문자열 검사만으로는 못 잡는다.
    실제로 쓰기 직전인 여기서 다시 막는다.
    """
    real_dst = os.path.realpath(dst)
    if real_dst != real_root and not real_dst.startswith(real_root + os.sep):
        raise OrganizeError(
            f"'{block}' 작업의 목적지가 실제로는 정리 대상 폴더 밖을 가리킵니다: {dst}",
            hint="목적지 경로 중간에 정리 대상 폴더 밖을 가리키는 심볼릭 링크가 있는지 확인해 주세요.",
        )


def _mkdir_recording(dst: Path) -> list[Path]:
    """폴더를 만들고 **이번에 새로 만든 것만** 바깥쪽부터 차례로 돌려준다.

    `mkdir(parents=True)` 는 중간 폴더까지 만드는데, Action 은 **잎 폴더
    하나만** 담는다. 그래서 `보관/2023` 을 만들면 실행 기록에 `보관/2023` 만
    남고 `보관` 은 아무 데도 안 적혔다. 되돌려도 그 중간 폴더가 빈 채로
    남는데 도구는 "실패 0" 이라고 말한다 — 조합 1092개 중 748개(68%)에서
    실측된 잔해다.

    **이미 있던 폴더는 담지 않는다.** 사용자가 미리 만들어 둔 폴더를
    되돌리기가 지워 버리면 그건 우리가 한 일을 되돌리는 게 아니다.

    바깥쪽부터 담는 이유: 되돌리기는 실행 기록을 **역순으로** 재생하므로,
    이 순서로 담아야 안쪽 폴더부터 지운다.
    """
    created: list[Path] = []
    probe = dst
    while not probe.exists():
        created.append(probe)
        if probe.parent == probe:
            break
        probe = probe.parent
    dst.mkdir(parents=True, exist_ok=True)
    return list(reversed(created))


def execute(built: BuiltPlan) -> ExecResult:
    result = ExecResult()
    remap: dict[Path, Path] = {}          # 계획된 경로 -> 실제로 놓인 경로
    quarantined: list[dict] = []
    real_root = os.path.realpath(built.root)

    for a in built.plan.actions:
        src_label = str(a.src) if a.src is not None else ""
        try:
            if a.kind == "mkdir":
                _guard_within_root(a.dst, real_root, block=a.block)
                for folder in _mkdir_recording(a.dst):
                    result.done.append({"kind": "mkdir", "final": str(folder)})
                continue

            src = remap.get(a.src, a.src)
            src_label = str(src)

            expected = built.snapshot.get(str(src))
            if expected is not None and _changed(src, expected):
                result.stale.append({
                    "kind": a.kind, "src": str(src),
                    "why": "미리보기 이후에 파일이 바뀌었습니다",
                })
                continue

            if a.kind in ("move", "quarantine"):
                _guard_within_root(a.dst, real_root, block=a.block)
                final = move_file(src, a.dst)
                if final != a.dst:
                    remap[a.dst] = final
                entry = {"kind": a.kind, "src": str(src), "final": str(final),
                         "reason": a.reason, "block": a.block}
                result.done.append(entry)
                if a.kind == "quarantine":
                    quarantined.append({"from": str(src), "to": str(final)})

            elif a.kind == "extract":
                _guard_within_root(a.dst, real_root, block=a.block)
                a.dst.parent.mkdir(parents=True, exist_ok=True)
                final = claim_path(a.dst)      # 이름을 먼저 잡는다(덮어쓰기 방지)
                try:
                    with zipfile.ZipFile(src) as z, z.open(a.member) as member, \
                            final.open("wb") as out:
                        out.write(member.read())
                except BaseException:
                    # 압축이 미리보기 이후 깨졌거나(BadZipFile), 항목이 없어졌거나
                    # (KeyError), 쓰다가 오류가 났거나(OSError) — 무엇이든 잡아 둔
                    # 빈 자리를 그대로 두면 정리 대상 폴더에 정체불명 파일이
                    # 남는다. move_file 이 실패 시 자리를 치우는 것과 같은 이유다.
                    final.unlink(missing_ok=True)
                    raise
                if final != a.dst:
                    remap[a.dst] = final
                result.done.append({"kind": "extract", "src": str(src),
                                    "final": str(final), "member": a.member,
                                    "reason": a.reason, "block": a.block})

        except OrganizeError as e:
            # hint 를 버리지 않는다 — errors.py 가 메시지와 힌트를 같이 들고
            # 다니게 설계한 이유(사람이 다음에 뭘 하면 되는지)를 실행 결과에서도
            # 지켜야 한다(Task 16 리뷰 Minor #1).
            result.failed.append({
                "kind": a.kind, "src": src_label, "why": e.message, "hint": e.hint,
            })
        except (OSError, zipfile.BadZipFile, KeyError):
            # 파이썬 예외 원문을 그대로 보여주지 않는다 — 이 프로젝트에서
            # 실제로 있었던 결함이다(hint 자리에 예외 원문을 넣으면 안 된다는
            # 전역 규칙). 어떤 파일이 실패했는지만 사람이 읽을 말로 알린다.
            result.failed.append({
                "kind": a.kind, "src": src_label,
                "why": f"파일을 처리하지 못했습니다: {(a.dst or a.src).name if (a.dst or a.src) else ''}",
            })

    if quarantined:
        # 이 장부는 "무엇이 왜 격리됐는지" 를 사람이 보라고 남기는 참고 자료다.
        # 되돌리기는 이걸 **읽지 않는다** — 실행 로그만 본다. 그러니 이걸 못
        # 썼다고 실행을 통째로 실패시키면 안 된다. 예전에는 여기서 난 예외가
        # execute() 밖으로 새어 나가 실행 로그 자체가 안 써졌고, 파일은 격리
        # 폴더에 있는데 organize undo 는 "되돌릴 기록이 없습니다" 라고 답했다.
        # 실측했다 — Critical #1 이 닫으려던 것과 정확히 같은 등급의 실패다.
        trash = built.root / ".organize" / "trash" / built.run_id
        try:
            trash.mkdir(parents=True, exist_ok=True)
            # **덮어쓰지 않고 이어 붙인다.** 격리 폴더 이름은 계획 때의 run_id
            # 라서, 같은 초의 두 실행은 이 폴더를 공유한다(기록 파일만 `-2` 로
            # 비켜 간다). 통째로 쓰면 파일 3개가 격리돼 있는데 장부는 1개만
            # 설명하게 된다 — 실측했다.
            manifest = trash / "_manifest.json"
            before: list = []
            try:
                loaded = json.loads(manifest.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    before = loaded
            except (OSError, ValueError):
                before = []          # 없거나 못 읽으면 이번 것만이라도 남긴다
            write_json_atomic(manifest, before + quarantined)
        except OSError:
            # 삼키지는 않는다 — 무엇이 안 됐는지 화면과 실행 기록에 남긴다.
            result.failed.append({
                "kind": "manifest", "src": str(trash),
                "why": "격리 목록을 남기지 못했습니다 — 치운 파일은 그대로 있습니다",
                "hint": f"'{trash}' 의 쓰기 권한과 디스크 남은 공간을 확인해 주세요. "
                        "되돌리기는 실행 기록으로 하므로 영향받지 않습니다.",
            })

    return result


def _claim_runlog_path(runs: Path, run_id: str) -> Path:
    """`<run_id>.json` 자리를 원자적으로 잡는다. 이미 있으면 `-2`, `-3` … 으로 비켜 간다.

    `run_id` 는 초 단위(`%Y%m%d-%H%M%S`)라 겹칠 수 있다 — 같은 폴더가 레시피의
    `roots` 에 두 번 들어가거나(별칭 두 개가 같은 곳을 가리키는 흔한 상황),
    1초 안에 두 번 실행하면 그렇다. 예전에는 그 자리를 **확인 없이 덮어써서**
    앞 실행이 무엇을 옮겼는지가 통째로 사라졌다. 파일은 옮겨졌는데 되돌릴 수
    없는, 이 프로젝트가 정의한 최악의 실패다.

    `paths.claim_path` 가 파일 이름을 잡는 것과 같은 이유이고 같은 방식이다 —
    `O_CREAT | O_EXCL` 은 "없을 때만 만든다" 를 운영체제가 원자적으로 보장하므로
    경쟁 상태가 없다.
    """
    n = 1
    while True:
        candidate = runs / (f"{run_id}.json" if n == 1 else f"{run_id}-{n}.json")
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            n += 1
            continue
        os.close(fd)
        return candidate


def write_json_atomic(path: Path, data) -> None:
    """임시 파일에 쓰고 `os.replace` 로 갈아끼운다. **반쯤 쓰인 기록이 안 생긴다.**

    예전에는 `path.write_text(...)` 로 통째 덮어썼다. 그건 먼저 파일을 비우고
    쓰기 때문에, 쓰는 도중 끊기면(강제 종료·전원) 기록이 깨진 JSON 으로 남는다.
    그러면 `list_runs` 도 `doctor` 도 그 기록을 못 읽어 **없는 것처럼** 다뤘고,
    파일은 옮겨져 있는데 "되돌릴 실행 기록이 없습니다" 가 나왔다. 실측했다.

    `os.replace` 는 원자적이다 — `paths.py` 의 `_move_onto` 가 같은 이유로 쓴다.
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)      # 조각을 남기지 않는다
        except OSError:
            pass                             # 정리에 실패해도 원래 오류를 덮지 않는다
        raise


def prepare_runlog(built: BuiltPlan) -> Path:
    """execute() 를 부르기 전에 실행 기록 자리를 미리 마련해 둔다.

    Task 18 리뷰 Critical #1: write_runlog 가 실행 *뒤에* 실패하면 파일은
    이미 옮겨졌는데 기록이 없어 되돌릴 수 없다. 핵심은 "아무것도 건드리기
    전에 실패하게 만드는 것" — 여기서 죽으면 execute() 가 아직 불리지
    않았으므로 파일이 하나도 안 움직인 상태다.

    뼈대는 유효한 JSON 이어야 한다 — 실행 중 강제 종료돼도 list_runs 가
    깨지지 않는다. done 이 비어 있으므로 latest_run_id 는 이 기록을 집지
    않는다(그 함수는 count 가 참일 때만 집는다).

    **남의 기록을 덮어쓰지 않는다.** 잡은 실제 경로를 `built.runlog_path` 에
    실어 두고, `write_runlog` 이 반드시 그 경로에 쓴다 — 여기서 어긋나면
    준비는 비켜 간 자리에 해 놓고 결과는 원래 이름에 덮어쓰는 꼴이 되어
    고치려던 결함이 그대로 남는다.
    """
    runs = built.root / ".organize" / "runs"
    path: Path | None = None
    try:
        runs.mkdir(parents=True, exist_ok=True)
        path = _claim_runlog_path(runs, built.run_id)
        write_json_atomic(path, {
            # 기록 안의 실행ID 는 **파일 이름과 반드시 같아야 한다** — undo 는
            # list_runs 가 준 run_id 로 `<run_id>.json` 을 찾기 때문이다.
            "run_id": path.stem,
            "trash_id": built.run_id,        # 격리 폴더 이름은 계획 때 이미 정해졌다
            "root": str(built.root),
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "done": [], "failed": [], "stale": [],
            "complete": False,
        })
    except OSError as e:
        # 잡아 둔 빈 자리를 치운다. **이 시점엔 execute() 가 아직 안 불렸으므로
        # 아무것도 안 옮겼다는 것이 확실하다.** 안 치우면 0바이트 기록이 남아,
        # 같은 도구가 여기서는 "아무 파일도 옮기지 않았습니다" 라고 하고
        # undo·doctor 에서는 "무엇을 옮겼는지 알 수 없으니 직접 확인해 주세요"
        # 라고 말한다. 지울 방법도 없어 doctor 에 영원히 남는다.
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass                 # 정리에 실패해도 원래 오류를 덮지 않는다
        # 파이썬 예외 원문을 그대로 보여주지 않는다(전역 규칙) — 무엇을
        # 확인하면 되는지만 한국어로 알린다.
        raise OrganizeError(
            f"실행 기록을 준비하지 못해 아무 파일도 옮기지 않았습니다: {built.root}",
            hint=f"'{runs}' 자리를 확인해 주세요 — 디스크 용량, 쓰기 권한, "
                 "또는 같은 이름의 파일이 이미 있는지 살펴보세요.",
        ) from e
    built.runlog_path = path
    return path


def write_runlog(built: BuiltPlan, result: ExecResult) -> Path:
    runs = built.root / ".organize" / "runs"
    # mkdir(parents=True, exist_ok=True) 는 그대로 남겨 둔다 — prepare_runlog
    # 없이 write_runlog 만 부르는 기존 호출자(test_executor.py, test_undo.py 의
    # run_plan 헬퍼)가 계속 통과해야 한다.
    path = built.runlog_path or (runs / f"{built.run_id}.json")
    try:
        runs.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, {
            "run_id": path.stem,             # 파일 이름과 어긋나면 undo 가 못 찾는다
            "trash_id": built.run_id,
            "root": str(built.root),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "done": result.done,
            "failed": result.failed,
            "stale": result.stale,
            "complete": True,
        })
    except OSError as e:
        # 이 시점엔 이미 execute() 가 끝나 파일이 옮겨져 있다. 그래서 여기서는
        # "실패했다"만 알리고 끝내지 않는다 — 호출부(CLI)가 이 오류를 받아
        # result(무엇을 어디로 옮겼는지)를 화면에 통째로 찍어야
        # 사람이 손으로 되돌릴 근거가 남는다.
        raise OrganizeError(
            f"파일은 옮겼지만 실행 기록을 남기지 못했습니다: {built.root}",
            hint=f"'{runs}' 자리를 확인해 주세요 — 디스크 용량, 쓰기 권한, "
                 "또는 같은 이름의 파일이 이미 있는지 살펴보세요.",
        ) from e
    return path
