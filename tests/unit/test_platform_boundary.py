"""Import-boundary guard for kb.platform's pure-Python contract modules.

platform/ will eventually host a real EventKit-backed service that legitimately
imports objc/EventKit — that module is expected to exist in a future task and is
intentionally NOT covered here. This guard only pins down the modules that make
up the swappable-backend contract itself (models, interfaces, fakes): they must
stay pure Python so ui/ can develop and test against them without EventKit
installed or a TCC prompt firing. Unlike core/'s guard, this one is an explicit
filename allowlist rather than a directory glob, precisely so the future
EventKit-backed module can be added to platform/ without silently failing this
test — a reviewer has to consciously decide whether it belongs on the list.
"""

from __future__ import annotations

import ast
from pathlib import Path

BANNED_TOP_LEVEL_MODULES = {"textual", "objc", "EventKit", "Cocoa", "Foundation"}

PLATFORM_DIR = Path(__file__).resolve().parents[2] / "src" / "kb" / "platform"

# Pure-Python contract modules only. Do NOT add a future EventKit-backed
# implementation module here — it will legitimately import objc/EventKit.
PURE_PYTHON_MODULES = {"__init__.py", "models.py", "interfaces.py", "fakes.py"}


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


def test_platform_contract_modules_never_import_objc_or_ui_modules():
    violations: dict[str, set[str]] = {}
    for name in sorted(PURE_PYTHON_MODULES):
        path = PLATFORM_DIR / name
        if not path.exists():
            continue
        imported = _top_level_imports(path.read_text())
        hit = imported & BANNED_TOP_LEVEL_MODULES
        if hit:
            violations[name] = hit

    assert violations == {}, f"platform/ contract modules import banned modules: {violations}"
