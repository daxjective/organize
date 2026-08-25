"""화면 2 에서 **위젯을 떼어낸** 부분. 창 없이 돌아야 한다.

창을 띄우는 코드는 자동 테스트하기 어렵다. 그래서 판단하는 대목(순서 바꾸기,
파일 체크 묶기, 탭 세기, 도착 자리 적기)만 순수 함수로 빼 두고 여기서 확인한다.
**위젯을 만들었다는 사실만 확인하는 테스트는 여기 두지 않는다** — 그건 아무것도
검사하지 않는다.
"""

from pathlib import Path

from organize.gui import (arrange_steps, dest_text, foot_text, keeps_preview,
                          kind_tabs, move_item, row_checks, toggle_file_key,
                          _raw_kind)
from organize.gui_model import Row, _KIND_LABEL


# ── ▲▼ 순서 바꾸기 ───────────────────────────────────────────────
def test_move_item_위로():
    assert move_item(["a", "b", "c"], 1, -1) == (["b", "a", "c"], 0)


def test_move_item_아래로():
    assert move_item(["a", "b", "c"], 1, 1) == (["a", "c", "b"], 2)


def test_move_item_맨_위에서_위로는_아무_일도_안_한다():
    # 목록이 그대로여야 부르는 쪽이 set_steps 를 건너뛴다 — 안 그러면 아무것도
    # 안 바뀌었는데 멀쩡한 미리보기가 무효가 된다.
    assert move_item(["a", "b"], 0, -1) == (["a", "b"], 0)


def test_move_item_맨_아래에서_아래로는_아무_일도_안_한다():
    assert move_item(["a", "b"], 1, 1) == (["a", "b"], 1)


def test_move_item_고른_줄이_없으면_그대로():
    assert move_item(["a", "b"], None, -1) == (["a", "b"], None)


def test_move_item_은_받은_목록을_고치지_않는다():
    원본 = ["a", "b", "c"]
    move_item(원본, 0, 1)
    assert 원본 == ["a", "b", "c"]


# ── 레시피를 고른 뒤의 줄 순서 ───────────────────────────────────
def test_arrange_steps_는_켠_것을_실행_순서대로_위에_둔다():
    # 보이는 순서가 곧 실행 순서라고 화면이 약속한다. 레시피가 route → dedup
    # 순이면 화면도 그 순서여야 한다(카탈로그 순서가 아니다).
    assert arrange_steps(["unzip", "dedup", "route"], ["route", "dedup"]) == \
        ["route", "dedup", "unzip"]


def test_arrange_steps_는_카탈로그에_없는_id_를_버린다():
    # 못 알아본 step 은 unmatched_steps() 가 따로 알린다. 여기서 줄을 만들면
    # 체크할 수 없는 유령 줄이 생긴다.
    assert arrange_steps(["a", "b"], ["b", "모르는것"]) == ["b", "a"]


# ── 파일별 체크 묶기 ─────────────────────────────────────────────
def test_toggle_file_key_끄면_들어가고_켜면_빠진다():
    뺀것 = toggle_file_key(set(), "/x/a.pdf", False)
    assert 뺀것 == {"/x/a.pdf"}
    assert toggle_file_key(뺀것, "/x/a.pdf", True) == set()


def test_toggle_file_key_열쇠가_없는_줄은_아무_일도_안_한다():
    # 폴더 생성처럼 어느 파일 것도 아닌 줄은 뺄 수 있는 대상이 아니다.
    assert toggle_file_key({"/x/a.pdf"}, "", False) == {"/x/a.pdf"}


def test_toggle_file_key_는_받은_묶음을_고치지_않는다():
    원본 = {"/x/a.pdf"}
    toggle_file_key(원본, "/x/b.pdf", False)
    assert 원본 == {"/x/a.pdf"}


def test_row_checks_하나를_끄면_같은_열쇠의_줄이_전부_꺼진다():
    # 한 파일이 두 번 옮겨지면 줄은 둘인데 파일은 하나다. 체크가 줄마다
    # 따로 놀면 사용자는 "껐는데 옮겨졌다" 를 보게 된다.
    rows = [Row(kind="이동", name="a.pdf", dest="/r/1", reason="", key="/r/a.pdf"),
            Row(kind="이동", name="a.pdf", dest="/r/2", reason="", key="/r/a.pdf"),
            Row(kind="이동", name="b.pdf", dest="/r/3", reason="", key="/r/b.pdf")]
    assert row_checks(rows, {"/r/a.pdf"}) == [False, False, True]


def test_row_checks_열쇠가_빈_줄에는_체크박스를_두지_않는다():
    # 폴더 생성 · 압축 안에서 나올 파일. 아직 없는 것을 빼 달라고 할 수 없다.
    rows = [Row(kind="폴더 생성", name="", dest="/r/01_Docs", reason="", key=""),
            Row(kind="이동", name="b.pdf", dest="/r/3", reason="", key="/r/b.pdf")]
    assert row_checks(rows, set()) == [None, True]


# ── 결과 탭 ──────────────────────────────────────────────────────
def test_kind_tabs_는_종류를_합쳐_세지_않는다():
    # 이 프로젝트는 이미 한 번 "2건" 이 실제로는 폴더 1 + 파일 1 이었다.
    탭 = kind_tabs({"move": 1, "mkdir": 1})
    assert 탭 == [("move", "이동", 1), ("mkdir", "폴더 생성", 1)]


def test_kind_tabs_는_0건인_종류에_탭을_만들지_않는다():
    assert kind_tabs({"move": 3, "quarantine": 0}) == [("move", "이동", 3)]


def test_kind_tabs_순서는_이동_격리_압축해제_폴더생성():
    탭 = kind_tabs({"mkdir": 1, "extract": 2, "quarantine": 3, "move": 4})
    assert [k for k, _, _ in 탭] == ["move", "quarantine", "extract", "mkdir"]


def test_이름표를_되짚으면_원래_종류가_나온다():
    # 표의 줄(`Row.kind`)은 이름표, 탭(`counts`)은 원래 이름이다. 둘을 맞대는
    # 표가 어긋나면 탭을 눌러도 줄이 하나도 안 보인다.
    for kind, label in _KIND_LABEL.items():
        assert _raw_kind(label) == kind


# ── 도착 자리 ────────────────────────────────────────────────────
def test_dest_text_정리_대상_안이면_상대_경로만():
    assert dest_text("/root/01_Docs/a.pdf", Path("/root")) == "01_Docs/a.pdf"


def test_dest_text_밖으로_나가면_전체_경로를_보여준다():
    # 밖으로 나가는 것은 무게가 다른 일이다. 어디로 가는지 다 보여야 한다.
    assert dest_text("/backup/01_Docs/a.pdf", Path("/root")).endswith(
        "/backup/01_Docs/a.pdf")


def test_dest_text_대상을_아직_안_골랐어도_죽지_않는다():
    assert dest_text("/backup/a.pdf", None) == "/backup/a.pdf"


def test_dest_text_도착_자리가_없는_줄은_빈_칸():
    assert dest_text("", Path("/root")) == ""


# ── 설정을 바꾼 뒤 표와 [실행] 을 그대로 둘 수 있는가 ────────────
# `keeps_preview` 가 화면 2 의 두 결함을 한 자리에서 막는다.
#   · 무조건 지우면 → 같은 값을 다시 골랐을 때 표만 비고 [실행] 은 켜진 채다.
#   · 지문만 보면 → 도는 중에 같은 값을 다시 고른 것까지 "바뀌었다" 로 읽는다.

def test_keeps_preview_같은_값을_다시_골랐으면_그대로_둔다():
    # 표만 지우고 [실행] 을 켜 둔 채로 남기면, 확인 대화상자의 요약이 빈칸이 된다.
    지문 = ("/root", "정리", ["dedup"], [], [])
    assert keeps_preview(지문, 지문, True) is True


def test_keeps_preview_설정이_진짜_바뀌면_버린다():
    앞 = ("/root", "정리", ["dedup"], [], [])
    뒤 = ("/other", "정리", ["dedup"], [], [])
    assert keeps_preview(앞, 뒤, True) is False


def test_keeps_preview_켠_작업이_바뀌어도_버린다():
    앞 = ("/root", None, ["unzip", "dedup"], [], [])
    뒤 = ("/root", None, ["unzip"], [], [])
    assert keeps_preview(앞, 뒤, True) is False


def test_keeps_preview_실행할_수_없다고_하면_지문이_같아도_버린다():
    # 세션이 이미 계획을 버린 뒤다(set_steps 는 값이 같아 보여도 무조건 버린다).
    # 표만 남겨 두면 화면은 계획을 보여주는데 [실행] 은 꺼져 있다.
    지문 = ("/root", "정리", ["dedup"], [], [])
    assert keeps_preview(지문, 지문, False) is False


# ── 표 아래 항상 보이는 줄 ───────────────────────────────────────
def test_foot_text_잘린_줄이_있으면_이유를_맨_앞에_적는다():
    # 250줄이면 표 안의 안내는 4233px 중 맨 아래라 200줄을 내려야 보인다.
    # 못 본 사람은 "전부 봤다" 고 믿고 [실행] 을 누른다.
    말 = foot_text({"move": 260}, skipped=0, hidden=60)
    assert 말.startswith("⚠"), 말
    assert "60줄" in 말


def test_foot_text_잘린_줄이_없으면_경고를_적지_않는다():
    말 = foot_text({"move": 3}, skipped=1)
    assert "⚠" not in 말
    assert "손대지 않음 1개" in 말


def test_foot_text_잘렸어도_손대지_않음_설명은_그대로_남는다():
    # 경고를 얹느라 원래 있던 설명이 밀려나면 안 된다.
    말 = foot_text({"extract": 2, "mkdir": 1}, skipped=5, hidden=10)
    assert "손대지 않음 5개" in 말
    assert "압축 안에서 나올 파일" in 말
    assert "폴더 생성은 파일이 아니라" in 말
