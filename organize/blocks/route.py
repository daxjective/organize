"""규칙에 따라 파일을 카테고리 폴더로 보낸다.

바탕화면 정리와 vault 번호 체계가 같은 블록이다. 프로파일만 바뀐다.
"""

from organize.blocks import BlockConfig, already_there, dest_folder
from organize.core.action import Action, Plan
from organize.core.context import Context
from organize.errors import OrganizeError
from organize.profiles import matches, route_target

BLOCK = "route"


def build(ctx: Context, cfg: BlockConfig) -> Plan:
    profile = cfg.options.get("profile")
    if profile is None:
        raise OrganizeError(
            "'route' 작업에 어떤 분류 규칙을 쓸지 적지 않았습니다.",
            hint="레시피에 profile 을 적어 주세요. 예: {'block': 'route', 'profile': 'desktop'}")
    plan = Plan()
    folders: list[str] = []
    moves: list[Action] = []

    for entry in ctx.files_at(cfg.target):
        if cfg.when and not matches(entry, cfg.when, ctx.today):
            plan.skipped.append((entry.path, "이 작업의 대상이 아님"))
            continue

        category = route_target(entry, profile, ctx.today)
        if category is None:
            plan.skipped.append((entry.path, "맞는 규칙이 없음"))
            continue

        rel = f"{cfg.out}/{category}" if cfg.out else category
        if already_there(ctx, entry, rel, category, cfg):
            plan.skipped.append((entry.path, f"이미 {category} 에 있음"))
            continue

        folder = dest_folder(ctx, rel, block=BLOCK)      # root 밖이면 여기서 막힌다
        if rel not in folders:
            folders.append(rel)
        moves.append(Action(
            kind="move",
            src=ctx.current_path(entry),
            dst=folder / ctx.current_path(entry).name,
            reason=f"확장자 {entry.ext or '없음'} → {category}",
            block=BLOCK,
        ))

    for rel in folders:                       # 폴더를 먼저 만들고 옮긴다
        plan.actions.append(Action(kind="mkdir", src=None,
                                   dst=dest_folder(ctx, rel, block=BLOCK),
                                   reason="분류 결과를 담을 폴더", block=BLOCK))
    plan.actions.extend(moves)
    return plan
