# Current State of LittleBigEngine

**Date:** 13 October 2026  
**Status:** Core Kernel, Tracked Proxies, Reference Preprocessor, Entity Script Execution, Hierarchy & Queries, Spawning, Dear PyGui Editor, Stable Function Identity, Engine-Native UI Subtrees, UI Bridge, Visual Reference Pill Tokens, Bootstrapped Workstation, Dynamic UIPanel Windows, and World-Space Overhead UI Billboards verified.

---

## 1. Verified Implemented Capabilities

The LittleBigEngine codebase is verified with **259 automated unit tests** passing in [`pytest`](file:///f:/ModEngine/tests) (259 passed, 21 skipped planned tests, 1 xpass):

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

## 2. Resolved Historical Defects

1. **P0 Dirty-Tracking Bug (Resolved):**  
   Previously, calling `get_component` or `get_resource` exposed raw dictionaries. Direct in-place edits (e.g. `comp["current"] = 50`) bypassed dirty tracking, leading to silent data loss on save. Resolved: [`Kernel.get_component`](file:///f:/ModEngine/LBE/kernel.py#L647-L688) returns a tracked [`ComponentProxy`](file:///f:/ModEngine/LBE/proxy.py#L12-L165) that automatically invokes [`Kernel.mark_dirty`](file:///f:/ModEngine/LBE/kernel.py#L134-L147).
2. **Nested Dictionary Mutation Bug (Resolved):**  
   Modifications to sub-dictionaries inside components (e.g. `entity.stats.movement.speed = 12`) previously failed to dirty the parent resource. Resolved: [`ComponentProxy.__getitem__`](file:///f:/ModEngine/LBE/proxy.py#L36-L45) recursively wraps returned child dictionaries in child proxies bound to the same root entity.

---

## 3. Remaining Known Issues & Planned Work

1. **Command Queue Prototype Cleanup:**  
   [`LBE/Queue.py`](file:///f:/ModEngine/LBE/Queue.py) contains a rudimentary [`CommandQueue`](file:///f:/ModEngine/LBE/Queue.py#L4-L12) prototype. A formal queue lifecycle and command dispatch pipeline remain to be specified and integrated.
2. **Transactional Dependency Graph Loading:**  
   If a nested child resource fails validation or disk read during recursive graph loading, resources loaded prior to the failure are not currently rolled back transactionally.
3. **Generation-Safe RuntimeID Recycling:**  
   Entity [`RuntimeID`](file:///f:/ModEngine/LBE/types.py#L6) allocations currently use incrementing counters. Stale runtime handles referencing destroyed entities require generation checks or slot handles (as proposed in ADR-008).
4. **Hot-Reload Rollback on Script Syntax Error:**  
   Live reloading of modified script source code should maintain the previous valid bytecode if new source contains a syntax error.
