"""Plan 을 실제로 수행하고 되돌릴 수 있는 기록을 남긴다.

네 가지를 지킨다.

1. 실행 직전 재검증 — 계획 시점의 크기·수정시각과 다르면 그 항목만 건너뛴다.
   미리보기와 실행 사이에 사람이 파일을 건드렸을 수 있다.
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
                a.dst.mkdir(parents=True, exist_ok=True)
                result.done.append({"kind": "mkdir", "final": str(a.dst)})
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
        trash = built.root / ".organize" / "trash" / built.run_id
        trash.mkdir(parents=True, exist_ok=True)
        (trash / "_manifest.json").write_text(
            json.dumps(quarantined, ensure_ascii=False, indent=2), encoding="utf-8")

    return result


def prepare_runlog(built: BuiltPlan) -> Path:
    """execute() 를 부르기 전에 실행 기록 자리를 미리 마련해 둔다.

    Task 18 리뷰 Critical #1: write_runlog 가 실행 *뒤에* 실패하면 파일은
    이미 옮겨졌는데 기록이 없어 되돌릴 수 없다. 핵심은 "아무것도 건드리기
    전에 실패하게 만드는 것" — 여기서 죽으면 execute() 가 아직 불리지
    않았으므로 파일이 하나도 안 움직인 상태다.

    뼈대는 유효한 JSON 이어야 한다 — 실행 중 강제 종료돼도 list_runs 가
    깨지지 않는다. done 이 비어 있으므로 latest_run_id 는 이 기록을 집지
    않는다(그 함수는 count 가 참일 때만 집는다).
    """
    runs = built.root / ".organize" / "runs"
    path = runs / f"{built.run_id}.json"
    try:
        runs.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "run_id": built.run_id,
            "root": str(built.root),
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "done": [], "failed": [], "stale": [],
            "complete": False,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        # 파이썬 예외 원문을 그대로 보여주지 않는다(전역 규칙) — 무엇을
        # 확인하면 되는지만 한국어로 알린다.
        raise OrganizeError(
            f"실행 기록을 준비하지 못해 아무 파일도 옮기지 않았습니다: {built.root}",
            hint=f"'{runs}' 자리를 확인해 주세요 — 디스크 용량, 쓰기 권한, "
                 "또는 같은 이름의 파일이 이미 있는지 살펴보세요.",
        ) from e
    return path


def write_runlog(built: BuiltPlan, result: ExecResult) -> Path:
    runs = built.root / ".organize" / "runs"
    # mkdir(parents=True, exist_ok=True) 는 그대로 남겨 둔다 — prepare_runlog
    # 없이 write_runlog 만 부르는 기존 호출자(test_executor.py, test_undo.py 의
    # run_plan 헬퍼)가 계속 통과해야 한다.
    path = runs / f"{built.run_id}.json"
    try:
        runs.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "run_id": built.run_id,
            "root": str(built.root),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "done": result.done,
            "failed": result.failed,
            "stale": result.stale,
            "complete": True,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
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
