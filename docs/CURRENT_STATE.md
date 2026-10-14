# Current State of LittleBigEngine

**Date:** 14 October 2026
**Status:** Phase 1 project persistence and deterministic startup loading are verified alongside the existing kernel and editor capabilities.

---

## 1. Verified Implemented Capabilities

The current integrated checkout is verified with **377 automated tests passing** (377 passed, 8 skipped planned tests, 0 failures). The architecture dependency checker passes across all 14 foundational modules.

### Phase 1: Project persistence and deterministic startup loading

Verified with **44 passing tests** in [`tests/test_project_persistence.py`](file:///f:/ModEngine/tests/test_project_persistence.py), with three future architectural tests explicitly skipped:

- `project.json` stores format version 1, project name, settings, and sorted persistent IDs for root entities.
- Existing projects load before demo-world population, preventing a new demo hierarchy on every startup.
- Projects without a manifest discover roots deterministically and write a manifest only after successful discovery and loading.
- Missing roots, children, and dependencies are reported through structured `BrokenReference` diagnostics without discarding otherwise usable resources.
- Invalid or unsupported manifests fail visibly and are not overwritten by startup bootstrapping.
- Fatal resource-graph loads and project loads roll back newly registered runtime resources.
- Dependencies and attached script/resource references belonging to nested child entities load recursively with the scene hierarchy.
- Orphaned entities whose recorded parent no longer exists are recoverable as discovered roots.
- Existing empty projects and projects with missing roots are not replaced with a new demo world during startup.
- Saving retains unresolved root references. A failed resource write prevents publication of an updated manifest, and a failed manifest write retains the previous in-memory manifest.
- Invalid UTF-8 resource files produce structured load errors and trigger rollback. A resource reached first as a dependency can still have its descendants loaded later through a hierarchy link.

### Example World application selection

`main.py` opens Application `2e4b8702e1e9514338d026d79d39f704` by persistent ID. The default world path is resolved beside `main.py`; `--world` and `--application-id` can select a different project/root. A missing manifest or selected root produces an error without creating a replacement application. Generic `Kernel.load_project()` still supports full-root loading and legacy discovery; its optional `root_storage_id` selects a single declared root while preserving unloaded roots on later saves.

The 62 older Application trees and 1,366 exclusive resources were removed from the active Example World into a recoverable archive. The full pre-cleanup world is backed up at `F:\ModEngine-backups\application-cleanup-20261014-202325\Example World`. One Application remains; startup mounts its 24 resources with no broken references. Unrelated/shared stored resources were preserved.

Deferred beyond Phase 1: manifest migration between future schema versions, generation-safe runtime handles, and file-watcher-driven manifest hot reload.

### Step 1: Tracked Mutations & Proxies
- **Transparent Dirty Tracking:** [`ComponentProxy`](file:///f:/ModEngine/LBE/proxy.py#L12-L165) wraps component state dicts. Any mutation via attribute set/delete (`proxy.speed = 10`, `del proxy.temp`), dictionary set/delete (`proxy["speed"] = 10`), or dict mutation methods (`pop`, `update`, `clear`, `setdefault`, `__ior__`) automatically marks the parent entity runtime ID dirty via [`Kernel.mark_dirty`](file:///f:/ModEngine/LBE/kernel.py#L134-L147).
- **Deep Recursive Tracking:** Reading a nested dictionary from a [`ComponentProxy`](file:///f:/ModEngine/LBE/proxy.py#L12-L165) returns another nested [`ComponentProxy`](file:///f:/ModEngine/LBE/proxy.py#L38-L45) pointing to the same root entity. Mutations on deeply nested structures (e.g., `proxy.stats.movement.speed += 5`) reliably mark the entity dirty and persist across sessions.
- **Ergonomic Entity Access:** [`EntityProxy`](file:///f:/ModEngine/LBE/proxy.py#L180-L310) provides seamless access to entity components via both attribute dot-access (`entity.transform.x`) and dictionary access (`entity["Transform"]["x"]`), featuring case-insensitive component name resolution, component addition (`entity.set("Health", {...})`), and component removal (`entity.remove("Health")` or `del entity.Health`).

### Step 2: Reference Preprocessor
- **Bracket Reference Syntax:** [`ReferencePreprocessor`](file:///f:/ModEngine/LBE/preprocessor.py#L40-L81) scans script source code for static references in the canonical format `<|ResourceType|StorageID.hex|>` (e.g., `<|0|a1b2c3d4...|>`) and transforms them into valid Python identifiers (`_0_a1b2c3d4...`).
- **1:1 Line Number Preservation:** Replacements are performed without changing line counts or shifting lines, guaranteeing that runtime tracebacks and syntax errors report exact line numbers matching original script source.
- **Lexical Safety:** References inside single-line comments (`# ...`), single-quoted strings, and multiline triple-quoted docstrings (`"""..."""` / `'''...'''`) are preserved without replacement. Malformed reference brackets raise a precise [`LBEReferenceSyntaxError`](file:///f:/ModEngine/LBE/preprocessor.py#L13-L25).
- **Runtime Binding:** [`RuntimeBinder`](file:///f:/ModEngine/LBE/preprocessor.py#L83-L104) and [`Kernel.resolve_proxy`](file:///f:/ModEngine/LBE/kernel.py#L907-L945) resolve referenced resources on demand into live [`EntityProxy`](file:///f:/ModEngine/LBE/proxy.py#L180-L310) instances or loaded resource envelopes.

### Step 3: Script Resources, Entity Attachment & Game Loop Execution
- **Script Resource Envelope:** Scripts are first-class engine resources ([`Script = 1`](file:///f:/ModEngine/LBE/types.py#L34)) created via [`Kernel.create_script_resource`](file:///f:/ModEngine/LBE/kernel.py#L1001-L1023), supporting inline code, external source paths, and declared component requirements (`requires: [...]`).
- **Entity Attachment:** Scripts attach to entities via [`Kernel.attach_script`](file:///f:/ModEngine/LBE/kernel.py#L1025-L1079) and detach via [`Kernel.detach_script`](file:///f:/ModEngine/LBE/kernel.py#L1080-L1126). Attached script references are stored canonically as 32-character hexadecimal Storage IDs in the entity's persistent JSON definition.
- **Execution with `self` Context:** Script functions (defaulting to `update`) execute with their parent entity bound as `self` (an [`EntityProxy`](file:///f:/ModEngine/LBE/proxy.py#L180-L310)), the current delta time `dt`, and the [`Kernel`](file:///f:/ModEngine/LBE/kernel.py#L14-L37) instance.
- **Component Requirement Verification:** Prior to script execution, declared component requirements are verified against the target entity. If any required component is missing, execution halts safely with [`MissingComponentRequirementError`](file:///f:/ModEngine/LBE/types.py#L28) rather than crashing with unhandled exceptions.
- **Engine Tick Loop:** [`Kernel.tick(dt)`](file:///f:/ModEngine/LBE/kernel.py#L1679-L1690) iterates over active entities with attached scripts and runs their update routines. Exceptions raised within individual scripts are captured and aggregated into an error list, allowing healthy entities to continue ticking uninterrupted.
- **Bytecode & Signature Caching:** Script compilation and preprocessor steps are cached in [`Kernel._script_cache`](file:///f:/ModEngine/LBE/kernel.py), eliminating redundant recompilations across frames and shared entities.

### Step 4: Entity Hierarchy, Queries & Spawning
Verified with **16 automated tests** in [`tests/test_hierarchy_and_spawning.py`](file:///f:/ModEngine/tests/test_hierarchy_and_spawning.py):
- **Scene Graph Hierarchy:** Bi-directional parent-child relationships managed via [`Kernel.add_entity_child`](file:///f:/ModEngine/LBE/kernel.py) and [`Kernel.remove_entity_child`](file:///f:/ModEngine/LBE/kernel.py), exposed ergonomically on [`EntityProxy`](file:///f:/ModEngine/LBE/proxy.py#L180-L310) through `entity.parent`, `entity.children`, `entity.add_child(...)`, and `entity.remove_child(...)`. Persistent storage maintains parent-child links across sessions.
- **Hierarchy Queries & Cycle Prevention:** [`EntityProxy.query_children`](file:///f:/ModEngine/LBE/proxy.py#L246-L265) filters direct or recursive child entities possessing required components, including cycle detection to safeguard against circular references.
- **World Queries:** Global component filtering via [`Kernel.query`](file:///f:/ModEngine/LBE/kernel.py#L1175-L1188), [`Kernel.query_proxies`](file:///f:/ModEngine/LBE/kernel.py#L1190-L1192), and `entity.world.query(*components)` via [`WorldProxy`](file:///f:/ModEngine/LBE/proxy.py#L167-L178).
- **Template Spawning & Cloning:** [`Kernel.spawn`](file:///f:/ModEngine/LBE/kernel.py#L1194-L1260) and `entity.spawn(...)` instantiate new entities from raw dictionary definitions or existing entity templates with deep copy component isolation, fresh unique Storage IDs, and optional immediate parent-child linkage (`as_child=True`).

### Step 5: Dear PyGui Desktop Editor Package (`editor/`)
Verified with **8 automated tests** in [`tests/test_editor.py`](file:///f:/ModEngine/tests/test_editor.py):
- **Headless Editor Controller:** [`EditorSession`](file:///f:/ModEngine/editor/session.py) cleanly isolates editor logic, entity selection state, component mutation pipelines, script attachment/detachment, subtree deletions, and storage operations from the GUI rendering layer.
- **Modular Panel Architecture:**
  - [`HierarchyPanel`](file:///f:/ModEngine/editor/hierarchy_panel.py): Tree view displaying root and nested entities with search filtering, selection handling, entity creation, child creation, and deletion.
  - [`InspectorPanel`](file:///f:/ModEngine/editor/inspector_panel.py): Dynamic inspector supporting component inspection, property editing (float, int, string, bool, dict), component addition/removal, and script attachment management.
  - [`StoragePanel`](file:///f:/ModEngine/editor/storage_panel.py): Project storage overview displaying resource counts, dirty indicators, save triggers, and reload actions.
- **Immediate-Mode UI & Non-Blocking App:** [`EditorApp`](file:///f:/ModEngine/editor/app.py) wraps Dear PyGui with custom dark styling ([`theme.py`](file:///f:/ModEngine/editor/theme.py)), status bar notifications, and non-blocking frame stepping (`start_non_blocking()`) for headless test automation.

### Step 6: Stable Function Identity & Cross-Script Callables (ADR-013)
Verified with **43 automated tests** in [`tests/test_script_references.py`](file:///f:/ModEngine/tests/test_script_references.py) and [`tests/test_proxy_mutation.py`](file:///f:/ModEngine/tests/test_proxy_mutation.py):
- **Permanent Function Identity:** Functions defined as `def _fn_<id>(self, ...): # <human_display_name>` have stable identity `_fn_<id>`. Refactoring human display names in comments never breaks callers or saved scenes.
- **AST Symbol Indexing:** [`extract_script_symbols`](file:///f:/ModEngine/LBE/preprocessor.py) extracts symbol-to-comment mappings automatically on script creation and modification.
- **Cross-Script Invocation:** Scripts reference functions via `<|1|script_hex|>._fn_<id>`, preprocessed into native Python attribute dispatch `_1_script_hex._fn_<id>`.
- **ScriptProxy & Binding:** [`ScriptProxy`](file:///f:/ModEngine/LBE/proxy.py) provides cached module execution with dependency injection, supporting both symbol dispatch and human display name aliases (`proxy.<display_name>()`). [`BoundScriptProxy`](file:///f:/ModEngine/LBE/proxy.py) binds functions to entity targets.

### Step 7: Engine-Native UI Primitives & Function Event Binding (ADR-014)
Verified with **43 automated tests** in [`tests/test_ui_components.py`](file:///f:/ModEngine/tests/test_ui_components.py):
- **Core UI Schemas:** `UIContainer`, `UIButton`, `UISlider`, `UITextInput`, `UIText` with schema validation via [`Validate.ui_component`](file:///f:/ModEngine/LBE/integrity.py) wired into the entity component loop.
- **Headless Event Dispatch:** [`Kernel.trigger_ui_event`](file:///f:/ModEngine/LBE/kernel.py) inspects components for handlers (`on_click`, `on_change`), parses durable references, resolves callables, and invokes them with fallback signatures and exception containment.
- **Proxy Helpers:** `entity.click()` and `entity.trigger("on_click")` on [`EntityProxy`](file:///f:/ModEngine/LBE/proxy.py).

### Step 8: UI Subtree Separation & Dear PyGui Bridge System (ADR-014)
Verified with **21 automated tests** in [`tests/test_ui_bridge.py`](file:///f:/ModEngine/tests/test_ui_bridge.py):
- **UI Bridge Panel:** [`UIBridgePanel`](file:///f:/ModEngine/editor/ui_bridge.py) translates UI entity subtrees into live Dear PyGui layouts (`collapsing_header`, `group`, `add_button`, `add_slider_float`, `add_input_text`, `add_text`) with mount selection, callback wiring, cycle detection, and rebuild suppression.
- **Hierarchy Subtree Separation:** [`HierarchyPanel`](file:///f:/ModEngine/editor/hierarchy_panel.py) filters entities under `"All"`, `"Game World"`, and `"UI & Tools"`, eliminating cluttered hierarchies without hidden engine state.

### Step 9: Visual Pill Tokens in Inspector & Tooling (ADR-015)
Verified with **29 automated tests** in [`tests/test_pills.py`](file:///f:/ModEngine/tests/test_pills.py):
- **Pill Token Projections:** [`PillData`](file:///f:/ModEngine/editor/pills.py) and [`parse_reference_pill`](file:///f:/ModEngine/editor/pills.py) project raw hashes into visual badges (`[ 📄 ScriptName :: ⚡ FunctionName ]` or `[ 📄 EntityName ]`).
- **Interactive Tooling:** Click-to-inspect detail modals and `"⚡ Pick"` Function Picker popup in [`InspectorPanel`](file:///f:/ModEngine/editor/inspector_panel.py).
- **Storage Panel Functions Explorer:** `"⚡ Functions"` modal in [`StoragePanel`](file:///f:/ModEngine/editor/storage_panel.py) with reference copying and inline display name refactoring.
- **Lexical Refactoring:** [`rename_script_function_display_name`](file:///f:/ModEngine/editor/pills.py) tokenizes raw code for exact 1:1 column index alignment, updating the trailing comment without modifying `_fn_<id>`.

### Step 10: Bootstrapped Workstation, Card Trees, Multi-Inspector Active Focus & Lock, and Layered Context Menus (ADR-016)
Verified with **8 automated tests** in [`tests/test_bootstrapped_editor.py`](file:///f:/ModEngine/tests/test_bootstrapped_editor.py):
- **Bootstrapped Scene Graph & Root Scoping:** Default world structures an `Application` root containing `Game` (`Player` with `Excalibur`, `Goblin`, `GameGUI`) and `Editor` (`Hierarchy Panel`, `Inspector Panel`) subtrees. [`EditorSession.view_root_id`](file:///f:/ModEngine/editor/session.py) scopes tree views to isolate game entities or view the entire application.
- **Procedural Vector Geometry:** Crisp vector chevrons, radio dots, window chrome, branch connector lines, dashed selection rectangles, and lock icons rendered via [`editor/vector_glyphs.py`](file:///f:/ModEngine/editor/vector_glyphs.py) directly into Dear PyGui drawlists.
- **Card-Based Tree Nodes & Auto-Hiding Flyouts:** Clean bordered cards (`#181818` fill, 1px border, electric blue `#0078FF` selection) with auto-hiding corner chrome (`▷` flyouts with Close, Minimize, Maximize) and tooltips.
- **Multi-Instance Inspector & Active Focus + Lock:** Dynamic inspector spawning ([`EditorApp.spawn_inspector`](file:///f:/ModEngine/editor/app.py)), active focus tracking in [`EditorSession`](file:///f:/ModEngine/editor/session.py), and lock pinning (`is_locked`) enabling side-by-side entity inspection.
- **3-Layer Context Menu & Zero-Button Clutter:** Complete elimination of static top/bottom button toolbars in favor of direct right-click manipulation: Layer 1 (Target Actions), Layer 2 (Panel Actions: this panel & other panels), and Layer 3 (Engine Global Actions).

### Step 11: Dynamic UIPanel Window Mounting & World-Space Overhead UI Billboards (ADR-017)
Verified with **25 automated tests** across [`tests/test_ui_components.py`](file:///f:/ModEngine/tests/test_ui_components.py), [`tests/test_ui_bridge.py`](file:///f:/ModEngine/tests/test_ui_bridge.py), and [`tests/test_overhead_ui_and_panels.py`](file:///f:/ModEngine/tests/test_overhead_ui_and_panels.py):
- **Dynamic `UIPanel` Window Mounting:** Entities in the ECS graph possessing `UIPanel` dynamically mount real floating Dear PyGui desktop windows, recursively rendering child UI entities (`UIContainer`, `UIButton`, `UISlider`, `UITextInput`, `UIText`). Custom developer tools and debug windows run standard LittleBigEngine function references with zero special "macro/tool" APIs. Internal workstation panels (`Hierarchy`, `Inspector`) with `"panel_type"` are disambiguated and protected from floating runtime window hijacking.
- **World-Space Overhead UI Billboards:** Child UI entities under game entities follow parent world translation $(x, y)$ plus local offset $(dx, dy)$ while **locking rotation at $0.0^\circ$** (screen-aligned billboard). Overhead UI children suppress duplicate body circles, selection rings, and phantom hierarchy lines. Nested containers stack children cleanly with proportional gap spacing across all camera zoom levels.
- **Lifecycle, Teardown & Persistence:** Windows clean up and delete from Dear PyGui when their parent entities are destroyed. Window close sets `minimized = True` on tracked proxies. End-to-end persistence roundtrip across independent kernel sessions verified.

### Step 12: Bootstrapped Subtree Architecture for Hierarchy & Inspector
Verified with **26 automated tests** in [`tests/test_hierarchy_inspector_subtrees.py`](file:///f:/ModEngine/tests/test_hierarchy_inspector_subtrees.py):
- **Full Subtree Population in ECS:** `Hierarchy Panel` populates `SearchInput` (`UITextInput`), `FilterBar` (`UIContainer` -> `AllFilter`, `GameFilter`, `ToolsFilter` with `UIButton`), and `TreeContainer` (`UIContainer`). `Inspector Panel` populates `HeaderBar` (`UIContainer` -> `TitleText` with `UIText`, `FocusBtn` and `LockBtn` with `UIButton`), and `ComponentContainer` (`UIContainer`).
- **Reactive Binding & Schema Invariants:** Modifying ECS child components updates panel hints and labels dynamically. Toggling inspector lock updates the `LockBtn` label and mutates `Panel.locked` on the parent panel entity adhering strictly to schema rules.
- **Viewport UI Selection Highlighting & Canvas Click Rule:** Selected GUI child entities render an electric blue (`#0078FF`, 2px) selection bounding box in the Scene View canvas drawlist. Left-clicking the viewport canvas skips overhead UI entities unless explicitly flagged with `canvas_selectable: True` or `selectable: True`, ensuring GUI elements are selected via the Hierarchy.
- **Procedural Vector Card Tree Presentation:** Card tree nodes render with procedural vector chevrons (`▽`/`▷`), vector radio dots (`○`/`◉`), and L-shaped branch connector lines, with unified expansion state tracking (`collapse_all` / `expand_all`).

---

## 2. Resolved Historical Defects & Architecture Hardening

1. **P0 Dirty-Tracking & Single Controlled Mutation Path (Resolved — Phase 3):**  
   Previously, calling `get_component` or `get_resource` exposed raw dictionaries. Direct in-place edits bypassed dirty tracking, leading to silent data loss on save. `ComponentProxy` also inherited `dict` and maintained duplicate state.  
   *Resolution:* [`ComponentProxy`](file:///f:/ModEngine/LBE/proxy.py) refactored to `collections.abc.MutableMapping` wrapping a single authoritative store. Direct in-place writes on `get_components` or `get_resource` are blocked via deep `MappingProxyType` and `ReadOnlySequence`. Nested sequences use `TrackedList` (`MutableSequence`) to intercept in-place mutations and dirty the entity.
2. **ABA Runtime Handle Recycling Hazard (Resolved — Phase 2):**  
   Deleting an entity and recycling its integer runtime ID allowed surviving proxies, callbacks, selections, or Dear PyGui tags to silently operate on an unrelated new entity.  
   *Resolution:* Packed 64-bit generation handles `(generation << 32) | slot_index`. Deletion advances the slot generation and frees the slot. Surviving proxies report authentic `AttributeError("Entity ... has been destroyed")` via `.is_alive` lifecycle guards.
3. **Graph Operations & Dual Hierarchy Authority (Resolved — Phase 4):**  
   Envelope `children` and entity data `children` previously risked divergence. Reparenting and deletion could fail mid-operation leaving orphan subtrees.  
   *Resolution:* Hierarchy authority strictly unified between envelope and data across creation, reparenting, and removal. Two-phase staged reparenting with cycle detection and snapshot rollback. Cascade subtree deletion advances slot generations for all descendants. Atomic resource saves via `.tmp`, `os.fsync`, and `os.replace`. Context manager `with kernel.transaction():` enables atomic batch mutations with rollback.
4. **Core / UI Boundary Separation & Slider Validation (Resolved — Phase 5):**  
   `Kernel` previously imported UI schemas directly and owned large UI event dispatch logic.  
   *Resolution:* UI schemas (`UI_SCHEMAS`, `UI_COMPONENT_NAMES`, `UI_COMPONENT_ALIASES`, `UI_EVENT_HANDLER_REGEX`) and `ValidateUI` moved to `LBE/ui.py`. `LBE/integrity.py` delegates and re-exports for backward compatibility. Slider validation enforces `min <= max` and `min <= value <= max`. Event dispatch validates generation handles and bubbles unhandled events up the parent chain.
5. **Script Reload Rollback & Detached View Safety (Resolved — Phase 6):**  
   Live reloading scripts on syntax error previously corrupted in-memory modules or left half-activated state. Detached component views masked `AttributeError` from descriptor getters.  
   *Resolution:* Three-stage compilation pipeline (`compile -> validate -> activate`) with rollback to `_last_good_script_modules[script_id]` and snapshot restoration on error. Masking bug fixed in `ComponentProxy.__getattr__`.
6. **Command Queue Typing & Logging Filter (Resolved — Phase 7):**  
   `LBE/Queue.py` referenced undefined types `CommandID`, `CallerID`, `ReceiverID`. Hot-path logging allocated records even when filtered.  
   *Resolution:* Explicit type aliases `(CommandID = str, CallerID = RuntimeID, ReceiverID = RuntimeID)`. `Logger.is_enabled` runs before `LogRecord` allocation. Editor layout configuration moved to `self.kernel.folder_location / "editor_layout.ini"`.

---

## 3. Remaining Future Capabilities Backlog (Deferred Stubs)

The remaining 8 skipped tests are planned future stubs not required for prototype stability:
1. 3D billboard matrix projection for overhead UI under perspective camera.
2. Dynamic runtime docking state persistence for UIPanel windows across external DCC sessions.
3. Preprocessor AST automatic call-site refactoring when a function symbol UID is renamed.
4. Manifest schema version migration pipeline (v1 -> v2+).
5. Two-way reactive data binding between ECS components and DPG input fields without focus interruption.
6. Undo/Redo stack for UI bridge widget modifications.
7. Custom Dear PyGui widget component plugin registration.
8. Drag-and-drop hierarchy card re-parenting in the GUI.
