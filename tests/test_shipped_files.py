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

from organize.core import dates
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


# --- 싣고 있는 photos.json 이 **평범한 사진 폴더**에서 진짜로 일하는가 ---

def _camera_jpg(path: Path, *, taken: str) -> Path:
    """EXIF 에 카메라 정보와 촬영일을 진짜로 박은 jpg. 카메라 사진으로 갈린다."""
    from PIL import ExifTags, Image
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (8, 8), (0, 255, 0))
    exif = img.getexif()
    exif[271] = "Canon"                       # Make
    exif[272] = "EOS R5"                      # Model
    exif.get_ifd(ExifTags.IFD.Exif)[36867] = taken
    img.save(path, exif=exif)
    return path


def _screenshot_jpg(path: Path) -> Path:
    """EXIF 카메라 정보가 없는 jpg — 화면 캡처로 갈린다."""
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), (0, 0, 255)).save(path)
    return path


def _run_shipped(name: str, root: Path):
    from organize.core.executor import execute
    recipe = load_recipe(find_recipe(RECIPES, name))
    built = build_plan(root, recipe.steps, today=date(2026, 1, 1), run_id="r1",
                       profiles_dir=PROFILES, now=1e12)
    return built, execute(built)


@pytest.mark.skipif(not dates.HAS_PILLOW, reason="Pillow 없이는 EXIF 를 만들 수 없다")
def test_shipped_photos_recipe_sorts_a_plain_picture_folder(tmp_path):
    """`02_Media` 가 **없는** 보통의 사진 폴더에서도 실제로 갈라져야 한다.

    한때 photos.json 이 `route(profile=photos, target="02_Media")` 로 시작해서,
    사진 폴더 바로 아래 있는 파일은 **손도 안 댔다.** 미리보기는
    "정리할 것이 없습니다 · 이동 0" 이었고 건너뛴 목록에도 안 나왔다 —
    이 프로젝트가 여덟 번 물린 "조용한 무작동" 이다. 실측한 결함이다.

    앞에 `route(profile=desktop)`(종류별 분류)를 두면 바로 아래 파일이 먼저
    02_Media 로 모이고, 그다음 두 단계가 캡처/사진·연도별로 가른다.
    """
    _camera_jpg(tmp_path / "루트사진.jpg", taken="2023:03:03 09:00:00")
    _screenshot_jpg(tmp_path / "루트캡처.jpg")
    (tmp_path / "루트영상.mp4").write_bytes(b"MP4DATA")

    built, result = _run_shipped("photos", tmp_path)

    assert built.plan.actions, "평범한 사진 폴더에서 계획이 비면 안 된다"
    assert not result.failed, result.failed
    assert (tmp_path / "02_Media" / "사진" / "2023" / "루트사진.jpg").is_file()
    assert (tmp_path / "02_Media" / "캡처" / "루트캡처.jpg").is_file()
    assert (tmp_path / "02_Media" / "영상" / "루트영상.mp4").is_file()
    assert not (tmp_path / "루트사진.jpg").exists(), "제자리에 남으면 무작동이다"


@pytest.mark.skipif(not dates.HAS_PILLOW, reason="Pillow 없이는 EXIF 를 만들 수 없다")
def test_shipped_photos_recipe_still_sorts_files_already_under_02_media(tmp_path):
    """옛 시나리오 — 이미 `02_Media` 아래 있는 파일도 그대로 갈려야 한다."""
    _camera_jpg(tmp_path / "02_Media" / "미디어사진.jpg", taken="2021:11:11 09:00:00")
    _screenshot_jpg(tmp_path / "02_Media" / "미디어캡처.jpg")

    _, result = _run_shipped("photos", tmp_path)

    assert not result.failed, result.failed
    assert (tmp_path / "02_Media" / "사진" / "2021" / "미디어사진.jpg").is_file()
    assert (tmp_path / "02_Media" / "캡처" / "미디어캡처.jpg").is_file()
