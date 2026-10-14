# LittleBigEngine — Foundational Architecture

**Status:** proposed target architecture v0.1, not the actual current implementation. Use `docs/CURRENT_STATE.md` for reality. A choice not marked Accepted in `docs/DECISIONS.md` is not a license to rewrite code.

## Vision and principles
LittleBigEngine **identifies → stores → connects → resolves → executes** objects. It should enable composable game creation without forcing every capability into a universal ECS or bootstrapped editor. Functionality should be ordinary Python first and engine-specific where persistent identity truly matters.

## Logical separation

```text
          Independent editor          Game application
                 |                           |
                 +---- shared public API ----+
                              |
                     ECS / Runtime services
                              |
            Registry, lifecycle and resolver
                      /               \
        Persistent storage       Runtime representation
        Python + JSON            handles + Python objects
```

This is a dependency/ownership model, not a required directory tree. The **kernel can run without a renderer, GUI or editor**. The editor modifies stored project data and starts/stops a preview explicitly. Full GUI bootstrapping is optional, not foundational. Reuse shared GUI primitives only if it genuinely lowers costs; sophisticated editor docking may be editor-only. Strong crash isolation eventually calls for a separate game-preview process.

## Objects and ownership
- **Persistent resource:** an item with stable identity, e.g., exportable function definition, saved entity or system definition.
- **World:** own namespace for active ECS entities, systems and execution state.
- **Entity:** identity plus typed component associations and optional explicit relationships.
- **Component:** typed data; need not itself have a universal ID for every field/value.
- **Function:** reusable Python callable; exported functions receive stable IDs and optional explicit contracts; private helpers remain normal Python.
- **System:** scheduling/orchestration unit; runs plain Python control flow, invoking reusable functions or, later, a declared graph.
- **Script:** source container; may export zero or many stable functions. A source path/symbol is metadata, never canonical identity.

## IDs: one persistent, one runtime
- **Persistent UID:** immutable identity in saved project metadata. The current kernel uses random **128-bit** IDs, not 256-bit; increasing the size is a **proposal requiring schema migration**. Do not silently change size.
- **Runtime handle:** compact integer or generation-aware `(slot, generation)` tied to a registry/world, never a durable identity. Sequential indexes are fine initially. Prevent stale handle reuse from returning an unrelated object.
- Persistent references on disk **always use a canonical UID**; generated caches may store compact indexes only with versioned/remappable manifests.
- UIDs identify *what* a resource is. Handles identify *where it is accessible now*. Prevent collisions, duplicate registrations, cross-world confusion and dangling lookups.

## Storage and loading
- Persist **Python source for code** and **versioned JSON for object data, export registry, stable references and dependency metadata**.
- Normalize UID encoding at boundaries (suggested lowercase fixed-width hex for current 128-bit baseline); do not persist raw `bytes` or ephemeral handles in JSON.
- JSON stores stable links and contracts, **not executable bytecode**. Avoid CloudPickle as core persistence (opaque, version-dependent, untrusted load can execute code).
- Loading must validate the graph before exposing complete resources, or use explicit `loading/ready/failed` states with rollback. Dependency cycles and optional/weak links need defined semantics.
- Mutable project state has **one reliable mutation contract**: tracked write API, transactional editing or tracked proxies; ordinary read access must not silently defeat saves.
- Support versioned schema, migration path and clear errors. Differentiate source, stored project state, runtime state, and generated cache.

## LBE references (design, not yet implemented)
Stored LBE-extended Python may contain a special expression:

```python
move = <lbe.ref("<full-persistent-uid>")>

def update(world, dt):
    for entity in world.entities_with(Position, Velocity):
        move(entity, dt)
```

The *interior expression* uses ordinary Python syntax; the angle brackets denote a proposed **LBE preprocessing boundary**, so the complete file is **not valid Python before translation**. The first grammar should be narrowly restricted to a recognizable literal `lbe.ref("uid")`, not arbitrary eval. A parser/preprocessor must accurately respect strings/comments, provide file/line diagnostics, support dependable dependency extraction and refuse unresolved/wrong-kind IDs. No raw regex substitution over all source code.

The build/resolver should bind each stored UID to a validated callable/object **once at load/build**. Generated code uses direct Python object references or cached bindings; hot-path iteration must not do repeated UID lookups. Stable identity protects path/name changes, **not** signature or semantic compatibility. Validate contracts and reverse dependencies before hot swapping.

## ECS/API design
Keep explicit primitives (`entity.get(Component)`, typed queries) as the reliable base. Entity-centric access can make game scripts pleasant; component-centric iteration can make data requirements clear and efficient. Optional automatic annotation-based injection or dot-access is a convenience layer **only after measurement and a proven use case**. Avoid multiple independent component stores hidden behind the same API.

## Execution and systems
A system controls phase, ordering, entity selection and calls; a function implements reusable behavior. Multiple systems may reference one function. Preserve ordinary Python loops, conditional expressions and nested calls. An optional declarative graph should be a *frontend to the same reference registry and callable executor*, not another entire runtime or new mandatory language.

## Editor and GUI
Editor does not have to be a gameplay world. It should inspect and edit stored data when game scripts cannot run, perform undo/redo and manage explicit previews. Runtime/editor sync is controlled and validated; incompatible updates fail visibly without corrupting the stored project. Shared GUI libraries are possible but should not dictate editor architecture.

## Performance and security
Measure relevant per-frame paths rather than assuming an abstraction is faster; avoid unconditional trace snapshots and signature reflection inside loops. Preserve clear errors and testable invariants. Code imported from third parties runs with Python's privileges unless isolated in a properly designed process/sandbox; reference metadata and reviews **do not** create a security boundary.

## First vertical slice: acceptance
1. Create two persistent entities with `Position` and `Velocity`.
2. Save and reload their UIDs and data; all mutations persist reliably.
3. Register a Python `move()` function with an export UID, from an independent source file.
4. Reference it from a system via the bracketed reference expression.
5. Resolve/validate once, execute and confirm both entities move.
6. Move/rename the implementation while preserving UID and updating export metadata; caller source remains unchanged.
7. Missing function/incompatible contract/dangling reference produces a specific error before execution.
8. Bad or cyclic resource graphs do not leave corrupt partial registrations.
9. Runtime handles cannot silently address the wrong objects after reuse.
10. Editor/project storage remains usable when preview code fails.

No rendering, GUI, node graph, marketplace or fully bootstrapped editor is required for this first slice.
