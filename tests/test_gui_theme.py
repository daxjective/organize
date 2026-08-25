"""Finder 톤이 **시안 문서와 같은가**. 창을 띄우지 않는다.

색을 손으로 옮겨 적어 두면, 시안이 바뀌었을 때 아무도 모른다. 그래서 이
테스트는 시안 문서(`docs/superpowers/specs/2026-08-25-gui-design.md`)를 직접
읽어서 비교한다. 문서가 바뀌면 여기가 빨개진다.
"""

import re
from pathlib import Path

import pytest

from organize import gui_theme

SPEC = (Path(__file__).resolve().parent.parent
        / "docs" / "superpowers" / "specs" / "2026-08-25-gui-design.md")

_HEX = re.compile(r"#[0-9A-Fa-f]{6}")


def 톤_절() -> str:
    """시안 문서에서 '톤 — Finder' 절만 잘라 온다."""
    글 = SPEC.read_text(encoding="utf-8")
    시작 = 글.index("## 톤 — Finder")
    끝 = 글.index("## ", 시작 + 3)
    return 글[시작:끝]


def 표_행() -> dict[str, tuple[list[str], list[str]]]:
    """색표를 {쓰임: (앞칸 색들, 뒷칸 색들)} 로 읽는다."""
    out: dict[str, tuple[list[str], list[str]]] = {}
    for 줄 in 톤_절().splitlines():
        칸 = [c.strip() for c in 줄.strip().strip("|").split("|")]
        if len(칸) != 3 or 칸[0] in ("쓰임", "---"):
            continue
        if not _HEX.search(줄):
            continue
        out[칸[0]] = ([h.upper() for h in _HEX.findall(칸[1])],
                      [h.upper() for h in _HEX.findall(칸[2])])
    return out


def 상수들() -> dict[str, str]:
    """gui_theme 이 들고 있는 색 상수 전부(대문자 이름만)."""
    out: dict[str, str] = {}
    for 이름, 값 in vars(gui_theme).items():
        if not 이름.isupper():
            continue
        if isinstance(값, str) and _HEX.fullmatch(값):
            out[이름] = 값.upper()
        elif isinstance(값, tuple) and all(
                isinstance(v, str) and _HEX.fullmatch(v) for v in 값):
            for i, v in enumerate(값):
                out[f"{이름}[{i}]"] = v.upper()
    return out


# ── 색 ───────────────────────────────────────────────────────────
def test_시안에_있는_색은_전부_이름을_갖고_있다():
    문서색 = {h.upper() for h in _HEX.findall(톤_절())}
    assert 문서색 - set(상수들().values()) == set()


def test_이름이_붙은_색은_전부_시안에_있는_색이다():
    """코드에만 있는 색은 아무도 고르지 않은 색이다."""
    문서색 = {h.upper() for h in _HEX.findall(톤_절())}
    assert set(상수들().values()) - 문서색 == set()


@pytest.mark.parametrize("쓰임, 앞, 뒤", [
    ("바탕", ["BG"], []),
    ("판 (surface)", ["SURFACE", "SURFACE_ALT"], ["SUNKEN"]),
    ("글자", ["TEXT"], ["MUTED", "FAINT"]),
    ("선", ["LINE"], ["LINE_SOFT"]),
    ("강조 · 이동", ["ACCENT"], ["ACCENT_BG"]),
    ("격리(치움)", ["TRASH"], ["TRASH_BG"]),
    ("새로 생김", ["NEW"], ["NEW_BG"]),
    ("손대지 않음", ["SKIP"], ["SKIP_BG"]),
])
def test_색표_한_줄씩_상수와_짝이_맞는다(쓰임, 앞, 뒤):
    행 = 표_행()
    assert 쓰임 in 행, f"시안 색표에서 '{쓰임}' 줄을 못 찾았습니다"
    문서앞, 문서뒤 = 행[쓰임]
    assert 문서앞 == [getattr(gui_theme, n).upper() for n in 앞]
    assert 문서뒤 == [getattr(gui_theme, n).upper() for n in 뒤]


def test_신호등_세_점이_시안_순서와_같다():
    줄 = next(l for l in 톤_절().splitlines() if "신호등" in l)
    assert [h.upper() for h in _HEX.findall(줄)] == [c.upper() for c in gui_theme.LIGHTS]


def test_모서리_반경이_시안과_같다():
    적힌값 = re.search(r"모서리 반경 `(\d+)px`", 톤_절()).group(1)
    assert gui_theme.RADIUS == int(적힌값)


# ── 폰트 ─────────────────────────────────────────────────────────
def test_창이_없어도_폰트를_돌려준다_예외가_아니다():
    """창 없이 부르는 일은 실제로 있다(테스트·CLI). 죽으면 안 된다."""
    for 폰트 in (gui_theme.body_font(), gui_theme.mono_font()):
        assert isinstance(폰트, tuple)
        assert isinstance(폰트[0], str) and 폰트[0]
        assert isinstance(폰트[1], int) and 폰트[1] > 0


def test_창이_없으면_한국어로_알린다_조용히_넘어가지_않는다(capsys, monkeypatch):
    monkeypatch.setattr(gui_theme, "_NOTICED", False)
    monkeypatch.setattr(gui_theme, "_families", lambda: ())
    gui_theme.body_font()
    알림 = capsys.readouterr().err
    assert "창" in 알림 and "기본" in 알림


def test_폰트_사슬_끝에_리눅스에_실제로_있는_것이_있다():
    """시안이 지정한 폰트는 이 WSL 에 하나도 없다(실측). 사슬이 끊기면 안 된다."""
    assert gui_theme.BODY_CHAIN[:2] == ("IBM Plex Sans KR", "Malgun Gothic")
    assert "NanumGothic" in gui_theme.BODY_CHAIN
    assert gui_theme.MONO_CHAIN[:2] == ("Consolas", "D2Coding")
    assert "DejaVu Sans Mono" in gui_theme.MONO_CHAIN


def test_설치된_것_중에서_고른다(monkeypatch):
    monkeypatch.setattr(gui_theme, "_families", lambda: ("NanumGothic", "DejaVu Sans Mono"))
    assert gui_theme.body_font()[0] == "NanumGothic"
    assert gui_theme.mono_font()[0] == "DejaVu Sans Mono"


def test_앞에_있는_것을_먼저_고른다(monkeypatch):
    monkeypatch.setattr(gui_theme, "_families",
                        lambda: ("NanumGothic", "Malgun Gothic", "DejaVu Sans Mono"))
    assert gui_theme.body_font()[0] == "Malgun Gothic"


def test_굵게_는_세_번째_칸으로_나간다(monkeypatch):
    monkeypatch.setattr(gui_theme, "_families", lambda: ("Malgun Gothic",))
    assert gui_theme.body_font(14, weight="bold") == ("Malgun Gothic", 14, "bold")
