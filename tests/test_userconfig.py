import json
from pathlib import Path

import pytest

from organize import aliases, userconfig
from organize.errors import OrganizeError
from organize.userconfig import (AliasNotDefined, UserConfig, load_config,
                                 refuse_unsupported, resolve_alias)


def write(p: Path, data: dict) -> None:
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_local_overrides_default(tmp_path):
    write(tmp_path / "config.default.json", {"paths": {"archive": "@documents/Archive"}})
    write(tmp_path / "config.local.json", {"paths": {"archive": "D:/보관"}})
    cfg = load_config(tmp_path)
    assert cfg.paths["archive"] == ["D:/보관"]


def test_works_with_no_local_file(tmp_path):
    write(tmp_path / "config.default.json", {"paths": {"archive": "@documents/Archive"}})
    cfg = load_config(tmp_path)
    assert cfg.paths["archive"] == ["@documents/Archive"]


def test_missing_both_files_is_not_an_error(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg.paths == {}


def test_single_string_is_normalised_to_a_list(tmp_path):
    write(tmp_path / "config.default.json", {"paths": {"a": "X:/one"}})
    assert load_config(tmp_path).paths["a"] == ["X:/one"]


def test_chain_picks_the_first_existing_path(tmp_path):
    present = tmp_path / "있음"
    present.mkdir()
    cfg = UserConfig(paths={"archive": [str(tmp_path / "없음"), str(present)]}, folder_names={})
    assert resolve_alias("@archive", cfg) == present


def test_chain_falls_back_to_the_last_entry_when_none_exist(tmp_path):
    last = tmp_path / "만들예정"
    cfg = UserConfig(paths={"archive": [str(tmp_path / "없음"), str(last)]}, folder_names={})
    assert resolve_alias("@archive", cfg) == last


def test_builtin_alias_resolves(monkeypatch, tmp_path):
    monkeypatch.setattr(userconfig, "builtin_path",
                        lambda name: tmp_path / "다운로드" if name == "downloads" else None)
    cfg = UserConfig(paths={}, folder_names={})
    assert resolve_alias("@downloads", cfg) == tmp_path / "다운로드"


def test_builtin_alias_with_subpath(monkeypatch, tmp_path):
    monkeypatch.setattr(userconfig, "builtin_path",
                        lambda name: tmp_path / "문서" if name == "documents" else None)
    cfg = UserConfig(paths={}, folder_names={})
    assert resolve_alias("@documents/메모", cfg) == tmp_path / "문서" / "메모"


# ── 내장 이름 vs 사용자가 등록한 값 — 어느 쪽이 이기는가 ────────────
# 이 우선순위를 못박는 테스트가 **하나도 없었다.** 그래서 내장 이름을
# 설정에 적어도 영영 무시되는 결함이 여덟 달 동안 안 잡혔다. 설정 화면의
# [다시 지정] 이 저장만 하고 아무 일도 안 하는 것이 그 증상이다.

def test_a_registered_path_beats_the_builtin_guess(monkeypatch, tmp_path):
    """PC 를 옮기면 OS 추측이 틀린다(OneDrive 백업 등). **사용자가 적은 값이 이긴다.**"""
    monkeypatch.setattr(userconfig, "builtin_path",
                        lambda name: tmp_path / "OS가찍은바탕화면")
    내가고른것 = tmp_path / "진짜바탕화면"
    내가고른것.mkdir()
    cfg = UserConfig(paths={"desktop": [str(내가고른것)]}, folder_names={})
    assert resolve_alias("@desktop", cfg) == 내가고른것


def test_a_registered_builtin_name_also_wins_for_subpaths(monkeypatch, tmp_path):
    """꼬리(`@desktop/보관`)가 붙어도 앞머리는 등록한 값에서 온다."""
    monkeypatch.setattr(userconfig, "builtin_path",
                        lambda name: tmp_path / "OS가찍은바탕화면")
    내가고른것 = tmp_path / "진짜바탕화면"
    내가고른것.mkdir()
    cfg = UserConfig(paths={"desktop": [str(내가고른것)]}, folder_names={})
    assert resolve_alias("@desktop/보관", cfg) == 내가고른것 / "보관"


def test_a_builtin_name_that_is_not_registered_still_uses_the_os(monkeypatch, tmp_path):
    """등록하지 않은 내장 이름은 **예전 그대로** OS 가 답한다(회귀 없음)."""
    monkeypatch.setattr(userconfig, "builtin_path",
                        lambda name: tmp_path / "OS가찍은바탕화면" if name == "desktop" else None)
    cfg = UserConfig(paths={"백업": ["X:/백업"]}, folder_names={})
    assert resolve_alias("@desktop", cfg) == tmp_path / "OS가찍은바탕화면"


def test_a_registered_builtin_name_falls_back_to_the_last_entry(monkeypatch, tmp_path):
    """USB 를 안 꽂았어도 목록의 마지막을 쓴다 — 사슬 규칙은 내장 이름에도 같다."""
    monkeypatch.setattr(userconfig, "builtin_path", lambda name: tmp_path / "OS가찍은것")
    cfg = UserConfig(paths={"pictures": [str(tmp_path / "없음1"), str(tmp_path / "없음2")]},
                     folder_names={})
    assert resolve_alias("@pictures", cfg) == tmp_path / "없음2"


def test_plain_path_passes_through(tmp_path):
    cfg = UserConfig(paths={}, folder_names={})
    assert resolve_alias(str(tmp_path), cfg) == tmp_path


def test_undefined_alias_says_what_to_do():
    cfg = UserConfig(paths={}, folder_names={})
    with pytest.raises(AliasNotDefined) as e:
        resolve_alias("@archive", cfg)
    assert "archive" in e.value.message
    assert e.value.hint and "organize paths" in e.value.hint


def test_self_referencing_alias_raises_error():
    cfg = UserConfig(paths={"archive": ["@archive"]}, folder_names={})
    with pytest.raises(AliasNotDefined) as e:
        resolve_alias("@archive", cfg)
    assert "archive" in e.value.message
    assert e.value.hint and "config.local.json" in e.value.hint


def test_mutually_referencing_aliases_raise_error():
    cfg = UserConfig(paths={"a": ["@b"], "b": ["@a"]}, folder_names={})
    with pytest.raises(AliasNotDefined) as e:
        resolve_alias("@a", cfg)
    assert "a" in e.value.message
    assert "@a" in e.value.message
    assert "@b" in e.value.message
    assert e.value.hint and "config.local.json" in e.value.hint


def test_seen_parameter_is_keyword_only():
    cfg = UserConfig(paths={}, folder_names={})
    with pytest.raises(TypeError):
        resolve_alias("@a", cfg, ("x",))


def test_pins_in_a_config_is_reported_not_silently_ignored(tmp_path):
    """Minor #1 — `pins` 는 "건드리지 말 것" 으로 읽히는데 **아무 데서도 안 읽혔다.**
    보호를 기대하고 적은 파일이 그대로 옮겨진다. 조용히 무시하지 않는다.

    다만 `load_config` 는 **던지지 않는다** — 그러면 `undo`·`doctor` 까지 같이
    죽어 되돌리기가 잠긴다. 실어만 보내고 판단은 부르는 쪽이 한다."""
    (tmp_path / "config.local.json").write_text(
        '{"pins": ["세금.pdf"]}', encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg.unsupported == ("pins",)

    with pytest.raises(OrganizeError) as ex:
        refuse_unsupported(cfg)              # 파일을 옮기는 명령에서만 부른다
    assert "pins" in ex.value.message
    assert ex.value.hint


def test_an_empty_pins_list_does_not_break_an_old_config(tmp_path):
    """빈 목록은 아무것도 약속하지 않는다 — 예전 설정 파일이 깨지면 안 된다."""
    (tmp_path / "config.local.json").write_text('{"pins": []}', encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg.paths == {} and cfg.unsupported == ()
    refuse_unsupported(cfg)                  # 아무것도 안 던진다


# --- 설정 파일이 문법은 맞고 모양만 틀린 경우 ---
# 되돌리기는 사용자의 마지막 안전줄이다. 설정 파일 하나가 이상하다고
# 파이썬 트레이스백으로 죽으면, 파일이 옮겨진 채 손쓸 방법이 없어진다.

@pytest.mark.parametrize("bad,왜", [
    ("[]", "목록"),
    ("null", "빈 값"),
    ('{"paths": "문자열"}', "paths 가 문자열"),
    ('{"paths": {"a": 1}}', "경로가 숫자"),
    ('{"folder_names": ["a"]}', "folder_names 가 목록"),
])
def test_a_wrongly_shaped_config_is_a_korean_error_not_a_traceback(tmp_path, bad, 왜):
    (tmp_path / "config.local.json").write_text(bad, encoding="utf-8")

    with pytest.raises(OrganizeError) as ex:
        load_config(tmp_path)

    assert "config.local.json" in ex.value.message, f"어느 파일인지 말해야 한다 ({왜})"
    assert ex.value.hint, "어떻게 고치는지 알려야 한다"
    # 파이썬 예외 원문을 그대로 노출하지 않는다
    합친것 = ex.value.message + (ex.value.hint or "")
    for 원문 in ("AttributeError", "TypeError", "object has no attribute", "not iterable"):
        assert 원문 not in 합친것


# ── 등록한 위치 지우기 (설정 화면의 [지우기]) ───────────────────────

def test_remove_local_path_removes_only_that_name(tmp_path):
    userconfig.save_local_path(tmp_path, "백업", "D:/백업")
    userconfig.save_local_path(tmp_path, "사진보관", "E:/사진")

    assert userconfig.remove_local_path(tmp_path, "백업") is True

    cfg = load_config(tmp_path)
    assert "백업" not in cfg.paths
    assert cfg.paths["사진보관"] == ["E:/사진"], "다른 이름은 그대로 남아야 한다"


def test_remove_local_path_returns_false_for_an_unknown_name(tmp_path):
    userconfig.save_local_path(tmp_path, "백업", "D:/백업")
    assert userconfig.remove_local_path(tmp_path, "없던이름") is False
    assert load_config(tmp_path).paths["백업"] == ["D:/백업"]


def test_remove_local_path_survives_a_missing_config_file(tmp_path):
    """`config.local.json` 이 아직 없는 PC 에서 눌러도 죽지 않는다."""
    assert not (tmp_path / "config.local.json").exists()
    assert userconfig.remove_local_path(tmp_path, "백업") is False
    assert not (tmp_path / "config.local.json").exists(), "없는 파일을 새로 만들지 않는다"


def test_remove_local_path_keeps_an_empty_paths_map(tmp_path):
    """마지막 하나를 지워도 `paths` 키는 빈 묶음으로 남는다."""
    userconfig.save_local_path(tmp_path, "백업", "D:/백업")
    assert userconfig.remove_local_path(tmp_path, "백업") is True

    data = json.loads((tmp_path / "config.local.json").read_text(encoding="utf-8"))
    assert data["paths"] == {}


def test_remove_local_path_never_touches_the_shared_config(tmp_path):
    """`config.default.json` 은 저장소 공용 파일이다 — 이 PC 의 [지우기] 가 건드리면 안 된다."""
    write(tmp_path / "config.default.json", {"paths": {"archive": "@documents/Archive"}})
    원본 = (tmp_path / "config.default.json").read_text(encoding="utf-8")

    assert userconfig.remove_local_path(tmp_path, "archive") is False
    assert (tmp_path / "config.default.json").read_text(encoding="utf-8") == 원본
