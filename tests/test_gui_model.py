"""창(위젯) 없이 도는 GUI 로직.

화면에 무엇을 보여줄지 계산하는 일과, 그것을 그리는 일을 나눈다.
계산하는 쪽만 여기서 테스트한다 — tkinter 가 없는 환경에서도 돌아야 하고,
창을 띄우지 않고도 "실행 버튼이 켜지는가" 같은 것을 못박을 수 있어야 한다.
"""

import json
import os
import time
from pathlib import Path

import pytest

from organize.errors import OrganizeError
from organize.gui_model import Session


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
