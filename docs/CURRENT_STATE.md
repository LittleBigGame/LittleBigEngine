# LittleBigEngine — current implementation

Date: 15 October 2026. This describes verified behavior, not every future design proposal in the architecture documents.

## Stabilization phases

| Phase | Implemented result |
| --- | --- |
| 1 — Project persistence | Version-1 manifest, deterministic legacy root discovery, structured broken-reference diagnostics, fatal-load rollback and startup by persistent root ID. |
| 2 — Runtime identity | Generation-aware handles invalidate deleted entities, scripts, callbacks and proxies. Allocation high-water marks survive rollback so aborted handles are never reissued. |
| 3 — Controlled mutation | Immutable resource reads; tracked component mappings and nested lists use one authoritative store. Detached views fail visibly instead of silently losing writes. |
| 4 — Graph transactions | Validated reparenting, cycle prevention, cascade deletion, rollback of batch mutations and staged multi-resource saves. Rollback restores existing containers in place, preserving working component references. |
| 5 — Responsibility boundaries | The Kernel façade retains public entry points and owns the state; registry, storage, world, script and UI modules implement separate capabilities. UI schemas and validation live in the UI module. |
| 6 — Script activation | Compile and bind before activation; failed reloads retain the last working module and expose diagnostics. Kernel state modified by rejected activation is rolled back. Source edits retain inline/external mode. |
| 7 — Editor reliability and overhead | Failures appear in a bounded error history and status bar. Reload-all is transactional and GUI reload requires confirmation when dirty. Logging filters before allocation and bounds history; hierarchy registry leaks and duplicate selection rebuilds are fixed. |
| 8 — Tooling and handoff | Production, editor, tests and tools pass Ruff. All engine modules are checked for forbidden GUI/backend imports. Package metadata, optional editor/dev dependencies, an installable launcher and a normal README are present. |
| 9 — Pure-UUID Exports & Property Components | Functions export under 128-bit hex UUIDs (`@export`). Dynamic `Property` components support computed properties, converters, and references with dynamic evaluation, cycle detection, read-only enforcement, and DPG inspector presentation. |
| 10 — Showcase Mini-Game | "The Dungeon of Alchemia" in `Example World` with WASD/arrow keyboard input, linked multi-orbit physics (`Excalibur`, `OrbOfPower`, `ShieldSatellite`), reactive enemy AI with spatial state transitions, and an interactive `AlchemistToolkit` desktop HUD. |

All stabilization phases and feature extensions through Phase E are implemented.

## Verification

- Full suite: **441 passed, 12 skipped**, no failures or unexpected passes.
- Ruff: **passed** across `LBE editor tools tests main.py`.
- Architecture import check: **passed**, all 14 engine modules.
- Independent architecture review: **PASS**, no unresolved critical or major findings.
- Real Dear PyGui smoke check on an isolated copy: hidden viewport and Hierarchy, Inspector and Scene panels created successfully, then torn down.
- A core wheel built successfully without third-party runtime dependencies. The editor remains an optional Dear PyGui dependency.
- Local diagnostic measurement: 100,000 component reads in 0.1249 seconds; 100 queries over 1,000 entities in 0.0615 seconds; zero retained trace records at the default log level. These are workstation measurements, not portable performance guarantees.

See [TESTING.md](TESTING.md) for commands and scope.

## Active application

`main.py` opens `Example World` beside its source file and Application `2e4b8702e1e9514338d026d79d39f704` by persistent ID. `--world` and `--application-id` select a different existing project/root. Missing selected data reports an error without creating another Application.

The retained graph contains 24 resources, including 23 entities, with zero broken references. The 62 old Application trees and 1,366 exclusive resource files were archived during the earlier cleanup. Unrelated/shared files remain stored but are not mounted by the default startup.

Full pre-cleanup backup: `F:\ModEngine-backups\application-cleanup-20261014-202325\Example World`.

## Contracts and practical limits

- Persistent references use 128-bit IDs serialized as 32-character hexadecimal strings. Runtime handles are temporary and must not be saved as references.
- Read access uses immutable projections. Use tracked proxies or explicit mutation methods for writes. Retrieve a new view after an intentional component replacement or resource reload.
- Public operations return `Error` for expected failures. The transaction context manager rolls back on exceptions; callers must raise a returned error to abort a manually composed transaction.
- Hierarchy envelope fields are maintained as a compatible serialized projection of entity hierarchy data. Existing saved shapes remain readable; this phase does not introduce a schema migration.
- Individual files use flush/fsync and atomic replacement. Batch saves stage resources and the manifest, restore earlier publications on an ordinary write failure, and retain a recovery folder if restoration itself fails. This is not a crash-recovery journal or a concurrent-writer protocol.
- Scripts execute as trusted Python in the host process. Exceptions and failed reloads are contained; infinite loops, native crashes, arbitrary filesystem effects and process termination require a separate preview process. Process isolation is a future capability, not an implemented sandbox.
- Generic queries still scan resources. Optimize indexes only against measured project workloads.

## Future features

The eight skipped tests cover:

1. Drag-and-drop hierarchy reparenting in the GUI.
2. Perspective-camera 3D billboard projection.
3. Dynamic UIPanel docking restoration.
4. Automatic call-site refactoring after changing a function symbol ID.
5. Migration from manifest version 1 to a future schema.
6. Full two-way UI binding without focus interruption.
7. UI undo/redo.
8. Custom Dear PyGui widget registration.

Additional future work includes process-isolated preview, crash-recovery journaling and concurrent project access. Historical review documents describe earlier snapshots and are not authority over this implementation.
