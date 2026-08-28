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

# 종류를 **사람이 부르는 이름**. 여기 하나뿐이다.
#
# 예전에는 `cli.py` 와 `gui_model.py` 가 같은 표를 따로 들고 있었다. 그러면
# 말을 바꿀 때 한쪽만 바뀌어 **창과 명령줄이 다른 말을 한다** — 같은 파일을
# 두고 창은 "보류", 명령줄은 "격리" 라고 하면 그게 같은 것인지 알 수 없다.
#
# `quarantine` 을 "보류" 라 부른다. 지우는 것이 아니라 `.organize/trash/` 로
# **옮겨 두는 것**이고, [되돌리기] 로 되살릴 수 있기 때문이다. 아무 일도 하지
# 않은 파일은 이것이 아니라 "손대지 않음" 으로 따로 센다.
KIND_LABEL: dict[str, str] = {"mkdir": "폴더 생성", "move": "이동",
                              "quarantine": "보류", "extract": "압축 해제"}


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
    # quarantine 전용 — **남기기로 정한 파일**의 현재 절대경로. 화면이 무리를
    # 묶고 「어느 자리를 남길까」를 보여주는 근거다.
    #
    # `reason` 글자("내용이 같음 · 남긴 파일 a.pdf")를 파싱하지 않는다 — 문구가
    # 바뀌는 날 조용히 깨지고, 이름만으로는 어느 폴더인지도 알 수 없다.
    keeper: Path | None = None


@dataclass
class Plan:
    actions: list[Action] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return dict(Counter(a.kind for a in self.actions))

    def extend(self, other: "Plan") -> None:
        self.actions.extend(other.actions)
        self.skipped.extend(other.skipped)
