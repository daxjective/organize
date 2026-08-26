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
    # 앞서 나온 **다른 이름**이 이미 같은 폴더를 가리키는가. 그 이름이 들어 있다.
    # 개수와 대상 목록에서는 빼되(같은 폴더를 두 번 셀 이유가 없다), 화면 3 은
    # 이 값을 보고 "다운로드 와 같은 폴더입니다" 라고 **말할 수 있어야 한다** —
    # 아무 말 없이 줄이 사라지면 [기본 위치로] 까지 같이 사라져 창만으로는
    # 되돌릴 방법이 없다.
    hidden_duplicate_of: str | None = None


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


def visible(infos: list[FolderInfo]) -> list[FolderInfo]:
    """개수를 세고 대상 목록을 만들 때 쓸 줄만.

    같은 폴더를 가리키는 두 이름을 두 줄로 세면 "설정이 두 벌인가" 로 읽힌다.
    **거르는 규칙도 여기 한 곳이다** — 화면 3 만은 거르지 않고 전부 받아
    "왜 여기 안 보이는지" 를 말한다.
    """
    return [f for f in infos if f.hidden_duplicate_of is None]


def overview(cfg: UserConfig) -> list[FolderInfo]:
    """내장 별칭 → 사용자가 등록한 이름(가나다순) 순서로 훑는다.

    **`doctor` 와 같은 순서다.** 두 화면이 같은 것을 다른 순서로 보여주면
    사용자는 같은 목록을 보고 있다고 믿지 못한다.

    **아무 줄도 버리지 않는다.** 예전에는 두 가지를 조용히 건너뛰었고, 둘 다
    실측한 결함이 됐다.

      · 안 풀리는 이름 — 손편집 설정의 `{"desktop": ["@desktop"]}` 같은 순환
        별칭이면 바탕화면 줄이 화면 1·화면 3·대상 드롭다운에서 아무 말 없이
        사라졌다. [다시 지정] 버튼까지 같이 사라져 창만으로는 고칠 수 없었다.
        → `status=UNRESOLVED` + `problem` 을 달아 돌려준다.
      · 같은 폴더를 가리키는 뒤엣 이름 — 화면 3 의 [다시 지정] 으로 '문서' 를
        다운로드와 같은 폴더로 고르면 '문서' 줄이 세 곳 모두에서 사라지고,
        [기본 위치로] 도 같이 사라져 되돌릴 방법이 없었다.
        → `hidden_duplicate_of` 를 달아 돌려준다.

    **거르는 것은 부르는 쪽의 몫이다**(`visible()`). 여기서 빼 버리면 "왜 안
    보이는지" 를 아무도 말할 수 없다.
    """
    out: list[FolderInfo] = []
    먼저본것: dict[Path, FolderInfo] = {}
    # 내장 이름을 사용자가 등록하면 아래 목록에 **두 번** 들어온다. 그건 같은
    # 줄이므로 두 번 그리지 않는다(같은 폴더를 가리키는 **다른** 이름과 다르다).
    이름본것: set[str] = set()

    for name in (*BUILTIN, *sorted(cfg.paths)):
        if name in 이름본것:
            continue
        이름본것.add(name)
        label = LABEL.get(name, name)
        try:
            path = resolve_alias(f"@{name}", cfg)
        except AliasNotDefined as e:
            # 어디를 가리키는지 모르므로 경로 자리에는 이름 그대로를 적는다.
            out.append(FolderInfo(name=name, label=label, path=Path(f"@{name}"),
                                  count=None, status=UNRESOLVED,
                                  builtin=name in BUILTIN, problem=e.message))
            continue
        먼저 = 먼저본것.get(path)
        if 먼저 is not None:
            # 같은 폴더다 — 개수를 다시 셀 이유가 없다. 먼저 센 값을 그대로 쓴다.
            out.append(FolderInfo(name=name, label=label, path=path,
                                  count=먼저.count, status=먼저.status,
                                  builtin=name in BUILTIN,
                                  hidden_duplicate_of=먼저.name))
            continue
        count, status = count_files(path)
        info = FolderInfo(name=name, label=label, path=path, count=count,
                          status=status, builtin=name in BUILTIN)
        먼저본것[path] = info
        out.append(info)
    return out
