"""폴더 개수를 세는 곳은 **한 군데**다.

`doctor`(명령줄)와 화면 1(창)이 같은 숫자를 보여줘야 한다. 표가 두 벌이 되면
한쪽만 고쳐지고, 그때부터 사용자는 어느 쪽이 맞는지 알 수 없다.
"""

import json
from pathlib import Path

import pytest

from organize import folders
from organize.userconfig import load_config


@pytest.fixture(autouse=True)
def 홈을_임시폴더로(monkeypatch, tmp_path):
    """내장 별칭이 진짜 홈을 보지 않게 한다 — 테스트가 사람 PC 를 세면 안 된다."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    for env in ("XDG_DESKTOP_DIR", "XDG_DOWNLOAD_DIR", "XDG_DOCUMENTS_DIR",
                "XDG_PICTURES_DIR", "XDG_MUSIC_DIR", "XDG_VIDEOS_DIR"):
        monkeypatch.delenv(env, raising=False)


def 폴더(path: Path, 파일수: int) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for i in range(파일수):
        (path / f"{i}.txt").write_text("x", encoding="utf-8")
    return path


def 설정(tmp_path: Path, paths: dict) -> object:
    (tmp_path / "config.default.json").write_text(
        json.dumps({"paths": paths}, ensure_ascii=False), encoding="utf-8")
    return load_config(tmp_path)


# ── 세기 ─────────────────────────────────────────────────────────
def test_파일만_센다_하위폴더는_안_센다(tmp_path):
    대상 = 폴더(tmp_path / "d", 3)
    (대상 / "안쪽").mkdir()
    assert folders.count_files(대상) == (3, "")


def test_폴더가_없으면_None_과_폴더없음(tmp_path):
    assert folders.count_files(tmp_path / "없다") == (None, "폴더 없음")


def test_읽을_수_없으면_None_과_읽을수없음(tmp_path, monkeypatch):
    대상 = 폴더(tmp_path / "d", 1)

    def 거부(self):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "iterdir", 거부)
    assert folders.count_files(대상) == (None, "읽을 수 없음")


def test_빈_폴더는_0_이지_없는_것이_아니다(tmp_path):
    (tmp_path / "비었다").mkdir()
    assert folders.count_files(tmp_path / "비었다") == (0, "")


# ── doctor 가 찍는 글자 ──────────────────────────────────────────
def test_doctor_표시_문자열이_예전과_같다(tmp_path, monkeypatch):
    """`organize doctor` 는 '파일 {여기}' 로 이어 붙여 찍는다.

    한 글자만 달라져도 사용자가 보던 화면이 바뀐다. 그래서 못박아 둔다.
    """
    assert folders.count_text(폴더(tmp_path / "d", 2)) == "2"
    assert folders.count_text(tmp_path / "없다") == "— 폴더 없음"

    def 거부(self):
        raise OSError

    monkeypatch.setattr(Path, "iterdir", 거부)
    assert folders.count_text(폴더(tmp_path / "e", 0)) == "읽을 수 없음"


# ── 목록 ─────────────────────────────────────────────────────────
def test_내장_별칭이_먼저_그다음_사용자_이름_가나다순(tmp_path):
    cfg = 설정(tmp_path, {"보관": str(tmp_path / "보관"), "가방": str(tmp_path / "가방")})
    이름들 = [f.name for f in folders.overview(cfg)]
    assert 이름들[:7] == ["home", "desktop", "downloads", "documents",
                        "pictures", "music", "videos"]
    assert 이름들[7:] == ["가방", "보관"]      # doctor 와 같은 순서(sorted)


def test_내장은_한국어_이름표_사용자_이름은_그대로(tmp_path):
    cfg = 설정(tmp_path, {"보관": str(tmp_path / "보관")})
    표 = {f.name: f.label for f in folders.overview(cfg)}
    assert 표["desktop"] == "바탕화면"
    assert 표["pictures"] == "사진"
    assert 표["보관"] == "보관"


def test_내장인지_아닌지_표시한다(tmp_path):
    cfg = 설정(tmp_path, {"보관": str(tmp_path / "보관")})
    표 = {f.name: f.builtin for f in folders.overview(cfg)}
    assert 표["desktop"] is True
    assert 표["보관"] is False


def test_같은_경로가_두_번_나오면_뒤엣것은_빠진다(tmp_path):
    """`@photos` 가 사진 폴더를 가리키면 같은 폴더를 두 줄로 보여줄 이유가 없다."""
    폴더(tmp_path / "Pictures", 1)
    cfg = 설정(tmp_path, {"photos": str(tmp_path / "Pictures")})
    이름들 = [f.name for f in folders.overview(cfg)]
    assert "pictures" in 이름들
    assert "photos" not in 이름들


def test_개수와_상태를_함께_준다(tmp_path):
    폴더(tmp_path / "Desktop", 6)
    cfg = 설정(tmp_path, {})
    표 = {f.name: (f.count, f.status) for f in folders.overview(cfg)}
    assert 표["desktop"] == (6, "")
    assert 표["downloads"] == (None, "폴더 없음")     # 만들지 않았다


def test_경로를_함께_준다(tmp_path):
    폴더(tmp_path / "Desktop", 1)
    cfg = 설정(tmp_path, {})
    바탕 = next(f for f in folders.overview(cfg) if f.name == "desktop")
    assert 바탕.path == tmp_path / "Desktop"


def test_풀_수_없는_이름은_건너뛴다_창이_죽으면_안_된다(tmp_path):
    """가리키는 이름이 돌고 도는 설정이 있어도 첫 화면은 떠야 한다."""
    cfg = 설정(tmp_path, {"고리": "@고리"})
    이름들 = [f.name for f in folders.overview(cfg)]
    assert "고리" not in 이름들
    assert "desktop" in 이름들
