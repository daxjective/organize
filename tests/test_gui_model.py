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

from organize import profiles
from organize.errors import OrganizeError
from organize.gui_model import Session
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


def test_set_recipe_photos_does_not_match_the_catalog_but_previews_as_written(
        real_recipes_repo, tmp_path, monkeypatch):
    """recipes/photos.json 의 step 은 카탈로그와 target 이 달라 알아보면 안 된다.

    그리고 못 알아봤다고 버리면 안 된다 — 미리보기는 레시피에 적힌 target
    ("사진") 그대로 계획을 세워야 한다. 카탈로그 값("02_Media/사진")을 대신
    쓰면 화면과 실제가 갈라진다.
    """
    monkeypatch.setattr(profiles, "has_exif_camera", lambda p: True)

    work = tmp_path / "사진작업"
    work.mkdir()
    old_file(work / "고양이.jpg")

    s = Session(repo_root=real_recipes_repo)
    s.set_recipe("photos")
    assert s.unmatched_steps(), "target 이 다르므로 알아보면 안 된다"

    s.set_root(work)
    view = s.preview()

    dests = [r.dest.replace("\\", "/") for r in view.rows if r.dest]
    assert any("/사진" in d or d.endswith("사진") for d in dests), \
        "레시피에 적힌 target('사진') 그대로 움직여야 한다"
    assert not any("02_Media" in d for d in dests), \
        "카탈로그 값이 아니라 레시피에 적힌 값을 그대로 써야 한다"


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
