from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from organize import profiles
from organize.core.scanner import FileEntry
from organize.errors import OrganizeError
from organize.profiles import load_profile, matches, parse_age, parse_size, route_target

TODAY = date(2026, 8, 21)


def entry(name, size=100, days_old=1):
    stamp = datetime(2026, 8, 21).timestamp() - days_old * 86400
    return FileEntry(path=Path("/x") / name, size=size, mtime=stamp)


def test_parse_size():
    assert parse_size("100") == 100
    assert parse_size("10KB") == 10 * 1024
    assert parse_size("2MB") == 2 * 1024 ** 2
    assert parse_size("1GB") == 1024 ** 3
    assert parse_size("2M") == 2 * 1024 ** 2        # B 를 생략해도 통해야 한다
    assert parse_size("500k") == 500 * 1024
    assert parse_size("1.5MB") == int(1.5 * 1024 ** 2)


@pytest.mark.parametrize("bad", ["MB", "abc", "10XB", ""])
def test_parse_size_rejects_nonsense(bad):
    with pytest.raises(Exception):
        parse_size(bad)


def test_parse_age():
    assert parse_age("30d") == timedelta(days=30)
    assert parse_age("6m") == timedelta(days=180)
    assert parse_age("2y") == timedelta(days=730)


def test_ext_condition_is_case_insensitive():
    assert matches(entry("사진.PNG"), {"ext": [".png"]}, TODAY)
    assert not matches(entry("사진.jpg"), {"ext": [".png"]}, TODAY)


def test_name_contains():
    assert matches(entry("2026 회고.md"), {"name_contains": ["회고"]}, TODAY)
    assert not matches(entry("메모.md"), {"name_contains": ["회고"]}, TODAY)


def test_name_regex():
    assert matches(entry("IMG_0001.jpg"), {"name_regex": r"^IMG_\d+"}, TODAY)
    assert not matches(entry("사진.jpg"), {"name_regex": r"^IMG_\d+"}, TODAY)


def test_older_than():
    assert matches(entry("옛것.pdf", days_old=800), {"older_than": "2y"}, TODAY)
    assert not matches(entry("새것.pdf", days_old=10), {"older_than": "2y"}, TODAY)


def test_larger_than():
    assert matches(entry("큰것.zip", size=200 * 1024 ** 2), {"larger_than": "100MB"}, TODAY)
    assert not matches(entry("작은것.zip", size=1024), {"larger_than": "100MB"}, TODAY)


def test_conditions_are_and_ed():
    cond = {"ext": [".png"], "larger_than": "1MB"}
    assert matches(entry("큰사진.png", size=5 * 1024 ** 2), cond, TODAY)
    assert not matches(entry("작은사진.png", size=100), cond, TODAY)


def test_empty_conditions_match_everything():
    assert matches(entry("무엇이든.xyz"), {}, TODAY)


def test_has_exif_camera_condition(monkeypatch):
    monkeypatch.setattr(profiles, "has_exif_camera",
                        lambda p: p.name.startswith("카메라"))
    assert matches(entry("카메라사진.jpg"), {"has_exif_camera": True}, TODAY)
    assert matches(entry("캡처.png"), {"has_exif_camera": False}, TODAY)
    assert not matches(entry("캡처.png"), {"has_exif_camera": True}, TODAY)


def test_rule_with_exif_condition_is_skipped_when_undecidable(monkeypatch):
    """Pillow 가 없으면 이 조건이 붙은 규칙은 건너뛰고 다음 규칙으로 넘어간다."""
    monkeypatch.setattr(profiles, "has_exif_camera", lambda p: None)
    assert not matches(entry("사진.jpg"), {"has_exif_camera": True}, TODAY)


def test_load_profile_and_route(tmp_path):
    toml = tmp_path / "t.toml"
    toml.write_text(
        'name = "테스트"\n'
        '[[rules]]\n to = "01_Docs"\n ext = [".pdf", ".md"]\n'
        '[[rules]]\n to = "02_Media"\n ext = [".png"]\n'
        '[[rules]]\n to = "99_Unsorted"\n default = true\n'
        '[synonyms]\n "02_Media" = ["사진", "이미지"]\n',
        encoding="utf-8",
    )
    p = load_profile(toml)
    assert p.name == "테스트"
    assert p.synonyms["02_Media"] == ["사진", "이미지"]
    assert route_target(entry("보고서.pdf"), p, TODAY) == "01_Docs"
    assert route_target(entry("사진.png"), p, TODAY) == "02_Media"
    assert route_target(entry("무엇.xyz"), p, TODAY) == "99_Unsorted"


def test_first_matching_rule_wins(tmp_path):
    toml = tmp_path / "t.toml"
    toml.write_text(
        'name = "순서"\n'
        '[[rules]]\n to = "먼저"\n ext = [".png"]\n'
        '[[rules]]\n to = "나중"\n ext = [".png"]\n',
        encoding="utf-8",
    )
    assert route_target(entry("a.png"), load_profile(toml), TODAY) == "먼저"


def test_no_matching_rule_and_no_default_returns_none(tmp_path):
    toml = tmp_path / "t.toml"
    toml.write_text('name = "없음"\n[[rules]]\n to = "01_Docs"\n ext = [".pdf"]\n', encoding="utf-8")
    assert route_target(entry("사진.png"), load_profile(toml), TODAY) is None


def test_malformed_toml_hint_is_korean_action_not_raw_parser_text(tmp_path):
    """[1] hint 는 '무엇을 하면 되는지' 한국어 행동 지시여야 한다 — tomllib 예외 원문이 그대로 오면 안 된다."""
    toml = tmp_path / "bad.toml"
    toml.write_text("name = ", encoding="utf-8")   # 문법 오류 TOML
    with pytest.raises(OrganizeError) as exc:
        load_profile(toml)
    hint = exc.value.hint
    assert "Invalid value" not in hint             # tomllib 의 영어 원문이 그대로 있으면 안 된다
    assert any("가" <= ch <= "힣" for ch in hint)   # 한국어 문장이어야 한다


def test_unknown_condition_key_is_rejected(tmp_path):
    """[2] 오타 난 조건 키를 조용히 버리면, 빈 조건이 되어 모든 파일에 매칭된다 — 그래서 거부해야 한다."""
    toml = tmp_path / "t.toml"
    toml.write_text(
        'name = "오타"\n'
        '[[rules]]\n to = "02_Media"\n extt = [".png"]\n',
        encoding="utf-8",
    )
    with pytest.raises(OrganizeError) as exc:
        load_profile(toml)
    assert "extt" in exc.value.message
    assert "ext" in exc.value.hint


def test_default_rule_must_be_the_last_rule(tmp_path):
    """[3] default 규칙이 앞에 오면 뒤 규칙을 전부 가린다 — 검증해서 거부해야 한다."""
    toml = tmp_path / "t.toml"
    toml.write_text(
        'name = "기본이 먼저"\n'
        '[[rules]]\n to = "99_Unsorted"\n default = true\n'
        '[[rules]]\n to = "02_Media"\n ext = [".png"]\n',
        encoding="utf-8",
    )
    with pytest.raises(OrganizeError) as exc:
        load_profile(toml)
    # 예외 종류만 보면 TOML 문법 오류에도 통과한다 — 무엇을 잡았는지까지 확인한다.
    assert "마지막" in exc.value.message or "마지막" in exc.value.hint


def test_at_most_one_default_rule(tmp_path):
    """[3] default 규칙은 최대 하나여야 한다."""
    toml = tmp_path / "t.toml"
    toml.write_text(
        'name = "기본 두 개"\n'
        '[[rules]]\n to = "A"\n default = true\n'
        '[[rules]]\n to = "B"\n default = true\n',
        encoding="utf-8",
    )
    with pytest.raises(OrganizeError) as exc:
        load_profile(toml)
    assert "하나" in exc.value.message or "하나" in exc.value.hint


def test_condition_keys_is_public_and_shared_with_runner():
    """러너가 when 필터의 오타를 잡을 때 이 공개 이름을 가져다 쓴다."""
    from organize.profiles import CONDITION_KEYS
    assert isinstance(CONDITION_KEYS, frozenset)
    assert CONDITION_KEYS == {"ext", "name_contains", "name_regex", "older_than",
                              "larger_than", "has_exif_camera"}


def test_default_rule_as_the_only_or_last_rule_is_fine(tmp_path):
    """[3] 회귀 방지 — default 가 하나이고 마지막이면 정상적으로 로드되어야 한다."""
    toml = tmp_path / "t.toml"
    toml.write_text(
        'name = "정상"\n'
        '[[rules]]\n to = "02_Media"\n ext = [".png"]\n'
        '[[rules]]\n to = "99_Unsorted"\n default = true\n',
        encoding="utf-8",
    )
    p = load_profile(toml)
    assert route_target(entry("무엇.xyz"), p, TODAY) == "99_Unsorted"


# --- 수정 라운드 2(최종 리뷰) — Important #1: 조건 **값의 타입**을 아무도 안 봤다. ---


def test_name_contains_given_as_a_bare_string_is_not_walked_letter_by_letter(tmp_path):
    """`name_contains = "report"`(대괄호 누락) 하나가 폴더를 통째로 옮겼다.
    any(w in name for w in "report") 가 **글자 단위로** 순회해서 `.jpg` 의 'p'
    하나에도 걸렸기 때문이다. 실측한 결함이다."""
    assert matches(entry("report_final.pdf"), {"name_contains": "report"}, TODAY)
    assert not matches(entry("가족사진.jpg"), {"name_contains": "report"}, TODAY)
    assert not matches(entry("노래.mp3"), {"name_contains": "report"}, TODAY)


def test_ext_given_as_a_bare_string_still_matches(tmp_path):
    """반대 방향 — `ext = ".pdf"` 는 ['.','p','d','f'] 가 되어 **아무것도 안 걸렸다.**"""
    assert matches(entry("보고서.pdf"), {"ext": ".pdf"}, TODAY)
    assert not matches(entry("사진.png"), {"ext": ".pdf"}, TODAY)


def test_empty_condition_list_is_rejected_instead_of_matching_nothing(tmp_path):
    """`ext = []` 는 조용히 0건이 된다 — 조용한 무작동이다."""
    with pytest.raises(OrganizeError) as ex:
        matches(entry("보고서.pdf"), {"ext": []}, TODAY)
    assert "비어" in ex.value.message


@pytest.mark.parametrize("bad", [5, {"a": 1}, [1, 2], None])
def test_condition_value_of_a_wrong_type_is_rejected_in_korean(bad):
    with pytest.raises(OrganizeError) as ex:
        matches(entry("보고서.pdf"), {"name_contains": bad}, TODAY)
    assert "이해하지 못했습니다" in ex.value.message


def test_profile_with_a_bare_string_condition_loads_and_behaves(tmp_path):
    """레시피·프로파일 어느 쪽에 적어도 같게 동작해야 한다."""
    toml = tmp_path / "t.toml"
    toml.write_text('name = "t"\n[[rules]]\n to = "보고서"\n name_contains = "report"\n',
                    encoding="utf-8")
    p = load_profile(toml)
    assert route_target(entry("report_final.pdf"), p, TODAY) == "보고서"
    assert route_target(entry("가족사진.jpg"), p, TODAY) is None


def test_profile_with_a_broken_regex_is_rejected_before_any_file_is_touched(tmp_path):
    toml = tmp_path / "t.toml"
    toml.write_text('name = "t"\n[[rules]]\n to = "x"\n name_regex = "[불완전"\n',
                    encoding="utf-8")
    with pytest.raises(OrganizeError) as ex:
        load_profile(toml)
    assert "name_regex" in ex.value.message
    assert "re.error" not in ex.value.message
