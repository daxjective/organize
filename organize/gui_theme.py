"""Finder 톤 — 색 이름과 폰트 고르기, ttk 스타일.

**위젯 코드에 `#1191B0` 같은 색 코드를 직접 쓰지 않는다.** 색이 여기저기
흩어지면 시안이 바뀌었을 때 어디를 고쳐야 하는지 아무도 모른다. 값은 시안
문서(`docs/superpowers/specs/2026-08-25-gui-design.md` 의 '톤 — Finder')에서
그대로 가져왔고, `tests/test_gui_theme.py` 가 **그 문서를 읽어서** 비교한다.

`tkinter` 는 함수 안에서 늦게 import 한다 — 없는 환경에서 `organize` 의
나머지가 죽으면 안 되기 때문이다.
"""

import sys

# ── 색 (시안 '톤 — Finder' 색표) ─────────────────────────────────
BG = "#E6F3F6"            # 바탕
SURFACE = "#F6FCFD"       # 판
SURFACE_ALT = "#ECF7F9"   # 판(두 번째 톤) — 줄을 번갈아 칠할 때
SUNKEN = "#DCEEF2"        # 가라앉은 곳
TEXT = "#141F2B"
MUTED = "#5A6875"         # 흐린 글자
FAINT = "#8695A3"         # 더 흐린 글자
LINE = "#D2DAE3"
LINE_SOFT = "#E4EAF0"
ACCENT = "#1191B0"; ACCENT_BG = "#DBF1F6"     # 강조 · 이동
TRASH = "#A8501F"; TRASH_BG = "#F5E2D5"       # 격리(치움) — 눈에 띄어야 하는 줄
NEW = "#54479B"; NEW_BG = "#E4E0F4"           # 새로 생김
SKIP = "#6E7C8A"; SKIP_BG = "#E5EAEE"         # 손대지 않음
LIGHTS = ("#FF5F56", "#FFBD2E", "#27C93F")    # 신호등
RADIUS = 4

# ── 폰트 ─────────────────────────────────────────────────────────
# 시안이 지정한 폰트는 리눅스에 없다(실측: 이 WSL 에 47종 중 하나도 없었다).
# 사슬 끝에 각 OS 에서 **실제로 있는 것**을 둔다: 윈도우는 Malgun Gothic ·
# Consolas 가 잡히고, 리눅스는 NanumGothic · DejaVu Sans Mono 가 잡힌다.
BODY_CHAIN = ("IBM Plex Sans KR", "Malgun Gothic", "NanumGothic")
MONO_CHAIN = ("Consolas", "D2Coding", "DejaVu Sans Mono")
BODY_SIZE = 10
MONO_SIZE = 10

# 창이 없어 폰트 목록을 못 물었을 때 쓰는 이름. Tk 가 늘 들고 있는 이름 폰트다.
_FALLBACK_BODY = "TkDefaultFont"
_FALLBACK_MONO = "TkFixedFont"

_CACHE: dict[str, tuple[str, ...]] = {}
_NOTICED = False          # 같은 안내를 계속 찍지 않는다


def _families() -> tuple[str, ...]:
    """이 PC 에 깔린 글꼴 이름들. **창이 없으면 빈 묶음**(예외가 아니다).

    tkinter 는 없는 폰트를 말없이 다른 것으로 바꿔치기한다. 그래서 '있는 것 중
    에서 고른다' 를 우리가 직접 해야 한다.
    """
    if _CACHE.get("families"):
        return _CACHE["families"]
    try:
        from tkinter import font as tkfont
        found = tuple(tkfont.families())
    except Exception:
        # 창이 없거나(RuntimeError) tkinter 자체가 없다. 둘 다 정상적인 상황이다.
        return ()
    if found:
        _CACHE["families"] = found
    return found


def _notice_no_window() -> None:
    """조용히 넘어가지 않는다 — 왜 폰트가 다른지 사람이 알아야 한다."""
    global _NOTICED
    if _NOTICED:
        return
    _NOTICED = True
    print("창이 없어 설치된 글꼴을 확인하지 못했습니다 — 기본 글꼴을 씁니다.",
          file=sys.stderr)


def _pick(chain: tuple[str, ...], fallback: str) -> str:
    families = _families()
    if not families:
        _notice_no_window()
        return fallback
    있는것 = {f.lower() for f in families}
    for name in chain:
        if name.lower() in 있는것:
            return name
    return fallback


def body_font(size: int = BODY_SIZE, *, weight: str = "normal") -> tuple:
    """본문 글꼴. 창이 없으면 기본값을 준다(예외를 던지지 않는다)."""
    family = _pick(BODY_CHAIN, _FALLBACK_BODY)
    return (family, size, "bold") if weight == "bold" else (family, size)


def mono_font(size: int = MONO_SIZE, *, weight: str = "normal") -> tuple:
    """경로·숫자용 고정폭 글꼴. 자릿수가 흔들리면 개수를 비교할 수 없다."""
    family = _pick(MONO_CHAIN, _FALLBACK_MONO)
    return (family, size, "bold") if weight == "bold" else (family, size)


def link_font(size: int = MONO_SIZE) -> tuple:
    """눌러서 탐색기로 여는 경로 글자.

    **밑줄까지 있어야 누를 수 있는 줄로 보인다.** 색만 강조색으로 바꾸면
    "여기는 값이 다르구나" 로 읽히지, 누를 수 있다는 신호가 되지 않는다.
    """
    return (*mono_font(size), "underline")


# ── ttk 스타일 ───────────────────────────────────────────────────
def _shade(color: str, factor: float) -> str:
    """색을 조금 어둡게/밝게. 눌렀을 때의 색은 시안이 정해 두지 않았다.

    상수로 두지 않는 이유: 이름 붙은 색은 **시안에 있는 색뿐**이어야 한다
    (테스트가 그것을 지킨다). 눌림 색은 강조색에서 계산해 쓴다.
    """
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    clamp = lambda v: max(0, min(255, int(v * factor)))
    return f"#{clamp(r):02X}{clamp(g):02X}{clamp(b):02X}"


def apply_theme(window) -> None:
    """ttk 스타일을 Finder 톤으로 맞춘다. **창이 있을 때만 부른다.**"""
    from tkinter import ttk

    style = ttk.Style(window)
    # 'clam' 만이 배경색·테두리를 우리가 시킨 대로 그린다. 윈도우 기본
    # 테마('vista')는 배경 지정을 무시해서 판이 회색으로 남는다.
    if "clam" in style.theme_names():
        style.theme_use("clam")

    body = body_font()
    small = body_font(9)
    window.configure(bg=BG)

    style.configure(".", background=BG, foreground=TEXT, font=body,
                    borderwidth=0, focuscolor=BG)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=SURFACE)
    style.configure("Sunken.TFrame", background=SUNKEN)
    style.configure("Line.TFrame", background=LINE_SOFT)      # 1px 구분선용

    style.configure("TLabel", background=BG, foreground=TEXT, font=body)
    style.configure("Title.TLabel", background=BG, foreground=TEXT,
                    font=body_font(15, weight="bold"))
    style.configure("Lead.TLabel", background=BG, foreground=TEXT, font=body_font(11))
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=small)
    style.configure("Faint.TLabel", background=BG, foreground=FAINT, font=small)
    style.configure("Alert.TLabel", background=BG, foreground=TRASH, font=small)

    # 판(카드) 위에 얹는 글자들. 배경이 다르면 글자 뒤에 네모가 남는다.
    style.configure("CardName.TLabel", background=SURFACE, foreground=TEXT, font=body)
    style.configure("CardPath.TLabel", background=SURFACE, foreground=MUTED,
                    font=mono_font(10))
    style.configure("CardFull.TLabel", background=SURFACE, foreground=FAINT,
                    font=mono_font(8))
    style.configure("CardCount.TLabel", background=SURFACE, foreground=ACCENT,
                    font=mono_font(17, weight="bold"))
    # 문제가 있는 줄(비었거나 없는 폴더)은 격리색으로 — 시선을 끌어야 한다.
    style.configure("CardAlertCount.TLabel", background=SURFACE, foreground=TRASH,
                    font=mono_font(17, weight="bold"))
    style.configure("CardAlert.TLabel", background=SURFACE, foreground=TRASH, font=small)

    style.configure("Primary.TButton", background=ACCENT, foreground="#FFFFFF",
                    font=body, padding=(18, 9), relief="flat", borderwidth=0)
    style.map("Primary.TButton",
              background=[("pressed", _shade(ACCENT, 0.85)),
                          ("active", _shade(ACCENT, 1.12))],
              foreground=[("disabled", FAINT)])
    style.configure("Ghost.TButton", background=SURFACE, foreground=ACCENT,
                    font=body, padding=(18, 9), relief="solid", borderwidth=1,
                    bordercolor=LINE, lightcolor=SURFACE, darkcolor=SURFACE)
    style.map("Ghost.TButton",
              background=[("pressed", SUNKEN), ("active", ACCENT_BG)],
              foreground=[("disabled", FAINT)])
    style.configure("Link.TButton", background=BG, foreground=MUTED,
                    font=small, padding=(4, 2), relief="flat", borderwidth=0)
    style.map("Link.TButton", background=[("active", BG), ("pressed", BG)],
              foreground=[("active", ACCENT)])

    # 대화상자의 글자 입력칸. **OS 기본 모양을 그대로 두지 않는다** — 창은
    # Finder 톤인데 입력칸만 회색 네모면 딴 프로그램에서 뜬 창처럼 보인다.
    style.configure("TEntry", fieldbackground=SURFACE, foreground=TEXT,
                    insertcolor=TEXT, bordercolor=LINE,
                    lightcolor=LINE, darkcolor=LINE, padding=6)
    style.map("TEntry", bordercolor=[("focus", ACCENT)],
              lightcolor=[("focus", ACCENT)], darkcolor=[("focus", ACCENT)])


def traffic_lights(parent, *, bg: str = BG, size: int = 11, gap: int = 7):
    """🔴🟡🟢 점 세 개. 시안의 창틀 느낌만 남기는 작은 장식.

    **가짜 제목표시줄을 만들지 않는다.** 윈도우에는 진짜 제목표시줄이 위에
    그대로 있어서, 창 안에 또 하나를 그리면 두 줄이 되어 흉하다. 화면 제목
    왼쪽에 점만 둔다.
    """
    import tkinter as tk

    canvas = tk.Canvas(parent, width=size * 3 + gap * 2, height=size,
                       bg=bg, highlightthickness=0, bd=0, takefocus=0)
    for i, color in enumerate(LIGHTS):
        x = i * (size + gap)
        canvas.create_oval(x, 1, x + size - 2, size - 1, fill=color, outline="")
    return canvas
