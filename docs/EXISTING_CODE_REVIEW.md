# LittleBigEngine — Source Review & Foundational Redesign

**Date:** 11 October 2026  
**Source reviewed:** `ModEngine.zip` (uploaded in this conversation)  
**Status:** Evidence-based review of the supplied archive; proposed future design, not a statement that proposed features already exist.

## Executive assessment

The uploaded archive is a **small, early kernel prototype**, not a complete game engine or editor. It contains seven Python source files (`LBE/__init__.py`, `types.py`, `integrity.py`, `kernel.py`, `logger.py`, `Queue.py`, and `main.py`) and one example saved entity. `LBE/kernel.py` (871 lines) contains most of the functional implementation; `integrity.py` (201 lines) validates resource envelopes, and `logger.py` (321 lines) provides rich tracing. The archive does **not** contain source implementations of an editor, rendering subsystem, gameplay scheduler, reference compiler, or reusable function registry. Compiled `.pyc` files exist for some other names, but those are not equivalent to reviewable source.

**Central finding:** The *idea* driving the redesign—persistent resource identity mapped to lightweight runtime identity—is already implemented in embryonic form. The main problems are unclear boundaries between persistent editable data and runtime state, mutable references escaping dirty tracking, insufficient reference validation, and diagnostics running through performance-sensitive paths. A new architecture can preserve this work and formalize its boundaries, rather than discarding its useful concepts.

## 1. What is actually implemented

| Capability | Supplied implementation | Assessment |
|---|---|---|
| Persistent identity | `StorageID` is `bytes`, allocated with `secrets.token_bytes(16)` (`types.py:5`, `kernel.py:486–496`) | Present: **128-bit**, not proposed 256-bit |
| Runtime identity | Monotonically allocated integer from `runtime_idx` and optional `stale_runtime_ids` pool (`kernel.py:23–28,115–124`) | Present; generation checks/deletion not implemented |
| Bidirectional mapping | `resource_runtime_ids` and `resource_storage_ids` (`kernel.py:23–25,36–75`) | Present and valuable |
| Generic resources | `type`, `data`, optional `name`, `dependencies`, `children`, `metadata` (`kernel.py:437–539`) | Present; generic envelope is useful |
| Entities/components | `create_entity()`, `get_component()`, `set_component()`, `has_component()`, `remove_component()` (`kernel.py:545–798`) | Present; currently name-keyed dict data, not a complete typed ECS/query API |
| Persistence | Per-resource JSON files named by storage ID; write temp then `replace()` (`kernel.py:145–259`) | Present; useful basic approach |
| Dirty tracking | `dirty_runtime_ids`, `mark_dirty()`, dirty flush (`kernel.py:126–145,261–273`) | Present but bypassable |
| Recursive references | Loading of top-level `dependencies` and `children` (`kernel.py:351–435`) | Present in basic form; no executable resolution or robust transaction |
| Validation | Shape/type checks for envelopes and entity component dictionaries (`integrity.py:9–201`) | Present but not comprehensive |
| Diagnostics | Trace-level logger with before/after snapshots and history (`logger.py`) | Present; overly expensive on hot paths by default |
| Function/system execution | No source implementing it in this archive | Not demonstrated |
| Editor and bootstrapping | No editor source in this archive | Cannot assess from this upload |

`main.py` is a small end-to-end demonstration: create a Player with Transform/Health, change Health through `set_component()`, save, and inspect trace history.

## 2. Confirmed defects and risks

These observations come directly from the supplied source. Where noted as **reproduced**, they were checked by importing only the supplied `.py` files in a temporary directory under Python 3.13 and writing test resources to an isolated temporary folder. No user project files were modified.

### P0 — Changes can bypass persistence tracking (**reproduced**)

`kernel.py:615–656` returns the actual mutable component dictionary from `get_component()`, and `kernel.py:776–797` does the same for the component collection. `get_resource()` (`kernel.py:76–87`) also exposes mutable internal data.

```python
health = kernel.get_component(entity_id, "Health")
health["current"] = 55  # Modifies memory directly
assert kernel.is_dirty(entity_id) is False  # No save scheduled
```

In the isolated test, the value in memory became 55 but, after `save_dirty_resources()` and a reload, persisted Health remained 100. **Fix:** choose a formal mutation contract: immutable/read-only views plus `set_component()` or an explicit edit transaction/proxy that automatically tracks changes. Do not promise automatic dirty tracking while returning raw mutable dictionaries.

### P0 — Loading can leave a partially registered graph

`load_resource()` (`kernel.py:351–435`) registers the parent resource in all maps before recursively loading its dependencies and children. If a child is missing, malformed, or fails validation, it returns an error without rolling back objects registered so far. A second attempt may see that parent as already loaded. **Fix:** separate graph discovery and validation from commit, or use a loading state machine with explicit failed/incomplete states and rollback/retry behavior.

### P1 — Stored byte references can fail to save (**reproduced**)

`create_resource()` accepts `dependencies: list[str | bytes]` and `children: list[str | bytes]` (`kernel.py:442–443`) but `save_resource()` uses plain `json.dumps()` (`kernel.py:177–196`). Byte IDs are not JSON-serializable. In an isolated test, a resource created with a bytes dependency returned `Error: Serialization failed` when saved. **Fix:** use one canonical on-disk UID encoding, such as lowercase fixed-width hex, and normalize/validate all IDs at the storage boundary.

### P1 — Importing command queue currently fails (**reproduced**)

`LBE/Queue.py:9` references `CommandID`, `CallerID`, and `ReceiverID`, none of which are defined in `types.py`. Importing `LBE.Queue` produced `NameError: name 'CommandID' is not defined`. The file is not imported by `LBE/__init__.py`, so this may have gone unnoticed. **Fix:** define or remove these types, or leave the queue outside the minimal kernel until its contract exists.

### P1 — Logging imposes unnecessary cost on normal operations

`logger.py:42–52,73–96` records every trace and prints it by default. `get_component()` itself logs successful reads (`kernel.py:649–655`), and several mutations take `deepcopy()` snapshots. That is useful for debugging, but risky for per-frame queries. The record history grows without a bound. **Fix:** let log level gate *record creation* and formatting, disable trace by default, add bounded history/optional development audit mode, and keep component read paths free of unconditional instrumentation.

### P1 — Reference validation is incomplete

`integrity.py:94–131` checks that `dependencies` and `children` are lists but not that their entries are well-formed UIDs. `create_resource()` validates a user-supplied storage ID with `len(storage_id)` rather than a type-safe normalizer (`kernel.py:486–496`). Passing a 16-character string as `storage_id` produced an `AttributeError` when `.hex()` was subsequently called. **Fix:** centralize UID parsing, type checking, normalization, and error reporting; validate references at creation and loading.

### P2 — Current entity references have ambiguous semantics

Entity-owned `data["resources"]` is persisted in `create_entity()` / `add_entity_resource()` (`kernel.py:545–565,822–858`), but `load_resource()` only traverses top-level `dependencies` and `children` (`kernel.py:401–433`). Those may deliberately be different kinds of links; currently the semantics are not documented or unified. **Fix:** give references explicit relation types (dependency, child, resource attachment, weak link) and well-defined resolution/lifetime behavior.

### P2 — Runtime handle reuse has no stale-handle defense

`stale_runtime_ids` is available for reuse, but this archive contains no unload/delete path that fills it, and no generation counter on handles. If recycling is introduced without generation checks, stale IDs may address a different object. **Fix:** world/registry-scoped slot + generation handles, or delay reuse until the design is proven.

### P2 — Persistence and error policy need explicit contracts

The temporary-file-then-replace save (`kernel.py:198–259`) is a good foundation, but there is no schema version or migration path, cross-file atomicity, journal, backup policy, or crash-durability guarantee. Many methods return `Error` objects rather than raising exceptions (`types.py:9–14`), while direct I/O operations can still raise normal Python exceptions. **Fix:** one public error strategy, versioned schema, and incremental/transactional saves where needed.

## 3. Important things to preserve

1. **Bidirectional UID ↔ runtime lookup** — already aligns with the proposed architecture.
2. **Generic resource envelopes** — useful for entities, functions, systems and other persistent assets if type contracts remain explicit.
3. **Per-resource JSON persistence** — convenient for incremental loading and modular editing; preserve it initially unless benchmarks show a problem.
4. **Explicit `set_component()` operations** — a natural place to centralize change tracking, validation, undo/redo and notifications.
5. **Validation and typed error codes** — keep the intention, strengthen the guarantees and simplify the public error model.
6. **Provenance logging** — useful for debugging and editor tooling; move costly snapshots behind opt-in facilities.
7. **Simple sample project** — grow `main.py` into repeatable integration tests.

The goal is **preserve concepts, improve ownership and boundaries**, not automatically preserve every function signature or file layout.

## 4. Agreed target model

> **LittleBigEngine identifies, stores, connects, resolves and executes independently identifiable resources.**

### Independent responsibilities

- **Identity/registry:** persistent resource IDs, runtime handles, lookup and lifecycle.
- **Storage/project model:** Python source, JSON metadata, entity/component state, named relationships and dependencies; schema versioning.
- **Resolver/build:** validate graph, discover static LBE references, bind registered objects, compile ordinary Python, report compatibility errors.
- **ECS runtime:** worlds, entities, components, efficient queries, events and systems. Runtime implementation need not mirror storage layout.
- **Public API:** clean entity-centric access plus explicit typed component queries. Optional automatic injection remains a convenience, not a kernel obligation.
- **Editor:** independent application for persistent graph manipulation; game preview separate, ideally with process isolation when appropriate.
- **GUI:** shared primitives only when genuinely beneficial. Editor does **not** have to be a game world to reuse game-facing UI code.

### Source, function and system model

- A **script** is ordinary Python source. It may contain multiple functions and private helpers.
- An exported **function** has a persistent UID, source location, symbol mapping and optional component/argument contract.
- A **system** controls *when*, *where* and *in which order* functions execute; it can use ordinary Python flow control and call functions identified by UID.
- Functions may call other functions, and different systems may reference the same exported function.
- The UID protects against renaming/moving **when registry metadata is updated**, not against breaking changes in signatures or behavior.
- JSON records metadata and dependency edges. It does not replace the executable Python source or automatically track arbitrary dynamic imports/calls.
- CloudPickle is **not** a required foundational persistence mechanism.

### Two-tier IDs

- **Persistent UID:** 128-bit random IDs already exist; 256-bit is an optional policy change rather than an urgent correctness fix. Do not change size without a migration strategy.
- **Runtime handle:** compact, scoped to a world/registry, with generation checks before ID reuse. For small prototypes, sequential integers are sufficient.
- **Persistence rule:** save UID references; runtime IDs are ephemeral. Generated caches may use compact local indexes with a valid remapping table, but cannot silently become the sole saved identities.

### Proposed embedded source reference

Stored LBE source (custom syntax):

```python
move = <lbe.ref("b82d...f103")>

def update(world, dt):
    for entity in world.query(Position, Velocity):
        move(entity, dt)
```

The text between angle brackets is a **normal Python expression**, but the angle brackets make this an LBE source extension: the full line is not valid Python before preprocessing. For v0.1, the accepted grammar should be intentionally narrow, e.g. a literal-UID `lbe.ref(...)` form, without evaluating arbitrary expressions at dependency-discovery time.

After resolution/compilation (conceptual):

```python
move = _lbe_bindings[0]  # A callable already resolved at build/load time

def update(world, dt):
    for entity in world.query(Position, Velocity):
        move(entity, dt)
```

The runtime does not resolve a persistent UID on every invocation. The reference index can be regenerated from explicit source references; function contracts should be validated before activation.

## 5. Design rules to freeze before further development

1. Object identity is independent of name, location and runtime representation.
2. Editor and game share services, **not** a mandatory shared world/lifecycle.
3. Persistent objects are not automatically live runtime objects.
4. The kernel must remain usable without a renderer, window, audio or editor.
5. Systems orchestrate; exported functions implement reusable behavior.
6. Standard Python source remains the editable source of truth.
7. JSON stores references and metadata, not opaque pickled executable state.
8. Component mutation must have one unambiguous path for dirty tracking.
9. Missing or incompatible references must fail visibly, never point silently at unrelated objects.
10. Measure the cost of convenience API layers before promoting them into the hot path.

## 6. Practical redesign sequence

**Stage 0 — Preserve and characterize.** Keep `ModEngine.zip` unchanged as a baseline. Build reproducible tests for entity create/save/load, alias mutations, missing dependencies, malformed IDs, system-free worlds and reference cycles. Capture current API behavior and error codes.

**Stage 1 — Identity and lifecycle.** Extract ID parsing/allocation and registry ownership from the monolithic kernel. Define scope (per project/world), persistent UID encoding, handle allocation and optional generation counters. Introduce lifecycle states (`unloaded`, `loading`, `ready`, `failed`) and idempotent resolution.

**Stage 2 — Persistent resource store.** Version JSON schemas; normalize references to hex; validate all boundaries; add transactional writes or scoped recovery for multi-resource operations. Specify resource relationship types and enforce safe read/edit APIs.

**Stage 3 — Minimal ECS.** Implement entity creation, components and queries with no renderer or editor. For performance, avoid treating serialized JSON envelopes as the per-frame component access representation. Start simple, then benchmark an indexed component store against the existing dict approach.

**Stage 4 — Function registry and systems.** Give exported functions UIDs, source pointers and signatures. Make systems ordinary executable orchestration with phases and explicit scheduling. Build clear contract validation and reverse dependency lookup.

**Stage 5 — LBE reference compiler.** Implement one tiny angle-bracket syntax, dependency extraction, error spans and cached binding. Avoid a general-purpose new language or hidden runtime resolution in loops.

**Stage 6 — Runtime sync/hot reload.** Resolve changes in the persistent project model, validate before swapping callables, and define rollback when a reload fails. Preserve unaffected world state where safe.

**Stage 7 — Standalone editor.** Start with hierarchy, component inspector, script editor, dependency viewer and explicit Preview control. The editor should still function when a game script is invalid.

**Stage 8 — Optional higher-level functionality.** Rendering, input, GUI, events, visual system graphs, marketplace/build packaging. Add these as independently testable modules, not kernel prerequisites.

## 7. Acceptance criteria for the first working vertical slice

A new LBE build is foundation-ready when it can:

1. Create two persistent entities with `Position` and `Velocity`.
2. Save and reload their typed component data and stable IDs.
3. Define an exported `move()` function in one source file, registered by UID.
4. Reference it from an `update()` system using `<lbe.ref("...")>` syntax.
5. Resolve its dependencies once and execute the system against matching entities.
6. Rename/move the function (update its export registry) without changing the referencing system source.
7. Report a removed function or incompatible signature before gameplay begins.
8. Support changes through a tracked edit API without silently losing data.
9. Reject malformed IDs, missing children and cyclic dependencies predictably.
10. Keep the storage/project editor usable if the game runtime fails.

## 8. Highest-priority next actions

**Immediately:** (a) lock down component ownership/mutation; (b) normalize all UID references; (c) prevent partial-graph load success; (d) remove trace logging from the hot path; (e) write tests for existing semantics.

**Then:** develop the minimal registered-function → bracket-reference → callable-binding example **before** a fully bootstrapped editor, node graph, cloudpickle packaging, or GUI system.

**Explicit scope limitation:** This review judges only the supplied `ModEngine.zip`. Because no editor, system scheduler, or script compiler source was included, it cannot conclude whether those parts of the broader LittleBigEngine project are well or poorly implemented elsewhere.
