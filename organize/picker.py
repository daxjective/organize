"""폴더를 탐색기에서 고르고, 탐색기로 연다.

**창을 띄우는 일과 저장하는 일을 나눈다.** 저장하는 쪽은 창 없이 테스트한다.

`tkinter` 는 파이썬 표준 라이브러리지만 **항상 있는 것은 아니다** — 리눅스에서는
별도 패키지(`python3-tk`)이고, 없는 환경에서 import 하면 죽는다. 그래서 이
모듈은 함수 안에서 늦게 import 하고, 없으면 한국어로 안내한다.
**CLI 의 나머지 기능은 tkinter 없이도 그대로 돌아야 한다.**

폴더를 **여는** 일(`open_folder`)은 tkinter 와 무관하다 — OS 의 파일 탐색기를
부르는 것뿐이라, 창이 없는 파이썬에서도 된다.
"""

import os
import platform
import subprocess
from pathlib import Path

from organize.errors import OrganizeError


def can_open_window() -> bool:
    """이 파이썬에서 창을 띄울 수 있는가."""
    try:
        import tkinter                                    # noqa: F401
    except Exception:
        return False
    return True


def _no_window_error(what: str) -> OrganizeError:
    return OrganizeError(
        f"이 파이썬에서는 {what} 창을 띄울 수 없습니다 (tkinter 없음).",
        hint="윈도우 파이썬에는 기본으로 들어 있습니다. "
             "리눅스라면 'sudo apt install python3-tk' 로 설치하세요.\n"
             "    창 없이 직접 적으려면: organize paths --set <이름>=<경로>")


def ask_folder(title: str = "폴더 고르기", start: Path | None = None) -> Path | None:
    """탐색기를 띄워 폴더 하나를 고르게 한다. 취소하면 None.

    창을 띄우는 유일한 자리다. 부르는 쪽은 결과 경로만 받는다.
    """
    try:
        import tkinter
        from tkinter import filedialog
    except Exception as e:
        raise _no_window_error("폴더 고르기") from e

    root = tkinter.Tk()
    root.withdraw()                    # 빈 본창은 보이지 않게
    root.attributes("-topmost", True)  # 탐색기가 뒤에 숨지 않게
    try:
        chosen = filedialog.askdirectory(
            title=title,
            initialdir=str(start) if start and Path(start).is_dir() else None,
            mustexist=True)
    finally:
        root.destroy()
    return Path(chosen) if chosen else None


def store_picked_path(repo_root: Path, name: str, folder: Path) -> Path:
    """고른 폴더를 이름표로 저장한다. **창 없이 테스트되는 부분이다.**

    저장 자체는 `userconfig.save_local_path` 가 한다. 여기서 하는 일은
    "고른 것이 정말 쓸 수 있는 폴더인가" 를 확인하는 것이다 — 창에서 골랐다고
    해서 그 사이에 뽑히지 않았다는 보장은 없다(USB·SD카드).
    """
    from organize.userconfig import save_local_path

    if not name or not name.strip():
        raise OrganizeError("이름이 비어 있습니다.",
                            hint="organize paths --pick 백업  처럼 이름을 적어 주세요.")
    folder = Path(folder)
    if not folder.is_dir():
        raise OrganizeError(
            f"고른 폴더를 찾을 수 없습니다: {folder}",
            hint="USB·SD카드라면 뽑히지 않았는지 확인하고 다시 골라 주세요.")
    save_local_path(repo_root, name.strip(), str(folder))
    return folder


# ── 폴더를 탐색기로 열기 ─────────────────────────────────────────
# 화면 1·3 의 경로 글자를 눌렀을 때 쓴다. **경로가 맞는지는 열어 봐야 안다** —
# `C:\Users\...\Desktop` 이라고 적혀 있어도 그게 내가 아는 그 바탕화면인지는
# 글자만으로 알 수 없다(OneDrive 백업이 켜진 PC 에서는 다른 곳이다).
# 여기는 tkinter 와 무관하다. 창이 없는 파이썬에서도 된다.


def is_wsl() -> bool:
    """WSL(윈도우 안의 리눅스) 인가.

    개발은 WSL 에서 하지만 **실사용은 윈도우 파이썬**이다(README). WSL 의
    `xdg-open` 은 리눅스 파일 관리자를 찾으므로, 여기서는 윈도우 탐색기를
    직접 부른다 — 안 그러면 링크를 눌러도 아무 일이 없다.
    """
    return "microsoft" in platform.release().lower()


def open_command(system: str, *, wsl: bool = False) -> list[str]:
    """폴더를 여는 명령의 **앞부분**. 뒤에 경로를 붙여 쓴다.

    윈도우 파이썬은 여기를 지나지 않는다 — `os.startfile` 이 있다. `explorer`
    는 **성공해도 종료 코드 1** 을 돌려주기 때문에, 명령으로 부르면 열렸는지
    안 열렸는지 구별할 방법이 없다.
    """
    if wsl:
        return ["explorer.exe"]
    return ["open"] if system == "Darwin" else ["xdg-open"]


def _windows_path(folder: Path) -> str:
    """WSL 경로를 윈도우 탐색기가 아는 형태로. 못 바꾸면 원래 글자를 그대로 준다."""
    try:
        done = subprocess.run(["wslpath", "-w", str(folder)],
                              capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return str(folder)
    return done.stdout.strip() or str(folder)


def _cannot_open(folder: Path) -> OrganizeError:
    """열지 못했을 때. **경로를 같이 적는다** — 손으로라도 갈 수 있어야 한다."""
    return OrganizeError(
        f"탐색기로 열지 못했습니다: {folder}",
        hint="이 PC 에 폴더를 여는 프로그램이 없을 수 있습니다.\n"
             f"    아래 경로를 직접 복사해 쓰세요:\n    {folder}")


def open_folder(folder: Path) -> None:
    """이 PC 의 파일 탐색기로 폴더를 연다. 못 열면 **한국어로** 알린다.

    **없는 폴더는 열지 않는다.** 부르는 쪽(창)이 이미 열 수 없는 줄을 링크로
    만들지 않지만, 그 사이에 USB 가 뽑혔을 수 있다.
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise OrganizeError(
            f"폴더를 찾을 수 없습니다: {folder}",
            hint="USB·SD카드라면 뽑히지 않았는지 확인하고, "
                 "[설정 · 폴더 위치] 에서 다시 지정해 주세요.")

    startfile = getattr(os, "startfile", None)
    if startfile is not None:                        # 윈도우 파이썬
        try:
            startfile(str(folder))
            return
        except OSError as e:
            raise _cannot_open(folder) from e

    wsl = is_wsl()
    cmd = [*open_command(platform.system(), wsl=wsl),
           _windows_path(folder) if wsl else str(folder)]
    try:
        # 기다리지 않는다 — 탐색기가 뜨는 동안 창이 멈추면 고장으로 읽힌다.
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, ValueError) as e:
        raise _cannot_open(folder) from e


def reveal_command(system: str, *, wsl: bool = False) -> list[str]:
    """그 파일을 **골라서** 여는 명령의 앞부분.

    윈도우 탐색기는 `/select,` 로 파일 하나를 지목할 수 있다. 파일을 여는
    것이 아니라 **가리키기만** 하므로 실행되지 않는다 — 다운로드 폴더의 중복
    `.exe` 를 확인하려다 설치 프로그램이 뜨면 안 된다.

    맥·리눅스에는 같은 일을 시키는 표준이 없다. 그쪽은 부모 폴더를 연다
    (`reveal_file` 이 경로를 폴더로 바꿔 넘긴다).
    """
    if wsl:
        return ["explorer.exe", "/select,"]
    if system == "Windows":
        return ["explorer", "/select,"]
    return ["open"] if system == "Darwin" else ["xdg-open"]


def reveal_file(path: Path) -> None:
    """탐색기를 열어 그 파일을 가리킨다. **파일을 실행하지 않는다.**

    `open_folder` 와 달리 `os.startfile` 을 쓰지 않는다 — 그것은 파일을 **연다**.
    윈도우에서도 `explorer /select,` 를 직접 부른다.
    """
    path = Path(path)
    if path.is_dir():
        raise OrganizeError(
            f"폴더는 이 방법으로 열 수 없습니다: {path}",
            hint="폴더를 열 때는 폴더 이름 쪽 링크를 눌러 주세요.")
    if not path.is_file():
        raise OrganizeError(
            f"파일을 찾을 수 없습니다: {path}",
            hint="이미 옮겨졌거나 지워졌을 수 있습니다. [미리보기] 를 다시 눌러 주세요.")

    wsl = is_wsl()
    앞 = reveal_command(platform.system(), wsl=wsl)
    if 앞[-1] == "/select,":
        cmd = [*앞, _windows_path(path) if wsl else str(path)]
    else:
        # 고를 수 없는 OS — 부모 폴더를 연다. 아무 일도 안 하는 것보다 낫다.
        cmd = [*앞, str(path.parent)]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, ValueError) as e:
        raise OrganizeError(
            f"탐색기를 열지 못했습니다: {path}",
            hint="파일이 있는 폴더를 직접 열어 확인해 주세요.") from e
