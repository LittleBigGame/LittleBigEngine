# LittleBigEngine coding standards — initial baseline

**Status: reviewable draft.** The uploaded project has no pre-existing `AGENTS.md`, standards file or test configuration. These guidelines were inferred from the code and the developer's instructions; **ask before declaring style decisions irreversible**. Existing code is a baseline, not automatic proof of the ideal format.

## Principles
- Python 3.13+ is the baseline for this archive (`type` alias syntax). Confirm targets before broad changes.
- Prefer **compact, explicit, modern Python**. Straightforward function composition over class hierarchies, wrappers or unnecessary design patterns.
- Type hints for public APIs, contracts and non-obvious structures. Do not add hints that obfuscate simple code.
- Keep names precise and consistent. Public naming changes require an approved migration plan.
- Favor readable linear flow; use short expressions where clear, but never sacrifice understanding for squeezing code onto one line.
- Comments/docstrings only where they explain non-obvious behavior, data invariants, critical performance constraints or external contracts. Avoid narrating obvious Python statements.
- Follow existing formatting in touched files unless explicitly approved to reformat more broadly. No unrelated clean-up.
- Prefer standard library. New libraries need a documented benefit, costs, compatibility and approval.
- Minimize allocations, reflection, string lookups and logging/copies in measured hot paths.
- Make side effects and mutation ownership explicit. Do not leak mutable internal data behind apparently read-only accessors.
- Errors must be actionable and consistent; don't silently swallow failures, return partially ready objects or claim missing dependencies are satisfied.
- Tests for relevant behavior, edge cases and regressions precede broad refactoring. Never turn tests off merely to get a green build.
- Avoid source duplication, speculative compatibility layers, magic dependency injection and global mutable service state.

## Code review questions
1. Is this the smallest change satisfying the stated behavior?
2. Does it belong in this module/layer?
3. Does an existing abstraction already do the job?
4. Are dependencies and ownership explicit?
5. Does it preserve public compatibility or document an intentional break?
6. Have tests and negative cases been run, not merely drafted?
7. Is it possible to explain this code to a maintainer six months later?

## Tooling policy
Run `python -m pytest -q` and `python tools/check_architecture.py`. Ruff is initially **strict for new support code** (`tools/`, `tests/`), not a blanket reformat of the legacy kernel. See `docs/TESTING.md` and `.github/workflows/quality.yml`. Expand enforcement in an approved cleanup phase after documenting baseline violations.
