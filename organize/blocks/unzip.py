"""폴더 안의 zip 을 대상 폴더로 평탄화 해제한다.

두 가지를 기존 스크립트에 없던 대로 처리한다.

1. 한글 이름 복구 — 구형 Windows 압축 프로그램은 파일명을 cp949 로 저장하는데
   파이썬은 UTF-8 플래그가 없으면 cp437 로 읽는다. 되돌려서 cp949 로 다시 읽는다.
2. 경로 탈출 방어(zip slip) — 압축 안에 `../` 가 있으면 대상 폴더 밖에 파일을
   쓸 수 있다. `dst` 는 항상 `out_dir / leaf-name` 으로만 만들어 애초에
   폴더 구조를 쓰지 않으므로(평탄화) 실제로 밖에 쓰는 일은 없다. 그래도
   이름 자체에 `..` 가 섞여 있으면 그 항목만 명시적으로 거부하고 건너뛴다 —
   조용히 평탄화해 버리면 "탈출 시도가 있었다"는 사실이 미리보기에서 사라진다.
"""

import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from organize.blocks import BlockConfig, dest_folder
from organize.core.action import Action, Plan
from organize.core.context import Context
from organize.profiles import matches

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


def _member_mtime(info: zipfile.ZipInfo) -> float:
    """압축 안에 적힌 시각. 읽을 수 없으면 0 을 준다.

    zip 의 시각은 1980 년부터만 표현할 수 있고 값이 깨진 파일도 있다.
    그럴 때 예외를 내지 않고 0 을 주면 by_date 가 파일명으로 폴백한다.
    """
    try:
        return datetime(*info.date_time).timestamp()
    except (ValueError, OverflowError, OSError):
        return 0.0


def _unique(name: str, taken: set[str]) -> str:
    """이미 있는 이름이면 `_(1)` 을 붙인다.

    **대소문자를 구분하지 않고 본다.** 이 도구의 주 사용 환경은 윈도우이고,
    윈도우 파일 시스템은 `A.txt` 와 `a.txt` 를 같은 파일로 본다. 구분해서
    처리하면 압축 안에 둘 다 있을 때 하나가 다른 하나를 덮어써 사라진다.
    리눅스에서는 `_(1)` 이 하나 더 붙을 뿐 잃는 것이 없다.
    """
    if name.casefold() not in taken:
        return name
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 1
    while f"{stem}_({n}){suffix}".casefold() in taken:
        n += 1
    return f"{stem}_({n}){suffix}"


def build(ctx: Context, cfg: BlockConfig) -> Plan:
    plan = Plan()
    out_dir = dest_folder(ctx, cfg.out, block=BLOCK) if cfg.out else ctx.root
    taken = {e.path.name.casefold() for e in ctx.files_at(cfg.out)}

    extracts: list[Action] = []
    quarantines: list[Action] = []

    for entry in ctx.files_at(cfg.target):
        if entry.ext != ".zip" or entry.virtual:
            continue
        # 다른 블록과 똑같이 `when` 을 받는다. 여기만 조용히 무시하면
        # 레시피에 `when` 을 써 놓고 왜 안 걸리는지 알 길이 없다.
        if cfg.when and not matches(entry, cfg.when, ctx.today):
            plan.skipped.append((entry.path, "이 작업의 대상이 아님"))
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
            # 이후 판정은 전부 이 정규화된 이름으로 한다 — recover_name 이 되살린
            # 결과와, 드물게 섞여 드는 백슬래시 구분자를 슬래시로 맞춰야 ".." 판정과
            # leaf 계산이 같은 이름을 보게 된다.
            name = recover_name(info.filename, info.flag_bits).replace("\\", "/")
            parts = PurePosixPath(name).parts
            leaf = PurePosixPath(name).name
            if not leaf:
                plan.skipped.append((entry.path, "압축 안 항목 이름이 비어 있음"))
                continue
            if leaf in (".", "..") or ".." in parts:
                plan.skipped.append(
                    (entry.path, f"압축 안의 경로가 대상 폴더를 벗어남: {name}"))
                continue
            final = _unique(leaf, taken)
            taken.add(final.casefold())
            extracts.append(Action(
                kind="extract", src=src, dst=out_dir / final,
                reason=f"{entry.name} 에서 꺼냄", block=BLOCK,
                member=info.filename,          # 실행기가 이 원래 이름으로 꺼낸다
                size=info.file_size,           # 뒤 블록이 볼 가상 엔트리의 크기
                mtime=_member_mtime(info),     # 없으면 by_date 가 1970 으로 보낸다
            ))
            extracted += 1

        if extracted and cfg.options.get("delete_original", False):
            quarantines.append(Action(
                kind="quarantine", src=src, dst=ctx.trash_dir / entry.name,
                reason=f"압축을 푼 원본 ({extracted}개 꺼냄)", block=BLOCK,
            ))

    if extracts and cfg.out:          # 기본값(out_dir == ctx.root)은 이미 있다
        plan.actions.append(Action(
            kind="mkdir", src=None, dst=out_dir,
            reason="압축 해제 결과를 담을 폴더", block=BLOCK))
    plan.actions.extend(extracts)
    plan.actions.extend(quarantines)
    return plan
