"""블록 사이에 상태를 넘기는 가상 파일 시스템 뷰.

블록은 파일을 만지지 않으므로, 2번 블록이 1번 블록의 결과를 보려면
"이 블록이 끝나면 어디에 있을 것인가"를 따로 들고 있어야 한다.
Context 가 그 장부다. 키는 항상 **원래 경로** 이므로 여러 번 옮겨도 추적된다.

블록은 Action 의 `src` 에 반드시 `ctx.current_path(entry)` 를 넣어야 한다.
이미 옮겨진 파일에 옛 경로를 넘기면 `_by_current` 에서 찾지 못해 그 이동이 장부에
반영되지 않는다. 그러면 다음 블록이 파일을 엉뚱한 곳에서 찾아 0건이 된다.
(미리보기와 실행이 어긋나지는 않는다 — 실행기는 Context 가 아니라 Plan 을 그대로 쓴다.)
"""

import os
from datetime import date
from pathlib import Path

from organize.core.action import Plan
from organize.core.scanner import FileEntry
from organize.errors import OrganizeError


class Context:
    def __init__(self, root: Path, entries: list[FileEntry], today: date,
                 run_id: str = "", external: dict[str, Path] | None = None) -> None:
        self.root = root
        self.today = today
        self.run_id = run_id
        # 이름 -> 정리 대상 폴더 **밖**의 실제 경로. 백업용이다(SD카드·USB).
        # 러너가 설정(`config.local.json`)에서 풀어서 넣어 준다. 여기 없는
        # 이름으로는 밖으로 못 나간다 — 손으로 쓴 경로는 아예 못 나간다.
        # 등록이라는 한 단계가 곧 안전장치다: 오타는 등록되어 있지 않다.
        self.external: dict[str, Path] = dict(external or {})
        self._entries: list[FileEntry] = list(entries)
        self._rel: dict[Path, str] = {}
        self._name: dict[Path, str] = {}
        self._gone: set[Path] = set()
        # 현재 경로 -> 원래 경로. 블록이 넘겨주는 Action.src 는 '지금 위치' 이므로
        # 이 표가 없으면 두 번째 이동부터 추적이 끊긴다.
        self._by_current: dict[Path, Path] = {}
        # 폴더별로 이 Plan 에서 이미 잡힌 이름. claim_name 이 쓴다.
        self._claimed: dict[str, set[str]] = {}
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
        if not self.run_id:
            # 빈 문자열이면 pathlib 이 조각을 접어서 .organize/trash 자체가 된다.
            # 그러면 실행마다 같은 폴더에 쌓여 undo 가 어느 실행 것인지 모른다.
            raise OrganizeError(
                "실행 번호 없이 격리 폴더를 정할 수 없습니다.",
                hint="파일을 치우는 작업은 organize run 으로 실행해 주세요.")
        return self.root / ".organize" / "trash" / self.run_id

    def rel_of(self, entry: FileEntry) -> str:
        return self._rel.get(entry.path, self._relative_folder(entry.path))

    def current_path(self, entry: FileEntry) -> Path:
        rel = self.rel_of(entry)
        name = self._name.get(entry.path, entry.path.name)
        return (self.root / rel / name) if rel else (self.root / name)

    def origin_of(self, path: Path) -> Path | None:
        """지금 이 경로에 있는 파일의 **원래 경로**. 모르면 None.

        화면이 체크박스를 **파일 단위**로 묶으려면 Action 하나가 어느 원본에서
        왔는지 알아야 한다. route 가 옮긴 뒤 by_date 가 또 옮기면 `Action.src`
        는 중간 경로라서 원본이 아니다.

        **`apply()` 전에 물어야 한다.** apply 가 `_by_current` 에서 옛 경로를
        지우므로, 뒤에 물으면 그 파일은 이미 사라지고 없어 None 이 돌아온다.
        """
        return self._by_current.get(path)

    def all_files(self) -> list[FileEntry]:
        alive = [e for e in self._entries if e.path not in self._gone]
        return sorted(alive, key=lambda e: (self.rel_of(e), e.path.name))

    def claim_name(self, rel: str, name: str) -> str:
        """이 Plan 안에서 `rel` 폴더에 `name` 을 쓰겠다고 잡는다. 잡힌 이름을 준다.

        **블록이 같은 목적지를 가리키는 동작을 두 개 만들면 안 된다.** 그러면
        미리보기가 거짓말을 하고(둘 다 같은 곳으로 간다고 보여준다), 실행기의
        이름 대응표가 어느 파일 것인지 구분하지 못한다. 실측했다 —
        같은 이름 파일 둘을 한 폴더로 보낸 뒤 날짜별로 또 나누게 했더니,
        한 파일만 연도 폴더로 가고 다른 하나는 조용히 남았으며, 사용자가 본 적
        없는 이름(`사진_(1).png`)으로 실패 메시지가 나왔다.

        이미 그 폴더에 있는 이름과, 이 Plan 에서 앞서 잡힌 이름을 함께 본다.
        **대소문자를 구분하지 않는다** — 주 사용 환경인 윈도우가 그렇다.

        디스크는 미리보기 이후에도 바뀔 수 있으므로 이 이름이 최종이라고
        보장하지는 않는다. 실행기가 `claim_path` 로 다시 잡는다. 여기서 하는
        일은 **한 Plan 안에서의 애매함을 없애는 것**이다.
        """
        # 같은 폴더를 가리키는 문자열이 여러 가지다 — "02_Media", "02_Media/",
        # "./02_Media", 그리고 윈도우에서는 "02_media" 까지. 정규화하지 않으면
        # 한 폴더에 이름표가 여러 개 생겨 서로를 못 본다. 실측했다.
        key = os.path.normpath(rel.replace("\\", "/") or ".").casefold()
        if key == ".":
            key = ""
        # setdefault 를 쓰면 안 된다 — 파이썬은 키가 이미 있어도 **두 번째 인자를
        # 항상 평가한다.** 그래서 이름표가 캐시돼 있는데도 files_at() 이 매번 다시
        # 돌았고, files_at 은 all_files() 로 전체를 정렬하므로 파일 하나당
        # O(n log n), 합쳐서 **O(n² log n)** 이 됐다. 실측: 1000개 미리보기 41초.
        # 진짜 다운로드 폴더에서는 미리보기 한 번에 몇 분이다.
        taken = self._claimed.get(key)
        if taken is None:
            taken = self._names_at(rel)
            self._claimed[key] = taken
        stem, suffix = Path(name).stem, Path(name).suffix
        candidate, n = name, 0
        while candidate.casefold() in taken:
            n += 1
            candidate = f"{stem}_({n}){suffix}"
        taken.add(candidate.casefold())
        return candidate

    def external_folder(self, rel: str) -> Path | None:
        """`@백업` · `@백업/2026` 을 실제 경로로 푼다. 못 풀면 None.

        **경로 계산은 여기 한 곳에서만 한다.** 목적지를 정하는 곳(dest_folder)과
        이름을 잡는 곳(claim_name)이 각자 계산하면, 둘이 다른 폴더를 보게 되는
        순간 미리보기가 거짓말을 한다. 이 프로젝트가 이미 겪은 실패다
        ("이름을 잡는 곳이 하나여야 한다").

        등록되지 않은 이름은 None 을 준다 — 여기서 예외를 던지지 않는 이유는,
        부르는 쪽마다 할 말이 다르기 때문이다(목적지는 거부해야 하고, 이름표는
        그냥 비어 있는 것으로 보면 된다).
        """
        if not rel.startswith("@"):
            return None
        name, _, tail = rel[1:].partition("/")
        base = self.external.get(name)
        if base is None:
            return None
        folder = Path(os.path.normpath(base / tail)) if tail else Path(os.path.normpath(base))
        return folder if folder.is_relative_to(base) else None

    def _disk_names(self, folder: Path) -> set[str]:
        """그 폴더에 **실제로 있는** 파일 이름들(소문자).

        폴더가 아직 없거나(앞으로 만들 목적지) 읽을 수 없으면(USB 가 안 꽂혔다)
        **비어 있는 것으로 본다** — 미리보기는 죽지 않아야 한다. 실제로 쓸 때는
        실행기가 `claim_path` 로 원자적으로 다시 잡으므로 덮어쓸 위험은 없다.
        """
        try:
            return {p.name.casefold() for p in folder.iterdir() if p.is_file()}
        except OSError:
            return set()

    def _names_at(self, rel: str) -> set[str]:
        """그 폴더에 이미 있는 파일 이름들(소문자). 이름표의 출발점이다.

        **스캐너가 본 것과 디스크에 실제로 있는 것을 합친다.** 스캐너를 통과한
        파일만 세면 이름표에 구멍이 난다 — 시스템 파일, 1분 안에 바뀐 파일,
        그리고 사용자가 미리보기에서 뺀 파일은 스캔 결과에 없지만 디스크에는
        그대로 앉아 있다. 그 이름을 비어 있다고 보면 미리보기가 "영상.mp4 로
        간다" 고 약속해 놓고 실제로는 `영상_(1).mp4` 가 된다(실행기가 덮어쓰지
        않으려고 비켜 놓는다). 데이터는 안전하지만 **화면과 실제가 다르다.**

        밖(external)과 안이 같은 모양이어야 한다 — 이름을 잡는 곳은 하나다.
        """
        external = self.external_folder(rel)
        if external is not None:
            return self._disk_names(external)
        return ({e.path.name.casefold() for e in self.files_at(rel)}
                | self._disk_names(self.root / rel if rel else self.root))

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
                # 압축 안에 적힌 크기·시각을 그대로 쓴다. 0 을 넣으면 by_date 가
                # 이 파일을 1970 폴더로 보낸다 — 사슬 전체가 무의미해진다.
                new = FileEntry(path=a.dst, size=a.size, mtime=a.mtime, virtual=True)
                self._entries.append(new)
                self._rel[new.path] = self._relative_folder(a.dst)
                self._name[new.path] = a.dst.name
                self._by_current[a.dst] = new.path
