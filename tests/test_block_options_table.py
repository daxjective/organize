"""`BLOCK_OPTIONS` 가 블록 코드와 어긋나지 않는지 지킨다.

러너는 이 표를 보고 레시피의 오타를 거부한다. 표가 코드와 어긋나면 두 방향으로
사고가 난다.

  표에 빠진 키   그 옵션을 쓴 **정상 레시피가 통째로 거부된다**
  표에 남은 키   그 오타가 다시 조용히 새어 나간다

블록에 옵션을 추가하면서 표를 안 고치는 일은 반드시 생긴다. 그때 이 테스트가
막는다 — 사람의 기억이 아니라 코드를 읽어서 대조한다.
"""

import ast
from pathlib import Path

from organize.blocks import BLOCK_OPTIONS

BLOCKS_DIR = Path(__file__).resolve().parent.parent / "organize" / "blocks"


def _option_keys_used(source: str) -> set[str]:
    """소스에서 `cfg.options[...]` 와 `cfg.options.get(...)` 의 키를 뽑는다."""
    keys: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "options"
                and isinstance(node.slice, ast.Constant)):
            keys.add(node.slice.value)
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "options"
                and node.args
                and isinstance(node.args[0], ast.Constant)):
            keys.add(node.args[0].value)
    return keys


def test_every_block_module_has_an_entry():
    """블록 파일을 새로 만들면 표에도 넣어야 한다."""
    modules = {p.stem for p in BLOCKS_DIR.glob("*.py") if p.stem != "__init__"}
    assert modules == set(BLOCK_OPTIONS)


def test_declared_options_match_what_the_code_actually_reads():
    for name, declared in sorted(BLOCK_OPTIONS.items()):
        used = _option_keys_used((BLOCKS_DIR / f"{name}.py").read_text(encoding="utf-8"))
        assert used == set(declared), (
            f"'{name}' 블록의 옵션 선언이 코드와 다릅니다. "
            f"코드에서 읽는 것={sorted(used)} · BLOCK_OPTIONS={sorted(declared)}"
        )


def test_the_checker_actually_finds_keys():
    """대조 도구 자체가 망가지면 위 두 테스트가 조용히 통과한다.

    빈 집합끼리 비교하면 무엇이든 맞아떨어지므로, 도구가 진짜로 키를 찾아내는지
    먼저 확인한다.
    """
    assert _option_keys_used('x = cfg.options["가"]') == {"가"}
    assert _option_keys_used('x = cfg.options.get("나", 1)') == {"나"}
    assert _option_keys_used("x = cfg.target") == set()
