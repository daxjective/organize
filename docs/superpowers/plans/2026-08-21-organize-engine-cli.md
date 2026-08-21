# organize 엔진과 CLI 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 터미널에서 `organize preview` / `organize run --apply` / `organize undo` 로 실제 폴더를 안전하게 정리할 수 있는 엔진과 CLI 를 만든다.

**Architecture:** "무엇을 할지 정하는 일"과 "실제로 하는 일"을 분리한다. 블록은 파일을 만지지 않고 `Action` 목록(`Plan`)만 만들며, 러너가 블록을 순서대로 엮어 하나의 `Plan` 으로 모은다. 실행기는 그 `Plan` 을 그대로 수행하고 `RunLog` 를 남긴다. 되돌리기는 `RunLog` 를 역순 재생한다. 미리보기와 실행이 같은 `Plan` 을 쓰므로 결과가 반드시 일치한다.

**Tech Stack:** Python 3.11+ 표준 라이브러리만 (`tomllib`, `json`, `hashlib`, `zipfile`, `ctypes`, `argparse`). 테스트는 `pytest`. `Pillow` 는 선택 의존성.

**Spec:** `docs/superpowers/specs/2026-08-19-organize-design.md`

## Global Constraints

이 절의 요구사항은 **모든 태스크에 암묵적으로 포함된다.**

- **Python 3.11 이상.** `tomllib` 이 3.11 에 들어왔다. 그 이하는 지원하지 않는다.
- **필수 외부 의존성 0.** `Pillow` 는 선택이며, 없으면 EXIF 를 건너뛰고 파일명·수정시각으로 폴백한다. import 실패를 잡아 처리하되 프로그램은 계속 돈다.
- **미리보기가 기본.** `--apply` 를 명시하지 않으면 어떤 파일도 생성·이동·삭제하지 않는다.
- **파일을 삭제하지 않는다.** 치우는 것은 전부 격리 폴더(`<root>/.organize/trash/<run-id>/`)로 이동이다. `os.remove` / `Path.unlink` 를 파일에 쓰지 않는다 (격리 폴더 비우기 명령만 예외이며 이 계획 범위 밖).
- **로컬에 실제로 있는 파일만 다룬다.** 클라우드에만 있는 파일(OneDrive 온라인 전용)은 읽지도 않는다.
- **폴더는 건드리지 않는다.** 이 계획의 어떤 블록도 폴더를 이동하거나 삭제하지 않는다.
- **결정적이어야 한다.** 같은 입력이면 항상 같은 `Plan` 이 나와야 한다. AI/LLM 을 쓰지 않고, `set` 순회 순서나 `os.listdir` 순서에 결과가 좌우되지 않게 항상 정렬한다.
- **테스트는 `tmp_path` 만 쓴다.** 사용자의 실제 폴더를 읽거나 쓰는 테스트를 만들지 않는다. 별칭 해석은 모킹한다. 개발 PC 가 바뀌어도 통과해야 한다.
- **CLI 출력 끝에 다음 명령어를 그대로 제안한다.** 사용자가 옵션을 다시 찾아보게 하지 않는다. 예: `실제로 실행하려면:\n    organize run downloads --apply`
- **오류 메시지는 한국어로, 사람 말로 쓴다.** 예외를 그대로 노출하지 않는다. 무엇이 문제고 무엇을 하면 되는지 쓴다.
- **경로는 항상 `pathlib.Path`.** 문자열 경로 연산을 하지 않는다.
- **커밋 메시지는 한국어 한 줄 + 필요시 본문.**

---

## 파일 구조

이 계획이 만드는 파일과 각자의 책임이다. 파일 하나는 책임 하나만 진다.

| 파일 | 책임 |
|---|---|
| `organize/__main__.py` | `python -m organize` 진입점. `cli.main()` 호출만 |
| `organize/cli.py` | 인자 파싱, 사람이 읽는 출력, 다음 명령어 제안 |
| `organize/errors.py` | 사용자용 예외. 메시지에 "무엇을 하면 되는지"를 포함 |
| `organize/aliases.py` | 내장 별칭 7개를 OS 에 질의해 실제 경로로 |
| `organize/userconfig.py` | `config.default.json` + `config.local.json` 병합, 대체 경로 체인 |
| `organize/core/action.py` | `Action`, `Plan` 자료구조. 로직 없음 |
| `organize/core/scanner.py` | 폴더를 읽어 `FileEntry` 목록. 제외 규칙 3종 |
| `organize/core/dates.py` | EXIF / 파일명 / 수정시각에서 날짜 하나 뽑기 |
| `organize/core/hashing.py` | 3단계 중복 판정, 남길 원본 선택 |
| `organize/core/paths.py` | 이름 충돌 시 번호 부여, 드라이브 판정, 실제 이동 |
| `organize/profiles.py` | TOML 프로파일 로더, 조건 매칭 (`when` 과 공용) |
| `organize/core/context.py` | 가상 파일 시스템 뷰. 블록 사이 상태 전달 |
| `organize/blocks/__init__.py` | 블록 레지스트리, `BlockConfig` |
| `organize/blocks/route.py` | 규칙 기반 분류 |
| `organize/blocks/by_date.py` | 날짜별 분류 |
| `organize/blocks/dedup.py` | 중복 제거 |
| `organize/blocks/unzip.py` | 압축 해제 |
| `organize/core/runner.py` | 블록을 순서대로 엮어 하나의 `Plan` 으로 |
| `organize/core/executor.py` | `Plan` 실행, 실행 직전 재검증, `RunLog` 기록 |
| `organize/core/undo.py` | `RunLog` 역순 재생 |
| `organize/recipes.py` | 레시피 JSON 로더/세이버 |

**의존 방향**은 한쪽으로만 흐른다. `core/*` 는 `blocks/*` 를 모르고, `blocks/*` 는 `cli.py` 를 모른다.

```
cli.py  →  recipes / runner / executor / undo
           runner  →  blocks/*  →  core/{context,scanner,hashing,dates,paths} · profiles
           executor → core/{action,paths}
```

## 이 계획이 다루지 않는 것

설계 문서의 아래 항목은 **빠뜨린 것이 아니라 다음 계획으로 미룬 것**이다.
계획 1 은 "터미널에서 실제로 폴더를 정리하고 되돌릴 수 있다" 까지를 책임진다.

| 설계 문서 | 어디로 | 왜 |
|---|---|---|
| §10 GUI 3화면 | **계획 2** | 엔진이 검증된 뒤에 올려야 화면이 흔들리지 않는다 |
| §6.6 폴더 이름 오버라이드 | **계획 2** | GUI 설정 화면에서 편집하는 값이다 |
| §5.5 `move_folders` | **계획 3** | 기본이 꺼짐이고, 폴더를 옮기는 유일한 기능이라 따로 다룬다 |
| §5.6 `empty_dirs` | **계획 3** | 정리 결과를 본 뒤에 필요성이 정해진다 |
| §6.7 중복 폴더 방지 3단계 | **계획 3** | 동의어 표와 제안 UI 가 필요하다 |
| §9.3 예약 실행 | **계획 3** | 수동 실행이 검증된 뒤에 자동화한다 |
| §9.4 고정(pin) · §9.5 규칙 제안 | **계획 3** | 실제로 써본 뒤 우선순위가 바뀔 수 있다 |
| §14.1 exe 포장 | **계획 3** | 기능 완성 후 마지막 단계 |

## 중간 확인 지점

Task 18 이 끝나면 **도구를 실제로 쓸 수 있다.** 거기서 한 번 멈추고 실제 폴더에
미리보기를 돌려본 뒤 Task 19 로 넘어가는 것을 권한다.

```
Task 1–9    자료구조와 읽기 — 아직 아무것도 못 한다
Task 10–13  블록 4개 — Plan 은 만들지만 실행은 못 한다
Task 14–17  실행과 되돌리기 — 엔진 완성
Task 18     CLI — ★ 여기서 실제로 쓸 수 있다
Task 19–20  편의 명령과 실사용 검증
```

---

### Task 1: 뼈대와 테스트 환경

**Files:**
- Create: `organize/__init__.py`, `organize/__main__.py`, `organize/cli.py`, `organize/errors.py`
- Create: `pyproject.toml`, `tests/__init__.py`
- Test: `tests/test_cli_smoke.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces:
  - `organize.cli.main(argv: list[str] | None = None) -> int` — 종료 코드 반환
  - `organize.errors.OrganizeError(Exception)` — 사용자에게 보여줄 메시지를 가진 예외. `__init__(self, message: str, hint: str | None = None)`
  - `organize.__version__: str`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_cli_smoke.py`:

```python
import pytest
from organize.cli import main
from organize.errors import OrganizeError


def test_version_prints_and_exits_zero(capsys):
    code = main(["--version"])
    out = capsys.readouterr().out
    assert code == 0
    assert "organize" in out


def test_no_args_shows_help_and_exits_zero(capsys):
    code = main([])
    out = capsys.readouterr().out
    assert code == 0
    assert "preview" in out          # 사용 가능한 명령이 안내되어야 한다


def test_unknown_command_is_friendly(capsys):
    code = main(["아무거나"])
    err = capsys.readouterr().out + capsys.readouterr().err
    assert code != 0


def test_organize_error_carries_hint():
    e = OrganizeError("경로를 찾을 수 없습니다.", hint="organize paths 로 확인하세요.")
    assert e.hint == "organize paths 로 확인하세요."
    assert "경로를 찾을 수 없습니다." in str(e)
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_cli_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'organize'`

- [ ] **Step 3: 최소 구현을 쓴다**

`pyproject.toml`:

```toml
[project]
name = "organize"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
exif = ["Pillow"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`organize/__init__.py`:

```python
__version__ = "0.1.0"
```

`organize/errors.py`:

```python
class OrganizeError(Exception):
    """사용자에게 그대로 보여줄 수 있는 오류.

    파이썬 예외 문구를 노출하지 않기 위해, 사람이 읽는 문장과
    "무엇을 하면 되는지"를 함께 담는다.
    """

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
```

`organize/cli.py`:

```python
import argparse
import sys

from organize import __version__
from organize.errors import OrganizeError

USAGE = """사용 가능한 명령

  organize preview <레시피>          미리보기 (파일을 건드리지 않음)
  organize run <레시피> --apply      실행
  organize undo                      되돌리기
  organize doctor                    환경 점검

자세히 보려면:
    organize <명령> --help
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="organize", add_help=True)
    p.add_argument("--version", action="store_true", help="버전 출력")
    p.add_argument("command", nargs="?", help="실행할 명령")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:            # argparse 가 종료하려 할 때 코드만 넘긴다
        return int(e.code or 0)

    if args.version:
        print(f"organize {__version__}")
        return 0

    if args.command is None:
        print(USAGE)
        return 0

    try:
        print(f"'{args.command}' 는 아직 없는 명령입니다.\n")
        print(USAGE)
        return 2
    except OrganizeError as e:
        print(f"{e.message}")
        if e.hint:
            print(f"\n{e.hint}")
        return 1
```

`organize/__main__.py`:

```python
import sys

from organize.cli import main

sys.exit(main())
```

`tests/__init__.py`: 빈 파일

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_cli_smoke.py -v`
Expected: PASS 4개

추가로 직접 실행해 본다:
Run: `python -m organize --version`
Expected: `organize 0.1.0`

- [ ] **Step 5: 커밋**

```bash
git add pyproject.toml organize/ tests/
git commit -m "organize 패키지 뼈대와 CLI 진입점 추가"
```

---

### Task 2: 내장 별칭 — OS 에 실제 경로를 물어본다

`~/Desktop` 으로 하드코딩하면 OneDrive 백업이 켜진 PC 에서 엉뚱한 폴더를 정리한다.
Windows 는 `SHGetKnownFolderPath` 로 물어봐야 리디렉션이 반영된 실제 경로가 나온다.

**Files:**
- Create: `organize/aliases.py`
- Test: `tests/test_aliases.py`

**Interfaces:**
- Consumes: `organize.errors.OrganizeError`
- Produces:
  - `organize.aliases.BUILTIN: tuple[str, ...]` — `("home","desktop","downloads","documents","pictures","music","videos")`
  - `organize.aliases.builtin_path(name: str) -> Path | None` — 내장 별칭이 아니면 `None`
  - `organize.aliases._windows_known_folder(guid: str) -> Path | None` (테스트에서 monkeypatch 대상)
  - `organize.aliases._posix_path(name: str) -> Path | None` (테스트에서 monkeypatch 대상)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_aliases.py`:

```python
from pathlib import Path

from organize import aliases


def test_builtin_names_are_the_seven_standard_folders():
    assert aliases.BUILTIN == (
        "home", "desktop", "downloads", "documents", "pictures", "music", "videos",
    )


def test_unknown_name_returns_none():
    assert aliases.builtin_path("archive") is None


def test_home_uses_pathlib_home(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert aliases.builtin_path("home") == tmp_path


def test_windows_asks_the_os_not_the_home_folder(monkeypatch, tmp_path):
    """OneDrive 로 리디렉션된 경로가 나와도 그대로 써야 한다."""
    redirected = tmp_path / "OneDrive" / "바탕 화면"
    monkeypatch.setattr(aliases.sys, "platform", "win32")
    monkeypatch.setattr(aliases, "_windows_known_folder", lambda guid: redirected)
    assert aliases.builtin_path("desktop") == redirected


def test_windows_falls_back_to_home_when_os_call_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(aliases.sys, "platform", "win32")
    monkeypatch.setattr(aliases, "_windows_known_folder", lambda guid: None)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert aliases.builtin_path("desktop") == tmp_path / "Desktop"


def test_posix_uses_xdg_lookup(monkeypatch, tmp_path):
    monkeypatch.setattr(aliases.sys, "platform", "linux")
    monkeypatch.setattr(aliases, "_posix_path", lambda name: tmp_path / "내려받기")
    assert aliases.builtin_path("downloads") == tmp_path / "내려받기"
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_aliases.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'organize.aliases'`

- [ ] **Step 3: 최소 구현을 쓴다**

`organize/aliases.py`:

```python
"""내장 별칭을 OS 에 물어 실제 경로로 바꾼다.

하드코딩하지 않는 이유: Windows 에서 OneDrive 백업을 켜면
바탕화면이 `C:\\Users\\<이름>\\OneDrive\\바탕 화면` 으로 리디렉션된다.
`~/Desktop` 을 쓰면 그 PC 에서 엉뚱한 빈 폴더를 정리하게 된다.
"""

import os
import sys
from pathlib import Path

# Windows KNOWNFOLDERID
_FOLDERID = {
    "desktop":   "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "pictures":  "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "music":     "{4BD8D571-6D19-48D3-BE97-422220080E43}",
    "videos":    "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
}

# XDG 이름과 홈 아래 기본 폴더명
_XDG = {
    "desktop":   ("XDG_DESKTOP_DIR",   "Desktop"),
    "downloads": ("XDG_DOWNLOAD_DIR",  "Downloads"),
    "documents": ("XDG_DOCUMENTS_DIR", "Documents"),
    "pictures":  ("XDG_PICTURES_DIR",  "Pictures"),
    "music":     ("XDG_MUSIC_DIR",     "Music"),
    "videos":    ("XDG_VIDEOS_DIR",    "Videos"),
}

BUILTIN: tuple[str, ...] = (
    "home", "desktop", "downloads", "documents", "pictures", "music", "videos",
)


def _windows_known_folder(guid: str) -> Path | None:
    """Windows 셸에 알려진 폴더의 실제 경로를 묻는다. 실패하면 None."""
    import ctypes
    from ctypes import wintypes

    class _GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_byte * 8),
        ]

    try:
        ole32 = ctypes.windll.ole32
        shell32 = ctypes.windll.shell32
    except (AttributeError, OSError):
        return None

    g = _GUID()
    if ole32.CLSIDFromString(ctypes.c_wchar_p(guid), ctypes.byref(g)) != 0:
        return None
    out = ctypes.c_wchar_p()
    if shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) != 0:
        return None
    try:
        return Path(out.value) if out.value else None
    finally:
        ole32.CoTaskMemFree(out)


def _posix_path(name: str) -> Path | None:
    """XDG 환경변수 → 홈 아래 기본 폴더명 순으로 찾는다."""
    env, default = _XDG[name]
    raw = os.environ.get(env)
    if raw:
        return Path(os.path.expandvars(raw)).expanduser()
    candidate = Path.home() / default
    return candidate if candidate.is_dir() else None


def builtin_path(name: str) -> Path | None:
    """내장 별칭 이름을 실제 경로로. 내장이 아니면 None."""
    if name not in BUILTIN:
        return None
    if name == "home":
        return Path.home()

    if sys.platform == "win32":
        found = _windows_known_folder(_FOLDERID[name])
        if found is not None:
            return found
    else:
        found = _posix_path(name)
        if found is not None:
            return found

    # OS 가 답하지 못하면 홈 아래 영문 기본 폴더명으로 폴백한다
    return Path.home() / _XDG[name][1]
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_aliases.py -v`
Expected: PASS 6개

실제 환경에서도 한 번 눈으로 본다:
Run: `python -c "from organize.aliases import BUILTIN, builtin_path; [print(f'{n:10} {builtin_path(n)}') for n in BUILTIN]"`
Expected: 일곱 줄이 나오고 경로가 이 PC 의 실제 폴더를 가리킨다

- [ ] **Step 5: 커밋**

```bash
git add organize/aliases.py tests/test_aliases.py
git commit -m "내장 별칭 해석 추가 — OS 에 실제 경로를 질의"
```

---

### Task 3: 사용자 설정 — 2단 병합과 대체 경로 체인

새 PC 에서 설정 없이 돌아야 하고, 외장하드를 안 꽂아도 레시피가 죽으면 안 된다.

**Files:**
- Create: `organize/userconfig.py`, `config.default.json`
- Test: `tests/test_userconfig.py`

**Interfaces:**
- Consumes: `organize.aliases.builtin_path`, `organize.errors.OrganizeError`
- Produces:
  - `organize.userconfig.UserConfig` — `paths: dict[str, list[str]]`, `folder_names: dict[str, dict[str, str]]`, `pins: list[str]`
  - `organize.userconfig.load_config(repo_root: Path) -> UserConfig`
  - `organize.userconfig.resolve_alias(spec: str, cfg: UserConfig, *, _seen: tuple[str, ...] = ()) -> Path` — `_seen` 은 순환 참조 방어용 내부 인자다. 호출자는 두 인자로만 부른다
  - `organize.userconfig.AliasNotDefined(OrganizeError)`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_userconfig.py`:

```python
import json
from pathlib import Path

import pytest

from organize import aliases, userconfig
from organize.userconfig import AliasNotDefined, UserConfig, load_config, resolve_alias


def write(p: Path, data: dict) -> None:
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_local_overrides_default(tmp_path):
    write(tmp_path / "config.default.json", {"paths": {"archive": "@documents/Archive"}})
    write(tmp_path / "config.local.json", {"paths": {"archive": "D:/보관"}})
    cfg = load_config(tmp_path)
    assert cfg.paths["archive"] == ["D:/보관"]


def test_works_with_no_local_file(tmp_path):
    write(tmp_path / "config.default.json", {"paths": {"archive": "@documents/Archive"}})
    cfg = load_config(tmp_path)
    assert cfg.paths["archive"] == ["@documents/Archive"]


def test_missing_both_files_is_not_an_error(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg.paths == {}
    assert cfg.pins == []


def test_single_string_is_normalised_to_a_list(tmp_path):
    write(tmp_path / "config.default.json", {"paths": {"a": "X:/one"}})
    assert load_config(tmp_path).paths["a"] == ["X:/one"]


def test_chain_picks_the_first_existing_path(tmp_path):
    present = tmp_path / "있음"
    present.mkdir()
    cfg = UserConfig(paths={"archive": [str(tmp_path / "없음"), str(present)]},
                     folder_names={}, pins=[])
    assert resolve_alias("@archive", cfg) == present


def test_chain_falls_back_to_the_last_entry_when_none_exist(tmp_path):
    last = tmp_path / "만들예정"
    cfg = UserConfig(paths={"archive": [str(tmp_path / "없음"), str(last)]},
                     folder_names={}, pins=[])
    assert resolve_alias("@archive", cfg) == last


def test_builtin_alias_resolves(monkeypatch, tmp_path):
    monkeypatch.setattr(userconfig, "builtin_path",
                        lambda name: tmp_path / "다운로드" if name == "downloads" else None)
    cfg = UserConfig(paths={}, folder_names={}, pins=[])
    assert resolve_alias("@downloads", cfg) == tmp_path / "다운로드"


def test_builtin_alias_with_subpath(monkeypatch, tmp_path):
    monkeypatch.setattr(userconfig, "builtin_path",
                        lambda name: tmp_path / "문서" if name == "documents" else None)
    cfg = UserConfig(paths={}, folder_names={}, pins=[])
    assert resolve_alias("@documents/메모", cfg) == tmp_path / "문서" / "메모"


def test_plain_path_passes_through(tmp_path):
    cfg = UserConfig(paths={}, folder_names={}, pins=[])
    assert resolve_alias(str(tmp_path), cfg) == tmp_path


def test_self_referencing_alias_is_caught(tmp_path):
    """손으로 고친 config.local.json 이 자기 자신을 가리켜도 트레이스백이 아니라 안내가 나와야 한다."""
    cfg = UserConfig(paths={"archive": ["@archive"]}, folder_names={}, pins=[])
    with pytest.raises(AliasNotDefined) as e:
        resolve_alias("@archive", cfg)
    assert "archive" in e.value.message
    assert e.value.hint


def test_mutually_referencing_aliases_are_caught():
    cfg = UserConfig(paths={"a": ["@b"], "b": ["@a"]}, folder_names={}, pins=[])
    with pytest.raises(AliasNotDefined) as e:
        resolve_alias("@a", cfg)
    assert e.value.hint


def test_undefined_alias_says_what_to_do():
    cfg = UserConfig(paths={}, folder_names={}, pins=[])
    with pytest.raises(AliasNotDefined) as e:
        resolve_alias("@archive", cfg)
    assert "archive" in e.value.message
    assert e.value.hint and "organize paths" in e.value.hint
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_userconfig.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'organize.userconfig'`

- [ ] **Step 3: 최소 구현을 쓴다**

`organize/userconfig.py`:

```python
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


def _first_existing(candidates: list[str], cfg: UserConfig,
                    _seen: tuple[str, ...] = ()) -> Path:
    resolved = [resolve_alias(c, cfg, _seen=_seen) for c in candidates]
    for p in resolved:
        if p.exists():
            return p
    return resolved[-1]


def resolve_alias(spec: str, cfg: UserConfig, *,
                  _seen: tuple[str, ...] = ()) -> Path:
    """'@downloads', '@documents/메모', '~/foo', 'F:/day' 를 모두 받는다.

    `_seen` 은 해석 중인 별칭 이름들이다. 별칭이 자기 자신이나 서로를 가리키면
    무한 재귀에 빠지는데, 그러면 RecursionError 트레이스백이 그대로 노출된다.
    사용자가 config.local.json 을 손으로 고치므로 실제로 일어날 수 있다.
    """
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
```

`config.default.json`:

```json
{
  "paths": {
    "archive": "@documents/Archive",
    "photos": "@pictures",
    "work": "@documents"
  },
  "folder_names": {},
  "pins": []
}
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_userconfig.py -v`
Expected: PASS 12개

- [ ] **Step 5: 커밋**

```bash
git add organize/userconfig.py config.default.json tests/test_userconfig.py
git commit -m "사용자 설정 2단 병합과 대체 경로 체인 추가"
```

---

### Task 4: Action 과 Plan — 미리보기와 실행이 공유하는 자료구조

**Files:**
- Create: `organize/core/__init__.py`, `organize/core/action.py`
- Test: `tests/test_action.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `organize.core.action.ActionKind = Literal["mkdir", "move", "quarantine", "extract"]`
  - `organize.core.action.Action` — `kind`, `src: Path | None`, `dst: Path | None`, `reason: str`, `block: str`, `member: str | None = None`. frozen dataclass. `member` 는 `extract` 에서만 쓰며 압축 안의 원래 항목 이름을 담는다 (실행기가 무엇을 꺼낼지 알아야 한다)
  - `organize.core.action.Plan` — `actions: list[Action]`, `skipped: list[tuple[Path, str]]`, `counts() -> dict[str, int]`, `extend(other: Plan) -> None`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_action.py`:

```python
from pathlib import Path

import pytest

from organize.core.action import Action, Plan


def make(kind="move", src="a.png", dst="02_Media/a.png"):
    return Action(kind=kind, src=Path(src), dst=Path(dst), reason="확장자 .png", block="route")


def test_action_is_immutable():
    a = make()
    with pytest.raises(Exception):
        a.reason = "다른 이유"


def test_counts_groups_by_kind():
    plan = Plan()
    plan.actions.extend([make(), make(), make(kind="quarantine")])
    assert plan.counts() == {"move": 2, "quarantine": 1}


def test_counts_of_empty_plan_is_empty():
    assert Plan().counts() == {}


def test_extend_merges_actions_and_skipped():
    a, b = Plan(), Plan()
    a.actions.append(make())
    a.skipped.append((Path("x.txt"), "대상이 아님"))
    b.actions.append(make(kind="mkdir", src=None, dst="02_Media"))
    b.skipped.append((Path("y.txt"), "시스템 파일"))
    a.extend(b)
    assert len(a.actions) == 2
    assert len(a.skipped) == 2


def test_mkdir_action_has_no_src():
    a = Action(kind="mkdir", src=None, dst=Path("02_Media"), reason="분류 결과를 담을 폴더", block="route")
    assert a.src is None
    assert a.member is None


def test_extract_action_carries_the_member_name():
    a = Action(kind="extract", src=Path("자료.zip"), dst=Path("문서.pdf"),
               reason="자료.zip 에서 꺼냄", block="unzip", member="안쪽폴더/문서.pdf")
    assert a.member == "안쪽폴더/문서.pdf"
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_action.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'organize.core'`

- [ ] **Step 3: 최소 구현을 쓴다**

`organize/core/__init__.py`: 빈 파일

`organize/core/action.py`:

```python
"""미리보기와 실행이 공유하는 자료구조.

블록은 파일을 만지지 않고 Action 목록만 만든다.
실행기는 그 목록을 그대로 수행한다. 따라서 미리보기에서 본 것과
실제로 일어나는 일이 반드시 같다.
"""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

ActionKind = Literal["mkdir", "move", "quarantine", "extract"]


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    src: Path | None       # mkdir 은 None
    dst: Path | None       # quarantine 은 격리 폴더 안의 경로
    reason: str            # 사람이 읽는 근거. UI 에 그대로 표시된다
    block: str             # 이 Action 을 만든 블록 이름
    member: str | None = None   # extract 전용 — 압축 안에서 꺼낼 항목 이름


@dataclass
class Plan:
    actions: list[Action] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return dict(Counter(a.kind for a in self.actions))

    def extend(self, other: "Plan") -> None:
        self.actions.extend(other.actions)
        self.skipped.extend(other.skipped)
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_action.py -v`
Expected: PASS 5개

- [ ] **Step 5: 커밋**

```bash
git add organize/core/ tests/test_action.py
git commit -m "Action / Plan 자료구조 추가"
```

---

### Task 5: 스캐너 — 건드리면 안 되는 파일을 먼저 걸러낸다

세 종류를 제외한다. 실제 폴더에 돌려보고 발견한 것들이라 전부 근거가 있다.

**Files:**
- Create: `organize/core/scanner.py`
- Test: `tests/test_scanner.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `organize.core.scanner.FileEntry` — frozen dataclass. `path: Path`, `size: int`, `mtime: float`. 프로퍼티 `name -> str`, `ext -> str`(소문자, 점 포함)
  - `organize.core.scanner.ScanResult` — `entries: list[FileEntry]`, `skipped: list[tuple[Path, str]]`
  - `organize.core.scanner.is_system_file(name: str) -> bool`
  - `organize.core.scanner.is_in_progress(name: str, mtime: float, now: float) -> bool`
  - `organize.core.scanner._is_cloud_attrs(attrs: int) -> bool` — 속성 비트만 보고 판정하는 순수 함수. Windows 없이 테스트할 수 있도록 분리한다
  - `organize.core.scanner.is_cloud_only(path: Path) -> bool`
  - `organize.core.scanner.scan(root: Path, *, recursive: bool = False, now: float | None = None, exclude_dirs: frozenset[str] = frozenset()) -> ScanResult`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_scanner.py`:

```python
import time
from pathlib import Path

from organize.core import scanner
from organize.core.scanner import FileEntry, is_in_progress, is_system_file, scan


def touch(p: Path, content: bytes = b"x", age_seconds: float = 3600) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    old = time.time() - age_seconds
    import os
    os.utime(p, (old, old))
    return p


def test_system_files_are_recognised():
    assert is_system_file("desktop.ini")
    assert is_system_file("Desktop.INI")          # 대소문자 무관
    assert is_system_file("Thumbs.db")
    assert is_system_file(".DS_Store")
    assert is_system_file("~$보고서.docx")         # Office 임시 파일
    assert not is_system_file("보고서.docx")


def test_in_progress_by_extension():
    now = time.time()
    assert is_in_progress("영화.mp4.crdownload", now - 9999, now)
    assert is_in_progress("자료.part", now - 9999, now)
    assert not is_in_progress("자료.pdf", now - 9999, now)


def test_in_progress_by_recent_modification():
    now = time.time()
    assert is_in_progress("자료.pdf", now - 10, now)      # 10초 전 = 작업 중일 수 있음
    assert not is_in_progress("자료.pdf", now - 120, now)  # 2분 전 = 안정


def test_scan_returns_sorted_entries(tmp_path):
    touch(tmp_path / "b.txt")
    touch(tmp_path / "a.txt")
    result = scan(tmp_path)
    assert [e.name for e in result.entries] == ["a.txt", "b.txt"]


def test_scan_excludes_system_files_with_reason(tmp_path):
    touch(tmp_path / "보고서.pdf")
    touch(tmp_path / "desktop.ini")
    result = scan(tmp_path)
    assert [e.name for e in result.entries] == ["보고서.pdf"]
    assert len(result.skipped) == 1
    assert "시스템 파일" in result.skipped[0][1]


def test_scan_excludes_in_progress_downloads(tmp_path):
    touch(tmp_path / "영화.mp4.crdownload")
    result = scan(tmp_path)
    assert result.entries == []
    assert "받는 중" in result.skipped[0][1]


def test_scan_excludes_cloud_only_files(tmp_path, monkeypatch):
    touch(tmp_path / "온라인.jpg")
    touch(tmp_path / "로컬.jpg")
    monkeypatch.setattr(scanner, "is_cloud_only", lambda p: p.name == "온라인.jpg")
    result = scan(tmp_path)
    assert [e.name for e in result.entries] == ["로컬.jpg"]
    assert "OneDrive" in result.skipped[0][1]


def test_scan_is_not_recursive_by_default(tmp_path):
    touch(tmp_path / "위.txt")
    touch(tmp_path / "하위" / "아래.txt")
    assert [e.name for e in scan(tmp_path).entries] == ["위.txt"]


def test_scan_recursive_reaches_subfolders(tmp_path):
    touch(tmp_path / "위.txt")
    touch(tmp_path / "하위" / "아래.txt")
    names = sorted(e.name for e in scan(tmp_path, recursive=True).entries)
    assert names == ["아래.txt", "위.txt"]


def test_scan_never_enters_organize_folder(tmp_path):
    touch(tmp_path / ".organize" / "trash" / "지운것.png")
    touch(tmp_path / "정상.png")
    assert [e.name for e in scan(tmp_path, recursive=True).entries] == ["정상.png"]


def test_scan_skips_named_exclude_dirs(tmp_path):
    touch(tmp_path / "01_Docs" / "이미정리됨.pdf")
    touch(tmp_path / "새파일.pdf")
    result = scan(tmp_path, recursive=True, exclude_dirs=frozenset({"01_Docs"}))
    assert [e.name for e in result.entries] == ["새파일.pdf"]


def test_cloud_attribute_bits(tmp_path):
    """속성 비트 판정은 Windows 없이도 검증할 수 있어야 한다."""
    from organize.core.scanner import _is_cloud_attrs
    assert _is_cloud_attrs(0x00400000)      # RECALL_ON_DATA_ACCESS
    assert _is_cloud_attrs(0x00040000)      # RECALL_ON_OPEN
    assert _is_cloud_attrs(0x00001000)      # OFFLINE
    assert not _is_cloud_attrs(0x20)        # ARCHIVE 뿐이면 로컬 파일이다
    assert not _is_cloud_attrs(0xFFFFFFFF)  # 읽기 실패는 클라우드가 아니다
    assert not _is_cloud_attrs(-1)          # 부호 있는 해석으로 들어와도 마찬가지


def test_symlink_to_a_directory_is_not_a_file(tmp_path):
    """폴더를 가리키는 링크는 폴더로 취급해야 한다. 파일로 새면 그 폴더의
    크기·수정시각을 가진 항목이 정리 대상이 된다.

    **대상 폴더의 mtime 도 과거로 돌려야 한다.** 갓 만든 폴더는 "최근 1분 내 수정"
    필터에 걸리므로, 링크가 파일로 새어나와도 entries 가 아니라 skipped 로 빠진다.
    그러면 버그가 있는 코드에서도 이 테스트가 통과해 버린다 — 실측으로 확인했다.
    회귀 테스트는 옛 코드에서 반드시 실패해야 한다.
    """
    import os
    inner = tmp_path / "실제폴더"
    inner.mkdir()
    touch(inner / "안쪽.txt")
    touch(tmp_path / "정상.txt")
    os.symlink(inner, tmp_path / "폴더링크")
    past = time.time() - 3600
    os.utime(inner, (past, past))          # 폴더 자체도 과거로 돌린다

    result = scan(tmp_path)
    assert [e.name for e in result.entries] == ["정상.txt"]
    assert result.skipped == []            # 링크는 건너뛴 게 아니라 아예 대상이 아니다


def test_unreadable_entry_is_reported_not_dropped(tmp_path):
    """읽을 수 없는 항목도 반드시 entries 나 skipped 중 하나에는 들어가야 한다."""
    import os
    touch(tmp_path / "정상.txt")
    os.symlink(tmp_path / "없는대상.txt", tmp_path / "깨진링크.txt")
    result = scan(tmp_path)
    assert [e.name for e in result.entries] == ["정상.txt"]
    assert [p.name for p, _ in result.skipped] == ["깨진링크.txt"]
    assert "읽을 수 없다" in result.skipped[0][1]


def test_file_entry_ext_is_lowercase_with_dot(tmp_path):
    p = touch(tmp_path / "사진.PNG")
    e = FileEntry(path=p, size=1, mtime=0.0)
    assert e.ext == ".png"
    assert e.name == "사진.PNG"
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_scanner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'organize.core.scanner'`

- [ ] **Step 3: 최소 구현을 쓴다**

`organize/core/scanner.py`:

```python
"""폴더를 읽어 FileEntry 목록을 만든다.

세 종류를 규칙보다 먼저 걸러낸다.

1. 시스템 파일    옮기면 폴더 아이콘·이름 설정이 깨진다
2. 받는 중인 파일  옮기면 다운로드가 깨진다
3. 온라인 전용    열면 클라우드 다운로드가 시작된다. 그래서 읽지도 않는다
"""

import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

_SYSTEM_NAMES = {"desktop.ini", "thumbs.db", ".ds_store", "ehthumbs.db"}
_IN_PROGRESS_EXT = {".crdownload", ".part", ".partial", ".tmp", ".download"}
_SETTLE_SECONDS = 60          # 이보다 최근에 바뀐 파일은 아직 작업 중으로 본다
_ALWAYS_EXCLUDE_DIRS = {".organize"}


@dataclass(frozen=True)
class FileEntry:
    path: Path
    size: int
    mtime: float

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def ext(self) -> str:
        return self.path.suffix.lower()


@dataclass
class ScanResult:
    entries: list[FileEntry] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)


def is_system_file(name: str) -> bool:
    return name.lower() in _SYSTEM_NAMES or name.startswith("~$")


def is_in_progress(name: str, mtime: float, now: float) -> bool:
    if Path(name).suffix.lower() in _IN_PROGRESS_EXT:
        return True
    return (now - mtime) < _SETTLE_SECONDS


_INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
_CLOUD_MASK = (0x00001000      # FILE_ATTRIBUTE_OFFLINE
               | 0x00040000    # FILE_ATTRIBUTE_RECALL_ON_OPEN
               | 0x00400000)   # FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS


def _is_cloud_attrs(attrs: int) -> bool:
    """속성 비트만 보고 판정한다. Windows 없이도 테스트할 수 있게 분리했다.

    음수도 실패로 본다. ctypes 의 기본 반환형이 부호 있는 c_int 라서,
    restype 을 지정하지 않으면 실패값 0xFFFFFFFF 가 -1 로 들어온다.
    그러면 `attrs == 0xFFFFFFFF` 가 영원히 False 이고 `-1 & mask` 는 항상 참이라
    **읽지 못한 모든 파일이 클라우드 전용으로 오분류된다.**
    아래 GetFileAttributesW 호출은 restype 을 명시하지만, 여기서도 한 번 더 막는다.
    """
    if attrs < 0 or attrs == _INVALID_FILE_ATTRIBUTES:
        return False
    return bool(attrs & _CLOUD_MASK)


def is_cloud_only(path: Path) -> bool:
    """디스크에 실제 내용이 없는 파일인지. Windows 밖에서는 항상 False."""
    if sys.platform != "win32":
        return False
    import ctypes

    get_attrs = ctypes.windll.kernel32.GetFileAttributesW
    get_attrs.restype = ctypes.c_uint32          # 기본값(c_int)이면 실패값이 -1 로 온다
    get_attrs.argtypes = [ctypes.c_wchar_p]

    try:
        return _is_cloud_attrs(get_attrs(str(path)))
    except OSError:
        return False


def scan(
    root: Path,
    *,
    recursive: bool = False,
    now: float | None = None,
    exclude_dirs: frozenset[str] = frozenset(),
) -> ScanResult:
    now = time.time() if now is None else now
    skip_dirs = _ALWAYS_EXCLUDE_DIRS | set(exclude_dirs)
    result = ScanResult()

    if not root.is_dir():
        return result

    paths: list[Path] = []
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in skip_dirs)
            for fn in filenames:
                paths.append(Path(dirpath) / fn)
    else:
        # Path.is_file() 은 OSError 를 삼켜 False 를 돌려준다. 그러면 깨진 심볼릭 링크나
        # 권한 없는 항목이 entries 에도 skipped 에도 안 들어가 조용히 사라진다.
        # 미리보기가 진실이려면 모든 항목이 둘 중 하나에는 있어야 한다.
        # scandir 은 디렉터리 판정에 이미 읽어둔 정보를 쓰므로 추가 stat 도 하지 않는다.
        try:
            with os.scandir(root) as it:
                for e in it:
                    try:
                        # 기본값(follow_symlinks=True)을 쓴다. False 로 두면 폴더를
                        # 가리키는 심볼릭 링크가 파일로 새어나가고, 그 폴더의 크기와
                        # 수정시각을 가진 FileEntry 가 만들어진다.
                        # 깨진 링크는 기본값에서도 예외 없이 False 를 돌려주므로
                        # 아래 stat 에서 사유가 남는다.
                        if e.is_dir():
                            continue
                    except OSError:
                        pass          # 판정 못 하면 파일로 보고 아래에서 사유를 남긴다
                    paths.append(Path(e.path))
        except OSError:
            return result

    for path in sorted(paths):                      # 항상 같은 순서 = 결정적
        name = path.name
        if is_system_file(name):
            result.skipped.append((path, "시스템 파일 · 옮기면 폴더 설정이 깨진다"))
            continue
        if is_cloud_only(path):
            result.skipped.append((path, "OneDrive 에만 있음 · 내려받아야 처리할 수 있다"))
            continue
        try:
            st = path.stat()
        except OSError:
            result.skipped.append((path, "파일 정보를 읽을 수 없다"))
            continue
        if is_in_progress(name, st.st_mtime, now):
            result.skipped.append((path, "받는 중이거나 방금 바뀐 파일"))
            continue
        result.entries.append(FileEntry(path=path, size=st.st_size, mtime=st.st_mtime))

    return result
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_scanner.py -v`
Expected: PASS 15개

- [ ] **Step 5: 커밋**

```bash
git add organize/core/scanner.py tests/test_scanner.py
git commit -m "스캐너 추가 — 시스템·작업중·온라인전용 파일 제외"
```

---

### Task 6: 날짜 추출 — 파일명 정규식의 오탐을 없앤다

기존 `sort.py` 의 `(19|20)\d{2}` 는 `screenshot_1920x1080.png` 를 **1920년** 폴더로 보낸다.
실제 다운로드 폴더의 유튜브 캡처 파일명에 해상도가 들어 있어서 한 끗 차이였다.

**Files:**
- Create: `organize/core/dates.py`
- Test: `tests/test_dates.py`

**Interfaces:**
- Consumes: `organize.core.scanner.FileEntry`
- Produces:
  - `organize.core.dates.DateHit` — frozen dataclass. `source: str`, `value: datetime.date`
  - `organize.core.dates.date_from_name(name: str, today: date) -> date | None`
  - `organize.core.dates.date_from_exif(path: Path) -> date | None` — Pillow 없으면 항상 `None`
  - `organize.core.dates.resolve_date(entry: FileEntry, today: date) -> DateHit | None`
  - `organize.core.dates.HAS_PILLOW: bool`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_dates.py`:

```python
from datetime import date
from pathlib import Path

import pytest

from organize.core import dates
from organize.core.dates import date_from_name, resolve_date
from organize.core.scanner import FileEntry

TODAY = date(2026, 8, 21)


@pytest.mark.parametrize("name,expected", [
    ("IMG_20231215.jpg",            date(2023, 12, 15)),
    ("20231215_120000.jpg",         date(2023, 12, 15)),
    ("2023-12-15 회의록.md",         date(2023, 12, 15)),
    ("2023_12_15.png",              date(2023, 12, 15)),
    ("2023.12.15 자료.pdf",          date(2023, 12, 15)),
    ("2026-06-02 17 47 38.png",     date(2026, 6, 2)),
    ("2023년12월15일.hwp",           date(2023, 12, 15)),
    ("sitewalk_20260818.md",        date(2026, 8, 18)),
])
def test_recognised_date_patterns(name, expected):
    assert date_from_name(name, TODAY) == expected


@pytest.mark.parametrize("name", [
    "screenshot_1920x1080.png",     # 해상도 — 기존 정규식이 1920년으로 오인하던 것
    "capture_1248x702.png",
    "영상 [ID - 1383x778 - 1m29s].png",
    "보고서_v2019_최종.docx",         # 연도만 있고 월일이 없다
    "20231340.jpg",                 # 13월 40일 — 유효하지 않다
    "20230000.jpg",
    "1h00m38s.png",
    "회의록.md",
])
def test_rejected_patterns(name):
    assert date_from_name(name, TODAY) is None


def test_dates_outside_the_allowed_range_are_rejected():
    assert date_from_name("19891231.jpg", TODAY) is None     # 1990 이전
    assert date_from_name("20991231.jpg", TODAY) is None     # 오늘+1일 이후


def test_tomorrow_is_allowed_for_timezone_slack():
    assert date_from_name("20260822.jpg", TODAY) == date(2026, 8, 22)


def test_resolve_prefers_exif_over_name(monkeypatch, tmp_path):
    p = tmp_path / "20231215.jpg"
    p.write_bytes(b"x")
    monkeypatch.setattr(dates, "date_from_exif", lambda path: date(2020, 1, 1))
    hit = resolve_date(FileEntry(path=p, size=1, mtime=0.0), TODAY)
    assert hit.value == date(2020, 1, 1)
    assert hit.source == "EXIF 촬영일"


def test_resolve_falls_back_to_name(monkeypatch, tmp_path):
    p = tmp_path / "20231215.jpg"
    p.write_bytes(b"x")
    monkeypatch.setattr(dates, "date_from_exif", lambda path: None)
    hit = resolve_date(FileEntry(path=p, size=1, mtime=0.0), TODAY)
    assert hit.value == date(2023, 12, 15)
    assert hit.source == "파일명 날짜"


def test_resolve_falls_back_to_mtime(monkeypatch, tmp_path):
    import datetime
    p = tmp_path / "회의록.md"
    p.write_bytes(b"x")
    monkeypatch.setattr(dates, "date_from_exif", lambda path: None)
    stamp = datetime.datetime(2024, 3, 9, 12, 0).timestamp()
    hit = resolve_date(FileEntry(path=p, size=1, mtime=stamp), TODAY)
    assert hit.value == date(2024, 3, 9)
    assert hit.source == "수정시각"


def _jpeg_with_exif(path, *, original=None, ifd0=None):
    """진짜 EXIF 를 가진 JPEG 를 만든다. 왕복 동작을 실측으로 확인했다."""
    from PIL import ExifTags, Image
    img = Image.new("RGB", (4, 4), (255, 0, 0))
    exif = img.getexif()
    if ifd0:
        exif[306] = ifd0
    if original:
        exif.get_ifd(ExifTags.IFD.Exif)[36867] = original
    img.save(path, exif=exif)
    return path


@pytest.mark.skipif(not dates.HAS_PILLOW, reason="Pillow 없이는 EXIF 를 만들 수 없다")
def test_capture_date_is_read_from_the_exif_subifd(tmp_path):
    """촬영일은 SubIFD 에만 있다. IFD0 의 DateTime 을 대신 읽으면 안 된다."""
    p = _jpeg_with_exif(tmp_path / "사진.jpg",
                        original="2021:07:07 12:00:00",
                        ifd0="2020:05:05 00:00:00")
    assert dates.date_from_exif(p) == date(2021, 7, 7)


@pytest.mark.skipif(not dates.HAS_PILLOW, reason="Pillow 없이는 EXIF 를 만들 수 없다")
def test_capture_date_found_even_without_ifd0_datetime(tmp_path):
    """카메라가 SubIFD 만 채우는 경우가 흔하다."""
    p = _jpeg_with_exif(tmp_path / "사진.jpg", original="2021:07:07 12:00:00")
    assert dates.date_from_exif(p) == date(2021, 7, 7)


@pytest.mark.skipif(not dates.HAS_PILLOW, reason="Pillow 없이는 EXIF 를 만들 수 없다")
def test_ifd0_datetime_is_the_last_resort(tmp_path):
    p = _jpeg_with_exif(tmp_path / "사진.jpg", ifd0="2020:05:05 00:00:00")
    assert dates.date_from_exif(p) == date(2020, 5, 5)


def test_non_image_file_returns_none(tmp_path):
    p = tmp_path / "문서.jpg"
    p.write_bytes(b"this is not an image")
    assert dates.date_from_exif(p) is None


def test_mixed_separators_are_rejected():
    assert date_from_name("2023-12_15.png", TODAY) is None


def test_exif_returns_none_without_pillow(monkeypatch, tmp_path):
    monkeypatch.setattr(dates, "HAS_PILLOW", False)
    p = tmp_path / "사진.jpg"
    p.write_bytes(b"x")
    assert dates.date_from_exif(p) is None
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_dates.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'organize.core.dates'`

- [ ] **Step 3: 최소 구현을 쓴다**

`organize/core/dates.py`:

```python
"""파일 하나에서 날짜 하나를 뽑는다.

우선순위: EXIF 촬영일 → 파일명 날짜 → 파일 수정시각.

파일명 패턴을 엄격히 한정하는 이유: 기존 스크립트의 `(19|20)\\d{2}` 는
`screenshot_1920x1080.png` 를 1920년으로 보냈다. 월·일까지 있고
유효한 날짜여야만 인정한다.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from organize.core.scanner import FileEntry

try:
    from PIL import ExifTags, Image
    HAS_PILLOW = True
except ImportError:                     # Pillow 는 선택 의존성이다
    HAS_PILLOW = False

_MIN_DATE = date(1990, 1, 1)

# YYYYMMDD / YYYY-MM-DD / YYYY_MM_DD / YYYY.MM.DD  (앞뒤가 숫자가 아닐 것)
_NUMERIC = re.compile(
    r"(?<!\d)(19\d{2}|20\d{2})([-_.])?(0[1-9]|1[0-2])([-_.])?(0[1-9]|[12]\d|3[01])(?!\d)"
)
# 2023년12월15일
_KOREAN = re.compile(r"(19\d{2}|20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")


def _in_range(d: date, today: date) -> bool:
    return _MIN_DATE <= d <= today + timedelta(days=1)


def date_from_name(name: str, today: date) -> date | None:
    m = _NUMERIC.search(name)
    if m:
        # 구분자를 썼다면 앞뒤가 같아야 한다 (2023-12_15 같은 혼용을 막는다)
        if m.group(2) == m.group(4):
            try:
                d = date(int(m.group(1)), int(m.group(3)), int(m.group(5)))
            except ValueError:
                d = None
            if d and _in_range(d, today):
                return d

    m = _KOREAN.search(name)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
        if _in_range(d, today):
            return d
    return None


# EXIF 태그 번호. 이름 역매핑을 매번 만들지 않으려고 상수로 둔다.
_EXIF_DATETIME_ORIGINAL = 36867     # 촬영 시각 — Exif SubIFD 에 있다
_EXIF_DATETIME_DIGITIZED = 36868    # 디지털화 시각 — Exif SubIFD 에 있다
_EXIF_DATETIME = 306                # 파일 변경 시각 — IFD0 에 있다


def date_from_exif(path: Path) -> date | None:
    """촬영일을 읽는다. 없으면 None.

    촬영일(DateTimeOriginal)은 IFD0 가 아니라 **Exif SubIFD** 에 들어 있다.
    `getexif()` 만 보면 그 값에 절대 닿지 못하고, IFD0 의 DateTime(파일이 마지막으로
    바뀐 시각)을 촬영일이라고 잘못 보고하게 된다. 실제 갤럭시 사진으로 확인했다 —
    DateTimeOriginal 은 SubIFD 에만 있었다.
    """
    if not HAS_PILLOW:
        return None
    try:
        with Image.open(path) as img:           # 곧 이 파일을 옮기므로 확실히 닫는다
            exif = img.getexif()
            if not exif:
                return None
            sub = exif.get_ifd(ExifTags.IFD.Exif)
            raw = (sub.get(_EXIF_DATETIME_ORIGINAL)
                   or sub.get(_EXIF_DATETIME_DIGITIZED)
                   or exif.get(_EXIF_DATETIME))
    except Exception:                   # 이미지가 아니거나 깨졌으면 조용히 넘어간다
        return None
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw)[:10], "%Y:%m:%d").date()
    except ValueError:
        return None


@dataclass(frozen=True)
class DateHit:
    source: str
    value: date


def resolve_date(entry: FileEntry, today: date) -> DateHit | None:
    found = date_from_exif(entry.path)
    if found:
        return DateHit("EXIF 촬영일", found)

    found = date_from_name(entry.name, today)
    if found:
        return DateHit("파일명 날짜", found)

    if entry.mtime is not None:      # 0.0 도 유효한 시각(1970-01-01)이다
        return DateHit("수정시각", datetime.fromtimestamp(entry.mtime).date())

    return None
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_dates.py -v`
Expected: PASS 27개 (parametrize 포함)

- [ ] **Step 5: 커밋**

```bash
git add organize/core/dates.py tests/test_dates.py
git commit -m "날짜 추출 추가 — 파일명 정규식 오탐 제거"
```

---

### Task 7: 중복 판정 — 해시를 3단계로 걸러 계산한다

실측: 파일 273개 중 크기가 겹치는 46개만 해시를 계산했다. 227개는 파일을 열지도 않았다.

**Files:**
- Create: `organize/core/hashing.py`
- Test: `tests/test_hashing.py`

**Interfaces:**
- Consumes: `organize.core.scanner.FileEntry`
- Produces:
  - `organize.core.hashing.has_copy_marker(name: str) -> bool`
  - `organize.core.hashing.find_duplicate_groups(entries: list[FileEntry]) -> list[list[FileEntry]]` — 각 그룹은 `pick_original` 기준으로 정렬되어 있고 첫 항목이 남길 원본
  - `organize.core.hashing.pick_original(group: list[FileEntry]) -> FileEntry`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_hashing.py`:

```python
import os
import time
from pathlib import Path

from organize.core.hashing import find_duplicate_groups, has_copy_marker, pick_original
from organize.core.scanner import FileEntry


def entry(path: Path, mtime: float | None = None) -> FileEntry:
    st = path.stat()
    return FileEntry(path=path, size=st.st_size, mtime=mtime if mtime is not None else st.st_mtime)


def write(p: Path, data: bytes, mtime: float | None = None) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def test_camera_and_screenshot_names_are_not_copies():
    """실제 폴더에서 나온 이름들. 일련번호·날짜를 복사본으로 오해하면 안 된다."""
    assert not has_copy_marker("IMG_1234.jpg")
    assert not has_copy_marker("DSC_5678.JPG")
    assert not has_copy_marker("PXL_20260615_143022.jpg")
    assert not has_copy_marker("20260820_085659.jpg")
    assert not has_copy_marker("sitewalk_20260818.md")


def test_copy_markers():
    assert has_copy_marker("가이드 (1).pdf")
    assert has_copy_marker("가이드 (12).pdf")
    assert has_copy_marker("가이드_1.pdf")
    assert has_copy_marker("가이드 - 복사본.pdf")
    assert has_copy_marker("guide - Copy.pdf")
    assert has_copy_marker("guide_copy.pdf")
    assert not has_copy_marker("가이드.pdf")
    assert not has_copy_marker("2026-06-02 17 47 38.png")


def test_files_of_different_size_are_never_hashed(tmp_path):
    a = write(tmp_path / "a.txt", b"1234")
    b = write(tmp_path / "b.txt", b"12345")
    assert find_duplicate_groups([entry(a), entry(b)]) == []


def test_same_size_different_content_is_not_a_duplicate(tmp_path):
    a = write(tmp_path / "a.txt", b"1234")
    b = write(tmp_path / "b.txt", b"5678")
    assert find_duplicate_groups([entry(a), entry(b)]) == []


def test_identical_content_with_different_names_is_a_duplicate(tmp_path):
    """실제 PicPick 폴더에서 나온 형태 — 이름이 전혀 다른데 내용이 같다."""
    a = write(tmp_path / "2026-06-05 09 59 20.png", b"SAME-CONTENT", mtime=1000.0)
    b = write(tmp_path / "2026-06-06 00 33 58.png", b"SAME-CONTENT", mtime=2000.0)
    groups = find_duplicate_groups([entry(a, 1000.0), entry(b, 2000.0)])
    assert len(groups) == 1
    assert groups[0][0].name == "2026-06-05 09 59 20.png"     # 오래된 쪽을 남긴다


def test_large_files_needing_full_hash(tmp_path):
    head = b"H" * 9000
    a = write(tmp_path / "a.bin", head + b"A")
    b = write(tmp_path / "b.bin", head + b"B")     # 앞 8KB 는 같고 뒤가 다르다
    c = write(tmp_path / "c.bin", head + b"A")
    groups = find_duplicate_groups([entry(a), entry(b), entry(c)])
    assert len(groups) == 1
    assert sorted(e.name for e in groups[0]) == ["a.bin", "c.bin"]


def test_original_prefers_name_without_copy_marker(tmp_path):
    a = write(tmp_path / "가이드 (1).pdf", b"SAME", mtime=1000.0)
    b = write(tmp_path / "가이드.pdf", b"SAME", mtime=2000.0)
    assert pick_original([entry(a, 1000.0), entry(b, 2000.0)]).name == "가이드.pdf"


def test_original_prefers_shallower_path(tmp_path):
    a = write(tmp_path / "깊이" / "자료.pdf", b"SAME", mtime=1000.0)
    b = write(tmp_path / "자료.pdf", b"SAME", mtime=2000.0)
    assert pick_original([entry(a, 1000.0), entry(b, 2000.0)]).path == b


def test_original_prefers_older_when_tied(tmp_path):
    a = write(tmp_path / "가.pdf", b"SAME", mtime=2000.0)
    b = write(tmp_path / "나.pdf", b"SAME", mtime=1000.0)
    assert pick_original([entry(a, 2000.0), entry(b, 1000.0)]).name == "나.pdf"


def test_result_is_deterministic_regardless_of_input_order(tmp_path):
    a = write(tmp_path / "가.pdf", b"SAME", mtime=1000.0)
    b = write(tmp_path / "나.pdf", b"SAME", mtime=1000.0)
    forward = find_duplicate_groups([entry(a, 1000.0), entry(b, 1000.0)])
    backward = find_duplicate_groups([entry(b, 1000.0), entry(a, 1000.0)])
    assert [e.name for e in forward[0]] == [e.name for e in backward[0]]


def test_unreadable_file_is_skipped_not_crashed(tmp_path):
    a = write(tmp_path / "a.txt", b"1234")
    ghost = FileEntry(path=tmp_path / "없는파일.txt", size=4, mtime=0.0)
    assert find_duplicate_groups([entry(a), ghost]) == []
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_hashing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'organize.core.hashing'`

- [ ] **Step 3: 최소 구현을 쓴다**

`organize/core/hashing.py`:

```python
"""내용이 같은 파일을 찾는다.

이름으로 판정하지 않는다. 실제 폴더에서 확인한 결과, 중복인 파일들은
`(1)`, `(2)` 가 붙은 것들이 아니라 이름이 전혀 다른 파일들이었다
(같은 화면을 다른 날 다시 캡처한 것). 반대로 `(2)`, `(3)` 파일들은
서로 다른 이미지였다. 내용 해시가 유일하게 옳은 방법이다.

계산은 3단계로 줄인다. 크기가 다르면 내용이 같을 수 없다.
"""

import hashlib
from collections import defaultdict
from pathlib import Path
import re

from organize.core.scanner import FileEntry

_HEAD_BYTES = 8192
_CHUNK = 65536
# `_1`, `_2` 같은 복사본 번호만 잡는다. 자릿수를 제한하지 않으면
# `IMG_1234.jpg`, `20260820_085659.jpg`, `sitewalk_20260818.md` 처럼
# 카메라·스크린샷이 붙이는 일련번호와 날짜까지 복사본으로 오판정한다.
# 실제 폴더 276개로 측정: 제한 없으면 3건 오판정, `{1,2}` 로 좁히면 0건이고
# 의도한 복사본 표식은 그대로 잡힌다.
_COPY_MARKER = re.compile(r"\(\d+\)|_\d{1,2}(?=\.[^.]+$)|-\s*복사본|-\s*Copy|_copy",
                          re.IGNORECASE)


def has_copy_marker(name: str) -> bool:
    return _COPY_MARKER.search(name) is not None


def _digest(path: Path, limit: int | None = None) -> str | None:
    h = hashlib.md5()
    try:
        with path.open("rb") as f:
            if limit is not None:
                h.update(f.read(limit))
            else:
                while chunk := f.read(_CHUNK):
                    h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _same_bytes(a: Path, b: Path) -> bool:
    """파일을 지우는 작업이므로 마지막에 바이트로 확인한다."""
    try:
        with a.open("rb") as fa, b.open("rb") as fb:
            while True:
                ca, cb = fa.read(_CHUNK), fb.read(_CHUNK)
                if ca != cb:
                    return False
                if not ca:
                    return True
    except OSError:
        return False


def pick_original(group: list[FileEntry]) -> FileEntry:
    """남길 파일 하나를 고른다. 완전히 결정적이어야 한다."""
    return min(group, key=_rank)


def _rank(e: FileEntry) -> tuple:
    return (
        1 if has_copy_marker(e.name) else 0,   # 복사본 표식이 없는 쪽
        len(e.path.parts),                     # 상위 폴더에 있는 쪽
        e.mtime,                               # 오래된 쪽
        str(e.path),                           # 마지막은 사전순
    )


def find_duplicate_groups(entries: list[FileEntry]) -> list[list[FileEntry]]:
    by_size: dict[int, list[FileEntry]] = defaultdict(list)
    for e in entries:
        by_size[e.size].append(e)

    stage2: dict[tuple[int, str], list[FileEntry]] = defaultdict(list)
    for size, group in by_size.items():
        if len(group) < 2:
            continue                                   # 1단계: 해시 계산 없음
        for e in group:
            head = _digest(e.path, _HEAD_BYTES)        # 2단계: 앞 8KB
            if head is not None:
                stage2[(size, head)].append(e)

    result: list[list[FileEntry]] = []
    for group in stage2.values():
        if len(group) < 2:
            continue
        by_full: dict[str, list[FileEntry]] = defaultdict(list)
        for e in group:
            full = _digest(e.path)                     # 3단계: 전체
            if full is not None:
                by_full[full].append(e)
        for same in by_full.values():
            if len(same) < 2:
                continue
            same.sort(key=_rank)
            keeper = same[0]
            confirmed = [keeper] + [e for e in same[1:] if _same_bytes(keeper.path, e.path)]
            if len(confirmed) > 1:
                result.append(confirmed)

    result.sort(key=lambda g: str(g[0].path))          # 결정적 순서
    return result
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_hashing.py -v`
Expected: PASS 11개

- [ ] **Step 5: 커밋**

```bash
git add organize/core/hashing.py tests/test_hashing.py
git commit -m "3단계 중복 판정과 원본 선택 규칙 추가"
```

---

### Task 8: 프로파일과 조건 매칭 — 분류 규칙은 코드가 아니라 데이터

같은 매칭 코드를 프로파일 규칙과 step 의 `when` 필터가 함께 쓴다.

**Files:**
- Create: `organize/profiles.py`, `profiles/desktop.toml`, `profiles/photos.toml`
- Modify: `organize/core/dates.py` (`has_exif_camera` 추가)
- Test: `tests/test_profiles.py`

**Interfaces:**
- Consumes: `organize.core.scanner.FileEntry`, `organize.core.dates`
- Produces:
  - `organize.core.dates.has_exif_camera(path: Path) -> bool | None` — `None` 은 판정 불가(Pillow 없음 또는 이미지 아님)
  - `organize.profiles.Rule` — `to: str | None`, `conditions: dict`, `is_default: bool`
  - `organize.profiles.Profile` — `name: str`, `rules: list[Rule]`, `synonyms: dict[str, list[str]]`
  - `organize.profiles.load_profile(path: Path) -> Profile`
  - `organize.profiles.matches(entry: FileEntry, conditions: dict, today: date) -> bool`
  - `organize.profiles.route_target(entry: FileEntry, profile: Profile, today: date) -> str | None`
  - `organize.profiles.parse_size(text: str) -> int`, `organize.profiles.parse_age(text: str) -> timedelta`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_profiles.py`:

```python
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from organize import profiles
from organize.core.scanner import FileEntry
from organize.profiles import load_profile, matches, parse_age, parse_size, route_target

TODAY = date(2026, 8, 21)


def entry(name, size=100, days_old=1):
    stamp = datetime(2026, 8, 21).timestamp() - days_old * 86400
    return FileEntry(path=Path("/x") / name, size=size, mtime=stamp)


def test_parse_size():
    assert parse_size("100") == 100
    assert parse_size("10KB") == 10 * 1024
    assert parse_size("2MB") == 2 * 1024 ** 2
    assert parse_size("1GB") == 1024 ** 3
    assert parse_size("2M") == 2 * 1024 ** 2        # B 를 생략해도 통해야 한다
    assert parse_size("500k") == 500 * 1024
    assert parse_size("1.5MB") == int(1.5 * 1024 ** 2)


@pytest.mark.parametrize("bad", ["MB", "abc", "10XB", ""])
def test_parse_size_rejects_nonsense(bad):
    with pytest.raises(Exception):
        parse_size(bad)


def test_parse_age():
    assert parse_age("30d") == timedelta(days=30)
    assert parse_age("6m") == timedelta(days=180)
    assert parse_age("2y") == timedelta(days=730)


def test_ext_condition_is_case_insensitive():
    assert matches(entry("사진.PNG"), {"ext": [".png"]}, TODAY)
    assert not matches(entry("사진.jpg"), {"ext": [".png"]}, TODAY)


def test_name_contains():
    assert matches(entry("2026 회고.md"), {"name_contains": ["회고"]}, TODAY)
    assert not matches(entry("메모.md"), {"name_contains": ["회고"]}, TODAY)


def test_name_regex():
    assert matches(entry("IMG_0001.jpg"), {"name_regex": r"^IMG_\d+"}, TODAY)
    assert not matches(entry("사진.jpg"), {"name_regex": r"^IMG_\d+"}, TODAY)


def test_older_than():
    assert matches(entry("옛것.pdf", days_old=800), {"older_than": "2y"}, TODAY)
    assert not matches(entry("새것.pdf", days_old=10), {"older_than": "2y"}, TODAY)


def test_larger_than():
    assert matches(entry("큰것.zip", size=200 * 1024 ** 2), {"larger_than": "100MB"}, TODAY)
    assert not matches(entry("작은것.zip", size=1024), {"larger_than": "100MB"}, TODAY)


def test_conditions_are_and_ed():
    cond = {"ext": [".png"], "larger_than": "1MB"}
    assert matches(entry("큰사진.png", size=5 * 1024 ** 2), cond, TODAY)
    assert not matches(entry("작은사진.png", size=100), cond, TODAY)


def test_empty_conditions_match_everything():
    assert matches(entry("무엇이든.xyz"), {}, TODAY)


def test_has_exif_camera_condition(monkeypatch):
    monkeypatch.setattr(profiles, "has_exif_camera",
                        lambda p: p.name.startswith("카메라"))
    assert matches(entry("카메라사진.jpg"), {"has_exif_camera": True}, TODAY)
    assert matches(entry("캡처.png"), {"has_exif_camera": False}, TODAY)
    assert not matches(entry("캡처.png"), {"has_exif_camera": True}, TODAY)


def test_rule_with_exif_condition_is_skipped_when_undecidable(monkeypatch):
    """Pillow 가 없으면 이 조건이 붙은 규칙은 건너뛰고 다음 규칙으로 넘어간다."""
    monkeypatch.setattr(profiles, "has_exif_camera", lambda p: None)
    assert not matches(entry("사진.jpg"), {"has_exif_camera": True}, TODAY)


def test_load_profile_and_route(tmp_path):
    toml = tmp_path / "t.toml"
    toml.write_text(
        'name = "테스트"\n'
        '[[rules]]\n to = "01_Docs"\n ext = [".pdf", ".md"]\n'
        '[[rules]]\n to = "02_Media"\n ext = [".png"]\n'
        '[[rules]]\n to = "99_Unsorted"\n default = true\n'
        '[synonyms]\n "02_Media" = ["사진", "이미지"]\n',
        encoding="utf-8",
    )
    p = load_profile(toml)
    assert p.name == "테스트"
    assert p.synonyms["02_Media"] == ["사진", "이미지"]
    assert route_target(entry("보고서.pdf"), p, TODAY) == "01_Docs"
    assert route_target(entry("사진.png"), p, TODAY) == "02_Media"
    assert route_target(entry("무엇.xyz"), p, TODAY) == "99_Unsorted"


def test_first_matching_rule_wins(tmp_path):
    toml = tmp_path / "t.toml"
    toml.write_text(
        'name = "순서"\n'
        '[[rules]]\n to = "먼저"\n ext = [".png"]\n'
        '[[rules]]\n to = "나중"\n ext = [".png"]\n',
        encoding="utf-8",
    )
    assert route_target(entry("a.png"), load_profile(toml), TODAY) == "먼저"


def test_no_matching_rule_and_no_default_returns_none(tmp_path):
    toml = tmp_path / "t.toml"
    toml.write_text('name = "없음"\n[[rules]]\n to = "01_Docs"\n ext = [".pdf"]\n', encoding="utf-8")
    assert route_target(entry("사진.png"), load_profile(toml), TODAY) is None
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_profiles.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'organize.profiles'`

- [ ] **Step 3: 최소 구현을 쓴다**

`organize/core/dates.py` 끝에 추가:

```python
_EXIF_MAKE = 271                    # 카메라 제조사 — IFD0 에 있다
_EXIF_MODEL = 272                   # 카메라 모델 — IFD0 에 있다


def has_exif_camera(path: Path) -> bool | None:
    """카메라·휴대폰으로 찍은 사진인지. None 은 판정 불가.

    카메라 사진에는 EXIF Make/Model 이 반드시 있고 화면 캡처에는 절대 없다.
    파일명에 'screenshot' 이 없어도 정확히 갈린다.
    """
    if not HAS_PILLOW:
        return None
    try:
        with Image.open(path) as img:            # 곧 이 파일을 옮기므로 확실히 닫는다
            exif = img.getexif()
            if exif is None:
                return None
            found = bool(exif.get(_EXIF_MAKE) or exif.get(_EXIF_MODEL))
    except Exception:
        return None
    return found
```

(수정 라운드 1/5: 최초 구현은 `Image.open(path).getexif()` 를 `with` 없이 호출해
파일 핸들을 닫지 않았다 — `ResourceWarning: unclosed file` 이 재현됐다. `date_from_exif`
와 같은 관례로 맞췄다.)

`organize/profiles.py`:

```python
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
_META_KEYS = {"to", "default"}          # 조건이 아니라 규칙 자체를 기술하는 키


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
        conditions = {k: v for k, v in raw.items() if k in _CONDITION_KEYS}
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
```

(수정 라운드 1/5: 최초 구현은 두 가지를 조용히 넘어갔다.

1. 알 수 없는 조건 키(예: `extt` 오타)를 만나면 그 규칙의 `conditions` 가 `{}` 가 되고,
   빈 조건은 모든 파일에 매칭됐다 — `.png` 만 잡으려던 규칙이 `.pdf` 까지 삼켰다.
   이제 `load_profile` 이 모르는 키를 만나면 어떤 규칙의 어떤 키인지, 쓸 수 있는 키
   목록과 함께 `OrganizeError` 로 거부한다.
2. `default = true` 규칙이 맨 앞이나 중간에 있으면 뒤 규칙을 전부 가렸는데도 검증이
   없었다. 이제 default 규칙은 최대 하나이고 반드시 마지막이어야 하며, 아니면
   `OrganizeError` 로 거부한다.

또한 TOML 파싱 실패 시 `hint` 자리에 `tomllib.TOMLDecodeError` 의 영어 원문을 그대로
넣었었다. `hint` 는 "무엇을 하면 되는지" 를 말하는 자리이므로, 파서 원문은 `message` 에
"(파서 메시지: ...)" 로 덧붙이고 `hint` 는 한국어 행동 지시로 바꿨다.)

`profiles/desktop.toml`:

```toml
name = "바탕화면·다운로드 정리"

[[rules]]
to  = "01_Docs"
ext = [".pdf", ".docx", ".xlsx", ".pptx", ".hwp", ".hwpx", ".txt", ".md", ".html"]

[[rules]]
to  = "02_Media"
ext = [".jpg", ".jpeg", ".png", ".gif", ".mp4", ".mov", ".heic", ".webp", ".avi", ".mkv"]

[[rules]]
to  = "03_Design"
ext = [".psd", ".ai", ".fig", ".sketch", ".xd"]

[[rules]]
to  = "04_Apps"
ext = [".exe", ".msi", ".msix", ".appimage", ".dmg"]

[[rules]]
to  = "05_Archives"
ext = [".zip", ".7z", ".tar", ".rar", ".gz"]

[[rules]]
to  = "06_Code"
ext = [".py", ".js", ".ts", ".ipynb", ".json", ".sql", ".sh"]

[[rules]]
to      = "99_Unsorted"
default = true

[synonyms]
"01_Docs"     = ["문서", "자료", "Documents", "Docs"]
"02_Media"    = ["사진", "이미지", "그림", "영상", "Pictures", "Images", "Media", "Videos"]
"03_Design"   = ["디자인", "Design"]
"04_Apps"     = ["설치", "프로그램", "Apps", "Installers"]
"05_Archives" = ["압축", "Archive", "Zip"]
"06_Code"     = ["코드", "소스", "Code", "Source"]
```

`profiles/photos.toml`:

```toml
name = "캡처와 사진 나누기"

# EXIF 에 카메라 정보가 있으면 사진, 없으면 화면 캡처다.
# 파일명에 'screenshot' 이 없어도 정확히 갈린다.

[[rules]]
to = "사진"
has_exif_camera = true

[[rules]]
to = "캡처"
has_exif_camera = false
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_profiles.py -v`
Expected: PASS (수정 라운드 1/5 반영 후 23개 — hint, 모르는 조건 키 거부,
default 위치 검증 회귀 테스트 5개가 추가됐다)

`has_exif_camera` 자체의 True/False/None 판정과 파일 핸들 회귀 테스트는
`organize.core.dates` 소속 함수이므로 `tests/test_dates.py` 에 있다 —
그 파일의 `date_from_exif` 테스트들과 같은 관례(Pillow 로 실제 이미지를 만들어
`tmp_path` 에서 검증)를 따른다.

- [ ] **Step 5: 커밋**

```bash
git add organize/profiles.py organize/core/dates.py profiles/ tests/test_profiles.py
git commit -m "프로파일 로더와 조건 매칭 추가 — when 필터와 공용"
```

---

### Task 9: Context — 블록 사이에 상태를 넘기는 가상 파일 시스템 뷰

2번 블록은 1번 블록이 **만들어낼** 파일을 봐야 한다. 하지만 미리보기 시점에는
그 파일이 아직 없다. 그래서 실제 파일 대신 "이 블록이 끝나면 어디에 있을 것인가"를 들고 다닌다.

**Files:**
- Create: `organize/core/context.py`
- Modify: `organize/core/scanner.py` (`FileEntry` 에 `virtual: bool = False` 추가)
- Test: `tests/test_context.py`

**Interfaces:**
- Consumes: `organize.core.action.Action`, `organize.core.action.Plan`, `organize.core.scanner.FileEntry`
- Produces:
  - `organize.core.scanner.FileEntry.virtual: bool` — 앞 블록이 만들 예정이라 디스크에 아직 없는 파일
  - `organize.core.context.Context` —
    - `__init__(self, root: Path, entries: list[FileEntry], today: date)`
    - `root: Path`, `today: date`
    - `files_at(rel: str) -> list[FileEntry]` — `rel=""` 는 root 직속
    - `all_files() -> list[FileEntry]` — 치워지지 않은 전부 (하위 포함)
    - `rel_of(entry: FileEntry) -> str`
    - `current_path(entry: FileEntry) -> Path`
    - `apply(plan: Plan) -> None`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_context.py`:

```python
from datetime import date
from pathlib import Path

from organize.core.action import Action, Plan
from organize.core.context import Context
from organize.core.scanner import FileEntry

TODAY = date(2026, 8, 21)
ROOT = Path("/작업")


def e(rel_path, size=10):
    return FileEntry(path=ROOT / rel_path, size=size, mtime=0.0)


def ctx(*entries):
    return Context(root=ROOT, entries=list(entries), today=TODAY)


def move(entry, dst_rel, block="route", src=None):
    # 실제 블록은 언제나 ctx.current_path(entry) 를 넘긴다. 이미 한 번 옮겨진 파일에
    # 원래 경로를 넘기면 Context 가 못 찾아 이동이 무시된다 — 그게 정상 동작이다.
    # 두 번째 이동을 시험하는 테스트는 반드시 src= 를 명시해야 한다.
    return Action(kind="move", src=src or entry.path, dst=ROOT / dst_rel,
                  reason="테스트", block=block)


def test_files_at_root_are_direct_children_only():
    c = ctx(e("a.png"), e("하위/b.png"))
    assert [x.name for x in c.files_at("")] == ["a.png"]


def test_files_at_subfolder():
    c = ctx(e("a.png"), e("하위/b.png"))
    assert [x.name for x in c.files_at("하위")] == ["b.png"]


def test_apply_move_changes_where_the_file_is():
    a = e("a.png")
    c = ctx(a)
    plan = Plan(actions=[move(a, "02_Media/a.png")])
    c.apply(plan)
    assert c.files_at("") == []
    assert [x.name for x in c.files_at("02_Media")] == ["a.png"]
    assert c.rel_of(a) == "02_Media"
    assert c.current_path(a) == ROOT / "02_Media" / "a.png"


def test_two_moves_in_a_row_chain():
    a = e("a.png")
    c = ctx(a)
    c.apply(Plan(actions=[move(a, "02_Media/a.png")]))
    c.apply(Plan(actions=[move(a, "02_Media/캡처/a.png", block="route2",
                              src=c.current_path(a))]))
    assert c.rel_of(a) == "02_Media/캡처"
    assert c.current_path(a) == ROOT / "02_Media" / "캡처" / "a.png"


def test_quarantined_file_disappears_from_the_view():
    a = e("a.png")
    c = ctx(a)
    c.apply(Plan(actions=[Action(kind="quarantine", src=a.path,
                                 dst=ROOT / ".organize/trash/x/a.png",
                                 reason="중복", block="dedup")]))
    assert c.files_at("") == []
    assert c.all_files() == []


def test_extract_adds_a_virtual_file():
    c = ctx(e("묶음.zip"))
    c.apply(Plan(actions=[Action(kind="extract", src=ROOT / "묶음.zip",
                                 dst=ROOT / "사진.png", reason="압축 해제", block="unzip")]))
    names = [x.name for x in c.files_at("")]
    assert "사진.png" in names
    assert next(x for x in c.files_at("") if x.name == "사진.png").virtual is True


def test_mkdir_does_not_change_the_file_view():
    a = e("a.png")
    c = ctx(a)
    c.apply(Plan(actions=[Action(kind="mkdir", src=None, dst=ROOT / "02_Media",
                                 reason="폴더", block="route")]))
    assert [x.name for x in c.files_at("")] == ["a.png"]


def test_files_are_returned_in_a_stable_order():
    c = ctx(e("나.png"), e("가.png"), e("다.png"))
    assert [x.name for x in c.files_at("")] == ["가.png", "나.png", "다.png"]
```

`tests/test_context.py` 에 다음 회귀 테스트를 반드시 포함한다. **이게 체인 전체를 지키는 테스트다.**

```python
def test_a_file_can_be_moved_more_than_once():
    """route → by_date 처럼 블록이 이어질 때 두 번째 이동이 반영되어야 한다.

    Action.src 는 '지금 위치' 이고 내부 장부의 키는 '원래 위치' 다.
    둘을 잇는 표가 없으면 두 번째 이동부터 조용히 무시된다.
    """
    entry = e("사진.png")
    c = ctx(entry)

    c.apply(Plan(actions=[Action("move", ROOT / "사진.png",
                                 ROOT / "02_Media" / "사진.png", "route", "route")]))
    assert c.rel_of(entry) == "02_Media"

    c.apply(Plan(actions=[Action("move", ROOT / "02_Media" / "사진.png",
                                 ROOT / "02_Media" / "2026" / "사진.png", "by_date", "by_date")]))
    assert c.rel_of(entry) == "02_Media/2026"
    assert c.current_path(entry) == ROOT / "02_Media" / "2026" / "사진.png"
    assert c.files_at("02_Media/2026") == [entry]
    assert c.files_at("02_Media") == []


def test_move_that_renames_is_tracked():
    """이름 충돌로 _(1) 이 붙어도 그 파일을 계속 따라가야 한다."""
    entry = e("a.png")
    c = ctx(entry)
    c.apply(Plan(actions=[Action("move", ROOT / "a.png",
                                 ROOT / "02_Media" / "a_(1).png", "충돌", "route")]))
    assert c.current_path(entry) == ROOT / "02_Media" / "a_(1).png"


def test_quarantine_after_a_move_removes_the_file():
    entry = e("b.png")
    c = ctx(entry)
    c.apply(Plan(actions=[Action("move", ROOT / "b.png",
                                 ROOT / "02_Media" / "b.png", "route", "route")]))
    c.apply(Plan(actions=[Action("quarantine", ROOT / "02_Media" / "b.png",
                                 ROOT / ".organize" / "trash" / "b.png", "중복", "dedup")]))
    assert c.all_files() == []


def test_extracted_virtual_file_can_then_be_routed():
    c = ctx()
    c.apply(Plan(actions=[Action("extract", ROOT / "자료.zip",
                                 ROOT / "문서.pdf", "압축 해제", "unzip")]))
    virtual = c.files_at("")[0]
    assert virtual.virtual is True
    c.apply(Plan(actions=[Action("move", ROOT / "문서.pdf",
                                 ROOT / "01_Docs" / "문서.pdf", "route", "route")]))
    assert c.rel_of(virtual) == "01_Docs"
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_context.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'organize.core.context'`

- [ ] **Step 3: 최소 구현을 쓴다**

`organize/core/scanner.py` 의 `FileEntry` 를 수정한다:

```python
@dataclass(frozen=True)
class FileEntry:
    path: Path
    size: int
    mtime: float
    virtual: bool = False      # 앞 블록이 만들 예정이라 디스크에 아직 없다
```

`organize/core/context.py`:

```python
"""블록 사이에 상태를 넘기는 가상 파일 시스템 뷰.

블록은 파일을 만지지 않으므로, 2번 블록이 1번 블록의 결과를 보려면
"이 블록이 끝나면 어디에 있을 것인가"를 따로 들고 있어야 한다.
Context 가 그 장부다. 키는 항상 **원래 경로** 이므로 여러 번 옮겨도 추적된다.

블록은 Action 의 `src` 에 반드시 `ctx.current_path(entry)` 를 넣어야 한다.
이미 옮겨진 파일에 옛 경로를 넘기면 `_by_current` 에서 찾지 못해 그 이동이 장부에
반영되지 않는다. 그러면 다음 블록이 파일을 엉뚱한 곳에서 찾아 0건이 된다.
(미리보기와 실행이 어긋나지는 않는다 — 실행기는 Context 가 아니라 Plan 을 그대로 쓴다.)
"""

from datetime import date
from pathlib import Path

from organize.core.action import Plan
from organize.core.scanner import FileEntry


class Context:
    def __init__(self, root: Path, entries: list[FileEntry], today: date) -> None:
        self.root = root
        self.today = today
        self._entries: list[FileEntry] = list(entries)
        self._rel: dict[Path, str] = {}
        self._name: dict[Path, str] = {}
        self._gone: set[Path] = set()
        # 현재 경로 -> 원래 경로. 블록이 넘겨주는 Action.src 는 '지금 위치' 이므로
        # 이 표가 없으면 두 번째 이동부터 추적이 끊긴다.
        self._by_current: dict[Path, Path] = {}
        for e in entries:
            self._rel[e.path] = self._relative_folder(e.path)
            self._name[e.path] = e.path.name
            self._by_current[e.path] = e.path

    def _relative_folder(self, path: Path) -> str:
        try:
            rel = path.parent.relative_to(self.root)
        except ValueError:
            return ""
        return "" if str(rel) == "." else rel.as_posix()

    def rel_of(self, entry: FileEntry) -> str:
        return self._rel.get(entry.path, self._relative_folder(entry.path))

    def current_path(self, entry: FileEntry) -> Path:
        rel = self.rel_of(entry)
        name = self._name.get(entry.path, entry.path.name)
        return (self.root / rel / name) if rel else (self.root / name)

    def all_files(self) -> list[FileEntry]:
        alive = [e for e in self._entries if e.path not in self._gone]
        return sorted(alive, key=lambda e: (self.rel_of(e), e.path.name))

    def files_at(self, rel: str) -> list[FileEntry]:
        return [e for e in self.all_files() if self.rel_of(e) == rel]

    def apply(self, plan: Plan) -> None:
        for a in plan.actions:
            if a.kind == "mkdir":
                continue
            origin = self._by_current.get(a.src) if a.src is not None else None

            if a.kind == "quarantine" and origin is not None:
                self._gone.add(origin)
                self._by_current.pop(a.src, None)

            elif a.kind == "move" and origin is not None and a.dst is not None:
                self._by_current.pop(a.src, None)
                self._rel[origin] = self._relative_folder(a.dst)
                self._name[origin] = a.dst.name
                self._by_current[a.dst] = origin

            elif a.kind == "extract" and a.dst is not None:
                new = FileEntry(path=a.dst, size=0, mtime=0.0, virtual=True)
                self._entries.append(new)
                self._rel[new.path] = self._relative_folder(a.dst)
                self._name[new.path] = a.dst.name
                self._by_current[a.dst] = new.path
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_context.py -v`
Expected: PASS 8개

전체 회귀도 확인한다:
Run: `python -m pytest -q`
Expected: 지금까지의 테스트가 전부 통과 (`FileEntry` 필드 추가가 기존 테스트를 깨지 않아야 한다)

- [ ] **Step 5: 커밋**

```bash
git add organize/core/context.py organize/core/scanner.py tests/test_context.py
git commit -m "블록 사이 상태를 넘기는 Context 추가"
```

---

### Task 10: 블록 레지스트리와 route 블록

**Files:**
- Create: `organize/blocks/__init__.py`, `organize/blocks/route.py`
- Test: `tests/test_block_route.py`

**Interfaces:**
- Consumes: `organize.core.context.Context`, `organize.core.action.Action/Plan`, `organize.profiles`
- Produces:
  - `organize.blocks.BlockConfig` — frozen dataclass. `target: str = ""`, `dest: str | None = None`, `when: dict = {}`, `options: dict = {}`. 프로퍼티 `out -> str` (`dest` 가 `None` 이면 `target`)
  - `organize.blocks.BlockFn = Callable[[Context, BlockConfig], Plan]`
  - `organize.blocks.REGISTRY: dict[str, BlockFn]`
  - `organize.blocks.get_block(name: str) -> BlockFn` — 없으면 `OrganizeError`
  - `organize.blocks.route.build(ctx: Context, cfg: BlockConfig) -> Plan` — `cfg.options["profile"]` 에 `Profile` 객체가 들어온다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_block_route.py`:

```python
from datetime import date
from pathlib import Path

import pytest

from organize.blocks import BlockConfig, get_block
from organize.blocks.route import build
from organize.core.context import Context
from organize.core.scanner import FileEntry
from organize.errors import OrganizeError
from organize.profiles import Profile, Rule

TODAY = date(2026, 8, 21)
ROOT = Path("/작업")

PROFILE = Profile(name="테스트", rules=[
    Rule(to="01_Docs", conditions={"ext": [".pdf", ".md"]}),
    Rule(to="02_Media", conditions={"ext": [".png", ".jpg"]}),
    Rule(to="99_Unsorted", conditions={}, is_default=True),
])


def e(rel, size=10):
    return FileEntry(path=ROOT / rel, size=size, mtime=0.0)


def ctx(*entries):
    return Context(root=ROOT, entries=list(entries), today=TODAY)


def cfg(**kw):
    kw.setdefault("options", {"profile": PROFILE})
    return BlockConfig(**kw)


def test_registry_has_route():
    assert get_block("route") is not None


def test_unknown_block_is_a_friendly_error():
    with pytest.raises(OrganizeError) as ex:
        get_block("없는블록")
    assert "없는블록" in ex.value.message


def test_files_go_to_their_category():
    c = ctx(e("보고서.pdf"), e("사진.png"))
    plan = build(c, cfg())
    moves = {a.src.name: a.dst.parent.name for a in plan.actions if a.kind == "move"}
    assert moves == {"보고서.pdf": "01_Docs", "사진.png": "02_Media"}


def test_unmatched_file_goes_to_default():
    c = ctx(e("무엇.xyz"))
    plan = build(c, cfg())
    assert [a.dst.parent.name for a in plan.actions if a.kind == "move"] == ["99_Unsorted"]


def test_mkdir_actions_come_before_moves_and_are_unique():
    c = ctx(e("a.pdf"), e("b.pdf"), e("c.png"))
    plan = build(c, cfg())
    kinds = [a.kind for a in plan.actions]
    assert kinds.index("mkdir") < kinds.index("move")
    mkdirs = sorted(a.dst.name for a in plan.actions if a.kind == "mkdir")
    assert mkdirs == ["01_Docs", "02_Media"]


def test_reason_explains_why():
    c = ctx(e("사진.png"))
    plan = build(c, cfg())
    move = next(a for a in plan.actions if a.kind == "move")
    assert ".png" in move.reason and "02_Media" in move.reason


def test_when_filter_limits_the_files():
    c = ctx(e("보고서.pdf"), e("사진.png"))
    plan = build(c, cfg(when={"ext": [".pdf"]}))
    assert [a.src.name for a in plan.actions if a.kind == "move"] == ["보고서.pdf"]
    assert [p.name for p, _ in plan.skipped] == ["사진.png"]


def test_only_files_at_target_are_touched():
    c = ctx(e("위.pdf"), e("하위/아래.pdf"))
    plan = build(c, cfg())
    assert [a.src.name for a in plan.actions if a.kind == "move"] == ["위.pdf"]


def test_dest_sends_results_elsewhere():
    c = ctx(e("보고서.pdf"))
    plan = build(c, cfg(dest="보관"))
    move = next(a for a in plan.actions if a.kind == "move")
    assert move.dst == ROOT / "보관" / "01_Docs" / "보고서.pdf"


def test_file_already_in_its_category_is_left_alone():
    """재실행해도 폴더가 중첩되지 않아야 한다."""
    c = ctx(e("01_Docs/보고서.pdf"))
    plan = build(c, BlockConfig(target="01_Docs", options={"profile": PROFILE}))
    assert [a for a in plan.actions if a.kind == "move"] == []


def test_dest_still_moves_a_file_that_is_already_in_that_category():
    """dest 를 콕 집어 말했으면, 같은 이름 폴더에 있더라도 그리로 옮긴다.

    '이미 제자리' 판정이 dest 를 안 보면 이 파일은 영영 안 움직인다.
    """
    c = ctx(e("01_Docs/보고서.pdf"))
    plan = build(c, cfg(target="01_Docs", dest="보관"))
    move = next(a for a in plan.actions if a.kind == "move")
    assert move.src == ROOT / "01_Docs" / "보고서.pdf"
    assert move.dst == ROOT / "보관" / "01_Docs" / "보고서.pdf"


def test_dest_leaves_a_file_that_is_already_at_the_destination():
    """반대로 이미 목적지에 도착해 있으면 건드리지 않는다."""
    c = ctx(e("보관/01_Docs/보고서.pdf"))
    plan = build(c, cfg(target="보관/01_Docs", dest="보관"))
    assert [a for a in plan.actions if a.kind == "move"] == []
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_block_route.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'organize.blocks'`

- [ ] **Step 3: 최소 구현을 쓴다**

`organize/blocks/__init__.py`:

```python
"""블록 레지스트리.

블록 하나가 파일 하나다. 모든 블록은 같은 시그니처를 갖는다.

    build(ctx: Context, cfg: BlockConfig) -> Plan

블록은 파일을 만지지 않고 Plan 만 만든다. 블록끼리 직접 호출하지 않는다.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from organize.core.action import Plan
from organize.core.context import Context
from organize.errors import OrganizeError


@dataclass(frozen=True)
class BlockConfig:
    target: str = ""                       # root 기준 상대 — 어디서 찾을지
    dest: str | None = None                # root 기준 상대 — 어디로 보낼지
    when: dict = field(default_factory=dict)
    options: dict = field(default_factory=dict)

    @property
    def out(self) -> str:
        return self.target if self.dest is None else self.dest


BlockFn = Callable[[Context, BlockConfig], Plan]


def dest_folder(ctx: Context, rel: str, *, block: str) -> Path:
    """root 기준 상대 폴더를 실제 경로로 바꾼다. **root 밖으로 나가면 거부한다.**

    `rel` 은 전부 사용자가 손으로 쓴 값에서 온다 — 레시피의 `dest`/`target`,
    프로파일의 `to`, by_date 의 `layout`, unzip 의 `out`. 입구가 넷이므로 각
    입구마다 막지 않고 **Action 을 만드는 이 한 곳**에서 막는다. 마지막 관문이다.

    막지 않으면 `/etc` 나 `../..` 가 그대로 통해서 사용자 파일이 root 밖으로
    나간다. 미리보기 화면에도 그렇게 보이므로 눈치채기 전에 실행된다.

    심볼릭 링크는 따지지 않는다 — `normpath` 는 순수 문자열 정규화다.
    링크를 통한 탈출은 실행기가 옮기기 직전에 막는다(Task 16).
    """
    folder = Path(os.path.normpath(ctx.root / rel))
    if not folder.is_relative_to(ctx.root):
        raise OrganizeError(
            f"'{block}' 작업의 목적지가 정리 대상 폴더 밖을 가리킵니다: {rel}",
            hint=f"목적지는 {ctx.root} 안쪽이어야 합니다. "
                 "'/' 로 시작하는 절대경로나 '..' 는 쓸 수 없습니다.")
    return folder


def already_there(ctx: Context, entry, rel: str, sub: str, cfg: BlockConfig) -> bool:
    """이 파일이 이미 갈 곳에 있는가. route 와 by_date 가 같이 쓴다.

    두 갈래다.
    1) 계산한 목적지와 지금 폴더가 **정확히 같다** — 두말할 것 없이 건너뛴다.
    2) `dest` 를 안 줬다(= "있던 자리 옆에 담아라")면, 지금 폴더가 이미 `sub` 로
       끝나는 것으로 충분하다. 이게 없으면 재실행할 때마다 `01_Docs/01_Docs`,
       `2023/2023` 처럼 같은 이름이 겹겹이 쌓인다.

    `dest` 를 **명시했을 때는 2)를 쓰지 않는다.** 사용자가 목적지를 콕 집어 말한
    것이므로, 이미 같은 이름 폴더에 있더라도 그리로 옮겨야 한다.
    (`01_Docs` 안의 파일을 `보관/01_Docs` 로 보내는 경우가 여기 걸린다.)

    `sub` 가 `2026/05` 처럼 여러 층일 수 있으므로 마지막 한 조각만 보면 안 된다.
    """
    rel_of = ctx.rel_of(entry)
    if rel == rel_of:
        return True
    return cfg.dest is None and (rel_of == sub or rel_of.endswith("/" + sub))


def _registry() -> dict[str, BlockFn]:
    from organize.blocks import by_date, dedup, route, unzip
    return {
        "unzip": unzip.build,
        "dedup": dedup.build,
        "route": route.build,
        "by_date": by_date.build,
    }


REGISTRY: dict[str, BlockFn] = {}


def get_block(name: str) -> BlockFn:
    if not REGISTRY:
        # 다시 대입하지 않고 제자리에서 채운다. `from organize.blocks import REGISTRY`
        # 로 먼저 참조를 잡아둔 쪽이 영원히 빈 딕셔너리를 보게 되는 걸 막는다.
        REGISTRY.update(_registry())
    if name not in REGISTRY:
        raise OrganizeError(
            f"'{name}' 이라는 작업은 없습니다.",
            hint="쓸 수 있는 작업: " + ", ".join(sorted(REGISTRY)),
        )
    return REGISTRY[name]
```

`organize/blocks/route.py`:

```python
"""규칙에 따라 파일을 카테고리 폴더로 보낸다.

바탕화면 정리와 vault 번호 체계가 같은 블록이다. 프로파일만 바뀐다.
"""

from organize.blocks import BlockConfig, already_there, dest_folder
from organize.core.action import Action, Plan
from organize.core.context import Context
from organize.profiles import matches, route_target

BLOCK = "route"


def build(ctx: Context, cfg: BlockConfig) -> Plan:
    profile = cfg.options["profile"]
    plan = Plan()
    folders: list[str] = []
    moves: list[Action] = []

    for entry in ctx.files_at(cfg.target):
        if cfg.when and not matches(entry, cfg.when, ctx.today):
            plan.skipped.append((entry.path, "이 작업의 대상이 아님"))
            continue

        category = route_target(entry, profile, ctx.today)
        if category is None:
            plan.skipped.append((entry.path, "맞는 규칙이 없음"))
            continue

        rel = f"{cfg.out}/{category}" if cfg.out else category
        if already_there(ctx, entry, rel, category, cfg):
            plan.skipped.append((entry.path, f"이미 {category} 에 있음"))
            continue

        folder = dest_folder(ctx, rel, block=BLOCK)      # root 밖이면 여기서 막힌다
        if rel not in folders:
            folders.append(rel)
        moves.append(Action(
            kind="move",
            src=ctx.current_path(entry),
            dst=folder / ctx.current_path(entry).name,
            reason=f"확장자 {entry.ext or '없음'} → {category}",
            block=BLOCK,
        ))

    for rel in folders:                       # 폴더를 먼저 만들고 옮긴다
        plan.actions.append(Action(kind="mkdir", src=None,
                                   dst=dest_folder(ctx, rel, block=BLOCK),
                                   reason="분류 결과를 담을 폴더", block=BLOCK))
    plan.actions.extend(moves)
    return plan
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_block_route.py -v`
Expected: FAIL — 아직 `by_date`, `dedup`, `unzip` 모듈이 없어 `_registry()` 가 ImportError 를 낸다.
임시로 `organize/blocks/by_date.py`, `dedup.py`, `unzip.py` 를 만들고 각각에 다음만 넣는다.
**빈 `Plan()` 을 돌려주면 안 된다** — 그러면 레시피에 `dedup` 을 넣었을 때 오류 없이
0건이 나오고, 사용자는 "정리할 게 없었나 보다" 라고 읽는다. 아직 없는 기능은 아직
없다고 말해야 한다. (`<이름>` 자리에 각 블록 이름을 넣는다.)

```python
from organize.blocks import BlockConfig
from organize.core.action import Plan
from organize.core.context import Context
from organize.errors import OrganizeError


def build(ctx: Context, cfg: BlockConfig) -> Plan:
    raise OrganizeError("'<이름>' 작업은 아직 만들어지지 않았습니다.",
                        hint="지금은 route 만 쓸 수 있습니다.")
```

그 다음 다시:
Run: `python -m pytest tests/test_block_route.py -v`
Expected: PASS 10개

- [ ] **Step 5: 커밋**

```bash
git add organize/blocks/ tests/test_block_route.py
git commit -m "블록 레지스트리와 route 블록 추가"
```

---

### Task 11: by_date 블록 — 날짜별 분류

**Files:**
- Create: `organize/blocks/by_date.py` (Task 10 에서 만든 stub 을 대체)
- Test: `tests/test_block_by_date.py`

**Interfaces:**
- Consumes: `organize.core.dates.resolve_date`, `organize.core.context.Context`, `organize.profiles.matches`
- Produces:
  - `organize.blocks.by_date.build(ctx: Context, cfg: BlockConfig) -> Plan`
  - `cfg.options["layout"]: str` — 기본값 `"{year}"`. `{year}` `{month}` `{day}` 를 쓸 수 있고 `/` 로 계층을 만든다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_block_by_date.py`:

```python
from datetime import date, datetime
from pathlib import Path

from organize.blocks import BlockConfig
from organize.blocks.by_date import build
from organize.core.context import Context
from organize.core.scanner import FileEntry

TODAY = date(2026, 8, 21)
ROOT = Path("/작업")


def e(rel, mtime_date=(2024, 3, 9)):
    stamp = datetime(*mtime_date).timestamp()
    return FileEntry(path=ROOT / rel, size=10, mtime=stamp)


def ctx(*entries):
    return Context(root=ROOT, entries=list(entries), today=TODAY)


def moves(plan):
    return {a.src.name: a.dst.parent.relative_to(ROOT).as_posix()
            for a in plan.actions if a.kind == "move"}


def test_year_layout_uses_name_date():
    plan = build(ctx(e("2023-12-15 회의록.md")), BlockConfig())
    assert moves(plan) == {"2023-12-15 회의록.md": "2023"}


def test_year_month_layout():
    plan = build(ctx(e("2023-12-15 회의록.md")), BlockConfig(options={"layout": "{year}/{month}"}))
    assert moves(plan) == {"2023-12-15 회의록.md": "2023/12"}


def test_falls_back_to_mtime_when_name_has_no_date():
    plan = build(ctx(e("회의록.md", mtime_date=(2024, 3, 9))), BlockConfig())
    assert moves(plan) == {"회의록.md": "2024"}


def test_resolution_in_filename_is_not_a_year():
    """기존 스크립트가 1920년 폴더로 보내던 파일."""
    plan = build(ctx(e("screenshot_1920x1080.png", mtime_date=(2025, 5, 5))), BlockConfig())
    assert moves(plan) == {"screenshot_1920x1080.png": "2025"}


def test_reason_says_where_the_date_came_from():
    plan = build(ctx(e("2023-12-15.md")), BlockConfig())
    move = next(a for a in plan.actions if a.kind == "move")
    assert "파일명 날짜" in move.reason and "2023-12-15" in move.reason


def test_dest_sends_year_folders_elsewhere():
    plan = build(ctx(e("2023-12-15.md")), BlockConfig(dest="보관"))
    move = next(a for a in plan.actions if a.kind == "move")
    assert move.dst == ROOT / "보관" / "2023" / "2023-12-15.md"


def test_when_filter_limits_the_files():
    plan = build(ctx(e("2023-12-15.md"), e("2023-12-15.png")),
                 BlockConfig(when={"ext": [".md"]}))
    assert list(moves(plan)) == ["2023-12-15.md"]


def test_files_already_in_their_year_folder_are_left_alone():
    """재실행해도 2026/2026 처럼 중첩되지 않아야 한다."""
    plan = build(ctx(e("2023/2023-12-15.md")), BlockConfig(target="2023"))
    assert moves(plan) == {}


def test_virtual_files_use_name_or_mtime_without_crashing():
    v = FileEntry(path=ROOT / "2023-12-15 문서.pdf", size=0, mtime=0.0, virtual=True)
    plan = build(ctx(v), BlockConfig())
    assert moves(plan) == {"2023-12-15 문서.pdf": "2023"}


def test_mkdir_precedes_moves():
    plan = build(ctx(e("2023-12-15.md")), BlockConfig())
    kinds = [a.kind for a in plan.actions]
    assert kinds.index("mkdir") < kinds.index("move")
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_block_by_date.py -v`
Expected: FAIL — stub 이 빈 `Plan()` 을 돌려주므로 `moves(plan) == {}` 로 대부분 실패

- [ ] **Step 3: 최소 구현을 쓴다**

`organize/blocks/by_date.py`:

```python
"""날짜별로 파일을 나눈다.

날짜는 EXIF 촬영일 → 파일명 → 수정시각 순으로 정한다.
판정할 수 없으면 옮기지 않고 그 자리에 둔다. 앞 단계가 이미 분류해 둔
결과를 미분류로 되돌리지 않기 위해서다.

재실행해도 `2026/2026` 처럼 중첩되지 않아야 한다. `files_at(target)` 이 직속
파일만 돌려주므로 target 이 루트일 때는 저절로 되지만, `target="2026"` 처럼
그 폴더 자체를 지정하면 대상이 **된다**. 그래서 `already_there()` 가 필요하다 —
장식이 아니다.
"""

from organize.blocks import BlockConfig, already_there, dest_folder
from organize.core.action import Action, Plan
from organize.core.context import Context
from organize.core.dates import resolve_date
from organize.errors import OrganizeError
from organize.profiles import matches

BLOCK = "by_date"
_DEFAULT_LAYOUT = "{year}"


def build(ctx: Context, cfg: BlockConfig) -> Plan:
    layout = cfg.options.get("layout", _DEFAULT_LAYOUT)
    plan = Plan()
    folders: list[str] = []
    moves: list[Action] = []

    for entry in ctx.files_at(cfg.target):
        if cfg.when and not matches(entry, cfg.when, ctx.today):
            plan.skipped.append((entry.path, "이 작업의 대상이 아님"))
            continue

        hit = resolve_date(entry, ctx.today)
        if hit is None:
            plan.skipped.append((entry.path, "날짜를 알 수 없어 그대로 둠"))
            continue

        try:
            sub = layout.format(year=f"{hit.value.year:04d}",
                                month=f"{hit.value.month:02d}",
                                day=f"{hit.value.day:02d}")
        except (KeyError, IndexError, ValueError) as e:
            # layout 은 사용자가 손으로 쓴다. '{years}' 오타 하나에
            # KeyError: 'years' 를 그대로 보여주면 안 된다.
            raise OrganizeError(
                f"날짜 폴더 모양('{layout}')을 이해하지 못했습니다.",
                hint="{year}, {month}, {day} 만 쓸 수 있습니다. "
                     "예: '{year}' 또는 '{year}/{month}'") from e
        rel = f"{cfg.out}/{sub}" if cfg.out else sub
        if already_there(ctx, entry, rel, sub, cfg):
            plan.skipped.append((entry.path, "이미 해당 폴더에 있음"))
            continue

        folder = dest_folder(ctx, rel, block=BLOCK)      # root 밖이면 여기서 막힌다
        if rel not in folders:
            folders.append(rel)
        moves.append(Action(
            kind="move",
            src=ctx.current_path(entry),
            dst=folder / ctx.current_path(entry).name,
            reason=f"{hit.source} {hit.value.isoformat()}",
            block=BLOCK,
        ))

    for rel in folders:
        plan.actions.append(Action(kind="mkdir", src=None,
                                   dst=dest_folder(ctx, rel, block=BLOCK),
                                   reason="날짜별로 담을 폴더", block=BLOCK))
    plan.actions.extend(moves)
    return plan
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_block_by_date.py -v`
Expected: PASS 10개

- [ ] **Step 5: 커밋**

```bash
git add organize/blocks/by_date.py tests/test_block_by_date.py
git commit -m "by_date 블록 추가 — EXIF·파일명·수정시각 순으로 날짜 판정"
```

---

### Task 12: dedup 블록 — 읽는 범위와 치우는 범위를 나눈다

**폴더는 건드리지 않는다**(제품 원칙). 하지만 하위 폴더를 참고하지 않으면 중복 제거가 쓸모없다.
그래서 하위 폴더는 **읽기만** 하고, 치우는 것은 **대상 폴더 직속 파일만** 한다.

**Files:**
- Create: `organize/blocks/dedup.py` (Task 10 의 stub 대체)
- Modify: `organize/core/context.py` (`run_id` 매개변수와 `trash_dir` 프로퍼티 추가)
- Test: `tests/test_block_dedup.py`

**Interfaces:**
- Consumes: `organize.core.hashing.find_duplicate_groups`
- Produces:
  - `organize.core.context.Context.__init__(self, root, entries, today, run_id: str = "")`
  - `organize.core.context.Context.trash_dir -> Path` — `root/.organize/trash/<run_id>`
  - `organize.blocks.dedup.build(ctx: Context, cfg: BlockConfig) -> Plan`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_block_dedup.py`:

```python
from datetime import date
from pathlib import Path

from organize.blocks import BlockConfig
from organize.blocks.dedup import build
from organize.core.context import Context
from organize.core.scanner import FileEntry, scan

TODAY = date(2026, 8, 21)


def ctx_for(tmp_path, run_id="20260821-120000"):
    entries = scan(tmp_path, recursive=True, now=1e12).entries
    return Context(root=tmp_path, entries=entries, today=TODAY, run_id=run_id)


def write(p: Path, data: bytes) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def quarantined(plan):
    return sorted(a.src.name for a in plan.actions if a.kind == "quarantine")


def test_no_duplicates_means_no_actions(tmp_path):
    write(tmp_path / "a.png", b"AAA")
    write(tmp_path / "b.png", b"BBB")
    assert build(ctx_for(tmp_path), BlockConfig()).actions == []


def test_duplicate_at_root_is_quarantined(tmp_path):
    write(tmp_path / "가이드.pdf", b"SAME-CONTENT")
    write(tmp_path / "가이드 (1).pdf", b"SAME-CONTENT")
    plan = build(ctx_for(tmp_path), BlockConfig())
    assert quarantined(plan) == ["가이드 (1).pdf"]     # 복사본 표식이 있는 쪽을 치운다


def test_files_inside_subfolders_are_never_touched(tmp_path):
    """하위 폴더는 참고만 한다. 거기 있는 파일은 절대 옮기지 않는다."""
    write(tmp_path / "6월" / "사진.png", b"SAME-CONTENT")
    write(tmp_path / "6월" / "사진 복사.png", b"SAME-CONTENT")
    plan = build(ctx_for(tmp_path), BlockConfig())
    assert plan.actions == []


def test_root_file_matching_a_subfolder_file_is_quarantined(tmp_path):
    """이미 정리해 둔 폴더에 같은 게 있으면, 새로 들어온 직속 파일을 치운다."""
    write(tmp_path / "6월" / "사진.png", b"SAME-CONTENT")
    write(tmp_path / "사진.png", b"SAME-CONTENT")
    plan = build(ctx_for(tmp_path), BlockConfig())
    assert quarantined(plan) == ["사진.png"]
    assert all(a.dst.parent.name == "20260821-120000" for a in plan.actions)


def test_quarantine_destination_is_the_run_trash_folder(tmp_path):
    write(tmp_path / "a.pdf", b"SAME")
    write(tmp_path / "a (1).pdf", b"SAME")
    plan = build(ctx_for(tmp_path), BlockConfig())
    a = next(x for x in plan.actions if x.kind == "quarantine")
    assert a.dst == tmp_path / ".organize" / "trash" / "20260821-120000" / "a (1).pdf"


def test_reason_names_the_file_that_was_kept(tmp_path):
    write(tmp_path / "가이드.pdf", b"SAME")
    write(tmp_path / "가이드 (1).pdf", b"SAME")
    plan = build(ctx_for(tmp_path), BlockConfig())
    a = next(x for x in plan.actions if x.kind == "quarantine")
    assert "가이드.pdf" in a.reason


def test_when_filter_limits_the_files(tmp_path):
    write(tmp_path / "a.pdf", b"SAME")
    write(tmp_path / "a (1).pdf", b"SAME")
    write(tmp_path / "b.png", b"EQUAL")
    write(tmp_path / "b (1).png", b"EQUAL")
    plan = build(ctx_for(tmp_path), BlockConfig(when={"ext": [".pdf"]}))
    assert quarantined(plan) == ["a (1).pdf"]


def test_virtual_files_are_skipped_with_a_clear_reason(tmp_path):
    entries = [FileEntry(path=tmp_path / "압축안.pdf", size=0, mtime=0.0, virtual=True)]
    c = Context(root=tmp_path, entries=entries, today=TODAY, run_id="r")
    plan = build(c, BlockConfig())
    assert plan.actions == []
    assert "압축을 푼 뒤" in plan.skipped[0][1]
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_block_dedup.py -v`
Expected: FAIL — `Context.__init__() got an unexpected keyword argument 'run_id'`

- [ ] **Step 3: 최소 구현을 쓴다**

`organize/core/context.py` 수정 — `__init__` 서명과 프로퍼티만 바꾼다:

```python
    def __init__(self, root: Path, entries: list[FileEntry], today: date,
                 run_id: str = "") -> None:
        self.root = root
        self.today = today
        self.run_id = run_id
        # ... 나머지는 그대로

    @property
    def trash_dir(self) -> Path:
        return self.root / ".organize" / "trash" / self.run_id
```

`organize/blocks/dedup.py`:

```python
"""내용이 같은 파일을 격리 폴더로 치운다.

읽는 범위와 치우는 범위가 다르다.

  읽기   대상 폴더 + 하위 폴더 전부   해시만 계산한다
  치우기 대상 폴더 직속 파일만        하위 폴더는 절대 건드리지 않는다

이름으로 판정하지 않는다. 실제 폴더에서는 이름이 전혀 다른 파일들이 중복이었고,
`(2)`, `(3)` 이 붙은 파일들은 오히려 서로 다른 이미지였다.
"""

from organize.blocks import BlockConfig
from organize.core.action import Action, Plan
from organize.core.context import Context
from organize.core.hashing import find_duplicate_groups
from organize.profiles import matches

BLOCK = "dedup"


def build(ctx: Context, cfg: BlockConfig) -> Plan:
    plan = Plan()

    readable = []
    for entry in ctx.all_files():
        if entry.virtual:
            plan.skipped.append((entry.path, "압축을 푼 뒤에 판정합니다"))
            continue
        readable.append(entry)

    removable = {e.path for e in ctx.files_at(cfg.target)}

    for group in find_duplicate_groups(readable):
        keeper = group[0]
        for other in group[1:]:
            if other.path not in removable:
                continue                       # 하위 폴더 파일은 건드리지 않는다
            if cfg.when and not matches(other, cfg.when, ctx.today):
                plan.skipped.append((other.path, "이 작업의 대상이 아님"))
                continue
            plan.actions.append(Action(
                kind="quarantine",
                src=ctx.current_path(other),
                dst=ctx.trash_dir / other.name,
                reason=f"내용이 같음 · 남긴 파일 {keeper.name}",
                block=BLOCK,
            ))
    return plan
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_block_dedup.py tests/test_context.py -v`
Expected: PASS — dedup 8개, context 는 기존대로 전부 통과

- [ ] **Step 5: 커밋**

```bash
git add organize/blocks/dedup.py organize/core/context.py tests/test_block_dedup.py
git commit -m "dedup 블록 추가 — 하위 폴더는 참고만 하고 직속 파일만 치운다"
```

---

### Task 13: unzip 블록 — 한글 파일명 복구와 경로 탈출 방어

기존 `zipper*.py` 에는 둘 다 없었다. 구형 알집으로 만든 zip 은 한글 이름이 깨지고,
압축 안에 `../` 가 있으면 대상 폴더 **밖**으로 파일이 써진다.

**Files:**
- Create: `organize/blocks/unzip.py` (Task 10 의 stub 대체)
- Test: `tests/test_block_unzip.py`

**Interfaces:**
- Consumes: `zipfile`, `organize.core.context.Context`
- Produces:
  - `organize.blocks.unzip.build(ctx: Context, cfg: BlockConfig) -> Plan` — `extract` Action 의 `member` 에 압축 안의 **원래** 항목 이름(`info.filename`)을 담는다. 복구한 한글 이름이 아니라 원래 이름이어야 `ZipFile.open()` 이 찾는다
  - `organize.blocks.unzip.recover_name(raw: str, flag_bits: int) -> str`
  - `cfg.options["delete_original"]: bool` — 기본 `False`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_block_unzip.py`:

```python
import zipfile
from datetime import date
from pathlib import Path

from organize.blocks import BlockConfig
from organize.blocks.unzip import build, recover_name
from organize.core.context import Context
from organize.core.scanner import scan

TODAY = date(2026, 8, 21)


def ctx_for(tmp_path):
    entries = scan(tmp_path, now=1e12).entries
    return Context(root=tmp_path, entries=entries, today=TODAY, run_id="r1")


def make_zip(path: Path, names: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for n in names:
            z.writestr(n, b"DATA")
    return path


def extracts(plan):
    return sorted(a.dst.name for a in plan.actions if a.kind == "extract")


def test_no_zip_means_no_actions(tmp_path):
    (tmp_path / "그냥.txt").write_bytes(b"x")
    assert build(ctx_for(tmp_path), BlockConfig()).actions == []


def test_members_are_flattened_into_the_target(tmp_path):
    make_zip(tmp_path / "자료.zip", ["문서.pdf", "안쪽폴더/사진.png"])
    plan = build(ctx_for(tmp_path), BlockConfig())
    assert extracts(plan) == ["문서.pdf", "사진.png"]
    assert all(a.dst.parent == tmp_path for a in plan.actions if a.kind == "extract")


def test_extract_action_remembers_the_original_member_name(tmp_path):
    """실행기가 ZipFile.open(member) 로 찾을 수 있어야 한다."""
    make_zip(tmp_path / "자료.zip", ["안쪽폴더/사진.png"])
    a = next(x for x in build(ctx_for(tmp_path), BlockConfig()).actions if x.kind == "extract")
    assert a.member == "안쪽폴더/사진.png"
    assert a.dst.name == "사진.png"


def test_directory_entries_are_ignored(tmp_path):
    make_zip(tmp_path / "자료.zip", ["폴더/", "폴더/문서.pdf"])
    assert extracts(build(ctx_for(tmp_path), BlockConfig())) == ["문서.pdf"]


def test_name_collision_inside_one_zip_gets_a_number(tmp_path):
    make_zip(tmp_path / "자료.zip", ["a/문서.pdf", "b/문서.pdf"])
    assert extracts(build(ctx_for(tmp_path), BlockConfig())) == ["문서.pdf", "문서_(1).pdf"]


def test_collision_with_an_existing_file_gets_a_number(tmp_path):
    (tmp_path / "문서.pdf").write_bytes(b"OLDFILE")
    make_zip(tmp_path / "자료.zip", ["문서.pdf"])
    assert extracts(build(ctx_for(tmp_path), BlockConfig())) == ["문서_(1).pdf"]


def test_path_traversal_is_refused(tmp_path):
    make_zip(tmp_path / "나쁜.zip", ["../탈출.txt", "정상.txt"])
    plan = build(ctx_for(tmp_path), BlockConfig())
    assert extracts(plan) == ["정상.txt"]
    assert any("압축 안의 경로가 대상 폴더를 벗어남" in why for _, why in plan.skipped)


def test_cp949_name_is_recovered():
    raw = "한글파일.txt".encode("cp949").decode("cp437")
    assert recover_name(raw, flag_bits=0) == "한글파일.txt"


def test_utf8_flagged_name_is_left_alone():
    assert recover_name("한글파일.txt", flag_bits=0x800) == "한글파일.txt"


def test_original_zip_is_kept_by_default(tmp_path):
    make_zip(tmp_path / "자료.zip", ["문서.pdf"])
    plan = build(ctx_for(tmp_path), BlockConfig())
    assert [a for a in plan.actions if a.kind == "quarantine"] == []


def test_original_zip_can_be_quarantined(tmp_path):
    make_zip(tmp_path / "자료.zip", ["문서.pdf"])
    plan = build(ctx_for(tmp_path), BlockConfig(options={"delete_original": True}))
    q = [a for a in plan.actions if a.kind == "quarantine"]
    assert len(q) == 1 and q[0].src.name == "자료.zip"
    assert q[0].dst.parent == tmp_path / ".organize" / "trash" / "r1"


def test_broken_zip_is_skipped_not_crashed(tmp_path):
    (tmp_path / "깨진.zip").write_bytes(b"not a zip file")
    plan = build(ctx_for(tmp_path), BlockConfig())
    assert plan.actions == []
    assert "열 수 없습니다" in plan.skipped[0][1]
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_block_unzip.py -v`
Expected: FAIL — stub 이 빈 `Plan()` 을 돌려주므로 대부분 실패

- [ ] **Step 3: 최소 구현을 쓴다**

`organize/blocks/unzip.py`:

```python
"""폴더 안의 zip 을 대상 폴더로 평탄화 해제한다.

두 가지를 기존 스크립트에 없던 대로 처리한다.

1. 한글 이름 복구 — 구형 Windows 압축 프로그램은 파일명을 cp949 로 저장하는데
   파이썬은 UTF-8 플래그가 없으면 cp437 로 읽는다. 되돌려서 cp949 로 다시 읽는다.
2. 경로 탈출 방어 — 압축 안에 `../` 가 있으면 대상 폴더 밖에 파일을 쓸 수 있다.
   평탄화하므로 원래도 안전하지만, 이름 자체를 검증해 명시적으로 거부한다.
"""

import zipfile
from pathlib import Path, PurePosixPath

from organize.blocks import BlockConfig, dest_folder
from organize.core.action import Action, Plan
from organize.core.context import Context

BLOCK = "unzip"
_UTF8_FLAG = 0x800


def recover_name(raw: str, flag_bits: int) -> str:
    """UTF-8 플래그가 없는 항목의 깨진 한글 이름을 되살린다."""
    if flag_bits & _UTF8_FLAG:
        return raw
    try:
        return raw.encode("cp437").decode("cp949")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return raw


def _unique(dst_dir: Path, name: str, taken: set[str]) -> str:
    if name not in taken:
        return name
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 1
    while f"{stem}_({n}){suffix}" in taken:
        n += 1
    return f"{stem}_({n}){suffix}"


def build(ctx: Context, cfg: BlockConfig) -> Plan:
    plan = Plan()
    out_dir = dest_folder(ctx, cfg.out, block=BLOCK) if cfg.out else ctx.root
    taken = {e.path.name for e in ctx.files_at(cfg.out)}

    for entry in ctx.files_at(cfg.target):
        if entry.ext != ".zip" or entry.virtual:
            continue
        src = ctx.current_path(entry)
        try:
            with zipfile.ZipFile(src) as z:
                infos = z.infolist()
        except (zipfile.BadZipFile, OSError):
            plan.skipped.append((entry.path, "압축 파일을 열 수 없습니다"))
            continue

        extracted = 0
        for info in infos:
            if info.is_dir():
                continue
            name = recover_name(info.filename, info.flag_bits)
            leaf = PurePosixPath(name.replace("\\", "/")).name
            if not leaf or leaf in (".", "..") or ".." in PurePosixPath(name).parts:
                plan.skipped.append((entry.path, f"압축 안의 경로가 대상 폴더를 벗어남: {name}"))
                continue
            final = _unique(out_dir, leaf, taken)
            taken.add(final)
            plan.actions.append(Action(
                kind="extract", src=src, dst=out_dir / final,
                reason=f"{entry.name} 에서 꺼냄", block=BLOCK,
                member=info.filename,          # 실행기가 이 이름으로 꺼낸다
            ))
            extracted += 1

        if extracted and cfg.options.get("delete_original", False):
            plan.actions.append(Action(
                kind="quarantine", src=src, dst=ctx.trash_dir / entry.name,
                reason=f"압축을 푼 원본 ({extracted}개 꺼냄)", block=BLOCK,
            ))
    return plan
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_block_unzip.py -v`
Expected: PASS 11개

- [ ] **Step 5: 커밋**

```bash
git add organize/blocks/unzip.py tests/test_block_unzip.py
git commit -m "unzip 블록 추가 — 한글 파일명 복구와 경로 탈출 방어"
```

---

### Task 14: 실제 파일 이동 — 이름 충돌과 드라이브 넘기

여기서부터는 진짜로 파일을 만진다. 이 태스크의 함수는 실행기만 쓴다.

**Files:**
- Create: `organize/core/paths.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- Consumes: `shutil`, `organize.errors.OrganizeError`
- Produces:
  - `organize.core.paths.unique_path(dst: Path) -> Path` — 이미 있으면 `이름_(1).확장자`
  - `organize.core.paths.same_drive(a: Path, b: Path) -> bool`
  - `organize.core.paths.move_file(src: Path, dst: Path) -> Path` — 실제 이동. 최종 경로를 돌려준다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_paths.py`:

```python
from pathlib import Path

import pytest

from organize.core.paths import move_file, same_drive, unique_path


def test_unique_path_returns_input_when_free(tmp_path):
    p = tmp_path / "a.txt"
    assert unique_path(p) == p


def test_unique_path_adds_a_number(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x")
    assert unique_path(tmp_path / "a.txt") == tmp_path / "a_(1).txt"


def test_unique_path_keeps_counting(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x")
    (tmp_path / "a_(1).txt").write_bytes(b"x")
    assert unique_path(tmp_path / "a.txt") == tmp_path / "a_(2).txt"


def test_unique_path_handles_no_extension(tmp_path):
    (tmp_path / "README").write_bytes(b"x")
    assert unique_path(tmp_path / "README") == tmp_path / "README_(1)"


def test_move_file_moves_and_creates_parent(tmp_path):
    src = tmp_path / "a.txt"
    src.write_bytes(b"DATA")
    dst = tmp_path / "깊은" / "폴더" / "a.txt"
    final = move_file(src, dst)
    assert final == dst
    assert dst.read_bytes() == b"DATA"
    assert not src.exists()


def test_move_file_avoids_overwriting(tmp_path):
    (tmp_path / "기존.txt").write_bytes(b"OLDFILE")
    src = tmp_path / "새것.txt"
    src.write_bytes(b"NEWFILE")
    final = move_file(src, tmp_path / "기존.txt")
    assert final == tmp_path / "기존_(1).txt"
    assert (tmp_path / "기존.txt").read_bytes() == b"OLDFILE"     # 원본이 살아있다
    assert final.read_bytes() == b"NEWFILE"


def test_same_drive_is_true_within_one_tree(tmp_path):
    assert same_drive(tmp_path / "a", tmp_path / "b" / "c")


def test_cross_drive_path_uses_copy_then_delete(tmp_path, monkeypatch):
    """다른 드라이브면 copy2 로 복사하고 크기를 확인한 뒤 원본을 지운다."""
    import organize.core.paths as paths
    monkeypatch.setattr(paths, "same_drive", lambda a, b: False)
    src = tmp_path / "a.txt"
    src.write_bytes(b"DATA")
    dst = tmp_path / "다른곳" / "a.txt"
    assert move_file(src, dst) == dst
    assert dst.read_bytes() == b"DATA"
    assert not src.exists()


def test_missing_source_is_a_friendly_error(tmp_path):
    from organize.errors import OrganizeError
    with pytest.raises(OrganizeError):
        move_file(tmp_path / "없음.txt", tmp_path / "b.txt")
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'organize.core.paths'`

- [ ] **Step 3: 최소 구현을 쓴다**

`organize/core/paths.py`:

```python
"""실제로 파일을 옮긴다. 덮어쓰지 않는다.

드라이브가 다르면 `shutil.move` 도 내부적으로 복사 후 삭제를 하지만,
복사가 끝났는지 확인하지 않는다. 파일이 사라지면 안 되므로
직접 copy2 → 크기 확인 → 삭제 순으로 한다.
"""

import shutil
from pathlib import Path

from organize.errors import OrganizeError


def unique_path(dst: Path) -> Path:
    if not dst.exists():
        return dst
    stem, suffix = dst.stem, dst.suffix
    n = 1
    while True:
        candidate = dst.with_name(f"{stem}_({n}){suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def same_drive(a: Path, b: Path) -> bool:
    return a.drive.lower() == b.drive.lower()


def move_file(src: Path, dst: Path) -> Path:
    if not src.exists():
        raise OrganizeError(
            f"옮기려는 파일이 없습니다: {src.name}",
            hint="미리보기 이후에 파일이 지워졌거나 이름이 바뀌었을 수 있습니다.",
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    final = unique_path(dst)

    if same_drive(src, final):
        shutil.move(str(src), str(final))
        return final

    shutil.copy2(str(src), str(final))
    if final.stat().st_size != src.stat().st_size:      # 복사 검증 후에만 지운다
        final.unlink(missing_ok=True)
        raise OrganizeError(
            f"복사가 끝나지 않아 옮기지 못했습니다: {src.name}",
            hint="대상 드라이브의 남은 공간과 연결 상태를 확인해 주세요.",
        )
    src.unlink()
    return final
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_paths.py -v`
Expected: PASS 9개

- [ ] **Step 5: 커밋**

```bash
git add organize/core/paths.py tests/test_paths.py
git commit -m "파일 이동 추가 — 덮어쓰지 않고 드라이브 넘기는 복사 후 검증"
```

---

### Task 15: 러너 — 블록을 순서대로 엮어 하나의 Plan 으로

**Files:**
- Create: `organize/core/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: `organize.core.scanner.scan`, `organize.core.context.Context`, `organize.blocks.get_block`, `organize.profiles.load_profile`
- Produces:
  - `organize.core.runner.BuiltPlan` — `root: Path`, `run_id: str`, `plan: Plan`, `per_block: list[tuple[str, int]]`, `snapshot: dict[str, tuple[int, float]]`
  - `organize.core.runner.make_run_id(now: datetime) -> str` — `"20260821-143210"`
  - `organize.core.runner.build_plan(root: Path, steps: list[dict], *, today: date, run_id: str, profiles_dir: Path, now: float | None = None) -> BuiltPlan` — `now` 는 스캐너의 "최근 1분 내 수정" 판정 기준시각. 테스트가 방금 만든 파일이 제외되지 않도록 주입할 수 있게 열어둔다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_runner.py`:

```python
from datetime import date, datetime
from pathlib import Path

import pytest

from organize.core.runner import build_plan, make_run_id
from organize.errors import OrganizeError

TODAY = date(2026, 8, 21)


@pytest.fixture
def profiles_dir(tmp_path):
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


def work(tmp_path):
    root = tmp_path / "작업"
    root.mkdir()
    return root


def old_file(path: Path, data: bytes = b"DATA") -> Path:
    """방금 만든 파일은 '작업 중' 으로 걸러지므로 수정시각을 한 시간 전으로 돌린다."""
    import os, time
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    past = time.time() - 3600
    os.utime(path, (past, past))
    return path


def test_run_id_format():
    assert make_run_id(datetime(2026, 8, 21, 14, 32, 10)) == "20260821-143210"


def test_single_step(tmp_path, profiles_dir):
    root = work(tmp_path)
    old_file(root / "보고서.pdf")
    built = build_plan(root, [{"block": "route", "profile": "desktop"}],
                       today=TODAY, run_id="r1", profiles_dir=profiles_dir)
    moves = [a for a in built.plan.actions if a.kind == "move"]
    assert [a.dst.parent.name for a in moves] == ["01_Docs"]
    assert built.per_block == [("route", 2)]        # mkdir 1 + move 1


def test_chained_steps_see_the_previous_result(tmp_path, profiles_dir):
    """route 가 02_Media 를 만들면 by_date 가 그 안을 대상으로 잡는다."""
    root = work(tmp_path)
    old_file(root / "2023-12-15.png")
    built = build_plan(
        root,
        [{"block": "route", "profile": "desktop"},
         {"block": "by_date", "target": "02_Media", "layout": "{year}"}],
        today=TODAY, run_id="r1", profiles_dir=profiles_dir,
    )
    dsts = [a.dst for a in built.plan.actions if a.kind == "move"]
    assert dsts[0] == root / "02_Media" / "2023-12-15.png"
    assert dsts[1] == root / "02_Media" / "2023" / "2023-12-15.png"


def test_wrong_order_produces_zero_actions_for_the_later_block(tmp_path, profiles_dir):
    """연도별을 먼저 돌리면 파일이 2023/ 안으로 들어가 route 대상이 사라진다."""
    root = work(tmp_path)
    old_file(root / "2023-12-15.png")
    built = build_plan(
        root,
        [{"block": "by_date"}, {"block": "route", "profile": "desktop"}],
        today=TODAY, run_id="r1", profiles_dir=profiles_dir,
    )
    assert dict(built.per_block)["route"] == 0


def test_scanner_skips_are_carried_into_the_plan(tmp_path, profiles_dir):
    root = work(tmp_path)
    old_file(root / "desktop.ini")
    old_file(root / "보고서.pdf")
    built = build_plan(root, [{"block": "route", "profile": "desktop"}],
                       today=TODAY, run_id="r1", profiles_dir=profiles_dir)
    assert any("시스템 파일" in why for _, why in built.plan.skipped)


def test_snapshot_records_size_and_mtime(tmp_path, profiles_dir):
    root = work(tmp_path)
    f = old_file(root / "보고서.pdf", b"12345")
    built = build_plan(root, [{"block": "route", "profile": "desktop"}],
                       today=TODAY, run_id="r1", profiles_dir=profiles_dir)
    assert built.snapshot[str(f)][0] == 5


def test_nothing_is_moved_on_disk(tmp_path, profiles_dir):
    """계획을 세우는 동안에는 파일이 하나도 움직이지 않아야 한다."""
    root = work(tmp_path)
    old_file(root / "보고서.pdf")
    build_plan(root, [{"block": "route", "profile": "desktop"}],
               today=TODAY, run_id="r1", profiles_dir=profiles_dir)
    assert (root / "보고서.pdf").exists()
    assert not (root / "01_Docs").exists()


def test_unknown_block_is_a_friendly_error(tmp_path, profiles_dir):
    root = work(tmp_path)
    with pytest.raises(OrganizeError):
        build_plan(root, [{"block": "없는것"}], today=TODAY, run_id="r1",
                   profiles_dir=profiles_dir)


def test_unknown_profile_is_a_friendly_error(tmp_path, profiles_dir):
    root = work(tmp_path)
    with pytest.raises(OrganizeError) as ex:
        build_plan(root, [{"block": "route", "profile": "없는설정"}],
                   today=TODAY, run_id="r1", profiles_dir=profiles_dir)
    assert "없는설정" in ex.value.message
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'organize.core.runner'`

- [ ] **Step 3: 최소 구현을 쓴다**

`organize/core/runner.py`:

```python
"""블록을 순서대로 엮어 하나의 Plan 으로 모은다.

블록끼리는 서로를 모른다. 앞 블록의 결과는 Context 를 통해서만 전달된다.
따라서 순서를 바꾸면 뒤 블록의 대상이 바뀌고, 때로는 0건이 된다.
그것이 정상 동작이며, 사용자에게 건수를 보여줘 알아채게 한다.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from organize.blocks import BlockConfig, get_block
from organize.core.action import Plan
from organize.core.context import Context
from organize.core.scanner import scan
from organize.profiles import load_profile

_RESERVED = {"block", "target", "dest", "when"}


@dataclass
class BuiltPlan:
    root: Path
    run_id: str
    plan: Plan
    per_block: list[tuple[str, int]] = field(default_factory=list)
    snapshot: dict[str, tuple[int, float]] = field(default_factory=dict)


def make_run_id(now: datetime) -> str:
    return now.strftime("%Y%m%d-%H%M%S")


def _to_config(step: dict, profiles_dir: Path) -> BlockConfig:
    options = {k: v for k, v in step.items() if k not in _RESERVED}
    if "profile" in options:
        options["profile"] = load_profile(profiles_dir / f"{options['profile']}.toml")
    return BlockConfig(
        target=step.get("target", ""),
        dest=step.get("dest"),
        when=step.get("when", {}) or {},
        options=options,
    )


def build_plan(root: Path, steps: list[dict], *, today: date, run_id: str,
               profiles_dir: Path, now: float | None = None) -> BuiltPlan:
    # 하위 폴더까지 읽는다. dedup 이 참고해야 하기 때문이다.
    # files_at("") 은 직속만 돌려주므로 하위 폴더 파일이 함부로 옮겨지지는 않는다.
    scanned = scan(root, recursive=True, now=now)
    ctx = Context(root=root, entries=scanned.entries, today=today, run_id=run_id)

    built = BuiltPlan(root=root, run_id=run_id, plan=Plan())
    built.plan.skipped.extend(scanned.skipped)
    built.snapshot = {str(e.path): (e.size, e.mtime) for e in scanned.entries}

    for step in steps:
        fn = get_block(step["block"])
        sub = fn(ctx, _to_config(step, profiles_dir))
        ctx.apply(sub)
        built.plan.extend(sub)
        built.per_block.append((step["block"], len(sub.actions)))

    return built
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_runner.py -v`
Expected: PASS 9개

- [ ] **Step 5: 커밋**

```bash
git add organize/core/runner.py tests/test_runner.py
git commit -m "러너 추가 — 블록 체인을 하나의 Plan 으로"
```

---

### Task 16: 실행기 — 실행 직전 재검증, 부분 실패, 실행 로그

한 파일이 여러 번 옮겨진다(route → by_date). 중간에 이름 충돌로 `_(1)` 이 붙으면
**다음 동작의 원본 경로가 어긋난다.** 실행기가 그 대응표를 들고 있어야 한다.

**Files:**
- Create: `organize/core/executor.py`
- Test: `tests/test_executor.py`

**Interfaces:**
- Consumes: `organize.core.paths.move_file`, `organize.core.runner.BuiltPlan`
- Produces:
  - `organize.core.executor.ExecResult` — `done: list[dict]`, `failed: list[dict]`, `stale: list[dict]`
  - `organize.core.executor.execute(built: BuiltPlan) -> ExecResult`
  - `organize.core.executor.write_runlog(built: BuiltPlan, result: ExecResult) -> Path`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_executor.py`:

```python
import json
import zipfile
from datetime import date
from pathlib import Path

from organize.core.action import Action, Plan
from organize.core.executor import execute, write_runlog
from organize.core.runner import BuiltPlan

TODAY = date(2026, 8, 21)


def built_for(root, actions, snapshot=None):
    return BuiltPlan(root=root, run_id="r1", plan=Plan(actions=list(actions)),
                     snapshot=snapshot or {})


def test_mkdir_creates_the_folder(tmp_path):
    b = built_for(tmp_path, [Action("mkdir", None, tmp_path / "01_Docs", "폴더", "route")])
    r = execute(b)
    assert (tmp_path / "01_Docs").is_dir()
    assert len(r.done) == 1 and not r.failed


def test_move_moves_the_file(tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"DATA")
    b = built_for(tmp_path, [Action("move", src, tmp_path / "01_Docs" / "a.pdf", "확장자", "route")])
    execute(b)
    assert (tmp_path / "01_Docs" / "a.pdf").read_bytes() == b"DATA"
    assert not src.exists()


def test_chained_moves_follow_a_rename(tmp_path):
    """첫 이동에서 이름이 바뀌면 두 번째 이동의 원본도 따라가야 한다."""
    (tmp_path / "01_Docs").mkdir()
    (tmp_path / "01_Docs" / "a.pdf").write_bytes(b"OLDFILE")
    src = tmp_path / "a.pdf"
    src.write_bytes(b"NEWFILE")
    b = built_for(tmp_path, [
        Action("move", src, tmp_path / "01_Docs" / "a.pdf", "1차", "route"),
        Action("move", tmp_path / "01_Docs" / "a.pdf",
               tmp_path / "01_Docs" / "2023" / "a.pdf", "2차", "by_date"),
    ])
    r = execute(b)
    assert not r.failed
    # 1차에서 a_(1).pdf 로 밀렸지만, 2차 이동은 그 파일을 따라가 최종적으로 a.pdf 가 된다
    assert (tmp_path / "01_Docs" / "2023" / "a.pdf").read_bytes() == b"NEWFILE"
    assert (tmp_path / "01_Docs" / "a.pdf").read_bytes() == b"OLDFILE"
    assert not (tmp_path / "01_Docs" / "a_(1).pdf").exists()


def test_quarantine_moves_into_the_trash_folder(tmp_path):
    src = tmp_path / "중복.pdf"
    src.write_bytes(b"x")
    trash = tmp_path / ".organize" / "trash" / "r1"
    b = built_for(tmp_path, [Action("quarantine", src, trash / "중복.pdf", "중복", "dedup")])
    execute(b)
    assert (trash / "중복.pdf").exists()
    assert not src.exists()


def test_quarantine_writes_a_manifest(tmp_path):
    src = tmp_path / "중복.pdf"
    src.write_bytes(b"x")
    trash = tmp_path / ".organize" / "trash" / "r1"
    b = built_for(tmp_path, [Action("quarantine", src, trash / "중복.pdf", "중복", "dedup")])
    execute(b)
    manifest = json.loads((trash / "_manifest.json").read_text(encoding="utf-8"))
    assert manifest[0]["from"] == str(src)


def test_extract_pulls_the_named_member(tmp_path):
    z = tmp_path / "자료.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("안쪽/문서.pdf", b"ZIPPED")
    b = built_for(tmp_path, [Action("extract", z, tmp_path / "문서.pdf",
                                    "꺼냄", "unzip", member="안쪽/문서.pdf")])
    execute(b)
    assert (tmp_path / "문서.pdf").read_bytes() == b"ZIPPED"


def test_changed_file_is_reported_as_stale_and_not_moved(tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"SHORT")
    snapshot = {str(src): (999, 0.0)}                   # 계획 시점과 크기가 다르다
    b = built_for(tmp_path, [Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route")],
                  snapshot)
    r = execute(b)
    assert src.exists()
    assert not r.done and len(r.stale) == 1
    assert "바뀌었" in r.stale[0]["why"]


def test_one_failure_does_not_stop_the_rest(tmp_path):
    ok = tmp_path / "있음.pdf"
    ok.write_bytes(b"x")
    b = built_for(tmp_path, [
        Action("move", tmp_path / "없음.pdf", tmp_path / "01_Docs" / "없음.pdf", "이동", "route"),
        Action("move", ok, tmp_path / "01_Docs" / "있음.pdf", "이동", "route"),
    ])
    r = execute(b)
    assert len(r.failed) == 1
    assert (tmp_path / "01_Docs" / "있음.pdf").exists()


def test_runlog_is_written_and_readable(tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"x")
    b = built_for(tmp_path, [Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route")])
    r = execute(b)
    log_path = write_runlog(b, r)
    assert log_path == tmp_path / ".organize" / "runs" / "r1.json"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert data["run_id"] == "r1"
    assert data["done"][0]["kind"] == "move"
    assert data["done"][0]["final"].endswith("a.pdf")
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_executor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'organize.core.executor'`

- [ ] **Step 3: 최소 구현을 쓴다**

`organize/core/executor.py`:

```python
"""Plan 을 실제로 수행하고 되돌릴 수 있는 기록을 남긴다.

세 가지를 지킨다.

1. 실행 직전 재검증 — 계획 시점의 크기·수정시각과 다르면 그 항목만 건너뛴다.
   미리보기와 실행 사이에 사람이 파일을 건드렸을 수 있다.
2. 부분 실패 — 하나가 실패해도 멈추지 않는다. 이미 한 일은 로그에 남아 되돌릴 수 있다.
3. 이름 바뀜 추적 — 한 파일이 여러 번 옮겨질 때, 앞 이동에서 _(1) 이 붙으면
   뒤 이동의 원본 경로가 어긋난다. 대응표로 이어 붙인다.
"""

import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from organize.core.paths import move_file, unique_path
from organize.core.runner import BuiltPlan
from organize.errors import OrganizeError


@dataclass
class ExecResult:
    done: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    stale: list[dict] = field(default_factory=list)


def _changed(path: Path, expected: tuple[int, float]) -> bool:
    try:
        st = path.stat()
    except OSError:
        return True
    size, mtime = expected
    return st.st_size != size or abs(st.st_mtime - mtime) > 1.0


def execute(built: BuiltPlan) -> ExecResult:
    result = ExecResult()
    remap: dict[Path, Path] = {}          # 계획된 경로 -> 실제로 놓인 경로
    quarantined: list[dict] = []

    for a in built.plan.actions:
        try:
            if a.kind == "mkdir":
                a.dst.mkdir(parents=True, exist_ok=True)
                result.done.append({"kind": "mkdir", "final": str(a.dst)})
                continue

            src = remap.get(a.src, a.src)

            expected = built.snapshot.get(str(src))
            if expected is not None and _changed(src, expected):
                result.stale.append({
                    "kind": a.kind, "src": str(src),
                    "why": "미리보기 이후에 파일이 바뀌었습니다",
                })
                continue

            if a.kind in ("move", "quarantine"):
                final = move_file(src, a.dst)
                if final != a.dst:
                    remap[a.dst] = final
                entry = {"kind": a.kind, "src": str(src), "final": str(final),
                         "reason": a.reason, "block": a.block}
                result.done.append(entry)
                if a.kind == "quarantine":
                    quarantined.append({"from": str(src), "to": str(final)})

            elif a.kind == "extract":
                a.dst.parent.mkdir(parents=True, exist_ok=True)
                final = unique_path(a.dst)
                with zipfile.ZipFile(src) as z, z.open(a.member) as member, \
                        final.open("wb") as out:
                    out.write(member.read())
                if final != a.dst:
                    remap[a.dst] = final
                result.done.append({"kind": "extract", "src": str(src),
                                    "final": str(final), "member": a.member,
                                    "reason": a.reason, "block": a.block})

        except OrganizeError as e:
            result.failed.append({"kind": a.kind, "src": str(a.src), "why": e.message})
        except OSError as e:
            result.failed.append({"kind": a.kind, "src": str(a.src),
                                  "why": f"파일을 처리하지 못했습니다 ({e.strerror or e})"})

    if quarantined:
        trash = built.root / ".organize" / "trash" / built.run_id
        trash.mkdir(parents=True, exist_ok=True)
        (trash / "_manifest.json").write_text(
            json.dumps(quarantined, ensure_ascii=False, indent=2), encoding="utf-8")

    return result


def write_runlog(built: BuiltPlan, result: ExecResult) -> Path:
    runs = built.root / ".organize" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    path = runs / f"{built.run_id}.json"
    path.write_text(json.dumps({
        "run_id": built.run_id,
        "root": str(built.root),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "done": result.done,
        "failed": result.failed,
        "stale": result.stale,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_executor.py -v`
Expected: PASS 9개

- [ ] **Step 5: 커밋**

```bash
git add organize/core/executor.py tests/test_executor.py
git commit -m "실행기 추가 — 재검증·부분실패·이름바뀜 추적과 실행 로그"
```

---

### Task 17: 되돌리기 — 실행 로그를 역순으로 재생한다

**Files:**
- Create: `organize/core/undo.py`
- Test: `tests/test_undo.py`

**Interfaces:**
- Consumes: `organize.core.paths.move_file`, `organize.core.executor.ExecResult`
- Produces:
  - `organize.core.undo.latest_run_id(root: Path) -> str | None` — 아직 되돌리지 않은 가장 최근 실행
  - `organize.core.undo.list_runs(root: Path) -> list[dict]` — `{"run_id", "finished_at", "undone_at" | None, "count"}`
  - `organize.core.undo.undo(root: Path, run_id: str | None = None) -> ExecResult`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_undo.py`:

```python
import json
from pathlib import Path

import pytest

from organize.core.action import Action, Plan
from organize.core.executor import execute, write_runlog
from organize.core.runner import BuiltPlan
from organize.core.undo import latest_run_id, list_runs, undo
from organize.errors import OrganizeError


def run_plan(root, actions, run_id="r1"):
    b = BuiltPlan(root=root, run_id=run_id, plan=Plan(actions=list(actions)))
    result = execute(b)
    write_runlog(b, result)
    return result


def test_move_is_reversed(tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"DATA")
    run_plan(tmp_path, [
        Action("mkdir", None, tmp_path / "01_Docs", "폴더", "route"),
        Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route"),
    ])
    assert not src.exists()

    undo(tmp_path)
    assert src.read_bytes() == b"DATA"
    assert not (tmp_path / "01_Docs" / "a.pdf").exists()


def test_empty_folder_is_removed_but_a_used_one_is_kept(tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"DATA")
    run_plan(tmp_path, [
        Action("mkdir", None, tmp_path / "01_Docs", "폴더", "route"),
        Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route"),
    ])
    (tmp_path / "01_Docs" / "사용자가둔파일.txt").write_bytes(b"KEEP")

    undo(tmp_path)
    assert (tmp_path / "01_Docs").is_dir()               # 비어있지 않으니 남긴다
    assert (tmp_path / "01_Docs" / "사용자가둔파일.txt").exists()


def test_quarantine_is_restored(tmp_path):
    src = tmp_path / "중복.pdf"
    src.write_bytes(b"DATA")
    trash = tmp_path / ".organize" / "trash" / "r1"
    run_plan(tmp_path, [Action("quarantine", src, trash / "중복.pdf", "중복", "dedup")])
    assert not src.exists()

    undo(tmp_path)
    assert src.read_bytes() == b"DATA"


def test_extracted_file_goes_to_the_undo_trash(tmp_path):
    import zipfile
    z = tmp_path / "자료.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("문서.pdf", b"ZIPPED")
    run_plan(tmp_path, [Action("extract", z, tmp_path / "문서.pdf", "꺼냄", "unzip",
                               member="문서.pdf")])
    assert (tmp_path / "문서.pdf").exists()

    undo(tmp_path)
    assert not (tmp_path / "문서.pdf").exists()
    assert (tmp_path / ".organize" / "trash" / "r1-undo" / "문서.pdf").exists()
    assert z.exists()                                    # 원본 zip 은 그대로


def test_round_trip_leaves_the_folder_as_it_was(tmp_path):
    for name in ["a.pdf", "b.png", "c.md"]:
        (tmp_path / name).write_bytes(name.encode())
    before = sorted(p.name for p in tmp_path.iterdir())

    run_plan(tmp_path, [
        Action("mkdir", None, tmp_path / "01_Docs", "폴더", "route"),
        Action("move", tmp_path / "a.pdf", tmp_path / "01_Docs" / "a.pdf", "이동", "route"),
        Action("move", tmp_path / "c.md", tmp_path / "01_Docs" / "c.md", "이동", "route"),
    ])
    undo(tmp_path)

    after = sorted(p.name for p in tmp_path.iterdir() if p.name != ".organize")
    assert after == before


def test_undo_marks_the_run_and_does_not_repeat(tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"DATA")
    run_plan(tmp_path, [Action("move", src, tmp_path / "01_Docs" / "a.pdf", "이동", "route")])
    undo(tmp_path)

    assert latest_run_id(tmp_path) is None
    log = json.loads((tmp_path / ".organize" / "runs" / "r1.json").read_text(encoding="utf-8"))
    assert log["undone_at"]


def test_latest_picks_the_newest_run(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"DATA")
    (tmp_path / "b.pdf").write_bytes(b"DATA")
    run_plan(tmp_path, [Action("move", tmp_path / "a.pdf", tmp_path / "x" / "a.pdf", "이동", "route")],
             run_id="20260821-100000")
    run_plan(tmp_path, [Action("move", tmp_path / "b.pdf", tmp_path / "x" / "b.pdf", "이동", "route")],
             run_id="20260821-110000")
    assert latest_run_id(tmp_path) == "20260821-110000"


def test_list_runs_reports_state(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"DATA")
    run_plan(tmp_path, [Action("move", tmp_path / "a.pdf", tmp_path / "x" / "a.pdf", "이동", "route")])
    rows = list_runs(tmp_path)
    assert rows[0]["run_id"] == "r1" and rows[0]["undone_at"] is None
    undo(tmp_path)
    assert list_runs(tmp_path)[0]["undone_at"] is not None


def test_nothing_to_undo_is_a_friendly_error(tmp_path):
    with pytest.raises(OrganizeError) as ex:
        undo(tmp_path)
    assert "되돌릴" in ex.value.message
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_undo.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'organize.core.undo'`

- [ ] **Step 3: 최소 구현을 쓴다**

`organize/core/undo.py`:

```python
"""실행 로그를 역순으로 재생해 되돌린다.

파일을 지우지 않았기 때문에 되돌릴 수 있다. 격리 폴더에 있는 것은 제자리로,
옮긴 것은 원래 위치로 돌린다. 압축을 푼 파일만은 되돌릴 곳이 없으므로
격리 폴더로 보낸다.
"""

import json
from datetime import datetime
from pathlib import Path

from organize.core.executor import ExecResult
from organize.core.paths import move_file
from organize.errors import OrganizeError


def _runs_dir(root: Path) -> Path:
    return root / ".organize" / "runs"


def list_runs(root: Path) -> list[dict]:
    rows = []
    for path in sorted(_runs_dir(root).glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows.append({
            "run_id": data.get("run_id", path.stem),
            "finished_at": data.get("finished_at"),
            "undone_at": data.get("undone_at"),
            "count": len(data.get("done", [])),
        })
    return rows


def latest_run_id(root: Path) -> str | None:
    for row in list_runs(root):
        if row["undone_at"] is None and row["count"]:
            return row["run_id"]
    return None


def undo(root: Path, run_id: str | None = None) -> ExecResult:
    run_id = run_id or latest_run_id(root)
    if run_id is None:
        raise OrganizeError(
            "되돌릴 실행 기록이 없습니다.",
            hint="organize run <레시피> --apply 로 한 번 실행한 뒤에 쓸 수 있습니다.",
        )

    log_path = _runs_dir(root) / f"{run_id}.json"
    if not log_path.is_file():
        raise OrganizeError(f"'{run_id}' 실행 기록을 찾을 수 없습니다.",
                            hint="organize trash --list 로 남은 기록을 볼 수 있습니다.")

    data = json.loads(log_path.read_text(encoding="utf-8"))
    result = ExecResult()
    undo_trash = root / ".organize" / "trash" / f"{run_id}-undo"

    for item in reversed(data.get("done", [])):
        kind = item["kind"]
        try:
            if kind == "mkdir":
                folder = Path(item["final"])
                if folder.is_dir() and not any(folder.iterdir()):
                    folder.rmdir()                       # 비어 있을 때만 지운다
                    result.done.append({"kind": "rmdir", "final": str(folder)})
                continue

            final = Path(item["final"])
            if kind in ("move", "quarantine"):
                back = move_file(final, Path(item["src"]))
                result.done.append({"kind": "restore", "final": str(back)})
            elif kind == "extract":
                moved = move_file(final, undo_trash / final.name)
                result.done.append({"kind": "quarantine", "final": str(moved)})

        except OrganizeError as e:
            result.failed.append({"kind": kind, "src": item.get("final"), "why": e.message})
        except OSError as e:
            result.failed.append({"kind": kind, "src": item.get("final"),
                                  "why": f"되돌리지 못했습니다 ({e.strerror or e})"})

    data["undone_at"] = datetime.now().isoformat(timespec="seconds")
    log_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_undo.py -v`
Expected: PASS 9개

- [ ] **Step 5: 커밋**

```bash
git add organize/core/undo.py tests/test_undo.py
git commit -m "되돌리기 추가 — 실행 로그 역순 재생"
```

---

### Task 18: 레시피와 CLI — 여기서 도구가 실제로 쓸 수 있게 된다

**이 태스크가 끝나면 터미널에서 실제 폴더를 정리하고 되돌릴 수 있다.**

**Files:**
- Create: `organize/recipes.py`, `recipes/downloads.json`
- Modify: `organize/cli.py` (Task 1 의 뼈대를 실제 명령으로 대체)
- Test: `tests/test_recipes.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: 앞 태스크 전부
- Produces:
  - `organize.recipes.Recipe` — `name: str`, `roots: list[str]`, `steps: list[dict]`
  - `organize.recipes.load_recipe(path: Path) -> Recipe`
  - `organize.recipes.save_recipe(path: Path, recipe: Recipe) -> None`
  - `organize.recipes.find_recipe(recipes_dir: Path, name: str) -> Path`
  - `organize.recipes.list_recipes(recipes_dir: Path) -> list[str]`
  - `organize.cli.repo_root() -> Path`
  - `organize.cli.main(argv) -> int` — `preview` / `run` / `undo` 처리

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_recipes.py`:

```python
import json
from pathlib import Path

import pytest

from organize.errors import OrganizeError
from organize.recipes import Recipe, find_recipe, list_recipes, load_recipe, save_recipe


def test_round_trip(tmp_path):
    r = Recipe(name="다운로드 정리", roots=["@downloads"],
               steps=[{"block": "route", "profile": "desktop"}])
    p = tmp_path / "downloads.json"
    save_recipe(p, r)
    assert load_recipe(p) == r


def test_single_root_string_is_normalised(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"name": "x", "roots": "@downloads", "steps": []}),
                 encoding="utf-8")
    assert load_recipe(p).roots == ["@downloads"]


def test_missing_steps_is_an_error(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"name": "x", "roots": ["@downloads"]}), encoding="utf-8")
    with pytest.raises(OrganizeError):
        load_recipe(p)


def test_find_recipe_accepts_name_without_extension(tmp_path):
    (tmp_path / "downloads.json").write_text(
        json.dumps({"name": "x", "roots": ["@downloads"], "steps": []}), encoding="utf-8")
    assert find_recipe(tmp_path, "downloads").name == "downloads.json"


def test_find_recipe_lists_options_when_missing(tmp_path):
    (tmp_path / "downloads.json").write_text("{}", encoding="utf-8")
    with pytest.raises(OrganizeError) as ex:
        find_recipe(tmp_path, "없는것")
    assert "downloads" in (ex.value.hint or "")


def test_list_recipes(tmp_path):
    (tmp_path / "b.json").write_text("{}", encoding="utf-8")
    (tmp_path / "a.json").write_text("{}", encoding="utf-8")
    assert list_recipes(tmp_path) == ["a", "b"]
```

`tests/test_cli.py`:

```python
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
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_recipes.py tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'organize.recipes'`

- [ ] **Step 3: 최소 구현을 쓴다**

`organize/recipes.py`:

```python
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
    except (OSError, json.JSONDecodeError) as e:
        raise OrganizeError(f"레시피를 읽지 못했습니다: {path.name}", hint=str(e)) from e

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
```

`recipes/downloads.json`:

```json
{
  "name": "다운로드 정리",
  "roots": ["@downloads"],
  "steps": [
    { "block": "dedup" },
    { "block": "route", "profile": "desktop" }
  ]
}
```

`organize/cli.py` (전체 교체):

```python
"""명령줄. 출력 끝에는 항상 다음에 칠 명령어를 그대로 보여준다."""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from organize import __version__
from organize.core.executor import execute, write_runlog
from organize.core.runner import build_plan, make_run_id
from organize.core.undo import undo as undo_run
from organize.errors import OrganizeError
from organize.recipes import find_recipe, list_recipes, load_recipe
from organize.userconfig import load_config, resolve_alias

_KIND_LABEL = {"mkdir": "폴더 생성", "move": "이동", "quarantine": "격리", "extract": "압축 해제"}


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_roots(recipe, override: str | None) -> list[Path]:
    cfg = load_config(repo_root())
    specs = [override] if override else recipe.roots
    if not specs:
        raise OrganizeError("정리할 폴더가 지정되지 않았습니다.",
                            hint='레시피의 "roots" 에 폴더를 적거나 --root 를 쓰세요.')
    return [resolve_alias(s, cfg) for s in specs]


def _print_plan(built, verbose: bool) -> dict:
    counts = built.plan.counts()
    for i, (block, n) in enumerate(built.per_block, 1):
        note = "해당 없음" if n == 0 else f"{n}건"
        print(f"  [{i}/{len(built.per_block)}] {block:<9} {note}")

    if verbose:
        print()
        for a in built.plan.actions:
            label = _KIND_LABEL.get(a.kind, a.kind)
            name = a.src.name if a.src else ""
            print(f"    {label:<6} {name} → {a.dst}    {a.reason}")

    print()
    print(f"  총계  이동 {counts.get('move', 0)} · 격리 {counts.get('quarantine', 0)}"
          f" · 폴더 생성 {counts.get('mkdir', 0)} · 압축 해제 {counts.get('extract', 0)}"
          f" · 손대지 않음 {len(built.plan.skipped)}")
    return counts


def _cmd_preview(args) -> int:
    return _preview_or_run(args, apply=False)


def _cmd_run(args) -> int:
    return _preview_or_run(args, apply=bool(args.apply))


def _preview_or_run(args, *, apply: bool) -> int:
    recipes_dir = repo_root() / "recipes"
    recipe = load_recipe(find_recipe(recipes_dir, args.recipe))
    roots = _resolve_roots(recipe, args.root)
    run_id = make_run_id(datetime.now())

    for root in roots:
        print(f"\n■ {root}")
        if not root.is_dir():
            print("  폴더를 찾을 수 없어 건너뜁니다.")
            continue

        built = build_plan(root, recipe.steps, today=date.today(), run_id=run_id,
                           profiles_dir=repo_root() / "profiles")
        _print_plan(built, args.verbose)

        if not apply:
            continue

        result = execute(built)
        log = write_runlog(built, result)
        print(f"\n  완료. 처리 {len(result.done)} · 실패 {len(result.failed)}"
              f" · 건너뜀 {len(result.stale)}")
        print(f"  기록: {log}")
        for row in result.failed:
            print(f"    실패  {Path(row['src']).name} — {row['why']}")

    print()
    if apply:
        print("  되돌리려면:")
        print(f"      organize undo --root {roots[0]}")
    else:
        print("  실제로 실행하려면:")
        print(f"      organize run {args.recipe} --apply")
        if not args.verbose:
            print("\n  무엇이 어디로 가는지 전부 보려면:")
            print(f"      organize preview {args.recipe} --verbose")
    return 0


def _cmd_undo(args) -> int:
    recipes_dir = repo_root() / "recipes"
    if args.root:
        roots = [resolve_alias(args.root, load_config(repo_root()))]
    else:
        recipe = load_recipe(find_recipe(recipes_dir, args.recipe)) if args.recipe else None
        if recipe is None:
            raise OrganizeError("어느 폴더를 되돌릴지 알 수 없습니다.",
                                hint="organize undo --root @downloads 처럼 폴더를 지정해 주세요.")
        roots = _resolve_roots(recipe, None)

    for root in roots:
        result = undo_run(root, args.run_id)
        print(f"■ {root}")
        print(f"  되돌림 {len(result.done)} · 실패 {len(result.failed)}")
        for row in result.failed:
            print(f"    실패  {row['why']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="organize", description="파일 정리 자동화")
    p.add_argument("--version", action="version", version=f"organize {__version__}")
    sub = p.add_subparsers(dest="command")

    def add_common(sp):
        sp.add_argument("--root", help="레시피의 대상 폴더를 덮어씁니다 (@downloads 등)")
        sp.add_argument("--verbose", action="store_true", help="모든 항목을 나열합니다")

    sp = sub.add_parser("preview", help="미리보기 (파일을 건드리지 않음)")
    sp.add_argument("recipe")
    add_common(sp)
    sp.set_defaults(func=_cmd_preview)

    sp = sub.add_parser("run", help="실행")
    sp.add_argument("recipe")
    sp.add_argument("--apply", action="store_true", help="실제로 실행합니다")
    add_common(sp)
    sp.set_defaults(func=_cmd_run)

    sp = sub.add_parser("undo", help="되돌리기")
    sp.add_argument("run_id", nargs="?")
    sp.add_argument("--recipe")
    sp.add_argument("--root")
    sp.set_defaults(func=_cmd_undo)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)

    if not getattr(args, "func", None):
        parser.print_help()
        return 0

    try:
        return args.func(args)
    except OrganizeError as e:
        print(f"\n{e.message}")
        if e.hint:
            print(f"\n{e.hint}")
        return 1
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/ -v`
Expected: 전체 통과. `tests/test_cli_smoke.py` 의 옛 테스트 두 개(`no_args`, `unknown_command`)는
새 CLI 구조에 맞게 고친다 — 인자 없으면 도움말 출력 후 0, 없는 명령이면 argparse 가 2 를 돌려준다.

- [ ] **Step 5: 커밋**

```bash
git add organize/recipes.py organize/cli.py recipes/ tests/test_recipes.py tests/test_cli.py tests/test_cli_smoke.py
git commit -m "레시피와 CLI 추가 — preview / run --apply / undo 동작"
```

---

### Task 19: 나머지 명령 — doctor · paths · list · do

새 PC 에 앉았을 때 무엇이 부족한지 찾아다니지 않아도 되게 한다.

**Files:**
- Modify: `organize/cli.py`, `organize/userconfig.py` (`save_local_path` 추가)
- Test: `tests/test_cli_doctor.py`

**Interfaces:**
- Produces:
  - `organize.userconfig.save_local_path(repo_root: Path, name: str, value: str) -> None` — `config.local.json` 갱신
  - `organize.cli` 하위 명령 `doctor`, `paths`, `list`, `do`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_cli_doctor.py`:

```python
import json
from pathlib import Path

import pytest

from organize import cli, userconfig


@pytest.fixture
def project(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "profiles").mkdir(parents=True)
    (repo / "recipes").mkdir()
    (repo / "profiles" / "desktop.toml").write_text(
        'name = "테스트"\n[[rules]]\n to = "01_Docs"\n ext = [".pdf"]\n', encoding="utf-8")
    work = tmp_path / "작업"
    work.mkdir()
    import os, time
    a = work / "a.pdf"
    a.write_bytes(b"DATA")
    past = time.time() - 3600
    os.utime(a, (past, past))
    (repo / "recipes" / "t.json").write_text(json.dumps({
        "name": "테스트", "roots": ["@archive"],
        "steps": [{"block": "route", "profile": "desktop"}],
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cli, "repo_root", lambda: repo)
    monkeypatch.setattr(userconfig, "builtin_path", lambda name: work if name == "downloads" else None)
    return repo, work


def test_doctor_reports_python_and_folders(project, capsys):
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "Python" in out
    assert "다운로드" in out or "downloads" in out


def test_doctor_shows_file_counts(project, capsys):
    """경로 문자열만으로는 맞는 폴더인지 알 수 없다. 개수를 보여줘야 한다."""
    cli.main(["doctor"])
    assert "1" in capsys.readouterr().out


def test_doctor_warns_about_aliases_a_recipe_needs(project, capsys):
    cli.main(["doctor"])
    out = capsys.readouterr().out
    assert "archive" in out
    assert "organize paths --set" in out


def test_doctor_exit_code_is_zero_even_with_warnings(project):
    assert cli.main(["doctor"]) == 0


def test_paths_set_writes_local_config(project, tmp_path, capsys):
    repo, _ = project
    target = tmp_path / "보관"
    target.mkdir()
    assert cli.main(["paths", "--set", f"archive={target}"]) == 0
    saved = json.loads((repo / "config.local.json").read_text(encoding="utf-8"))
    assert saved["paths"]["archive"] == str(target)


def test_paths_set_rejects_bad_format(project):
    assert cli.main(["paths", "--set", "형식없음"]) == 1


def test_list_shows_recipes_and_profiles(project, capsys):
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "t" in out and "desktop" in out


def test_do_runs_one_block_as_preview(project, capsys):
    _, work = project
    assert cli.main(["do", "route", "--root", str(work), "--profile", "desktop"]) == 0
    out = capsys.readouterr().out
    assert "이동 1" in out
    assert (work / "a.pdf").exists()          # 미리보기이므로 그대로


def test_do_with_apply_moves(project):
    _, work = project
    assert cli.main(["do", "route", "--root", str(work), "--profile", "desktop", "--apply"]) == 0
    assert (work / "01_Docs" / "a.pdf").exists()


def test_do_only_filters_by_extension(project, capsys):
    _, work = project
    import os, time
    b = work / "b.png"
    b.write_bytes(b"IMG")
    past = time.time() - 3600
    os.utime(b, (past, past))
    cli.main(["do", "route", "--root", str(work), "--profile", "desktop", "--only", "*.pdf"])
    assert "이동 1" in capsys.readouterr().out
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_cli_doctor.py -v`
Expected: FAIL — `doctor` 하위 명령이 없어 argparse 가 종료 코드 2 를 돌려준다

- [ ] **Step 3: 최소 구현을 쓴다**

`organize/userconfig.py` 에 추가:

```python
def save_local_path(repo_root: Path, name: str, value: str) -> None:
    path = repo_root / "config.local.json"
    data = _read(path)
    data.setdefault("paths", {})[name] = value
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
```

`organize/cli.py` 에 추가 — 아래 함수들을 넣고 `build_parser()` 에 하위 명령을 등록한다:

```python
import sys as _sys
from organize.aliases import BUILTIN
from organize.core.scanner import scan
from organize.profiles import load_profile
from organize.recipes import Recipe
from organize.userconfig import AliasNotDefined, save_local_path

_ALIAS_LABEL = {"home": "홈", "desktop": "바탕화면", "downloads": "다운로드",
                "documents": "문서", "pictures": "사진", "music": "음악", "videos": "영상"}


def _count_files(path: Path) -> str:
    if not path.is_dir():
        return "없음!"
    try:
        return str(sum(1 for p in path.iterdir() if p.is_file()))
    except OSError:
        return "읽을 수 없음"


def _cmd_doctor(args) -> int:
    root = repo_root()
    cfg = load_config(root)

    print(f"  Python          {_sys.version.split()[0]:<18}"
          f"{'OK' if _sys.version_info >= (3, 11) else '3.11 이상이 필요합니다'}")
    try:
        import tkinter
        print(f"  tkinter         {tkinter.TkVersion:<18}OK")
    except ImportError:
        print("  tkinter         없음              선택  GUI 를 쓰려면 필요합니다")
    try:
        import PIL  # noqa: F401
        print("  Pillow          있음              OK   EXIF 촬영일을 읽습니다")
    except ImportError:
        print("  Pillow          없음              선택  EXIF 촬영일을 못 읽습니다.")
        print("                                        파일명과 수정시각으로 대체합니다.")
        print("                                        쓰려면: pip install Pillow")

    print("\n  폴더 위치")
    for name in BUILTIN:
        try:
            p = resolve_alias(f"@{name}", cfg)
        except AliasNotDefined:
            continue
        print(f"    {_ALIAS_LABEL.get(name, name):<10} {str(p):<44} 파일 {_count_files(p)}")
    for name in sorted(cfg.paths):
        p = resolve_alias(f"@{name}", cfg)
        print(f"    @{name:<9} {str(p):<44} 파일 {_count_files(p)}")

    recipes_dir = root / "recipes"
    names = list_recipes(recipes_dir)
    print(f"\n  레시피 {len(names)}개 · 프로파일 {len(list((root / 'profiles').glob('*.toml')))}개")

    missing: set[str] = set()
    for name in names:
        try:
            recipe = load_recipe(find_recipe(recipes_dir, name))
        except OrganizeError:
            continue
        for spec in recipe.roots:
            if not spec.startswith("@"):
                continue
            head = spec[1:].split("/")[0]
            if head not in BUILTIN and head not in cfg.paths:
                missing.add(head)

    if missing:
        print()
        for head in sorted(missing):
            print(f"  '@{head}' 위치가 정해져 있지 않습니다. 지정하려면:")
            print(f"      organize paths --set {head}=<경로>")
    return 0


def _cmd_paths(args) -> int:
    root = repo_root()
    if args.set:
        if "=" not in args.set:
            raise OrganizeError(f"형식이 올바르지 않습니다: {args.set}",
                                hint="organize paths --set archive=D:/보관  처럼 적어 주세요.")
        name, value = args.set.split("=", 1)
        save_local_path(root, name.strip(), value.strip())
        print(f"  @{name.strip()} → {value.strip()} 로 저장했습니다.")
        return 0

    cfg = load_config(root)
    for name in BUILTIN:
        print(f"  @{name:<10} {resolve_alias(f'@{name}', cfg)}")
    for name in sorted(cfg.paths):
        print(f"  @{name:<10} {resolve_alias(f'@{name}', cfg)}")
    print("\n  위치를 바꾸려면:")
    print("      organize paths --set <이름>=<경로>")
    return 0


def _cmd_list(args) -> int:
    root = repo_root()
    print("  레시피")
    for name in list_recipes(root / "recipes"):
        print(f"    {name}")
    print("\n  분류 설정")
    for p in sorted((root / "profiles").glob("*.toml")):
        print(f"    {p.stem}")
    print("\n  미리보려면:")
    print("      organize preview <레시피>")
    return 0


def _cmd_do(args) -> int:
    step: dict = {"block": args.block}
    if args.profile:
        step["profile"] = args.profile
    if args.layout:
        step["layout"] = args.layout
    if args.dest:
        step["dest"] = args.dest
    if args.only:
        step["when"] = {"ext": [Path(args.only).suffix.lower()]}

    recipe = Recipe(name=f"즉석 {args.block}", roots=[args.root], steps=[step])
    fake = argparse.Namespace(recipe=None, root=args.root, verbose=args.verbose,
                              apply=args.apply)
    return _run_recipe(recipe, fake, apply=bool(args.apply), label=args.block)
```

`_preview_or_run` 을 레시피 객체를 받는 `_run_recipe(recipe, args, *, apply, label)` 로 빼고,
`_cmd_preview` / `_cmd_run` / `_cmd_do` 가 모두 그것을 부르게 한다. `label` 은 마지막에
제안할 명령어 문구를 고르는 데만 쓴다 (`preview t` vs `do route --root ...`).

`build_parser()` 에 추가:

```python
    sp = sub.add_parser("doctor", help="환경 점검")
    sp.set_defaults(func=_cmd_doctor)

    sp = sub.add_parser("paths", help="폴더 위치 확인·지정")
    sp.add_argument("--set", help="이름=경로")
    sp.set_defaults(func=_cmd_paths)

    sp = sub.add_parser("list", help="레시피와 분류 설정 목록")
    sp.set_defaults(func=_cmd_list)

    sp = sub.add_parser("do", help="레시피 없이 작업 하나만 실행")
    sp.add_argument("block")
    sp.add_argument("--root", required=True)
    sp.add_argument("--profile")
    sp.add_argument("--layout")
    sp.add_argument("--dest")
    sp.add_argument("--only", help='확장자만 고릅니다. 예: "*.md"')
    sp.add_argument("--apply", action="store_true")
    sp.add_argument("--verbose", action="store_true")
    sp.set_defaults(func=_cmd_do)
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/ -v`
Expected: 전체 통과

- [ ] **Step 5: 커밋**

```bash
git add organize/cli.py organize/userconfig.py tests/test_cli_doctor.py
git commit -m "doctor · paths · list · do 명령 추가"
```

---

### Task 20: 실사용 검증 — 진짜 폴더에 돌려본다

여기까지는 전부 `tmp_path` 였다. 마지막으로 **실제 폴더**에 돌려 눈으로 확인한다.
이 태스크는 코드를 쓰지 않고 **확인만** 한다.

**Files:**
- Modify: `README.md` (실행 방법 갱신)

- [ ] **Step 1: 환경을 점검한다**

Windows 파이썬으로 실행한다. WSL 경유(`/mnt/c`)는 해시 계산이 수십 배 느리다.

```
PS> python -m organize doctor
```

확인할 것:
- Python 이 3.11 이상인가
- 폴더 위치의 **파일 개수**가 실제와 맞는가 (0 으로 뜨면 OneDrive 리디렉션을 의심한다)
- 정해지지 않은 별칭이 있으면 안내대로 지정한다

- [ ] **Step 2: 미리보기를 돌린다 — 파일은 그대로여야 한다**

```
PS> python -m organize preview downloads --verbose
```

확인할 것:
- 각 작업 옆의 건수가 납득되는가. `해당 없음` 이 뜨면 순서가 잘못된 것이다
- 근거 열이 "왜 이 파일이 여기로 가는지"를 설명하는가
- **탐색기에서 대상 폴더를 열어 아무것도 바뀌지 않았는지 확인한다**

- [ ] **Step 3: 안전한 곳에 복사해 실제로 실행해 본다**

진짜 다운로드 폴더에 바로 `--apply` 하지 않는다. 먼저 복사본에 돌린다.

```
PS> mkdir C:\Users\<사용자>\Desktop\정리테스트
PS> copy C:\Users\<사용자>\Downloads\* C:\Users\<사용자>\Desktop\정리테스트\
PS> python -m organize preview downloads --root C:\Users\<사용자>\Desktop\정리테스트
PS> python -m organize run downloads --apply --root C:\Users\<사용자>\Desktop\정리테스트
```

확인할 것:
- 미리보기에서 본 것과 실제 결과가 **정확히 같은가**
- `.organize/runs/<id>.json` 이 생겼는가
- 격리된 파일이 `.organize/trash/<id>/` 에 있는가

- [ ] **Step 4: 되돌려서 원래대로 오는지 확인한다**

```
PS> python -m organize undo --root C:\Users\<사용자>\Desktop\정리테스트
```

확인할 것:
- 파일이 전부 제자리로 돌아왔는가
- 비어버린 `01_Docs` 등이 사라졌는가
- 사용자가 직접 넣어둔 파일이 있는 폴더는 **남아 있는가**

- [ ] **Step 5: 진짜 폴더에 적용하고 README 를 갱신한다**

복사본에서 결과가 만족스러우면 실제 폴더에 적용한다.

```
PS> python -m organize preview downloads
PS> python -m organize run downloads --apply
```

`README.md` 의 "현재 상태" 를 갱신하고, 실제로 쓴 명령을 적는다.

- [ ] **Step 6: 커밋**

```bash
git add README.md
git commit -m "실사용 검증 완료 — README 갱신"
```
