"""미리보기와 실행이 공유하는 자료구조.

블록은 파일을 만지지 않고 Action 목록만 만든다.
실행기는 그 목록을 그대로 수행한다. 따라서 미리보기에서 본 것과
실제로 일어나는 일이 반드시 같다.
"""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

ActionKind = Literal["mkdir", "move", "quarantine", "extract"]


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    src: Path | None       # mkdir 은 None
    dst: Path | None       # quarantine 은 격리 폴더 안의 경로
    reason: str            # 사람이 읽는 근거. UI 에 그대로 표시된다
    block: str             # 이 Action 을 만든 블록 이름
    member: str | None = None   # extract 전용 — 압축 안에서 꺼낼 항목 이름
    # extract 전용 — 압축 안에 적힌 크기와 시각. Context 가 이 값으로 가상
    # 엔트리를 만든다. 없으면 mtime 0 이 되어 by_date 가 전부 1970 폴더로
    # 보낸다 — 실제로 그렇게 됐다.
    size: int = 0
    mtime: float = 0.0


@dataclass
class Plan:
    actions: list[Action] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return dict(Counter(a.kind for a in self.actions))

    def extend(self, other: "Plan") -> None:
        self.actions.extend(other.actions)
        self.skipped.extend(other.skipped)
