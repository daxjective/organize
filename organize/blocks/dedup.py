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
그래서 이 블록만의 규칙을 따로 둔다 — 한 무리를 "치울 수 있는 후보"(candidates)와
"건드릴 수 없어 참고만 하는 쪽"(protected)으로 가른다. 하위 폴더 파일도,
`when` 에 안 맞는 직속 파일도 둘 다 이 스텝이 옮길 수 없다는 점에서 같은 처지다
("읽는 범위 ≠ 치우는 범위"). protected 가 하나라도 있으면 그게 이미 존재하는
원본이라 보고 무조건 남기고, candidates 는 전부 치운다. protected 가 하나도
없을 때(무리 전체가 치울 수 있는 후보)만 `find_duplicate_groups` 가 고른 순위를
그대로 쓴다.
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
        # 무리를 둘로 가른다.
        #   candidates 이 step 이 실제로 치울 수 있는 파일 (직속 + when 통과)
        #   protected  옮길 수 없는 파일 — 하위 폴더 파일, when 에 안 맞는 파일.
        #              둘 다 "참고용" 이다. 중복 판정에는 참여하되 치우지는 않는다.
        candidates, protected = [], []
        for e in group:
            if e.path not in removable:
                protected.append(e)            # 하위 폴더 — 폴더는 건드리지 않는다
            elif cfg.when and not matches(e, cfg.when, ctx.today):
                plan.skipped.append((e.path, "이 작업의 대상이 아님"))
                protected.append(e)            # 이 step 의 대상이 아니다
            else:
                candidates.append(e)
        if not candidates:
            continue                           # 치울 수 있는 게 없다

        # 남길 파일 고르기. protected 가 하나라도 있으면 그게 이미 존재하는
        # 원본이므로 무조건 남기고 candidates 는 전부 치운다(위 docstring 참고).
        # protected 가 없으면(전부 candidates) find_duplicate_groups 가 고른
        # candidates[0](순위 1위)을 그대로 쓴다.
        keeper = pick_original(protected) if protected else candidates[0]

        for other in candidates:
            if other.path == keeper.path:
                continue                       # 남길 파일 자신
            plan.actions.append(Action(
                kind="quarantine",
                src=ctx.current_path(other),
                dst=ctx.trash_dir / ctx.current_path(other).name,
                reason=f"내용이 같음 · 남긴 파일 {ctx.current_path(keeper).name}",
                block=BLOCK,
            ))
    return plan
