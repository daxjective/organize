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

from organize import folders, gui_theme as theme
from organize.errors import OrganizeError
from organize.gui_model import Session
from organize.userconfig import load_config

_SCREENS = ("first", "main", "settings")

_TITLES = {"first": "organize — 처음 실행",
           "main": "organize",
           "settings": "설정 · 폴더 위치"}

# 폴더가 비었거나 없을 때 옆에 적는 말. **왜** 그런지까지 적는다 — OneDrive
# 백업이 켜진 PC 에서는 진짜 바탕화면이 다른 곳이라 여기가 0 으로 뜬다.
_ONEDRIVE = "OneDrive 백업이 켜져 있으면 실제 폴더가 다른 곳일 수 있습니다."


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
        self.window.geometry("760x660")
        self.window.minsize(680, 560)
        theme.apply_theme(self.window)

        self.status_var = tk.StringVar(value="")
        self._counted = False                  # 폴더를 이미 세었는가
        self._inbox: queue.SimpleQueue = queue.SimpleQueue()

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

        # 무슨 일이 있었는지 적는 줄. 오류·진행 상황이 여기 남는다 — 창을 닫고
        # 나서야 알게 되는 일이 없도록.
        ttk.Label(self.window, textvariable=self.status_var,
                  style="Muted.TLabel", anchor="w").pack(fill="x", padx=26, pady=(0, 10))

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
        if name == "first":
            # 세는 일은 화면 1 에서만 필요하다. 필요할 때 시작한다.
            self._start_counting()

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
            infos = [f for f in folders.overview(load_config(self.repo_root))
                     # 내장 별칭만 보여준다. 홈은 뺀다 — 홈 전체 파일 개수는
                     # 정리 대상이 아니고, 숫자가 크면 겁만 준다.
                     if f.builtin and f.name != "home"]
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
            self._fill_folders(payload)
        else:
            self._counting_note.config(text="폴더를 세지 못했습니다.")
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
        self.status_var.set(
            f"폴더 {len(infos)}곳을 확인했습니다."
            + (f"  그중 {문제수}곳은 비어 있거나 없습니다." if 문제수 else ""))

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

    # ── 화면 2·3 — 다음 Task 의 몫 ───────────────────────────────
    def _build_main(self, parent) -> None:
        self._stub(parent, "메인", "레시피·작업 체크박스·미리보기 표가 들어올 자리입니다.")

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
