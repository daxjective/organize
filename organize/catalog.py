"""작업 카탈로그 — 블록을 사람이 읽을 이름과 기본 설정으로 묶는다.

화면(GUI, 다음 Task)은 작업을 체크박스로 뿌릴 때 이 표만 본다. 값은
시안(`docs/superpowers/specs/2026-08-25-gui-design.md` 화면 2)에서 그대로
가져왔다 — 화면과 여기가 어긋나면 체크박스 문구와 실제 동작이 갈라진다.

**순서가 곧 실행 순서다.** 압축을 풀어야 그 안의 파일이 분류되고, 종류별로
02_Media 에 모은 다음에야 그 안에서 캡처와 사진이 갈리고, 사진 폴더가 생긴
다음에야 연도별로 나뉜다. `catalog()` 는 정렬하지 않는다 — 정렬하면 이 순서가
깨진다.
"""

import copy
from dataclasses import dataclass

from organize.errors import OrganizeError


@dataclass(frozen=True)
class CatalogEntry:
    id: str            # 화면이 체크 상태를 기억할 열쇠. 카탈로그 안에서 유일하다.
    label: str          # "압축 해제"
    summary: str        # 체크박스 오른쪽 회색 글씨 — 이 작업의 현재 설정 요약
    default_on: bool    # 처음 화면을 열었을 때 켜져 있는가
    step: dict          # build_plan 에 그대로 넘길 수 있는 step. {"block": ...} 포함.


# 원본은 이 파일 안에서만 산다. catalog()/by_id() 는 매번 이걸 얕게 복제한
# CatalogEntry 를 새로 만들어 돌려준다 — 아래 두 함수의 docstring 참고.
_ENTRIES: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        id="unzip", label="압축 해제", summary="원본은 남김", default_on=True,
        step={"block": "unzip"},
    ),
    CatalogEntry(
        id="empty_files", label="빈 파일 치우기", summary="0바이트만", default_on=True,
        step={"block": "empty_files"},
    ),
    CatalogEntry(
        id="dedup", label="중복 제거", summary="해시 기준", default_on=True,
        step={"block": "dedup"},
    ),
    CatalogEntry(
        id="route_kind", label="종류별 분류", summary="바탕화면·다운로드 규칙",
        default_on=True,
        step={"block": "route", "profile": "desktop"},
    ),
    CatalogEntry(
        id="route_photos", label="캡처·사진 분리", summary="02_Media",
        default_on=True,
        step={"block": "route", "profile": "photos", "target": "02_Media"},
    ),
    CatalogEntry(
        id="by_date_year", label="연도별 분류", summary="02_Media/사진",
        default_on=False,
        step={"block": "by_date", "target": "02_Media/사진", "layout": "{year}"},
    ),
)


def _copy(entry: CatalogEntry) -> CatalogEntry:
    # step 은 deepcopy 해서 돌려준다. 호출자가 받은 step 을 고쳐도(미리보기에서
    # target 을 바꿔보는 등) _ENTRIES 원본이나 다음 호출자가 오염되면 안 된다.
    # MappingProxyType 으로 아예 못 고치게 막는 방법도 있었지만, step 은 그대로
    # 레시피 JSON 으로 저장될 값이라 호출자가 진짜 dict 를 쥐고 있어야
    # json.dumps 등에 바로 쓸 수 있다 — 그래서 "못 고치게" 대신 "고쳐도 안전하게"
    # 를 골랐다.
    return CatalogEntry(id=entry.id, label=entry.label, summary=entry.summary,
                         default_on=entry.default_on, step=copy.deepcopy(entry.step))


def catalog() -> list[CatalogEntry]:
    """화면에 보일 순서대로 돌려준다. 정렬하지 않는다 — 순서가 곧 실행 순서다."""
    return [_copy(e) for e in _ENTRIES]


def by_id(entry_id: str) -> CatalogEntry:
    """id 로 하나를 찾는다. 모르는 id 면 파이썬 KeyError 대신 OrganizeError."""
    for e in _ENTRIES:
        if e.id == entry_id:
            return _copy(e)
    raise OrganizeError(
        f"'{entry_id}' 라는 작업은 카탈로그에 없습니다.",
        hint="쓸 수 있는 작업: " + ", ".join(e.id for e in _ENTRIES),
    )
