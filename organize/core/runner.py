"""블록을 순서대로 엮어 하나의 Plan 으로 모은다.

블록끼리는 서로를 모른다. 앞 블록의 결과는 Context 를 통해서만 전달된다.
따라서 순서를 바꾸면 뒤 블록의 대상이 바뀌고, 때로는 0건이 된다.
그것이 정상 동작이며, 사용자에게 건수를 보여줘 알아채게 한다.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from organize.blocks import BLOCK_OPTIONS, BlockConfig, get_block
from organize.core.action import Plan
from organize.core.context import Context
from organize.core.scanner import FileEntry, scan
from organize.errors import OrganizeError
from organize.profiles import CONDITION_KEYS, load_profile, normalize_conditions

_RESERVED = {"block", "target", "dest", "when"}


@dataclass
class BuiltPlan:
    root: Path
    run_id: str
    plan: Plan
    # Action 마다 "원래 어느 파일에서 나온 것인가". **plan.actions 와 길이·순서가
    # 같다.** 화면이 미리보기 표의 체크박스를 파일 단위로 묶는 데 쓴다 — 사슬로
    # 두 번 옮겨지는 파일은 `Action.src` 가 중간 경로라서 그것만으로는 못 묶는다.
    # **스캐너가 실제로 본 파일만** 가리킨다. 어느 파일 것도 아닌 mkdir 과,
    # 이 계획이 앞으로 만들어 낼 파일(압축에서 나올 것)은 None 이다 — 아직
    # 없는 파일은 빼 달라고 해도 뺄 수가 없으므로 체크박스를 주면 거짓말이 된다.
    origins: list[Path | None] = field(default_factory=list)
    # (블록 이름, 그 블록이 만든 Action 수). **파일 개수가 아니다** — mkdir 도
    # 하나로 센다. 화면에 "route 2건" 을 그냥 내보내면 "파일 2개 옮김" 으로
    # 읽힌다(실제로는 폴더 1 + 파일 1 인 경우가 있다). 보여줄 때는 kind 별로
    # 나눠 세야 한다.
    per_block: list[tuple[str, int]] = field(default_factory=list)
    snapshot: dict[str, tuple[int, float]] = field(default_factory=dict)
    # prepare_runlog 이 실제로 잡은 실행 기록 경로. run_id 가 겹쳐 `-2` 로 비켜
    # 갔을 수 있으므로 write_runlog 은 반드시 이 경로에 써야 한다 — 어긋나면
    # 준비한 자리와 결과를 쓴 자리가 달라져 남의 기록을 덮어쓴다.
    runlog_path: Path | None = None
    # 정리 대상 폴더 **밖**인데 사용자가 등록해서 허락한 곳들(백업 대상).
    # 실행기가 "밖으로 나가면 막는다" 를 판정할 때 이 목록을 예외로 본다.
    # 계획 단계(dest_folder)와 실행 단계(_guard_destination)가 **같은 목록**을
    # 봐야 한다 — 어긋나면 계획은 세워지는데 실행에서 막혀 미리보기가 거짓말이 된다.
    external: list[Path] = field(default_factory=list)


def make_run_id(now: datetime) -> str:
    return now.strftime("%Y%m%d-%H%M%S")


def _check_keys(step: dict, block_name: str, order: int) -> None:
    """레시피에 적힌 이름 중 모르는 것이 있으면 거부한다.

    **조용히 무시하면 안 된다.** `when` 을 `whne` 로 잘못 쓰면 그 값이 무해한
    옵션으로 흡수되고 필터는 사라진다. 실측했다 — "pdf 만 정리해줘" 라고 쓴
    레시피가 사진까지 전부 옮겼다. 오류도 안 난다.
    """
    allowed = _RESERVED | set(BLOCK_OPTIONS.get(block_name, ()))
    unknown = sorted(set(step) - allowed)
    if unknown:
        raise OrganizeError(
            f"{order}번째 작업('{block_name}')에 모르는 항목이 있습니다: "
            + ", ".join(unknown),
            hint=f"'{block_name}' 에 쓸 수 있는 항목: " + ", ".join(sorted(allowed)),
        )

    bad = sorted(set(step.get("when") or {}) - CONDITION_KEYS)
    if bad:
        raise OrganizeError(
            f"{order}번째 작업의 'when' 에 모르는 조건이 있습니다: " + ", ".join(bad),
            hint="쓸 수 있는 조건: " + ", ".join(sorted(CONDITION_KEYS)),
        )

    # 키만 보고 값을 안 보면 `name_contains = "report"`(대괄호 누락) 하나가
    # 필터를 "전부 일치" 로 뒤집고, `name_regex` 오타 하나가 실행 도중
    # re.error 로 터진다. 파일을 하나도 건드리기 전인 여기서 막는다.
    normalize_conditions(step.get("when") or {},
                         f"{order}번째 작업('{block_name}')의 'when'")


def _to_config(step: dict, profiles_dir: Path, block_name: str,
               order: int) -> BlockConfig:
    _check_keys(step, block_name, order)
    options = {k: v for k, v in step.items() if k not in _RESERVED}
    if "profile" in options:
        options["profile"] = load_profile(profiles_dir / f"{options['profile']}.toml")
    return BlockConfig(
        target=step.get("target", ""),
        dest=step.get("dest"),
        # 정규화한 값을 넘긴다 — 검사만 하고 원본을 넘기면 검사와 실제 동작이
        # 갈라진다.
        when=normalize_conditions(step.get("when", {}) or {},
                                  f"{order}번째 작업('{block_name}')의 'when'"),
        options=options,
    )


def external_names(steps: list[dict]) -> list[str]:
    """레시피가 밖으로 내보내려는 이름들(`dest: "@백업"`)을 모은다.

    부르는 쪽이 이 이름들을 설정에서 풀어 `build_plan(external=...)` 로 넘긴다.
    러너가 직접 설정을 읽지 않는 이유는, 계획을 세우는 일과 이 PC 의 설정을
    읽는 일이 다른 관심사이기 때문이다(테스트도 설정 없이 돌아야 한다).
    """
    names: list[str] = []
    for step in steps:
        dest = step.get("dest")
        if isinstance(dest, str) and dest.startswith("@"):
            name = dest[1:].partition("/")[0]
            if name and name not in names:
                names.append(name)       # 순서 유지 — 결정적이어야 한다
    return names


def _origin(ctx: Context, src: Path | None, on_disk: set[Path]) -> Path | None:
    """이 동작이 나온 원본 파일. mkdir(=src 없음)과 계획이 만들 파일은 None."""
    if src is None:
        return None
    origin = ctx.origin_of(src)
    return origin if origin in on_disk else None


def build_plan(root: Path, steps: list[dict], *, today: date, run_id: str,
               profiles_dir: Path, now: float | None = None,
               external: dict[str, Path] | None = None,
               exclude: set[Path] | None = None) -> BuiltPlan:
    """`exclude` 는 이번 실행에서 뺄 파일들의 절대경로(스캔했을 때의 경로).

    **만들어진 Plan 에서 동작을 골라내지 않는다. 계획을 처음부터 다시 세운다.**
    골라내면 세 가지가 깨진다. ① 그 폴더로 갈 파일을 다 뺐는데 mkdir 이 남아
    **빈 폴더**가 생긴다. ② `보고서_(1).pdf` 는 앞 파일이 `보고서.pdf` 를
    차지했기 때문에 붙은 이름인데, 앞 것을 빼도 **이름이 그대로 남는다**.
    ③ 한 파일을 두 번 옮기는 사슬에서 중간을 빼면 뒤 동작의 `src` 가 있지도
    않은 경로를 가리킨다. 그래서 뺀 파일은 **블록이 아예 못 보게** 한다.
    """
    # 하위 폴더까지 읽는다. dedup 이 참고해야 하기 때문이다.
    # files_at("") 은 직속만 돌려주므로 하위 폴더 파일이 함부로 옮겨지지는 않는다.
    scanned = scan(root, recursive=True, now=now)
    entries = scanned.entries
    dropped: list[FileEntry] = []
    if exclude:
        entries = [e for e in scanned.entries if e.path not in exclude]
        dropped = [e for e in scanned.entries if e.path in exclude]
    # 스캐너가 **실제로 본** 파일들. origin 은 이 안에 있는 것만 인정한다 —
    # 아래 origins 주석 참고.
    on_disk = {e.path for e in entries}
    ctx = Context(root=root, entries=entries, today=today, run_id=run_id,
                  external=external)

    built = BuiltPlan(root=root, run_id=run_id, plan=Plan(),
                      external=sorted(set((external or {}).values()), key=str))
    built.plan.skipped.extend(scanned.skipped)
    # 뺀 파일이 **조용히 사라지면 안 된다.** 화면의 "손대지 않음" 숫자에 잡혀야
    # 사용자가 자기가 뺀 것을 확인할 수 있다.
    built.plan.skipped.extend((e.path, "제외함") for e in dropped)
    built.snapshot = {str(e.path): (e.size, e.mtime) for e in entries}

    for i, step in enumerate(steps, start=1):
        # step["block"] 을 바로 읽으면 이 키가 아예 없을 때 파이썬 KeyError 가
        # 그대로 사용자에게 노출된다 — 레시피는 사람이 손으로 쓰므로 실제로
        # 빠뜨릴 수 있는 실수다. 전역 규칙(예외를 그대로 보여주지 않는다)에 따라
        # 여기서 먼저 한국어 오류로 바꾼다.
        if "block" not in step:
            raise OrganizeError(
                f"{i}번째 작업에 'block' 이 없습니다.",
                hint="각 단계는 {'block': '작업이름', ...} 형태로 적어야 합니다. "
                     "쓸 수 있는 작업: unzip, dedup, route, by_date",
            )
        block_name = step["block"]
        fn = get_block(block_name)
        sub = fn(ctx, _to_config(step, profiles_dir, block_name, i))
        # **ctx.apply 보다 먼저 물어야 한다.** apply 가 옛 경로를 장부에서
        # 지우므로, 뒤에 물으면 두 번째 이동부터 origin 이 전부 None 이 된다.
        #
        # `on_disk` 로 한 번 거르는 이유: 압축에서 나올 파일처럼 **이 계획이
        # 만들어 낼 파일**은 아직 디스크에 없다. 그 경로로 exclude 를 걸어도
        # 스캔 결과에 없으니 아무 일도 안 일어난다 — 그대로 두면 화면에
        # **눌러도 아무 일 없는 체크박스**가 생긴다(실측했다). 열쇠를 안 주면
        # 창은 폴더 생성 줄처럼 체크박스 없이 그린다. 압축 안의 파일을 빼고
        # 싶으면 그 zip 의 체크를 끄면 된다.
        built.origins.extend(
            _origin(ctx, a.src, on_disk) for a in sub.actions)
        ctx.apply(sub)
        built.plan.extend(sub)
        built.per_block.append((block_name, len(sub.actions)))

    return built
