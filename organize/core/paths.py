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
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise OrganizeError(
            f"대상 폴더를 만들지 못했습니다: {dst.parent}",
            hint="상위 폴더의 쓰기 권한을 확인해 주세요.",
        ) from e
    final = unique_path(dst)

    if same_drive(src, final):
        try:
            shutil.move(str(src), str(final))
        except OSError as e:
            raise OrganizeError(
                f"파일을 옮기지 못했습니다: {src.name}",
                hint="대상 폴더의 쓰기 권한이나 파일이 다른 프로그램에서 열려있는지 확인해 주세요.",
            ) from e
        return final

    try:
        shutil.copy2(str(src), str(final))
    except OSError as e:
        final.unlink(missing_ok=True)   # 복사 도중 중단됐다면 남은 조각을 지운다 (원본은 그대로)
        raise OrganizeError(
            f"파일을 복사하지 못했습니다: {src.name}",
            hint="대상 드라이브의 남은 공간과 연결 상태를 확인해 주세요.",
        ) from e

    if final.stat().st_size != src.stat().st_size:      # 복사 검증 후에만 지운다
        final.unlink(missing_ok=True)
        raise OrganizeError(
            f"복사가 끝나지 않아 옮기지 못했습니다: {src.name}",
            hint="대상 드라이브의 남은 공간과 연결 상태를 확인해 주세요.",
        )
    src.unlink()
    return final
