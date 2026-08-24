"""레시피는 블록을 엮은 것이다. GUI 가 저장하므로 JSON 을 쓴다."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from organize.errors import OrganizeError


@dataclass
class Recipe:
    name: str
    roots: list[str] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)


def load_recipe(path: Path) -> Recipe:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise OrganizeError(
            f"레시피를 읽지 못했습니다: {path.name}",
            hint="파일이 있는지, 읽기 권한이 있는지 확인해 주세요.",
        ) from e
    except json.JSONDecodeError as e:
        # userconfig.py::_read() 와 같은 패턴 — hint 자리에 파이썬 예외
        # 원문(영어)을 그대로 넣지 않는다(전역 규칙). 몇 번째 줄인지만
        # 한국어로 짚어 준다.
        raise OrganizeError(
            f"레시피를 읽지 못했습니다: {path.name} ({e.lineno}번째 줄)",
            hint="파일을 열어 쉼표나 따옴표가 빠지지 않았는지 확인해 주세요.",
        ) from e

    if "steps" not in data:
        raise OrganizeError(
            f"레시피에 할 일이 없습니다: {path.name}",
            hint='"steps" 항목에 실행할 작업을 적어야 합니다.',
        )
    roots = data.get("roots", [])
    if isinstance(roots, str):
        roots = [roots]
    return Recipe(name=data.get("name", path.stem), roots=list(roots),
                  steps=list(data["steps"]))


def save_recipe(path: Path, recipe: Recipe) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(recipe), ensure_ascii=False, indent=2),
                    encoding="utf-8")


def list_recipes(recipes_dir: Path) -> list[str]:
    if not recipes_dir.is_dir():
        return []
    return sorted(p.stem for p in recipes_dir.glob("*.json"))


def find_recipe(recipes_dir: Path, name: str) -> Path:
    path = recipes_dir / (name if name.endswith(".json") else f"{name}.json")
    if not path.is_file():
        available = list_recipes(recipes_dir)
        raise OrganizeError(
            f"'{name}' 레시피가 없습니다.",
            hint=("쓸 수 있는 레시피: " + ", ".join(available)) if available
                 else "recipes 폴더에 레시피가 하나도 없습니다.",
        )
    return path
