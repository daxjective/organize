"""카탈로그 표가 실제 블록·러너와 어긋나지 않는지 확인한다.

화면(다음 Task)은 이 카탈로그만 보고 체크박스를 그린다. 표가 러너의 실제
규칙(BLOCK_OPTIONS, _RESERVED)과 어긋나면 화면에서는 멀쩡해 보이던 체크박스가
실행 시점에만 거부된다 — 이 테스트들이 그 간극을 잡는다.
"""

from datetime import date
from pathlib import Path

import pytest

from organize.blocks import BLOCK_OPTIONS, get_block
from organize.catalog import by_id, catalog
from organize.core.runner import _RESERVED, build_plan
from organize.errors import OrganizeError

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_ids_are_unique():
    ids = [e.id for e in catalog()]
    assert len(ids) == len(set(ids))


def test_every_step_key_is_known_to_its_block():
    """여기 없는 키가 있으면 runner._check_keys 가 실행 시점에 거부한다.

    _RESERVED 를 여기서 다시 적지 않고 runner 에서 그대로 import 한다 —
    표를 두 벌로 만들면 한쪽만 고쳤을 때 조용히 어긋난다.
    """
    for e in catalog():
        block = e.step["block"]
        allowed = _RESERVED | set(BLOCK_OPTIONS[block])
        unknown = set(e.step) - allowed
        assert not unknown, f"{e.id}: 모르는 키 {unknown}"


def test_every_step_block_is_registered():
    for e in catalog():
        get_block(e.step["block"])  # 예외 없이 통과해야 한다


def _make_files(root: Path) -> None:
    root.mkdir()
    (root / "문서.pdf").write_bytes(b"pdf")
    (root / "그림.png").write_bytes(b"png")


def test_catalog_builds_a_real_plan(tmp_path):
    """카탈로그 전체로 진짜 계획이 서는지 — 가장 중요한 테스트.

    profiles_dir 는 저장소의 진짜 profiles/ 를 쓴다. 가짜 프로파일을 만들면
    "카탈로그가 없는 프로파일 이름을 가리키는가" 를 못 잡는다.
    """
    root = tmp_path / "작업"
    _make_files(root)

    steps = [e.step for e in catalog()]
    built = build_plan(root, steps, today=date(2026, 8, 25), run_id="t",
                       profiles_dir=REPO_ROOT / "profiles", now=1e12)

    assert built.plan.actions  # 비어 있으면 안 된다


def test_without_now_the_plan_is_silently_empty(tmp_path):
    """함정을 실제로 밟아 확인한다 — `now` 를 안 넘기면 방금 만든 파일이

    전부 "작업 중"으로 걸러져 계획이 조용히 비게 된다. 이 프로젝트가 이
    함정에 여덟 번 물렸다고 한다. 이 테스트는 **통과해야 정상**이다
    (= 함정이 실제로 존재함을 증명한다). 카탈로그 테스트 자신이 이 함정에
    걸리지 않았다는 것은 위 test_catalog_builds_a_real_plan 이
    `now=1e12` 를 넘겨서 따로 확인한다.
    """
    root = tmp_path / "작업"
    _make_files(root)

    steps = [e.step for e in catalog()]
    built = build_plan(root, steps, today=date(2026, 8, 25), run_id="t",
                       profiles_dir=REPO_ROOT / "profiles")  # now 없음

    assert built.plan.actions == []


def test_summary_does_not_lie_about_target():
    """화면에는 summary 만 보인다. summary 가 target 과 다른 곳을 가리키면

    사용자는 파일이 실제로 어디로 갔는지 알 길이 없다.
    """
    for e in catalog():
        target = e.step.get("target")
        if target:
            assert target in e.summary, (
                f"{e.id}: target={target!r} 이 summary({e.summary!r})에 없음"
            )


def test_by_id_unknown_raises_organize_error_not_key_error():
    with pytest.raises(OrganizeError) as ex:
        by_id("없는것")
    assert "없는것" in ex.value.message


def test_step_dict_is_isolated_between_calls():
    """호출자가 step 을 고쳐도 다음 호출자는 오염된 값을 받으면 안 된다."""
    first = by_id("unzip")
    first.step["delete_original"] = True  # 호출자가 받은 걸 고쳐본다

    second = by_id("unzip")
    assert "delete_original" not in second.step

    first_from_catalog = catalog()[0]
    first_from_catalog.step["target"] = "손댐"
    assert catalog()[0].step.get("target") != "손댐"
