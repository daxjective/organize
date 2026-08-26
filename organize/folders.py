"""등록된 폴더들의 **개수 한 장**. `doctor`(명령줄)와 화면 1(창)이 같이 본다.

이 파일이 있는 이유는 하나다 — 개수를 세는 코드와 이름표 표가 **두 벌이 되지
않게** 하려는 것. 두 벌이 되면 한쪽만 고쳐지고, 그때부터 명령줄과 창이 서로
다른 숫자를 말한다. 사용자는 어느 쪽이 맞는지 알 방법이 없다.

여기는 창을 모른다(tkinter 를 import 하지 않는다). 그래서 창 없이 테스트된다.
"""

from dataclasses import dataclass
from pathlib import Path

from organize.aliases import BUILTIN
from organize.userconfig import AliasNotDefined, UserConfig, resolve_alias

# 내장 별칭의 한국어 이름표. `doctor` 도 화면도 이 표만 본다.
LABEL = {"home": "홈", "desktop": "바탕화면", "downloads": "다운로드",
         "documents": "문서", "pictures": "사진", "music": "음악", "videos": "영상"}

# 폴더가 아예 없을 때 `doctor` 가 찍어 온 글자. "파일 0" 과 헷갈리지 않게
# 앞에 '—' 를 붙인다 — 이 문장은 사용자가 이미 보던 것이라 바꾸지 않는다.
_NO_FOLDER_TEXT = "— 폴더 없음"

# 이름이 **아예 안 풀리는** 줄의 status. "폴더 없음"(어디인지는 아는데 그
# 폴더가 없다)과 다른 일이라 글자를 따로 둔다. 창이 이 값을 보고 빨갛게 칠한다.
UNRESOLVED = "위치를 확인할 수 없습니다"


@dataclass(frozen=True)
class FolderInfo:
    name: str            # "desktop" 또는 사용자가 등록한 이름
    label: str           # "바탕화면" — LABEL 에 없으면 name 그대로
    path: Path
    count: int | None    # 파일 개수. 폴더가 없거나 못 읽으면 None
    status: str          # "" · "폴더 없음" · "읽을 수 없음" · UNRESOLVED
    builtin: bool        # 내장 별칭인가
    # 이름이 안 풀린 이유(한국어 한 줄). UNRESOLVED 인 줄에만 들어 있다.
    # 화면이 그대로 보여 준다 — "확인할 수 없습니다" 만으로는 무엇을 고쳐야
    # 할지 알 수 없기 때문이다.
    problem: str = ""


def count_files(path: Path) -> tuple[int | None, str]:
    """그 폴더 **바로 아래의 파일** 개수. 하위 폴더 안까지는 세지 않는다.

    개수를 못 센 이유를 숫자에 섞지 않는다 — "0" 과 "폴더가 없다" 는 사용자에게
    전혀 다른 뜻이다(OneDrive 백업이 켜진 PC 에서는 이 구분이 곧 답이다).
    """
    if not path.is_dir():
        return None, "폴더 없음"
    try:
        return sum(1 for p in path.iterdir() if p.is_file()), ""
    except OSError:
        return None, "읽을 수 없음"


def count_text(path: Path) -> str:
    """`doctor` 가 "파일 {여기}" 로 이어 붙여 찍는 글자."""
    count, status = count_files(path)
    if count is not None:
        return str(count)
    return _NO_FOLDER_TEXT if status == "폴더 없음" else status


def overview(cfg: UserConfig) -> list[FolderInfo]:
    """내장 별칭 → 사용자가 등록한 이름(가나다순) 순서로 훑는다.

    **`doctor` 와 같은 순서다.** 두 화면이 같은 것을 다른 순서로 보여주면
    사용자는 같은 목록을 보고 있다고 믿지 못한다.

    같은 경로가 두 번 나오면 뒤엣것은 넣지 않는다 — `@photos` 가 사진 폴더를
    가리킬 때 같은 폴더를 두 줄로 셀 이유가 없다.

    **안 풀리는 이름도 줄로 남긴다.** 예전에는 조용히 건너뛰었다. 손편집 설정에
    `{"desktop": ["@desktop"]}` 같은 순환 별칭이 들어가면 바탕화면 줄이 화면
    1·화면 3·대상 드롭다운에서 **아무 말 없이 사라졌고**, 그 줄이 사라지면서
    [다시 지정] 버튼까지 같이 사라져 창만으로는 고칠 방법이 없었다. 실측한 결함이다.
    """
    out: list[FolderInfo] = []
    seen: set[Path] = set()
    # 내장 이름을 사용자가 등록하면 아래 목록에 **두 번** 들어온다. 풀리는 줄은
    # `seen`(경로)이 걸러 주지만, 안 풀리는 줄은 경로가 없어 그냥 두면 같은
    # 이름이 두 줄로 나온다.
    이름본것: set[str] = set()

    for name in (*BUILTIN, *sorted(cfg.paths)):
        if name in 이름본것:
            continue
        이름본것.add(name)
        try:
            path = resolve_alias(f"@{name}", cfg)
        except AliasNotDefined as e:
            # 어디를 가리키는지 모르므로 경로 자리에는 이름 그대로를 적는다.
            out.append(FolderInfo(name=name, label=LABEL.get(name, name),
                                  path=Path(f"@{name}"), count=None,
                                  status=UNRESOLVED, builtin=name in BUILTIN,
                                  problem=e.message))
            continue
        if path in seen:
            continue
        seen.add(path)
        count, status = count_files(path)
        out.append(FolderInfo(name=name, label=LABEL.get(name, name), path=path,
                              count=count, status=status, builtin=name in BUILTIN))
    return out
