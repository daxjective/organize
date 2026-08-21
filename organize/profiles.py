"""분류 규칙을 TOML 에서 읽고 파일 하나에 적용한다.

같은 매칭 코드를 프로파일 규칙과 step 의 `when` 필터가 함께 쓴다.
사용자가 배울 문법이 하나뿐이고, 조건 테스트도 한 벌이면 된다.
"""

import re
import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from organize.core.dates import has_exif_camera
from organize.core.scanner import FileEntry
from organize.errors import OrganizeError

_SIZE_UNITS = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}
_AGE_UNITS = {"d": 1, "m": 30, "y": 365}


def parse_size(text: str) -> int:
    # 단위 접두사와 B 를 따로 받는다. "2M" 처럼 B 를 생략해도 통해야 한다.
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([KMG]?)(B?)\s*", str(text), re.IGNORECASE)
    if not m:
        raise OrganizeError(f"크기 표기를 알 수 없습니다: {text}",
                            hint="100, 10KB, 2MB, 1GB 처럼 적어 주세요.")
    prefix = m.group(2).upper()
    return int(float(m.group(1)) * _SIZE_UNITS[(prefix + "B") if prefix else "B"])


def parse_age(text: str) -> timedelta:
    m = re.fullmatch(r"\s*(\d+)\s*([dmy])\s*", str(text), re.IGNORECASE)
    if not m:
        raise OrganizeError(f"기간 표기를 알 수 없습니다: {text}",
                            hint="30d, 6m, 2y 처럼 적어 주세요.")
    return timedelta(days=int(m.group(1)) * _AGE_UNITS[m.group(2).lower()])


@dataclass(frozen=True)
class Rule:
    to: str | None
    conditions: dict
    is_default: bool = False


@dataclass(frozen=True)
class Profile:
    name: str
    rules: list[Rule] = field(default_factory=list)
    synonyms: dict[str, list[str]] = field(default_factory=dict)


_CONDITION_KEYS = {"ext", "name_contains", "name_regex", "older_than",
                   "larger_than", "has_exif_camera"}


def load_profile(path: Path) -> Profile:
    if not path.is_file():
        raise OrganizeError(f"분류 설정을 찾을 수 없습니다: {path.name}",
                            hint="organize list 로 쓸 수 있는 설정을 확인해 주세요.")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise OrganizeError(f"분류 설정을 읽지 못했습니다: {path.name}",
                            hint=f"{e}") from e

    rules = []
    for raw in data.get("rules", []):
        conditions = {k: v for k, v in raw.items() if k in _CONDITION_KEYS}
        rules.append(Rule(to=raw.get("to"), conditions=conditions,
                          is_default=bool(raw.get("default", False))))
    return Profile(name=data.get("name", path.stem), rules=rules,
                   synonyms=data.get("synonyms", {}))


def matches(entry: FileEntry, conditions: dict, today: date) -> bool:
    for key, want in conditions.items():
        if key == "ext":
            if entry.ext not in [e.lower() for e in want]:
                return False
        elif key == "name_contains":
            if not any(w in entry.name for w in want):
                return False
        elif key == "name_regex":
            if not re.search(want, entry.name):
                return False
        elif key == "older_than":
            cutoff = datetime.combine(today, datetime.min.time()) - parse_age(want)
            if datetime.fromtimestamp(entry.mtime) > cutoff:
                return False
        elif key == "larger_than":
            if entry.size <= parse_size(want):
                return False
        elif key == "has_exif_camera":
            found = has_exif_camera(entry.path)
            if found is None or found != bool(want):
                return False
    return True


def route_target(entry: FileEntry, profile: Profile, today: date) -> str | None:
    for rule in profile.rules:
        if rule.is_default:
            return rule.to
        if matches(entry, rule.conditions, today):
            return rule.to
    return None
