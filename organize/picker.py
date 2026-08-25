"""폴더를 탐색기에서 고른다.

**창을 띄우는 일과 저장하는 일을 나눈다.** 저장하는 쪽은 창 없이 테스트한다.

`tkinter` 는 파이썬 표준 라이브러리지만 **항상 있는 것은 아니다** — 리눅스에서는
별도 패키지(`python3-tk`)이고, 없는 환경에서 import 하면 죽는다. 그래서 이
모듈은 함수 안에서 늦게 import 하고, 없으면 한국어로 안내한다.
**CLI 의 나머지 기능은 tkinter 없이도 그대로 돌아야 한다.**
"""

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
