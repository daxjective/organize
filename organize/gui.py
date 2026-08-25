"""창. **여기는 그리기만 한다** — 무엇을 그릴지는 `gui_model.Session` 이 정한다.

`tkinter` 를 함수 안에서 늦게 import 한다. 없는 환경에서도 `organize` 의 나머지
기능은 그대로 돌아야 하기 때문이다(리눅스에서 tkinter 는 별도 패키지다).

화면은 셋이고 **창은 하나다**(`ttk.Frame` 세 개를 `tkraise()` 로 바꿔 올린다).
창을 여러 개 띄우면 사용자가 창을 관리하게 된다 — 그건 도구의 일이다.

색과 글꼴은 `gui_theme` 만 안다. 여기서 색 코드를 직접 쓰지 않는다.
"""

import queue
import threading
from pathlib import Path

from organize import catalog, folders, gui_theme as theme
from organize.errors import OrganizeError
# 종류 이름표(`move` → "이동")는 `gui_model` 이 이미 갖고 있다. 여기서 같은 표를
# 다시 적으면 탭 이름과 표 안의 글자가 갈라진다 — 한쪽만 고쳐지기 때문이다.
from organize.gui_model import _KIND_LABEL as KIND_LABEL, Session
from organize.recipes import find_recipe, load_recipe
from organize.userconfig import AliasNotDefined, load_config, resolve_alias

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
        self._count_summary = ""
        self._inbox: queue.SimpleQueue = queue.SimpleQueue()

        # ── 화면 2 가 들고 있는 것 ────────────────────────────────
        self._jobs: queue.SimpleQueue = queue.SimpleQueue()
        self._busy = False              # 미리보기·실행이 도는 중인가
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
        self._counting_note = ttk.Label(self.folder_card, text="폴더를 세는 중입니다…",
                                        style="CardPath.TLabel")
        self._counting_note.grid(row=0, column=0, sticky="w", padx=16, pady=16)

    def _go(self, name: str) -> None:
        """버튼이 실제로 화면을 바꾼다. **눌러도 아무 일이 없으면 그게 결함이다.**"""
        with self._reporting("화면 바꾸기"):
            self.show(name)
            self.status_var.set("")

    # ── 폴더 개수 세기 (창이 멈추면 안 된다) ─────────────────────
    def _start_counting(self) -> None:
        """세는 일은 딴 스레드에서. 진짜 다운로드 폴더는 파일이 많고 WSL 은 느리다."""
        if self._counted:
            return
        self._counted = True
        threading.Thread(target=self._count_worker, daemon=True).start()
        # 결과는 **주 스레드**가 꺼내 간다. 딴 스레드가 위젯을 건드리면
        # tkinter 는 조용히 이상해지거나 죽는다.
        self.window.after(80, self._drain)

    def _count_worker(self) -> None:
        """디스크를 읽는 부분. 위젯을 하나도 건드리지 않는다."""
        try:
            # 홈은 뺀다 — 홈 전체 파일 개수는 정리 대상이 아니고, 숫자가 크면
            # 겁만 준다. 나머지는 다 싣는다: 화면 1 은 내장만 골라 쓰고,
            # 화면 2 의 대상 드롭다운은 등록한 이름까지 필요하다.
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
        if kind == "ok":
            self._fill_folders([f for f in payload if f.builtin])
            self._fill_targets(payload)
        else:
            self._counting_note.config(text="폴더를 세지 못했습니다.")
            self.target_var.set(_NO_TARGET)
            self._report("폴더 세기", payload)

    def _fill_folders(self, infos) -> None:
        ttk = self.ttk
        self._counting_note.destroy()
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
        """한 줄: 이름 · 꼬리 경로 · 전체 경로(작게) · 개수(크게)."""
        ttk = self.ttk
        row = ttk.Frame(parent, style="Card.TFrame")
        row.columnconfigure(1, weight=1)

        ttk.Label(row, text=info.label, style="CardName.TLabel", width=7,
                  ).grid(row=0, column=0, sticky="w")
        ttk.Label(row, text=_tail(info.path), style="CardPath.TLabel",
                  ).grid(row=0, column=1, sticky="w")

        문제 = _문제인가(info)
        ttk.Label(row, text=("—" if info.count is None else str(info.count)),
                  style="CardAlertCount.TLabel" if 문제 else "CardCount.TLabel",
                  anchor="e", width=5).grid(row=0, column=2, rowspan=2,
                                            sticky="e", padx=(12, 0))

        ttk.Label(row, text=_short(info.path), style="CardFull.TLabel",
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
        ttk.Button(머리, text="설정 · 폴더 위치", style="Link.TButton",
                   command=lambda: self._go("settings")).pack(side="right")

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
        ttk.Button(순서줄, text="▼", style="Tiny.Ghost.TButton", width=3,
                   command=lambda: self._move_step(1)).pack(side="right")
        ttk.Button(순서줄, text="▲", style="Tiny.Ghost.TButton", width=3,
                   command=lambda: self._move_step(-1)).pack(side="right", padx=(0, 6))

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
        return mb

    def _fill_dropdown(self, mb, items) -> None:
        """(글자, 누르면 할 일, 회색인가) 목록으로 메뉴를 다시 만든다."""
        menu = mb.dropdown
        menu.delete(0, "end")
        for i, (text, action, faint) in enumerate(items):
            menu.add_command(label=text, command=action)
            if faint:
                menu.entryconfigure(i, foreground=theme.FAINT)
        mb.configure(state="normal" if items else "disabled")

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
            self.session.set_recipe(name)
            self.recipe_var.set(name)
            self._sync_steps_from_session()
            옮김 = self._follow_recipe_root(name)
            self._clear_result(
                f"레시피 '{name}' 을 불러왔습니다." + (f"  대상을 {옮김} 으로 옮겼습니다."
                                                  if 옮김 else "")
                + "  [미리보기] 를 눌러 주세요.")
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
        from tkinter import messagebox, simpledialog

        name = simpledialog.askstring("레시피 저장", "이 조합을 무슨 이름으로 저장할까요?",
                                      parent=self.window)
        if not name:
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
                if not messagebox.askyesno(
                        "레시피 저장",
                        f"'{name.strip()}' 레시피가 이미 있습니다. 덮어쓸까요?",
                        parent=self.window):
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
            self.session.set_root(info.path)
            self.target_var.set(text)
            self._clear_result(f"대상: {info.path}")
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
                                font=theme.body_font(), takefocus=0)
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
        with self._reporting("작업 고르기"):
            self.session.set_steps(ids)
        # set_steps 뒤에는 어떤 레시피도 아니다(세션이 그렇게 말한다).
        # 드롭다운에 옛 레시피 이름이 남아 있으면 그것이 곧 거짓말이 된다.
        self.recipe_var.set(_NO_RECIPE)
        self._update_unmatched()
        if not quiet:
            self._clear_result("작업이 바뀌었습니다 — [미리보기] 를 다시 눌러 주세요.")
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

    # ── 세 버튼 ──────────────────────────────────────────────────
    def _sync_buttons(self) -> None:
        """켜짐/꺼짐은 **오직 세션**이 정한다.

        여기서 따로 판단하면 규칙이 두 곳이 되고, 어긋나는 순간 미리보기를 안 본
        채로 실행이 눌린다. 일이 도는 동안(`_busy`)은 전부 끈다 — 두 번 눌려
        두 번 실행되면 안 된다.
        """
        for btn, 켤까 in ((self.btn_preview, self.session.can_preview),
                         (self.btn_apply, self.session.can_apply),
                         (self.btn_undo, self.session.can_undo)):
            btn.state(["!disabled"] if (켤까 and not self._busy) else ["disabled"])
        self.btn_save.state(["disabled"] if self._busy else ["!disabled"])

    def _do_preview(self) -> None:
        self._run_job("미리보기", self.session.preview, self._preview_done)

    def _do_apply(self) -> None:
        from tkinter import messagebox

        보던것 = self.view.summary if self.view else ""
        if not messagebox.askyesno(
                "실행", f"지금 미리보기 그대로 파일을 옮깁니다.\n\n{보던것}\n\n계속할까요?",
                parent=self.window):
            return
        self._run_job("실행", self.session.apply, self._apply_done)

    def _do_undo(self) -> None:
        self._run_job("되돌리기", self.session.undo, self._undo_done)

    def _run_job(self, what: str, work, done) -> None:
        """오래 걸리는 일을 딴 스레드에서. 도는 동안 버튼을 전부 끈다."""
        if self._busy:
            return
        self._busy = True
        self._sync_buttons()
        self.status_var.set(f"{what} 중…  (파일이 많으면 시간이 걸립니다)")

        def 일하기():
            try:
                self._jobs.put((what, done, "ok", work()))
            except Exception as e:               # noqa: BLE001 — 창은 살아 있어야 한다
                self._jobs.put((what, done, "fail", e))

        threading.Thread(target=일하기, daemon=True).start()
        self.window.after(60, self._drain_jobs)

    def _drain_jobs(self) -> None:
        try:
            what, done, kind, payload = self._jobs.get_nowait()
        except queue.Empty:
            self.window.after(60, self._drain_jobs)
            return
        self._busy = False
        if kind == "ok":
            with self._reporting(what):
                done(payload)
        else:
            self._report(what, payload)
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
        from tkinter import messagebox
        # 다 보여주면 대화상자가 화면 밖으로 나간다. 앞 20 줄만 보이고 나머지는
        # 몇 줄이 더 있는지 알린다 — 있다는 사실 자체를 숨기지 않는다.
        본문 = "\n".join(messages[:20])
        if len(messages) > 20:
            본문 += f"\n… 그 밖에 {len(messages) - 20}줄"
        messagebox.showinfo(제목, 본문, parent=self.window)

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
        if len(보일줄) > _MAX_ROWS:
            tk.Label(self.table_inner,
                     text=f"… 이 탭의 나머지 {len(보일줄) - _MAX_ROWS}줄은 표시하지"
                          " 않았습니다(너무 많으면 창이 멈춥니다).",
                     bg=theme.SURFACE, fg=theme.MUTED, font=theme.body_font(9),
                     anchor="w").pack(fill="x", padx=14, pady=(6, 8))

        self.foot.config(text=self._foot_text(view))

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
        """뺀 파일을 표 아래에 **남긴다.** 사라지면 다시 켤 방법이 없다."""
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

    def _foot_text(self, view) -> str:
        말 = [f"손대지 않음 {view.skipped}개 (여기에 뺀 파일도 들어갑니다)."]
        if view.counts.get("extract"):
            # 누를 수 없는 이유를 모르면 고장으로 읽힌다.
            말.append("압축 안에서 나올 파일에는 체크박스가 없습니다 — 아직 디스크에"
                     " 없어서 뺄 수가 없습니다. 빼려면 그 압축 파일의 체크를 끄세요.")
        if view.counts.get("mkdir"):
            말.append("폴더 생성은 파일이 아니라 따로 셉니다.")
        return "  ".join(말)

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
        with self._reporting("파일 빼기"):
            self.session.set_excluded(toggle_file_key(self.session.excluded_keys(),
                                                      key, 켜짐))
        self._do_preview()

    # ── 화면 3 — 다음 Task 의 몫 ────────────────────────────────
    def _build_settings(self, parent) -> None:
        self._stub(parent, "설정 · 폴더 위치", "등록한 위치와 폴더 이름이 들어올 자리입니다.")

    def _stub(self, parent, 제목: str, 설명: str) -> None:
        ttk = self.ttk
        self._header(parent, 제목)
        card = self._card(parent)
        card.pack(fill="both", expand=True, pady=(14, 0))
        ttk.Label(card, text="다음 단계에서 만듭니다.", style="CardName.TLabel",
                  ).pack(anchor="w", padx=16, pady=(18, 2))
        ttk.Label(card, text=설명, style="CardPath.TLabel",
                  ).pack(anchor="w", padx=16, pady=(0, 18))
        ttk.Button(parent, text="← 처음 화면", style="Link.TButton",
                   command=lambda: self._go("first")).pack(anchor="w", pady=(12, 0))

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

    def _card(self, parent):
        """판 하나. 얇은 테두리를 두른 밝은 면.

        ttk 프레임 대신 `tk.Frame` 을 쓴다 — `highlightthickness` 로 1px 테두리를
        어느 OS 에서나 같은 색으로 그릴 수 있는 유일한 방법이다. 둥근 모서리는
        tkinter 에 없다(시안의 반경 4px 는 여기서 못 낸다).
        """
        return self.tk.Frame(parent, bg=theme.SURFACE, bd=0,
                             highlightthickness=1,
                             highlightbackground=theme.LINE, highlightcolor=theme.LINE)

    # ── 오류를 창으로 ────────────────────────────────────────────
    def _report(self, what: str, exc: BaseException) -> None:
        from tkinter import messagebox
        if isinstance(exc, OrganizeError):
            몸 = exc.message + (f"\n\n{exc.hint}" if exc.hint else "")
        else:
            # 파이썬 예외 원문을 그대로 보여주지 않는다(전역 규칙).
            몸 = (f"{what} 중 예상치 못한 오류가 났습니다.\n\n"
                  "디스크 상태나 쓰기 권한을 확인해 주세요.")
        messagebox.showerror(what, 몸, parent=self.window)
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
    if info.status == "폴더 없음":
        return "폴더가 없습니다"
    if info.status == "읽을 수 없음":
        return "읽을 수 없습니다 — 접근 권한을 확인해 주세요"
    return "비어 있습니다"
