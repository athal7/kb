"""Import-boundary guard for kb.core.

core/ is the pure-Python, UI-agnostic layer. It must never import Textual (the TUI
framework) or any of the macOS ObjC bridging modules (objc, EventKit, Cocoa,
Foundation) that platform/ and ui/ depend on. Static AST analysis catches violations
even behind a try/except, without needing the banned packages installed.
"""

from __future__ import annotations

import ast
from pathlib import Path

BANNED_TOP_LEVEL_MODULES = {"textual", "objc", "EventKit", "Cocoa", "Foundation"}

CORE_DIR = Path(__file__).resolve().parents[2] / "src" / "kb" / "core"


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


def test_core_never_imports_ui_or_platform_modules():
    violations: dict[str, set[str]] = {}
    for path in sorted(CORE_DIR.rglob("*.py")):
        imported = _top_level_imports(path.read_text())
        hit = imported & BANNED_TOP_LEVEL_MODULES
        if hit:
            violations[str(path.relative_to(CORE_DIR))] = hit

    assert violations == {}, f"core/ files import banned UI/platform modules: {violations}"
