# LittleBigEngine: full-repository understanding snapshot

## Metadata

- Agent: Codex
- Date: 2026-10-06
- Branch: `codex/uuid-kernel-gui`
- Commit: `ace82b86bb6d1787d0ab056db3fc5854935987fe`
- Working tree at inspection: tracked files clean; untracked user-owned `Projects/` preserved.
- Relevant tracker: issues #93 and #95; draft PR #94.

This describes that commit, **before** the requested no-compatibility cutover. Bradley explicitly approved a full repository read. All tracked engine modules, bundled templates, examples, tests, benchmark and documentation were read; local governance and the original attached architectural proposal were also read. Earlier compatibility-preserving instructions in that proposal are superseded by Bradley's latest instruction and issue #93's revised acceptance criteria.

## 1. Executive model

LBE is a Python engine whose editor is itself an application made from the engine's entities and behaviours. It is not a conventional collection of special GameObject, Tile and Widget classes. Components carry arbitrary application data; tags select roles; named relations and hierarchy connect entities; attached Python behaviours operate in isolated namespaces. Graphics, input, spatial indexing, file operations and editing tools sit above the generic runtime.

The current commit introduces persistent UUID-keyed typed items beneath this model, but does not complete the architectural transition. Most application code still calls legacy component/tag/relation/system/script collections and reads component values as entity attributes. The screenshot accurately exposes this gap: the default editor still presents the old split model.

The requested destination is one authoritative typed-item collection per entity, native item-only persistence, explicit UUID linking, disposable runtime handles and a unified item inspector. Existing user projects must not be silently upgraded or overwritten.

## 2. Module map

| Area | Responsibility |
|---|---|
| `src/lbe/core.py` | Entity lifetime, hierarchy, scoped queries, changes and frame scheduling; also legacy collection facades. |
| `items.py`, `linker.py`, `references.py` | UUID records and indexes; object registration, handles and inherited values; lexical typed source references. |
| `systems.py`, `scripts.py`, `events.py` | Compiled definitions, attachment instances, lifecycle, explicit script execution and subscription cleanup. |
| `assets.py`, `item_storage.py`, `project.py` | Asset UUID registry/cache, item encoding and project persistence/bootstrap; currently include legacy conversion. |
| `project_files.py`, `project_templates.py`, `history.py` | Recoverable file operations, template manifests/upgrades and undo commands. |
| `desktop.py`, `launcher.py`, `__main__.py`, `main.py` | Pyglet backend, input queue, graphical project picker and entry points. |
| `ui.py`, `text.py`, `syntax.py`, `completion.py` | Entity-based controls, text editing, highlighting/reference pills and static completion. |
| `space.py`, `dock.py`, `menus.py` | Derived spatial lookup, panel layout and entity-based menus. |
| `activity.py`, `effects.py` | Bounded diagnostic snapshots and behaviour observation. |
| `templates/editor/` | Default self-hosted editor and separate hierarchy, inspector, source, file, drawing, docking and logging behaviours. |
| `templates/demo/`, `templates/counter/`, `examples/` | Smaller executable examples and project templates. |
| `tests/`, `benchmarks/` | Runtime/editor regressions, synthetic desktop walkthroughs and measured workload comparisons. |

## 3. Actual public API

`Runtime.create` accepts identity, parent, tags, components and named component values. Entities expose `components`, `tags`, `relations`, `systems`, `scripts`, hierarchy properties, scoped `query`, explicit script `run`, and dynamic component attributes. These are implemented compatibility-era APIs, not the requested final API.

Entities additionally expose UUID identity, `items`, item lookup and typed iteration. Item records include Component, InheritedComponent, Tag, Relation, Parent, SystemInstance and ScriptInstance. Ordinary records are immutable declarations, though their stored Python values may be mutable. Behaviour instances carry live execution state.

System definitions compile Python once; instances own namespaces. Injected names include the owner entity, runtime, current system, query/create/resolve/destroy, assets, events, changes and backend services. Some injection still exposes old collection terminology. Literal component requirements and the legacy frame `run(dt)` path are still supported. Scripts use explicit `run(entity, ...)` and validate required components.

Typed references such as `<|Component:UUID|>` are lexically lowered before compilation, outside strings/comments. The editor additionally recognises older `asset(...)`, `resolve(...)` and asset-index source patterns. These older paths must be removed in the requested cutover rather than maintained as adapters.

## 4. Core boundary

Core owns generic lifetime, typed data, hierarchy, relations, queries, behaviour scheduling, observation and events. It does not own players, bullets, cameras, physics, editor panels or widget semantics.

Services provide graphics/input capabilities, asset access, spatial acceleration and project operations. UI and editor helpers interpret ordinary component conventions above Core. This keeps application decisions inspectable and replaceable without adding specialised runtime entity classes.

Current risks are the size of the legacy API surface and duplicated representations in persistence, rather than a player- or widget-specific Core class. A new native item API must not introduce another authoritative application graph or merely rename the old facades.

## 5. Data model

Runtime owns live entities by UUID. Each entity owns an Items mapping with UUID records and derived type/name indexes. Linker registers entity/item UUIDs and their owners. Hierarchy uses Parent records, with derived adjacency maintained by runtime. Incoming relations are indexed for destruction cleanup.

InheritedComponent declares a source item UUID and generic patches. Resolution follows the source through the linker and applies patches to a copy. Missing sources and cycles fail explicitly. Editing an inherited value preserves its declaration identity instead of mutating its source.

Handles combine slot, generation and runtime scope. They are runtime lookup accelerators, not persistent identities; stale and cross-runtime handles are rejected. Component mutation and structural changes publish observations. Nested mutable data requires the explicit edit/touch protocol to remain observable.

Destruction handles subtrees, stops behaviours/subscriptions, disconnects incoming references and unregisters identities. Creation under a destroying parent is disallowed. Arbitrary Python values are allowed at runtime, but persistence has a narrower supported-value contract.

## 6. Systems

Definitions cache compiled source; attachment instances have independent namespaces, lifecycle flags, subscriptions and bounded errors. Instances are distinct UUID objects even when sharing a definition. Lazy asset-backed scripts resolve through stable asset identity.

Frames snapshot scheduled attachments, update all eligible instances, then draw them. Attachment/reload during a frame takes effect in the next snapshot. Detached instances in a snapshot are skipped. Paused scopes suppress updates without suppressing drawing. Script instances are explicitly invoked, not automatically stepped as scheduled systems.

Reload and source/file relocation must preserve attachment UUID and ordering. Namespace isolation, lifecycle cleanup and error isolation are existing working guarantees; the cutover must not sacrifice them to simplify storage.

## 7. Execution flow

Entry point → graphical launcher or selected project → template/project/assets bootstrap → root application attachment → child editor/game entities → frame update snapshot → draw snapshot → backend presentation → lifecycle close.

The launcher is already graphical when running `main.py`; a PowerShell project-creation workflow is not required. It creates a project from a selected template. Therefore migrating the default template and launcher-facing bootstrap is essential to satisfying the request.

Project loading stages entities and resolves references before starting behaviours. Saves serialise supported application state and replace the project file atomically. Existing transient UI/runtime state is filtered according to project ownership.

## 8. Services and authority

- Graphics and Input are backend capabilities; pooled drawable objects and queued events are derived/runtime state.
- SpatialIndex accelerates ordinary position/size conventions; entity data remains authoritative.
- AssetRegistry owns persistent asset UUID/path associations. Compiled definition caches derive from files/content.
- PersistentGraph records project ownership across reparenting; it is a persistence policy, not a replacement runtime graph.
- UI owns interaction/rendering helpers and caches; controls remain entities with ordinary data.
- DockTree represents layout calculations and serialisable layout choices, not game-world ownership.
- TextBuffer owns editable text/cursor/undo state stored as a component value. Completion is static analysis; authored code is not executed to obtain suggestions.
- Activity and Effects retain bounded diagnostics/observations, not application truth.
- ProjectFiles owns recoverable filesystem transactions and UUID-aware source relocation.

## 9. Editor and self-hosting

The application creates editor chrome, viewport, Game, two sample rectangle entities and a camera. Independent attached behaviours drive hierarchy, inspector, source editing, file browsing, panel layout and logging. Source inspection exposes the editor's own entity graph. A walk/shoot demo is available as an optional action.

The inspector remains split into components, systems/scripts and links/hierarchy. It contains recent UUID and inheritance additions, but its backing calls and overall interaction model remain legacy. A unified typed-item inspector needs to make item type, UUID, value/source, inheritance provenance and behaviour status visible in one model.

Application bootstrap stores a SimpleNamespace of callbacks/control handles as component data. This is a wiring convenience, not a second entity hierarchy, but its size makes reload-sensitive callback cleanup important. Editor behaviour reload reuses controls where possible. Selection/focus/context menus use relations; transient controls must not leak into saved game ownership.

## 10. Tests and invariants

The suite covers lifetime, hierarchy, queries, subscriptions, frame snapshots, independent namespaces, reload, explicit scripts, assets, serialization failures, atomic saves, missing declarations, ownership, file undo, docking, selection, text input, reference pills, completion and default project creation. Existing GUI tests exercise source attachment/editing and events rather than only inspecting class existence.

Some assertions explicitly require old APIs, legacy-format migrations and the split inspector. Those must be replaced with native-contract assertions while retaining the underlying behavioural coverage. Important new checks are absence of legacy Entity APIs, item-only disk shape, unsupported-format rejection before writes, persistent item UUIDs through editor undo/reload and a launcher-created native default application.

Recorded pre-cutover verification: 314 unit tests passed; check/short headless entry points passed; a real Pyglet rendering walkthrough with synthetic input passed. This is not manual human GUI acceptance and is not evidence that the requested native cutover is complete. No full suite was rerun merely for this report.

## 11. Requirement compliance

| Requirement/group | Status at snapshot | Evidence/reasoning | Action/issue |
|---|---|---|---|
| Entity-first structure | Complies | Editor controls and gameplay objects use generic entities. | Preserve in #93. |
| Flat arbitrary components | Complies | Named values support arbitrary runtime Python data; serialization is explicitly narrower. | Preserve edit/touch observability. |
| Scoped queries | Complies | Owner/subtree scope and component/tag filters; no compulsory global query. | Preserve snapshot semantics. |
| Core gameplay/editor agnostic | Complies | Application conventions are above Core. | Avoid new specialised entity classes. |
| Components/data source of truth | Partial | Runtime Items is authoritative, but facades and persisted projections perpetuate duplicate contracts. | #93 native cutover. |
| Independent behaviour instances | Complies | Per-attachment namespace, lifecycle, errors and subscriptions. | Preserve UUID during reload. |
| Self-hosted editor | Partial | Entity-based editor is inspectable; much bootstrap wiring is Python helper state, and inspector remains legacy. | #93 unified item inspection. |
| Backend/API separation | Complies | Desktop capability supplied through runtime services. | Preserve headless testing. |
| Generic hierarchy and relations | Complies | Parent/relation records, derived indexes and destruction cleanup. | Native typed operations. |
| Explicit observations/events | Complies | Changes, scoped subscriptions and bounded diagnostics. | Keep mutation/cleanup invariants. |
| Persistent UUID item identity | Partial | Kernel/linker support exists; several editor transactions still reconstruct through old mappings. | #93. |
| Disposable handles, explicit missing links | Complies | Generation/scope checks and explicit resolution failure. | Extend native roundtrip tests. |
| Native item-only project format | Violates revised requirement | Version 3 writes items plus old split fields; migration helpers retain legacy input. | #93, remove adapters. |
| Default projects native end to end | Violates revised requirement | Launcher/templates/editor still use legacy access. | #93. |
| Diagnostics/performance discipline | Partial | Broad tests and benchmarks exist, but measured UUID transition regressions remain. | #95. |

Older normative documents describe the previous public API. Bradley has explicitly authorised replacing it; their generic engine philosophy still applies. This report does not silently redefine those documents.

## 12. Violations and architectural debt

### Incomplete native migration — #93

Problem: dynamic entity attributes and separate collection facades still dominate engine, templates and tests. Persistence additionally stores redundant split fields and supports old-format conversion.

Conflict/impact: the requested single typed-item contract is not what a new project exposes. Changing only kernel storage cannot make the default editor native. Recommended direction: migrate consumers directly, remove adapters, use a strictly validated native format and expose one typed-item inspector. Do not convert user Projects automatically.

### UUID transition overhead — #95

Problem: measured creation, reads, scheduling and serialization became slower; serialized size increased substantially. Impact: scaling and editor responsiveness. Direction: profile native paths, remove redundant serialization/projections, retain derived indexes and benchmark after cutover. Do not substitute speculative optimisations for measured evidence.

### Bootstrap and editor concentration — #93 risk, not an independent model violation

The application and inspector scripts are large, reload-sensitive wiring modules. Their helper state is an intentional bootstrap compromise, not proof of a parallel world model. Native migration should retain established interactions and reduce dependence on collection-specific transactions; unrelated wholesale restructuring would increase risk.

Existing #63/#64 track richer component presets and specialised property editing. They are optional editor features, not blockers for the native kernel contract.

## 13. High-risk areas

1. Converting dynamic attributes indiscriminately can damage backend, TextBuffer and helper-object attributes. Entity data access must be distinguished from ordinary Python state.
2. Reconstructing items during rename/undo/reload can silently break UUID source references.
3. Starting behaviours before registering all entities/items breaks forward linking.
4. Removing migration only after template initialization can mutate an unsupported project before rejecting it.
5. Persistent project ownership must remain independent of temporary UI reparenting and relations.
6. Changes to input capture, text reference atomicity, completion workers or callback cleanup can regress working editor interaction.
7. Merely renaming collection facades or inspector headings would repeat the current incomplete cutover.
8. Gameplay/UI semantics must remain above Core, including the walking/shooting example.

## 14. Performance model

Measured historical comparison (old `9f37a27` → this snapshot; milliseconds, workload labels from benchmark):

| Workload | Old | UUID snapshot |
|---|---:|---:|
| Create/destroy 1,000 entities | 23.316 | 111.925 |
| Query 1,000 entities ×20 | 31.473 | 36.489 |
| 20,000 value reads | 5.003 | 14.366 |
| Step 1,000 entities ×20 | 157.626 | 289.702 |
| Serialize 1,000 entities | 19.981 | 93.878 |
| RecordingGraphics editor frame | 11.980 | 19.726 |

Serialized bytes: 282,205 → 887,498. Both editor measurements had 205 entities. These are local benchmark observations, not universal guarantees or a fresh measurement in this report.

Obvious costs include UUID allocation/registration, facade dispatch, traversal/snapshot creation and duplicate project fields. Type/name indexes make direct named lookup constant-time on average; broad scoped queries still traverse candidates. Profiling previously implicated allocation, facade reads and serialization. The expected benefit of removing adapters is an inference until remeasured.

## 15. GitHub state

Canonical repository is connected. Issue #93 acceptance was updated to Bradley's strict native migration request; #95 remains the measured performance follow-up. Draft PR #94 owns this branch and must stay unmerged pending user testing. Other open draft work includes #87 (composable editor behaviours/scripts), #85 (visual polish), #80 (runtime audit/log) and #73 (project stabilization); #75 concerns asset-path recreation. Their overlap warrants checking before integration, not incorporating unrelated changes blindly. No milestones were returned by the repository milestone query.

## 16. Context-light entry points

- Core/items: `core.py`, `items.py`, `linker.py`; core/lifecycle/items tests.
- Behaviour execution: `systems.py`, `scripts.py`, `events.py`; systems/scripts/stabilization tests.
- Source links: `references.py`, `syntax.py`, `text.py`; references/text/syntax tests.
- Persistence/assets: `project.py`, `item_storage.py`, `assets.py`; project/assets/item-storage tests.
- File operations: `project_files.py`, `project_templates.py`; file-history, asset-rescan and nested-template tests.
- Default application: launcher, editor app/inspector/hierarchy/code-editor behaviours; launcher/editor/kernel-editor tests.
- Backend and layout: `desktop.py`, `ui.py`, `dock.py`, `space.py`; scene/ui/dock/space tests.
- Acceptance paths: desktop and kernel walkthrough scripts; distinguish synthetic input from manual testing.

## 17. Confidence and unknowns

High confidence in the current dependency graph and the reason the generated editor remains legacy: confirmed across source, templates, persistence and tests. This report matches the recorded tracked commit; no engine source changes occurred during the read. Issue metadata was updated separately.

Unknown until implementation/testing: final native API details, cutover performance, native GUI acceptance and compatibility of user-authored code with the intentionally breaking contract. User Projects were not inspected or modified. Historical successful tests must not be represented as verification of future edits. This snapshot is context, not authority over newer code or Bradley's instructions.
