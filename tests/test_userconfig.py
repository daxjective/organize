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
