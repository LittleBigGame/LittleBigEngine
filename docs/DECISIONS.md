# LittleBigEngine Architectural Decision Register

Record key choices here. Only **Accepted** decisions are binding. Agents must not rewrite an Accepted decision or the root governance document without the developer's explicit approval.

| ID | Status | Decision | Why / implications |
|---|---|---|---|
| ADR-001 | Accepted | Keep a tiny engine kernel (`LBE/`) independent of editor, GUI, physics and rendering | Limits coupling, keeps engine headless, embeddable, and testable |
| ADR-002 | Accepted (design direction) | Separate persistent identity from session-scoped runtime identity | Portable stable references without runtime lookup overhead |
| ADR-003 | Accepted (design direction) | Persist Python source + JSON metadata and references | Editable, inspectable, avoid CloudPickle as core storage |
| ADR-004 | Accepted (design direction) | Systems orchestrate reusable functions with stable export IDs | Functions can move/rename without breaking identity |
| ADR-005 | Accepted (design direction) | Editor can inspect stored project without running gameplay | Failure isolation, no compulsory bootstrapped game editor |
| ADR-006 | Proposed | Migrate current 128-bit UIDs to random 256-bit UIDs | Very low collision chance already; migration may outweigh benefits |
| ADR-007 | Accepted | Static reference grammar `<\|ResourceType\|StorageID.hex\|>` resolving to `_ResourceType_StorageID` with 1:1 line preservation | Unambiguous static resource binding, preserves exact traceback line numbers, eliminates runtime lookup overhead |
| ADR-008 | Proposed | Slot + generation 64-bit runtime handles | Stale-handle protection; initially sequential IDs suffice |
| ADR-009 | Accepted | `ComponentProxy` and `EntityProxy` with transparent dirty tracking | Eliminates silent unsaved mutations, provides natural Pythonic dot/dict syntax, and tracks nested sub-dictionaries |
| ADR-010 | Accepted | Build desktop editor in `editor/` using Dear PyGui with headless `EditorSession` controller | Decoupled native immediate-mode UI with GPU acceleration, leaving engine kernel 100% headless |
| ADR-011 | Proposed | Annotation-driven automatic component injection | Optional, benchmark and justify before kernel integration |
| ADR-012 | Accepted | Unified 3D `Transform` component; 2D as an orthographic slice of 3D space | Eliminates bifurcated 2D/3D math routines, unifies scene graph computations, enables mixed-dimension gameplay (parallax, 2.5D) |
| ADR-013 | Accepted | Stable Function Identity (`_fn_<id>` + trailing `# <display_name>`) and Cross-Script Callables | Refactoring display names never breaks callers or saved references; native Python attribute dispatch |
| ADR-014 | Accepted | Engine-Native UI Primitives & Dear PyGui Bridge System | Unified data-driven UI components for game HUDs and editor tools with headless kernel event dispatch |
| ADR-015 | Accepted | Visual Pill Token Projections in Inspector & Tooling | Raw reference hashes projected as interactive visual pills; safe comment refactoring |
| ADR-016 | Accepted | Bootstrapped Workstation, Card Trees, Multi-Inspector Active Focus & Lock, and Layered Context Menus | Zero-button workstation with crisp vector glyphs, root scoping, multi-instance inspectors with active routing/locking, and 3-layer context menus |
| ADR-017 | Accepted | Dynamic UIPanel Window Mounting & World-Space Overhead UI Billboards | UI entities with UIPanel mount as live desktop windows without special macro APIs; child UI entities billboard above parents at 0° rotation |

---

## Decision Records

### ADR-001 & ADR-010: Headless Engine Kernel and Dear PyGui Desktop Editor
- **Status:** Accepted
- **Date:** 11 October 2026
- **Context:** The engine requires an intuitive, responsive desktop editor for manipulating entities, inspecting components, editing scripts, and triggering persistence. However, coupling GUI libraries directly into the core engine kernel (`LBE/`) would destroy headless CLI execution, server simulation, and automated testability.
- **Choice:** Maintain `LBE/` as a strictly headless engine kernel with zero GUI or rendering dependencies. Build the desktop editor in an independent top-level package (`editor/`) powered by Dear PyGui. Decouple editor state and actions from the graphical interface via a headless [`EditorSession`](file:///f:/ModEngine/editor/session.py) controller.
- **Other options:**
  - Embedding GUI code directly into `LBE/` (rejected: violates separation of concerns, breaks headless testing and server execution).
  - Web/Electron-based editor (rejected: high memory footprint, slower startup, complex inter-process communication).
  - Tkinter / PyQt (rejected: Dear PyGui provides fast C++ immediate-mode rendering, native docking support, GPU acceleration, and a Pythonic API).
- **Consequences:** The engine remains lightweight, embeddable, and headless. The editor can be tested in automated CI pipelines using non-blocking headless frame stepping without opening windows.
- **Validation:** 8 automated tests in [`tests/test_editor.py`](file:///f:/ModEngine/tests/test_editor.py) verifying selection state, component mutation pipelines, panel synchronization, and headless frame execution.
- **Approved by developer:** Yes (11 October 2026)

---

### ADR-007: Reference Syntax Preprocessor and Identifier Transformation
- **Status:** Accepted
- **Date:** 11 October 2026
- **Context:** Scripts and systems need to reference persistent engine assets and entities across disk boundaries using stable Storage IDs, while avoiding cumbersome runtime lookup calls like `kernel.get_entity(bytes.fromhex("..."))` on every frame. Source code tracebacks and line numbers must remain preserved for debugging.
- **Choice:** Accept the angle-bracket pipe delimiter syntax `<|ResourceType|StorageID.hex|>` (e.g., `<|0|a1b2c3d4...|>`). The preprocessor transforms matches outside comments and string literals into Python identifiers matching `_{ResourceType}_{StorageID.hex}`. Transformations strictly preserve line counts (1:1 line preservation). The preprocessor scans dependencies and the engine binds them into the module's global execution namespace prior to script evaluation.
- **Other options:**
  - Standard function calls `lbe.ref("uid")` (rejected: requires global lookup overhead and runtime resolution machinery during every frame execution).
  - Python AST rewriting (rejected: more brittle with comments and line numbers, higher parsing overhead compared to regex token scanning).
  - Custom Python DSL or syntax fork (rejected: breaks IDE support, static typecheckers, and standard Python tooling).
- **Consequences:** Scripts can declare references directly in Python code. Tracebacks report accurate line numbers. Invalid bracket syntax raises [`LBEReferenceSyntaxError`](file:///f:/ModEngine/LBE/preprocessor.py#L13-L25). Comments and string literals are safely ignored.
- **Compatibility/migration:** Fully backward compatible; pure Python source code without bracket syntax compiles untouched.
- **Validation:** 20 automated unit tests in [`tests/test_preprocessor.py`](file:///f:/ModEngine/tests/test_preprocessor.py) covering regex replacement, comments, quotes, multiline strings, length validation, line number stability, and runtime execution binding.
- **Approved by developer:** Yes (11 October 2026)

---

### ADR-009: Tracked Mutations via ComponentProxy and EntityProxy
- **Status:** Accepted
- **Date:** 11 October 2026
- **Context:** Previously, calling `kernel.get_component(entity, name)` returned an uninstrumented mutable `dict`. Mutations made directly onto this dictionary failed to mark the parent entity dirty in the kernel, causing silent data loss on save unless developers remembered to call `kernel.set_component(...)`. Furthermore, game scripting ergonomics suffered from repetitive dictionary access methods.
- **Choice:** Implement transparent dirty tracking via [`ComponentProxy`](file:///f:/ModEngine/LBE/proxy.py#L12-L165) and [`EntityProxy`](file:///f:/ModEngine/LBE/proxy.py#L180-L310). Any mutating operation (`__setitem__`, `__delitem__`, `__setattr__`, `__delattr__`, `pop`, `update`, `clear`, `setdefault`) automatically flags the entity dirty in the [`Kernel`](file:///f:/ModEngine/LBE/kernel.py#L134-L147). Sub-dictionaries are recursively wrapped on read to guarantee nested mutations (e.g., `entity.stats.movement.speed += 5`) are tracked durably. Non-mutating reads do not mark entities dirty.
- **Other options:**
  - Read-only dictionary views requiring explicit `kernel.set_component(...)` calls for all writes (rejected: poor ergonomics for rapid game development and math operations like `transform.x += 10 * dt`).
  - Coarse manual `with kernel.transaction(entity):` blocks (rejected: easy to forget, cumbersome syntax for simple entity scripts).
- **Consequences:** Highly ergonomic Pythonic dot and dict access for scriptwriters. Zero silent data loss on component mutation. Recursive dirty propagation to root entities.
- **Compatibility/migration:** [`ComponentProxy`](file:///f:/ModEngine/LBE/proxy.py#L12-L165) inherits from `dict`, preserving dictionary iteration, key membership, equality comparisons, and serialization via `to_dict()`.
- **Validation:** 19 unit tests in [`tests/test_proxy_mutation.py`](file:///f:/ModEngine/tests/test_proxy_mutation.py) and 14 tests in [`tests/test_script_execution.py`](file:///f:/ModEngine/tests/test_script_execution.py) verifying nested mutations, dot and dict syntax, dirty marking, and cross-session disk durability.
- **Approved by developer:** Yes (11 October 2026)

---

### ADR-012: Unified 3D Transform Representation (2D as Orthographic Slice)
- **Status:** Accepted
- **Date:** 11 October 2026
- **Context:** Game engines frequently bifurcate transform components and spatial hierarchies into separate 2D (`Transform2D`) and 3D (`Transform3D`) systems. This leads to duplicate codebases, incompatible camera and physics systems, and severe friction when transitioning a 2D game to 2.5D or 3D.
- **Choice:** Adopt a unified 3D spatial transformation model (`Transform` with `position: [x, y, z]`, `rotation: [x, y, z, w]` / Euler, and `scale: [x, y, z]`) across all entities. 2D gameplay, sprites, and rendering are treated as an orthographic 2D projection/slice of 3D space (typically along the $xy$-plane with $z=0$ or layered depths).
- **Other options:**
  - Distinct `Transform2D` and `Transform3D` components (rejected: fractures the component ecosystem, duplicates hierarchy multiplication math, prevents multi-layer depth sorting in 2D).
  - Flexible variant-typed Transform (rejected: introduces runtime branching in inner simulation loops).
- **Consequences:** One unified scene graph hierarchy traversal and matrix composition for all games. 2D games gain seamless parallax scrolling, layering, and camera projection options without unique engine implementations.
- **Compatibility/migration:** 2D scripts access `x` and `y` directly on `entity.transform` while $z$ remains available for depth layering.
- **Validation:** Scene graph hierarchy and query tests in [`tests/test_hierarchy_and_spawning.py`](file:///f:/ModEngine/tests/test_hierarchy_and_spawning.py).
- **Approved by developer:** Yes (11 October 2026)

---

### ADR-013: Stable Function Identity and Cross-Script Callables
- **Status:** Accepted
- **Date:** 12 October 2026
- **Context:** Scripts and systems need to reference and invoke specific functions inside other Script resources across disk boundaries without whole-script coupling. Renaming a function for readability must never break external callers, button event handlers, or saved scenes referencing that function.
- **Choice:** Establish the durable function identity convention `def _fn_<id>(self, ...): # <human_display_name>` in Script resources. The symbol `_fn_<id>` is the permanent identifier, while `# <human_display_name>` serves as human presentation. Cross-script references use `<|1|storage_id_hex|>._fn_<id>` preprocessed into `_1_storage_id_hex._fn_<id>`. [`ScriptProxy`](file:///f:/ModEngine/LBE/proxy.py) provides on-demand module caching, compilation, and attribute delegation to callables, supporting both direct symbol invocation (`proxy._fn_<id>(...)`) and human display name aliases (`proxy.<display_name>(...)`).
- **Other options:**
  - Standard Python function names as durable references (rejected: renaming a function immediately breaks all callers, event handlers, and saved references).
  - Central function registry/indirection service (rejected: introduces global mutable state and indirection layers forbidden by `AGENTS.md`).
- **Consequences:** Functions can be renamed freely in code editor tooling by updating the trailing comment without breaking existing call sites or saved scenes. Fast attribute-based execution at native Python speeds.
- **Validation:** Automated unit tests in [`tests/test_script_references.py`](file:///f:/ModEngine/tests/test_script_references.py) and [`tests/test_proxy_mutation.py`](file:///f:/ModEngine/tests/test_proxy_mutation.py).
- **Approved by developer:** Yes (12 October 2026)

---

### ADR-014: Engine-Native UI Primitives & Dear PyGui Bridge System
- **Status:** Accepted
- **Date:** 12 October 2026
- **Context:** The engine requires graphical user interfaces for both in-game HUDs and custom editor tooling/macros. Building a separate GUI framework from scratch in pure Python ECS risks severe complexity, while coupling the kernel directly to Dear PyGui violates the headless invariant (ADR-001).
- **Choice:** Define data-driven UI components in the kernel: `UIContainer`, `UIButton`, `UISlider`, `UITextInput`, `UIText`. Event handlers store durable function references (`<|1|storage_id_hex|>._fn_<id>`). The headless kernel executes events via [`Kernel.trigger_ui_event`](file:///f:/ModEngine/LBE/kernel.py). In the editor, [`UIBridgePanel`](file:///f:/ModEngine/editor/ui_bridge.py) translates UI entity subtrees into Dear PyGui layouts. The entity hierarchy cleanly separates entities under `All`, `Game World`, and `UI & Tools` filter tabs.
- **Other options:**
  - Pure Python ECS GUI rendered into Raylib/OpenGL (rejected: massive boilerplate, complex layout algorithms, high maintenance overhead).
  - Hardcoded editor-only GUI separate from game UI (rejected: prevents game HUDs from using the same engine components and prevents custom in-engine macros).
- **Consequences:** Both games and editor tools share identical UI primitives and event dispatch. Kernel remains 100% headless. Failure in game code or broken references does not crash the editor host.
- **Validation:** 43 tests in [`tests/test_ui_components.py`](file:///f:/ModEngine/tests/test_ui_components.py) and 21 tests in [`tests/test_ui_bridge.py`](file:///f:/ModEngine/tests/test_ui_bridge.py).
- **Approved by developer:** Yes (12 October 2026)

---

### ADR-015: Visual Pill Token Projections in Inspector & Tooling
- **Status:** Accepted
- **Date:** 12 October 2026
- **Context:** Raw reference strings like `<|1|3f4a...|>._fn_f8e12a` are unreadable in the inspector, while raw human names are fragile to renames.
- **Choice:** Project raw reference hashes as interactive visual "Pills" (`[ 📄 ScriptName :: ⚡ FunctionName ]`) in the Inspector and Storage panels via [`PillData`](file:///f:/ModEngine/editor/pills.py). The underlying stored data remains the durable ID. Renaming a function from the inspector or storage panel updates only the `# <comment>` on the function declaration line using lexical tokenization of raw code, preserving exact column alignment and 1:1 line numbers.
- **Other options:**
  - Storing human names in entity JSON (rejected: fragile; renames cause silent broken references).
  - Arbitrary AST rewriting on save (rejected: destroys user formatting, comments, and whitespace).
- **Consequences:** Intuitive, drag-and-drop-ready visual presentation in UI tooling while preserving permanent durable references under the hood.
- **Validation:** 29 automated tests in [`tests/test_pills.py`](file:///f:/ModEngine/tests/test_pills.py).
- **Approved by developer:** Yes (12 October 2026)

---

### ADR-016: Bootstrapped Workstation, Card Trees, Multi-Inspector Active Focus & Lock, and Layered Context Menus
- **Status:** Accepted
- **Date:** 12 October 2026
- **Context:** The editor interface suffered from excessive toolbar button clutter and platform-dependent unicode symbol distortion. Developers require a modern, zero-clutter workstation: a card-based hierarchy tree with crisp vector lines and glyphs, direct manipulation via right-click context menus rather than distant toolbar buttons, root scoping to isolate game scenes from editor tools, and multi-instance inspectors with active selection focus routing and lock pinning (enabling side-by-side inspection or subtree isolation).
- **Choice:**
  1. **Bootstrapped Hierarchy & Root Scoping:** Default world structures an `Application` root containing `Game` and `Editor` subtrees. [`EditorSession.view_root_id`](file:///f:/ModEngine/editor/session.py) scopes the hierarchy tree to `Game` (isolating game entities) or `Application`.
  2. **Procedural Vector Geometry:** Dedicated [`editor/vector_glyphs.py`](file:///f:/ModEngine/editor/vector_glyphs.py) renders crisp vector chevrons, radio dots, window chrome, branch connector lines, dashed selection rectangles, and lock glyphs directly via Dear PyGui drawlists, eliminating distorted text glyphs.
  3. **Card Trees & Auto-Hiding Corner Chrome:** Each entity row is rendered as an interactive bordered card (`#181818` fill, 1px border, electric blue `#0078FF` selection). Panel titlebars feature auto-hiding corner chrome (`▷` flyout with Close, Minimize, Maximize) with hover tooltips.
  4. **Multi-Instance Inspector & Active Focus + Lock:** Multiple [`InspectorPanel`](file:///f:/ModEngine/editor/inspector_panel.py) instances register with [`EditorSession`](file:///f:/ModEngine/editor/session.py). Hierarchy clicks route to the active unlocked inspector. Clicking an inspector activates it; locking it (`🔒`) pins its target and bypasses it during hierarchy selection routing.
  5. **3-Layer Context Menu:** Removed all top and bottom static button toolbars across panels. Direct manipulation via right-click popup divided into:
     - **Layer 1 (Target Actions):** Rename, Add Child, Duplicate (with deep component copy), Delete, and Add Component modal.
     - **Layer 2 (Panel Actions):** This Panel verbs (Root Scope, Lock/Unlock, Set Active, Clear Target) and Other Panel verbs (Open in New Inspector, Focus in Viewport).
     - **Layer 3 (Engine Global Actions):** Save Dirty Resources, Play/Pause Tick, Reload World.
- **Other options:**
  - Fixed single-inspector design (rejected: prevents comparing multiple entities or locking an entity during scene navigation).
  - Heavy toolbar buttons atop each panel (rejected: causes visual clutter and mouse travel fatigue; direct manipulation via context menus is significantly faster and cleaner).
  - Unicode glyphs for UI controls (rejected: platform font dependent, inconsistent anti-aliasing and sizing across operating systems).
- **Consequences:** Clean, button-free workstation aesthetics. Zero coupling between kernel and editor UI (kernel remains 100% headless). Full support for side-by-side inspection and scoped subtrees.
- **Validation:** 8 automated unit/integration tests in [`tests/test_bootstrapped_editor.py`](file:///f:/ModEngine/tests/test_bootstrapped_editor.py) verifying hierarchy bootstrapping, root scoping, vector glyph draw commands, multi-inspector registration/routing/locking, dynamic inspector spawning, 3-layer context menu actions, and flyout toggling/closing.
- **Approved by developer:** Yes (12 October 2026)

---

### ADR-017: Dynamic UIPanel Window Mounting & World-Space Overhead UI Billboards
- **Status:** Accepted
- **Date:** 13 October 2026
- **Context:** Developers need the ability to build custom editor tools, debug windows, and in-game HUDs using the exact same ECS primitives as gameplay (entities, components, and standard function references), without introducing special "macro" or "plugin" APIs. Furthermore, child UI entities attached to in-game characters (such as overhead health bars and nametags) must follow the parent's world position but remain screen-aligned without spinning or inverting as the character rotates.
- **Choice:**
  1. **Dynamic `UIPanel` Window Mounting:** Add `UIPanel` (`title`, `width`, `height`, `minimized`, `closable`) to [`LBE/integrity.py`](file:///f:/ModEngine/LBE/integrity.py). In [`editor/ui_bridge.py`](file:///f:/ModEngine/editor/ui_bridge.py), any entity in the ECS graph possessing `UIPanel` dynamically mounts a real Dear PyGui floating desktop window, recursively rendering its child UI entities (`UIContainer`, `UIButton`, `UISlider`, `UITextInput`, `UIText`) inside it. Buttons execute standard LittleBigEngine function references (`<|1|storage_id|>._fn_<id>`). Internal workstation panels (`Hierarchy`, `Inspector`) with `"panel_type"` are disambiguated and protected from floating runtime window hijacking.
  2. **World-Space Overhead UI Billboards:** In [`editor/viewport_panel.py`](file:///f:/ModEngine/editor/viewport_panel.py), child UI entities under game entities follow the parent entity's world translation $(x, y)$ plus local offset $(dx, dy)$, but their **rotation is locked at $0.0^\circ$** (screen-aligned billboard). Overhead UI children suppress duplicate body circles, selection rings, and phantom hierarchy lines, ensuring clean visual presentation.
- **Other options:**
  - Dedicated macro/tool button plugin API (rejected: creates bifurcated APIs and violates the principle of using standard ECS mechanisms for all capabilities).
  - Rigid rotation inheritance for overhead UI (rejected: causes spinning or upside-down health bars and illegible text when characters rotate).
- **Consequences:** The editor can host arbitrary custom developer tools directly from the ECS scene graph. Overhead health bars and nametags stay perfectly upright and legible during gameplay. Headless kernel invariant is 100% preserved.
- **Validation:** 25 automated tests across [`tests/test_ui_components.py`](file:///f:/ModEngine/tests/test_ui_components.py), [`tests/test_ui_bridge.py`](file:///f:/ModEngine/tests/test_ui_bridge.py), and [`tests/test_overhead_ui_and_panels.py`](file:///f:/ModEngine/tests/test_overhead_ui_and_panels.py) verifying schema bounds, window creation/teardown, rotation locking, child stacking, and persistence roundtrip.
- **Approved by developer:** Yes (13 October 2026)

---

## Decision Protocol

For changes to decisions, provide: **Context; Decision; Alternatives; Trade-offs; Migration or compatibility; Tests; User approval and date**. Add a dated superseding entry rather than silently rewriting previous history. `Accepted (design direction)` means the principle is agreed, *not* that its exact source implementation or schema is frozen.

### Template
```text
ADR-XXX — Status: Proposed | Accepted | Superseded
Date:
Context:
Choice:
Other options:
Consequences:
Compatibility/migration:
Validation:
Approved by developer:
```
