"""창이 무엇을 보여줄지 계산한다. **여기서 tkinter 를 쓰지 않는다.**

화면을 그리는 일(위젯)과 무엇을 그릴지 정하는 일(여기)을 나눈다. 그래야
tkinter 가 없는 환경에서도 로직을 테스트할 수 있고, "미리보기를 보기 전에는
실행 버튼이 켜지지 않는다" 같은 약속을 창을 띄우지 않고 못박을 수 있다.

이 모듈은 CLI 와 **같은 엔진**을 부른다. 화면용으로 따로 계산하지 않는다 —
갈라지는 순간 창에서 본 것과 명령줄에서 본 것이 달라지고, 그러면 어느 쪽이
맞는지 아무도 모르게 된다.
"""

import copy
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from organize import catalog
from organize.aliases import BUILTIN
# 종류 이름표는 `core.action` 이 하나만 갖고 있다(창·명령줄이 같은 말을 쓰도록).
from organize.core.action import KIND_LABEL as _KIND_LABEL
from organize.core.executor import execute, prepare_runlog, write_runlog
from organize.core.runner import BuiltPlan, build_plan, external_names, make_run_id
from organize.core.purge import purge_run
from organize.core.undo import latest_run_id, undo as undo_run
from organize.errors import OrganizeError
from organize.recipes import (Recipe, find_recipe, list_recipes, load_recipe,
                              save_recipe as write_recipe_file)
from organize.userconfig import (AliasNotDefined, load_config, refuse_unsupported,
                                 resolve_alias)


@dataclass
class Row:
    """표 한 줄. 위젯은 이걸 그대로 그리기만 한다."""
    kind: str                  # 이동 · 보류 · 폴더 생성 · 압축 해제
    name: str                  # 어느 파일
    dest: str                  # 어디로 (전체 경로)
    reason: str                # 왜
    leaving: bool = False      # 정리 대상 폴더 **밖**으로 나가는가
    # 이 줄이 나온 **원본 파일**의 절대경로 문자열. 체크박스를 파일 단위로
    # 묶는 열쇠다 — 한 파일이 두 번 옮겨지면 줄이 둘인데 체크박스는 하나여야
    # 한다. 폴더 생성처럼 어느 파일 것도 아닌 줄은 빈 문자열.
    key: str = ""
    # ── 보류 줄만 채우는 무리 정보 ──────────────────────────────
    # 표가 "같은 파일 5개" 로 묶고 「어느 자리를 남길까」를 보여주는 근거다.
    # 빈 글자면 무리가 아니다(무리 아닌 보류도 있을 수 있다).
    keeper: str = ""          # 남기는 파일의 절대경로 — 이것으로 묶는다
    keeper_at: str = ""       # 남기는 파일의 위치
    keeper_when: str = ""     # 남기는 파일의 수정일
    keeper_size: str = ""     # 남기는 파일의 크기
    at: str = ""              # 이 줄 파일의 위치
    when: str = ""            # 이 줄 파일의 수정일


@dataclass
class PreviewView:
    rows: list[Row] = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        c = self.counts
        # 이름표를 글자로 다시 적지 않는다 — 말이 바뀌면 여기만 옛말로 남는다.
        return (" · ".join(f"{_KIND_LABEL[k]} {c.get(k, 0)}"
                           for k in ("move", "quarantine", "mkdir", "extract"))
                + f" · 손대지 않음 {self.skipped}")


def root_spec(root: Path | None, cfg) -> str:
    """정리할 폴더를 레시피에 **무엇으로 적을까**. 등록된 이름이 있으면 `@이름`.

    절대 경로를 박아 두면 PC 를 옮기는 순간 그 조합이 죽는다 — 이 도구가
    존재하는 이유가 이식성이다. `@downloads` 로 적어 두면 새 PC 에서는 그 PC 의
    다운로드를 가리킨다.

    **내장 이름을 먼저 본다.** 어느 PC 에나 있는 이름이라 가장 잘 옮겨 간다.
    등록되지 않은 폴더(그 자리에서 직접 고른 것)는 적을 이름이 없으니 경로
    그대로 적는다 — 그 사실은 부르는 쪽이 사용자에게 알린다.
    """
    if root is None:
        return ""
    같은가 = os.path.realpath(root)
    for name in (*BUILTIN, *sorted(cfg.paths)):
        try:
            if os.path.realpath(resolve_alias(f"@{name}", cfg)) == 같은가:
                return f"@{name}"
        except (AliasNotDefined, OSError):
            continue          # 안 풀리는 이름은 그냥 건너뛴다. 여기서 알릴 일은 아니다
    return str(root)


def landing_folders(done, root: Path) -> list[tuple[str, int, str]]:
    """실행 결과를 **어느 폴더에 몇 개** 로 묶는다. (보일 이름, 개수, 진짜 경로).

    파일 113개를 하나씩 늘어놓으면 어디로 갔는지 **오히려 안 보인다.** 실행을
    마친 사람이 하는 일은 "그 폴더에 잘 들어갔나" 를 열어 보는 것이므로, 폴더
    단위로 세고 그 폴더를 바로 열 수 있게 진짜 경로도 같이 준다.

    **폴더 생성은 세지 않는다** — 파일이 아니다. 파일이 들어간 폴더라면 아래
    목록에 이미 나오고, 안 들어갔으면 셀 것이 없다.

    치운 파일(quarantine)은 `.organize/trash/<실행번호>/…` 로 흩어지는데, 그
    안쪽 구조는 사람이 알 바가 아니다. **한 줄로 묶고** 공통 폴더를 준다.
    """
    센것: dict[str, int] = {}
    경로: dict[str, str] = {}
    치운것: list[Path] = []
    for row in done:
        if row.get("kind") == "mkdir":
            continue
        final = row.get("final")
        if not final:
            continue
        if row.get("kind") == "quarantine":
            치운것.append(Path(final))
            continue
        폴더 = Path(final).parent
        이름 = _어디라고_적을까(폴더, root)
        센것[이름] = 센것.get(이름, 0) + 1
        경로[이름] = str(폴더)

    out = [(이름, 센것[이름], 경로[이름]) for 이름 in sorted(센것)]
    if 치운것:
        out.append((_KIND_LABEL["quarantine"], len(치운것), _공통폴더(치운것)))
    return out


def _어디라고_적을까(folder: Path, root: Path) -> str:
    """정리 대상 폴더 안이면 **거기서부터의 상대 경로**만.

    줄마다 `C:\\Users\\나\\Downloads\\` 를 반복하면 정작 다른 부분(어느 폴더로
    갔는가)이 안 보인다. 밖으로 나간 것은 전체 경로를 적는다 — 그건 반복되는
    앞머리가 아니라 **주의해서 봐야 할 자리**다.
    """
    try:
        return str(folder.relative_to(root)) or "(정리 대상 폴더 바로 밑)"
    except ValueError:
        return str(folder)


def file_facts(path: Path | None, root: Path) -> tuple[str, str, str]:
    """(위치, 수정일, 크기). 못 읽으면 전부 빈 글자다.

    **여기서 디스크를 읽는다.** `Action` 에 수정일·크기를 싣지 않기 때문이다 —
    `Action` 은 미리보기와 실행이 공유하는 계약이지 화면 표시용 자루가 아니다.
    부르는 자리가 미리보기 스레드 안이라 창이 멈추지 않는다.

    파일이 이미 없어도 **죽지 않는다.** 두 미리보기 사이에 사용자가 탐색기에서
    지웠을 수 있고, 그건 정상적인 일이다. 줄은 그대로 그리고 이 칸만 비운다.
    """
    if path is None:
        return "", "", ""
    try:
        st = os.stat(path)
    except OSError:
        return "", "", ""
    위치 = _어디라고_적을까(Path(path).parent, root)
    # **`.` 도 받는다.** `_어디라고_적을까` 는 `str(폴더.relative_to(root)) or …`
    # 인데, root 자신이면 `relative_to` 가 `Path('.')` 를 주고 `str()` 이 `'.'`
    # 이라 truthy 다 — `or` 뒤 문구는 **절대 걸리지 않는다**(실측). 그 함수는
    # 실행 결과 목록이 같이 쓰므로 거기서 고치지 않고, 이 자리에서 받아 낸다.
    if 위치 in (".", "(정리 대상 폴더 바로 밑)"):
        위치 = "(최상단)"          # 표에서는 짧아야 한다 — 줄마다 나오는 말이다
    when = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d")
    return 위치, when, human_size(st.st_size)


def human_size(n: int) -> str:
    """사람이 읽는 크기. 바이트 수를 그대로 보여주면 큰지 작은지 안 읽힌다."""
    칸 = float(n)
    for 단위 in ("B", "KB", "MB", "GB"):
        if 칸 < 1024 or 단위 == "GB":
            return f"{int(칸)}{단위}" if 단위 == "B" else f"{칸:.1f}{단위}"
        칸 /= 1024
    return f"{칸:.1f}GB"


def _공통폴더(paths: list[Path]) -> str:
    """여러 파일이 들어간 자리를 **하나로** 가리키는 폴더."""
    부모들 = [str(p.parent) for p in paths]
    try:
        return os.path.commonpath(부모들)
    except ValueError:
        return 부모들[0]        # 드라이브가 서로 다르다 — 첫 자리라도 알려준다


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
    # 파일이 실제로 들어간 자리. (보일 이름, 개수, 진짜 경로) — 창이 이걸
    # 눌러서 열 수 있는 목록으로 그린다. 숫자만으로는 "잘 됐나" 를 확인할
    # 방법이 없어서, **확인하러 갈 곳**을 같이 준다.
    landed: list[tuple[str, int, str]] = field(default_factory=list)
    # 실행 뒤 [보류한 N개 지우기] 를 그리는 근거. 창이 이 둘 없이는 그 단추를
    # 그릴 수도, 무엇을 지울지 정할 수도 없다.
    run_id: str = ""
    quarantined: int = 0


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
        # 레시피 드롭다운과 체크박스는 둘 다 이 steps 를 채우는 두 가지 방법일
        # 뿐이다 — Recipe 객체를 따로 들고 있으면 체크박스가 끼어들 자리가 없다.
        self._steps: list[dict] = []
        # 이번 실행에서 뺄 파일들(Row.key = 원본 절대경로 문자열).
        self._excluded: set[str] = set()
        # 미리보기 결과. **이것이 있어야만 실행할 수 있다.**
        self._built: dict[Path, BuiltPlan] | None = None
        self._applied_root: Path | None = None

    # ── 고를 수 있는 것 ───────────────────────────────────────────
    def recipe_names(self) -> list[str]:
        return list_recipes(self.repo_root / "recipes")

    def saved_roots(self) -> list[str]:
        """지금 고른 폴더를 레시피에 적을 형태로. 아직 안 골랐으면 빈 목록."""
        if self._root is None:
            return []
        return [root_spec(self._root, load_config(self.repo_root))]

    def recipe_root_label(self, name: str) -> str:
        """그 조합이 **어느 폴더용인지**. 드롭다운에 미리 적으려고 쓴다.

        못 풀거나 안 적혀 있으면 빈 글자다 — 모르면 아무 말도 안 하는 편이,
        틀린 폴더 이름을 적어 두는 것보다 낫다.
        """
        try:
            recipe = load_recipe(find_recipe(self.repo_root / "recipes", name))
            if not recipe.roots:
                return ""
            spec = recipe.roots[0]
            if spec.startswith("@"):
                # 이름 그대로가 사람이 부르는 말이다(`@downloads` → "다운로드").
                from organize.folders import LABEL
                이름 = spec[1:].partition("/")[0]
                return LABEL.get(이름, 이름)
            return Path(spec).name or spec
        except (OrganizeError, AliasNotDefined, OSError):
            return ""

    def set_root(self, folder: Path | str | None) -> None:
        """정리할 폴더를 정한다. **진짜 바뀌었을 때만** 본 것을 버린다.

        `set_recipe` 와 같은 빗장이다. 무조건 버리면, 창이 같은 폴더를 다시
        고르거나(사용자가 [찾아보기] 에서 같은 것을 다시 눌렀다) 화면을
        새로고침하면서 같은 값을 되먹일 때마다 체크 상태와 미리보기가 조용히
        날아간다 — 사용자는 자기가 뭘 잘못 눌렀는지 알 수 없다.
        """
        new = Path(folder) if folder else None
        if new == self._root:
            return
        self._invalidate()          # 대상이 바뀌면 본 것이 무효다
        # 다른 폴더인데 옛 제외가 남아 있으면 설명할 수 없는 결과가 된다.
        self._clear_excluded()
        self._root = new

    def set_recipe(self, name: str | None) -> None:
        """레시피 파일에서 steps 를 채운다.

        레시피의 step 은 **그대로 쓴다** — 카탈로그로 못 알아보는 것도
        버리지 않는다. `unmatched_steps()` 가 그걸 화면에 드러낸다.
        """
        if not name:
            self._recipe_name, self._steps = None, []
            self._invalidate()
            self._clear_excluded()
            return
        recipe = load_recipe(find_recipe(self.repo_root / "recipes", name))
        new_steps = list(recipe.steps)
        # 이름이 같아도 파일 내용이 바뀌었으면 무효화한다 — 그래야 같은 이름을
        # 다시 골랐을 때 옛 미리보기(_built)가 화면에 안 보이는 계획을 실행하게
        # 두지 않는다. 반대로 진짜 아무것도 안 바뀐 재선택까지 지우면 다음
        # Task 에서 드롭다운을 새로고침할 때마다 미리보기가 날아간다.
        if name != self._recipe_name or new_steps != self._steps:
            self._invalidate()
            # 할 일이 바뀌었으면 어느 파일을 뺐는지도 의미가 없어진다.
            self._clear_excluded()
        self._recipe_name, self._steps = name, new_steps

    def detach_recipe(self) -> bool:
        """조합 **이름만** 뗀다. 켜 둔 할 일(steps)은 그대로 남긴다.

        `set_recipe(None)` 과 다르다 — 그쪽은 steps 까지 비운다. 정리할 폴더를
        바꿨다고 켜 둔 할 일까지 사라지면, 사용자는 자기가 무엇을 지웠는지 알
        방법이 없다.

        이름만 떼는 이유: 조합은 **폴더까지 묶어서** 저장한 것이다. 폴더가
        달라진 순간에도 화면이 그 조합 이름을 달고 있으면 거짓말이 된다
        (「사진 → 사진」 이라고 적힌 채 실제로는 바탕화면을 정리하게 된다).

        이미 이름이 없으면 아무 일도 하지 않는다 — 미리보기를 괜히 버리지 않기
        위해 돌려주는 값으로 "뗐는지" 를 알린다.
        """
        if self._recipe_name is None:
            return False
        self._recipe_name = None
        return True

    def set_steps(self, ids: list[str]) -> None:
        """켠 작업들을 **보이는 순서 그대로** steps 로 만든다.

        catalog.by_id 로 푼다 — 모르는 id 면 OrganizeError(파이썬 KeyError
        가 아니다). 체크박스로 조립했으니 이제 어떤 레시피도 아니다.
        """
        steps = [catalog.by_id(entry_id).step for entry_id in ids]
        self._recipe_name = None
        self._steps = steps
        self._invalidate()
        self._clear_excluded()

    def checked_ids(self) -> list[str]:
        """지금 steps 중 카탈로그로 알아볼 수 있는 것들의 id, steps 순서대로.

        알아보기는 dict 완전 일치다. block 이름만 같은 것은 알아본 것이
        아니다 — target 이 다르면 실제로 다른 폴더가 만들어진다.
        """
        entries = catalog.catalog()
        ids: list[str] = []
        for step in self._steps:
            for e in entries:
                if e.step == step:
                    ids.append(e.id)
                    break
        return ids

    def unmatched_steps(self) -> list[dict]:
        """카탈로그에 없는 step 들(원본 dict), steps 순서대로.

        **버리지 않는다.** 조용히 사라지는 step 이 이 프로젝트가 여러 번
        물린 병이다 — 화면은 이 목록이 비어 있지 않으면 사용자에게 알려야 한다.
        """
        catalog_steps = [e.step for e in catalog.catalog()]
        # deepcopy 해서 돌려준다 — catalog._copy() 와 같은 이유다: 받은 쪽이
        # 이 dict 를 고치면 _invalidate() 를 안 지나고 _steps 안의 같은 객체가
        # 조용히 오염된다.
        return [copy.deepcopy(step) for step in self._steps if step not in catalog_steps]

    def _recipe_path(self, name: str) -> Path:
        """조합 이름을 파일 경로로 바꾼다. **여기가 이름 검사의 유일한 자리다.**

        사용자가 타이핑한 값을 그대로 경로에 붙이므로, 손으로 쓴 이름으로는
        저장소 밖에 못 나간다는 전역 규칙을 여기서 지킨다. 저장·이름 바꾸기가
        따로 검사하면 한쪽만 고쳐지는 날이 온다.

        앞뒤 공백을 뗀 이름을 **끝까지** 쓴다 — 안 그러면 "  desktop  " 이
        진짜 desktop.json 과의 겹침 검사를 피해 "  desktop  .json" 이라는
        다른 파일을 만든다.
        """
        이름 = (name or "").strip()
        if not 이름:
            raise OrganizeError("조합 이름을 입력해 주세요.", hint="예: 내조합")
        if "/" in 이름 or "\\" in 이름 or ".." in 이름:
            raise OrganizeError(
                f"조합 이름에 쓸 수 없는 문자가 있습니다: {이름}",
                hint="폴더 구분자(/, \\)나 '..' 없이 이름만 입력해 주세요.")
        return self.repo_root / "recipes" / f"{이름}.json"

    def rename_recipe(self, old: str, new: str, *, overwrite: bool = False) -> Path:
        """조합 이름을 바꾼다. **파일 이름과 파일 안의 이름을 같이 바꾼다.**

        파일 이름만 바꾸면 `Recipe.name` 이 옛 이름으로 남아, 목록에 보이는
        이름과 파일 안의 이름이 갈라진다.

        **새 파일을 먼저 쓰고 옛 파일을 지운다.** 반대로 하면 쓰기가 실패했을
        때 조합이 통째로 사라진다. 이 순서에서 최악은 같은 조합이 둘로 보이는
        것이고, 그건 사용자가 하나 지우면 된다.
        """
        옛것 = find_recipe(self.repo_root / "recipes", old)
        새것 = self._recipe_path(new)
        if 새것 == 옛것:
            return 옛것               # 같은 이름을 그대로 넣었다 — 바꿀 것이 없다
        if 새것.exists() and not overwrite:
            raise OrganizeError(
                f"'{새것.stem}' 조합이 이미 있습니다.",
                hint="덮어쓰려면 같은 이름으로 다시 눌러 주세요.")
        recipe = load_recipe(옛것)
        recipe.name = 새것.stem
        try:
            write_recipe_file(새것, recipe)
        except OSError as e:
            raise OrganizeError(
                f"'{새것.stem}' 으로 바꾸지 못했습니다.",
                hint="이름에 시스템 예약어를 쓰지 않았는지, 너무 길지 않은지, "
                     "폴더에 쓸 권한이 있는지 확인해 주세요.") from e
        try:
            옛것.unlink()
        except OSError as e:
            raise OrganizeError(
                f"새 이름으로는 만들었지만 옛 이름('{old}')을 지우지 못했습니다.",
                hint="목록에 둘 다 보일 수 있습니다. 옛 것을 [지우기] 로 지워 주세요."
                ) from e
        if self._recipe_name == old:
            self._recipe_name = 새것.stem
        return 새것

    def delete_recipe(self, name: str) -> None:
        """조합 파일을 지운다. **되돌릴 수 없다** — 묻는 일은 창이 한다.

        지운 뒤에도 켜 둔 할 일은 남긴다(`detach_recipe` 와 같은 이유). 이름을
        지웠다고 지금 하려던 일까지 없앨 이유가 없다.
        """
        path = find_recipe(self.repo_root / "recipes", name)
        try:
            path.unlink()
        except OSError as e:
            raise OrganizeError(
                f"'{name}' 조합을 지우지 못했습니다.",
                hint="파일이 다른 프로그램에서 열려 있지 않은지 확인해 주세요.") from e
        if self._recipe_name == name:
            self._recipe_name = None   # 없는 것을 계속 가리키고 있을 수 없다

    def save_recipe(self, name: str, *, overwrite: bool = False) -> Path:
        """지금 steps 와 **정리할 폴더**를 레시피 JSON 으로 저장한다.

        예전에는 `roots=[]` 로 폴더를 버렸다. 그래서 딸려 온 레시피 셋(폴더가
        박혀 있다)과 내가 저장한 것(폴더가 없다)이 **같은 드롭다운에 섞여 있는데
        하나는 대상을 바꾸고 하나는 안 바꿨다.** 어느 쪽인지 화면에 표시도
        없었다 — "레시피를 고르면 대상이 자동으로 박히는 구조인가" 라는 질문이
        나온 뿌리다.

        이름을 붙여 저장하는 이유는 **다음에 똑같이 하려고** 이므로, 폴더도 같이
        기억한다. 등록된 폴더는 `@이름` 으로 적어 다른 PC 에서도 살아 있게 한다.
        """
        path = self._recipe_path(name)
        name = path.stem
        if not self._steps:
            raise OrganizeError("저장할 작업이 없습니다.",
                                hint="체크박스를 하나 이상 켜 주세요.")

        if path.exists() and not overwrite:
            raise OrganizeError(
                f"'{name}' 레시피가 이미 있습니다.",
                hint="덮어쓰려면 같은 이름으로 다시 저장을 눌러 주세요.")

        try:
            write_recipe_file(path, Recipe(name=name, roots=self.saved_roots(),
                                           steps=list(self._steps)))
        except OSError as e:
            # 파이썬 예외 원문을 그대로 보여주지 않는다 — 윈도우 예약어(con,
            # nul), 너무 긴 이름, 권한 없음을 한꺼번에 덮는 한국어 메시지로 바꾼다.
            raise OrganizeError(
                f"'{name}' 레시피를 저장하지 못했습니다.",
                hint="이름에 시스템 예약어를 쓰지 않았는지, 너무 길지 않은지, "
                     "폴더에 쓸 권한이 있는지 확인해 주세요.") from e
        self._recipe_name = name          # 드롭다운이 방금 저장한 것을 가리켜야 한다
        return path

    # ── 이번 실행에서 뺄 파일 ────────────────────────────────────
    def set_excluded(self, keys: set[str] | list[str]) -> None:
        """미리보기 표에서 체크를 끈 파일들(`Row.key`)을 기억한다.

        **여기서 다시 계획을 세우지 않는다. 창이 이 뒤에 `preview()` 를 부르는
        책임을 진다.** 창은 체크를 여러 개 껐다 켤 수 있고, 그때마다 계획을
        통째로 다시 세우면 느리기 때문이다.

        대신 **실행 버튼이 꺼진다**(`can_apply` == False). 이것이 핵심
        안전장치다 — 체크를 바꿨는데 예전 계획으로 실행되면 사용자가 본 적
        없는 일이 벌어진다.
        """
        self._excluded = {str(k) for k in keys}
        self._invalidate()

    def excluded_keys(self) -> set[str]:
        """지금 뺀 파일들의 key. 창이 체크 상태를 그리는 데 쓴다.

        **복사본을 준다** — 받은 쪽이 고치면 `_invalidate()` 를 안 지나고
        세션 상태가 조용히 바뀐다.
        """
        return set(self._excluded)

    def _clear_excluded(self) -> None:
        """제외 목록을 비운다. 비울 것이 있었으면 **미리보기도 함께 버린다.**

        체크 상태와 세워 둔 계획이 갈라지면, 화면은 다 켜진 체크박스를 그리는데
        실행은 뺀 계획으로 도는 상태가 된다 — 사용자가 설명할 수 없는 결과다.
        """
        if self._excluded:
            self._excluded = set()
            self._invalidate()

    def invalidate(self) -> None:
        """계산해 둔 미리보기를 버린다.

        창이 "내가 부탁한 것과 지금 설정이 달라졌다" 고 말할 수 있어야 한다.
        (set_root/set_steps 를 다시 불러도 값이 같으면 빠져나가므로 안 통한다.)
        """
        self._invalidate()

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
        return self._root is not None and bool(self._steps)

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
        root, steps = self._require_choices()
        if not root.is_dir():
            raise OrganizeError(
                f"정리할 폴더를 찾을 수 없습니다: {root}",
                hint="폴더가 지워졌거나, USB·SD카드라면 꽂혀 있는지 확인해 주세요.")
        refuse_unsupported(load_config(self.repo_root))

        external = self._resolve_external(apply=False)
        built = build_plan(root, steps, today=date.today(),
                           run_id=make_run_id(datetime.now()),
                           profiles_dir=self.repo_root / "profiles",
                           external=external,
                           # 뺀 파일은 블록이 **아예 못 보게** 한다. 만들어진
                           # 계획에서 골라내면 빈 폴더가 생기고 `_(1)` 이 남는다
                           # (runner.build_plan 의 설명 참고).
                           exclude={Path(k) for k in self._excluded})
        self._built = {root: built}
        return self._view(built)

    def _view(self, built: BuiltPlan) -> PreviewView:
        rows: list[Row] = []
        나가는것: dict[Path, int] = {}
        # strict=True 로 묶는다. 길이가 어긋나면 **화면이 엉뚱한 파일에 체크를
        # 붙인다** — 조용히 밀린 채로 그리느니 여기서 터지는 편이 낫다.
        for a, origin in zip(built.plan.actions, built.origins, strict=True):
            leaving = False
            if a.dst is not None and not a.dst.is_relative_to(built.root):
                for base in built.external:
                    if a.dst.is_relative_to(base):
                        leaving = True
                        if a.kind != "mkdir":
                            나가는것[base] = 나가는것.get(base, 0) + 1
                        break
            # 보류 줄만 무리 정보를 싣는다. `a.keeper` 가 None 이면(quarantine
            # 이 아니거나, unzip 의 delete_original 처럼 keeper 없는 보류)
            # file_facts 를 아예 안 부른다 — file_facts 는 os.stat 을 한다.
            # move·mkdir·extract 줄까지 매번 두 번씩 디스크를 읽을 이유가 없다.
            if a.keeper is not None:
                k_at, k_when, k_size = file_facts(a.keeper, built.root)
                내_at, 내_when, _ = file_facts(a.src, built.root)
            else:
                k_at = k_when = k_size = 내_at = 내_when = ""
            rows.append(Row(
                kind=_KIND_LABEL.get(a.kind, a.kind),
                # 폴더 생성에는 **원본 파일이 없다**(`src=None`). 그대로 두면 이름
                # 칸이 빈 채로 그려져, 표에 줄은 있는데 무엇에 대한 줄인지 안
                # 보인다(실측: 캡처에서 세 줄이 전부 빈칸으로 났다).
                # 만들 폴더 이름을 적는다 — 그 줄의 주인공이 그것이다.
                name=a.src.name if a.src else (a.dst.name if a.dst else ""),
                dest=str(a.dst) if a.dst else "",
                reason=a.reason,
                leaving=leaving,
                key=str(origin) if origin is not None else "",
                keeper=str(a.keeper) if a.keeper else "",
                keeper_at=k_at, keeper_when=k_when, keeper_size=k_size,
                at=내_at, when=내_when))

        warnings = [
            f"이 정리는 파일 {n}개를 정리 대상 폴더 밖으로 내보냅니다 → {base}"
            f"  (되돌리기 전까지 원래 폴더에 없습니다)"
            for base, n in sorted(나가는것.items(), key=lambda kv: str(kv[0]))]

        # 뺐다고 한 파일이 스캔 결과에 없으면 **아무 일도 안 일어난다.**
        # 거부하지는 않는다 — 두 미리보기 사이에 사용자가 탐색기에서 지웠거나
        # USB 를 뽑았을 수 있고, 그건 정상적인 일이다. 대신 조용히 넘어가지
        # 않는다: 조용한 무작동이 이 프로젝트의 금기다.
        if built.missing_excluded:
            warnings.append(
                f"뺀 파일 {len(built.missing_excluded)}개를 찾을 수 없습니다 "
                "— 이미 옮겨졌거나 지워졌을 수 있습니다.")

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
            failed=len(result.failed), skipped=len(result.stale),
            quarantined=sum(1 for r in result.done
                            if r.get("kind") == "quarantine"),
            landed=landing_folders(result.done, root))
        try:
            out.log_path = write_runlog(built, result)
            out.run_id = out.log_path.stem      # 지울 때 어느 실행인지 알아야 한다
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

    def purge_quarantine(self, run_id: str):
        """그 실행이 보류시킨 파일을 지운다. **되돌릴 수 없다.**

        묻는 일은 창이 한다 — 여기는 묻지 않는다. 되돌리기를 끄지도 않는다:
        옮긴 파일은 여전히 되돌아가고, 보류만 못 되살아난다.
        """
        root = self._root or self._applied_root
        if root is None:
            raise OrganizeError(
                "어느 폴더의 보류를 지울지 알 수 없습니다.",
                hint="[정리할 폴더] 를 고른 뒤에 다시 눌러 주세요.")
        return purge_run(root, run_id)

    # ── 되돌리기 ─────────────────────────────────────────────────
    def undo(self) -> UndoResult:
        """지금 고른 폴더의 **마지막 기록**을 되돌린다.

        **`_root` 를 먼저 본다.** `can_undo` 도 `_root` 를 보기 때문이다 —
        순서가 반대면 [되돌리기] 가 켜지는 근거와 실제로 되돌아가는 폴더가
        갈라진다. 실행을 마친 뒤 대상만 바꾸면 화면은 새 폴더를 가리키는데
        `_applied_root`(옛 폴더)의 파일이 움직인다. 화면의 대상 드롭다운이
        진실이다 — 사용자가 보는 것과 일어나는 일이 같아야 한다.

        `_applied_root` 는 대상을 아직 아무것도 안 고른 상태(_root is None)에서만
        쓰이는 마지막 보루다.
        """
        root = self._root or self._applied_root
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
        if not self._steps:
            raise OrganizeError("무엇을 할지 골라 주세요.",
                                hint="목록에서 정리 방식을 고르거나 체크박스를 켜 주세요.")
        return self._root, self._steps

    def _resolve_external(self, *, apply: bool) -> dict[str, Path]:
        """steps 가 밖으로 내보내려는 이름들을 실제 경로로 푼다.

        CLI 와 같은 규칙이다: 등록 안 된 이름이면 거부하고, 실행할 때는 그
        위치가 실제로 있는지도 본다(USB 가 안 꽂혔을 수 있다). 미리보기는
        꽂지 않은 채로도 무엇이 어디로 갈지 볼 수 있어야 하므로 따지지 않는다.
        """
        names = external_names(self._steps) if self._steps else []
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
