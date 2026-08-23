"""블록을 순서대로 엮어 하나의 Plan 으로 모은다.

블록끼리는 서로를 모른다. 앞 블록의 결과는 Context 를 통해서만 전달된다.
따라서 순서를 바꾸면 뒤 블록의 대상이 바뀌고, 때로는 0건이 된다.
그것이 정상 동작이며, 사용자에게 건수를 보여줘 알아채게 한다.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from organize.blocks import BlockConfig, get_block
from organize.core.action import Plan
from organize.core.context import Context
from organize.core.scanner import scan
from organize.errors import OrganizeError
from organize.profiles import load_profile

_RESERVED = {"block", "target", "dest", "when"}


@dataclass
class BuiltPlan:
    root: Path
    run_id: str
    plan: Plan
    per_block: list[tuple[str, int]] = field(default_factory=list)
    snapshot: dict[str, tuple[int, float]] = field(default_factory=dict)


def make_run_id(now: datetime) -> str:
    return now.strftime("%Y%m%d-%H%M%S")


def _to_config(step: dict, profiles_dir: Path) -> BlockConfig:
    options = {k: v for k, v in step.items() if k not in _RESERVED}
    if "profile" in options:
        options["profile"] = load_profile(profiles_dir / f"{options['profile']}.toml")
    return BlockConfig(
        target=step.get("target", ""),
        dest=step.get("dest"),
        when=step.get("when", {}) or {},
        options=options,
    )


def build_plan(root: Path, steps: list[dict], *, today: date, run_id: str,
               profiles_dir: Path, now: float | None = None) -> BuiltPlan:
    # 하위 폴더까지 읽는다. dedup 이 참고해야 하기 때문이다.
    # files_at("") 은 직속만 돌려주므로 하위 폴더 파일이 함부로 옮겨지지는 않는다.
    scanned = scan(root, recursive=True, now=now)
    ctx = Context(root=root, entries=scanned.entries, today=today, run_id=run_id)

    built = BuiltPlan(root=root, run_id=run_id, plan=Plan())
    built.plan.skipped.extend(scanned.skipped)
    built.snapshot = {str(e.path): (e.size, e.mtime) for e in scanned.entries}

    for i, step in enumerate(steps, start=1):
        # step["block"] 을 바로 읽으면 이 키가 아예 없을 때 파이썬 KeyError 가
        # 그대로 사용자에게 노출된다 — 레시피는 사람이 손으로 쓰므로 실제로
        # 빠뜨릴 수 있는 실수다. 전역 규칙(예외를 그대로 보여주지 않는다)에 따라
        # 여기서 먼저 한국어 오류로 바꾼다.
        if "block" not in step:
            raise OrganizeError(
                f"{i}번째 작업에 'block' 이 없습니다.",
                hint="각 단계는 {'block': '작업이름', ...} 형태로 적어야 합니다. "
                     "쓸 수 있는 작업: unzip, dedup, route, by_date",
            )
        block_name = step["block"]
        fn = get_block(block_name)
        sub = fn(ctx, _to_config(step, profiles_dir))
        ctx.apply(sub)
        built.plan.extend(sub)
        built.per_block.append((block_name, len(sub.actions)))

    return built
