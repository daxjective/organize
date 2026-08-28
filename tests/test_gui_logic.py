"""화면 2 에서 **위젯을 떼어낸** 부분. 창 없이 돌아야 한다.

창을 띄우는 코드는 자동 테스트하기 어렵다. 그래서 판단하는 대목(순서 바꾸기,
파일 체크 묶기, 탭 세기, 도착 자리 적기)만 순수 함수로 빼 두고 여기서 확인한다.
**위젯을 만들었다는 사실만 확인하는 테스트는 여기 두지 않는다** — 그건 아무것도
검사하지 않는다.
"""

from pathlib import Path

from organize import folders
from organize.folders import FolderInfo
from organize.gui import (arrange_steps, builtin_places, control_locks, custom_places,
                          dest_text, foot_text, group_rows, keeps_preview, kind_tabs,
                          local_place_names, move_item, name_width, new_place_error,
                          openable, place_path_width,
                          KIND_LABEL, HELP_SECTIONS, why_disabled, recipe_display,
                          profile_folder_names, row_checks, toggle_file_key,
                          undo_label, undo_prompt, _raw_kind,
                          _ORDER_NOTE, _MOVE_NOTE,
                          blocked_steps, step_makes, step_needs,
                          text_width, _short)
from organize.gui_model import Row, _KIND_LABEL
from organize.userconfig import UserConfig


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
    assert "압축 안에서 나올 파일" in 말, \
        "눈앞의 줄에 체크박스가 없는 이유는 도움말이 아니라 여기 있어야 한다"


# ── 일이 도는 동안 무엇이 잠기는가 ───────────────────────────────
# 실측 결함: 버튼 셋만 잠그고 대상 드롭다운을 열어 둔 탓에, 실행이 도는 3초
# 사이에 대상을 바꾸면 끝난 뒤 화면은 다운로드를 가리키는데 되돌아가는 것은
# 바탕화면이었다. 그래서 잠금 판단을 여기 한 곳으로 모았다.

def _locks(**바꿀것):
    기본 = dict(busy=False, can_preview=True, can_apply=True, can_undo=True,
              has_recipes=True, has_targets=True)
    기본.update(바꿀것)
    return control_locks(**기본)


def test_도는_동안에는_하나도_안_눌린다():
    on = _locks(busy=True)
    assert on == {k: False for k in on}, on


def test_잠기는_것에_대상_레시피_체크박스_순서바꾸기_설정링크가_모두_들어간다():
    # 하나라도 빠지면 그 조작만 결함으로 남는다 — 이번 결함이 정확히 그 모양이었다.
    # 'settings' 가 빠져 있어서, 미리보기가 도는 중에 [설정 · 폴더 위치] 로
    # 들어가 **정리 중인 바로 그 대상의 등록을 [지우기] 로 지울 수 있었다.**
    assert set(_locks()) >= {"preview", "apply", "undo", "save",
                             "recipe", "target", "steps", "order", "settings"}


def test_일이_끝나면_전부_다시_켜진다():
    # 잠근 채로 남으면 창이 영영 굳는다.
    on = _locks(busy=False)
    assert all(on.values()), on


def test_도는_중이_아니면_버튼은_오직_세션이_정한다():
    on = _locks(can_preview=True, can_apply=False, can_undo=False)
    assert (on["preview"], on["apply"], on["undo"]) == (True, False, False)


def test_고를_것이_없는_드롭다운은_도는_중이_아니어도_꺼진다():
    on = _locks(has_recipes=False, has_targets=False)
    assert on["recipe"] is False and on["target"] is False
    # 그렇다고 나머지까지 꺼지지는 않는다.
    assert on["steps"] is True and on["order"] is True


# ── 되돌리기 확인 대화상자 ───────────────────────────────────────
class _가짜폴더:
    def __init__(self, label, path):
        self.label, self.path = label, path


def test_undo_label_은_드롭다운에_보이던_이름을_쓴다():
    바탕 = Path("/home/나/Desktop")
    targets = {"바탕화면": _가짜폴더("바탕화면", 바탕),
               "다운로드": _가짜폴더("다운로드", Path("/home/나/Downloads"))}
    assert undo_label(바탕, targets) == "바탕화면"


def test_undo_label_등록_안_된_폴더는_폴더_이름으로():
    assert undo_label(Path("/mnt/d/보관함"), {}) == "보관함"


def test_undo_prompt_에_폴더_이름과_경로가_둘_다_나온다():
    # 되돌릴 대상이 무엇인지 **글자로** 보이는 것이 이 대화상자의 목적이다.
    말 = undo_prompt("바탕화면", Path("/home/나/Desktop"))
    assert "「바탕화면」" in 말
    assert "Desktop" in 말
    assert "계속할까요?" in 말


def test_undo_prompt_이름을_모를_때도_말이_되게_적는다():
    말 = undo_prompt("", Path("/home/나/Desktop"))
    assert "「" not in 말 and "이 폴더의" in 말
    assert "Desktop" in 말


# ── 화면 3 — 설정 · 폴더 위치 ────────────────────────────────────
# 창을 못 띄우는 곳에서도 **무엇을 적을지**는 확인할 수 있어야 한다.

def _info(name, label, path, *, count=3, status="", builtin=True,
          problem="", hidden_duplicate_of=None):
    return FolderInfo(name=name, label=label, path=Path(path), count=count,
                      status=status, builtin=builtin, problem=problem,
                      hidden_duplicate_of=hidden_duplicate_of)


def test_builtin_places_정상인_줄은_조용히_둔다():
    줄 = builtin_places([_info("desktop", "바탕화면", "/home/나/Desktop")], set())[0]
    assert 줄.note == "정상" and 줄.alert is False


def test_builtin_places_홈은_목록에서_뺀다():
    # 홈 전체는 정리 대상이 아니다. 목록에 두면 겁만 준다.
    infos = [_info("home", "홈", "/home/나"),
             _info("desktop", "바탕화면", "/home/나/Desktop")]
    assert [p.name for p in builtin_places(infos, set())] == ["desktop"]


def test_builtin_places_파일이_0개면_빨갛게():
    """OneDrive 백업이 켜진 PC 의 신호다 — 진짜 바탕화면이 다른 곳에 있다."""
    줄 = builtin_places([_info("desktop", "바탕화면", "/x", count=0)], set())[0]
    assert 줄.alert is True and 줄.note == "비어 있습니다"


def test_builtin_places_폴더가_없으면_빨갛게():
    줄 = builtin_places([_info("pictures", "사진", "/x", count=None,
                               status="폴더 없음")], set())[0]
    assert 줄.alert is True and "폴더가 없습니다" == 줄.note


def test_builtin_places_이름이_안_풀린_줄은_빨갛게_이유까지_적는다():
    """줄이 사라지면 [다시 지정] 도 같이 사라져 창만으로는 고칠 수 없다."""
    줄 = builtin_places([_info("desktop", "바탕화면", "@desktop", count=None,
                              status=folders.UNRESOLVED,
                              problem="'@desktop' 위치가 돌고 돌아 자기 자신을 가리킵니다")],
                       set())[0]
    assert 줄.alert is True
    assert "돌고" in 줄.note, "무엇이 문제인지 그대로 적어야 한다"
    assert 줄.path == "—", "어디인지 모르므로 경로 자리는 비운다(긴 이유에 자리를 내준다)"


def test_builtin_places_같은_폴더라_뺀_줄도_이유를_달고_남는다():
    """**빼는 것과 없애는 것은 다르다.**

    '문서' 를 다운로드와 같은 폴더로 고르면 그 줄이 세 곳 모두에서 조용히
    사라지고, [기본 위치로] 까지 같이 사라져 되돌릴 방법이 없었다. 실측한 결함.
    잘못된 상태는 아니므로 **빨갛게 하지는 않는다** — 회색으로 이유만 적는다.
    """
    infos = [_info("downloads", "다운로드", "/x"),
             _info("documents", "문서", "/x", hidden_duplicate_of="downloads")]
    줄 = {p.name: p for p in builtin_places(infos, {"documents"})}
    assert "documents" in 줄, "이름이 조용히 사라지면 안 된다"
    assert 줄["documents"].alert is False
    assert "다운로드" in 줄["documents"].note
    assert 줄["documents"].pinned is True, \
        "[기본 위치로] 가 있어야 창만으로 되돌릴 수 있다"


def test_builtin_places_직접_지정한_줄만_pinned():
    infos = [_info("desktop", "바탕화면", "/a"), _info("pictures", "사진", "/b")]
    표 = {p.name: p.pinned for p in builtin_places(infos, {"desktop"})}
    assert 표 == {"desktop": True, "pictures": False}


def test_builtin_places_내장이_아닌_줄은_이_칸에_안_들어온다():
    infos = [_info("백업", "백업", "/mnt/usb", builtin=False)]
    assert builtin_places(infos, set()) == []


def test_custom_places_있는_폴더는_조용히(tmp_path):
    (tmp_path / "USB").mkdir()
    cfg = UserConfig(paths={"백업": [str(tmp_path / "USB")]}, folder_names={})
    줄 = custom_places(cfg, {"백업"})[0]
    assert 줄.alert is False and 줄.note == "" and 줄.pinned is True


def test_custom_places_안_꽂힌_USB는_빨갛게_하되_지우지_않는다(tmp_path):
    cfg = UserConfig(paths={"백업": [str(tmp_path / "안꽂힘")]}, folder_names={})
    줄들 = custom_places(cfg, {"백업"})
    assert len(줄들) == 1, "없다고 목록에서 빼면 안 된다"
    assert 줄들[0].alert is True and 줄들[0].note == "없음 · 다시 지정"


def test_custom_places_내장_이름은_두_번_적지_않는다(tmp_path):
    """`organize paths` 가 같은 줄을 두 번 찍던 것과 같은 문제다 —
    내장 이름을 등록하면 '자동으로 찾은 위치' 칸에 이미 나온다."""
    cfg = UserConfig(paths={"desktop": [str(tmp_path)], "백업": [str(tmp_path)]},
                     folder_names={})
    assert [p.name for p in custom_places(cfg, set())] == ["백업"]


def test_custom_places_공용_설정에서_온_이름은_pinned가_아니다(tmp_path):
    cfg = UserConfig(paths={"archive": [str(tmp_path)]}, folder_names={})
    assert custom_places(cfg, set())[0].pinned is False


def test_custom_places_돌고_도는_별칭은_그_줄만_빨갛게(tmp_path):
    """목록 전체가 죽는 것보다 그 줄에 이유를 적는 편이 낫다."""
    cfg = UserConfig(paths={"고리": ["@고리"], "백업": [str(tmp_path)]}, folder_names={})
    표 = {p.name: p for p in custom_places(cfg, set())}
    assert 표["고리"].alert is True and "돌고 돌아" in 표["고리"].note
    assert 표["백업"].alert is False, "한 줄이 이상해도 나머지는 보여야 한다"


def test_local_place_names_파일이_없으면_빈_묶음(tmp_path):
    assert local_place_names(tmp_path) == set()


def test_local_place_names_는_이_PC_설정만_읽는다(tmp_path):
    (tmp_path / "config.default.json").write_text(
        '{"paths": {"archive": "D:/보관"}}', encoding="utf-8")
    (tmp_path / "config.local.json").write_text(
        '{"paths": {"백업": "E:/백업"}}', encoding="utf-8")
    assert local_place_names(tmp_path) == {"백업"}


def test_local_place_names_설정이_깨져도_죽지_않는다(tmp_path):
    (tmp_path / "config.local.json").write_text("{망가짐", encoding="utf-8")
    assert local_place_names(tmp_path) == set()


def test_new_place_error_빈_이름():
    assert new_place_error("   ", UserConfig()) == "이름이 비어 있습니다."


def test_new_place_error_이미_있는_이름():
    말 = new_place_error("백업", UserConfig(paths={"백업": ["D:/x"]}))
    assert 말 and "이미 있는 이름" in 말


def test_new_place_error_앞에_붙인_골뱅이는_막는다():
    말 = new_place_error("@백업", UserConfig())
    assert 말 and "@" in 말


def test_new_place_error_슬래시는_막는다():
    """`@백업/사진` 의 뒷부분과 구분이 안 된다 — 등록해도 영영 안 풀린다."""
    assert new_place_error("백업/사진", UserConfig()) is not None
    assert new_place_error("백업\\사진", UserConfig()) is not None


def test_new_place_error_내장_이름은_막는다():
    """cfg.paths 만 보면 내장 이름이 그대로 통과한다 — 저장하면 `resolve_alias`
    가 사용자 값을 먼저 보기 때문에 **그 내장 폴더가 조용히 옮겨간다.**

    화면은 "저장했습니다" 라고 답하는데 '내가 추가한 위치' 에는 안 생기고,
    대신 '바탕화면' 줄의 경로가 바뀐다. 다음 정리에서 화면이 말한 폴더가 아닌
    폴더의 파일이 움직인다. 실측한 결함이다.
    """
    for 이름 in ("desktop", "downloads", "documents", "pictures", "music",
                "videos", "home"):
        말 = new_place_error(이름, UserConfig())
        assert 말 and 이름 in 말, f"{이름} 을 막지 않았다: {말}"
        assert "다른 이름" in 말, f"무엇을 하면 되는지 알려야 한다: {말}"


def test_new_place_error_멀쩡한_이름은_통과한다():
    assert new_place_error("  백업드라이브  ", UserConfig()) is None


def test_profile_folder_names_는_실제로_만들_폴더를_모은다(tmp_path):
    (tmp_path / "a.toml").write_text(
        'name = "바탕화면 정리"\n'
        '[[rules]]\n to = "01_Docs"\n ext = [".pdf"]\n'
        '[[rules]]\n to = "01_Docs"\n ext = [".md"]\n'
        '[[rules]]\n to = "99_Unsorted"\n default = true\n', encoding="utf-8")
    (보일이름, 폴더들, 문제), = profile_folder_names(tmp_path)
    assert 보일이름 == "바탕화면 정리"
    assert 폴더들 == ["01_Docs", "99_Unsorted"], "같은 이름을 두 번 적지 않는다"
    assert 문제 == ""


def test_profile_folder_names_못_읽는_파일도_숨기지_않는다(tmp_path):
    """조용히 빼면 사용자는 그 프로파일이 없는 줄 안다."""
    (tmp_path / "깨진것.toml").write_text("이건 = TOML 이 아니다 [[", encoding="utf-8")
    (보일이름, 폴더들, 문제), = profile_folder_names(tmp_path)
    assert 보일이름 == "깨진것" and 폴더들 == [] and 문제


# ── 경로를 눌러서 탐색기로 열기 ─────────────────────────────────
# **눌러도 아무 일이 없는 링크를 그리지 않는 것**이 여기서 지킬 것이다.
# 그런 링크는 "안 열리는구나" 가 아니라 "도구가 고장났구나" 로 읽힌다.

def test_openable_정상인_폴더는_열_수_있다():
    assert openable(_info("desktop", "바탕화면", "/home/나/Desktop")) is True


def test_openable_비어_있어도_열_수_있다():
    """개수가 0 인 줄이야말로 열어 봐야 한다 — OneDrive 백업이 켜진 PC 의 신호다."""
    assert openable(_info("desktop", "바탕화면", "/x", count=0)) is True


def test_openable_읽을_수_없는_폴더도_열_수_있다():
    """권한 문제는 탐색기에서 고친다 — 거기로 보내 주는 자리다."""
    assert openable(_info("사진", "사진", "/x", count=None, status="읽을 수 없음")) is True


def test_openable_없는_폴더는_열_수_없다():
    assert openable(_info("사진", "사진", "/x", count=None, status="폴더 없음")) is False


def test_openable_어디인지_모르는_줄은_열_수_없다():
    assert openable(_info("desktop", "바탕화면", "@desktop", count=None,
                          status=folders.UNRESOLVED)) is False


def test_builtin_places_열_수_있는_줄에만_진짜_경로가_붙는다():
    """`path` 는 가운데를 접은 **보여주기용** 글자라 그걸로는 못 연다."""
    긴것 = "/home/나/" + "아주긴폴더이름" * 6 + "/Desktop"
    줄 = builtin_places([_info("desktop", "바탕화면", 긴것)], set())[0]
    assert "…" in 줄.path, "보여주는 글자는 접힌다"
    assert 줄.open_path == 긴것, "여는 데 쓸 경로는 접지 않은 진짜 경로여야 한다"


def test_builtin_places_없는_폴더는_링크로_만들지_않는다():
    줄 = builtin_places([_info("사진", "사진", "/x", count=None,
                               status="폴더 없음")], set())[0]
    assert 줄.open_path == ""


def test_custom_places_있는_폴더에만_진짜_경로가_붙는다(tmp_path):
    (tmp_path / "USB").mkdir()
    cfg = UserConfig(paths={"백업": [str(tmp_path / "USB")]}, folder_names={})
    assert custom_places(cfg, set())[0].open_path == str(tmp_path / "USB")


def test_custom_places_안_꽂힌_USB는_링크로_만들지_않는다(tmp_path):
    """등록은 남기되, 눌러도 안 열릴 링크는 그리지 않는다."""
    cfg = UserConfig(paths={"백업": [str(tmp_path / "없다")]}, folder_names={})
    줄 = custom_places(cfg, set())[0]
    assert 줄.alert is True and 줄.open_path == ""


def test_name_width_한글은_두_칸씩_잡는다():
    """`width` 는 영문 글자폭 기준이다 — 한글 6자를 6 으로 잡으면 뒤가 잘린다."""
    assert name_width(["백업드라이브"]) >= 12


def test_name_width_가장_긴_이름에_맞춘다():
    """숫자를 못 박으면 그보다 긴 이름에서 같은 일이 다시 난다."""
    좁은것 = name_width(["백업"])
    넓은것 = name_width(["백업", "외장하드백업드라이브"])
    assert 넓은것 > 좁은것 == 12
    assert 넓은것 >= 20, "한글 10자는 20칸쯤 먹는다"


def test_name_width_목록이_비어도_칸은_남는다():
    """줄이 없을 때 0 을 주면 다음에 그릴 때 칸이 무너진다."""
    assert name_width([]) == 12


def test_name_width_영문_이름은_두_배로_잡지_않는다():
    """'archive' 를 14칸으로 잡으면 이름 칸만 허옇게 남는다."""
    assert name_width(["archive", "photos", "work"]) == 12


def test_place_path_width_이름이_짧으면_경로는_그대로():
    from organize.gui import _PLACE_PATH
    assert place_path_width(["백업", "사진"]) == _PLACE_PATH


def test_place_path_width_이름이_길어진_만큼_경로가_자리를_내준다():
    """이름은 못 자르니 경로가 접힌다 — 안 그러면 경로 끝이 잘려 나간다."""
    from organize.gui import _PLACE_PATH
    assert place_path_width(["외장하드백업드라이브"]) == _PLACE_PATH - 8


def test_place_path_width_아무리_긴_이름이라도_경로_조각은_남긴다():
    """앞(드라이브)과 끝(폴더 이름)마저 사라지면 무슨 폴더인지 알 수 없다."""
    assert place_path_width(["아" * 40]) == 24


def test_custom_places_긴_이름이_섞이면_그_칸_경로가_다_같이_접힌다(tmp_path):
    """줄마다 따로 접으면 같은 칸의 경로들이 서로 다른 자리에서 접힌다."""
    긴폴더 = tmp_path / ("아주긴폴더이름" * 5)
    긴폴더.mkdir()
    짧은cfg = UserConfig(paths={"백업": [str(긴폴더)]}, folder_names={})
    긴cfg = UserConfig(paths={"백업": [str(긴폴더)],
                              "외장하드백업드라이브": [str(긴폴더)]}, folder_names={})

    짧을때 = custom_places(짧은cfg, set())[0].path
    길때 = {p.name: p.path for p in custom_places(긴cfg, set())}

    assert len(길때["백업"]) < len(짧을때), "긴 이름이 생기면 경로가 더 접힌다"
    assert len(길때["백업"]) == len(길때["외장하드백업드라이브"]), \
        "같은 칸이면 같은 자리에서 접혀야 한다"


# ── 이름표는 한 곳뿐이다 ────────────────────────────────────────
# 예전에는 cli.py 와 gui_model.py 가 같은 표를 따로 들고 있었다. 말을 바꿀 때
# 한쪽만 바뀌면 같은 파일을 두고 창은 "보류", 명령줄은 "격리" 라고 한다.

def test_창과_명령줄이_같은_이름표를_쓴다():
    from organize import cli, gui_model
    from organize.core.action import KIND_LABEL

    assert cli._KIND_LABEL is KIND_LABEL, "명령줄이 자기 표를 따로 들면 안 된다"
    assert gui_model._KIND_LABEL is KIND_LABEL, "창도 마찬가지다"


def test_요약줄이_이름표를_글자로_다시_적지_않는다():
    """`summary` 가 '격리' 를 글자로 박아 두면 말을 바꿔도 거기만 옛말로 남는다."""
    from organize.core.action import KIND_LABEL
    from organize.gui_model import PreviewView

    말 = PreviewView(counts={"move": 1, "quarantine": 2}, skipped=3).summary

    assert KIND_LABEL["quarantine"] in 말
    assert "격리" not in 말, "옛말이 남아 있으면 안 된다"


def test_보류가_손대지_않음과_헷갈리지_않게_짚어_준다():
    """둘 다 '아무 일 없었다' 로 읽힌다 — 보류는 실제로 폴더를 옮기는 것이다.

    이 설명은 표 아래가 아니라 **[?] 도움말**에 있다. 매번 보이는 자리에 두면
    줄이 네댓 문장으로 불어나 정작 숫자와 ⚠ 경고가 묻힌다.
    """
    도움말 = " ".join(줄 for _, 줄들 in HELP_SECTIONS for 줄 in 줄들)

    assert "다릅니다" in 도움말 and "손대지 않음" in 도움말
    assert "되돌리기" in 도움말, "되살릴 수 있다는 것까지 말해야 안심한다"


def test_표_아래에는_설명이_아니라_이번_실행의_숫자만_남는다():
    """설명까지 늘어놓으면 매번 달라지는 숫자가 그 안에 묻힌다."""
    말 = foot_text({"move": 3, "quarantine": 2}, skipped=9)

    assert "손대지 않음 9개" in 말
    assert "지우지 않고" not in 말, "보류가 무엇인지는 도움말이 설명한다"


def test_도움말이_할_일_다섯_가지를_다_설명한다():
    """체크박스만 보고는 무엇을 하는 작업인지 알 수 없다."""
    from organize import catalog

    도움말 = " ".join(줄 for _, 줄들 in HELP_SECTIONS for 줄 in 줄들)
    빠진것 = [e.label for e in catalog.catalog() if e.label not in 도움말]

    assert not 빠진것, f"도움말에 없는 작업: {빠진것}"


# ── 버튼이 왜 꺼졌는지 ──────────────────────────────────────────
# "미리보기를 눌러도 아무 동작이 없다" — 사실은 눌리지 않는 것인데, 회색 버튼만
# 보고 그 이유를 알아낼 방법이 화면에 하나도 없었다.

def test_why_disabled_폴더를_안_골랐으면_그것부터():
    assert "정리할 폴더" in why_disabled(
        busy=False, has_root=False, has_steps=True, can_apply=False)


def test_why_disabled_할_일이_없으면_그것부터():
    assert "할 일" in why_disabled(
        busy=False, has_root=True, has_steps=False, can_apply=False)


def test_why_disabled_둘_다_없으면_폴더를_먼저_짚는다():
    """세 줄을 한꺼번에 늘어놓으면 지금 무엇을 해야 하는지가 오히려 안 보인다."""
    말 = why_disabled(busy=False, has_root=False, has_steps=False, can_apply=False)
    assert "정리할 폴더" in 말 and "할 일" not in 말


def test_why_disabled_도는_중에는_기다리라고_한다():
    """고장이 아니라 진행 중이라는 것을 말해야 한다."""
    말 = why_disabled(busy=True, has_root=False, has_steps=False, can_apply=False)
    assert "끝나면" in 말


def test_why_disabled_다_갖췄으면_아무_말도_안_한다():
    """누를 수 있는데 이유를 적어 두면 그게 더 헷갈린다."""
    assert why_disabled(busy=False, has_root=True, has_steps=True,
                        can_apply=True) == ""


def test_why_disabled_미리보기_전이면_그렇게_말한다():
    말 = why_disabled(busy=False, has_root=True, has_steps=True, can_apply=False)
    assert "미리보기" in 말


# ── 조합이 어느 폴더용인지 미리 보이기 ──────────────────────────

def test_recipe_display_폴더가_있으면_같이_보인다():
    """고른 뒤에야 상태줄에 나오면 놀란다. 목록에서 미리 보이면 놀랄 일이 아니다."""
    assert recipe_display("다운로드 정리", "다운로드") == "다운로드 정리 → 다운로드"


def test_recipe_display_폴더가_없으면_이름만():
    """모르면 아무 말도 안 하는 편이, 틀린 폴더 이름을 적는 것보다 낫다."""
    assert recipe_display("내조합", "") == "내조합"


# ── 도움말 ───────────────────────────────────────────────────────
def test_도움말이_기계가_뽑은_목록처럼_읽히지_않는다():
    """"압축 해제 — zip 안의…" 처럼 붙임표로 여는 줄이 열두 개였다.

    사람이 쓴 안내가 아니라 뽑아 준 표처럼 읽힌다는 지적을 받았다. 이름 뒤에는
    쌍점(:)을 쓰고, 문장 가운데서는 마침표로 끊는다.
    """
    붙임표줄 = [줄 for _, 줄들 in HELP_SECTIONS for 줄 in 줄들 if "—" in 줄]

    assert not 붙임표줄, f"붙임표가 남은 줄: {붙임표줄}"


def test_도움말이_연도별이_왜_아무_일도_안_하는지_알려준다():
    """켜 놨는데 결과가 비면 고장으로 읽힌다 — 실제로 그렇게 읽혔다.

    연도별 분류는 `02_Media/사진` 안만 본다. 그 앞의 캡처·사진 분리가 꺼져
    있거나, 촬영정보 없는 그림뿐이면 사진 폴더 자체가 안 생긴다.
    """
    도움말 = " ".join(줄 for _, 줄들 in HELP_SECTIONS for 줄 in 줄들)

    assert "02_Media/사진" in 도움말, "어느 폴더를 보는지 적어야 한다"
    assert "캡처·사진 분리를 같이 켜" in 도움말, "무엇을 하면 되는지까지 말해야 한다"
    assert "EXIF" in 도움말 and "스크린샷" in 도움말, "왜 사진으로 안 가는지"


def test_도움말이_어느_작업을_같이_켜야_하는지_알려준다():
    """할 일 다섯 가지를 따로 설명해도, 묶어 쓰는 법은 어디에도 없었다."""
    제목들 = [제목 for 제목, _ in HELP_SECTIONS]

    assert "이럴 땐 이렇게" in 제목들

    줄들 = dict(HELP_SECTIONS)["이럴 땐 이렇게"]
    assert any("바탕화면" in 줄 for 줄 in 줄들)
    assert any("사진 폴더를 정리할 때" in 줄 for 줄 in 줄들)


# ── 한 화면에서 "선택" 을 두 뜻으로 쓰지 않는다 ─────────────────
def test_실행_순서_안내가_ㅅㅐㄱ_선택과_말이_겹치지_않는다():
    """`선택한 항목을 순서대로` 로 바꾸자는 제안이 있었다 — 바꾸면 더 헷갈린다.

    바로 아래 줄의 "선택한 작업 ▲▼ 순서 변경" 에서 '선택' 은 **▲▼ 로 옮길 한
    줄을 고른 것**이다. 위 줄까지 '선택' 을 쓰면 같은 말이 두 가지를 가리켜,
    무엇을 ▲▼ 하는 것인지 알 방법이 없어진다.
    """
    assert "선택" in _MOVE_NOTE, "아래 줄은 '선택' 이 맞다(▲▼ 로 옮길 한 줄)"
    assert "선택" not in _ORDER_NOTE, "위 줄에까지 쓰면 같은 말이 두 뜻이 된다"
    assert "체크" in _ORDER_NOTE, "체크박스를 켠 것이라고 말해야 한다"


# ── 켜 놨는데 아무 일도 못 하는 작업 ────────────────────────────
# "연도별 분류를 선택해도 02_Media 폴더만 생긴다" 는 고장이 아니었다. 그 작업은
# `02_Media/사진` 안만 보는데, 그 폴더를 만드는 「캡처·사진 분리」가 꺼져 있으면
# 볼 것이 없다. **조용한 것이 문제였다** — 켠 사람은 고장으로 읽는다.

def _프로파일들(tmp_path):
    """진짜 프로파일 두 개를 흉내낸다(카탈로그가 그 이름으로 찾는다)."""
    d = tmp_path / "profiles"
    d.mkdir()
    (d / "desktop.toml").write_text(
        'name = "바탕화면"\n'
        '[[rules]]\n to = "01_Docs"\n ext = [".pdf"]\n'
        '[[rules]]\n to = "02_Media"\n ext = [".png"]\n', encoding="utf-8")
    (d / "photos.toml").write_text(
        'name = "사진"\n'
        '[[rules]]\n to = "사진"\n has_exif_camera = true\n'
        '[[rules]]\n to = "캡처"\n has_exif_camera = false\n', encoding="utf-8")
    return d


def test_step_makes_는_target_아래에_만든다(tmp_path):
    """`route` 의 목적지는 dest(없으면 target) 아래다 — BlockConfig.out 그대로."""
    d = _프로파일들(tmp_path)

    assert step_makes({"block": "route", "profile": "desktop"}, d) == ["01_Docs", "02_Media"]
    assert step_makes({"block": "route", "profile": "photos",
                       "target": "02_Media"}, d) == ["02_Media/사진", "02_Media/캡처"]


def test_step_makes_는_route_말고는_모른다(tmp_path):
    """by_date 도 폴더를 만들지만 이름이 파일 날짜에 달려 미리 알 수 없다."""
    d = _프로파일들(tmp_path)

    assert step_makes({"block": "by_date", "target": "02_Media/사진"}, d) == []
    assert step_makes({"block": "dedup"}, d) == []


def test_step_makes_는_못_읽는_프로파일에_안_죽는다(tmp_path):
    """체크박스 줄에 읽지도 못할 오류를 띄우는 것보다 조용한 편이 낫다."""
    assert step_makes({"block": "route", "profile": "없는것"}, tmp_path) == []


def test_step_needs_는_읽을_폴더다():
    assert step_needs({"block": "by_date", "target": "02_Media/사진"}) == "02_Media/사진"
    assert step_needs({"block": "dedup"}) == "", "빈 글자면 정리할 폴더 자신이다"


# ── blocked_steps ───────────────────────────────────────────────
_LABELS = {"route_kind": "종류별 분류", "route_photos": "캡처·사진 분리",
           "by_date_year": "연도별 분류"}
_NEEDS = {"route_kind": "", "route_photos": "02_Media", "by_date_year": "02_Media/사진"}
_MAKES = {"route_kind": ["01_Docs", "02_Media"],
          "route_photos": ["02_Media/사진", "02_Media/캡처"], "by_date_year": []}
_ORDER = ["route_kind", "route_photos", "by_date_year"]


def _막힌것(checked, 있는폴더=()):
    return blocked_steps(_ORDER, labels=_LABELS, needs=_NEEDS, makes=_MAKES,
                         checked=set(checked), exists=lambda rel: rel in 있는폴더)


def test_연도별만_켜면_무엇을_같이_켜야_하는지_말해_준다():
    """이것이 이번 작업의 전부다 — 빈 결과를 보고 고장으로 읽던 그 자리."""
    막힘 = _막힌것(["by_date_year"])

    assert "by_date_year" in 막힘
    assert "캡처·사진 분리" in 막힘["by_date_year"], "무엇을 누르면 되는지까지"
    assert "02_Media/사진" in 막힘["by_date_year"], "어느 폴더가 없는지"


def test_필요한_작업을_앞에_켜면_막히지_않는다():
    assert _막힌것(["route_kind", "route_photos", "by_date_year"]) == {}


def test_켜져_있어도_뒤에_있으면_막힌다():
    """앞 작업이 만든 폴더를 뒤 작업이 쓴다 — 순서가 뒤집히면 볼 것이 없다."""
    거꾸로 = ["by_date_year", "route_kind", "route_photos"]

    막힘 = blocked_steps(거꾸로, labels=_LABELS, needs=_NEEDS, makes=_MAKES,
                       checked={"route_kind", "route_photos", "by_date_year"},
                       exists=lambda _r: False)

    assert "▲▼" in 막힘["by_date_year"], "순서를 바꾸라고 말해야 한다"
    assert "캡처·사진 분리" in 막힘["by_date_year"]


def test_그_폴더가_이미_디스크에_있으면_경고하지_않는다():
    """지난번 정리로 이미 02_Media/사진 이 있으면 연도별만 켜도 제대로 돈다.

    디스크를 안 보고 경고하면 **틀린 말**을 하게 된다.
    """
    assert _막힌것(["by_date_year"], 있는폴더={"02_Media/사진"}) == {}


def test_꺼_놓은_작업은_경고하지_않는다():
    """켜지도 않은 줄에 경고를 달면 목록이 온통 주황색이 된다."""
    assert _막힌것([]) == {}
    assert "by_date_year" not in _막힌것(["route_kind"])


def test_진짜_카탈로그와_프로파일에서도_사슬이_이어진다():
    """위 테스트들은 흉내낸 표로 **논리만** 본다.

    실제로 그 사슬이 그렇게 이어져 있는지는 진짜 파일을 읽어야 안다 —
    프로파일의 `to` 하나만 바뀌어도 화면의 안내가 조용히 틀린 말이 된다.
    읽기만 한다.
    """
    from organize import catalog

    repo = Path(__file__).resolve().parent.parent
    entries = catalog.catalog()
    makes = {e.id: step_makes(e.step, repo / "profiles") for e in entries}
    needs = {e.id: step_needs(e.step) for e in entries}

    assert "02_Media" in makes["route_kind"], "종류별 분류가 02_Media 를 만든다"
    assert "02_Media/사진" in makes["route_photos"], "캡처·사진 분리가 사진 폴더를 만든다"
    assert needs["by_date_year"] == "02_Media/사진", "연도별은 사진 폴더만 본다"

    막힘 = blocked_steps([e.id for e in entries],
                       labels={e.id: e.label for e in entries},
                       needs=needs, makes=makes,
                       checked={"by_date_year"}, exists=lambda _r: False)

    assert "캡처·사진 분리" in 막힘["by_date_year"]


def test_처음_켜져_있는_작업들만으로는_아무것도_막히지_않는다():
    """창을 열자마자 주황색 경고가 뜨면 그것부터 고장으로 보인다."""
    from organize import catalog

    repo = Path(__file__).resolve().parent.parent
    entries = catalog.catalog()

    막힘 = blocked_steps([e.id for e in entries],
                       labels={e.id: e.label for e in entries},
                       needs={e.id: step_needs(e.step) for e in entries},
                       makes={e.id: step_makes(e.step, repo / "profiles") for e in entries},
                       checked={e.id for e in entries if e.default_on},
                       exists=lambda _r: False)

    assert 막힘 == {}, f"처음부터 막힌 줄이 있다: {막힘}"


# ── 경로 접기는 글자 수가 아니라 칸 수로 ────────────────────────
# 한글은 라틴 글자의 두 배 넓이로 그려진다. 글자 수로 접으면 한글 경로만
# 칸 밖으로 밀려 끝이 잘린다 — 하필 폴더 이름이 있는 쪽이라 눈에 띈다.
# 실측: 설정 화면에서 '없는드라이브' 가 '없는드라(' 로 났다.

def test_text_width_한글은_두_칸():
    assert text_width("abc") == 3
    assert text_width("한글") == 4
    assert text_width("a한b") == 4


def test_짧은_경로는_그대로_둔다():
    assert _short("/home/davin/Desktop", 56) == "/home/davin/Desktop"


def test_한글_경로도_칸_수를_넘지_않는다():
    긴것 = "/tmp/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/home/없는드라이브"

    접힌것 = _short(긴것, 34)

    assert text_width(접힌것) <= 34, f"칸을 넘었다: {text_width(접힌것)}"
    assert 접힌것.endswith("없는드라이브"), "폴더 이름은 남아야 알아본다"


def test_라틴_경로도_칸_수를_넘지_않는다():
    긴것 = "/tmp/claude-1000/-home-davin-project/scratchpad/sandbox/home/Pictures"

    접힌것 = _short(긴것, 34)

    assert text_width(접힌것) <= 34
    assert 접힌것.endswith("Pictures"), "폴더 이름은 남아야 알아본다"
    assert 접힌것.startswith("/tmp/"), "앞쪽(드라이브·루트)도 남는다"


def test_글자_가운데를_쪼개지_않는다():
    """두 칸짜리 글자가 경계에 걸리면 통째로 뺀다 — 반쪽 글자는 못 읽는다."""
    for limit in range(16, 40):
        접힌것 = _short("/aaaa/가나다라마바사아자차카타파하/끝폴더", limit)
        assert text_width(접힌것) <= limit, f"limit={limit} 에서 넘쳤다"


# ── 보류를 무리로 묶는다 ────────────────────────────────────────
def _보류줄(name, keeper):
    return Row(kind="보류", name=name, dest="", reason="", keeper=keeper)


def test_같은_keeper_끼리_묶인다():
    줄들 = [_보류줄("b.pdf", "/집/a.pdf"), _보류줄("x.jpg", "/집/w.jpg"),
           _보류줄("c.pdf", "/집/a.pdf")]

    무리들, 잘린것 = group_rows(줄들, limit=200)

    assert 잘린것 == 0
    assert [k for k, _ in 무리들] == ["/집/a.pdf", "/집/w.jpg"], "keeper 사전순"
    assert [r.name for r in 무리들[0][1]] == ["b.pdf", "c.pdf"], "무리 안은 원래 순서"


def test_keeper_가_없는_줄은_맨_뒤에_한_덩어리로():
    줄들 = [_보류줄("혼자.pdf", ""), _보류줄("b.pdf", "/집/a.pdf")]

    무리들, _ = group_rows(줄들, limit=200)

    assert [k for k, _ in 무리들] == ["/집/a.pdf", ""]
    assert [r.name for r in 무리들[-1][1]] == ["혼자.pdf"]


def test_무리_중간에서_자르지_않는다():
    """머리줄만 있고 파일이 없는 조각이 남으면 안 된다."""
    줄들 = ([_보류줄(f"a{i}.pdf", "/집/A.pdf") for i in range(3)]
           + [_보류줄(f"b{i}.pdf", "/집/B.pdf") for i in range(3)])

    무리들, 잘린것 = group_rows(줄들, limit=4)

    assert [k for k, _ in 무리들] == ["/집/A.pdf"], "두 번째 무리는 통째로 뺀다"
    assert len(무리들[0][1]) == 3, "첫 무리는 통째로 들어간다"
    assert 잘린것 == 3, "못 그린 줄 수를 사실대로 알린다"


def test_첫_무리부터_한도를_넘으면_그것만은_그린다():
    """아무것도 안 그리면 표가 비어 고장으로 보인다."""
    줄들 = [_보류줄(f"a{i}.pdf", "/집/A.pdf") for i in range(10)]

    무리들, 잘린것 = group_rows(줄들, limit=3)

    assert len(무리들) == 1 and len(무리들[0][1]) == 10
    assert 잘린것 == 0


def test_빈_목록이면_빈_결과():
    assert group_rows([], limit=200) == ([], 0)
