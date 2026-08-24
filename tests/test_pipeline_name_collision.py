"""route -> by_date 체인에서 같은 이름 파일 둘이 서로를 잃지 않는지 확인한다.

Task 16 리뷰 Critical 1건의 재현·회귀 테스트. 근본 원인은 실행기가 아니라
블록이 만드는 Plan 자체였다 — 같은 이름 파일 둘을 한 폴더로 보낸 뒤 날짜별로
또 나누게 하면, 블록이 두 동작에 같은 dst(그리고 뒤 블록에서는 같은 src)를
줘서 실행기의 remap(경로 하나당 값 하나)이 둘을 구분하지 못했다.

이 파일은 러너(build_plan)와 실행기(execute)를 실제로 엮어서, 미리보기가
사실을 말하는지(각 동작이 서로 다른 경로를 가리키는지)와, 실제 실행이
실패 없이 두 파일을 모두 옮기는지를 함께 확인한다.
"""

import os
import time
from datetime import date
from pathlib import Path

from organize.core.executor import execute
from organize.core.runner import build_plan

TODAY = date(2026, 8, 21)


def _old_file(path: Path, data: bytes) -> Path:
    """방금 만든 파일은 '작업 중' 으로 걸러지므로 수정시각을 한 시간 전으로 돌린다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    past = time.time() - 3600
    os.utime(path, (past, past))
    return path


def _profiles_dir(tmp_path):
    d = tmp_path / "profiles"
    d.mkdir()
    (d / "desktop.toml").write_text(
        'name = "테스트"\n'
        '[[rules]]\n to = "01_Docs"\n ext = [".pdf", ".md"]\n'
        '[[rules]]\n to = "02_Media"\n ext = [".png"]\n'
        '[[rules]]\n to = "99_Unsorted"\n default = true\n',
        encoding="utf-8",
    )
    return d


def _same_name_scenario(tmp_path):
    """하위1/사진.png 와 하위2/사진.png 를 같은 02_Media 로 모은 뒤 연도별로 나눈다."""
    root = tmp_path / "작업"
    _old_file(root / "하위1" / "사진.png", b"AAAA")
    _old_file(root / "하위2" / "사진.png", b"BBBB")
    steps = [
        {"block": "route", "profile": "desktop", "target": "하위1", "dest": ""},
        {"block": "route", "profile": "desktop", "target": "하위2", "dest": ""},
        {"block": "by_date", "target": "02_Media", "layout": "{year}"},
    ]
    return root, steps


def test_preview_gives_each_file_its_own_destination(tmp_path):
    root, steps = _same_name_scenario(tmp_path)
    built = build_plan(root, steps, today=TODAY, run_id="r1",
                       profiles_dir=_profiles_dir(tmp_path))
    moves = [a for a in built.plan.actions if a.kind == "move"]

    route_dsts = {a.dst for a in moves if a.block == "route"}
    assert route_dsts == {
        root / "02_Media" / "사진.png",
        root / "02_Media" / "사진_(1).png",
    }

    by_date_moves = [a for a in moves if a.block == "by_date"]
    assert len(by_date_moves) == 2
    # 미리보기가 사실을 말한다 — 두 동작의 src 가 서로 다르다.
    srcs = {a.src for a in by_date_moves}
    assert srcs == {
        root / "02_Media" / "사진.png",
        root / "02_Media" / "사진_(1).png",
    }
    assert by_date_moves[0].src != by_date_moves[1].src
    # dst 도 서로 다르다.
    assert len({a.dst for a in by_date_moves}) == 2


def test_execution_moves_both_files_with_no_failures(tmp_path):
    root, steps = _same_name_scenario(tmp_path)
    built = build_plan(root, steps, today=TODAY, run_id="r1",
                       profiles_dir=_profiles_dir(tmp_path))
    result = execute(built)

    assert result.failed == []
    by_date_done = [d for d in result.done if d["kind"] == "move" and d["block"] == "by_date"]
    assert len(by_date_done) == 2

    finals = [Path(d["final"]) for d in by_date_done]
    # AAAA 와 BBBB 둘 다 연도 폴더로 갔다 — 내용이 뒤바뀌지 않았다.
    assert {f.read_bytes() for f in finals} == {b"AAAA", b"BBBB"}
    assert len({f.name for f in finals}) == 2          # 서로 다른 이름
    for f in finals:
        assert f.parent.parent == root / "02_Media"    # 연도 폴더 밑에 있다
        assert f.exists()
