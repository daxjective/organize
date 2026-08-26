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
                          dest_text, foot_text, keeps_preview, kind_tabs,
                          local_place_names, move_item, new_place_error,
                          profile_folder_names, row_checks, toggle_file_key,
                          undo_label, undo_prompt, _raw_kind)
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
    assert "압축 안에서 나올 파일" in 말
    assert "폴더 생성은 파일이 아니라" in 말


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
