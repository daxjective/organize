import json
from pathlib import Path

import pytest

from organize import cli


def old_file(path: Path, data: bytes = b"DATA") -> Path:
    """방금 만든 파일은 '작업 중' 으로 걸러지므로 수정시각을 한 시간 전으로 돌린다."""
    import os, time
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    past = time.time() - 3600
    os.utime(path, (past, past))
    return path


def write_multi_recipe(repo, name: str, roots: list[Path]) -> None:
    """root 가 여러 개인 레시피를 만든다 — 단일 root 만 다루는 `project` 픽스처로는
    root 여러 개 중 하나가 죽는 상황(Critical #2)을 재현할 수 없다."""
    (repo / "recipes" / f"{name}.json").write_text(json.dumps({
        "name": name, "roots": [str(r) for r in roots],
        "steps": [{"block": "route", "profile": "desktop"}],
    }, ensure_ascii=False), encoding="utf-8")


def block_runlog_path(root: Path) -> None:
    """`<root>/.organize/runs` 자리에 파일을 미리 놓아, write_runlog/prepare_runlog
    가 mkdir 하려는 자리를 막는다 — 디스크 풀·권한 거부와 같은 부류의 실패를
    결정적으로 재현하는 방법(컨트롤러가 실측에 쓴 것과 같은 방법)."""
    organize_dir = root / ".organize"
    organize_dir.mkdir(parents=True, exist_ok=True)
    (organize_dir / "runs").write_text("나는 파일입니다", encoding="utf-8")


@pytest.fixture
def project(tmp_path, monkeypatch):
    """저장소 구조와 대상 폴더를 통째로 흉내낸다."""
    repo = tmp_path / "repo"
    (repo / "profiles").mkdir(parents=True)
    (repo / "recipes").mkdir()
    (repo / "profiles" / "desktop.toml").write_text(
        'name = "테스트"\n'
        '[[rules]]\n to = "01_Docs"\n ext = [".pdf", ".md"]\n'
        '[[rules]]\n to = "02_Media"\n ext = [".png"]\n'
        '[[rules]]\n to = "99_Unsorted"\n default = true\n', encoding="utf-8")

    work = tmp_path / "작업"
    work.mkdir()
    (repo / "recipes" / "t.json").write_text(json.dumps({
        "name": "테스트", "roots": [str(work)],
        "steps": [{"block": "route", "profile": "desktop"}],
    }, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(cli, "repo_root", lambda: repo)
    return repo, work


def test_preview_does_not_touch_files(project, capsys):
    _, work = project
    old_file(work / "보고서.pdf")
    assert cli.main(["preview", "t"]) == 0
    out = capsys.readouterr().out
    assert "이동 1" in out
    assert (work / "보고서.pdf").exists()
    assert not (work / "01_Docs").exists()


def test_preview_suggests_the_next_command(project, capsys):
    _, work = project
    old_file(work / "보고서.pdf")
    cli.main(["preview", "t"])
    assert "organize run t --apply" in capsys.readouterr().out


def test_run_without_apply_is_only_a_preview(project, capsys):
    _, work = project
    old_file(work / "보고서.pdf")
    assert cli.main(["run", "t"]) == 0
    assert (work / "보고서.pdf").exists()
    assert "--apply" in capsys.readouterr().out


def test_run_with_apply_moves_files(project, capsys):
    _, work = project
    old_file(work / "보고서.pdf")
    assert cli.main(["run", "t", "--apply"]) == 0
    assert (work / "01_Docs" / "보고서.pdf").read_bytes() == b"DATA"
    out = capsys.readouterr().out
    assert "organize undo" in out


def test_run_with_apply_writes_a_runlog(project, capsys):
    """execute() 는 실행 로그를 스스로 쓰지 않는다 — 부르는 쪽(CLI)이
    write_runlog(built, result) 을 따로 불러야 한다. CLI 가 그걸 빠뜨리면
    파일은 옮겨졌는데 되돌릴 방법이 없다. 그 계약을 여기서 직접 못박는다."""
    _, work = project
    old_file(work / "보고서.pdf")
    cli.main(["run", "t", "--apply"])
    capsys.readouterr()

    logs = list((work / ".organize" / "runs").glob("*.json"))
    assert len(logs) == 1, "run --apply 뒤에는 실행 기록이 정확히 하나 남아야 한다"

    data = json.loads(logs[0].read_text(encoding="utf-8"))
    assert any(d["kind"] == "move" for d in data["done"]), \
        "실행 기록에 실제로 옮긴 항목이 담겨 있어야 되돌릴 수 있다"


def test_undo_restores(project, capsys):
    _, work = project
    old_file(work / "보고서.pdf")
    cli.main(["run", "t", "--apply"])
    assert cli.main(["undo", "--root", str(work)]) == 0
    assert (work / "보고서.pdf").read_bytes() == b"DATA"


def test_unknown_recipe_is_a_friendly_error(project, capsys):
    assert cli.main(["preview", "없는것"]) == 1
    out = capsys.readouterr().out
    assert "없는것" in out and "t" in out


def test_verbose_lists_every_action(project, capsys):
    _, work = project
    old_file(work / "보고서.pdf")
    cli.main(["preview", "t", "--verbose"])
    assert "보고서.pdf" in capsys.readouterr().out


def test_preview_suggestion_keeps_the_root_you_asked_for(project, tmp_path, capsys):
    """`--root` 로 다른 폴더를 봤으면 제안하는 명령에도 그대로 있어야 한다.

    안 그러면 미리보기는 이 폴더를 보여주고, 사용자가 복사한 명령은 레시피에
    적힌 **원래 폴더**(예: 진짜 다운로드 폴더)를 `--apply` 로 정리해 버린다.
    미리보기의 존재 이유가 무너지는 자리다.
    """
    other = tmp_path / "다른폴더"
    old_file(other / "메모.md")

    cli.main(["preview", "t", "--root", str(other)])
    out = capsys.readouterr().out

    suggested = [ln for ln in out.splitlines()
                 if "organize run" in ln or "organize preview" in ln]
    assert suggested, "제안한 명령이 아예 없다"
    for line in suggested:
        assert f"--root {other}" in line, f"제안한 명령에 대상 폴더가 없다: {line.strip()}"


# ---------------------------------------------------------------------------
# 수정 라운드 1(Task 18 리뷰) — Critical #1/#2, Important #1.
# 컨트롤러가 실측으로 재현한 것과 같은 방법(.organize/runs 자리를 파일로
# 막기)을 그대로 쓴다.
# ---------------------------------------------------------------------------


def test_run_with_apply_blocked_runlog_leaves_files_untouched(project, capsys):
    """Critical #1 — .organize/runs 자리가 막혀 있으면 execute() 를 부르기도
    전에 막혀야 한다. 원본이 제자리에 있는지가 이 테스트의 핵심 단언이다."""
    _, work = project
    old_file(work / "보고서.pdf")
    block_runlog_path(work)

    assert cli.main(["run", "t", "--apply"]) == 1
    out = capsys.readouterr().out

    assert (work / "보고서.pdf").exists(), "파일이 하나도 움직이지 않아야 한다"
    assert not (work / "01_Docs").exists(), "옮겨진 흔적이 있으면 안 된다"
    assert "Traceback" not in out and "FileExistsError" not in out


def test_run_with_apply_prints_moved_list_when_write_runlog_fails_after_move(
        project, capsys, monkeypatch):
    """Critical #1 — prepare_runlog 는 통과했지만(자리는 확보됨) 실행 후
    write_runlog 이 실패하면(디스크가 도중에 꽉 차는 등), 파일은 이미
    옮겨졌으므로 최소한 무엇을 어디로 옮겼는지 화면에 전부 남아야 한다.
    이게 사람이 손으로 되돌릴 수 있는 유일한 근거다."""
    _, work = project
    old_file(work / "보고서.pdf")

    from organize.errors import OrganizeError

    def boom(built, result):
        raise OrganizeError("실행 기록을 남기지 못했습니다(시뮬레이션)",
                            hint="디스크 공간을 확인해 주세요.")

    monkeypatch.setattr(cli, "write_runlog", boom)

    assert cli.main(["run", "t", "--apply"]) == 1
    out = capsys.readouterr().out

    assert (work / "01_Docs" / "보고서.pdf").exists(), "파일은 실제로 옮겨졌다"
    assert "보고서.pdf" in out
    assert "01_Docs" in out
    assert "실행 기록을 남기지 못했습니다" in out


def test_multi_root_continues_past_a_blocked_root_and_exits_nonzero(project, tmp_path, capsys):
    """Critical #2 — root 3개 중 가운데가 죽어도 나머지 root(특히 세 번째)는
    처리돼야 한다. 조용히 넘어가면 안 되고, 종료 코드가 1 이어야 한다."""
    repo, _ = project
    work_a = tmp_path / "a"
    work_b = tmp_path / "b"
    work_c = tmp_path / "c"
    old_file(work_a / "가.pdf")
    old_file(work_b / "나.pdf")
    old_file(work_c / "다.pdf")
    block_runlog_path(work_b)
    write_multi_recipe(repo, "multi3", [work_a, work_b, work_c])

    assert cli.main(["run", "multi3", "--apply"]) == 1
    out = capsys.readouterr().out

    assert (work_a / "01_Docs" / "가.pdf").exists(), "A는 정상 처리돼야 한다"
    assert (work_b / "나.pdf").exists(), "B는 막혔으니 손도 대지 않아야 한다"
    assert not (work_b / "01_Docs").exists()
    assert (work_c / "01_Docs" / "다.pdf").exists(), \
        "B가 죽어도 C는 계속 처리돼야 한다 — 이게 이번 결함의 핵심이다"
    assert str(work_b) in out, "어느 폴더가 실패했는지 화면에 안내가 있어야 한다"


def test_multi_root_partial_failure_suggests_per_root_undo_not_recipe(project, tmp_path, capsys):
    """직접 CLI 로 확인해서 찾은 것: 일부 root 만 성공했을 때
    `organize undo --recipe` 를 그대로 권하면, 그 명령 자체가
    `_cmd_undo` 의 (root 단위로 격리돼 있지 않은) 반복문에서 실패한 root 를
    만나 멈춰 버려 성공한 root(C)는 되돌아가지 않는다 — 우리가 권한
    명령이 조용한 무작동을 낳는 꼴이다. 그래서 일부만 성공했을 때는
    성공한 root 만 하나씩 --root 로 짚어 줘야 한다."""
    repo, _ = project
    work_a = tmp_path / "a"
    work_b = tmp_path / "b"
    work_c = tmp_path / "c"
    old_file(work_a / "가.pdf")
    old_file(work_b / "나.pdf")
    old_file(work_c / "다.pdf")
    block_runlog_path(work_b)
    write_multi_recipe(repo, "multi3c", [work_a, work_b, work_c])

    assert cli.main(["run", "multi3c", "--apply"]) == 1
    out = capsys.readouterr().out

    assert "organize undo --recipe" not in out
    assert f"organize undo --root {work_a}" in out
    assert f"organize undo --root {work_c}" in out


def test_multi_root_apply_suggests_undo_by_recipe_not_only_first_root(project, tmp_path, capsys):
    """Important #1 — root 가 여러 개면 '되돌리려면' 안내가 roots[0] 만
    보여줘선 안 된다. organize undo --recipe <이름> 처럼 전체를 되돌리는
    명령을 제안해야 한다."""
    repo, _ = project
    work_a = tmp_path / "a"
    work_b = tmp_path / "b"
    old_file(work_a / "가.pdf")
    old_file(work_b / "나.pdf")
    write_multi_recipe(repo, "multi2", [work_a, work_b])

    assert cli.main(["run", "multi2", "--apply"]) == 0
    out = capsys.readouterr().out

    assert "organize undo --recipe multi2" in out


def test_multi_root_os_error_from_build_plan_does_not_abort_other_roots(
        project, tmp_path, capsys, monkeypatch):
    """Critical #2(보강) — OrganizeError 뿐 아니라 순정 OSError 도 root
    하나에서 새면 나머지 root 처리를 막지 못해야 한다."""
    repo, _ = project
    work_a = tmp_path / "a"
    work_b = tmp_path / "b"
    work_c = tmp_path / "c"
    old_file(work_a / "가.pdf")
    old_file(work_b / "나.pdf")
    old_file(work_c / "다.pdf")
    write_multi_recipe(repo, "multi3b", [work_a, work_b, work_c])

    real_build_plan = cli.build_plan

    def flaky(root, *a, **k):
        if root == work_b:
            raise OSError("디스크가 갑자기 사라짐(시뮬레이션)")
        return real_build_plan(root, *a, **k)

    monkeypatch.setattr(cli, "build_plan", flaky)

    assert cli.main(["run", "multi3b", "--apply"]) == 1
    out = capsys.readouterr().out
    assert (work_a / "01_Docs" / "가.pdf").exists()
    assert (work_c / "01_Docs" / "다.pdf").exists(), "B에서 OSError 가 나도 C는 처리돼야 한다"


def test_undo_keeps_going_when_one_root_has_nothing_to_undo(project, tmp_path, capsys):
    """폴더 여러 개를 되돌릴 때 하나가 실패해도 나머지는 되돌려야 한다.

    되돌릴 기록이 없는 폴더는 흔하다 — 이번에 처리되지 않은 폴더, 이미 되돌린
    폴더가 그렇다. 예전에는 `_cmd_undo` 의 반복문에 폴더 단위 격리가 없어서
    **첫 폴더에서 통째로 죽고 나머지 폴더는 옮겨진 채 남았다.** 실행 쪽에서
    고친 것과 정확히 같은 부류의 결함이다(Task 18 리뷰 Critical #2).
    """
    repo, work = project
    empty = tmp_path / "빈폴더"
    empty.mkdir()
    # 대상 폴더를 두 곳으로 바꾼다. 앞 폴더는 정리할 게 없어 되돌릴 기록도 없다.
    (repo / "recipes" / "t.json").write_text(json.dumps({
        "name": "테스트", "roots": [str(empty), str(work)],
        "steps": [{"block": "route", "profile": "desktop"}],
    }, ensure_ascii=False), encoding="utf-8")

    old_file(work / "보고서.pdf")
    cli.main(["run", "t", "--apply"])
    capsys.readouterr()
    assert (work / "01_Docs" / "보고서.pdf").exists()

    code = cli.main(["undo", "--recipe", "t"])
    out = capsys.readouterr().out

    assert (work / "보고서.pdf").read_bytes() == b"DATA", \
        "앞 폴더가 실패했다고 뒤 폴더를 포기하면 안 된다"
    assert str(empty) in out and str(work) in out, "두 폴더 모두 화면에 나와야 한다"
    assert code == 1, "실패가 있었으면 종료 코드에 드러나야 한다"


def test_undo_reports_a_failure_in_korean_without_a_raw_exception(project, tmp_path, capsys):
    """되돌리는 중 순정 파이썬 예외가 나도 화면에는 한국어만 나온다."""
    _, work = project
    old_file(work / "보고서.pdf")
    cli.main(["run", "t", "--apply"])
    capsys.readouterr()

    def _boom(_root, _run_id):
        raise OSError(13, "Permission denied")

    import organize.cli as cli_mod
    original = cli_mod.undo_run
    cli_mod.undo_run = _boom
    try:
        code = cli.main(["undo", "--root", str(work)])
    finally:
        cli_mod.undo_run = original

    out = capsys.readouterr().out
    assert "Permission denied" not in out
    assert code == 1
