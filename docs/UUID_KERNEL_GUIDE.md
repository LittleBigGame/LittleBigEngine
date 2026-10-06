# UUID item kernel and GUI walkthrough

## Start through the project launcher

Run `F:\NanoEngine\main.py` as usual. Choose a directory, enter a new project
name, click **Create**, then **Copy Default LBE v1 Editor**. Newly created projects
copy the updated editor and sample sources automatically. No PowerShell project
creation is necessary.

Existing project directories and their customized scripts have not been replaced.
The engine changes apply immediately, but an existing project's copied editor
scripts remain its own files. Test with a new project first. The existing explicit
`--upgrade-template --project <directory>` mechanism upgrades only unchanged,
managed template files and retains backups; unmanaged/customized files need a
deliberate manual update. Do not copy an entire template over your game.

## A player that walks and shoots

1. Right-click **Game** in the hierarchy and choose **Create walk-and-shoot demo**.
2. Click the viewport. **WASD / arrows** move; **Space** shoots in the most recent
   movement direction. **F5** pauses/resumes the game. The initial two example
   rectangles remain in the scene; they are not obstacles and have no collision.
3. Inspect **Player**. It has ordinary position, size, colour and aiming components.
   Scroll the component section to see **speed**.
4. Inspect **PlayerBlueprint**. It has a speed value but no position, size, physics
   or drawing requirement. Change its speed: the player picks up the change.
5. Inspect Player again. Its speed label is purple because the declaration is
   inherited. Editing the value creates a local replacement patch. The blueprint
   is untouched. Right-click speed and choose **Reset local patch** to follow the
   blueprint again. Inspector value edits support undo/redo, including the patch.
6. Inspect Game's **walk_shoot** system and click **Edit**. The normal project file
   `systems/game/walk_shoot.py` contains movement, aiming, cooldown, bullet creation,
   bullet movement and lifetime expiry. Edit it and use **Ctrl+S** to reload.
7. Use **Save project**, close and reopen. Entity, component, link and attachment
   UUIDs are preserved. Bullet lifetime/cooldown is a simple demonstration, not a
   production combat or physics subsystem.

## Referencing objects in source

Click an inspector's Entity identity heading to inspect its UUID, temporary
runtime handle and item count, or copy its Entity reference. Right-click a
component to copy a Component reference. Attachment menus similarly copy the
attachment's identity, which is distinct from the source asset's identity.

Paste references into source:

```python
player = <|Entity:11111111-1111-1111-1111-111111111111|>
speed = <|Component:22222222-2222-2222-2222-222222222222|>

def update(dt):
    player.x += speed.value * dt
```

The UUIDs above are placeholders: copy real references from your project. Source
files retain the explicit UUID syntax. The editor renders friendly pills; arrow
keys and deletion treat each reference as a unit. Missing references show red
pills. Right-click a typed object pill to inspect its owner or copy its identity.
Strings and comments are never linked, including triple strings and f-strings.
Malformed syntax is a source diagnostic. Missing or incorrectly typed objects
fail initialization without inventing blank entities; failed reload preserves
the previous working behavior.

Supported kinds: Entity, Component, System, Script, Relation, Tag, Asset. Component
bindings expose a live `.value`; non-Entity object bindings follow reload/edits
through the linker. Existing `resolve("uuid")`, `asset("uuid")` and asset pills
continue working.

To reuse data entirely through the GUI: copy a component reference from its
context menu, inspect a different entity, and choose **+ Add → Inherit component
from copied reference**. The new declaration has its own UUID and points to the
source UUID. The source can belong to any entity, not only an ancestor.

## Architecture rundown

There is one authoritative `entity.items` collection keyed by UUID. Components,
inherited components, tags, relations, parent links and behavior attachments are
typed records in that collection. `entity[uuid]` retrieves a declaration;
`entity.all(Component)`, `entity.all(InheritedComponent)`, `entity.all(System)` and
other type queries retrieve matching typed records. `System` and `Script` are
aliases of the existing instance classes, not another execution model.

The familiar `entity.x`, `entity.components`, `entity.tags`, `entity.relations`,
`entity.systems` and `entity.scripts` remain supported as projections. Their
internal dictionaries no longer independently own application data. Ordinary
component edits, renames and successful attachment reloads preserve item UUIDs.
Deletion/recreation is a new identity. Systems retain the existing lifecycle,
per-attachment namespaces, subscription cleanup and update-before-draw order.

Parent and relation records contain UUID targets. Runtime child order/adjacency,
name/type lookup indexes, spatial indexes and editor views are disposable derived
state. Entities are not recursively serialized into owners. UI entities are
still ordinary entities; no second editor/game-object model was introduced.

`InheritedComponent(name, source_uuid, patch)` stores only its declaration.
Resolution reads the live source and applies a private-copy patch. Supported
operations are `set`/`replace`, numeric/list `add`, `multiply`, and path `remove`.
Paths are lists of mapping keys or list indices. Source edits notify inherited
consumers through the existing change stream. Nested edits use
`components.edit(key)` or explicit `components.patch(key, operations)`; modifying
a resolved inherited copy alone does not persist an edit. The old nearest-ancestor
`entity.inherit("name")` helper keeps its existing meaning.

Project format v3 stores canonical typed item records. Legacy fields emitted by
the public serializer are compatibility projections; loading prefers `items`
when present, so edited redundant fields cannot override canonical data. v0–v2
projects migrate, with deterministic UUIDs for legacy items. Missing sources are
retained rather than synthesized. Restore creates all entities/data, registers
all behavior attachments, links their source references, initializes them, then
starts them. Forward attachment references are therefore available during linking.

`runtime.linker` owns disposable UUID-to-object and dependency indexes. UUIDs are
the persistent identity; `Handle(slot, generation, scope)` is runtime-only.
Destroying an object invalidates its handle, even if its slot is reused. Handles
from another runtime are rejected and are never serialized. This is an explicit
linking boundary around the current runtime, not a replacement native/columnar ECS.

## Limits and performance

This is an incremental, working foundation. It is **not** a finished optimized
runtime representation, physics engine, prefab editor, or general graph browser.
Composition resolves on demand; it is not a compiled cached inheritance graph.
Asset files keep the existing UUID registry. Mutable Python values still require
explicit mutation notifications. Changes do not provide a global transactional
save/undo mechanism beyond the existing editor operations.

UUID records/indexes and the compatibility layer add measurable overhead versus
the old dictionaries, especially mass creation and serialization. The reproducible
comparison is `benchmarks/kernel.py` (optional `--baseline 9f37a27`). It uses
isolated temporary projects, 1,000-entity workloads and a warmed recording-backend
editor frame. Results are machine-dependent, not GPU FPS. Retain the migrated
design and optimize measured hot paths before scaling to large worlds; there is
no evidence here that a wholesale rebuild is necessary or that this refactor is
faster than the old engine.

One local comparison against `9f37a27` (median milliseconds):

| Workload | Before | UUID kernel |
| --- | ---: | ---: |
| Create/destroy 1,000 entities | 23.32 | 111.93 |
| Query 1,000 entities, 20 times | 31.47 | 36.49 |
| 20,000 component reads | 5.00 | 14.37 |
| 1,000 moving entities, 20 steps | 157.63 | 289.70 |
| Serialize 1,000 entities | 19.98 | 93.88 |
| Warm editor frame, recording backend | 11.98 | 19.73 |

The serialized fixture grew from 282,205 to 887,498 bytes because persistent item
identities and transitional compatibility projections are emitted. Profiling
identified named compatibility access, record updates, UUID allocation during
creation and serialization as remaining costs. Initial editor-frame overhead was
larger; direct ordinary-value reads, reused UUID keys, per-type indexes and
avoiding needless index rebuilds reduced it. The next optimization should focus
on these costs, not introduce gameplay-specific kernel types or duplicate state.

Automated coverage includes item identity, stale handles, flat links, composition,
canonical persistence, legacy migration, forward references, reference lexing,
GUI inheritance edits/undo, movement/shooting/reopen and reference pills. The
graphics walkthrough uses real desktop rendering with synthetic input; it does
not substitute for your interactive acceptance test.
