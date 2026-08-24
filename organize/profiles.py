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
    # **아직 아무 데서도 읽지 않는다.** GUI(다음 단계)가 "이미 있는 폴더 중
    # 이 분류에 해당하는 것" 을 찾아 줄 때 쓸 자리다. 분류 동작에는 영향이 없다
    # — `route` 는 오직 `to` 만 본다.
    synonyms: dict[str, list[str]] = field(default_factory=dict)


# 러너도 레시피의 `when` 을 검사할 때 쓰므로 공개 이름으로 둔다.
CONDITION_KEYS = frozenset({"ext", "name_contains", "name_regex", "older_than",
                            "larger_than", "has_exif_camera"})
_CONDITION_KEYS = CONDITION_KEYS        # 기존 내부 사용처(이 파일 안)는 그대로 둔다
_META_KEYS = {"to", "default"}          # 조건이 아니라 규칙 자체를 기술하는 키

# 값이 "여러 개 중 하나라도 맞으면" 인 조건 — 목록을 받는다.
_ANY_OF_KEYS = ("ext", "name_contains")


def normalize_ext(value: str, where: str) -> str:
    """확장자 표기를 하나로 맞춘다. `.pdf` · `pdf` · `PDF` · `*.pdf` · `pdf.` 전부 `.pdf`.

    **레시피·프로파일의 `ext` 와 CLI 의 `--only` 가 같은 함수를 쓴다.** 예전에는
    `--only pdf` 는 도구가 점을 붙여 받아 주는데 프로파일의 `ext = "pdf"` 는
    조용히 0건이었다 — 같은 도구가 사용자를 **정반대로 가르쳤다.** 실측한 결함이다.

    `entry.ext` 는 `Path.suffix`(마지막 조각)이므로 `report.pdf` 처럼 이름을
    통째로 적었을 때도 마지막 조각만 쓴다. 어느 쪽이든 **말없이 0건이 되지만
    않으면** 된다.
    """
    text = value.strip().lower().strip("*")
    if "/" in text or "\\" in text:
        raise OrganizeError(
            f"{where} 에는 확장자만 적어 주세요: {value}",
            hint='예: pdf · .pdf · "*.pdf"')
    text = text.strip(".")              # 앞뒤 점을 다 떼고 하나만 다시 붙인다
    if "." in text:
        text = text.rsplit(".", 1)[-1]  # "report.pdf" -> "pdf"
    if not text:
        raise OrganizeError(
            f"{where} 값에서 확장자를 찾지 못했습니다: {value!r}",
            hint='예: pdf · .pdf · "*.pdf"')
    return "." + text


def normalize_conditions(conditions: dict, where: str) -> dict:
    """조건 **값의 타입까지** 검사하고 정규화한다. 파일을 건드리기 전에 부른다.

    커밋 63dcb33 이 조건 **키**의 오타(`whne`)를 막았지만, **값의 타입**은
    아무도 안 봤다. 결과가 똑같이 나빴다 — 실측이다.

      name_contains = "report"   ← 대괄호만 빠뜨림
      => any(w in name for w in "report") 는 글자 단위로 순회한다.
         `.jpg` 의 'p' 하나에도 걸려서 **폴더를 통째로 옮겼다.**
      ext = ".pdf"
      => ['.','p','d','f'] 가 되어 **아무것도 안 걸렸다.**

    그래서 문자열 하나는 **한 칸짜리 목록으로 감싼다.** 사용자가 쓴 대로
    동작하는 것이 가장 안 놀랍고, 거부보다 친절하다. 대신 그 밖의 타입
    (숫자·사전·빈 목록·목록 안의 비문자열)은 조용히 다르게 동작하느니
    한국어로 거부한다.

    `name_regex` 는 여기서 미리 컴파일해 본다. `re.error` 는 ValueError 의
    자식이라 실행 중에 터지면 per-root `except (OrganizeError, OSError)` 도
    `main()` 의 `except OrganizeError` 도 빠져나가, **앞 폴더에서 이미 옮긴
    것의 되돌리기 안내가 통째로 사라졌다.** 파일을 하나도 건드리기 전에
    죽는 것이 맞다.
    """
    out: dict = {}
    for key, want in conditions.items():
        if key == "ext":
            out[key] = [normalize_ext(v, f"{where} 의 'ext'")
                        for v in _as_list(key, want, where)]
        elif key in _ANY_OF_KEYS:
            out[key] = _as_list(key, want, where)
        elif key == "name_regex":
            if not isinstance(want, str):
                raise OrganizeError(
                    f"{where} 의 'name_regex' 는 글자로 적어야 합니다.",
                    hint='예: name_regex = "^IMG_[0-9]+"')
            try:
                re.compile(want)
            except re.error as e:
                raise OrganizeError(
                    f"{where} 의 'name_regex' 표현식을 이해하지 못했습니다: {want}",
                    # 파이썬 예외 원문(영어)을 그대로 넣지 않는다(전역 규칙).
                    hint="대괄호 [ ] · 괄호 ( ) 의 짝이 맞는지 확인해 주세요. "
                         '단순히 이름에 든 글자를 찾는 것이라면 name_contains = ["찾을말"] '
                         "가 더 안전합니다.") from e
            out[key] = want
        elif key in ("older_than", "larger_than"):
            # 표기가 틀리면 여기서 막힌다. **어느 규칙인지 붙여서** 다시 던진다 —
            # 다른 조건 오류에는 붙는 문맥이 여기만 빠져서, 규칙이 열 개인
            # 프로파일에서 어디를 고쳐야 할지 알 수 없었다.
            parse = parse_age if key == "older_than" else parse_size
            try:
                parse(_as_text(key, want, where))
            except OrganizeError as e:
                raise OrganizeError(f"{where} 의 '{key}' — {e.message}",
                                    hint=e.hint) from e
            out[key] = want
        elif key == "has_exif_camera":
            if not isinstance(want, bool):
                raise OrganizeError(
                    f"{where} 의 'has_exif_camera' 는 true 또는 false 여야 합니다.",
                    hint="예: has_exif_camera = true")
            out[key] = want
        else:
            out[key] = want                              # 키 검사는 부르는 쪽이 한다
    return out


def _as_list(key: str, want, where: str) -> list[str]:
    values: list[str] | None = None
    if isinstance(want, str):
        values = [want]                                  # 사용자가 쓴 대로 동작시킨다
    elif isinstance(want, (list, tuple)) and all(isinstance(w, str) for w in want):
        values = list(want)
    if values is not None and (not values or any(not v.strip() for v in values)):
        # 빈 **목록**은 거부하면서 빈 **문자열**을 통과시키면 비대칭이다.
        # `name_contains = ""` 은 감싸져서 `[""]` 가 되고 **모든 파일에 걸린다** —
        # I1 이 닫으려던 원래 증상("report 가 든 파일만" 이 폴더를 통째로
        # 옮겼다)이 그대로 되살아난다.
        raise OrganizeError(
            f"{where} 의 '{key}' 가 비어 있습니다 — "
            + ("모든 파일에 걸립니다." if key == "name_contains" else "아무 파일도 걸리지 않습니다."),
            hint=f'값을 적거나 조건 자체를 지워 주세요. 예: {key} = ["보고서"]')
    if values is not None:
        return values
    raise OrganizeError(
        f"{where} 의 '{key}' 값을 이해하지 못했습니다: {want!r}",
        hint=f'글자 하나이거나 글자 목록이어야 합니다. 예: {key} = ["보고서", "리포트"]')


def _as_text(key: str, want, where: str) -> str:
    if isinstance(want, str):
        return want
    if isinstance(want, (int, float)) and not isinstance(want, bool):
        return str(want)
    raise OrganizeError(
        f"{where} 의 '{key}' 값을 이해하지 못했습니다: {want!r}",
        hint='따옴표로 감싼 글자여야 합니다. 예: older_than = "30d", larger_than = "100MB"')


def load_profile(path: Path) -> Profile:
    if not path.is_file():
        raise OrganizeError(f"분류 설정을 찾을 수 없습니다: {path.name}",
                            hint="organize list 로 쓸 수 있는 설정을 확인해 주세요.")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise OrganizeError(
            f"분류 설정을 읽지 못했습니다: {path.name} (파서 메시지: {e})",
            hint="TOML 문법을 확인해 주세요 — 따옴표·대괄호 짝, 값이 빠진 줄이 없는지부터 봐 주세요.",
        ) from e

    raw_rules = data.get("rules", [])

    rules = []
    for i, raw in enumerate(raw_rules, start=1):
        unknown = sorted(set(raw) - _CONDITION_KEYS - _META_KEYS)
        if unknown:
            raise OrganizeError(
                f"{path.name} 의 {i}번째 규칙(to=\"{raw.get('to', '?')}\")에 "
                f"모르는 조건이 있습니다: {', '.join(unknown)}",
                hint="쓸 수 있는 조건: " + ", ".join(sorted(_CONDITION_KEYS)),
            )
        conditions = normalize_conditions(
            {k: v for k, v in raw.items() if k in _CONDITION_KEYS},
            f"{path.name} 의 {i}번째 규칙(to=\"{raw.get('to', '?')}\")")
        rules.append(Rule(to=raw.get("to"), conditions=conditions,
                          is_default=bool(raw.get("default", False))))

    default_indexes = [i for i, r in enumerate(rules) if r.is_default]
    if len(default_indexes) > 1:
        raise OrganizeError(
            f"{path.name} 에 default 규칙이 {len(default_indexes)}개 있습니다.",
            hint="default = true 인 규칙은 프로파일마다 하나만 둘 수 있습니다.",
        )
    if default_indexes and default_indexes[0] != len(rules) - 1:
        raise OrganizeError(
            f"{path.name} 의 default 규칙이 마지막에 있지 않습니다.",
            hint="default = true 인 규칙은 항상 맨 마지막에 두세요. "
                 "그 뒤에 오는 규칙은 실행되지 않습니다.",
        )

    return Profile(name=data.get("name", path.stem), rules=rules,
                   synonyms=data.get("synonyms", {}))


def matches(entry: FileEntry, conditions: dict, today: date) -> bool:
    # 값 타입 정규화를 여기서도 한 번 더 한다. 계획 시점(load_profile ·
    # runner._to_config)에서 이미 걸렀지만, 이 함수를 직접 부르는 길이 남아
    # 있으면 **같은 조건이 자리에 따라 다르게 동작하는** 상황이 생긴다.
    # 미리보기와 실행이 같아야 한다는 이 도구의 존재 이유가 걸린 자리다.
    conditions = normalize_conditions(conditions, "조건")
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
