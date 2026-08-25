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


# ---------------------------------------------------------------------------
# 수정 라운드 2(최종 리뷰) — Critical #1/#2/#3.
# 셋 다 "파일은 옮겨졌는데 되돌릴 수 없고, 화면은 완료라고 말한다" 는 한 부류다.
# ---------------------------------------------------------------------------


def write_recipe(repo, name: str, roots: list[Path], steps: list[dict]) -> None:
    (repo / "recipes" / f"{name}.json").write_text(json.dumps({
        "name": name, "roots": [str(r) for r in roots], "steps": steps,
    }, ensure_ascii=False), encoding="utf-8")


def test_same_folder_listed_twice_still_leaves_a_usable_run_record(project, capsys):
    """Critical #1 — 레시피 roots 에 같은 폴더가 두 번 있으면(별칭 두 개가 같은
    곳을 가리키는 흔한 상황) 두 번째 통과가 **같은 run_id 로** prepare_runlog 을
    다시 불러 첫 통과의 기록을 `done: []` 뼈대로 덮어썼다. 화면은 "완료" 라고
    말하고 되돌리기 명령까지 권하는데, 그 명령은 "되돌릴 실행 기록이 없습니다"
    라고 답한다. 컨트롤러가 실측한 그대로다."""
    repo, work = project
    old_file(work / "보고서.pdf")
    write_recipe(repo, "dup", [work, work], [{"block": "route", "profile": "desktop"}])

    assert cli.main(["run", "dup", "--apply"]) == 0
    out = capsys.readouterr().out
    assert out.count(f"■ {work}") == 1, "같은 폴더를 두 번 정리하지 않는다"
    assert (work / "01_Docs" / "보고서.pdf").exists()

    assert cli.main(["undo", "--root", str(work)]) == 0, \
        "권한 되돌리기 명령이 실제로 되돌려야 한다"
    assert (work / "보고서.pdf").read_bytes() == b"DATA"


def test_two_runs_in_the_same_second_keep_both_records(project, tmp_path, capsys):
    """Critical #1(b) — run_id 는 초 단위다. 1초 안에 두 번 실행하면 두 번째
    prepare_runlog 이 첫 기록을 덮어써, 첫 실행이 옮긴 파일이 영영 갇힌다."""
    repo, work = project
    old_file(work / "보고서.pdf")
    old_file(work / "사진.png")
    write_recipe(repo, "one", [work], [{"block": "route", "profile": "desktop",
                                        "when": {"ext": [".pdf"]}}])
    write_recipe(repo, "two", [work], [{"block": "route", "profile": "desktop",
                                        "when": {"ext": [".png"]}}])

    # 같은 run_id 를 강제한다 — 1초 안에 두 번 친 것과 같다(타이밍 운에 안 맡긴다).
    import organize.cli as cli_mod
    original = cli_mod.make_run_id
    cli_mod.make_run_id = lambda now: "20260824-185957"
    try:
        assert cli.main(["run", "one", "--apply"]) == 0
        assert cli.main(["run", "two", "--apply"]) == 0
    finally:
        cli_mod.make_run_id = original
    capsys.readouterr()

    logs = sorted((work / ".organize" / "runs").glob("*.json"))
    assert len(logs) == 2, "실행 두 번이면 기록도 두 개여야 한다 — 덮어쓰면 안 된다"
    moved = [d for p in logs
             for d in json.loads(p.read_text(encoding="utf-8"))["done"]
             if d["kind"] == "move"]
    assert len(moved) == 2, "두 실행이 옮긴 것이 모두 기록에 남아야 한다"

    # 두 번 되돌리면 두 파일 모두 제자리로 온다
    assert cli.main(["undo", "--root", str(work)]) == 0
    assert cli.main(["undo", "--root", str(work)]) == 0
    assert (work / "보고서.pdf").exists() and (work / "사진.png").exists()


def test_bad_regex_in_a_recipe_never_reaches_a_python_traceback(project, tmp_path, capsys):
    """Critical #2 — 레시피의 정규식 오타 하나가 `re.error` 로 터졌다.
    `re.error` 는 ValueError 의 자식이라 per-root `except (OrganizeError, OSError)`
    도 `main()` 의 `except OrganizeError` 도 빠져나간다. 폴더 여러 개짜리
    레시피에서는 **앞 폴더에서 이미 옮긴 것의 되돌리기 안내가 통째로 사라진다.**
    파일을 하나도 건드리기 전에 한국어로 거부하는 것이 맞다."""
    repo, _ = project
    work_a = tmp_path / "a"
    work_b = tmp_path / "b"
    old_file(work_a / "가.pdf")
    old_file(work_b / "나.txt")          # route 의 when 에 안 걸려 root 에 남는다
    # 컨트롤러 재현과 같은 모양: 앞 폴더는 정규식을 만나지 않고(파일이 이미
    # 옮겨져 by_date 의 대상이 0건), 뒤 폴더에서만 터진다.
    write_recipe(repo, "badre", [work_a, work_b], [
        {"block": "route", "profile": "desktop", "when": {"ext": [".pdf"]}},
        {"block": "by_date", "when": {"name_regex": "[불완전"}},
    ])

    code = cli.main(["run", "badre", "--apply"])         # 예외가 새면 여기서 죽는다
    out = capsys.readouterr().out

    assert code == 1
    assert "Traceback" not in out and "re.error" not in out
    assert "name_regex" in out, "어느 조건이 잘못됐는지 짚어 줘야 한다"
    assert (work_a / "가.pdf").exists(), "계획 단계에서 막히므로 파일은 그대로다"
    assert not (work_a / "01_Docs").exists()
    assert (work_b / "나.txt").exists()


def test_an_unexpected_exception_in_one_root_does_not_abandon_the_others(
        project, tmp_path, capsys, monkeypatch):
    """Critical #2(그물) — 우리가 미처 못 본 예외가 또 있을 수 있다. 예외 종류를
    열거하는 그물은 세 번 뚫렸다. 무엇이 터지든 나머지 폴더는 살리고, 화면에
    한국어로 남기고, 종료 코드에 반영한다."""
    repo, _ = project
    work_a, work_b, work_c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    for w, n in ((work_a, "가.pdf"), (work_b, "나.pdf"), (work_c, "다.pdf")):
        old_file(w / n)
    write_multi_recipe(repo, "boom", [work_a, work_b, work_c])

    real_build_plan = cli.build_plan

    def flaky(root, *a, **k):
        if root == work_b:
            raise ValueError("아무도 예상 못 한 예외(시뮬레이션)")
        return real_build_plan(root, *a, **k)

    monkeypatch.setattr(cli, "build_plan", flaky)

    code = cli.main(["run", "boom", "--apply"])
    out = capsys.readouterr().out

    assert code == 1
    assert (work_a / "01_Docs" / "가.pdf").exists()
    assert (work_c / "01_Docs" / "다.pdf").exists(), "B가 죽어도 C는 처리돼야 한다"
    assert "아무도 예상 못 한 예외" not in out, "파이썬 예외 원문을 노출하지 않는다"
    assert str(work_b) in out


def test_ctrl_c_still_stops_everything(project, tmp_path, monkeypatch):
    """그물을 넓히면서 Ctrl-C 까지 삼키면 안 된다. KeyboardInterrupt 는
    Exception 의 자식이 아니므로 그대로 새어 나가야 한다."""
    repo, _ = project
    work_a = tmp_path / "a"
    old_file(work_a / "가.pdf")
    write_multi_recipe(repo, "ctrlc", [work_a])

    def interrupted(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "build_plan", interrupted)
    with pytest.raises(KeyboardInterrupt):
        cli.main(["run", "ctrlc", "--apply"])


def test_undo_says_the_record_is_unreadable_instead_of_nothing_to_undo(project, capsys):
    """Critical #3 — 기록이 쓰다 만 상태면 list_runs 가 조용히 건너뛰어
    "되돌릴 실행 기록이 없습니다" 가 나왔다. 파일은 옮겨져 있는데 말이다.
    없는 척하지 않는 것이 요점이다."""
    _, work = project
    old_file(work / "보고서.pdf")
    cli.main(["run", "t", "--apply"])
    capsys.readouterr()

    log = next((work / ".organize" / "runs").glob("*.json"))
    text = log.read_text(encoding="utf-8")
    log.write_text(text[:len(text) // 2], encoding="utf-8")     # 쓰다가 끊긴 상태

    code = cli.main(["undo", "--root", str(work)])
    out = capsys.readouterr().out

    assert code == 1
    assert "되돌릴 실행 기록이 없습니다" not in out, \
        "못 읽은 기록을 '없다' 로 말하면 안 된다"
    assert "읽지" in out or "손상" in out
    assert str(log) in out or log.name in out, "어느 파일인지 알려줘야 한다"


def test_undo_by_run_id_on_a_corrupted_record_is_korean_not_a_traceback(project, capsys):
    """Critical #3(덤) — 깨진 기록을 실행ID 로 콕 집으면 JSONDecodeError
    트레이스백이 그대로 떴다."""
    _, work = project
    old_file(work / "보고서.pdf")
    cli.main(["run", "t", "--apply"])
    capsys.readouterr()

    log = next((work / ".organize" / "runs").glob("*.json"))
    text = log.read_text(encoding="utf-8")
    log.write_text(text[:len(text) // 2], encoding="utf-8")

    code = cli.main(["undo", log.stem, "--root", str(work)])
    out = capsys.readouterr().out
    assert code == 1
    assert "JSONDecodeError" not in out and "Traceback" not in out
    assert "손상" in out or "읽지" in out


# ---------------------------------------------------------------------------
# 수정 라운드 2(최종 리뷰) — Important #2/#3/#4/#7, Minor #3/#4.
# ---------------------------------------------------------------------------


def test_undo_after_a_nested_layout_leaves_no_empty_folders(project, tmp_path, capsys):
    """Important #2 — `do by_date --layout '{year}/{month}'` 뒤 되돌리면
    연도 폴더가 비어 있는 채 남았다. 그런데 "실패 0" 으로 끝났다."""
    _, work = project
    old_file(work / "사진_2023-05-04.jpg")
    old_file(work / "사진_2024-11-11.jpg")

    assert cli.main(["do", "by_date", "--root", str(work),
                     "--layout", "{year}/{month}", "--apply"]) == 0
    assert cli.main(["undo", "--root", str(work)]) == 0
    capsys.readouterr()

    left = sorted(p.name for p in work.iterdir() if p.name != ".organize")
    assert left == ["사진_2023-05-04.jpg", "사진_2024-11-11.jpg"], \
        f"되돌린 뒤 없던 폴더가 남았다: {left}"


def test_a_failed_item_shows_its_hint_and_makes_the_exit_code_nonzero(
        project, capsys, monkeypatch):
    """Important #3 — executor 는 hint 를 일부러 보존하는데 CLI 가 그걸 버렸다.
    그리고 파일 하나가 안 옮겨졌는데 **종료 코드가 0** 이었다."""
    _, work = project
    old_file(work / "보고서.pdf")

    from organize.errors import OrganizeError

    def boom(src, dst):
        raise OrganizeError("파일을 만들 자리를 잡지 못했습니다: 보고서.pdf",
                            hint="대상 폴더의 쓰기 권한을 확인해 주세요.")

    import organize.core.executor as ex_mod
    monkeypatch.setattr(ex_mod, "move_file", boom)

    code = cli.main(["run", "t", "--apply"])
    out = capsys.readouterr().out

    assert "대상 폴더의 쓰기 권한을 확인해 주세요." in out, "hint 를 화면에서 버리면 안 된다"
    assert code == 1, "항목이 실패했으면 종료 코드에 드러나야 한다"


def test_a_failed_preview_does_not_suggest_apply(project, tmp_path, capsys):
    """Important #4 — 방금 안 된다고 말한 명령을 그대로 권하면 안 된다."""
    repo, work = project
    write_recipe(repo, "없는블록", [work], [{"block": "없는것"}])
    old_file(work / "보고서.pdf")

    assert cli.main(["preview", "없는블록"]) == 1
    out = capsys.readouterr().out
    assert "--apply" not in out, "실패한 미리보기가 --apply 를 권하면 안 된다"


def test_a_preview_with_nothing_to_do_does_not_suggest_apply(project, capsys):
    """할 일이 0건인데 "실제로 실행하려면" 을 권하는 것도 같은 부류다."""
    _, work = project
    assert cli.main(["preview", "t"]) == 0
    out = capsys.readouterr().out
    assert "--apply" not in out


@pytest.mark.parametrize("only", ["*.pdf", ".pdf", "pdf", "*.PDF"])
def test_do_only_accepts_the_forms_a_person_would_type(project, capsys, only):
    """Important #7 — `--only .pdf` 와 `--only pdf` 가 조용히 0건이었다.
    Path(".pdf").suffix 도 Path("pdf").suffix 도 빈 문자열이기 때문이다."""
    _, work = project
    old_file(work / "보고서.pdf")
    old_file(work / "사진.png")
    cli.main(["do", "route", "--root", str(work), "--profile", "desktop", "--only", only])
    assert "이동 1" in capsys.readouterr().out


def test_do_only_rejects_something_that_is_not_an_extension(project, capsys):
    _, work = project
    assert cli.main(["do", "route", "--root", str(work),
                     "--profile", "desktop", "--only", "폴더/이름.pdf"]) == 1
    assert "확장자" in capsys.readouterr().out


def test_stale_items_are_listed_not_just_counted(project, capsys, monkeypatch):
    """Minor #3 — `실패` 는 한 줄씩 찍는데 `건너뜀 3` 은 어떤 파일인지
    끝내 안 나왔다."""
    _, work = project
    old_file(work / "보고서.pdf")

    from organize.core.executor import ExecResult
    real_execute = cli.execute

    def with_stale(built):
        result = real_execute(built)
        result.stale.append({"kind": "move", "src": str(work / "다른파일.pdf"),
                             "why": "미리보기 이후에 파일이 바뀌었습니다"})
        return result

    monkeypatch.setattr(cli, "execute", with_stale)
    cli.main(["run", "t", "--apply"])
    out = capsys.readouterr().out
    assert "다른파일.pdf" in out, "건너뛴 파일이 무엇인지 알려줘야 한다"


def test_undo_tells_the_user_when_a_file_came_back_renamed(project, capsys):
    """Minor #4 — 원래 자리를 못 써서 다른 이름으로 돌려놓고 "실패 0" 이라고만 했다."""
    _, work = project
    old_file(work / "보고서.pdf")
    cli.main(["run", "t", "--apply"])
    capsys.readouterr()
    (work / "보고서.pdf").mkdir()          # 원래 자리를 막는다

    cli.main(["undo", "--root", str(work)])
    out = capsys.readouterr().out
    assert "이름" in out and "보고서_(1).pdf" in out


def test_two_runs_in_the_same_second_undo_in_reverse_order(project, capsys):
    """C1 수정이 새로 만든 결함 — `<run_id>-2.json` 이름이 `list_runs` 의
    최신순 정렬을 뒤집었다('-'(45) < '.'(46)). 옛 기록을 먼저 되돌리면
    그 실행이 만든 폴더 안에 아직 새 기록의 파일이 남아 있어 폴더가 안 지워지고,
    새 기록에는 mkdir 항목이 없어 나중에 아무도 안 지운다."""
    repo, work = project
    old_file(work / "a.pdf")
    old_file(work / "b.pdf")
    old_file(work / "c.md")
    write_recipe(repo, "ab", [work], [{"block": "route", "profile": "desktop",
                                       "when": {"ext": [".pdf"]}}])
    write_recipe(repo, "cc", [work], [{"block": "route", "profile": "desktop",
                                       "when": {"ext": [".md"]}}])

    import organize.cli as cli_mod
    original = cli_mod.make_run_id
    cli_mod.make_run_id = lambda now: "20260824-193928"
    try:
        assert cli.main(["run", "ab", "--apply"]) == 0
        assert cli.main(["run", "cc", "--apply"]) == 0
    finally:
        cli_mod.make_run_id = original
    capsys.readouterr()

    assert cli.main(["undo", "--root", str(work)]) == 0
    assert cli.main(["undo", "--root", str(work)]) == 0
    capsys.readouterr()

    left = sorted(p.name for p in work.iterdir() if p.name != ".organize")
    assert left == ["a.pdf", "b.pdf", "c.md"], f"되돌린 뒤 없던 폴더가 남았다: {left}"


# ---------------------------------------------------------------------------
# 마지막 라운드 — 실행이 중간에 끊기면 `undo --root` 가 "한 번 실행한 뒤에
# 쓸 수 있습니다" 라고 답한다. 파일은 옮겨져 있는데.
# ---------------------------------------------------------------------------


def _crash_after_moving(monkeypatch, keep: int = 2):
    """앞 `keep` 개 동작만 실제로 수행하고 예상 못 한 예외로 죽는다.
    진짜 프로그래밍 버그(TypeError)가 실행 도중에 터진 상황을 흉내낸다."""
    from organize.core.action import Plan
    from organize.core.runner import BuiltPlan
    real_execute = cli.execute
    state = {"done": False}

    def half_then_boom(built):
        if state["done"]:
            return real_execute(built)        # 한 번만 터진다 — 뒤 명령은 정상 동작
        state["done"] = True
        half = BuiltPlan(root=built.root, run_id=built.run_id,
                         plan=Plan(actions=built.plan.actions[:keep]),
                         snapshot=built.snapshot, runlog_path=built.runlog_path)
        real_execute(half)
        raise TypeError("코드 버그(시뮬레이션)")

    monkeypatch.setattr(cli, "execute", half_then_boom)


def test_an_interrupted_apply_never_says_the_folder_was_skipped(project, capsys, monkeypatch):
    """C2 의 새 그물이 "이 폴더는 건너뜁니다" 라고 말하는데, 그 시점엔 이미
    파일을 옮기고 폴더를 만든 뒤다. 안 건드렸다는 뜻으로 읽힌다."""
    _, work = project
    old_file(work / "a.pdf")
    old_file(work / "b.pdf")
    _crash_after_moving(monkeypatch)

    assert cli.main(["run", "t", "--apply"]) == 1
    out = capsys.readouterr().out

    assert (work / "01_Docs").is_dir(), "실제로 옮긴 뒤다"
    assert "건너뜁니다" not in out, "옮긴 뒤에 '건너뜁니다' 는 사실과 다르다"
    assert ".organize" in out, "무엇을 확인하면 되는지(기록 자리) 짚어 줘야 한다"


def test_undo_after_an_interrupted_apply_does_not_claim_you_never_ran_it(
        project, capsys, monkeypatch):
    """**축: `undo` 를 run_id 없이 치는 경로.** 사람이 실제로 치는 명령이다."""
    _, work = project
    old_file(work / "a.pdf")
    old_file(work / "b.pdf")
    _crash_after_moving(monkeypatch)
    cli.main(["run", "t", "--apply"])
    capsys.readouterr()

    code = cli.main(["undo", "--root", str(work)])
    out = capsys.readouterr().out
    assert code == 1
    assert "한 번 실행한 뒤에" not in out, "실행했고 파일도 옮겨졌다 — 거짓말이다"
    assert "완전하지 않" in out or "끊" in out


def test_an_apply_that_moved_nothing_does_not_suggest_undo(project, capsys, monkeypatch):
    """I4 의 apply 쪽 — 항목이 전부 실패해 아무것도 못 옮겼는데도
    `organize undo --root ...` 를 권했다. 그대로 치면 "기록이 없습니다" 가 나온다."""
    _, work = project
    old_file(work / "보고서.pdf")

    from organize.errors import OrganizeError

    def boom(src, dst):
        raise OrganizeError("파일을 만들 자리를 잡지 못했습니다",
                            hint="대상 폴더의 쓰기 권한을 확인해 주세요.")

    import organize.core.executor as ex_mod
    monkeypatch.setattr(ex_mod, "move_file", boom)
    # 목적지 폴더가 이미 있어야 mkdir 이 done 에 안 들어간다 — "아무것도 못 옮김"
    (work / "01_Docs").mkdir()

    assert cli.main(["run", "t", "--apply"]) == 1
    out = capsys.readouterr().out
    assert "organize undo" not in out, "되돌릴 것이 없는데 undo 를 권하면 안 된다"


def test_undo_still_works_when_the_config_has_pins(project, capsys):
    """I-2 — 미구현 키 하나 때문에 **되돌리기가 잠기면** 안 된다.
    되돌리기는 사용자의 마지막 안전줄이다. (doctor·paths 쪽은
    tests/test_cli_doctor.py 에 있다 — 그 픽스처만 홈 폴더를 격리한다.)"""
    repo, work = project
    old_file(work / "보고서.pdf")
    assert cli.main(["run", "t", "--apply"]) == 0
    capsys.readouterr()

    (repo / "config.local.json").write_text('{"pins": ["세금.pdf"]}', encoding="utf-8")

    assert cli.main(["undo", "--root", str(work)]) == 0, "되돌리기는 돌아야 한다"
    assert (work / "보고서.pdf").exists()
    assert "pins" in capsys.readouterr().out, "그래도 경고는 해야 한다"


def test_a_run_with_pins_in_the_config_still_refuses(project, capsys):
    """거부 자체는 유지한다 — 조용히 무시하면 보호를 기대한 파일이 옮겨진다."""
    repo, work = project
    old_file(work / "보고서.pdf")
    (repo / "config.local.json").write_text('{"pins": ["세금.pdf"]}', encoding="utf-8")

    assert cli.main(["run", "t", "--apply"]) == 1
    assert (work / "보고서.pdf").exists()
    assert "pins" in capsys.readouterr().out

    # 미리보기도 막는다 — 사용자가 미리보기 화면을 믿고 --apply 를 치기 때문이다.
    assert cli.main(["preview", "t"]) == 1
    assert "pins" in capsys.readouterr().out


def test_undo_mentions_records_it_could_not_use(project, capsys):
    """되돌리기가 성공해도, **옆에 못 되돌리는 기록이 남아 있으면 말해야 한다.**

    끊긴 실행이 옮겨 놓은 파일은 그대로 남아 있는데 화면은 `되돌림 N · 실패 0`
    뿐이다. 도구는 그 사실을 알고 있으면서(같은 `list_runs` 를 읽는다) 말하지
    않는다 — 사용자는 다 정리됐다고 믿는다. 이 프로젝트가 여덟 번 물린
    "조용한 무작동" 이다.
    """
    from organize.core.executor import prepare_runlog
    from organize.core.runner import BuiltPlan
    from organize.core.action import Action, Plan

    _, work = project
    old_file(work / "보고서.pdf")
    cli.main(["run", "t", "--apply"])          # 되돌릴 수 있는 정상 실행
    capsys.readouterr()

    # 그 옆에, 끊겨서 뼈대만 남은 실행 하나
    stranded = work / "01_Docs" / "끊긴것.pdf"
    prepare_runlog(BuiltPlan(root=work, run_id="99999999-000000",
                             plan=Plan(actions=[Action("move", stranded, stranded,
                                                       "이동", "route")])))

    assert cli.main(["undo", "--root", str(work)]) == 0
    out = capsys.readouterr().out

    assert "되돌림" in out
    assert "99999999-000000" in out, "못 되돌리는 기록이 있으면 어느 것인지 말해야 한다"


# ── 다른 드라이브로 백업 (SD카드·USB) ────────────────────────────
def test_a_recipe_can_send_files_to_a_registered_place(project, tmp_path, capsys):
    """이 도구를 만든 이유 — 백업. 레시피가 `@백업` 으로 밖에 내보낸다."""
    repo, work = project
    usb = tmp_path / "USB"
    usb.mkdir()
    (repo / "config.local.json").write_text(
        json.dumps({"paths": {"백업": str(usb)}}, ensure_ascii=False), encoding="utf-8")
    (repo / "recipes" / "t.json").write_text(json.dumps({
        "name": "백업", "roots": [str(work)],
        "steps": [{"block": "route", "profile": "desktop", "dest": "@백업"}],
    }, ensure_ascii=False), encoding="utf-8")
    old_file(work / "보고서.pdf")

    assert cli.main(["run", "t", "--apply"]) == 0
    assert (usb / "01_Docs" / "보고서.pdf").read_bytes() == b"DATA"
    assert not (work / "보고서.pdf").exists()

    # 그리고 되돌아와야 한다 — 드라이브를 넘었어도
    assert cli.main(["undo", "--root", str(work)]) == 0
    assert (work / "보고서.pdf").read_bytes() == b"DATA"


def test_an_unregistered_backup_name_fails_before_touching_anything(project, capsys):
    """등록 안 한 이름이면 **파일을 건드리기 전에** 멈춘다."""
    repo, work = project
    (repo / "recipes" / "t.json").write_text(json.dumps({
        "name": "백업", "roots": [str(work)],
        "steps": [{"block": "route", "profile": "desktop", "dest": "@없는것"}],
    }, ensure_ascii=False), encoding="utf-8")
    old_file(work / "보고서.pdf")

    assert cli.main(["run", "t", "--apply"]) == 1
    out = capsys.readouterr().out
    assert "없는것" in out
    assert "paths --set" in out or "paths --pick" in out
    assert (work / "보고서.pdf").exists(), "막았으면 파일은 그대로여야 한다"


def test_a_backup_drive_that_is_not_plugged_in_stops_before_moving(project, tmp_path, capsys):
    """SD카드·USB 는 안 꽂혀 있을 수 있다. 그때 **한 파일도 옮기지 않는다.**"""
    repo, work = project
    없는드라이브 = tmp_path / "안꽂힌USB"          # 만들지 않는다
    (repo / "config.local.json").write_text(
        json.dumps({"paths": {"백업": str(없는드라이브)}}, ensure_ascii=False), encoding="utf-8")
    (repo / "recipes" / "t.json").write_text(json.dumps({
        "name": "백업", "roots": [str(work)],
        "steps": [{"block": "route", "profile": "desktop", "dest": "@백업"}],
    }, ensure_ascii=False), encoding="utf-8")
    old_file(work / "보고서.pdf")

    code = cli.main(["run", "t", "--apply"])
    out = capsys.readouterr().out

    assert code == 1
    assert "백업" in out
    assert (work / "보고서.pdf").exists(), "드라이브가 없으면 한 파일도 옮기지 않는다"


def test_preview_warns_loudly_when_files_leave_the_folder(project, tmp_path, capsys):
    """파일이 **정리 대상 폴더 밖으로 나가면** 미리보기가 눈에 띄게 알린다.

    폴더 안에서 옮기는 것과 다른 드라이브로 내보내는 것은 무게가 다르다.
    USB 를 뽑으면 접근이 끊기고, 실수로 다른 매체에 쏟으면 되돌리기 전까지
    파일이 여기 없다. 화면에서 구분되지 않으면 사용자는 같은 일로 읽는다.
    """
    repo, work = project
    usb = tmp_path / "USB"
    usb.mkdir()
    (repo / "config.local.json").write_text(
        json.dumps({"paths": {"백업": str(usb)}}, ensure_ascii=False), encoding="utf-8")
    (repo / "recipes" / "t.json").write_text(json.dumps({
        "name": "백업", "roots": [str(work)],
        "steps": [{"block": "route", "profile": "desktop", "dest": "@백업"}],
    }, ensure_ascii=False), encoding="utf-8")
    old_file(work / "보고서.pdf")

    cli.main(["preview", "t"])
    out = capsys.readouterr().out

    assert str(usb) in out, "어디로 나가는지 경로가 보여야 한다"
    assert "밖" in out or "내보냅" in out, "밖으로 나간다는 사실이 보여야 한다"
    assert "1" in out, "몇 개가 나가는지 보여야 한다"


def test_preview_does_not_cry_wolf_when_nothing_leaves(project, capsys):
    """폴더 안에서만 움직이면 그 경고를 띄우지 않는다 — 매번 뜨면 안 보게 된다."""
    _, work = project
    old_file(work / "보고서.pdf")
    cli.main(["preview", "t"])
    out = capsys.readouterr().out
    assert "내보냅니다" not in out
