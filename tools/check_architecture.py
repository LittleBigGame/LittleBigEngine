"""Fail if foundational LBE modules import forbidden application-layer dependencies."""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_FILES = tuple(sorted(p for p in (PROJECT_ROOT / "LBE").glob("*.py") if p.is_file()))
FORBIDDEN_ROOTS = {
    "pygame", "PyQt5", "PyQt6", "PySide2", "PySide6", "tkinter",
    "editor", "rendering", "graphics", "physics", "audio", "gui",
    "dearpygui", "raylib", "pyray",
}


def forbidden_dependencies(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    errors = []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        for name in names:
            if name.split(".", 1)[0] in FORBIDDEN_ROOTS:
                errors.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: forbidden import {name}")
    return errors


def main() -> int:
    failures = [error for path in CORE_FILES for error in forbidden_dependencies(path)]
    if failures:
        print("Architecture boundary violations:\n" + "\n".join(failures))
        return 1
    print(f"Architecture dependency check passed ({len(CORE_FILES)} foundational modules).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
