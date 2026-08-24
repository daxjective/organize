"""실제로 파일을 옮긴다. 덮어쓰지 않는다.

이름을 고르는 것과 그 자리를 실제로 차지하는 것(`claim_path`)은 다른 동작이다.
둘 사이에 시간차가 있으면 그 틈에 다른 프로그램이 같은 이름을 만들 수 있고,
그러면 우리가 그걸 조용히 덮어쓴다. 그래서 실제로 쓰기 직전에는 반드시
`claim_path` 로 "없음 확인"과 "이름 잡기"를 한 syscall로 합친다.

**미리보기에서 이름을 고르는 자리는 이 파일이 아니라
`organize.core.context.Context.claim_name` 이다.** 아래 `unique_path` 는
production 에서 아무도 부르지 않는다 — 그 함수를 살아 있는 미리보기 경로로
읽으면 안 된다.

드라이브가 다르면 `shutil.move` 도 내부적으로 복사 후 삭제를 하지만,
복사가 끝났는지 확인하지 않는다. 파일이 사라지면 안 되므로
직접 copy2 → 크기 확인 → 삭제 순으로 한다. 드라이브가 같은지는 미리
판정하지 않는다 — `os.replace` 를 그냥 해 보고 운영체제가 `EXDEV` 를 주면
그때 복사 경로로 간다.
"""

import errno
import os
import shutil
from pathlib import Path

from organize.errors import OrganizeError


def _numbered(dst: Path, n: int) -> Path:
    return dst.with_name(f"{dst.stem}_({n}){dst.suffix}")


def claim_path(dst: Path) -> Path:
    """빈 파일을 만들어 **이름을 원자적으로 잡는다.** 잡은 경로를 돌려준다.

    "없네" 를 확인하고 실제로 옮기기까지 사이에 틈이 있으면, 그 틈에 다른
    프로그램이 같은 이름을 만들 수 있고 우리가 그걸 조용히 덮어쓴다.
    **실제로 쓰기 직전에는 반드시 이 함수로 자리를 먼저 잡는다.**
    (미리보기에서 이름을 고르는 것은 `Context.claim_name` 이다 — 디스크를
    만지지 않는다. 이 파일의 `unique_path` 는 production 에서 아무도 안 부른다.)

    `O_CREAT | O_EXCL` 은 "없을 때만 만든다" 를 운영체제가 원자적으로 보장한다.
    만들어 두면 그 이름은 우리 것이므로 이후 덮어써도 남의 파일이 아니다.
    중간에 프로그램이 죽으면 빈 파일이 남는데, 파일이 사라지는 것보다 낫다.
    """
    n = 0
    while True:
        candidate = dst if n == 0 else _numbered(dst, n)
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            n += 1
            continue
        except OSError as e:
            raise OrganizeError(
                f"파일을 만들 자리를 잡지 못했습니다: {candidate.name}",
                hint="대상 폴더의 쓰기 권한을 확인해 주세요.",
            ) from e
        os.close(fd)
        return candidate


def unique_path(dst: Path) -> Path:
    """**production 에서 아무도 안 부른다.** 확인과 쓰기 사이에 틈이 있어서다.

    미리보기의 이름 고르기는 `Context.claim_name`(디스크를 안 만짐)이 하고,
    실제 쓰기는 `claim_path`(O_CREAT|O_EXCL)가 한다. 이 함수는 그 둘의 차이를
    설명하는 반례로만 남아 있다 — 새 코드에서 쓰지 말 것. 붙어 있는 테스트는
    `move_file` 이 **이 함수를 쓰지 않는다**는 사실을 못박는 용도다.
    """
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
    """두 경로의 드라이브 문자가 같은가. **production 에서 아무도 안 부른다.**

    **안전 판정에 쓰지 말 것.**

    `Path.drive` 는 윈도우 경로에서만 값이 있다. WSL 마운트 경로
    (`/mnt/c`, `/mnt/d`)는 둘 다 빈 문자열이라 **다른 드라이브인데 같다고
    답한다.** 이 함수의 답을 믿고 안전 검사를 건너뛰면 그 검사가 통째로
    사라진다 — 실제로 그런 결함이 있었다.

    `move_file` 은 이 함수를 쓰지 않는다. `os.replace` 를 해 보고 운영체제가
    `EXDEV` 를 주면 그때 다른 드라이브로 판정한다. 추측이 아니라 사실이다.
    이 함수는 안내 문구를 만들 때처럼 틀려도 안전한 곳에만 쓴다.
    """
    return a.drive.lower() == b.drive.lower()


def move_file(src: Path, dst: Path) -> Path:
    """실제 이동. 최종 경로를 돌려준다. **절대 덮어쓰지 않는다.**

    드라이브가 같은지 미리 판정하지 않는다. `same_drive` 는 WSL 마운트 경로
    (`/mnt/c`, `/mnt/d`)를 같은 드라이브로 오판한다 — 그러면 크기 검증이라는
    안전망을 통째로 건너뛴다. 그냥 `os.replace` 를 해 보고 운영체제가
    `EXDEV`(드라이브가 다르다)를 주면 그때 복사 경로로 간다. 판정을 추측이
    아니라 운영체제에게 맡긴다.
    """
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
            hint="상위 폴더의 쓰기 권한을 확인하거나, 경로 중간에 같은 이름의 파일이 있는지 확인해 주세요.",
        ) from e

    final = claim_path(dst)        # 이름을 먼저 잡는다 — 이제 이 자리는 우리 것이다
    try:
        return _move_onto(src, final)
    except OrganizeError:
        raise                      # 아래에서 이미 정리하고 안내까지 만들었다
    except BaseException:
        # Ctrl-C 나 예상 못 한 오류. 우리가 잡아 둔 빈 자리가 남으면 사용자
        # 폴더에 0바이트 파일이 생기고, 다음 실행 때 그 이름이 막혀 _(1) 이
        # 계속 밀린다. 아직 아무것도 안 옮겼을 때만 치운다.
        _discard_placeholder(src, final)
        raise


def _discard_placeholder(src: Path, final: Path) -> None:
    """아직 아무것도 안 옮겼으면 잡아 둔 빈 자리를 치운다."""
    try:
        if src.exists() and final.stat().st_size == 0:
            final.unlink(missing_ok=True)
    except OSError:
        pass                       # 정리에 실패해도 원래 오류를 덮지 않는다


def _move_onto(src: Path, final: Path) -> Path:
    try:
        os.replace(src, final)     # 우리가 만든 빈 파일 위에 덮는다. 원자적이다.
        return final
    except OSError as e:
        if e.errno != errno.EXDEV:
            final.unlink(missing_ok=True)      # 우리가 만든 빈 자리만 치운다
            raise OrganizeError(
                f"파일을 옮기지 못했습니다: {src.name}",
                hint="대상 폴더의 쓰기 권한이나 파일이 다른 프로그램에서 열려있는지 확인해 주세요.",
            ) from e

    # 드라이브가 다르다. 복사 -> 크기 확인 -> 삭제. 이 순서를 지켜야 파일이 안 사라진다.
    try:
        shutil.copy2(str(src), str(final))
    except OSError as e:
        final.unlink(missing_ok=True)   # 복사 도중 중단됐다면 조각을 치운다 (원본은 그대로)
        raise OrganizeError(
            f"파일을 복사하지 못했습니다: {src.name}",
            hint="대상 드라이브의 남은 공간과 연결 상태를 확인해 주세요.",
        ) from e

    try:                                   # 검증 전에는 절대 안 지운다
        copied_ok = final.stat().st_size == src.stat().st_size
    except OSError as e:                   # 확인조차 못 했으면 지우지 않는다
        final.unlink(missing_ok=True)
        raise OrganizeError(
            f"복사한 파일을 확인하지 못했습니다: {src.name}",
            hint="대상 드라이브의 연결 상태를 확인해 주세요. 원본은 그대로 있습니다.",
        ) from e
    if not copied_ok:
        final.unlink(missing_ok=True)
        raise OrganizeError(
            f"복사가 끝나지 않아 옮기지 못했습니다: {src.name}",
            hint="대상 드라이브의 남은 공간과 연결 상태를 확인해 주세요.",
        )

    try:
        src.unlink()
    except OSError as e:
        # 복사본은 멀쩡하다. 원본이 안 지워졌을 뿐이므로 파일을 잃지는 않았다.
        raise OrganizeError(
            f"복사는 끝났는데 원본을 지우지 못했습니다: {src.name}",
            hint=f"같은 파일이 {final} 에도 있습니다. 원본을 직접 지워 주세요.",
        ) from e
    return final
