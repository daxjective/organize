"""창이 무엇을 보여줄지 계산한다. **여기서 tkinter 를 쓰지 않는다.**

화면을 그리는 일(위젯)과 무엇을 그릴지 정하는 일(여기)을 나눈다. 그래야
tkinter 가 없는 환경에서도 로직을 테스트할 수 있고, "미리보기를 보기 전에는
실행 버튼이 켜지지 않는다" 같은 약속을 창을 띄우지 않고 못박을 수 있다.

이 모듈은 CLI 와 **같은 엔진**을 부른다. 화면용으로 따로 계산하지 않는다 —
갈라지는 순간 창에서 본 것과 명령줄에서 본 것이 달라지고, 그러면 어느 쪽이
맞는지 아무도 모르게 된다.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from organize.core.executor import execute, prepare_runlog, write_runlog
from organize.core.runner import BuiltPlan, build_plan, external_names, make_run_id
from organize.core.undo import latest_run_id, undo as undo_run
from organize.errors import OrganizeError
from organize.recipes import find_recipe, list_recipes, load_recipe
from organize.userconfig import (AliasNotDefined, load_config, refuse_unsupported,
                                 resolve_alias)

_KIND_LABEL = {"mkdir": "폴더 생성", "move": "이동",
               "quarantine": "격리", "extract": "압축 해제"}


@dataclass
class Row:
    """표 한 줄. 위젯은 이걸 그대로 그리기만 한다."""
    kind: str                  # 이동 · 격리 · 폴더 생성 · 압축 해제
    name: str                  # 어느 파일
    dest: str                  # 어디로 (전체 경로)
    reason: str                # 왜
    leaving: bool = False      # 정리 대상 폴더 **밖**으로 나가는가


@dataclass
class PreviewView:
    rows: list[Row] = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        c = self.counts
        return (f"이동 {c.get('move', 0)} · 격리 {c.get('quarantine', 0)}"
                f" · 폴더 생성 {c.get('mkdir', 0)} · 압축 해제 {c.get('extract', 0)}"
                f" · 손대지 않음 {self.skipped}")


@dataclass
class ApplyResult:
    # **폴더 생성은 '옮김' 이 아니다.** 이 프로젝트는 이미 한 번 mkdir 을
    # 파일 개수에 섞어 세서 "2건" 이 실제로는 폴더 1 + 파일 1 이었던 적이 있다.
    # 사람이 읽는 숫자는 kind 별로 나눠 센다.
    moved: int = 0             # 실제로 옮긴 파일
    folders: int = 0           # 만든 폴더
    failed: int = 0
    skipped: int = 0
    log_path: Path | None = None
    messages: list[str] = field(default_factory=list)


@dataclass
class UndoResult:
    restored: int = 0
    failed: int = 0
    messages: list[str] = field(default_factory=list)


class Session:
    """창 하나가 들고 있는 상태. 고른 것, 본 것, 한 것."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = Path(repo_root)
        self._root: Path | None = None
        self._recipe_name: str | None = None
        self._recipe = None
        # 미리보기 결과. **이것이 있어야만 실행할 수 있다.**
        self._built: dict[Path, BuiltPlan] | None = None
        self._applied_root: Path | None = None

    # ── 고를 수 있는 것 ───────────────────────────────────────────
    def recipe_names(self) -> list[str]:
        return list_recipes(self.repo_root / "recipes")

    def set_root(self, folder: Path | str | None) -> None:
        new = Path(folder) if folder else None
        if new != self._root:
            self._invalidate()          # 대상이 바뀌면 본 것이 무효다
        self._root = new

    def set_recipe(self, name: str | None) -> None:
        if not name:
            self._recipe_name, self._recipe = None, None
            self._invalidate()
            return
        recipe = load_recipe(find_recipe(self.repo_root / "recipes", name))
        if name != self._recipe_name:
            self._invalidate()
        self._recipe_name, self._recipe = name, recipe

    def _invalidate(self) -> None:
        """미리보기 결과를 버린다.

        **폴더나 레시피를 바꾸면 반드시 여기를 지난다.** 안 그러면 A 를
        미리보고 B 로 바꾼 뒤 그대로 실행을 눌러 **본 적 없는 결과**가 벌어진다.
        명령줄에서 `--root` 가 빠져 엉뚱한 폴더를 정리할 뻔한 것과 같은 부류다.
        """
        self._built = None

    # ── 버튼이 켜지는가 ───────────────────────────────────────────
    @property
    def root(self) -> Path | None:
        return self._root

    @property
    def recipe_name(self) -> str | None:
        return self._recipe_name

    @property
    def can_preview(self) -> bool:
        return self._root is not None and self._recipe is not None

    @property
    def can_apply(self) -> bool:
        return bool(self._built)

    @property
    def can_undo(self) -> bool:
        if self._root is None:
            return False
        try:
            return latest_run_id(self._root) is not None
        except OSError:
            return False

    # ── 미리보기 ─────────────────────────────────────────────────
    def preview(self) -> PreviewView:
        """계획을 세워 표로 만든다. **파일을 건드리지 않는다.**"""
        root, recipe = self._require_choices()
        if not root.is_dir():
            raise OrganizeError(
                f"정리할 폴더를 찾을 수 없습니다: {root}",
                hint="폴더가 지워졌거나, USB·SD카드라면 꽂혀 있는지 확인해 주세요.")
        refuse_unsupported(load_config(self.repo_root))

        external = self._resolve_external(apply=False)
        built = build_plan(root, recipe.steps, today=date.today(),
                           run_id=make_run_id(datetime.now()),
                           profiles_dir=self.repo_root / "profiles",
                           external=external)
        self._built = {root: built}
        return self._view(built)

    def _view(self, built: BuiltPlan) -> PreviewView:
        rows: list[Row] = []
        나가는것: dict[Path, int] = {}
        for a in built.plan.actions:
            leaving = False
            if a.dst is not None and not a.dst.is_relative_to(built.root):
                for base in built.external:
                    if a.dst.is_relative_to(base):
                        leaving = True
                        if a.kind != "mkdir":
                            나가는것[base] = 나가는것.get(base, 0) + 1
                        break
            rows.append(Row(
                kind=_KIND_LABEL.get(a.kind, a.kind),
                name=a.src.name if a.src else "",
                dest=str(a.dst) if a.dst else "",
                reason=a.reason,
                leaving=leaving))

        warnings = [
            f"이 정리는 파일 {n}개를 정리 대상 폴더 밖으로 내보냅니다 → {base}"
            f"  (되돌리기 전까지 원래 폴더에 없습니다)"
            for base, n in sorted(나가는것.items(), key=lambda kv: str(kv[0]))]

        return PreviewView(rows=rows, counts=built.plan.counts(),
                           skipped=len(built.plan.skipped), warnings=warnings)

    # ── 실행 ─────────────────────────────────────────────────────
    def apply(self) -> ApplyResult:
        """미리보기에서 본 그 계획을 그대로 수행한다.

        **미리보기 없이는 실행하지 않는다.** 창의 버튼 상태만 믿지 않고
        여기서 한 번 더 막는다 — 버튼을 잘못 켜는 실수가 파일을 옮기면 안 된다.
        """
        if not self._built:
            raise OrganizeError(
                "먼저 미리보기를 해 주세요.",
                hint="무엇이 어디로 가는지 확인한 뒤에 실행할 수 있습니다.")
        root, _ = self._require_choices()
        self._resolve_external(apply=True)     # USB 가 꽂혀 있는지 여기서 본다

        built = self._built[root]
        prepare_runlog(built)
        result = execute(built)

        out = ApplyResult(
            moved=sum(1 for r in result.done if r.get("kind") != "mkdir"),
            folders=sum(1 for r in result.done if r.get("kind") == "mkdir"),
            failed=len(result.failed), skipped=len(result.stale))
        try:
            out.log_path = write_runlog(built, result)
        except OrganizeError as e:
            # 기록을 못 남겼어도 무엇을 옮겼는지는 화면에 남긴다 — 사람이
            # 손으로 되돌릴 수 있는 유일한 근거다.
            out.messages.append(e.message)
            for row in result.done:
                out.messages.append(f"{row.get('src', '')} → {row.get('final', '')}")
        for row in result.failed:
            out.messages.append(f"실패  {row['why']}")

        self._applied_root = root
        self._invalidate()          # 실행했으면 그 미리보기는 이미 쓴 것이다
        return out

    # ── 되돌리기 ─────────────────────────────────────────────────
    def undo(self) -> UndoResult:
        root = self._applied_root or self._root
        if root is None:
            raise OrganizeError("되돌릴 폴더를 알 수 없습니다.",
                                hint="정리할 폴더를 먼저 골라 주세요.")
        result = undo_run(root)
        out = UndoResult(restored=len(result.done), failed=len(result.failed))
        for row in result.failed:
            out.messages.append(f"실패  {row['why']}")
        self._invalidate()
        return out

    # ── 내부 ─────────────────────────────────────────────────────
    def _require_choices(self):
        if self._root is None:
            raise OrganizeError("정리할 폴더를 골라 주세요.",
                                hint="[찾아보기] 를 눌러 폴더를 고릅니다.")
        if self._recipe is None:
            raise OrganizeError("무엇을 할지 골라 주세요.",
                                hint="목록에서 정리 방식을 고릅니다.")
        return self._root, self._recipe

    def _resolve_external(self, *, apply: bool) -> dict[str, Path]:
        """레시피가 밖으로 내보내려는 이름들을 실제 경로로 푼다.

        CLI 와 같은 규칙이다: 등록 안 된 이름이면 거부하고, 실행할 때는 그
        위치가 실제로 있는지도 본다(USB 가 안 꽂혔을 수 있다). 미리보기는
        꽂지 않은 채로도 무엇이 어디로 갈지 볼 수 있어야 하므로 따지지 않는다.
        """
        names = external_names(self._recipe.steps) if self._recipe else []
        if not names:
            return {}
        cfg = load_config(self.repo_root)
        out: dict[str, Path] = {}
        for name in names:
            try:
                path = resolve_alias(f"@{name}", cfg)
            except AliasNotDefined as e:
                raise OrganizeError(
                    f"보낼 위치 '@{name}' 가 등록되어 있지 않습니다.",
                    hint="[보낼 곳] 옆 [찾아보기] 로 폴더를 골라 등록해 주세요.") from e
            if apply and not path.is_dir():
                raise OrganizeError(
                    f"보낼 위치 '@{name}' 를 찾을 수 없습니다: {path}",
                    hint="USB·SD카드라면 꽂혀 있는지, 드라이브 문자가 바뀌지 "
                         "않았는지 확인해 주세요.")
            out[name] = path
        return out
