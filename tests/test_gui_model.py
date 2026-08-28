"""창(위젯) 없이 도는 GUI 로직.

화면에 무엇을 보여줄지 계산하는 일과, 그것을 그리는 일을 나눈다.
계산하는 쪽만 여기서 테스트한다 — tkinter 가 없는 환경에서도 돌아야 하고,
창을 띄우지 않고도 "실행 버튼이 켜지는가" 같은 것을 못박을 수 있어야 한다.
"""

import json
import os
import shutil
import time
from pathlib import Path

import pytest

from organize import catalog
from organize.core.action import KIND_LABEL as _KIND_LABEL
from organize.errors import OrganizeError
from organize.gui_model import Session, landing_folders
from organize.recipes import load_recipe


def old_file(path: Path, data: bytes = b"DATA") -> Path:
    """방금 만든 파일은 '작업 중' 으로 걸러지므로 수정시각을 한 시간 전으로 돌린다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    past = time.time() - 3600
    os.utime(path, (past, past))
    return path


@pytest.fixture
def repo(tmp_path):
    """저장소 구조를 흉내낸다."""
    r = tmp_path / "repo"
    (r / "profiles").mkdir(parents=True)
    (r / "recipes").mkdir()
    (r / "profiles" / "desktop.toml").write_text(
        'name = "테스트"\n'
        '[[rules]]\n to = "01_Docs"\n ext = [".pdf"]\n'
        '[[rules]]\n to = "99_Unsorted"\n default = true\n', encoding="utf-8")
    (r / "recipes" / "정리.json").write_text(json.dumps({
        "name": "정리", "roots": ["@downloads"],
        "steps": [{"block": "route", "profile": "desktop"}],
    }, ensure_ascii=False), encoding="utf-8")
    return r


@pytest.fixture
def work(tmp_path):
    w = tmp_path / "작업"
    w.mkdir()
    old_file(w / "보고서.pdf")
    return w


@pytest.fixture
def real_recipes_repo(tmp_path):
    """저장소의 진짜 recipes/desktop.json · photos.json 과 그에 필요한
    profiles 를 tmp_path 로 복사해 넣는다.

    카탈로그가 진짜 레시피 파일과 알아보는지(또는 일부러 못 알아보는지) 보는
    테스트 전용 — 읽기만 하므로 원본을 복사해 와도 안전하지만, 이 fixture
    자체는 tmp_path 안에서만 쓴다(브리프 8번 규칙과 같은 이유: 실수로 진짜
    파일을 건드리면 안 된다).
    """
    src = Path(__file__).resolve().parent.parent
    r = tmp_path / "repo"
    (r / "recipes").mkdir(parents=True)
    (r / "profiles").mkdir()
    for name in ("desktop.json", "photos.json"):
        shutil.copy(src / "recipes" / name, r / "recipes" / name)
    for name in ("desktop.toml", "photos.toml"):
        shutil.copy(src / "profiles" / name, r / "profiles" / name)
    return r


# ── 고를 수 있는 것들 ──────────────────────────────────────────────

def test_session_lists_the_recipes_it_can_run(repo):
    s = Session(repo_root=repo)
    assert s.recipe_names() == ["정리"]


def test_a_fresh_session_cannot_apply_anything(repo):
    """아무것도 안 골랐으면 실행 버튼은 꺼져 있어야 한다."""
    s = Session(repo_root=repo)
    assert not s.can_apply
    assert not s.can_preview


def test_choosing_a_folder_and_recipe_enables_preview_but_not_apply(repo, work):
    """**미리보기를 보기 전에는 실행할 수 없다.** 이 도구의 핵심 약속이다."""
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    assert s.can_preview
    assert not s.can_apply, "미리보기를 보기 전에 실행 버튼이 켜지면 안 된다"


# ── 미리보기 ──────────────────────────────────────────────────────

def test_preview_produces_rows_a_table_can_draw(repo, work):
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")

    view = s.preview()

    assert view.rows, "보여줄 것이 있어야 한다"
    이동 = [r for r in view.rows if r.kind == "이동"]
    assert len(이동) == 1
    assert 이동[0].name == "보고서.pdf"
    assert "01_Docs" in 이동[0].dest
    assert 이동[0].reason, "왜 거기 가는지 사람이 읽을 말로 있어야 한다"
    assert not 이동[0].leaving, "폴더 안에서 움직이면 '밖으로 나감' 이 아니다"


def test_preview_touches_nothing(repo, work):
    """미리보기는 파일을 건드리지 않는다 — 창에서 눌러도 마찬가지다."""
    before = sorted(p.name for p in work.iterdir())
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    s.preview()
    assert sorted(p.name for p in work.iterdir()) == before


def test_apply_turns_on_only_after_a_preview(repo, work):
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    s.preview()
    assert s.can_apply


def test_changing_the_folder_invalidates_the_preview(repo, work, tmp_path):
    """**미리보기를 본 뒤 폴더를 바꾸면 실행 버튼이 다시 꺼져야 한다.**

    안 그러면 A 폴더를 미리보고, B 폴더로 바꾼 뒤, 그대로 실행을 눌러
    **본 적 없는 결과**가 실제로 벌어진다. 미리보기가 보장하는 것이 무너지는
    자리다 — CLI 에서 `--root` 가 빠져 엉뚱한 폴더를 정리할 뻔한 것과 같은 부류다.
    """
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    s.preview()
    assert s.can_apply

    다른폴더 = tmp_path / "다른곳"
    다른폴더.mkdir()
    s.set_root(다른폴더)

    assert not s.can_apply, "폴더를 바꿨으면 미리보기를 다시 봐야 한다"


def test_changing_the_recipe_invalidates_the_preview(repo, work):
    """레시피를 바꿔도 마찬가지다 — 본 것과 할 것이 달라진다."""
    (repo / "recipes" / "다른것.json").write_text(json.dumps({
        "name": "다른것", "roots": ["@downloads"],
        "steps": [{"block": "dedup"}],
    }, ensure_ascii=False), encoding="utf-8")

    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    s.preview()
    assert s.can_apply

    s.set_recipe("다른것")
    assert not s.can_apply


def test_reselecting_the_same_recipe_after_its_file_changed_invalidates_the_preview(repo, work):
    """이름이 같아도 파일 **내용**이 바뀌었으면 무효화해야 한다.

    안 그러면 desktop 을 미리보고, 그 사이 recipes/desktop.json 이 바뀐 뒤
    같은 이름을 다시 골라도 can_apply 가 True 로 남아 옛 미리보기(_built)가
    화면에 없는 계획을 실행하게 된다 — 이 도구의 핵심 불변식(미리보기에서
    본 것만 실행) 위반이다.
    """
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    s.preview()
    assert s.can_apply

    (repo / "recipes" / "정리.json").write_text(json.dumps({
        "name": "정리", "roots": ["@downloads"],
        "steps": [{"block": "dedup"}],
    }, ensure_ascii=False), encoding="utf-8")

    s.set_recipe("정리")          # 이름은 같다 — 옛 로직은 여기서 안 지나쳤다
    assert not s.can_apply, "레시피 파일 내용이 바뀌었으면 미리보기를 다시 봐야 한다"


def test_reselecting_the_exact_same_recipe_keeps_the_preview(repo, work):
    """진짜 아무것도 안 바뀐 재선택까지 미리보기를 지우면 안 된다.

    다음 Task 에서 화면이 드롭다운을 새로고침할 때마다 미리보기가 날아가면
    안 되기 때문이다.
    """
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    s.preview()
    assert s.can_apply

    s.set_recipe("정리")          # 이름도 내용도 안 바뀜
    assert s.can_apply, "아무것도 안 바뀐 재선택은 미리보기를 지우면 안 된다"


# ── 밖으로 내보내기 (백업) ────────────────────────────────────────

def test_preview_marks_rows_that_leave_the_folder(repo, work, tmp_path):
    """백업으로 밖에 나가는 줄은 표에서 구분돼야 한다."""
    usb = tmp_path / "USB"
    usb.mkdir()
    (repo / "config.local.json").write_text(
        json.dumps({"paths": {"백업": str(usb)}}, ensure_ascii=False), encoding="utf-8")
    (repo / "recipes" / "백업.json").write_text(json.dumps({
        "name": "백업", "roots": ["@downloads"],
        "steps": [{"block": "route", "profile": "desktop", "dest": "@백업"}],
    }, ensure_ascii=False), encoding="utf-8")

    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("백업")
    view = s.preview()

    이동 = [r for r in view.rows if r.kind == "이동"]
    assert 이동 and all(r.leaving for r in 이동), "밖으로 나가는 것이 표시돼야 한다"
    assert view.warnings, "밖으로 나간다는 경고가 있어야 한다"
    assert str(usb) in " ".join(view.warnings)


def test_a_backup_place_that_is_not_plugged_in_is_reported_not_crashed(repo, work, tmp_path):
    """USB 가 안 꽂혀 있으면 창이 죽지 않고 한국어로 알린다."""
    (repo / "config.local.json").write_text(
        json.dumps({"paths": {"백업": str(tmp_path / "안꽂힌USB")}}, ensure_ascii=False),
        encoding="utf-8")
    (repo / "recipes" / "백업.json").write_text(json.dumps({
        "name": "백업", "roots": ["@downloads"],
        "steps": [{"block": "route", "profile": "desktop", "dest": "@백업"}],
    }, ensure_ascii=False), encoding="utf-8")

    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("백업")

    view = s.preview()                     # 미리보기는 꽂지 않아도 볼 수 있다
    assert view.rows

    with pytest.raises(OrganizeError) as ex:
        s.apply()                          # 실행은 막힌다
    assert "찾을 수 없습니다" in ex.value.message
    assert (work / "보고서.pdf").exists(), "막았으면 파일은 그대로여야 한다"


# ── 실행과 되돌리기 ───────────────────────────────────────────────

def test_apply_then_undo_comes_back(repo, work):
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    s.preview()

    done = s.apply()
    assert done.moved == 1
    assert (work / "01_Docs" / "보고서.pdf").exists()
    assert s.can_undo

    undone = s.undo()
    assert undone.restored >= 1
    assert (work / "보고서.pdf").exists()


def test_apply_needs_a_preview_first(repo, work):
    """미리보기 없이 실행을 부르면 거부한다 — 창의 버튼 상태만 믿지 않는다."""
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    with pytest.raises(OrganizeError):
        s.apply()
    assert (work / "보고서.pdf").exists()


def test_실행을_마친_뒤_대상을_바꾸면_can_undo_와_undo_가_같은_폴더를_본다(repo, tmp_path):
    """화면의 대상 드롭다운이 진실이다.

    실측 결함: `can_undo` 는 `_root` 를 보는데 `undo()` 는 `_applied_root` 를
    되돌렸다. 실행을 마치고 대상만 바꾸면 화면은 새 폴더를 가리키는데 옛
    폴더의 파일이 움직였다 — 동시성이 없어도 나는 갈라짐이다.
    """
    바탕 = tmp_path / "바탕화면"
    다운 = tmp_path / "다운로드"
    old_file(바탕 / "바탕.pdf")
    old_file(다운 / "다운.pdf")

    s = Session(repo_root=repo)
    s.set_root(바탕)
    s.set_recipe("정리")
    s.preview()
    s.apply()
    assert (바탕 / "01_Docs" / "바탕.pdf").exists()

    s.set_root(다운)                      # 실행만 끝내고 대상을 바꾼다
    assert not s.can_undo, "다운로드에는 되돌릴 기록이 없다"

    with pytest.raises(OrganizeError):    # 켜지지 않는 버튼은 아무 일도 못 한다
        s.undo()
    assert (바탕 / "01_Docs" / "바탕.pdf").exists(), \
        "화면이 가리키지 않는 폴더를 되돌리면 안 된다"


def test_대상을_되돌릴_폴더로_다시_고르면_그_폴더가_되돌아온다(repo, tmp_path):
    """`can_undo` 가 켜진다고 말한 폴더가 실제로 되돌아가는 폴더다."""
    바탕 = tmp_path / "바탕화면"
    old_file(바탕 / "바탕.pdf")

    s = Session(repo_root=repo)
    s.set_root(바탕)
    s.set_recipe("정리")
    s.preview()
    s.apply()

    s.set_root(tmp_path / "딴데")         # 잠깐 딴 데를 봤다가
    s.set_root(바탕)                      # 다시 돌아온다
    assert s.can_undo
    s.undo()
    assert (바탕 / "바탕.pdf").exists()


def test_undo_is_off_until_something_was_applied(repo, work):
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    assert not s.can_undo


# ── 고장난 입력 ───────────────────────────────────────────────────

def test_a_missing_folder_is_a_korean_message(repo, tmp_path):
    s = Session(repo_root=repo)
    s.set_root(tmp_path / "없는폴더")
    s.set_recipe("정리")
    with pytest.raises(OrganizeError) as ex:
        s.preview()
    assert "찾을 수 없" in ex.value.message


def test_an_unknown_recipe_is_a_korean_message(repo, work):
    s = Session(repo_root=repo)
    s.set_root(work)
    with pytest.raises(OrganizeError):
        s.set_recipe("없는레시피")


# ── 체크박스로 steps 조립 (Task 9) ─────────────────────────────────

def test_set_steps_keeps_the_checked_order(repo):
    """dedup 을 먼저 켜고 unzip 을 켜면, 순서를 바꿔 켠 것과 결과가 달라야 한다."""
    s = Session(repo_root=repo)
    s.set_steps(["dedup", "unzip"])
    assert s.checked_ids() == ["dedup", "unzip"]

    s2 = Session(repo_root=repo)
    s2.set_steps(["unzip", "dedup"])
    assert s2.checked_ids() == ["unzip", "dedup"]


def test_set_steps_enables_preview_once_a_root_is_chosen(repo, work):
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_steps(["dedup"])
    assert s.can_preview


def test_set_steps_after_a_preview_invalidates_apply(repo, work):
    """미리보기 뒤 체크박스 조합을 바꾸면 실행 버튼이 다시 꺼져야 한다.

    안 그러면 A 조합을 미리보고 B 조합으로 바꾼 뒤 그대로 실행해 본 적 없는
    결과가 벌어진다 — 레시피를 바꿀 때와 같은 부류의 사고다.
    """
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_steps(["route_kind"])        # profiles/desktop.toml 로 미리보기 가능
    s.preview()
    assert s.can_apply

    s.set_steps(["dedup"])
    assert not s.can_apply, "체크박스 조합을 바꿨으면 미리보기를 다시 봐야 한다"


def test_set_steps_with_an_unknown_id_is_a_korean_error_not_a_keyerror(repo):
    s = Session(repo_root=repo)
    with pytest.raises(OrganizeError):
        s.set_steps(["없는id"])


def test_set_recipe_desktop_matches_the_catalog_exactly(real_recipes_repo):
    """recipes/desktop.json 은 dedup + route(profile=desktop) 이라 카탈로그와
    dict 완전 일치한다 — 못 알아본 step 이 없어야 한다."""
    s = Session(repo_root=real_recipes_repo)
    s.set_recipe("desktop")
    assert s.checked_ids() == ["dedup", "route_kind"]
    assert s.unmatched_steps() == []


def test_set_recipe_photos_matches_the_catalog_exactly(real_recipes_repo):
    """recipes/photos.json 도 카탈로그와 dict 완전 일치해야 한다.

    예전에는 target 이 없거나("route") "사진" 이라("by_date") 둘 다 못
    알아봤다. 그래서 화면에서 '사진 정리' 를 고르면 **체크박스가 전부 꺼진
    채** 뜨는데 미리보기는 두 단계를 실제로 돌았다 — 화면이 말하는 것과
    실행되는 것이 갈라지는, 이 프로젝트가 가장 경계하는 모양이다.

    기준은 카탈로그다(시안이 정한 값이고 다른 화면 요소가 이미 그걸 전제한다).
    레시피를 카탈로그에 맞춘다.

    세 단계다 — 앞에 route_kind(종류별 분류)가 있어야 사진 폴더 **바로 아래**
    있는 파일이 02_Media 로 모인다. 그게 없으면 02_Media 가 없는 보통의 사진
    폴더에서 아무 일도 안 일어난다(아래 엔진 테스트가 그것을 못박는다).
    """
    s = Session(repo_root=real_recipes_repo)
    s.set_recipe("photos")
    assert s.checked_ids() == ["route_kind", "route_photos", "by_date_year"]
    assert s.unmatched_steps() == []


def test_shipped_photos_recipe_carries_the_catalog_steps_verbatim():
    """저장소가 **실제로 싣고 있는** 파일이 카탈로그와 같은지 못박는다.

    위 테스트는 복사본을 보므로, 원본이 손으로 고쳐져 어긋나는 것은 못 잡는다.
    """
    steps = json.loads(
        (Path(__file__).resolve().parent.parent / "recipes" / "photos.json")
        .read_text(encoding="utf-8"))["steps"]
    assert steps == [catalog.by_id(i).step
                     for i in ("route_kind", "route_photos", "by_date_year")]


def test_a_step_the_catalog_does_not_know_is_previewed_exactly_as_written(
        repo, work):
    """못 알아본 step 이라고 버리거나 카탈로그 값으로 바꿔치면 안 된다.

    미리보기는 레시피에 적힌 그대로 계획을 세워야 한다 — 안 그러면 화면이
    보여준 것과 실제로 벌어지는 일이 갈라진다.
    """
    (repo / "recipes" / "손으로쓴것.json").write_text(json.dumps({
        "name": "손으로쓴것", "roots": [],
        "steps": [{"block": "route", "profile": "desktop", "target": "받은것"}],
    }, ensure_ascii=False), encoding="utf-8")
    old_file(work / "받은것" / "보고서.pdf")

    s = Session(repo_root=repo)
    s.set_recipe("손으로쓴것")
    assert s.checked_ids() == [], "target 이 다르므로 알아보면 안 된다"
    assert s.unmatched_steps() == [
        {"block": "route", "profile": "desktop", "target": "받은것"}]

    s.set_root(work)
    dests = [r.dest.replace("\\", "/") for r in s.preview().rows if r.dest]
    assert dests and all("받은것/" in d for d in dests), \
        f"레시피에 적힌 target('받은것') 그대로 움직여야 한다: {dests}"


def test_unmatched_steps_returns_a_copy_not_the_live_dict(repo):
    """받은 쪽이 돌려받은 dict/list 를 고쳐도 _steps 는 오염되면 안 된다.

    catalog.py 의 _copy() 가 copy.deepcopy 를 쓰는 것과 같은 이유다 —
    안 그러면 _invalidate() 를 안 지나고 조용히 오염된다.
    """
    (repo / "recipes" / "이상한것.json").write_text(json.dumps({
        "name": "이상한것", "roots": [],
        "steps": [{"block": "이상한블록", "x": 1}],
    }, ensure_ascii=False), encoding="utf-8")

    s = Session(repo_root=repo)
    s.set_recipe("이상한것")

    got = s.unmatched_steps()
    assert got == [{"block": "이상한블록", "x": 1}]

    got[0]["x"] = 999          # 돌려받은 dict 를 고쳐본다
    got.append({"block": "다른것"})  # 돌려받은 list 도 고쳐본다

    again = s.unmatched_steps()
    assert again == [{"block": "이상한블록", "x": 1}], \
        "돌려받은 것을 고쳐도 _steps 는 그대로여야 한다"


def test_save_recipe_writes_a_recipe_that_loads_back_the_same_steps(repo):
    s = Session(repo_root=repo)
    s.set_steps(["dedup", "route_kind"])

    path = s.save_recipe("내조합")

    assert path == repo / "recipes" / "내조합.json"
    assert path.is_file()
    loaded = load_recipe(path)
    assert loaded.roots == []
    assert loaded.steps == [{"block": "dedup"},
                            {"block": "route", "profile": "desktop"}]
    assert "내조합" in s.recipe_names()
    assert s.recipe_name == "내조합", "저장한 레시피를 드롭다운이 가리켜야 한다"


def test_save_recipe_refuses_to_silently_replace_an_existing_recipe(repo):
    """`desktop` 이라고 치면 기본 제공 레시피가 말없이 사라지면 안 된다."""
    (repo / "recipes" / "desktop.json").write_text(json.dumps({
        "name": "바탕화면 정리", "roots": [], "steps": [{"block": "dedup"}],
    }, ensure_ascii=False), encoding="utf-8")

    s = Session(repo_root=repo)
    s.set_steps(["route_kind"])

    with pytest.raises(OrganizeError):
        s.save_recipe("desktop")

    path = s.save_recipe("desktop", overwrite=True)
    assert path.is_file()
    assert load_recipe(path).steps == [{"block": "route", "profile": "desktop"}]


def test_save_recipe_rejects_names_that_could_escape_the_recipes_folder(repo):
    s = Session(repo_root=repo)
    s.set_steps(["dedup"])
    for bad in ("../밖", "a/b", "  ", ""):
        with pytest.raises(OrganizeError):
            s.save_recipe(bad)


def test_save_recipe_refuses_when_there_is_nothing_to_save(repo):
    s = Session(repo_root=repo)
    with pytest.raises(OrganizeError):
        s.save_recipe("x")


def test_save_recipe_trims_the_name_before_writing(repo):
    """`save_recipe("  x  ")` 가 `recipes/  x  .json` 이 아니라
    `recipes/x.json` 을 만들어야 한다."""
    s = Session(repo_root=repo)
    s.set_steps(["dedup"])

    path = s.save_recipe("  x  ")

    assert path == repo / "recipes" / "x.json"
    assert path.is_file()
    assert not (repo / "recipes" / "  x  .json").exists()
    assert s.recipe_name == "x", "_recipe_name 도 뗀 이름을 써야 한다"


def test_save_recipe_trims_before_checking_for_an_existing_recipe(repo):
    """이미 있는 이름 앞뒤에 공백을 붙여도 overwrite 없이는 거부돼야 한다.

    옛 코드는 떼지 않은 이름으로 경로를 만들어 진짜 desktop.json 과의
    겹침 검사를 피해 갔다.
    """
    s = Session(repo_root=repo)
    s.set_steps(["dedup"])
    s.save_recipe("desktop")           # 진짜 desktop.json 을 만든다

    s2 = Session(repo_root=repo)
    s2.set_steps(["route_kind"])
    with pytest.raises(OrganizeError):
        s2.save_recipe("  desktop  ")  # 공백을 떼면 같은 이름이다

    # 거부됐으니 원래 desktop.json 내용이 그대로여야 한다
    assert load_recipe(repo / "recipes" / "desktop.json").steps == [{"block": "dedup"}]


def test_save_recipe_write_failure_is_a_korean_message_not_the_raw_exception(repo, monkeypatch):
    """파일 쓰기가 실패하면(윈도우 예약어, 권한 없음 등) 파이썬 예외 원문을
    그대로 보여주지 않고 한국어 OrganizeError 로 바꿔야 한다."""
    import organize.gui_model as gui_model

    def boom(path, recipe):
        raise OSError("some very specific os-level error text")

    monkeypatch.setattr(gui_model, "write_recipe_file", boom)

    s = Session(repo_root=repo)
    s.set_steps(["dedup"])
    with pytest.raises(OrganizeError) as ex:
        s.save_recipe("x")
    assert "some very specific os-level error text" not in ex.value.message


# ── 파일 하나만 이번 실행에서 빼기 (미리보기 표의 체크박스) ────────────────

def test_rows_carry_the_key_of_the_file_they_came_from(repo, work):
    """줄마다 '어느 원본 파일인가' 가 붙어 있어야 체크박스를 파일 단위로 묶는다."""
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")

    view = s.preview()

    이동 = [r for r in view.rows if r.kind == "이동"]
    assert 이동[0].key == str(work / "보고서.pdf")
    폴더 = [r for r in view.rows if r.kind == "폴더 생성"]
    assert 폴더, "01_Docs 를 만드는 줄이 있어야 한다"
    assert 폴더[0].key == "", "폴더 생성은 어느 파일 것도 아니다"


def test_set_excluded_turns_the_apply_button_off(repo, work):
    """체크를 바꿨는데 예전 계획으로 실행되면 사용자가 본 적 없는 일이 벌어진다."""
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    s.preview()
    assert s.can_apply

    s.set_excluded({str(work / "보고서.pdf")})

    assert not s.can_apply, "체크를 바꿨으면 미리보기를 다시 봐야 한다"
    assert s.excluded_keys() == {str(work / "보고서.pdf")}


def test_an_excluded_file_disappears_from_the_next_preview(repo, work):
    old_file(work / "사진.png")
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")

    view = s.preview()
    assert {r.name for r in view.rows if r.kind == "이동"} == {"보고서.pdf", "사진.png"}
    key = next(r.key for r in view.rows if r.name == "보고서.pdf")

    s.set_excluded({key})
    다시 = s.preview()

    assert not any(r.name == "보고서.pdf" for r in 다시.rows), "뺀 파일은 표에서 사라진다"
    assert any(r.name == "사진.png" for r in 다시.rows), "안 뺀 파일은 그대로다"
    assert 다시.skipped > view.skipped, "뺀 파일은 '손대지 않음' 에 잡혀야 한다"


def test_choosing_another_folder_clears_the_exclusions(repo, work, tmp_path):
    """다른 폴더인데 옛 제외가 남아 있으면 설명할 수 없는 결과가 된다."""
    다른폴더 = tmp_path / "다른작업"
    old_file(다른폴더 / "메모.pdf")
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    s.preview()
    s.set_excluded({str(work / "보고서.pdf")})

    s.set_root(다른폴더)

    assert s.excluded_keys() == set()


def test_changing_the_steps_clears_the_exclusions(repo, work):
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    s.preview()
    s.set_excluded({str(work / "보고서.pdf")})

    s.set_steps(["dedup"])

    assert s.excluded_keys() == set()


def test_excluded_keys_hands_out_a_copy(repo, work):
    """받은 쪽이 고쳐도 세션 상태가 조용히 바뀌면 안 된다 — _invalidate 를 안 지난다."""
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    s.set_excluded({str(work / "보고서.pdf")})

    s.excluded_keys().add("엉뚱한것")

    assert s.excluded_keys() == {str(work / "보고서.pdf")}


# ── 리뷰 2건(Minor): 같은 폴더를 다시 골라도 조용히 날리지 않는다 ──────────

def test_choosing_the_same_folder_again_keeps_the_exclusions(repo, work):
    """`set_recipe` 와 같은 빗장이다 — **진짜 바뀌었을 때만** 버린다.

    창이 같은 값을 되먹이는 일은 실제로 생긴다(새로고침, [찾아보기] 에서
    같은 폴더를 다시 고르기). 그때마다 체크 상태와 미리보기가 조용히
    날아가면 사용자는 자기가 뭘 잘못 눌렀는지 알 수 없다.
    """
    old_file(work / "사진.png")
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    s.set_excluded({str(work / "보고서.pdf")})
    s.preview()
    assert s.can_apply, "여기서 켜져 있어야 뒤 assert 가 뭔가를 확인한다"

    s.set_root(work)                      # 같은 폴더를 다시 고른다

    assert s.excluded_keys() == {str(work / "보고서.pdf")}
    assert s.can_apply, "같은 폴더인데 미리보기가 날아가면 안 된다"


def test_the_same_folder_written_as_a_string_is_still_the_same_folder(repo, work):
    """창은 위젯에서 문자열을 받아 넘긴다 — Path 로 고쳐 넣은 것과 같아야 한다."""
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    s.preview()

    s.set_root(str(work))

    assert s.can_apply


def test_choosing_a_different_folder_still_throws_the_preview_away(repo, work, tmp_path):
    """빗장을 걸었다고 **진짜 바뀐** 경우까지 놓치면 안 된다."""
    다른폴더 = tmp_path / "다른작업"
    old_file(다른폴더 / "메모.pdf")
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    s.preview()
    assert s.can_apply

    s.set_root(다른폴더)

    assert not s.can_apply


# ── 리뷰 3건(Minor): 뺐다고 한 파일이 없으면 화면에 드러낸다 ────────────────

def test_preview_warns_when_an_excluded_file_is_gone(repo, work):
    """조용한 무작동은 금기다. 거부하지도 않는다 — 파일은 진짜로 사라질 수 있다."""
    old_file(work / "사진.png")
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    view = s.preview()
    key = next(r.key for r in view.rows if r.name == "보고서.pdf")

    s.set_excluded({key})
    (work / "보고서.pdf").unlink()          # 탐색기에서 지웠다 · USB 를 뽑았다
    다시 = s.preview()

    assert any("찾을 수 없습니다" in w for w in 다시.warnings), \
        f"경고가 없다: {다시.warnings}"
    assert any(r.name == "사진.png" for r in 다시.rows), "나머지는 그대로 돈다"


def test_preview_does_not_warn_when_every_excluded_file_is_there(repo, work):
    old_file(work / "사진.png")
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    view = s.preview()
    key = next(r.key for r in view.rows if r.name == "보고서.pdf")

    s.set_excluded({key})
    다시 = s.preview()

    assert not any("찾을 수 없습니다" in w for w in 다시.warnings), \
        f"멀쩡히 뺐는데 경고가 났다: {다시.warnings}"


# ── 리뷰(Critical): 도는 동안 설정이 바뀐 미리보기를 창이 버릴 수 있어야 한다 ──

def test_invalidate_throws_away_a_preview_the_window_no_longer_wants(repo, work):
    """창은 "내가 부탁한 것과 지금 설정이 달라졌다" 고 말할 수 있어야 한다.

    미리보기가 딴 스레드에서 도는 동안 사용자가 체크를 바꾸면, 끝나는 순간
    `preview()` 가 **옛 steps 로 세운 계획**을 세션에 써 넣는다. 창이 그 결과를
    화면에 안 그려도 `can_apply` 는 True 라 [실행] 이 되살아난다 — 그때
    화면에서 본 적 없는 계획이 그대로 실행된다.
    """
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    s.preview()
    assert s.can_apply

    s.invalidate()
    assert not s.can_apply, "버렸다고 했는데 [실행] 이 켜진 채로 남았다"


def test_invalidate_works_where_calling_the_setters_again_does_not(repo, work):
    """같은 값으로 세터를 다시 부르는 것으로는 못 버린다 — 값이 같으면 빠져나간다.

    그래서 공개 메서드가 따로 필요하다. 이 두 줄이 그 이유 전부다.
    """
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    s.preview()

    s.set_root(work)              # 같은 값 — 세터는 아무 일도 안 한다
    s.set_recipe("정리")
    assert s.can_apply, "세터로는 못 버린다(그래서 invalidate 가 있다)"

    s.invalidate()
    assert not s.can_apply


def test_invalidate_on_a_session_that_never_previewed_is_harmless(repo, work):
    """버릴 것이 없을 때 불러도 죽지 않는다. 창은 조건 없이 부를 수 있어야 한다."""
    s = Session(repo_root=repo)
    s.invalidate()
    s.set_root(work)
    s.set_recipe("정리")
    s.invalidate()
    assert not s.can_apply
    assert s.can_preview, "버렸다고 고른 것까지 지우면 안 된다"


def test_invalidate_keeps_what_the_user_chose(repo, work):
    """계획만 버린다. 대상·레시피·뺀 파일은 사용자가 고른 것이라 남는다."""
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    view = s.preview()
    key = next(r.key for r in view.rows if r.name == "보고서.pdf")
    s.set_excluded({key})
    s.preview()

    s.invalidate()
    assert s.root == work
    assert s.recipe_name == "정리"
    assert s.excluded_keys() == {key}
    assert s.can_preview, "다시 [미리보기] 를 누를 수 있어야 한다"


# ── 실행 결과를 폴더별로 묶기 ───────────────────────────────────
# 파일 113개를 하나씩 늘어놓으면 어디로 갔는지 오히려 안 보인다. 사람이 실행
# 뒤에 하는 일은 "그 폴더에 잘 들어갔나" 를 열어 보는 것이다.

def test_landing_folders_들어간_폴더별로_센다():
    root = Path("/정리할곳")
    done = [{"kind": "move", "final": "/정리할곳/01_Docs/가.pdf"},
            {"kind": "move", "final": "/정리할곳/01_Docs/나.pdf"},
            {"kind": "move", "final": "/정리할곳/02_Media/사진.jpg"}]
    assert landing_folders(done, root) == [
        ("01_Docs", 2, "/정리할곳/01_Docs"),
        ("02_Media", 1, "/정리할곳/02_Media")]


def test_landing_folders_폴더_생성은_세지_않는다():
    """폴더 생성은 파일이 아니다. 섞어 세면 '3개' 가 파일 2 + 폴더 1 이 된다."""
    root = Path("/정리할곳")
    done = [{"kind": "mkdir", "final": "/정리할곳/01_Docs"},
            {"kind": "move", "final": "/정리할곳/01_Docs/가.pdf"}]
    assert landing_folders(done, root) == [("01_Docs", 1, "/정리할곳/01_Docs")]


def test_landing_folders_치운_파일은_한_줄로_묶는다():
    """`.organize/trash/<실행번호>/…` 안쪽 구조는 사람이 알 바가 아니다."""
    root = Path("/정리할곳")
    done = [{"kind": "quarantine", "final": "/정리할곳/.organize/trash/r1/a/가.pdf"},
            {"kind": "quarantine", "final": "/정리할곳/.organize/trash/r1/b/나.pdf"}]
    (이름, 개수, 경로), = landing_folders(done, root)
    assert 개수 == 2
    assert 경로 == "/정리할곳/.organize/trash/r1", "여러 갈래를 하나로 가리켜야 한다"


def test_landing_folders_밖으로_나간_것은_전체_경로로_적는다():
    """반복되는 앞머리가 아니라, 주의해서 봐야 할 자리다."""
    done = [{"kind": "move", "final": "/mnt/백업USB/사진/가.jpg"}]
    (이름, _, _), = landing_folders(done, Path("/정리할곳"))
    assert 이름 == "/mnt/백업USB/사진"


def test_landing_folders_대상_폴더_바로_밑도_이름이_있다():
    """빈 글자로 두면 목록에 이름 없는 줄이 생겨 무엇인지 알 수 없다."""
    done = [{"kind": "move", "final": "/정리할곳/가.pdf"}]
    (이름, _, _), = landing_folders(done, Path("/정리할곳"))
    assert 이름.strip(), f"이름이 비면 안 된다: {이름!r}"


def test_landing_folders_옮긴_것이_없으면_빈_목록():
    assert landing_folders([], Path("/정리할곳")) == []


def test_폴더_생성_줄에도_이름이_붙는다(repo, work):
    """원본 파일이 없다고 이름 칸을 비우면, 표에 줄만 있고 정체가 안 보인다.

    실측: 「폴더 생성 3」 탭이 이름 칸 세 줄을 전부 빈칸으로 그렸다.
    """
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")

    폴더 = [r for r in s.preview().rows if r.kind == "폴더 생성"]

    assert 폴더, "01_Docs 를 만드는 줄이 있어야 한다"
    assert all(r.name for r in 폴더), \
        f"이름이 빈 줄이 있다: {[r.name for r in 폴더]}"
    assert "01_Docs" in [r.name for r in 폴더], "만들 폴더 이름을 적는다"


# ── 저장할 때 폴더도 같이 기억한다 ──────────────────────────────
# 예전에는 roots=[] 로 폴더를 버렸다. 그래서 딸려 온 레시피(폴더 있음)와 내가
# 저장한 것(폴더 없음)이 같은 드롭다운에 섞여, 하나는 대상을 바꾸고 하나는
# 안 바꿨다. 어느 쪽인지 화면에 표시도 없었다.

def test_root_spec_등록된_폴더는_이름으로_적는다(tmp_path):
    """절대 경로를 박으면 PC 를 옮기는 순간 그 조합이 죽는다."""
    from organize.gui_model import root_spec
    from organize.userconfig import UserConfig

    usb = tmp_path / "USB"
    usb.mkdir()
    cfg = UserConfig(paths={"백업": [str(usb)]}, folder_names={})

    assert root_spec(usb, cfg) == "@백업"


def test_root_spec_등록_안_된_폴더는_경로_그대로(tmp_path):
    """적을 이름이 없다. 그 사실은 부르는 쪽이 사용자에게 알린다."""
    from organize.gui_model import root_spec
    from organize.userconfig import UserConfig

    아무데나 = tmp_path / "한번쓰고말것"
    아무데나.mkdir()

    assert root_spec(아무데나, UserConfig(paths={}, folder_names={})) == str(아무데나)


def test_root_spec_안_골랐으면_빈_글자():
    from organize.gui_model import root_spec
    from organize.userconfig import UserConfig

    assert root_spec(None, UserConfig(paths={}, folder_names={})) == ""


def test_저장한_조합이_폴더를_같이_들고_있다(repo, work):
    """이름 붙여 저장하는 이유는 '다음에 똑같이 하려고' 다 — 폴더가 빠지면
    매번 다시 골라야 한다."""
    import json

    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")

    path = s.save_recipe("내조합")
    저장된것 = json.loads(path.read_text(encoding="utf-8"))

    assert 저장된것["roots"], "폴더를 버리면 안 된다"
    assert str(work) in 저장된것["roots"][0] or 저장된것["roots"][0].startswith("@")


def test_저장한_조합을_다시_고르면_그_폴더로_돌아온다(repo, work):
    """저장 → 다른 폴더로 옮김 → 다시 고름. 그때 원래 폴더를 가리켜야 한다."""
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")
    s.save_recipe("내조합")

    assert s.recipe_root_label("내조합"), "어느 폴더용인지 화면이 말할 수 있어야 한다"


def test_폴더를_안_골랐으면_저장에_폴더가_안_들어간다(repo):
    """없는 것을 지어내지 않는다."""
    s = Session(repo_root=repo)
    s.set_recipe("정리")

    assert s.saved_roots() == []


def test_recipe_root_label_폴더가_없는_조합은_빈_글자(repo):
    """모르면 아무 말도 안 하는 편이, 틀린 폴더 이름을 적는 것보다 낫다."""
    s = Session(repo_root=repo)
    s.set_recipe("정리")
    s.save_recipe("폴더없는조합")

    assert s.recipe_root_label("폴더없는조합") == ""


def test_등록_안_된_폴더로_저장하면_경로_그대로_들어간다(repo, work):
    """다른 PC 에서 안 맞는다 — 그 사실은 저장 창이 미리 알린다."""
    s = Session(repo_root=repo)
    s.set_root(work)
    s.set_recipe("정리")

    (적힌것,) = s.saved_roots()

    assert not 적힌것.startswith("@"), "등록 안 된 폴더에는 붙일 이름이 없다"
    assert 적힌것 == str(work)


def test_등록된_폴더로_저장하면_이름으로_들어간다(repo, tmp_path):
    """@이름 으로 적어야 다른 PC 에서도 그 PC 의 폴더를 가리킨다."""
    usb = tmp_path / "USB"
    usb.mkdir()
    (repo / "config.local.json").write_text(
        json.dumps({"paths": {"백업": str(usb)}}, ensure_ascii=False), encoding="utf-8")

    s = Session(repo_root=repo)
    s.set_root(usb)
    s.set_recipe("정리")

    assert s.saved_roots() == ["@백업"]


# ── 폴더를 바꾸면 조합 이름이 풀린다 ────────────────────────────
# 조합은 **폴더까지 묶어서** 저장한 것이다. 폴더만 바꿔 놓고 조합 이름이 그대로
# 남아 있으면 「사진 → 사진」 이라고 적힌 채 바탕화면을 정리하게 된다.
# 실측: 그것이 화면 2 에서 "바로 와닿지 않는다" 던 첫 번째 이유였다.

def test_detach_recipe_이름만_떼고_할_일은_남긴다(repo, work):
    s = Session(repo)
    s.set_recipe("정리")
    켜둔것 = s.checked_ids()
    assert 켜둔것, "이 테스트는 조합에 할 일이 있어야 의미가 있다"

    떼었나 = s.detach_recipe()

    assert 떼었나 is True
    assert s.recipe_name is None, "이름은 떨어져야 한다"
    assert s.checked_ids() == 켜둔것, "켜 둔 할 일까지 지우면 안 된다"


def test_detach_recipe_뗄_이름이_없으면_아무_일도_안_한다(repo):
    s = Session(repo)

    assert s.detach_recipe() is False, "괜히 무효화를 부르지 않게 알려 줘야 한다"


def test_detach_recipe_는_set_recipe_None_과_다르다(repo):
    """`set_recipe(None)` 은 할 일까지 비운다 — 그래서 여기에 쓸 수 없다."""
    s = Session(repo)
    s.set_recipe("정리")

    s.set_recipe(None)

    assert s.checked_ids() == [], "이쪽은 비우는 것이 맞다(둘을 헷갈리지 말 것)"


# ── 조합 이름 바꾸기 · 지우기 ───────────────────────────────────
# 조합은 지금까지 **만들 수만** 있었다. 잘못 지은 이름을 고칠 수도, 필요 없어진
# 것을 치울 수도 없어서 목록이 늘어나기만 했다.

def test_이름을_바꾸면_파일_이름과_안의_이름이_같이_바뀐다(repo):
    """파일 이름만 바꾸면 목록의 이름과 파일 안의 이름이 갈라진다."""
    s = Session(repo)
    s.set_recipe("정리")

    path = s.rename_recipe("정리", "내 바탕화면")

    assert path.name == "내 바탕화면.json"
    assert not (repo / "recipes" / "정리.json").exists(), "옛 파일이 남으면 안 된다"
    assert load_recipe(path).name == "내 바탕화면", "파일 안의 이름도 바뀌어야 한다"
    assert s.recipe_name == "내 바탕화면", "드롭다운이 가리키는 이름도 따라간다"


def test_이름을_바꿔도_할_일은_그대로(repo):
    s = Session(repo)
    s.set_recipe("정리")
    켠것 = s.checked_ids()

    s.rename_recipe("정리", "새이름")

    assert s.checked_ids() == 켠것


def test_같은_이름을_그대로_넣으면_아무_일도_안_한다(repo):
    s = Session(repo)

    path = s.rename_recipe("정리", "  정리  ")

    assert path.is_file() and load_recipe(path).steps


def test_이미_있는_이름으로는_묻기_전에는_안_바꾼다(repo):
    (repo / "recipes" / "다른것.json").write_text(
        json.dumps({"name": "다른것", "steps": [{"block": "dedup"}]}, ensure_ascii=False),
        encoding="utf-8")
    s = Session(repo)

    with pytest.raises(OrganizeError):
        s.rename_recipe("정리", "다른것")

    assert (repo / "recipes" / "정리.json").is_file(), "옛 것이 사라지면 안 된다"
    assert load_recipe(repo / "recipes" / "다른것.json").steps == [{"block": "dedup"}]


def test_덮어쓰기를_허락하면_바꾼다(repo):
    (repo / "recipes" / "다른것.json").write_text(
        json.dumps({"name": "다른것", "steps": [{"block": "dedup"}]}, ensure_ascii=False),
        encoding="utf-8")
    s = Session(repo)

    s.rename_recipe("정리", "다른것", overwrite=True)

    assert not (repo / "recipes" / "정리.json").exists()
    assert load_recipe(repo / "recipes" / "다른것.json").steps == [
        {"block": "route", "profile": "desktop"}], "'정리' 의 내용으로 덮인다"


@pytest.mark.parametrize("나쁜이름", ["", "   ", "../밖", "밖/으로", "밖\\으로"])
def test_이름으로_저장소_밖에_못_나간다(repo, 나쁜이름):
    """손으로 쓴 이름을 그대로 경로에 붙이므로 여기서 막는다."""
    s = Session(repo)

    with pytest.raises(OrganizeError):
        s.rename_recipe("정리", 나쁜이름)


def test_지우면_파일이_사라지고_이름만_떨어진다(repo):
    """켜 둔 할 일까지 없애지 않는다 — 이름을 지웠다고 하려던 일이 없어지진 않는다."""
    s = Session(repo)
    s.set_recipe("정리")
    켠것 = s.checked_ids()

    s.delete_recipe("정리")

    assert not (repo / "recipes" / "정리.json").exists()
    assert s.recipe_name is None
    assert s.checked_ids() == 켠것
    assert "정리" not in s.recipe_names()


def test_없는_조합을_지우려_하면_한국어로_알린다(repo):
    s = Session(repo)

    with pytest.raises(OrganizeError):
        s.delete_recipe("없는것")


# ── 보류 줄이 무리 정보를 싣는다 ────────────────────────────────
from organize.gui_model import file_facts          # noqa: E402


def test_file_facts_정리할_폴더_기준으로_적는다(tmp_path):
    (tmp_path / "백업").mkdir()
    파일 = old_file(tmp_path / "백업" / "보고서.pdf", b"X" * 2048)

    위치, 수정일, 크기 = file_facts(파일, tmp_path)

    assert 위치 == "백업"
    assert len(수정일) == 10 and 수정일[4] == "-", f"YYYY-MM-DD 여야 한다: {수정일}"
    assert 크기 == "2.0KB"


def test_file_facts_최상단이면_그렇게_적는다(tmp_path):
    파일 = old_file(tmp_path / "보고서.pdf", b"X")

    위치, _, _ = file_facts(파일, tmp_path)

    assert 위치 == "(최상단)"


def test_file_facts_정리할_폴더_밖이면_전체_경로(tmp_path):
    밖 = tmp_path.parent / "밖에있는것"
    밖.mkdir(exist_ok=True)
    파일 = old_file(밖 / "보고서.pdf", b"X")

    위치, _, _ = file_facts(파일, tmp_path)

    assert 위치 == str(밖)


def test_file_facts_못_읽으면_빈_값이고_죽지_않는다(tmp_path):
    assert file_facts(tmp_path / "없는것.pdf", tmp_path) == ("", "", "")
    assert file_facts(None, tmp_path) == ("", "", "")


def test_보류_줄이_남기는_파일을_싣는다(repo, tmp_path):
    """표가 무리를 묶으려면 줄마다 keeper 가 있어야 한다."""
    작업 = tmp_path / "작업"
    작업.mkdir()
    old_file(작업 / "a.txt", b"SAME")
    old_file(작업 / "b.txt", b"SAME")
    s = Session(repo)
    s.set_root(작업)
    s.set_steps(["dedup"])

    보류 = [r for r in s.preview().rows if r.kind == _KIND_LABEL["quarantine"]]

    assert 보류, "이 테스트는 보류가 나와야 의미가 있다"
    for r in 보류:
        assert r.keeper, "남기는 파일의 경로"
        assert r.keeper_at == "(최상단)"
        assert r.keeper_when and r.keeper_size
        assert r.at == "(최상단)" and r.when


def test_보류가_아닌_줄에는_무리_정보가_없다(repo, work):
    s = Session(repo)
    s.set_root(work)
    s.set_steps(["route_kind"])

    for r in s.preview().rows:
        assert r.keeper == "", f"{r.kind} 줄에 keeper 가 붙었다"


def test_file_facts는_keeper_없는_줄에서_불리지_않는다(repo, tmp_path, monkeypatch):
    """file_facts 는 os.stat 을 한다 — move·mkdir 줄까지 매번 두 번씩 부르면
    다운로드 폴더처럼 파일이 많을 때 미리보기가 그만큼 느려진다.

    dedup(보류 1개) + route_kind(이동·폴더 생성 여러 줄) 를 같이 돌려서,
    보류 아닌 줄이 실제로 있는 상황을 만든다.
    """
    import organize.gui_model as gui_model

    불린것: list = []
    원래 = gui_model.file_facts

    def 세는것(path, root):
        불린것.append(path)
        return 원래(path, root)

    monkeypatch.setattr(gui_model, "file_facts", 세는것)

    작업 = tmp_path / "작업"
    작업.mkdir()
    old_file(작업 / "a.txt", b"SAME")
    old_file(작업 / "b.txt", b"SAME")
    old_file(작업 / "보고서.pdf", b"DOC")
    s = Session(repo)
    s.set_root(작업)
    s.set_steps(["dedup", "route_kind"])

    view = s.preview()

    보류줄 = [r for r in view.rows if r.kind == _KIND_LABEL["quarantine"]]
    다른줄 = [r for r in view.rows if r.kind != _KIND_LABEL["quarantine"]]
    assert 보류줄, "이 테스트는 보류가 나와야 의미가 있다"
    assert 다른줄, "move·mkdir 같은 다른 줄도 있어야 의미가 있다"
    assert len(불린것) == len(보류줄) * 2, \
        f"보류 아닌 줄({len(다른줄)}개)에서도 file_facts 가 불렸다: {len(불린것)}회"


# ── 실행 뒤 보류한 것 지우기 ────────────────────────────────────
def test_실행_결과가_보류_개수와_실행번호를_알려준다(repo, tmp_path):
    """[보류한 N개 지우기] 를 그리려면 이 둘이 있어야 한다."""
    작업 = tmp_path / "작업"
    작업.mkdir()
    old_file(작업 / "a.txt", b"SAME")
    old_file(작업 / "b.txt", b"SAME")
    s = Session(repo)
    s.set_root(작업)
    s.set_steps(["dedup"])
    s.preview()

    out = s.apply()

    assert out.quarantined == 1
    assert out.run_id and out.run_id == out.log_path.stem


def test_보류가_없으면_개수가_0(repo, work):
    s = Session(repo)
    s.set_root(work)
    s.set_steps(["route_kind"])
    s.preview()

    out = s.apply()

    assert out.quarantined == 0


def test_purge_quarantine_이_보류한_것을_지운다(repo, tmp_path):
    작업 = tmp_path / "작업"
    작업.mkdir()
    old_file(작업 / "a.txt", b"SAME")
    old_file(작업 / "b.txt", b"SAME")
    s = Session(repo)
    s.set_root(작업)
    s.set_steps(["dedup"])
    s.preview()
    out = s.apply()

    지운것 = s.purge_quarantine(out.run_id)

    assert 지운것.removed == 1
    trash = 작업 / ".organize" / "trash"
    남은것 = list(trash.rglob("*.txt")) if trash.is_dir() else []
    assert 남은것 == [], f"보류 폴더에 파일이 남았다: {남은것}"


def test_지운_뒤에도_되돌리기는_켜져_있다(repo, tmp_path):
    """옮긴 것은 여전히 되돌아간다. 보류만 못 되살아난다."""
    작업 = tmp_path / "작업"
    작업.mkdir()
    old_file(작업 / "a.txt", b"SAME")
    old_file(작업 / "b.txt", b"SAME")
    s = Session(repo)
    s.set_root(작업)
    s.set_steps(["dedup"])
    s.preview()
    out = s.apply()

    s.purge_quarantine(out.run_id)

    assert s.can_undo is True


def test_지운_뒤_되돌려도_죽지_않는다(repo, tmp_path):
    """보류 파일은 못 되살아나지만 되돌리기 자체가 터지면 안 된다."""
    작업 = tmp_path / "작업"
    작업.mkdir()
    old_file(작업 / "a.txt", b"SAME")
    old_file(작업 / "b.txt", b"SAME")
    old_file(작업 / "보고서.pdf", b"DOC")
    s = Session(repo)
    s.set_root(작업)
    s.set_steps(["dedup", "route_kind"])
    s.preview()
    out = s.apply()
    s.purge_quarantine(out.run_id)

    되돌림 = s.undo()

    assert 되돌림.restored >= 1, "옮긴 것은 되돌아간다"
    assert (작업 / "보고서.pdf").is_file()
