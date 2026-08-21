"""블록 레지스트리.

블록 하나가 파일 하나다. 모든 블록은 같은 시그니처를 갖는다.

    build(ctx: Context, cfg: BlockConfig) -> Plan

블록은 파일을 만지지 않고 Plan 만 만든다. 블록끼리 직접 호출하지 않는다.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
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


def dest_folder(ctx: Context, rel: str, *, block: str) -> Path:
    """root 기준 상대 폴더를 실제 경로로 바꾼다. **root 밖으로 나가면 거부한다.**

    `rel` 은 전부 사용자가 손으로 쓴 값에서 온다 — 레시피의 `dest`/`target`,
    프로파일의 `to`, by_date 의 `layout`, unzip 의 `out`. 입구가 넷이므로 각
    입구마다 막지 않고 **Action 을 만드는 이 한 곳**에서 막는다. 마지막 관문이다.

    막지 않으면 `/etc` 나 `../..` 가 그대로 통해서 사용자 파일이 root 밖으로
    나간다. 미리보기 화면에도 그렇게 보이므로 눈치채기 전에 실행된다.

    심볼릭 링크는 따지지 않는다 — `normpath` 는 순수 문자열 정규화다.
    링크를 통한 탈출은 실행기가 옮기기 직전에 막는다(Task 16).
    """
    folder = Path(os.path.normpath(ctx.root / rel))
    if not folder.is_relative_to(ctx.root):
        raise OrganizeError(
            f"'{block}' 작업의 목적지가 정리 대상 폴더 밖을 가리킵니다: {rel}",
            hint=f"목적지는 {ctx.root} 안쪽이어야 합니다. "
                 "'/' 로 시작하는 절대경로나 '..' 는 쓸 수 없습니다.")
    return folder


def already_there(ctx: Context, entry, rel: str, sub: str, cfg: BlockConfig) -> bool:
    """이 파일이 이미 갈 곳에 있는가. route 와 by_date 가 같이 쓴다.

    두 갈래다.
    1) 계산한 목적지와 지금 폴더가 **정확히 같다** — 두말할 것 없이 건너뛴다.
    2) `dest` 를 안 줬다(= "있던 자리 옆에 담아라")면, 지금 폴더가 이미 `sub` 로
       끝나는 것으로 충분하다. 이게 없으면 재실행할 때마다 `01_Docs/01_Docs`,
       `2023/2023` 처럼 같은 이름이 겹겹이 쌓인다.

    `dest` 를 **명시했을 때는 2)를 쓰지 않는다.** 사용자가 목적지를 콕 집어 말한
    것이므로, 이미 같은 이름 폴더에 있더라도 그리로 옮겨야 한다.
    (`01_Docs` 안의 파일을 `보관/01_Docs` 로 보내는 경우가 여기 걸린다.)

    `sub` 가 `2026/05` 처럼 여러 층일 수 있으므로 마지막 한 조각만 보면 안 된다.
    """
    rel_of = ctx.rel_of(entry)
    if rel == rel_of:
        return True
    return cfg.dest is None and (rel_of == sub or rel_of.endswith("/" + sub))


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
    if not REGISTRY:
        # 지연 초기화: 이 함수 안에서 비로소 by_date/dedup/route/unzip 을 import
        # 한다. 블록들은 다시 `organize.blocks` 에서 BlockConfig/already_there 를
        # 가져가므로 순환이다. 최상단에서 import 해도 **지금은** 돈다 — 단 그
        # import 문이 BlockConfig 정의보다 아래에 있을 때만이다. 즉 이 파일의
        # 줄 순서에 정확성이 걸리게 된다. 여기서 늦추면 그 함정이 아예 없어진다.
        # 다시 대입(REGISTRY = ...)하지 않고 REGISTRY.update(...) 로
        # 제자리에서 채우는 이유는: `from organize.blocks import REGISTRY` 로
        # 먼저 참조를 잡아둔 코드가 있다면, 재대입은 그 참조를 영원히 빈
        # 딕셔너리로 남기기 때문이다. update 는 같은 객체를 채우므로 먼저 잡은
        # 참조도 함께 채워진다.
        REGISTRY.update(_registry())
    if name not in REGISTRY:
        raise OrganizeError(
            f"'{name}' 이라는 작업은 없습니다.",
            hint="쓸 수 있는 작업: " + ", ".join(sorted(REGISTRY)),
        )
    return REGISTRY[name]
