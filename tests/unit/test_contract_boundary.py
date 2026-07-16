"""Import-boundary guard for kb.contract.

contract/ is a pure translation/schema layer sitting alongside core/, platform/, and
ui/ — it must never import Textual (the TUI framework) or any of the macOS ObjC
bridging modules (objc, EventKit, Cocoa, Foundation) that platform/ and ui/ depend on,
matching core/'s discipline. Static AST analysis catches violations even behind a
try/except, without needing the banned packages installed.
"""

from __future__ import annotations

import ast
from pathlib import Path

BANNED_TOP_LEVEL_MODULES = {"textual", "objc", "EventKit", "Cocoa", "Foundation"}

CONTRACT_DIR = Path(__file__).resolve().parents[2] / "src" / "kb" / "contract"


def _top_level_imports(source: str) -> set[str]:
    tree = ast.parse(source)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module.split(".")[0])
    return modules


def test_contract_never_imports_ui_or_platform_modules():
    violations: dict[str, set[str]] = {}
    for path in sorted(CONTRACT_DIR.rglob("*.py")):
        imported = _top_level_imports(path.read_text())
        hit = imported & BANNED_TOP_LEVEL_MODULES
        if hit:
            violations[str(path.relative_to(CONTRACT_DIR))] = hit

    assert violations == {}, f"contract/ files import banned UI/platform modules: {violations}"
