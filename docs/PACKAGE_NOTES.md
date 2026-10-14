# Agent governance package — change record (11 October 2026)

## What changed
- Added root persistent `AGENTS.md` and editable design/decision/standards/testing/current-state documentation.
- Added five Antigravity 2.0 custom agent definitions, with conversational primary `lbe-lead`.
- Added two reusable agent skills (`lbe-change`, `lbe-review`).
- Added `ANTIGRAVITY_START_PROMPT.md`, `README_ANTIGRAVITY.md` and verification infrastructure.
- Added baseline test coverage and explicit xfail markers for two pre-existing defects.
- Added AST-based foundational import-boundary checker and a GitHub Actions quality workflow.

## What intentionally did not change
- The original seven `.py` source files and saved sample world JSON are **byte-for-byte unchanged**.
- No game engine implementation was rewritten, no known engine bugs were fixed, no new live ECS, editor, parser or subagent runtime was built.
- The existing 128-bit persistent ID format remains intact.
- No local Git history/branch protections, Antigravity user settings or installed models were changed.

## Excluded from new ZIP
Machine-specific or generated folders from original ZIP: `.git` skeleton, `.idea`, `.venv`, `.venv1` and `__pycache__`. Keep the original ZIP as a complete backup. Install Python dependencies in your own local environment.

## Executed verification
- Python 3.13: `python -m pytest -q` → **3 passed, 2 xfailed** (known failures, not fixes).
- `python tools/check_architecture.py` → **PASS** for current three foundational modules.
- Custom agent and skill YAML frontmatter: **7 files successfully parsed**.
- Python support tools/tests compiled with `compileall`: **PASS**.
- `ruff check tools tests`: **NOT RUN**, Ruff not installed in the generation environment. GitHub CI will run it after upload to GitHub and installing dev requirements.
- Actual Antigravity discovery/delegation: **NOT TESTED** from this container. Verify in your installed product following `README_ANTIGRAVITY.md`.
