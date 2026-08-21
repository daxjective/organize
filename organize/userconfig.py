"""설정을 2단으로 병합한다.

config.default.json   저장소에 포함. 모든 PC 공통 기본값
config.local.json     이 PC 전용. .gitignore 로 제외

별칭 하나에 경로를 여러 개 적으면 위에서부터 실제로 존재하는 첫 경로를 쓴다.
전부 없으면 마지막 것을 쓴다(그 자리에 만들 예정이라는 뜻).
외장하드를 안 꽂아도 레시피가 죽지 않게 하기 위한 장치다.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from organize.aliases import builtin_path
from organize.errors import OrganizeError


class AliasNotDefined(OrganizeError):
    pass


@dataclass(frozen=True)
class UserConfig:
    paths: dict[str, list[str]] = field(default_factory=dict)
    folder_names: dict[str, dict[str, str]] = field(default_factory=dict)
    pins: list[str] = field(default_factory=list)


def _read(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise OrganizeError(
            f"설정 파일을 읽지 못했습니다: {path.name} ({e.lineno}번째 줄)",
            hint="파일을 열어 쉼표나 따옴표가 빠지지 않았는지 확인해 주세요.",
        ) from e


def load_config(repo_root: Path) -> UserConfig:
    base = _read(repo_root / "config.default.json")
    local = _read(repo_root / "config.local.json")

    paths: dict[str, list[str]] = {}
    for src in (base, local):
        for name, value in (src.get("paths") or {}).items():
            paths[name] = [value] if isinstance(value, str) else list(value)

    folder_names: dict[str, dict[str, str]] = {}
    for src in (base, local):
        for profile, mapping in (src.get("folder_names") or {}).items():
            folder_names.setdefault(profile, {}).update(mapping)

    pins: list[str] = []
    for src in (base, local):
        for pattern in (src.get("pins") or []):
            if pattern not in pins:
                pins.append(pattern)

    return UserConfig(paths=paths, folder_names=folder_names, pins=pins)


def _first_existing(candidates: list[str], cfg: "UserConfig",
                    _seen: tuple[str, ...] = ()) -> Path:
    resolved = [resolve_alias(c, cfg, _seen=_seen) for c in candidates]
    for p in resolved:
        if p.exists():
            return p
    return resolved[-1]


def resolve_alias(spec: str, cfg: UserConfig, *,
                  _seen: tuple[str, ...] = ()) -> Path:
    """'@downloads', '@documents/메모', '~/foo', 'F:/day' 를 모두 받는다."""
    if not spec.startswith("@"):
        return Path(spec).expanduser()

    head, _, tail = spec[1:].partition("/")

    base = builtin_path(head)
    if base is None:
        if head in _seen:
            chain = " → ".join(f"@{n}" for n in (*_seen, head))
            raise AliasNotDefined(
                f"'@{head}' 위치가 돌고 돌아 자기 자신을 가리킵니다: {chain}",
                hint=f"config.local.json 에서 '@{head}' 가 가리키는 경로를 실제 폴더로 바꿔 주세요.",
            )
        if head not in cfg.paths:
            raise AliasNotDefined(
                f"'@{head}' 위치가 정해져 있지 않습니다.",
                hint=f"다음 명령으로 지정할 수 있습니다:\n    organize paths --set {head}=<경로>",
            )
        base = _first_existing(cfg.paths[head], cfg, _seen=(*_seen, head))

    return base / tail if tail else base
