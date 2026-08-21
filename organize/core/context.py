"""블록 사이에 상태를 넘기는 가상 파일 시스템 뷰.

블록은 파일을 만지지 않으므로, 2번 블록이 1번 블록의 결과를 보려면
"이 블록이 끝나면 어디에 있을 것인가"를 따로 들고 있어야 한다.
Context 가 그 장부다. 키는 항상 **원래 경로** 이므로 여러 번 옮겨도 추적된다.

블록은 Action 의 `src` 에 반드시 `ctx.current_path(entry)` 를 넣어야 한다.
이미 옮겨진 파일에 옛 경로를 넘기면 `_by_current` 에서 찾지 못해 그 이동이 장부에
반영되지 않는다. 그러면 다음 블록이 파일을 엉뚱한 곳에서 찾아 0건이 된다.
(미리보기와 실행이 어긋나지는 않는다 — 실행기는 Context 가 아니라 Plan 을 그대로 쓴다.)
"""

from datetime import date
from pathlib import Path

from organize.core.action import Plan
from organize.core.scanner import FileEntry


class Context:
    def __init__(self, root: Path, entries: list[FileEntry], today: date,
                 run_id: str = "") -> None:
        self.root = root
        self.today = today
        self.run_id = run_id
        self._entries: list[FileEntry] = list(entries)
        self._rel: dict[Path, str] = {}
        self._name: dict[Path, str] = {}
        self._gone: set[Path] = set()
        # 현재 경로 -> 원래 경로. 블록이 넘겨주는 Action.src 는 '지금 위치' 이므로
        # 이 표가 없으면 두 번째 이동부터 추적이 끊긴다.
        self._by_current: dict[Path, Path] = {}
        for e in entries:
            self._rel[e.path] = self._relative_folder(e.path)
            self._name[e.path] = e.path.name
            self._by_current[e.path] = e.path

    def _relative_folder(self, path: Path) -> str:
        try:
            rel = path.parent.relative_to(self.root)
        except ValueError:
            return ""
        return "" if str(rel) == "." else rel.as_posix()

    @property
    def trash_dir(self) -> Path:
        return self.root / ".organize" / "trash" / self.run_id

    def rel_of(self, entry: FileEntry) -> str:
        return self._rel.get(entry.path, self._relative_folder(entry.path))

    def current_path(self, entry: FileEntry) -> Path:
        rel = self.rel_of(entry)
        name = self._name.get(entry.path, entry.path.name)
        return (self.root / rel / name) if rel else (self.root / name)

    def all_files(self) -> list[FileEntry]:
        alive = [e for e in self._entries if e.path not in self._gone]
        return sorted(alive, key=lambda e: (self.rel_of(e), e.path.name))

    def files_at(self, rel: str) -> list[FileEntry]:
        return [e for e in self.all_files() if self.rel_of(e) == rel]

    def apply(self, plan: Plan) -> None:
        for a in plan.actions:
            if a.kind == "mkdir":
                continue
            origin = self._by_current.get(a.src) if a.src is not None else None

            if a.kind == "quarantine" and origin is not None:
                self._gone.add(origin)
                self._by_current.pop(a.src, None)

            elif a.kind == "move" and origin is not None and a.dst is not None:
                self._by_current.pop(a.src, None)
                self._rel[origin] = self._relative_folder(a.dst)
                self._name[origin] = a.dst.name
                self._by_current[a.dst] = origin

            elif a.kind == "extract" and a.dst is not None:
                new = FileEntry(path=a.dst, size=0, mtime=0.0, virtual=True)
                self._entries.append(new)
                self._rel[new.path] = self._relative_folder(a.dst)
                self._name[new.path] = a.dst.name
                self._by_current[a.dst] = new.path
