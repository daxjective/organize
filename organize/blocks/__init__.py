"""블록 레지스트리.

블록 하나가 파일 하나다. 모든 블록은 같은 시그니처를 갖는다.

    build(ctx: Context, cfg: BlockConfig) -> Plan

블록은 파일을 만지지 않고 Plan 만 만든다. 블록끼리 직접 호출하지 않는다.
"""

from dataclasses import dataclass, field
from typing import Callable

from organize.core.action import Plan
from organize.core.context import Context
from organize.errors import OrganizeError


@dataclass(frozen=True)
class BlockConfig:
    target: str = ""                       # root 기준 상대 — 어디서 찾을지
    dest: str | None = None                # root 기준 상대 — 어디로 보낼지
    when: dict = field(default_factory=dict)
    options: dict = field(default_factory=dict)

    @property
    def out(self) -> str:
        return self.target if self.dest is None else self.dest


BlockFn = Callable[[Context, BlockConfig], Plan]


def _registry() -> dict[str, BlockFn]:
    from organize.blocks import by_date, dedup, route, unzip
    return {
        "unzip": unzip.build,
        "dedup": dedup.build,
        "route": route.build,
        "by_date": by_date.build,
    }


REGISTRY: dict[str, BlockFn] = {}


def get_block(name: str) -> BlockFn:
    global REGISTRY
    if not REGISTRY:
        REGISTRY = _registry()
    if name not in REGISTRY:
        raise OrganizeError(
            f"'{name}' 이라는 작업은 없습니다.",
            hint="쓸 수 있는 작업: " + ", ".join(sorted(REGISTRY)),
        )
    return REGISTRY[name]
