"""날짜별로 파일을 나눈다.

날짜는 EXIF 촬영일 → 파일명 → 수정시각 순으로 정한다.
판정할 수 없으면 옮기지 않고 그 자리에 둔다. 앞 단계가 이미 분류해 둔
결과를 미분류로 되돌리지 않기 위해서다.

재실행해도 `2026/2026` 처럼 중첩되지 않아야 한다. `files_at(target)` 이 직속
파일만 돌려주므로 target 이 루트일 때는 저절로 되지만, `target="2026"` 처럼
그 폴더 자체를 지정하면 대상이 **된다**. 그래서 `already_there()` 가 필요하다 —
장식이 아니다.
"""

from organize.blocks import BlockConfig, already_there, dest_folder
from organize.core.action import Action, Plan
from organize.core.context import Context
from organize.core.dates import resolve_date
from organize.errors import OrganizeError
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

        try:
            sub = layout.format(
                year=f"{hit.value.year:04d}",
                month=f"{hit.value.month:02d}",
                day=f"{hit.value.day:02d}",
            )
        except (KeyError, IndexError, ValueError) as e:
            # layout 은 사용자가 손으로 쓴다. '{years}' 오타 하나에
            # KeyError: 'years' 를 그대로 보여주면 안 된다.
            raise OrganizeError(
                f"날짜 폴더 모양('{layout}')을 이해하지 못했습니다.",
                hint="{year}, {month}, {day} 만 쓸 수 있습니다. "
                     "예: '{year}' 또는 '{year}/{month}'") from e
        rel = f"{cfg.out}/{sub}" if cfg.out else sub
        if already_there(ctx, entry, rel, sub, cfg):
            plan.skipped.append((entry.path, "이미 해당 폴더에 있음"))
            continue

        folder = dest_folder(ctx, rel, block=BLOCK)      # root 밖이면 여기서 막힌다
        if rel not in folders:
            folders.append(rel)
        # 같은 이름이 겹치면 여기서 갈라놓는다. 안 그러면 두 동작이 같은 곳을
        # 가리켜 미리보기가 거짓말을 하고 실행기가 둘을 구분하지 못한다.
        name = ctx.claim_name(rel, ctx.current_path(entry).name)
        moves.append(Action(
            kind="move",
            src=ctx.current_path(entry),
            dst=folder / name,
            reason=f"{hit.source} {hit.value.isoformat()}",
            block=BLOCK,
        ))

    for rel in folders:
        plan.actions.append(Action(kind="mkdir", src=None,
                                   dst=dest_folder(ctx, rel, block=BLOCK),
                                   reason="날짜별로 담을 폴더", block=BLOCK))
    plan.actions.extend(moves)
    return plan
