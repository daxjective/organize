"""날짜별로 파일을 나눈다.

날짜는 EXIF 촬영일 → 파일명 → 수정시각 순으로 정한다.
판정할 수 없으면 옮기지 않고 그 자리에 둔다. 앞 단계가 이미 분류해 둔
결과를 미분류로 되돌리지 않기 위해서다.

자기 폴더 보호는 따로 코드가 필요 없다. `files_at(target)` 은 target 직속
파일만 돌려주므로, 이미 `2026/` 안에 있는 파일은 애초에 대상이 아니다.
"""

from organize.blocks import BlockConfig, already_there
from organize.core.action import Action, Plan
from organize.core.context import Context
from organize.core.dates import resolve_date
from organize.profiles import matches

BLOCK = "by_date"
_DEFAULT_LAYOUT = "{year}"


def build(ctx: Context, cfg: BlockConfig) -> Plan:
    layout = cfg.options.get("layout", _DEFAULT_LAYOUT)
    plan = Plan()
    folders: list[str] = []
    moves: list[Action] = []

    for entry in ctx.files_at(cfg.target):
        if cfg.when and not matches(entry, cfg.when, ctx.today):
            plan.skipped.append((entry.path, "이 작업의 대상이 아님"))
            continue

        hit = resolve_date(entry, ctx.today)
        if hit is None:
            plan.skipped.append((entry.path, "날짜를 알 수 없어 그대로 둠"))
            continue

        sub = layout.format(year=f"{hit.value.year:04d}",
                            month=f"{hit.value.month:02d}",
                            day=f"{hit.value.day:02d}")
        rel = f"{cfg.out}/{sub}" if cfg.out else sub
        if already_there(ctx, entry, rel, sub, cfg):
            plan.skipped.append((entry.path, "이미 해당 폴더에 있음"))
            continue

        if rel not in folders:
            folders.append(rel)
        moves.append(Action(
            kind="move",
            src=ctx.current_path(entry),
            dst=ctx.root / rel / ctx.current_path(entry).name,
            reason=f"{hit.source} {hit.value.isoformat()}",
            block=BLOCK,
        ))

    for rel in folders:
        plan.actions.append(Action(kind="mkdir", src=None, dst=ctx.root / rel,
                                   reason="날짜별로 담을 폴더", block=BLOCK))
    plan.actions.extend(moves)
    return plan
