import json
from pathlib import Path

import pytest

from organize.errors import OrganizeError
from organize.recipes import Recipe, find_recipe, list_recipes, load_recipe, save_recipe


def test_round_trip(tmp_path):
    r = Recipe(name="다운로드 정리", roots=["@downloads"],
               steps=[{"block": "route", "profile": "desktop"}])
    p = tmp_path / "downloads.json"
    save_recipe(p, r)
    assert load_recipe(p) == r


def test_single_root_string_is_normalised(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"name": "x", "roots": "@downloads", "steps": []}),
                 encoding="utf-8")
    assert load_recipe(p).roots == ["@downloads"]


def test_missing_steps_is_an_error(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"name": "x", "roots": ["@downloads"]}), encoding="utf-8")
    with pytest.raises(OrganizeError):
        load_recipe(p)


def test_find_recipe_accepts_name_without_extension(tmp_path):
    (tmp_path / "downloads.json").write_text(
        json.dumps({"name": "x", "roots": ["@downloads"], "steps": []}), encoding="utf-8")
    assert find_recipe(tmp_path, "downloads").name == "downloads.json"


def test_find_recipe_lists_options_when_missing(tmp_path):
    (tmp_path / "downloads.json").write_text("{}", encoding="utf-8")
    with pytest.raises(OrganizeError) as ex:
        find_recipe(tmp_path, "없는것")
    assert "downloads" in (ex.value.hint or "")


def test_list_recipes(tmp_path):
    (tmp_path / "b.json").write_text("{}", encoding="utf-8")
    (tmp_path / "a.json").write_text("{}", encoding="utf-8")
    assert list_recipes(tmp_path) == ["a", "b"]
