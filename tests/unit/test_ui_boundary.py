"""Import-boundary guard for kb.ui.

ui/ is expected to import Textual freely — that's its job. It must never import
the macOS ObjC bridging modules (objc, EventKit, Cocoa, Foundation) directly; it
should only ever talk to Calendar/Reminders through the CalendarService/
RemindersService Protocols in platform/interfaces.py. That keeps the real
EventKit-backed service (a future task) swappable for FakeCalendarService/
FakeRemindersService without touching any UI code. Static AST analysis catches
violations even behind a try/except, without needing the banned packages
installed.
"""

from __future__ import annotations

import ast
from pathlib import Path

BANNED_TOP_LEVEL_MODULES = {"objc", "EventKit", "Cocoa", "Foundation"}

UI_DIR = Path(__file__).resolve().parents[2] / "src" / "kb" / "ui"


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


def test_ui_never_imports_objc_bridging_modules_directly():
    violations: dict[str, set[str]] = {}
    for path in sorted(UI_DIR.rglob("*.py")):
        imported = _top_level_imports(path.read_text())
        hit = imported & BANNED_TOP_LEVEL_MODULES
        if hit:
            violations[str(path.relative_to(UI_DIR))] = hit

    assert violations == {}, f"ui/ files import banned ObjC bridging modules: {violations}"
