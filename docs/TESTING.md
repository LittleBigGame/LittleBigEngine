# Verification gates and test roadmap

## Currently executable (this ZIP)

From the project root (Python **3.13+**):

```bash
python -m pip install pytest ruff
python -m pytest -q
python tools/check_architecture.py
ruff check tools tests
```

The package's own imports use modern `type` syntax; older Python interpreters will fail to parse it.

- `tests/test_kernel_baseline.py`: smoke-tested existing entity create/set/save/reload and two-way IDs; includes explicitly **xfail** known defects. `xfail` is not a fix or proof the defect has disappeared.
- `tests/test_api_contract.py`: checks selected currently exposed surface signatures, to detect accidental API removals until an approved migration.
- `tests/test_project_persistence.py`: verifies the format-version-1 project manifest, deterministic legacy root discovery, startup idempotency, broken-reference diagnostics, recursive child dependencies and fatal-load rollback.
- `tools/check_architecture.py`: AST-based check for forbidden dependencies in the kernel/integrity/types, not a general architecture theorem prover.
- GitHub Actions runs these checks when code is pushed or a PR is opened. It does not itself enforce branch protection: configure required checks and reviews in GitHub settings if desired.
- Ruff checking is initially restricted to support code (`tools/` and `tests/`) because legacy source has not been lint-refactored.

## Known failing behaviors to fix with tests
1. Mutating a returned component dictionary bypasses dirty tracking and save.
2. A failed recursive dependency load can leave registered parent resources.
3. `bytes` IDs in `dependencies` can fail JSON serialization.
4. `LBE/Queue.py` import fails for undefined type aliases.
5. Runtime handle recycle (future) must not allow stale references.
6. Logging must be optional in hot paths and profiling must demonstrate costs.

## Required future tests (not possible with today's archive)
- Exported reusable function registry and cross-system calls.
- Reference parser rejects malformed syntax/unknown IDs/wrong resource kind; preserves strings and comments.
- Rename/move function without breaking a UID-based call site; signature change is detected.
- Save and reload JSON with versioned schemas, migrations and canonical IDs.
- Dependency cycles, optional links, failed load rollback and duplicate IDs.
- Runtime handle generation and registry-scope isolation.
- Hot reload with rollback, isolated runtime preview failure, editor still usable offline.
- Benchmarks for high-frequency ECS queries and reference-call overhead.

## Completion evidence
A code change requires recorded commands and actual results. A subagent returns tests it ran; a separate test agent reproduces or expands coverage. Review findings are classified `CRITICAL`, `MAJOR`, `MINOR` or `PASS` with file-level evidence. Any unresolved critical finding blocks integration; major findings require developer decision. Never treat documentation alone as a passing quality gate.

### Phase 1 persistence verification — 14 October 2026

Run from `F:\ModEngine` using the local Python 3.14 environment:

- `.venv\Scripts\python.exe -m pytest tests\test_project_persistence.py -q -p no:cacheprovider`: **40 passed, 3 skipped**.
- `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`: **325 passed, 21 skipped, 1 xpassed**.
- `.venv\Scripts\python.exe tools\check_architecture.py`: **passed**.
- `.venv\Scripts\ruff.exe check tools tests\test_project_persistence.py`: **passed**.
- `git diff --check`: **passed**.

Independent read-only review: **PASS**, with no unresolved critical, major or minor findings in the persistence changes. Separate probes checked dependency-first hierarchy traversal with cycles and finite depths, and rollback after invalid UTF-8 while preserving an existing registry.

The full `ruff check tools tests` gate remains failing with **69 existing findings outside the persistence suite**. The queue import XPASS remains a known annotation/lifecycle concern. The three persistence skips cover future schema migration, project unload/reload handle safety, and file-watcher-driven manifest reload. These results do not verify the desktop UI manually or implement the wider architecture roadmap.

### Application cleanup and pinned startup — 14 October 2026

After adding selection by persistent ID and cleaning duplicate application data: persistence suite **44 passed, 3 skipped**; full integrated suite **331 passed, 19 skipped, 1 xpassed**. Architecture and scoped Ruff checks pass. Independent review of root selection and saving unloaded roots: **PASS**. A zero-tick startup from a different working directory opened only the retained Application's 24 resources. A full backup was hash-verified before archiving duplicate files; retained resource bytes were checked against that backup after cleanup.
