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


def _unique(name: str, taken: set[str]) -> str:
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

    extracts: list[Action] = []
    quarantines: list[Action] = []

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
            # 이후 판정은 전부 이 정규화된 이름으로 한다 — recover_name 이 되살린
            # 결과와, 드물게 섞여 드는 백슬래시 구분자를 슬래시로 맞춰야 ".." 판정과
            # leaf 계산이 같은 이름을 보게 된다.
            name = recover_name(info.filename, info.flag_bits).replace("\\", "/")
            parts = PurePosixPath(name).parts
            leaf = PurePosixPath(name).name
            if not leaf or leaf in (".", "..") or ".." in parts:
                plan.skipped.append(
                    (entry.path, f"압축 안의 경로가 대상 폴더를 벗어남: {name}"))
                continue
            final = _unique(leaf, taken)
            taken.add(final)
            extracts.append(Action(
                kind="extract", src=src, dst=out_dir / final,
                reason=f"{entry.name} 에서 꺼냄", block=BLOCK,
                member=info.filename,          # 실행기가 이 원래 이름으로 꺼낸다
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
