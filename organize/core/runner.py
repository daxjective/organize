"""블록을 순서대로 엮어 하나의 Plan 으로 모은다.

블록끼리는 서로를 모른다. 앞 블록의 결과는 Context 를 통해서만 전달된다.
따라서 순서를 바꾸면 뒤 블록의 대상이 바뀌고, 때로는 0건이 된다.
그것이 정상 동작이며, 사용자에게 건수를 보여줘 알아채게 한다.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from organize.blocks import BLOCK_OPTIONS, BlockConfig, get_block
from organize.core.action import Plan
from organize.core.context import Context
from organize.core.scanner import scan
from organize.errors import OrganizeError
from organize.profiles import CONDITION_KEYS, load_profile

_RESERVED = {"block", "target", "dest", "when"}


@dataclass
class BuiltPlan:
    root: Path
    run_id: str
    plan: Plan
    # (블록 이름, 그 블록이 만든 Action 수). **파일 개수가 아니다** — mkdir 도
    # 하나로 센다. 화면에 "route 2건" 을 그냥 내보내면 "파일 2개 옮김" 으로
    # 읽힌다(실제로는 폴더 1 + 파일 1 인 경우가 있다). 보여줄 때는 kind 별로
    # 나눠 세야 한다.
    per_block: list[tuple[str, int]] = field(default_factory=list)
    snapshot: dict[str, tuple[int, float]] = field(default_factory=dict)


def make_run_id(now: datetime) -> str:
    return now.strftime("%Y%m%d-%H%M%S")


def _check_keys(step: dict, block_name: str, order: int) -> None:
    """레시피에 적힌 이름 중 모르는 것이 있으면 거부한다.

    **조용히 무시하면 안 된다.** `when` 을 `whne` 로 잘못 쓰면 그 값이 무해한
    옵션으로 흡수되고 필터는 사라진다. 실측했다 — "pdf 만 정리해줘" 라고 쓴
    레시피가 사진까지 전부 옮겼다. 오류도 안 난다.
    """
    allowed = _RESERVED | set(BLOCK_OPTIONS.get(block_name, ()))
    unknown = sorted(set(step) - allowed)
    if unknown:
        raise OrganizeError(
            f"{order}번째 작업('{block_name}')에 모르는 항목이 있습니다: "
            + ", ".join(unknown),
            hint=f"'{block_name}' 에 쓸 수 있는 항목: " + ", ".join(sorted(allowed)),
        )

    bad = sorted(set(step.get("when") or {}) - CONDITION_KEYS)
    if bad:
        raise OrganizeError(
            f"{order}번째 작업의 'when' 에 모르는 조건이 있습니다: " + ", ".join(bad),
            hint="쓸 수 있는 조건: " + ", ".join(sorted(CONDITION_KEYS)),
        )


def _to_config(step: dict, profiles_dir: Path, block_name: str,
               order: int) -> BlockConfig:
    _check_keys(step, block_name, order)
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
        sub = fn(ctx, _to_config(step, profiles_dir, block_name, i))
        ctx.apply(sub)
        built.plan.extend(sub)
        built.per_block.append((block_name, len(sub.actions)))

    return built
