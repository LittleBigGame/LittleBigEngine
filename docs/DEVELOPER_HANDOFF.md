# LittleBigEngine stabilization — developer handoff

Date: 15 October 2026

## Scope and status

The eight stabilization phases are implemented in the current local checkout. The work focused on making the existing LBE core and editor safer to operate and easier to extend. It did not implement the future feature backlog listed at the end of this document.

The checkout is on branch `main`. At the time this handoff was written, there are local modifications and new files in the working tree; the work has not been represented here as committed or pushed. Check `git status` before building on top of it. The detailed current behavior and verification snapshot is in [CURRENT_STATE.md](CURRENT_STATE.md), and runnable verification commands are in [TESTING.md](TESTING.md).

## Work completed

### 1. Project persistence and startup identity

- Project loading supports a version-1 manifest, deterministic discovery of legacy roots, structured diagnostics for broken references, and rollback when a fatal load fails.
- `Kernel.load_project(root_storage_id=...)` supports selecting one manifest-declared root. A selected missing or undeclared root fails explicitly; it does not fall back to another root.
- `main.py` chooses the default Application by persistent ID `2e4b8702e1e9514338d026d79d39f704`, using the `Example World` beside the source file. `--world` and `--application-id` permit explicit selection of another existing project/root.
- Saving preserves roots that are not currently loaded, rather than silently dropping them from the manifest.
- Earlier cleanup left one Application tree mounted in the default Example World. The other 62 Application trees and 1,366 exclusive JSON resources were moved into a recoverable backup. Shared/unrelated resources were preserved. The full pre-cleanup Example World backup is at `F:\ModEngine-backups\application-cleanup-20261014-202325\Example World`.

### 2. Runtime identity and stale-handle safety

- Runtime handles are generation-aware. A handle from a deleted or replaced entity, script, callback, or proxy is rejected rather than resolving to a later object that reused the same slot.
- Generation high-water marks are deliberately not rolled back with ordinary Kernel state. This prevents an identity allocated during an aborted transaction from being issued again later.
- Regression coverage exercises deletion/reuse, rollback, and failed script activation.

### 3. Controlled, single-source mutation

- Read APIs expose immutable projections. Writes go through tracked mappings/lists or explicit mutation APIs, all tied to the Kernel's authoritative resource state.
- Nested component lists and mappings are tracked. An old view remains attached to the original containers when a transaction rolls back, while a view detached by an intentional replacement or reload fails visibly.
- Resource creation canonicalizes persistent references and copies caller-provided data to avoid accidental mutable aliasing.

### 4. Graph operations and persistence transactions

- Hierarchy reparenting validates the target and prevents cycles. Cascade deletion and multi-resource mutations use rollback on failure.
- Rollback restores pre-existing dictionaries and lists in place, preserving previously obtained live component views.
- Batch saves stage resource files and the project manifest, publish the manifest last, and restore already-published files after an ordinary write failure. If restoration also fails, a recovery directory is retained and reported.
- Individual writes flush and sync temporary files before atomic replacement. Reload failures, including malformed JSON and I/O/encoding errors, become structured errors.
- The editor's reload-all operation is transactional. Dirty GUI reloads require an explicit discard-and-reload action.

These guarantees cover ordinary in-process failures. The implementation is not a crash-recovery journal and does not coordinate concurrent writers.

### 5. Core/editor responsibility boundary

- `LBE/kernel.py` is now a public façade of roughly 380 lines. It owns authoritative state and delegates capability work to `registry.py`, `storage.py`, `world.py`, `scripts.py`, `ui.py`, and `views.py`.
- These modules work against the Kernel's state; they do not establish a second authoritative application model.
- UI schemas and validation live in the headless engine UI module. `LBE/integrity.py` keeps compatibility re-exports.
- `LBE/__init__.py` has explicit exports. The architecture checker scans all 14 engine modules for forbidden GUI/editor/backend imports.
- Serialized hierarchy envelope fields remain a compatibility projection of hierarchy data. This work did not change the saved schema or create a migration.

### 6. Script activation and editing

- Script source is preprocessed/compiled and symbols are inspected before activation. Candidate activation runs against a Kernel snapshot; rejected activation restores its changes and leaves the last working module available when one exists.
- Reload diagnostics and failed source fingerprints are tracked. A successful source recovery clears stale diagnostics.
- Recursive activation and `SystemExit` are caught and reported in the relevant activation, run, and UI-event paths.
- `Kernel.update_script_source` validates source before applying it, retains inline versus external storage mode, and updates external files through a temporary file and atomic replacement.
- Editor function renaming uses that path for a real Kernel, avoiding accidental conversion of external scripts to inline scripts.

Scripts remain trusted Python executed in the editor process. Exceptions are contained, but there is no sandbox or process boundary. Infinite loops, native crashes, arbitrary filesystem side effects, and deliberate process termination are outside the current containment guarantees.

### 7. Editor reliability and runtime overhead

- Editor errors are reported through a bounded session error history, logging, and status feedback. Listener errors no longer disappear silently; other healthy listeners continue to run.
- Save, reload, mutation, UI-event, and script-reload failures are surfaced through the session/editor path.
- Dirty reload confirmation is shared by the storage panel and reload-all context menu.
- Duplicate selection subscriptions and a hierarchy registry retention leak were corrected.
- Dear PyGui layout state is stored under the selected project's folder rather than the process working directory.
- Logging defaults to INFO, checks the level before allocating records, and bounds retained history.
- A local diagnostic run measured 100,000 component reads in 0.1249 seconds and 100 queries over 1,000 entities in 0.0615 seconds, with no retained trace records at the default log level. These are local measurements, not performance guarantees. Querying remains a resource scan; indexing should follow representative workload measurements.

### 8. Tooling, packaging, and developer documentation

- Ruff passes over production code, editor, tools, tests, and `main.py`; existing test lint findings and undefined imports/annotations found during this work were corrected.
- `tools/check_architecture.py` checks all engine modules for forbidden UI/backend dependencies.
- `pyproject.toml` defines a setuptools build, the `littlebigengine` distribution, optional editor and development dependencies, and the `lbe` launcher.
- A wheel built and imported from an isolated install target. The core package has no mandatory third-party runtime dependency; Dear PyGui is optional for editor use.
- `README.md`, `docs/CURRENT_STATE.md`, `docs/TESTING.md`, and the current boundary section in `docs/ARCHITECTURE.md` describe setup, current behavior, test commands, and limits.
- Scratch material is excluded from the built packages and should be reviewed before execution; historical material was not removed as part of this work.

## Verification evidence

The latest recorded verification is:

- Full test suite: **384 passed, 8 skipped**, no failures or unexpected passes.
- Ruff: **passed** for `LBE editor tools tests main.py`.
- Architecture check: **passed** for all 14 engine modules.
- Independent read-only review: **PASS**, with no unresolved critical or major findings after fixes for handle reuse after rollback and cached component views after rollback.
- Dear PyGui setup smoke check on an isolated copy of Example World: project loaded, hidden viewport and Hierarchy/Inspector/Scene panels were created, and the app tore down successfully. This was a setup/lifecycle smoke check, not a manual visual interaction audit.
- Wheel build and isolated installation/import: **passed**; installed imports resolved from the isolated target and the configured Application ID was preserved.
- `git diff --check`: passed with only expected line-ending notices.

Re-run the commands in [TESTING.md](TESTING.md) when preparing a commit or changing these paths. The verification record is a snapshot of the checkout on the date above.

## Remaining work

The eight skipped tests describe future behavior, not failures in the completed stabilization scope:

1. GUI drag-and-drop hierarchy reparenting.
2. Perspective-camera 3D billboard projection.
3. Dynamic UIPanel docking restoration.
4. Automatic call-site refactoring when a function symbol ID changes.
5. Migration from manifest version 1 to a future schema.
6. Full two-way UI binding without interrupting text focus.
7. UI undo/redo.
8. Custom Dear PyGui widget registration.

Other explicit future capabilities are process-isolated script preview, crash-recovery journaling, and concurrent project access. These require separate designs because they expand the current failure/isolation or persistence contract.

Before merging or handing off to another developer:

- Review the complete diff and current Git status; the verification snapshot alone does not guarantee that every local edit is intended for one commit.
- Run the test and architecture commands from [TESTING.md](TESTING.md) against the exact commit candidate.
- Keep the skipped-feature list and the in-process trusted-script limitation visible in release notes until those capabilities change.

## User impact

The editor opens one explicitly selected Application by persistent ID, instead of choosing among duplicated Application trees. Missing selected data is reported rather than silently replaced with a generated demo. Saves and reloads have clearer failure behavior, script reload failures preserve the last working module where possible, and editor errors are easier to find. The saved hierarchy representation remains compatible with the current format.

## Developer impact

The Kernel's public role and implementation responsibilities are easier to locate, identity and mutation semantics have regression coverage, and storage/script/editor failures have clearer reporting paths. Packaging and setup are defined in project metadata and the README. Future work can be planned against the eight listed feature gaps and the three broader runtime/persistence capabilities, without treating them as delivered by this stabilization pass.
