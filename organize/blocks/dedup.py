"""내용이 같은 파일을 격리 폴더로 치운다.

읽는 범위와 치우는 범위가 다르다.

  읽기   대상 폴더 + 하위 폴더 전부   해시만 계산한다
  치우기 대상 폴더 직속 파일만        하위 폴더는 절대 건드리지 않는다

이름으로 판정하지 않는다. 실제 폴더에서는 이름이 전혀 다른 파일들이 중복이었고,
`(2)`, `(3)` 이 붙은 파일들은 오히려 서로 다른 이미지였다 — 판정은 전부
`organize.core.hashing` 이 한다.

`find_duplicate_groups` 가 고르는 "남길 파일"은 경로 깊이가 얕은 쪽을 우선한다
(상위 폴더에 있는 쪽). 그런데 이 블록은 하위 폴더 파일을 절대 옮길 수 없으므로,
얕은 쪽이 직속 파일이고 깊은 쪽이 하위 폴더 파일이면 얕은 쪽(직속 파일)이
"남길 파일"로 뽑히는데 정작 치울 수 있는 건 하위 폴더 쪽뿐인 모순이 생긴다.
그래서 이 블록만의 규칙을 따로 둔다 — 한 무리 안에 하위 폴더 파일이 하나라도
있으면 그 파일은 이미 사용자가 정리해 둔 것으로 보고 무조건 남기고, 직속
파일은 전부 치운다. 하위 폴더 파일이 하나도 없을 때(무리 전체가 직속 파일)만
`find_duplicate_groups` 가 고른 순위를 그대로 쓴다.
"""

from organize.blocks import BlockConfig
from organize.core.action import Action, Plan
from organize.core.context import Context
from organize.core.hashing import find_duplicate_groups, pick_original
from organize.profiles import matches

BLOCK = "dedup"


def _within_target(rel: str, target: str) -> bool:
    """rel 이 target 폴더 자신이거나 그 하위 폴더인가."""
    return target == "" or rel == target or rel.startswith(target + "/")


def build(ctx: Context, cfg: BlockConfig) -> Plan:
    plan = Plan()

    # 읽기: 대상 폴더 + 하위 폴더 전부. 형제 폴더(대상 밖)는 읽지 않는다 —
    # 안 그러면 target 과 무관한 폴더의 내용까지 중복 판정에 끼어든다.
    readable = []
    for entry in ctx.all_files():
        if not _within_target(ctx.rel_of(entry), cfg.target):
            continue
        if entry.virtual:
            plan.skipped.append((entry.path, "압축을 푼 뒤에 판정합니다"))
            continue
        readable.append(entry)

    # 치우기: 대상 폴더 직속 파일만. entry.path(원래 경로) 로 판정한다 —
    # ctx.files_at() 은 이미 격리된 파일을 걸러 준 현재 위치 기준 목록이다.
    removable = {e.path for e in ctx.files_at(cfg.target)}

    for group in find_duplicate_groups(readable):
        candidates = [e for e in group if e.path in removable]
        if not candidates:
            continue                                   # 하위 폴더 파일뿐 — 건드릴 게 없음

        protected = [e for e in group if e.path not in removable]
        # 하위 폴더 파일이 하나라도 있으면 그쪽을 무조건 남긴다(위 docstring 참고).
        # 없으면(전부 직속 파일) find_duplicate_groups 가 고른 group[0] 을 남긴다.
        keeper = pick_original(protected) if protected else group[0]

        for other in candidates:
            if other.path == keeper.path:
                continue                               # 남길 파일 자신
            if cfg.when and not matches(other, cfg.when, ctx.today):
                plan.skipped.append((other.path, "이 작업의 대상이 아님"))
                continue
            plan.actions.append(Action(
                kind="quarantine",
                src=ctx.current_path(other),
                dst=ctx.trash_dir / ctx.current_path(other).name,
                reason=f"내용이 같음 · 남긴 파일 {ctx.current_path(keeper).name}",
                block=BLOCK,
            ))
    return plan
