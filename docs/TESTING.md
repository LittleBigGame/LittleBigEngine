# Verification

Date: 15 October 2026. Python 3.13+ is required. Verification was run with Python 3.14.4 on Windows.

## Commands

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\ruff.exe check LBE editor tools tests main.py
.\.venv\Scripts\python.exe tools/check_architecture.py
git diff --check
```

Install the declared development tools with `python -m pip install -e ".[dev]"`; add the `editor` extra for Dear PyGui.

## Latest results

- Full integrated suite: **384 passed, 8 planned skips**, no failures or unexpected passes.
- Ruff: **passed** across engine, editor, tests, tools and launcher.
- Architecture checker: **passed**, all 14 engine modules. GUI/editor/backend imports are rejected in engine code.
- Independent review: **PASS**, no unresolved critical or major findings within the stabilization changes.
- Packaging: **passed**, a `littlebigengine-0.1.0-py3-none-any.whl` built from an isolated source copy.
- Real Dear PyGui setup: **passed** on a temporary copy of the retained world. A hidden viewport and the Hierarchy, Inspector and Scene panels were created and torn down. This verifies real bindings and lifecycle setup, not a full visual/user-interaction audit.
- Default startup from another working directory: selected Application ID loaded 24 resources, including 23 entities, without creating a demo world.

## Important regression coverage

- `test_project_persistence.py`: manifest validation, discovery, broken references, selected-root startup, missing-root preservation and fatal load rollback.
- `test_transactional_graph.py`: parent/child consistency, cycle prevention, subtree deletion, transaction rollback and write/replace failure injection.
- `test_hardening.py`: last-working-module fallback, recovery, source-write failure, external source mode, transactional identity high-water marks, cached component reference preservation, editor errors, dirty-reload confirmation, bounded logging and batch publication rollback.
- `test_proxy_mutation.py`: immutable reads, tracked nested lists/maps, stale handles and durable writes.
- Script/UI/editor suites: callable identity, reference preprocessing, event dispatch, panel lifecycle and editor-session behavior.

The old Queue import xfail was replaced by active coverage after correcting its type aliases. Eight feature stubs remain intentionally skipped; see [CURRENT_STATE.md](CURRENT_STATE.md).

## Independent review findings resolved

The reviewer reproduced two defects beyond the earlier test suite: a handle from an aborted replacement could be reissued later, and restoring copied resource dictionaries detached views held by the retained working script module. Allocation high-water marks now survive every rollback. Snapshot restoration repairs the original nested dictionaries/lists in place. New regression tests cover both cases; independent nested-rollback probes passed.

## Performance measurement

A local diagnostic over 1,000 entities measured 100,000 component reads in 0.1249 seconds and 100 component queries in 0.0615 seconds, with zero trace records retained at the default INFO level. No portable timing threshold or claim of constant-time queries is implied.

## Completion policy

Run tests appropriate to the changed behavior, then the full suite, lint and architecture checks. Add failure-path coverage for reproducible defects. An independent reviewer must inspect the actual changes without implementing their own fixes. Critical findings block completion; major findings require resolution or a recorded developer decision.

Tests use temporary projects. Do not run scratch experiments or project scripts against the active world as verification. A successful test run does not establish process isolation, crash recovery, safe concurrent writers or future schema migration.
