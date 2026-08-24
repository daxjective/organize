"""저장소가 **실제로 싣고 있는** 레시피·프로파일·README 가 사실인지 확인한다.

여기만 tmp_path 밖을 본다 — 다만 **읽기만 한다.** 사용자의 폴더는 건드리지
않고, 정리 대상은 언제나 tmp_path 다.

이 파일이 필요한 이유: README 빠른 시작 4줄 중 3줄이 실제로는 안 됐다.
문서에 적힌 사용처는 셋인데 레시피는 `downloads` 하나뿐이었다 — 클론한
사람이 첫 명령에서 막힌다. 사람이 다시 안 읽어도 CI 가 잡게 못박는다.
"""

import re
from datetime import date
from pathlib import Path

import pytest

from organize.core.runner import build_plan
from organize.profiles import load_profile
from organize.recipes import find_recipe, list_recipes, load_recipe

REPO = Path(__file__).resolve().parent.parent
RECIPES = REPO / "recipes"
PROFILES = REPO / "profiles"


def _recipe_names_in_readme() -> list[str]:
    text = (REPO / "README.md").read_text(encoding="utf-8")
    found = re.findall(r"organize\s+(?:preview|run)\s+(\S+)", text)
    return sorted({n for n in found if not n.startswith("<") and not n.startswith("-")})


def test_readme_quickstart_names_recipes_that_exist():
    named = _recipe_names_in_readme()
    assert named, "README 가 예로 든 레시피가 하나도 없다"
    available = list_recipes(RECIPES)
    missing = [n for n in named if n not in available]
    assert not missing, f"README 가 없는 레시피를 예로 들고 있다: {missing} (있는 것: {available})"


def test_readme_undo_example_names_a_folder():
    """`organize undo` 만 치면 '어느 폴더를 되돌릴지 알 수 없습니다' 로 끝난다."""
    text = (REPO / "README.md").read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("python") and " organize undo" in stripped:
            assert "--root" in stripped or "--recipe" in stripped, \
                f"되돌리기 예시에 대상이 없다: {stripped}"


@pytest.mark.parametrize("name", list_recipes(RECIPES))
def test_every_shipped_recipe_actually_builds_a_plan(name, tmp_path):
    """레시피가 문법·조건·프로파일까지 실제로 통과하는지 본다.
    대상 폴더는 빈 tmp_path 로 바꾼다 — 사용자의 진짜 폴더는 읽지 않는다."""
    recipe = load_recipe(find_recipe(RECIPES, name))
    assert recipe.roots, f"{name} 레시피에 대상 폴더가 없다"
    build_plan(tmp_path, recipe.steps, today=date.today(), run_id="r1",
               profiles_dir=PROFILES)


@pytest.mark.parametrize("path", sorted(PROFILES.glob("*.toml")), ids=lambda p: p.stem)
def test_every_shipped_profile_loads(path):
    load_profile(path)
