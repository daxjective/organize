"""창. **여기는 그리기만 한다** — 무엇을 그릴지는 `gui_model.Session` 이 정한다.

`tkinter` 를 함수 안에서 늦게 import 한다. 없는 환경에서도 `organize` 의 나머지
기능은 그대로 돌아야 하기 때문이다(리눅스에서 tkinter 는 별도 패키지다).

화면은 셋이고 **창은 하나다**(`ttk.Frame` 세 개를 `tkraise()` 로 바꿔 올린다).
창을 여러 개 띄우면 사용자가 창을 관리하게 된다 — 그건 도구의 일이다.

색과 글꼴은 `gui_theme` 만 안다. 여기서 색 코드를 직접 쓰지 않는다.
"""

import json
import queue
import threading
from pathlib import Path
from typing import NamedTuple

from organize import catalog, folders, gui_theme as theme, picker, profiles
from organize.aliases import BUILTIN
from organize.errors import OrganizeError
# 종류 이름표(`move` → "이동")는 `gui_model` 이 이미 갖고 있다. 여기서 같은 표를
# 다시 적으면 탭 이름과 표 안의 글자가 갈라진다 — 한쪽만 고쳐지기 때문이다.
from organize.gui_model import _KIND_LABEL as KIND_LABEL, Session
from organize.recipes import find_recipe, load_recipe
from organize.userconfig import (AliasNotDefined, load_config, remove_local_path,
                                 resolve_alias)

_SCREENS = ("first", "main", "settings")

_TITLES = {"first": "organize — 처음 실행",
           "main": "organize",
           "settings": "설정 · 폴더 위치"}

# 폴더가 비었거나 없을 때 옆에 적는 말. **왜** 그런지까지 적는다 — OneDrive
# 백업이 켜진 PC 에서는 진짜 바탕화면이 다른 곳이라 여기가 0 으로 뜬다.
_ONEDRIVE = "OneDrive 백업이 켜져 있으면 실제 폴더가 다른 곳일 수 있습니다."

# 드롭다운에 고른 것이 없을 때 적는 글자. **빈 칸으로 두지 않는다** — 비어
# 있으면 "아직 안 골랐다" 인지 "고장났다" 인지 구별이 안 된다.
_NO_RECIPE = "(직접 고름)"
_NO_TARGET = "(고르지 않음)"
_LOADING = "(폴더 확인 중…)"
_NO_RECIPE_FILES = "(저장된 레시피 없음)"

# 표에 한 번에 그리는 줄 수의 한계. 다운로드 폴더는 수천 개일 수 있고, 줄마다
# 위젯을 서너 개 만들면 창이 몇 초씩 멈춘다(체크 하나 끌 때마다 다시 그린다).
_MAX_ROWS = 200

# 탭 순서. **폴더 생성(mkdir)은 따로 센다** — 파일 개수에 섞으면 "2건" 이
# 실제로는 폴더 1 + 파일 1 이 된다. 이 프로젝트가 이미 한 번 물린 곳이다.
_KIND_TABS = ("move", "quarantine", "extract", "mkdir")

# 종류별 색. 시안의 색표 그대로 — 이동은 강조색, 격리는 치움색, 새로 생기는
# 것(압축에서 나온 파일 · 만들어질 폴더)은 '새로 생김' 색.
_KIND_COLOR = {"move": (theme.ACCENT, theme.ACCENT_BG),
               "quarantine": (theme.TRASH, theme.TRASH_BG),
               "extract": (theme.NEW, theme.NEW_BG),
               "mkdir": (theme.NEW, theme.NEW_BG)}

# `Row.kind` 는 이미 사람이 읽는 이름표다. 탭(`counts`)은 원래 이름을 쓰므로
# 되짚어야 한다. 표를 **하나만** 두려고 뒤집어 쓴다.
_RAW_KIND = {label: kind for kind, label in KIND_LABEL.items()}


# ── 위젯 없이 도는 부분 ──────────────────────────────────────────
# 아래 함수들은 tkinter 를 모른다. 창을 띄우는 코드는 자동 테스트하기 어려우니,
# **판단하는 대목만 여기로 떼어내** 창 없이 테스트한다(tests/test_gui_logic.py).

def move_item(items: list, index: int, delta: int) -> tuple[list, int]:
    """▲▼ 한 칸. (새 목록, 새 선택 위치) 를 돌려준다.

    맨 위에서 ▲, 맨 아래에서 ▼ 는 **아무 일도 하지 않는다** — 목록이 그대로면
    부르는 쪽이 `set_steps` 를 건너뛰어, 멀쩡한 미리보기가 헛되이 무효가 되는
    것을 막는다.
    """
    out = list(items)
    if index is None or not (0 <= index < len(out)):
        return out, index
    target = index + delta
    if not (0 <= target < len(out)):
        return out, index
    out[index], out[target] = out[target], out[index]
    return out, target


def arrange_steps(all_ids: list[str], checked_ids: list[str]) -> list[str]:
    """켠 작업을 **실행 순서 그대로** 위에, 나머지는 카탈로그 순서로 아래에.

    보이는 순서가 곧 실행 순서라고 화면이 약속하므로, 레시피를 고른 뒤 그
    레시피의 순서가 눈에 보여야 한다. 카탈로그에 없는 id 는 버린다(그건
    `unmatched_steps()` 가 따로 알린다).
    """
    known = [i for i in checked_ids if i in all_ids]
    return [*known, *(i for i in all_ids if i not in known)]


def toggle_file_key(excluded: set[str], key: str, checked: bool) -> set[str]:
    """파일 하나의 체크를 바꾼 뒤의 '뺀 파일' 묶음.

    열쇠는 **원본 파일 경로**라, 한 파일이 두 줄로 보여도(사슬로 두 번 옮겨짐,
    zip 하나에서 여러 줄) 하나를 끄면 같은 열쇠의 줄이 **전부** 꺼진다.
    열쇠가 빈 줄(폴더 생성)은 뺄 수 있는 대상이 아니므로 아무 일도 안 한다.
    """
    out = set(excluded)
    if not key:
        return out
    out.discard(key) if checked else out.add(key)
    return out


def row_checks(rows, excluded: set[str]) -> list:
    """줄마다 체크박스 상태. `None` 이면 체크박스를 두지 않는다.

    체크 상태를 줄이 아니라 **열쇠**로 정하기 때문에, 같은 파일에서 나온 줄들은
    자동으로 같은 상태가 된다.
    """
    return [None if not r.key else (r.key not in excluded) for r in rows]


def _raw_kind(label: str) -> str:
    """"이동" → "move". 탭(원래 이름)과 표(이름표)를 맞대려면 한 번 되짚어야 한다."""
    return _RAW_KIND.get(label, label)


def kind_tabs(counts: dict) -> list[tuple[str, str, int]]:
    """(종류, 이름표, 개수). 0 건인 종류는 탭을 만들지 않는다.

    **종류를 합쳐 세지 않는다.** 특히 폴더 생성은 파일이 아니다.
    """
    return [(kind, KIND_LABEL.get(kind, kind), counts.get(kind, 0))
            for kind in _KIND_TABS if counts.get(kind, 0)]


def control_locks(*, busy: bool, can_preview: bool, can_apply: bool, can_undo: bool,
                  has_recipes: bool, has_targets: bool) -> dict[str, bool]:
    """지금 **무엇을 누를 수 있는가**. 켜짐/꺼짐을 정하는 곳은 여기 하나다.

    창의 `_sync_buttons` 는 이 표를 위젯에 바르기만 한다. 잠그는 판단이 여러
    곳에 흩어지면 하나를 빠뜨리는 순간 그 조작만 결함으로 남는다 — 실제로
    버튼 셋만 잠그고 대상 드롭다운을 열어 둔 탓에, 실행이 도는 3초 사이에
    대상을 바꾸면 화면은 다운로드를 가리키는데 되돌아가는 것은 바탕화면이었다.

    **일이 도는 동안(`busy`)은 전부 꺼진다.** 세 버튼만이 아니라 대상·레시피·
    작업 체크박스·▲▼·[저장]·[설정 · 폴더 위치] 링크까지다. 도는 동안 바뀔 수
    있는 것이 하나라도 남으면, 끝난 뒤 화면이 말하는 것과 실제로 벌어진 일이
    갈라진다. 링크만 열어 뒀더니 미리보기가 도는 중에 화면 3 으로 들어가
    **정리 중인 바로 그 대상의 등록을 [지우기] 로 지울 수 있었다.** 실측했다.

    `busy` 가 아닐 때 켜지는 근거는 **오직 세션의 `can_*`** 와 "고를 것이
    있는가" 다. 드롭다운은 항목이 없으면 눌러도 빈 메뉴가 뜰 뿐이다.
    """
    살아있음 = not busy
    return {
        "preview": 살아있음 and can_preview,
        "apply": 살아있음 and can_apply,
        "undo": 살아있음 and can_undo,
        "save": 살아있음,
        "recipe": 살아있음 and has_recipes,
        "target": 살아있음 and has_targets,
        "steps": 살아있음,        # 작업 체크박스
        "order": 살아있음,        # ▲▼
        "settings": 살아있음,     # [설정 · 폴더 위치] 링크 — 여기서 대상을 지울 수 있다
    }


def undo_label(root, targets: dict) -> str:
    """되돌릴 폴더를 **사람이 부르는 이름**으로. 등록된 이름이 있으면 그것.

    확인 대화상자에 경로만 적으면 `C:\\Users\\...\\Desktop` 이 무엇인지 한 번 더
    읽어야 한다. 드롭다운에 보이던 그 이름("바탕화면")을 그대로 쓴다.
    """
    if root is None:
        return ""
    for info in targets.values():
        if getattr(info, "path", None) == root:
            return info.label
    return Path(root).name or str(root)


def undo_prompt(label: str, root) -> str:
    """[되돌리기] 확인 대화상자에 적을 말.

    **되돌릴 대상이 무엇인지 글자로 보이는 것이 목적이다.** 되돌리기는
    사용자의 마지막 안전줄이라 어렵게 만들지 않는다 — 확인 한 번이면 된다.
    """
    이름 = f"「{label}」의" if label else "이 폴더의"
    return (f"{이름} 마지막 정리를 되돌립니다.\n\n"
            f"  {_short(Path(root))}\n\n"
            "계속할까요?")


def keeps_preview(before, after, can_apply: bool) -> bool:
    """설정을 바꾼 **뒤** — 지금 표와 [실행] 을 그대로 둘 수 있는가.

    **둘 다여야 한다.**
      · 세션이 말하는 설정(`before`/`after` 지문)이 그대로일 것.
      · 세션이 여전히 실행할 수 있다고 말할 것(`can_apply`).

    앞만 보면, 같은 값을 다시 골라 세션이 조용히 버린 계획을 표가 계속
    보여준다. 뒤만 보면, 도는 중(can_apply=False)에 같은 값을 다시 고른 것까지
    "바뀌었다" 로 읽어 멀쩡한 미리보기를 버린다.
    """
    return before == after and can_apply


def foot_text(counts: dict, skipped: int, hidden: int = 0) -> str:
    """표 아래 **항상 보이는** 줄에 적을 말.

    잘렸다는 안내가 여기 있어야 한다. 표 맨 끝에 두면 250줄일 때 4233px 중 맨
    아래라 200줄을 내려야 보이고, 못 본 사람은 "전부 봤다" 고 믿고 [실행] 을
    누른다. 그래서 **잘린 이유를 맨 앞에** 적는다.
    """
    말 = []
    if hidden:
        말.append(f"⚠ 이 탭의 {hidden}줄은 표에 그리지 않았습니다 — 너무 많으면"
                 " 창이 멈춥니다. 탭 숫자와 아래 개수는 안 그린 줄까지 다 셉니다.")
    말.append(f"손대지 않음 {skipped}개 (여기에 뺀 파일도 들어갑니다).")
    if counts.get("extract"):
        # 누를 수 없는 이유를 모르면 고장으로 읽힌다.
        말.append("압축 안에서 나올 파일에는 체크박스가 없습니다 — 아직 디스크에"
                 " 없어서 뺄 수가 없습니다. 빼려면 그 압축 파일의 체크를 끄세요.")
    if counts.get("mkdir"):
        말.append("폴더 생성은 파일이 아니라 따로 셉니다.")
    return "  ".join(말)


def dest_text(dest: str, root) -> str:
    """표 오른쪽에 적을 도착 자리.

    정리 대상 폴더 안이면 **거기서부터의 상대 경로**만 보여준다 — 줄마다 같은
    앞머리를 반복하면 정작 다른 부분(어느 폴더로 가는가)이 안 보인다.
    """
    if not dest:
        return ""
    if root is not None:
        try:
            return str(Path(dest).relative_to(root))
        except ValueError:
            pass                      # 밖으로 나가는 줄이다 — 전체 경로를 보여준다
    return _short(Path(dest))


def openable(info) -> bool:
    """이 줄의 폴더를 탐색기로 **열 수 있는가**. 화면 1·3 이 같이 쓴다.

    **비어 있는 폴더도 연다** — 오히려 그때 열어 봐야 "여기가 맞나" 를 확인할
    수 있다(OneDrive 백업이 켜진 PC 는 진짜 바탕화면이 다른 곳이라 0 으로 뜬다).
    권한 때문에 못 읽는 폴더도 연다 — 탐색기에서 고치라고 보내는 자리다.

    **못 여는 곳을 링크로 그리지 않으려고** 있는 함수다. 눌러도 아무 일이 없는
    링크는 "안 열리는구나" 가 아니라 "도구가 고장났구나" 로 읽힌다.
    """
    if not getattr(info, "path", None):
        return False
    # 어디인지 모르는 줄(UNRESOLVED)과 그 폴더가 없는 줄만 못 연다.
    return info.status not in (folders.UNRESOLVED, "폴더 없음")


# ── 화면 3 이 쓰는 것 (역시 위젯을 모른다) ───────────────────────

# 설정 화면의 경로 칸 길이. 표 기본값(56)보다 짧다 — 오른쪽에 상태 글자와
# 버튼 둘이 더 붙어서, 길면 서로 밀고 들어온다(실측: 캡처에서 그렇게 됐다).
_PLACE_PATH = 46

# 별칭 이름 → 사람이 부르는 이름. `folders.LABEL` 그대로다(표를 두 벌 만들지 않는다).
LABEL_OF = folders.LABEL


class Place(NamedTuple):
    """설정 화면의 위치 한 줄. **무엇을 적을지만 정한다** — 그리는 일은 창이 한다."""
    name: str        # 별칭 이름 ("desktop" · "백업")
    label: str       # 화면에 보일 이름 ("바탕화면" · "백업")
    path: str        # 보여줄 경로 글자(길면 가운데를 접은 것)
    note: str        # 오른쪽에 적을 말. 문제 없으면 "정상" 또는 빈 칸
    alert: bool      # 빨갛게 + [다시 지정] 을 붙일 줄인가
    pinned: bool     # 이 PC 에서 직접 지정한 것인가(config.local.json 에 있는가)
    # 탐색기로 열 **진짜 경로**. 빈 글자면 링크로 만들지 않는다.
    # `path` 는 가운데를 접은 **보여주기용 글자**라 그걸로는 열 수 없다 —
    # 둘을 하나로 쓰면 긴 경로에서만 안 열리는, 찾기 어려운 결함이 된다.
    open_path: str = ""


def name_width(labels) -> int:
    """설정 화면의 이름 칸을 **몇 글자폭**으로 잡을까.

    tkinter 의 `width` 는 **영문 글자폭** 기준이라 한글은 한 글자가 두 칸쯤
    먹는다. 12 로 못 박아 뒀더니 「백업드라이브」(6자 = 12칸)가 딱 걸려 뒤가
    잘리고 옆 경로와 붙어 보였다. 숫자를 조금 키우는 것으로는 같은 일이 더 긴
    이름에서 다시 난다 — **그 목록에서 가장 긴 이름**에 맞춘다.

    이름은 사용자가 지은 것이라 자르면 안 된다. 대신 `_PLACE_PATH` 로 이미
    접혀 있는 경로 쪽이 자리를 내준다.
    """
    def 폭(s: str) -> int:
        # U+2E80 위쪽은 한글·한자·이모지 — 폭이 대략 두 배다.
        return sum(2 if ord(c) > 0x2E80 else 1 for c in s)

    return max([12, *(폭(str(l)) for l in labels)])


def place_path_width(labels) -> int:
    """경로를 **몇 글자로 접을까**. 이름 칸이 넓어진 만큼 경로가 자리를 내준다.

    한 줄의 가로폭은 정해져 있다. 이름을 안 자르기로 했으니(`name_width`)
    누군가는 자리를 내줘야 하는데, **경로가 그쪽이다** — 가운데를 접어도
    앞(드라이브)과 끝(폴더 이름)은 남아서 알아볼 수 있기 때문이다.

    이걸 안 하면 「외장하드백업드라이브」를 등록한 순간 그 칸의 **모든 줄에서**
    경로 끝이 한두 글자씩 잘린다(실측: 캡처에서 'Archive' 가 'Archiv' 로 났다).
    """
    남는것 = _PLACE_PATH - max(0, name_width(labels) - 12)
    return max(24, 남는것)      # 너무 접으면 앞뒤 조각마저 사라진다


def local_place_names(repo_root: Path) -> set[str]:
    """`config.local.json` 에 적힌 별칭 이름들 — **이 화면에서 지울 수 있는 것.**

    `config.default.json` 은 저장소 공용 파일이라 이 PC 의 [지우기] 가 건드릴
    대상이 아니다. 구분하지 않으면 눌러도 아무 일이 없는 버튼이 생긴다.
    설정이 깨져 있으면 빈 묶음을 준다 — 무엇이 잘못됐는지는 `load_config` 가
    한국어로 알린다. 여기서 같은 말을 두 번 하지 않는다.
    """
    path = repo_root / "config.local.json"
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    paths = data.get("paths") if isinstance(data, dict) else None
    return set(paths) if isinstance(paths, dict) else set()


def builtin_places(infos, pinned: set[str]) -> list[Place]:
    """'자동으로 찾은 위치' 칸. **정상이면 조용히 둔다.**

    `home` 은 뺀다 — 홈 전체는 정리 대상이 아니고, 목록에 두면 겁만 준다.
    """
    # 접을 길이는 **이 칸 전체**를 보고 정한다. 줄마다 따로 정하면 같은 칸의
    # 경로들이 서로 다른 자리에서 접혀 목록으로 안 읽힌다.
    쓸것 = [i for i in infos if i.builtin and i.name != "home"]
    접을길이 = place_path_width([i.label for i in 쓸것])
    out = []
    for info in 쓸것:
        if info.hidden_duplicate_of:
            # 개수와 대상 목록에서는 뺀 줄이다(같은 폴더를 두 번 셀 이유가 없다).
            # **여기서까지 빼면 이름이 조용히 사라진다** — 그러면 [기본 위치로]
            # 도 같이 사라져 창만으로는 되돌릴 방법이 없다. 실측한 결함이다.
            # 잘못된 상태는 아니므로 빨갛게 하지 않고, 회색으로 이유만 적는다.
            먼저 = LABEL_OF.get(info.hidden_duplicate_of, info.hidden_duplicate_of)
            out.append(Place(name=info.name, label=info.label,
                             path=_short(info.path, 접을길이),
                             note=f"「{먼저}」와 같은 폴더입니다 — 한 번만 셉니다",
                             alert=False, pinned=info.name in pinned,
                             open_path=str(info.path) if openable(info) else ""))
            continue
        문제 = _문제인가(info)
        # 이름이 안 풀린 줄은 경로 자리에 적을 것이 없다 — `custom_places` 와
        # 같은 모양으로 '—' 를 두고 자리를 이유에 내준다(안 그러면 긴 이유가
        # 경로 칸을 밀어 '@d' 처럼 잘린 글자만 남는다. 실측: 캡처에서 그렇게 됐다).
        경로 = "—" if info.status == folders.UNRESOLVED else _short(info.path, 접을길이)
        out.append(Place(name=info.name, label=info.label, path=경로,
                         note=_why(info) if 문제 else "정상",
                         alert=문제, pinned=info.name in pinned,
                         open_path=str(info.path) if openable(info) else ""))
    return out


def custom_places(cfg, pinned: set[str]) -> list[Place]:
    """'내가 추가한 위치' 칸.

    **내장 이름은 여기에 다시 적지 않는다** — 위 칸에 이미 나온 줄이다
    (`organize paths` 가 같은 줄을 두 번 찍던 것과 같은 문제).

    **폴더가 없다고 등록을 지우지 않는다.** USB·SD카드는 안 꽂혀 있을 수 있다.
    """
    이름들 = [n for n in sorted(cfg.paths) if n not in BUILTIN]
    접을길이 = place_path_width(이름들)
    out = []
    for name in 이름들:
        try:
            path = resolve_alias(f"@{name}", cfg)
        except AliasNotDefined as e:
            # 돌고 도는 별칭. 목록 전체가 죽는 것보다 그 줄에 이유를 적는 편이 낫다.
            out.append(Place(name, name, "—", e.message, True, name in pinned))
            continue
        있음 = path.is_dir()
        out.append(Place(name, name, _short(path, 접을길이),
                         "" if 있음 else "없음 · 다시 지정",
                         not 있음, name in pinned,
                         str(path) if 있음 else ""))
    return out


def new_place_error(name: str, cfg) -> str | None:
    """[+ 위치 추가] 로 받은 이름이 쓸 수 있는가. 못 쓰면 **한국어 이유**를 준다."""
    이름 = (name or "").strip()
    if not 이름:
        return "이름이 비어 있습니다."
    if 이름.startswith("@"):
        return "이름 앞에 @ 를 붙이지 마세요 — 쓸 때만 '@백업' 처럼 붙입니다."
    if "/" in 이름 or "\\" in 이름:
        # `@백업/사진` 의 뒷부분과 구분이 안 된다 — 등록해도 영영 안 풀린다.
        return "이름에 / 나 \\ 를 쓸 수 없습니다."
    if 이름 in BUILTIN:
        # **cfg.paths 만 보면 안 된다.** 내장 이름은 아직 cfg.paths 에 없으므로
        # 위 검사를 그대로 통과하는데, 저장하면 `resolve_alias` 가 사용자 값을
        # 먼저 보기 때문에 **그 내장 폴더가 조용히 그리로 옮겨간다.** 화면에는
        # "저장했습니다" 라고 답하면서 '내가 추가한 위치' 에는 안 생기고,
        # 대신 '바탕화면' 줄의 경로가 바뀐다 — 사용자는 자기가 만든 이름이
        # 어디로 갔는지 알 방법이 없다. 다음 정리에서 **화면이 말한 폴더가
        # 아닌 폴더의 파일이 움직인다.** 실측한 결함이다.
        return (f"'{이름}' 은 이미 자동으로 찾은 위치 이름입니다 — 다른 이름을 쓰거나, "
                "'자동으로 찾은 위치' 칸의 [다시 지정] 으로 그 폴더를 바꿔 주세요.")
    if 이름 in cfg.paths:
        return f"'{이름}' 은 이미 있는 이름입니다 — 그 줄의 [찾아보기] 로 경로만 바꿀 수 있습니다."
    return None


def profile_folder_names(profiles_dir: Path) -> list[tuple[str, list[str], str]]:
    """프로파일이 **실제로 만드는** 폴더 이름. (보일 이름, 폴더들, 문제).

    설정의 `folder_names` 는 **엔진이 읽지 않는다.** 편집 화면을 만들면
    "바꿨는데 안 바뀐다" 가 된다 — 그래서 못 바꾸는 것을 바꿀 수 있는 것처럼
    그리지 않고, 지금 실제로 쓰이는 이름을 읽기 전용으로 보여준다.
    """
    out: list[tuple[str, list[str], str]] = []
    for path in sorted(profiles_dir.glob("*.toml")):
        try:
            profile = profiles.load_profile(path)
        except OrganizeError:
            # 조용히 빼면 사용자는 그 프로파일이 없는 줄 안다.
            out.append((path.stem, [], "이 파일을 읽지 못했습니다 — organize list 로 확인해 주세요."))
            continue
        이름들: list[str] = []
        for rule in profile.rules:
            if rule.to and rule.to not in 이름들:
                이름들.append(rule.to)
        out.append((profile.name, 이름들, ""))
    return out


def run(repo_root: Path) -> int:
    """창을 띄운다. 창을 못 띄우면 한국어로 알리고 1 을 돌려준다."""
    try:
        import tkinter                                    # noqa: F401
    except Exception:
        raise OrganizeError(
            "이 파이썬에서는 창을 띄울 수 없습니다 (tkinter 없음).",
            hint="윈도우 파이썬에는 기본으로 들어 있습니다. "
                 "리눅스라면 'sudo apt install python3-tk' 로 설치하세요.\n"
                 "    창 없이 쓰려면: organize preview <레시피>")
    app = App(repo_root)
    app.window.mainloop()
    return 0


class App:
    """위젯 묶음. 상태는 전부 `Session` 이 들고 있다."""

    def __init__(self, repo_root: Path) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk = tk, ttk
        self.repo_root = Path(repo_root)
        self.session = Session(repo_root)

        self.window = tk.Tk()
        self.window.title(_TITLES["first"])
        self.window.geometry("860x780")
        self.window.minsize(720, 620)
        theme.apply_theme(self.window)
        style = ttk.Style(self.window)
        # ▲▼ 는 [미리보기] 만 한 크기일 이유가 없다. 색은 손대지 않고 여백만
        # 줄인다(Ghost.TButton 을 물려받는다).
        style.configure("Tiny.Ghost.TButton", padding=(10, 3))
        # 꺼진 [미리보기] 가 켜진 것과 **같은 색**이면 세 버튼이 다 꺼졌다는 것을
        # 눈으로 알 수 없다(실측: 캡처에서 글자만 흐려질 뿐 파란 판은 그대로였다).
        # 원래 배경 규칙을 읽어 앞에 'disabled' 만 얹는다 — 눌림·닿음 색은
        # gui_theme 이 정한 그대로 남는다.
        style.map("Primary.TButton",
                  background=[("disabled", theme.SUNKEN),
                              *style.map("Primary.TButton", "background")])

        self.status_var = tk.StringVar(value="")
        self.current = "first"
        self._counted = False                  # 폴더를 이미 세었는가
        self._pending_counts = 0               # 아직 안 돌아온 세기 작업 수
        self._count_summary = ""
        self._infos: list = []                 # 마지막으로 센 결과. 화면 3 도 이것을 본다
        self._inbox: queue.SimpleQueue = queue.SimpleQueue()

        # ── 화면 2 가 들고 있는 것 ────────────────────────────────
        self._jobs: queue.SimpleQueue = queue.SimpleQueue()
        self._busy = False              # 미리보기·실행이 도는 중인가
        # 설정이 바뀔 때마다 올라가는 번호. 미리보기를 띄울 때 지금 번호를 같이
        # 넘겨, 결과가 돌아왔을 때 번호가 다르면 그 결과를 **버린다.** 도는
        # 동안 사용자를 60초 묶어 두는 대신 낡은 결과를 버리는 쪽을 골랐다.
        self._generation = 0
        self.entries = catalog.catalog()
        self.step_order = [e.id for e in self.entries]     # 보이는 순서 = 실행 순서
        self.step_selected: str | None = None              # ▲▼ 가 다룰 줄(체크와 다르다)
        self.step_vars: dict = {}
        self.step_rows: dict = {}
        self.targets: dict = {}         # 드롭다운 글자 → FolderInfo
        self.view = None                # 마지막 미리보기 결과(PreviewView)
        self.tab_kind: str | None = None

        # 무슨 일이 있었는지 적는 줄. 오류·진행 상황이 여기 남는다 — 창을 닫고
        # 나서야 알게 되는 일이 없도록.
        # **화면보다 먼저 자리를 잡는다.** 나중에 붙이면 내용이 길어졌을 때
        # 이 줄이 창 밖으로 밀려 반쯤 잘린다(실측: 캡처에서 그렇게 됐다).
        ttk.Label(self.window, textvariable=self.status_var,
                  style="Muted.TLabel", anchor="w").pack(side="bottom", fill="x",
                                                         padx=26, pady=(0, 10))

        body = ttk.Frame(self.window)
        body.pack(fill="both", expand=True)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        # 화면 셋을 같은 자리에 겹쳐 둔다. 바꿀 때는 tkraise() 만 한다.
        self.frames = {}
        for name, build in (("first", self._build_first),
                            ("main", self._build_main),
                            ("settings", self._build_settings)):
            frame = ttk.Frame(body, padding=(24, 20))
            frame.grid(row=0, column=0, sticky="nsew")
            self.frames[name] = frame
            build(frame)

        # 설정이 이미 있으면 첫 화면을 건너뛴다(시안: "설정이 이미 있으면 이 화면을 건너뛴다").
        self.show("main" if (self.repo_root / "config.local.json").is_file() else "first")

    # ── 화면 바꾸기 ──────────────────────────────────────────────
    def show(self, name: str) -> None:
        """화면 하나를 올린다. "first" | "main" | "settings"."""
        if name not in self.frames:
            raise OrganizeError(f"그런 화면이 없습니다: {name}",
                                hint=f"쓸 수 있는 이름: {', '.join(_SCREENS)}")
        self.frames[name].tkraise()
        self.window.title(_TITLES[name])
        self.current = name
        if name in ("first", "main"):
            # 화면 1 은 개수를, 화면 2 는 대상 드롭다운 목록을 이 결과로 채운다.
            # 한 번만 센다 — 두 화면이 같은 것을 두 번 세면 숫자가 갈릴 수 있다.
            self._start_counting()
        if name == "first" and self._count_summary:
            self.status_var.set(self._count_summary)      # 이미 센 결과를 되살린다
        if name == "main":
            self._sync_buttons()
        if name == "settings":
            # 들어올 때마다 다시 센다 — 명령줄에서 위치를 바꿨거나 USB 를 꽂았을
            # 수 있다. 이 화면은 "무엇이 잘못됐는가" 를 보러 오는 곳이다.
            self._start_counting(force=True)
            self._fill_settings()

    # ── 화면 1 — 처음 실행 ───────────────────────────────────────
    def _build_first(self, parent) -> None:
        ttk = self.ttk
        self._header(parent, "처음 실행")

        ttk.Label(parent, text="폴더 위치를 자동으로 찾았습니다.",
                  style="Lead.TLabel").pack(anchor="w", pady=(14, 2))
        ttk.Label(parent, text="파일 개수가 맞는지 봐 주세요. 개수가 0 이면 다른 곳일 수 있습니다.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 12))

        # **버튼을 먼저 바닥에 붙인다.** 나중에 붙이면 목록이 길어졌을 때
        # 버튼이 창 밖으로 밀려 잘린다(실측: 캡처에서 반쯤 잘려 나갔다).
        # 아래에서 위로 — 버튼줄, 안내줄, 그리고 남는 자리를 목록이 갖는다.
        아래 = ttk.Frame(parent)
        아래.pack(side="bottom", fill="x", pady=(16, 0))
        ttk.Label(아래, text="이 위치가 맞나요?", style="Lead.TLabel").pack(side="left")
        # 버튼을 이름으로 들고 있는다 — 눌렀을 때 실제로 화면이 바뀌는지
        # 밖에서 확인할 수 있어야 한다(invoke). 다음 Task 도 이 이름을 쓴다.
        self.btn_pick = ttk.Button(아래, text="직접 고를게요", style="Ghost.TButton",
                                   command=lambda: self._go("settings"))
        self.btn_pick.pack(side="right")
        self.btn_start = ttk.Button(아래, text="맞아요, 시작", style="Primary.TButton",
                                    command=lambda: self._go("main"))
        self.btn_start.pack(side="right", padx=(0, 10))

        # 문제 있는 줄이 있을 때만 보이는 안내. 같은 문장을 줄마다 반복하면
        # 여섯 줄이 같은 빨간 글로 뒤덮여 아무도 안 읽는다(실측: 캡처로 확인).
        # 줄 옆에는 짧은 이유만, 왜 그런지는 여기 한 번만 적는다.
        self._alert_note = ttk.Label(
            parent, style="Alert.TLabel", wraplength=700, justify="left",
            text=f"표시된 줄은 비어 있거나 폴더가 없습니다 — {_ONEDRIVE}\n"
                 "[직접 고를게요] 에서 위치를 직접 지정할 수 있습니다.")

        self.folder_card = self._card(parent)
        self.folder_card.pack(fill="both", expand=True)
        self.folder_card.columnconfigure(0, weight=1)
        self._folder_note("폴더를 세는 중입니다…")

    def _go(self, name: str) -> None:
        """버튼이 실제로 화면을 바꾼다. **눌러도 아무 일이 없으면 그게 결함이다.**"""
        with self._reporting("화면 바꾸기"):
            self.show(name)
            self.status_var.set("")

    # ── 폴더 개수 세기 (창이 멈추면 안 된다) ─────────────────────
    def _start_counting(self, *, force: bool = False) -> None:
        """세는 일은 딴 스레드에서. 진짜 다운로드 폴더는 파일이 많고 WSL 은 느리다.

        `force` 는 **설정에서 위치를 바꾼 뒤**에 쓴다. 다시 세지 않으면 방금
        지정한 폴더가 화면 1·대상 드롭다운·설정 화면에 옛 값으로 남는다.
        """
        if self._counted and not force:
            return
        self._counted = True
        self._pending_counts += 1
        threading.Thread(target=self._count_worker, daemon=True).start()
        # 결과는 **주 스레드**가 꺼내 간다. 딴 스레드가 위젯을 건드리면
        # tkinter 는 조용히 이상해지거나 죽는다.
        # 꺼내는 고리는 **하나만** 돈다 — 두 번 세면 고리가 둘이 되어, 하나는
        # 영영 빈 상자를 들여다보며 80ms 마다 깨어난다.
        if self._pending_counts == 1:
            self.window.after(80, self._drain)

    def _count_worker(self) -> None:
        """디스크를 읽는 부분. 위젯을 하나도 건드리지 않는다."""
        try:
            # 홈은 뺀다 — 홈 전체 파일 개수는 정리 대상이 아니고, 숫자가 크면
            # 겁만 준다. 나머지는 다 싣는다: 화면 1 은 내장만 골라 쓰고,
            # 화면 2 의 대상 드롭다운은 등록한 이름까지 필요하다.
            # 화면 3 은 dedup 으로 뺀 줄까지 받아야 "왜 안 보이는지" 를 말할 수
            # 있다. 개수·대상 목록에서 거르는 일은 `folders.visible()` 이 한다.
            infos = [f for f in folders.overview(load_config(self.repo_root))
                     if f.name != "home"]
            self._inbox.put(("ok", infos))
        except Exception as e:                   # noqa: BLE001 — 창은 살아 있어야 한다
            self._inbox.put(("fail", e))

    def _drain(self) -> None:
        try:
            kind, payload = self._inbox.get_nowait()
        except queue.Empty:
            self.window.after(80, self._drain)   # 아직이다. 다시 본다.
            return
        self._pending_counts = max(0, self._pending_counts - 1)
        if kind == "ok":
            self._infos = payload
            보일것 = folders.visible(payload)
            self._fill_folders([f for f in 보일것 if f.builtin])
            self._fill_targets(보일것)
            self._fill_settings()          # 화면 3 만은 뺀 줄까지 받는다
        else:
            self._folder_note("폴더를 세지 못했습니다.")
            self.target_var.set(_NO_TARGET)
            self._report("폴더 세기", payload)
        if self._pending_counts:
            self.window.after(80, self._drain)   # 다시 세라고 시킨 것이 남아 있다

    def _folder_note(self, text: str) -> None:
        """화면 1 의 판을 비우고 한 줄만 적는다("세는 중" · "못 셌습니다").

        판을 비우지 않으면 다시 셀 때마다 같은 줄이 아래에 쌓인다.
        """
        for w in self.folder_card.winfo_children():
            w.destroy()
        self.ttk.Label(self.folder_card, text=text, style="CardPath.TLabel",
                       ).grid(row=0, column=0, sticky="w", padx=16, pady=16)

    def _fill_folders(self, infos) -> None:
        ttk = self.ttk
        # 다시 셀 때가 있다(설정에서 위치를 바꾼 뒤). 지우지 않으면 같은 줄이
        # 아래에 계속 쌓인다.
        for w in self.folder_card.winfo_children():
            w.destroy()
        self._alert_note.pack_forget()      # 이번 결과에 문제가 없으면 옛 경고가 남으면 안 된다
        for r, info in enumerate(infos):
            if r:                                 # 줄 사이 얇은 선 — Finder 의 목록 느낌
                ttk.Frame(self.folder_card, style="Line.TFrame", height=1).grid(
                    row=r * 2 - 1, column=0, sticky="ew", padx=16)
            self._folder_row(self.folder_card, info).grid(
                row=r * 2, column=0, sticky="ew", padx=16, pady=9)
        문제수 = sum(1 for f in infos if _문제인가(f))
        if 문제수:
            self._alert_note.pack(side="bottom", fill="x", pady=(10, 0))
        self._count_summary = (f"폴더 {len(infos)}곳을 확인했습니다."
                               + (f"  그중 {문제수}곳은 비어 있거나 없습니다."
                                  if 문제수 else ""))
        if self.current == "first":
            # 화면 2 에서 시작했다면 여기 결과는 드롭다운을 채우는 데만 쓴다.
            # 그때 이 문장을 쓰면 사용자가 방금 누른 것의 결과를 덮어쓴다.
            self.status_var.set(self._count_summary)

    def _folder_row(self, parent, info):
        """한 줄: 이름 · 꼬리 경로 · 전체 경로(눌러서 열기) · 개수(크게)."""
        ttk = self.ttk
        row = ttk.Frame(parent, style="Card.TFrame")
        # 이름 칸은 **줄마다 같은 자리에서 끝나되 글자를 자르지 않는다.**
        # 예전에는 `width=7`(영문 7자폭)로 못 박았는데 한글 4자가 그보다 넓어
        # 「바탕화면」·「다운로드」의 뒤가 잘리고 옆 경로와 붙어 보였다. 칸의
        # **최소폭**만 정하고, 오른쪽 여백으로 경로와 떼어 놓는다.
        row.columnconfigure(0, minsize=100)
        row.columnconfigure(1, weight=1)

        ttk.Label(row, text=info.label, style="CardName.TLabel", anchor="w",
                  ).grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Label(row, text=_tail(info.path), style="CardPath.TLabel",
                  ).grid(row=0, column=1, sticky="w")

        문제 = _문제인가(info)
        ttk.Label(row, text=("—" if info.count is None else str(info.count)),
                  style="CardAlertCount.TLabel" if 문제 else "CardCount.TLabel",
                  anchor="e", width=5).grid(row=0, column=2, rowspan=2,
                                            sticky="e", padx=(12, 0))

        # 전체 경로를 **눌러서 여는 링크**로. 글자만 봐서는 그 폴더가 내가 아는
        # 그 폴더인지 알 수 없다 — 열어 봐야 안다. 개수가 0 인 줄이야말로 그렇다.
        self._path_link(row, text=_short(info.path), size=8,
                        folder=str(info.path) if openable(info) else "",
                        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(1, 0))
        if 문제:
            ttk.Label(row, text=_why(info), style="CardAlert.TLabel",
                      wraplength=480, justify="left",
                      ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(3, 0))
        return row

    # ── 화면 2 — 메인 ────────────────────────────────────────────
    def _build_main(self, parent) -> None:
        """레시피·대상·작업·미리보기 표.

        **경로 입력창도 [찾아보기] 도 없다.** 대상은 이름 드롭다운이다 — 시안의
        핵심 문장이 "경로를 칠 일이 없다" 이고, 탐색기는 화면 3 에서만 쓴다.
        """
        tk, ttk = self.tk, self.ttk
        머리 = self._header(parent, "organize")
        # **변수로 들고 있는다.** 이 링크도 도는 동안 꺼야 하는데, 붙잡아 두지
        # 않으면 끌 방법이 없다(▲▼ 가 남았던 것과 같은 이유다).
        self.btn_settings = ttk.Button(머리, text="설정 · 폴더 위치", style="Link.TButton",
                                       command=lambda: self._go("settings"))
        self.btn_settings.pack(side="right")

        # ── 레시피 · 대상 ─────────────────────────────────────
        위 = ttk.Frame(parent)
        위.pack(fill="x", pady=(14, 0))
        위.columnconfigure(2, weight=1)          # 가운데를 비워 [저장] 을 오른쪽 끝으로

        ttk.Label(위, text="레시피", width=6).grid(row=0, column=0, sticky="w")
        self.recipe_var = tk.StringVar(value=_NO_RECIPE)
        self.recipe_menu = self._dropdown(위, self.recipe_var)
        self.recipe_menu.grid(row=0, column=1, sticky="w")
        self.btn_save = ttk.Button(위, text="저장", style="Ghost.TButton",
                                   command=self._save_recipe)
        self.btn_save.grid(row=0, column=3, sticky="e", padx=(10, 0))

        ttk.Label(위, text="대상", width=6).grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.target_var = tk.StringVar(value=_LOADING)
        self.target_menu = self._dropdown(위, self.target_var)
        self.target_menu.grid(row=1, column=1, sticky="w", pady=(8, 0))

        # 레시피에 목록에 없는 작업이 섞여 있을 때만 보이는 줄. **조용히 넘어가지
        # 않는다** — 체크 하나를 건드리는 순간 그 작업들이 빠지는데, 미리 말해
        # 주지 않으면 사용자가 알 방법이 없다.
        self.unmatched_note = ttk.Label(위, style="Faint.TLabel", wraplength=780,
                                        justify="left")
        self.unmatched_note.grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.unmatched_note.grid_remove()

        # ── 설정(작업 체크박스) ───────────────────────────────
        ttk.Label(parent, text="설정", style="Lead.TLabel").pack(anchor="w", pady=(14, 4))
        판 = self._card(parent)
        판.pack(fill="x")
        self.step_box = tk.Frame(판, bg=theme.SURFACE)
        self.step_box.pack(fill="x", padx=12, pady=(10, 2))

        순서줄 = tk.Frame(판, bg=theme.SURFACE)
        순서줄.pack(fill="x", padx=12, pady=(0, 10))
        tk.Label(순서줄, text="선택한 작업 ▲▼ 순서 변경", bg=theme.SURFACE,
                 fg=theme.MUTED, font=theme.body_font(9)).pack(side="left")
        # **변수로 들고 있는다.** `_sync_buttons` 가 도는 동안 이 둘도 꺼야 하는데,
        # 붙잡아 두지 않으면 끌 방법이 없다(이것이 이번 결함이 남은 이유다).
        self.btn_down = ttk.Button(순서줄, text="▼", style="Tiny.Ghost.TButton", width=3,
                                   command=lambda: self._move_step(1))
        self.btn_down.pack(side="right")
        self.btn_up = ttk.Button(순서줄, text="▲", style="Tiny.Ghost.TButton", width=3,
                                 command=lambda: self._move_step(-1))
        self.btn_up.pack(side="right", padx=(0, 6))

        # ── 세 버튼 ───────────────────────────────────────────
        줄 = ttk.Frame(parent)
        줄.pack(fill="x", pady=(14, 0))
        self.btn_preview = ttk.Button(줄, text="미리보기", style="Primary.TButton",
                                      command=self._do_preview)
        self.btn_preview.pack(side="left")
        self.btn_apply = ttk.Button(줄, text="실행", style="Ghost.TButton",
                                    command=self._do_apply)
        self.btn_apply.pack(side="left", padx=(10, 0))
        self.btn_undo = ttk.Button(줄, text="되돌리기", style="Ghost.TButton",
                                   command=self._do_undo)
        self.btn_undo.pack(side="left", padx=(10, 0))

        # ── 결과 ──────────────────────────────────────────────
        결과 = ttk.Frame(parent)
        결과.pack(fill="both", expand=True, pady=(12, 0))
        self.warn_box = ttk.Frame(결과)
        self.warn_box.pack(fill="x")
        self.tab_box = ttk.Frame(결과)
        self.tab_box.pack(fill="x", pady=(0, 6))
        # 아래 설명줄이 표보다 **먼저** 자리를 잡는다. 표는 늘어나는 쪽이라,
        # 나중에 붙이면 줄이 많을 때 설명줄이 창 밖으로 밀려 잘린다.
        self.foot = ttk.Label(결과, style="Muted.TLabel", wraplength=800, justify="left")
        self.foot.pack(side="bottom", fill="x", pady=(6, 0))
        wrap, self.table_canvas, self.table_inner = self._table_area(결과)
        wrap.pack(fill="both", expand=True)

        # 화면과 세션이 처음부터 같은 것을 말하게 한다. 체크박스는 켜 놓고
        # 세션은 빈 채로 두면, 보이는 것과 실행되는 것이 처음부터 다르다.
        self._draw_steps()
        self._push_steps(quiet=True)
        self._refresh_recipes()
        self._clear_result("정리할 대상을 고르고 [미리보기] 를 눌러 주세요.")

    # ── 설정이 바뀌면 **반드시 여기를 지난다** ───────────────────
    def _settings_fingerprint(self) -> tuple:
        """미리보기가 무엇으로 세워지는지를 나타내는 지문.

        **세션이 말하는 것만 쓴다.** 창이 따로 기억하면 판단의 출처가 둘이 되고,
        어긋나는 순간 화면과 실행이 갈라진다.
        """
        s = self.session
        return (s.root, s.recipe_name, s.checked_ids(), s.unmatched_steps(),
                sorted(s.excluded_keys()))

    def _after_change(self, before: tuple, note: str | None) -> bool:
        """설정을 바꾼 **뒤** 부른다. 진짜 바뀌었으면 미리보기를 무효로 만든다.

        **세대를 올리는 자리는 여기 하나뿐이다.** 대상·체크·▲▼·레시피·파일
        빼기가 전부 여기를 지나야, 도는 중인 미리보기가 끝나 옛 계획을 들고
        와도 화면에 반영되지 않는다(`_drain_jobs` 가 세대를 본다). 하나라도
        빠뜨리면 그 조작에서만 옛 계획으로 [실행] 이 되살아난다.

        `note` 가 None 이면 표를 그대로 둔다 — 파일 체크를 껐을 때는 곧바로
        미리보기를 다시 세우므로, 표를 비웠다가 다시 그리면 눈만 깜박인다.
        """
        after = self._settings_fingerprint()
        if keeps_preview(before, after, self.session.can_apply):
            return False              # 정말 아무것도 안 바뀌었다 — 표도 [실행] 도 그대로
        if after != before:
            self._generation += 1
        if note is not None:
            self._clear_result(note)
        self._sync_buttons()
        return True

    # ── 드롭다운 (ttk.Combobox 가 아니다) ────────────────────────
    def _dropdown(self, parent, var):
        """이름 드롭다운 하나.

        `ttk.Combobox` 가 아니라 `tk.Menubutton` 을 쓴다 — 항목 **하나만** 회색으로
        칠할 수 있는 것이 이것뿐이기 때문이다. 폴더가 없는 대상을 목록에서
        빼 버리면 사용자는 그 이름이 왜 사라졌는지 알 수 없다.
        """
        tk = self.tk
        mb = tk.Menubutton(parent, anchor="w", relief="flat", width=34,
                           bg=theme.SURFACE, fg=theme.TEXT,
                           activebackground=theme.ACCENT_BG, activeforeground=theme.TEXT,
                           disabledforeground=theme.FAINT,
                           font=theme.body_font(), padx=10, pady=5,
                           highlightthickness=1, highlightbackground=theme.LINE,
                           highlightcolor=theme.LINE, indicatoron=False, direction="below")
        # Tk 가 그리는 표시(작은 가로선)는 눌러서 펼치는 것으로 안 보인다.
        # 시안의 ▾ 를 글자로 붙인다 — 값(var)에는 섞지 않는다. 섞으면 고른 이름을
        # 되읽는 쪽이 화살표까지 이름으로 받는다.
        var.trace_add("write", lambda *_: mb.configure(text=f"{var.get()}   ▾"))
        mb.configure(text=f"{var.get()}   ▾")
        mb.dropdown = tk.Menu(mb, tearoff=0, bg=theme.SURFACE, fg=theme.TEXT,
                              activebackground=theme.ACCENT_BG,
                              activeforeground=theme.TEXT, bd=0,
                              font=theme.body_font())
        mb.configure(menu=mb.dropdown)
        mb.has_items = False        # `_sync_buttons` 가 읽는다. 아직 못 채웠다
        return mb

    def _fill_dropdown(self, mb, items) -> None:
        """(글자, 누르면 할 일, 회색인가) 목록으로 메뉴를 다시 만든다.

        **여기서 켜고 끄지 않는다.** 고를 것이 있는지만 적어 두고, 실제로
        누를 수 있는지는 `_sync_buttons` 한 곳이 정한다 — 잠그는 판단이 두
        곳이면 일이 도는 중에 이 함수가 불리는 순간 잠금이 풀린다(대상 목록은
        폴더를 다 센 뒤 이렇게 채워진다).
        """
        menu = mb.dropdown
        menu.delete(0, "end")
        for i, (text, action, faint) in enumerate(items):
            menu.add_command(label=text, command=action)
            if faint:
                menu.entryconfigure(i, foreground=theme.FAINT)
        mb.has_items = bool(items)
        self._sync_buttons()

    # ── 레시피 ───────────────────────────────────────────────────
    def _refresh_recipes(self, select: str | None = None) -> None:
        with self._reporting("레시피 목록"):
            names = self.session.recipe_names()
        self._fill_dropdown(self.recipe_menu,
                            [(n, (lambda n=n: self._on_recipe(n)), False) for n in names])
        if select:
            self.recipe_var.set(select)
        elif not names:
            self.recipe_var.set(_NO_RECIPE_FILES)

    def _on_recipe(self, name: str) -> None:
        with self._reporting("레시피 고르기"):
            # `_follow_recipe_root` 가 대상까지 옮길 수 있으므로 **그 전에** 지문을
            # 뜬다. 레시피와 대상 중 하나라도 바뀌면 미리보기가 무효다.
            before = self._settings_fingerprint()
            self.session.set_recipe(name)
            self.recipe_var.set(name)
            self._sync_steps_from_session()
            옮김 = self._follow_recipe_root(name)
            말 = (f"레시피 '{name}' 을 불러왔습니다."
                 + (f"  대상을 {옮김} 으로 옮겼습니다." if 옮김 else "")
                 + "  [미리보기] 를 눌러 주세요.")
            # 같은 레시피를 다시 고른 것뿐이면 표도 [실행] 도 건드리지 않는다.
            if not self._after_change(before, 말):
                self.status_var.set(f"레시피 '{name}' 은 이미 고른 것입니다"
                                    " — 미리보기를 그대로 둡니다.")
        self._sync_buttons()

    def _follow_recipe_root(self, name: str) -> str | None:
        """레시피의 `roots` 첫 번째가 풀리면 대상을 거기로 옮긴다.

        **조용히 바꾸지 않는다** — 드롭다운 글자가 같이 바뀌고, 옮겼다는 말을
        상태줄에 남긴다. 안 풀리는 이름이면 대상을 건드리지 않는다.
        """
        try:
            recipe = load_recipe(find_recipe(self.repo_root / "recipes", name))
            if not recipe.roots:
                return None
            path = resolve_alias(recipe.roots[0], load_config(self.repo_root))
        except (OrganizeError, AliasNotDefined, OSError):
            return None               # 못 풀면 그냥 둔다. 여기서 실패를 알릴 일은 아니다
        for text, info in self.targets.items():
            if info.path == path:
                self._pick_target(text)
                return info.label       # 상태 꼬리표("— 폴더 없음")는 문장에 안 섞는다
        # 등록 목록에 없는 곳이라도 레시피가 가리키는 곳은 대상이 될 수 있다.
        # 그럴 때도 **글자로 보여야** 한다 — 안 보이면 조용히 바뀐 것과 같다.
        보일글자 = _short(path, 30)
        self.target_var.set(보일글자)
        self.session.set_root(path)
        return 보일글자

    def _save_recipe(self) -> None:
        name = self._ask_text("레시피 저장", "이 조합을 무슨 이름으로 저장할까요?",
                              example="예: 내 바탕화면 정리")
        if not name:
            # 알리지 않으면 상태줄에 직전 "저장했습니다" 가 남아, 방금 저장된
            # 것처럼 읽힌다.
            self.status_var.set("레시피 저장을 취소했습니다.")
            return
        with self._reporting("레시피 저장"):
            try:
                path = self.session.save_recipe(name)
            except OrganizeError:
                # 이미 있는 이름인가를 **파일로** 확인한다. 오류 문구를 글자로
                # 비교하면 문구가 바뀌는 날 조용히 안 물어보게 된다.
                있는것 = self.repo_root / "recipes" / f"{name.strip()}.json"
                if not 있는것.is_file():
                    raise
                if not self._confirm(
                        "레시피 저장",
                        f"'{name.strip()}' 레시피가 이미 있습니다. 덮어쓸까요?"):
                    self.status_var.set("저장하지 않았습니다.")
                    return
                path = self.session.save_recipe(name, overwrite=True)
            self._refresh_recipes(select=path.stem)
            self.status_var.set(f"레시피 '{path.stem}' 으로 저장했습니다.")

    # ── 대상 ─────────────────────────────────────────────────────
    def _fill_targets(self, infos) -> None:
        """대상 드롭다운을 채운다. **폴더가 없는 것도 목록에 남긴다**(회색으로)."""
        self.targets = {}
        items = []
        for info in infos:
            text = info.label if not info.status else f"{info.label} — {info.status}"
            self.targets[text] = info
            items.append((text, (lambda t=text: self._pick_target(t)), bool(info.status)))
        self._fill_dropdown(self.target_menu, items)
        if self.target_var.get() == _LOADING:
            self.target_var.set(_NO_TARGET if items else "(등록된 폴더 없음)")

    def _pick_target(self, text: str) -> None:
        info = self.targets.get(text)
        if info is None:
            return
        with self._reporting("대상 고르기"):
            if info.status == folders.UNRESOLVED:
                # 목록에는 남긴다(사라지면 고칠 방법도 사라진다) — 다만 어디인지
                # 모르는 곳을 정리 대상으로 삼을 수는 없다.
                raise OrganizeError(
                    f"'{info.label}' 이 어느 폴더인지 확인할 수 없어 대상으로 고를 수 없습니다.",
                    hint="[설정 · 폴더 위치] 에서 이 위치를 다시 지정해 주세요.")
            before = self._settings_fingerprint()
            self.session.set_root(info.path)
            self.target_var.set(text)
            # 같은 폴더를 다시 골랐으면 표도 [실행] 도 그대로 둔다. 무조건
            # 지우면 표만 비고 [실행] 은 켜진 채로 남아, 확인 대화상자의 요약이
            # 빈칸으로 뜬다.
            if not self._after_change(before, f"대상: {info.path}"):
                self.status_var.set(f"대상: {info.path}"
                                    "  — 이미 고른 대상입니다. 미리보기를 그대로 둡니다.")
        self._sync_buttons()

    # ── 작업 체크박스 + ▲▼ ──────────────────────────────────────
    def _sync_steps_from_session(self) -> None:
        """세션의 steps 를 체크박스에 그대로 옮긴다(레시피를 고른 뒤)."""
        켠것 = self.session.checked_ids()
        self.step_order = arrange_steps([e.id for e in self.entries], 켠것)
        self.step_selected = None
        self._draw_steps(checked=set(켠것))
        self._update_unmatched()

    def _update_unmatched(self) -> None:
        남은것 = self.session.unmatched_steps()
        if 남은것:
            self.unmatched_note.config(
                text=f"이 레시피에는 목록에 없는 작업 {len(남은것)}개가 있습니다"
                     " — 체크를 건드리면 그 작업은 빠집니다.")
            self.unmatched_note.grid()
        else:
            self.unmatched_note.grid_remove()

    def _draw_steps(self, checked: set | None = None) -> None:
        """작업 목록을 통째로 다시 그린다. 순서가 바뀌면 줄도 바뀌기 때문이다."""
        tk = self.tk
        옛것 = {i: v.get() for i, v in self.step_vars.items()}
        for w in self.step_box.winfo_children():
            w.destroy()
        self.step_vars, self.step_rows = {}, {}

        by_id = {e.id: e for e in self.entries}
        for entry_id in self.step_order:
            entry = by_id[entry_id]
            if checked is not None:      # 레시피를 골랐다 — 그 레시피가 정한다
                켬 = entry_id in checked
            elif entry_id in 옛것:        # 순서만 바뀌었다 — 체크는 그대로
                켬 = 옛것[entry_id]
            else:                        # 처음 그린다 — 카탈로그의 기본값
                켬 = entry.default_on
            var = tk.BooleanVar(value=켬)
            self.step_vars[entry_id] = var

            줄 = tk.Frame(self.step_box, bg=theme.SURFACE)
            줄.pack(fill="x")
            cb = tk.Checkbutton(줄, text=entry.label, variable=var,
                                command=lambda i=entry_id: self._on_step_toggle(i),
                                bg=theme.SURFACE, fg=theme.TEXT, selectcolor=theme.SURFACE,
                                activebackground=theme.SURFACE, activeforeground=theme.TEXT,
                                highlightthickness=0, bd=0, anchor="w", width=16,
                                font=theme.body_font(), takefocus=0,
                                # 꺼졌을 때 눈으로 보여야 한다 — 색은 theme 만 안다.
                                disabledforeground=theme.FAINT)
            cb.pack(side="left", pady=1)
            요약 = tk.Label(줄, text=entry.summary, bg=theme.SURFACE, fg=theme.MUTED,
                           font=theme.body_font(9), anchor="w")
            요약.pack(side="left", padx=(8, 0))
            self.step_rows[entry_id] = (줄, cb, 요약)
            # 체크와 선택은 다르다 — 체크는 "실행한다", 선택은 "지금 이 줄을
            # 다루고 있다"(▲▼ 의 대상). 줄 아무 데나 누르면 선택된다.
            for w in (줄, 요약):
                w.bind("<Button-1>", lambda _e, i=entry_id: self._select_step(i))
        self._paint_steps()
        # 줄을 통째로 새로 만들었으니 잠금도 다시 발라야 한다. 새 체크박스는
        # 기본이 켜짐이라, 이걸 빼면 도는 중에 다시 그려진 줄만 눌린다.
        self._sync_buttons()

    def _select_step(self, entry_id: str) -> None:
        self.step_selected = entry_id
        self._paint_steps()

    def _paint_steps(self) -> None:
        for entry_id, (줄, cb, 요약) in self.step_rows.items():
            bg = theme.SUNKEN if entry_id == self.step_selected else theme.SURFACE
            줄.configure(bg=bg)
            cb.configure(bg=bg, selectcolor=bg, activebackground=bg)
            요약.configure(bg=bg)

    def _on_step_toggle(self, entry_id: str) -> None:
        self._select_step(entry_id)
        self._push_steps()

    def _push_steps(self, *, quiet: bool = False) -> None:
        """체크·순서를 **즉시** 세션에 넘긴다. 화면과 실행이 갈라지지 않게."""
        ids = [i for i in self.step_order if self.step_vars[i].get()]
        before = self._settings_fingerprint()
        with self._reporting("작업 고르기"):
            self.session.set_steps(ids)
        # set_steps 뒤에는 어떤 레시피도 아니다(세션이 그렇게 말한다).
        # 드롭다운에 옛 레시피 이름이 남아 있으면 그것이 곧 거짓말이 된다.
        self.recipe_var.set(_NO_RECIPE)
        self._update_unmatched()
        # ▲▼ 로 **켜지 않은** 줄만 옮긴 경우처럼, 세션은 계획을 버렸는데 실제로
        # 실행될 것은 그대로인 때가 있다. 그때도 표와 [실행] 은 세션을 따른다.
        self._after_change(before,
                           None if quiet else
                           "작업이 바뀌었습니다 — [미리보기] 를 다시 눌러 주세요.")
        self._sync_buttons()

    def _move_step(self, delta: int) -> None:
        if self.step_selected is None:
            self.status_var.set("먼저 옮길 작업 줄을 눌러 골라 주세요.")
            return
        새순서, _ = move_item(self.step_order,
                            self.step_order.index(self.step_selected), delta)
        if 새순서 == self.step_order:
            # 맨 위에서 ▲, 맨 아래에서 ▼. 여기서 set_steps 를 부르면 아무것도
            # 안 바뀌었는데 멀쩡한 미리보기가 무효가 된다.
            self.status_var.set("더 옮길 자리가 없습니다.")
            return
        self.step_order = 새순서
        self._draw_steps()
        self._push_steps()

    # ── 누를 수 있는 것 / 없는 것 ────────────────────────────────
    def _sync_buttons(self) -> None:
        """켜짐/꺼짐을 **화면 전체에 한 번에** 바른다. 판단은 `control_locks` 가 한다.

        여기서 따로 판단하면 규칙이 두 곳이 되고, 어긋나는 순간 미리보기를 안 본
        채로 실행이 눌린다. 일이 도는 동안(`_busy`)은 세 버튼뿐 아니라 대상·
        레시피·작업 체크박스·▲▼·[저장]·[설정 · 폴더 위치] 링크까지 **전부** 끈다
        — 하나라도 열어 두면 도는 사이에 그것만 바뀌어, 끝난 뒤 화면이 가리키는
        폴더와 실제로 손댄 폴더가 갈라진다.
        """
        on = control_locks(busy=self._busy,
                           can_preview=self.session.can_preview,
                           can_apply=self.session.can_apply,
                           can_undo=self.session.can_undo,
                           has_recipes=getattr(self.recipe_menu, "has_items", False),
                           has_targets=getattr(self.target_menu, "has_items", False))
        for btn, key in ((self.btn_preview, "preview"), (self.btn_apply, "apply"),
                         (self.btn_undo, "undo"), (self.btn_save, "save"),
                         (self.btn_up, "order"), (self.btn_down, "order"),
                         (self.btn_settings, "settings")):
            btn.state(["!disabled"] if on[key] else ["disabled"])
        for mb, key in ((self.recipe_menu, "recipe"), (self.target_menu, "target")):
            mb.configure(state="normal" if on[key] else "disabled")
        상태 = "normal" if on["steps"] else "disabled"
        for _줄, cb, _요약 in self.step_rows.values():
            cb.configure(state=상태)

    def _do_preview(self) -> None:
        self._run_job("미리보기", self.session.preview, self._preview_done,
                      discard_if_stale=True)

    def _do_apply(self) -> None:
        # **빗장을 먼저.** 대화상자를 먼저 띄우면, 세 번 눌렀을 때 실행은 한 번만
        # 되어도 대화상자가 세 번 떴다 사라진다.
        if self._busy:
            return
        보던것 = self.view.summary if self.view else ""
        if not self._confirm(
                "실행", f"지금 미리보기 그대로 파일을 옮깁니다.\n\n{보던것}\n\n계속할까요?"):
            return
        self._run_job("실행", self.session.apply, self._apply_done)

    def _do_undo(self) -> None:
        """되돌리기 전에 **어느 폴더인지 글자로** 보여주고 한 번만 묻는다.

        [실행] 과 같은 모양이다. 되돌리기는 사용자의 마지막 안전줄이라 더
        어렵게 만들지 않는다 — 확인 한 번이면 된다.
        """
        # [실행] 과 같은 순서: 빗장을 먼저. 대화상자를 먼저 띄우면 여러 번 눌렸을 때
        # 되돌리기는 한 번만 돌아도 대화상자가 그만큼 떴다 사라진다.
        if self._busy:
            return
        root = self.session.root
        if root is None:
            # 세션과 같은 말을 쓴다(`Session.undo` 도 이렇게 거절한다).
            self._report("되돌리기", OrganizeError(
                "되돌릴 폴더를 알 수 없습니다.", hint="정리할 폴더를 먼저 골라 주세요."))
            return
        if not self._confirm(
                "되돌리기", undo_prompt(undo_label(root, self.targets), root)):
            # 알리지 않으면 상태줄에 직전 말이 남아 무슨 일이 있었는지 헷갈린다.
            self.status_var.set("되돌리기를 취소했습니다 — 아무것도 바뀌지 않았습니다.")
            return
        self._run_job("되돌리기", self.session.undo, self._undo_done)

    def _run_job(self, what: str, work, done, *,
                 discard_if_stale: bool = False) -> None:
        """오래 걸리는 일을 딴 스레드에서. 도는 동안 **화면의 조작을 전부 끈다.**

        버튼만이 아니다 — 대상·레시피·작업 체크박스·▲▼ 까지다. 하나라도 열어
        두면 도는 사이에 그것만 바뀌어, 끝난 뒤 화면과 실제가 갈라진다.

        `discard_if_stale` 은 **미리보기에만** 붙인다. 도는 동안 설정이 바뀌면
        그 결과는 화면이 말하는 것과 다르므로 버린다.

        실행·되돌리기에는 붙이지 않는다 — 그쪽은 이미 파일을 건드린 뒤라,
        결과를 버리면 무슨 일이 벌어졌는지가 화면에서 사라진다. 대신 두 메서드는
        끝에서 스스로 미리보기를 무효로 만들므로 옛 계획이 되살아나지 않는다.
        """
        if self._busy:
            return
        self._busy = True
        self._sync_buttons()
        # 잠근 이유가 화면에 보여야 한다 — 회색이 된 대상·체크박스를 보고
        # 고장으로 읽지 않도록, 무엇을 하는 중이고 언제 풀리는지 적는다.
        self.status_var.set(f"{what} 중…  끝날 때까지 다른 조작은 잠깁니다."
                            "  (파일이 많으면 시간이 걸립니다)")
        세대 = self._generation if discard_if_stale else None

        def 일하기():
            try:
                self._jobs.put((what, done, 세대, "ok", work()))
            except Exception as e:               # noqa: BLE001 — 창은 살아 있어야 한다
                self._jobs.put((what, done, 세대, "fail", e))

        try:
            threading.Thread(target=일하기, daemon=True).start()
        except RuntimeError:
            # 스레드를 못 띄웠는데 `_busy` 를 켠 채로 두면 **창이 영영 굳는다**
            # (아무도 `_drain_jobs` 를 부르지 않는다). 반드시 되돌려 놓고 알린다.
            self._busy = False
            self._sync_buttons()
            self._report(what, OrganizeError(
                f"{what} 를 시작하지 못했습니다.",
                hint="다른 프로그램을 닫고 잠시 뒤에 다시 눌러 주세요."))
            return
        self.window.after(60, self._drain_jobs)

    def _drain_jobs(self) -> None:
        try:
            what, done, 세대, kind, payload = self._jobs.get_nowait()
        except queue.Empty:
            self.window.after(60, self._drain_jobs)
            return
        self._busy = False
        if 세대 is not None and 세대 != self._generation:
            # 띄울 때와 지금의 세대가 다르다 — 도는 동안 설정이 바뀌었다.
            # **세션이 계산해 둔 계획도 함께 버린다.** 창이 결과를 안 그리는
            # 것만으로는 부족하다: session.can_apply 가 True 로 남아 [실행] 이
            # 되살아나고, 확인 대화상자는 화면에 없는 계획을 요약해 보여준다.
            self.session.invalidate()
            # 조용히 버리면 사용자는 미리보기가 아직 안 끝났다고 생각한다.
            self.status_var.set("설정이 바뀌어 미리보기를 버렸습니다"
                                " — [미리보기] 를 다시 눌러 주세요.")
            self._sync_buttons()
            return
        # **끝났으면 무슨 일이 있었든 다시 켠다.** `done` 이나 오류 알림이
        # 터져도 잠긴 채로 남으면 창이 영영 굳는다 — 그래서 finally 다.
        try:
            if kind == "ok":
                with self._reporting(what):
                    done(payload)
            else:
                self._report(what, payload)
        finally:
            self._sync_buttons()

    def _preview_done(self, view) -> None:
        self.view = view
        self._draw_result()
        self.status_var.set(view.summary)

    def _apply_done(self, result) -> None:
        self.view = None
        기록 = f"  기록: {result.log_path.name}" if result.log_path else ""
        self._clear_result(
            f"실행을 마쳤습니다 — 옮김 {result.moved} · 폴더 생성 {result.folders}"
            f" · 실패 {result.failed} · 건너뜀 {result.skipped}.{기록}\n"
            "다시 보려면 [미리보기] 를 눌러 주세요.")
        self.status_var.set(f"옮김 {result.moved} · 폴더 {result.folders}"
                            f" · 실패 {result.failed}")
        if result.messages:
            self._show_messages("실행 결과", result.messages)

    def _undo_done(self, result) -> None:
        self.view = None
        self._clear_result(f"되돌렸습니다 — 제자리로 {result.restored}개"
                           f" · 실패 {result.failed}개.")
        self.status_var.set(f"되돌림 {result.restored} · 실패 {result.failed}")
        if result.messages:
            self._show_messages("되돌리기 결과", result.messages)

    def _show_messages(self, 제목: str, messages: list) -> None:
        # 다 보여주면 대화상자가 화면 밖으로 나간다. 앞 20 줄만 보이고 나머지는
        # 몇 줄이 더 있는지 알린다 — 있다는 사실 자체를 숨기지 않는다.
        본문 = "\n".join(messages[:20])
        if len(messages) > 20:
            본문 += f"\n… 그 밖에 {len(messages) - 20}줄"
        self._notice(제목, 본문)

    # ── 결과 표 ──────────────────────────────────────────────────
    def _table_area(self, parent):
        tk, ttk = self.tk, self.ttk
        wrap = ttk.Frame(parent)
        canvas = tk.Canvas(wrap, bg=theme.SURFACE, highlightthickness=1,
                           highlightbackground=theme.LINE, highlightcolor=theme.LINE,
                           bd=0, takefocus=0)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")

        inner = tk.Frame(canvas, bg=theme.SURFACE)
        창 = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(창, width=e.width))

        def 휠(event):
            # 리눅스는 Button-4/5, 윈도우는 MouseWheel 로 온다. 둘 다 받는다.
            아래로 = getattr(event, "num", 0) == 5 or getattr(event, "delta", 0) < 0
            canvas.yview_scroll(1 if 아래로 else -1, "units")

        def 잡기(_e):
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.window.bind_all(seq, 휠)

        def 놓기(_e):
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.window.unbind_all(seq)

        canvas.bind("<Enter>", 잡기)
        canvas.bind("<Leave>", 놓기)
        return wrap, canvas, inner

    def _clear_result(self, note: str) -> None:
        """표를 비운다. **미리보기가 무효가 되면 표도 남기지 않는다** —
        무효가 된 계획을 보면서 [실행] 이 왜 꺼졌는지 사용자는 알 수 없다."""
        self.view = None
        self.tab_kind = None
        for box in (self.warn_box, self.tab_box, self.table_inner):
            for w in box.winfo_children():
                w.destroy()
        self.tk.Label(self.table_inner, text=note, bg=theme.SURFACE, fg=theme.MUTED,
                      font=theme.body_font(), anchor="w", justify="left",
                      wraplength=760).pack(anchor="w", padx=14, pady=14)
        self.foot.config(text="")
        # 표를 버렸으면 아래 줄에 남아 있는 옛 미리보기 요약도 거짓이 된다.
        self.status_var.set("")

    def _draw_result(self) -> None:
        """미리보기 결과를 **통째로** 다시 그린다.

        파일 하나의 체크를 끄면 계획이 처음부터 다시 세워지므로 **다른 파일의
        줄도 바뀐다**(중복 제거에서 남길 파일이 뒤집히면 `격리` 가 `이동` 이
        된다). 그래서 줄 하나만 고쳐 그리지 않는다.
        """
        tk = self.tk
        view = self.view
        for box in (self.warn_box, self.tab_box, self.table_inner):
            for w in box.winfo_children():
                w.destroy()

        for 경고 in view.warnings:
            self.ttk.Label(self.warn_box, text=f"⚠ {경고}", style="Alert.TLabel",
                           wraplength=800, justify="left").pack(anchor="w", pady=(0, 4))

        탭들 = kind_tabs(view.counts)
        if 탭들 and self.tab_kind not in [k for k, _, _ in 탭들]:
            self.tab_kind = 탭들[0][0]
        for kind, 이름, 개수 in 탭들:
            self._tab(kind, f"{이름} {개수}").pack(side="left", padx=(0, 6))

        # 뺀 파일을 **표 맨 위에** 둔다. 아래에 두면 줄이 많을 때 화면 밖으로
        # 밀려, 방금 뺀 것이 어디로 갔는지 보이지 않는다(실측: 캡처에서 안 보였다).
        self._draw_excluded()

        보일줄 = [r for r in view.rows if _raw_kind(r.kind) == self.tab_kind]
        상태 = row_checks(보일줄, self.session.excluded_keys())
        for i, (row, 켜짐) in enumerate(zip(보일줄[:_MAX_ROWS], 상태[:_MAX_ROWS])):
            self._file_row(row.name, dest_text(row.dest, self.session.root),
                           row.reason, 켜짐, row.key, row.leaving, i)
        # 여기서 잘렸다는 **표시**만 남긴다. 이유를 적은 문장은 아래 줄(foot)에
        # 둔다 — 250줄이면 이 줄은 4233px 중 맨 아래라 200줄을 내려야 보인다.
        가린줄 = max(0, len(보일줄) - _MAX_ROWS)
        if 가린줄:
            tk.Label(self.table_inner,
                     text=f"… 여기서 잘렸습니다 — 이 탭의 나머지 {가린줄}줄.",
                     bg=theme.SURFACE, fg=theme.MUTED, font=theme.body_font(9),
                     anchor="w").pack(fill="x", padx=14, pady=(6, 8))

        self.foot.config(text=foot_text(view.counts, view.skipped, 가린줄))

    def _tab(self, kind: str, text: str):
        """탭 하나. 누르면 그 종류만 표에 남는다(계획을 다시 세우지는 않는다)."""
        색, 배경 = _KIND_COLOR.get(kind, (theme.MUTED, theme.SKIP_BG))
        고른것 = kind == self.tab_kind
        lab = self.tk.Label(self.tab_box, text=text,
                            bg=배경 if 고른것 else theme.SURFACE,
                            fg=색 if 고른것 else theme.MUTED,
                            font=theme.body_font(9, weight="bold" if 고른것 else "normal"),
                            padx=12, pady=5, highlightthickness=1,
                            highlightbackground=색 if 고른것 else theme.LINE)
        lab.bind("<Button-1>", lambda _e, k=kind: self._pick_tab(k))
        return lab

    def _pick_tab(self, kind: str) -> None:
        self.tab_kind = kind
        if self.view:
            self._draw_result()

    def _file_row(self, name: str, dest: str, reason: str, 켜짐, key: str,
                  leaving: bool, index: int) -> None:
        tk = self.tk
        bg = theme.TRASH_BG if leaving else (
            theme.SURFACE if index % 2 == 0 else theme.SURFACE_ALT)
        줄 = tk.Frame(self.table_inner, bg=bg)
        줄.pack(fill="x")
        if 켜짐 is None:
            # 압축 안에서 나올 파일 · 폴더 생성. 아직 디스크에 없거나 어느 파일
            # 것도 아니라 **뺄 수가 없다.** 빈 자리를 남겨 줄이 어긋나지 않게 한다.
            tk.Label(줄, text=" ", bg=bg, width=3).pack(side="left")
        else:
            var = tk.BooleanVar(value=켜짐)
            tk.Checkbutton(줄, variable=var, bg=bg, activebackground=bg,
                           selectcolor=bg, highlightthickness=0, bd=0, takefocus=0,
                           command=lambda k=key, v=var: self._on_file_check(k, v.get()),
                           ).pack(side="left")
        tk.Label(줄, text=name, bg=bg, fg=theme.TEXT, font=theme.body_font(),
                 anchor="w").pack(side="left")
        if leaving:
            tk.Label(줄, text="밖으로", bg=bg, fg=theme.TRASH,
                     font=theme.body_font(9, weight="bold")).pack(side="left", padx=(8, 0))
        tk.Label(줄, text=dest, bg=bg, fg=theme.MUTED, font=theme.mono_font(9),
                 anchor="e").pack(side="right", padx=(8, 12))
        if reason:
            tk.Label(줄, text=reason, bg=bg, fg=theme.FAINT, font=theme.body_font(8),
                     anchor="w").pack(side="left", padx=(10, 0))

    def _draw_excluded(self) -> None:
        """뺀 파일을 표 **맨 위에** 남긴다. 사라지면 다시 켤 방법이 없다.

        아래에 두면 줄이 많을 때 화면 밖으로 밀려, 방금 뺀 것이 어디로 갔는지
        보이지 않는다(실측: 캡처에서 안 보였다).
        """
        tk = self.tk
        뺀것 = sorted(self.session.excluded_keys())
        if not 뺀것:
            return
        tk.Label(self.table_inner, text=f"제외한 파일 {len(뺀것)}개 — 체크를 다시 켜면"
                                        " 계획에 다시 들어갑니다.",
                 bg=theme.SURFACE, fg=theme.MUTED, font=theme.body_font(9),
                 anchor="w").pack(fill="x", padx=14, pady=(6, 2))
        for key in 뺀것:
            줄 = tk.Frame(self.table_inner, bg=theme.SKIP_BG)
            줄.pack(fill="x")
            var = tk.BooleanVar(value=False)
            tk.Checkbutton(줄, variable=var, bg=theme.SKIP_BG,
                           activebackground=theme.SKIP_BG, selectcolor=theme.SKIP_BG,
                           highlightthickness=0, bd=0, takefocus=0,
                           command=lambda k=key, v=var: self._on_file_check(k, v.get()),
                           ).pack(side="left")
            tk.Label(줄, text=Path(key).name, bg=theme.SKIP_BG, fg=theme.SKIP,
                     font=theme.body_font(), anchor="w").pack(side="left")
            tk.Label(줄, text="제외함", bg=theme.SKIP_BG, fg=theme.SKIP,
                     font=theme.mono_font(9)).pack(side="right", padx=(8, 12))
        tk.Frame(self.table_inner, bg=theme.LINE_SOFT, height=1).pack(fill="x", pady=(0, 6))

    def _on_file_check(self, key: str, 켜짐: bool) -> None:
        """파일 하나를 빼거나 되돌린다. **계획을 처음부터 다시 세운다.**

        동작 하나만 골라내면 빈 폴더가 남고 `가이드(1).pdf` 의 `(1)` 이 남는다.
        다시 세우면 이름도 폴더도 전부 다시 계산되어 미리보기와 실행이 같아진다.
        """
        if self._busy:
            # 도는 중에 바꾸면 화면과 세션이 갈라진다. 방금 누른 체크를 되돌려
            # 그린다(표를 통째로 다시 그리면 세션이 말하는 상태로 돌아온다).
            self.status_var.set("미리보기가 도는 중입니다 — 잠시 뒤에 다시 눌러 주세요.")
            if self.view:
                self._draw_result()
            return
        before = self._settings_fingerprint()
        with self._reporting("파일 빼기"):
            self.session.set_excluded(toggle_file_key(self.session.excluded_keys(),
                                                      key, 켜짐))
        # 표는 그대로 두고(note=None) 곧바로 다시 세운다. 세대를 올리는 자리를
        # 여기도 지나야 다섯 조작이 모두 같은 규칙을 따른다.
        self._after_change(before, None)
        self._do_preview()

    # ── 화면 3 — 설정 · 폴더 위치 ────────────────────────────────
    def _build_settings(self, parent) -> None:
        """등록된 위치를 보고 고친다. **탐색기를 쓰는 유일한 화면이다.**

        **[저장] 버튼을 두지 않는다** — 탐색기에서 고른 것이 곧 확정이라
        저장할 것이 없다. 아무 일도 안 하는 버튼은 사용자를 속인다.
        """
        ttk = self.ttk
        self._header(parent, "설정 · 폴더 위치")

        # 바닥부터 붙인다 — 목록이 길어져도 [닫기] 가 창 밖으로 밀려 잘리지 않게
        # (화면 1 에서 실측한 실수다).
        아래 = ttk.Frame(parent)
        아래.pack(side="bottom", fill="x", pady=(14, 0))
        self.btn_settings_close = ttk.Button(아래, text="닫기", style="Primary.TButton",
                                             command=self._close_settings)
        self.btn_settings_close.pack(side="right")
        ttk.Label(아래, text="고른 즉시 저장됩니다 — 그래서 [저장] 버튼이 없습니다.",
                  style="Faint.TLabel").pack(side="left")

        wrap, _canvas, self.settings_body = self._table_area(parent)
        wrap.pack(fill="both", expand=True, pady=(14, 0))
        self._fill_settings()

    def _fill_settings(self) -> None:
        """설정 화면을 처음부터 다시 그린다. **무엇을 적을지는 순수 함수가 정한다.**"""
        tk, ttk = self.tk, self.ttk
        body = getattr(self, "settings_body", None)
        if body is None:
            return                          # 아직 화면을 짓는 중이다
        for w in body.winfo_children():
            w.destroy()

        try:
            cfg = load_config(self.repo_root)
        except OrganizeError as e:
            칸 = self._settings_group(body, "설정을 읽지 못했습니다", e.message)
            self._settings_line(칸, e.hint or "", alert=True)
            return
        pinned = local_place_names(self.repo_root)

        # ① 자동으로 찾은 위치 — 정상이면 조용히 둔다
        칸 = self._settings_group(
            body, "자동으로 찾은 위치",
            "문제가 있는 줄만 눈에 띕니다. PC 를 옮겼으면 그 줄만 다시 지정하면 됩니다.")
        내장 = builtin_places(self._infos, pinned)
        if not 내장:
            self._settings_line(칸, "폴더를 확인하는 중입니다…")
        폭 = name_width([p.label for p in 내장])
        for place in 내장:
            self._place_row(칸, place, builtin=True, width=폭)

        # ② 내가 추가한 위치 — 탐색기를 쓰는 유일한 자리
        칸 = self._settings_group(
            body, "내가 추가한 위치",
            "USB·SD카드는 안 꽂혀 있을 수 있습니다 — 없다고 등록을 지우지 않습니다.")
        추가 = custom_places(cfg, pinned)
        if not 추가:
            self._settings_line(칸, "아직 없습니다. 아래 [+ 위치 추가] 로 등록하세요.")
        폭 = name_width([p.label for p in 추가])
        for place in 추가:
            self._place_row(칸, place, builtin=False, width=폭)
        줄 = tk.Frame(칸, bg=theme.SURFACE)
        줄.pack(fill="x", pady=(8, 0))
        ttk.Button(줄, text="+ 위치 추가", style="Tiny.Ghost.TButton",
                   command=self._add_place).pack(side="right")

        # ③ 폴더 이름 — **읽기 전용.** 엔진이 folder_names 를 읽지 않는다.
        칸 = self._settings_group(
            body, "폴더 이름 (읽기 전용)",
            "정리하면 아래 이름의 폴더가 만들어집니다.")
        for 보일이름, 폴더들, 문제 in profile_folder_names(self.repo_root / "profiles"):
            줄 = tk.Frame(칸, bg=theme.SURFACE)
            줄.pack(fill="x", pady=3)
            tk.Label(줄, text=보일이름, bg=theme.SURFACE, fg=theme.TEXT,
                     font=theme.body_font(), width=18, anchor="w").pack(side="left")
            tk.Label(줄, text=(문제 or "  ".join(폴더들) or "만드는 폴더가 없습니다"),
                     bg=theme.SURFACE, fg=(theme.TRASH if 문제 else theme.MUTED),
                     font=theme.mono_font(9), anchor="w", justify="left",
                     wraplength=520).pack(side="left")
        self._settings_line(
            칸, "폴더 이름을 바꾸려면 profiles 폴더의 .toml 파일에서 to 값을 고치세요.")

    def _settings_group(self, parent, 제목: str, 설명: str):
        """설정 화면의 칸 하나. 제목·설명을 얹고 줄이 들어갈 자리를 돌려준다."""
        tk = self.tk
        칸 = tk.Frame(parent, bg=theme.SURFACE)
        칸.pack(fill="x", padx=16, pady=(16, 6))
        tk.Label(칸, text=제목, bg=theme.SURFACE, fg=theme.TEXT,
                 font=theme.body_font(11), anchor="w").pack(fill="x")
        if 설명:
            tk.Label(칸, text=설명, bg=theme.SURFACE, fg=theme.MUTED,
                     font=theme.body_font(9), anchor="w", justify="left",
                     wraplength=740).pack(fill="x", pady=(1, 8))
        tk.Frame(칸, bg=theme.LINE_SOFT, height=1).pack(fill="x", pady=(0, 8))
        return 칸

    def _settings_line(self, parent, text: str, *, alert: bool = False) -> None:
        self.tk.Label(parent, text=text, bg=theme.SURFACE,
                      fg=(theme.TRASH if alert else theme.FAINT),
                      font=theme.body_font(9), anchor="w", justify="left",
                      wraplength=740).pack(fill="x", pady=(6, 0))

    def _place_row(self, parent, place, *, builtin: bool, width: int) -> None:
        """위치 한 줄. 오른쪽 버튼을 **먼저** 붙인다 — 경로가 길어도 밀려나지 않게.

        `width` 는 그 칸 전체에서 가장 긴 이름에 맞춘 값이다(`name_width`).
        줄마다 따로 재면 이름 칸이 들쭉날쭉해져 목록으로 안 읽힌다.
        """
        tk, ttk = self.tk, self.ttk
        줄 = tk.Frame(parent, bg=theme.SURFACE)
        줄.pack(fill="x", pady=3)

        tk.Label(줄, text=place.label, bg=theme.SURFACE, fg=theme.TEXT,
                 font=theme.body_font(), width=width, anchor="w",
                 ).pack(side="left", padx=(0, 10))

        if builtin:
            # 정상인 줄에는 버튼을 두지 않는다 — 고칠 것이 없는데 고치는 단추가
            # 있으면 무엇이 문제인지 눈에 안 들어온다.
            if place.alert:
                ttk.Button(줄, text="다시 지정", style="Tiny.Ghost.TButton",
                           command=lambda p=place: self._pick_place(p.name, p.label),
                           ).pack(side="right", padx=(6, 0))
            if place.pinned:
                # 직접 지정한 줄은 **되돌릴 수 있어야 한다.** 안 그러면 한 번
                # 잘못 고른 뒤로 OS 가 찾아 주는 자리로 못 돌아온다.
                ttk.Button(줄, text="기본 위치로", style="Tiny.Ghost.TButton",
                           command=lambda p=place: self._reset_place(p.name, p.label),
                           ).pack(side="right", padx=(6, 0))
        else:
            if place.pinned:
                ttk.Button(줄, text="지우기", style="Tiny.Ghost.TButton",
                           command=lambda p=place: self._remove_place(p),
                           ).pack(side="right", padx=(6, 0))
            else:
                # 지울 수 없는 이름에 [지우기] 를 그리면 눌러도 아무 일이 없다.
                tk.Label(줄, text="공용 설정", bg=theme.SURFACE, fg=theme.FAINT,
                         font=theme.body_font(9)).pack(side="right", padx=(6, 0))
            ttk.Button(줄, text="찾아보기", style="Tiny.Ghost.TButton",
                       command=lambda p=place: self._pick_place(p.name, p.label),
                       ).pack(side="right", padx=(6, 0))

        if place.note:
            tk.Label(줄, text=place.note, bg=theme.SURFACE,
                     fg=(theme.TRASH if place.alert else theme.MUTED),
                     font=theme.body_font(9)).pack(side="right", padx=(10, 0))
        # 여기도 **눌러서 여는 링크**다 — 안 그러면 경로를 눈으로 읽고 탐색기
        # 주소창에 손으로 옮겨 적어야 한다. 없는 폴더는 링크가 아니라 빨간 글자로
        # 남는다(눌러도 아무 일이 없는 링크를 그리지 않는다).
        self._path_link(줄, text=place.path, folder=place.open_path, size=9,
                        plain_fg=(theme.TRASH if place.alert else theme.FAINT),
                        ).pack(side="left", fill="x", expand=True, padx=(0, 8))

    # ── 화면 3 의 조작 — 고른 즉시 저장된다 ─────────────────────
    def _pick_place(self, name: str, label: str) -> None:
        """탐색기로 폴더를 골라 그 이름으로 저장한다. 고른 것이 곧 확정이다."""
        with self._reporting("위치 지정"):
            self._need_picker()
            cfg = load_config(self.repo_root)
            try:
                시작 = resolve_alias(f"@{name}", cfg)
            except AliasNotDefined:
                시작 = None
            chosen = picker.ask_folder(title=f"'{label}' 으로 쓸 폴더를 고르세요",
                                       start=시작)
            if chosen is None:
                self.status_var.set("고르지 않았습니다 — 아무것도 바꾸지 않았습니다.")
                return
            picker.store_picked_path(self.repo_root, name, chosen)
            # 경로를 통째로 적으면 상태줄이 창 밖으로 밀려 끝이 잘린다(실측).
            self.status_var.set(f"'{label}' 위치를 {_short(chosen)} 로 저장했습니다.")
        self._refresh_settings()

    def _add_place(self) -> None:
        """이름을 묻고 → 탐색기 → 저장. 이름이 이상하면 한국어로 알린다."""
        with self._reporting("위치 추가"):
            self._need_picker()
            name = self._ask_text("위치 추가", "이 위치를 무슨 이름으로 부를까요?",
                                  example="예: 백업드라이브")
            if name is None:
                self.status_var.set("위치 추가를 취소했습니다.")
                return
            cfg = load_config(self.repo_root)
            문제 = new_place_error(name, cfg)
            if 문제:
                raise OrganizeError(
                    문제, hint="다른 이름으로 [+ 위치 추가] 를 다시 눌러 주세요.")
            이름 = name.strip()
            chosen = picker.ask_folder(title=f"'{이름}' 으로 쓸 폴더를 고르세요")
            if chosen is None:
                # 이름만 저장해 두면 가리키는 곳이 없는 이름이 남는다.
                self.status_var.set("고르지 않았습니다 — 이름도 저장하지 않았습니다.")
                return
            picker.store_picked_path(self.repo_root, 이름, chosen)
            self.status_var.set(f"'{이름}' 위치를 {_short(chosen)} 로 저장했습니다.")
        self._refresh_settings()

    def _remove_place(self, place) -> None:
        """등록만 지운다. **폴더와 파일은 건드리지 않는다** — 그 말을 대화상자에 적는다."""
        if not self._confirm(
                "위치 지우기",
                f"'{place.name}' 위치 등록을 지웁니다.\n\n  {place.path}\n\n"
                "폴더와 파일은 그대로 있고, 이름만 지워집니다.\n\n계속할까요?"):
            self.status_var.set("지우지 않았습니다 — 아무것도 바뀌지 않았습니다.")
            return
        with self._reporting("위치 지우기"):
            지웠나 = remove_local_path(self.repo_root, place.name)
        self.status_var.set(
            f"'{place.name}' 위치를 지웠습니다." if 지웠나 else
            f"'{place.name}' 은 저장소 공용 설정(config.default.json)에 있어 여기서 지울 수 없습니다.")
        self._refresh_settings()

    def _reset_place(self, name: str, label: str) -> None:
        """직접 지정한 내장 위치를 OS 가 찾아 주는 기본 위치로 되돌린다."""
        if not self._confirm(
                "기본 위치로",
                f"'{label}' 을 이 PC 의 기본 위치로 되돌립니다.\n\n"
                "폴더와 파일은 그대로 있고, 직접 지정한 기록만 지웁니다.\n\n계속할까요?"):
            self.status_var.set("되돌리지 않았습니다 — 아무것도 바뀌지 않았습니다.")
            return
        with self._reporting("기본 위치로"):
            지웠나 = remove_local_path(self.repo_root, name)
        self.status_var.set(f"'{label}' 을 기본 위치로 되돌렸습니다." if 지웠나 else
                            f"'{label}' 은 직접 지정한 기록이 없습니다.")
        self._refresh_settings()

    def _need_picker(self) -> None:
        """탐색기를 못 띄우는 파이썬이면 **한국어로 알리고 창은 살려 둔다.**"""
        if not picker.can_open_window():
            raise OrganizeError(
                "이 파이썬에서는 폴더 고르기 창을 띄울 수 없습니다 (tkinter 없음).",
                hint="리눅스라면 'sudo apt install python3-tk' 로 설치하세요.\n"
                     "    창 없이 지정하려면: organize paths --set <이름>=<경로>")

    def _refresh_settings(self) -> None:
        """설정을 바꾼 뒤. 개수를 **다시 세고** 화면 3 을 다시 그린다."""
        self._start_counting(force=True)
        self._fill_settings()

    def _close_settings(self) -> None:
        """화면 2 로 돌아가면서 **대상 드롭다운을 새로 고친다.**

        방금 등록한 위치가 바로 안 보이면 사용자는 등록이 안 된 줄 안다.
        """
        self._go("main")
        self._start_counting(force=True)

    # ── 공통 조각 ────────────────────────────────────────────────
    def _header(self, parent, 제목: str) -> None:
        """신호등 점 + 화면 제목.

        **가짜 제목표시줄이 아니다.** 윈도우에는 진짜 제목표시줄이 위에 그대로
        있어서, 창 안에 또 하나를 그리면 두 줄이 되어 흉하다.
        """
        ttk = self.ttk
        줄 = ttk.Frame(parent)
        줄.pack(fill="x")
        theme.traffic_lights(줄).pack(side="left", pady=(0, 2))
        ttk.Label(줄, text=제목, style="Title.TLabel").pack(side="left", padx=(12, 0))
        return 줄            # 화면 2 가 오른쪽 끝에 링크를 하나 더 얹는다

    def _path_link(self, parent, *, text: str, folder: str, size: int,
                   plain_fg: str = theme.FAINT, bg: str = theme.SURFACE):
        """경로 글자 하나. `folder` 가 있으면 **눌러서 탐색기로 여는 링크**가 된다.

        `folder` 가 빈 글자면(어디인지 모르거나 폴더가 없는 줄) 보통 글자로
        둔다 — 눌러도 아무 일이 없는 링크는 "안 열리네" 가 아니라 "고장났네"
        로 읽힌다.

        **배치는 하지 않고 위젯만 돌려준다** — 화면 1 은 grid, 화면 3 은 pack 이라
        여기서 정할 수 없다.
        """
        tk = self.tk
        if not folder:
            return tk.Label(parent, text=text, bg=bg, fg=plain_fg,
                            font=theme.mono_font(size), anchor="w")
        lab = tk.Label(parent, text=text, bg=bg, fg=theme.ACCENT,
                       font=theme.link_font(size), anchor="w", cursor="hand2")
        lab.bind("<Button-1>", lambda _e, p=folder: self._open_folder(p))
        return lab

    def _open_folder(self, folder: str) -> None:
        """링크를 눌렀을 때. 못 열면 한국어로 알리고 **창은 살아 있다.**

        여는 동안 기다리지 않는다 — `picker.open_folder` 가 띄우기만 하고 곧장
        돌아온다. 무슨 일이 있었는지는 상태줄에 남긴다: 탐색기가 다른 창 뒤에서
        뜨면 눌러도 아무 일이 없는 것처럼 보이기 때문이다.
        """
        with self._reporting("폴더 열기"):
            picker.open_folder(Path(folder))
            self.status_var.set(f"탐색기에서 열었습니다 — {_short(Path(folder))}")

    def _card(self, parent):
        """판 하나. 얇은 테두리를 두른 밝은 면.

        ttk 프레임 대신 `tk.Frame` 을 쓴다 — `highlightthickness` 로 1px 테두리를
        어느 OS 에서나 같은 색으로 그릴 수 있는 유일한 방법이다. 둥근 모서리는
        tkinter 에 없다(시안의 반경 4px 는 여기서 못 낸다).
        """
        return self.tk.Frame(parent, bg=theme.SURFACE, bd=0,
                             highlightthickness=1,
                             highlightbackground=theme.LINE, highlightcolor=theme.LINE)

    # ── 대화상자 (버튼 글자가 한국어여야 한다) ───────────────────
    # 묻는 창을 **전부 우리가 그린다.** `messagebox`·`simpledialog` 는 버튼이
    # [OK]/[Cancel] 로 뜨고 테마가 안 먹는다 — tkinter 에 그 글자를 바꾸는 표준
    # 방법이 없다. 이 도구는 오류도 안내도 전부 한국어이고 창은 Finder 톤인데,
    # 정작 "정말 실행할까요" 와 "무슨 이름으로 부를까요" 만 영어에 회색 네모면
    # 되돌리기 가장 어려운 순간에 사용자가 낯선 창을 마주하게 된다.
    #
    # **묻는 내용과 동작은 바뀌지 않는다** — 글자와 창만 우리가 그린다.

    def _dialog(self, title: str):
        """대화상자의 껍데기. 톤을 정하는 곳은 **여기 하나다.**

        (창, 내용이 들어갈 프레임) 을 돌려준다. 가운데 맞추기와 붙잡기(grab)는
        내용을 다 채운 뒤 `_show_dialog` 가 한다 — 크기가 정해져야 가운데를
        계산할 수 있기 때문이다.
        """
        tk, ttk = self.tk, self.ttk
        win = tk.Toplevel(self.window)
        win.title(title)
        win.configure(bg=theme.BG)
        win.transient(self.window)
        win.resizable(False, False)
        몸 = ttk.Frame(win, padding=(22, 18))
        몸.pack(fill="both", expand=True)
        return win, 몸

    def _show_dialog(self, win, focus=None) -> None:
        """부모 창 가운데에 놓고, 닫힐 때까지 기다린다."""
        win.update_idletasks()
        가로 = max(0, (self.window.winfo_width() - win.winfo_width()) // 2)
        win.geometry(f"+{self.window.winfo_rootx() + 가로}"
                     f"+{self.window.winfo_rooty() + 110}")
        if focus is not None:
            focus.focus_set()
        try:
            win.grab_set()      # 묻는 동안 뒤 화면이 바뀌면 확인한 것과 달라진다
        except self.tk.TclError:
            pass                # 창을 아직 못 잡는 환경 — 물어보는 일 자체는 그대로 된다
        self.window.wait_window(win)

    def _confirm(self, title: str, body: str) -> bool:
        """[예]/[아니오] 로 묻는다. 예를 누르면 True."""
        ttk = self.ttk
        답 = {"예": False}
        win, 몸 = self._dialog(title)
        ttk.Label(몸, text=body, style="Lead.TLabel", wraplength=440,
                  justify="left").pack(anchor="w")
        줄 = ttk.Frame(몸)
        줄.pack(fill="x", pady=(18, 0))

        def 끝(값: bool) -> None:
            답["예"] = 값
            win.destroy()

        ttk.Button(줄, text="아니오", style="Ghost.TButton",
                   command=lambda: 끝(False)).pack(side="right")
        예 = ttk.Button(줄, text="예", style="Primary.TButton", command=lambda: 끝(True))
        예.pack(side="right", padx=(0, 10))

        # Enter 는 예, Esc 는 아니오. **창을 그냥 닫아도 아니오다** — 확인 없이
        # 파일이 움직이는 일이 있어서는 안 된다.
        win.bind("<Return>", lambda _e: 끝(True))
        win.bind("<Escape>", lambda _e: 끝(False))
        win.protocol("WM_DELETE_WINDOW", lambda: 끝(False))
        self._show_dialog(win, 예)
        return 답["예"]

    def _ask_text(self, title: str, prompt: str, *, example: str = "") -> str | None:
        """글자 하나를 묻는다. **취소하면 None.**

        빈 글자와 취소를 구별한다 — 취소는 None, [확인] 은 칸에 적힌 그대로다.
        빈 이름을 막는 일은 부르는 쪽이 한다(`new_place_error` 가 한국어 이유를
        준다). 여기서 같이 막으면 판단이 두 곳으로 갈라진다.
        """
        tk, ttk = self.tk, self.ttk
        답: dict = {"값": None}
        win, 몸 = self._dialog(title)
        ttk.Label(몸, text=prompt, style="Lead.TLabel", wraplength=380,
                  justify="left").pack(anchor="w")
        if example:
            ttk.Label(몸, text=example, style="Faint.TLabel").pack(anchor="w", pady=(2, 0))

        var = tk.StringVar()
        칸 = ttk.Entry(몸, textvariable=var, width=32, font=theme.body_font())
        칸.pack(fill="x", pady=(10, 0))

        줄 = ttk.Frame(몸)
        줄.pack(fill="x", pady=(18, 0))

        def 끝(값) -> None:
            답["값"] = 값
            win.destroy()

        ttk.Button(줄, text="취소", style="Ghost.TButton",
                   command=lambda: 끝(None)).pack(side="right")
        ttk.Button(줄, text="확인", style="Primary.TButton",
                   command=lambda: 끝(var.get())).pack(side="right", padx=(0, 10))

        # Enter 는 확인, Esc 는 취소. **창을 그냥 닫아도 취소다.**
        win.bind("<Return>", lambda _e: 끝(var.get()))
        win.bind("<Escape>", lambda _e: 끝(None))
        win.protocol("WM_DELETE_WINDOW", lambda: 끝(None))
        self._show_dialog(win, 칸)
        return 답["값"]

    def _notice(self, title: str, body: str, *, alert: bool = False) -> None:
        """읽고 [확인] 만 누르는 창. 오류도 여기로 나온다.

        창이 이미 닫히는 중이면 조용히 넘긴다 — 알리려다 죽으면 정작 무슨 일이
        있었는지 아무도 못 본다.
        """
        ttk = self.ttk
        try:
            if not self.window.winfo_exists():
                return
            win, 몸 = self._dialog(title)
        except self.tk.TclError:
            return
        if alert:
            # 무엇이 잘못됐는지 **한 줄로 먼저** 보인다. 본문은 검게 둔다 —
            # 여러 줄을 다 빨갛게 칠하면 정작 어디가 문제인지 안 읽힌다.
            ttk.Label(몸, text=f"⚠ {title}", style="Alert.TLabel",
                      font=theme.body_font(11, weight="bold"),
                      ).pack(anchor="w", pady=(0, 6))
        ttk.Label(몸, text=body, style="Lead.TLabel", wraplength=440,
                  justify="left").pack(anchor="w")
        줄 = ttk.Frame(몸)
        줄.pack(fill="x", pady=(18, 0))
        확인 = ttk.Button(줄, text="확인", style="Primary.TButton", command=win.destroy)
        확인.pack(side="right")
        win.bind("<Return>", lambda _e: win.destroy())
        win.bind("<Escape>", lambda _e: win.destroy())
        self._show_dialog(win, 확인)

    # ── 오류를 창으로 ────────────────────────────────────────────
    def _report(self, what: str, exc: BaseException) -> None:
        if isinstance(exc, OrganizeError):
            몸 = exc.message + (f"\n\n{exc.hint}" if exc.hint else "")
        else:
            # 파이썬 예외 원문을 그대로 보여주지 않는다(전역 규칙).
            몸 = (f"{what} 중 예상치 못한 오류가 났습니다.\n\n"
                  "디스크 상태나 쓰기 권한을 확인해 주세요.")
        self._notice(what, 몸, alert=True)
        self.status_var.set(f"{what} 실패 — 위 안내를 확인해 주세요.")

    class _Reporting:
        def __init__(self, app, what): self.app, self.what = app, what

        def __enter__(self): return self

        def __exit__(self, exc_type, exc, tb):
            if exc is None:
                return False
            self.app._report(self.what, exc)
            return True                    # 창이 죽지 않는다

    def _reporting(self, what: str):
        """무엇이 터지든 창은 살아 있고, 사람이 읽을 말로 알린다."""
        return self._Reporting(self, what)


def _tail(path: Path) -> str:
    """`…\\Desktop` 처럼 **꼬리만**. 전체 경로는 그 아래 회색 작은 글씨로 따로 보여준다."""
    parent = str(path.parent)
    sep = "\\" if "\\" in parent else "/"
    return f"…{sep}{path.name}" if path.name else str(path)


def _short(text_path: Path, limit: int = 56) -> str:
    """긴 경로는 가운데를 접는다.

    접지 않으면 라벨이 개수 칸까지 밀고 들어와 **숫자와 글자가 겹친다**
    (실측: 임시 폴더 경로에서 그렇게 됐다). 앞(드라이브·루트)과 끝(폴더 이름)은
    남긴다 — 사용자가 알아보는 두 조각이 그것이다.
    """
    text = str(text_path)
    if len(text) <= limit:
        return text
    return f"{text[:14]}…{text[-(limit - 15):]}"


def _문제인가(info) -> bool:
    """이 줄을 눈에 띄게 해야 하는가.

    개수 0 과 폴더 없음은 **다른 일이지만 둘 다 신호다** — OneDrive 백업이
    켜진 PC 에서는 진짜 바탕화면이 다른 곳에 있다.
    """
    return info.status != "" or info.count == 0


def _why(info) -> str:
    """줄 옆에 적을 **짧은** 이유. 긴 설명은 카드 아래에 한 번만 적는다."""
    if info.status == folders.UNRESOLVED:
        # 이 줄만은 길어도 그대로 적는다 — "확인할 수 없습니다" 만 보여 주면
        # 무엇을 고쳐야 하는지 알 수 없다(순환 별칭인지, 없는 이름인지).
        return getattr(info, "problem", "") or folders.UNRESOLVED
    if info.status == "폴더 없음":
        return "폴더가 없습니다"
    if info.status == "읽을 수 없음":
        return "읽을 수 없습니다 — 접근 권한을 확인해 주세요"
    return "비어 있습니다"
