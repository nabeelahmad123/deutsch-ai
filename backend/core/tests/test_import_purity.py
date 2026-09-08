"""backend/core imports nothing LLM / MCP / HTTP -- a core design rule.

An AST scan of every non-test module under backend/core. The DB (sqlalchemy) is
the one network dependency the contract allows.
"""

import ast
import pathlib

FORBIDDEN = {"anthropic", "mcp", "openai", "httpx", "requests", "urllib", "aiohttp"}
CORE = pathlib.Path(__file__).resolve().parents[1]


def _imported_top_levels(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module.split(".")[0])
    return mods


def test_core_has_no_llm_or_network_imports():
    offenders = {}
    for path in CORE.rglob("*.py"):
        if "tests" in path.parts:
            continue
        bad = _imported_top_levels(path) & FORBIDDEN
        if bad:
            offenders[str(path.relative_to(CORE))] = sorted(bad)
    assert offenders == {}, offenders
