# UUID item kernel and GUI walkthrough

This describes an intermediate migration checkpoint, not the completed
no-compatibility architecture. The inspector is now one UUID-item list;
dynamic data attributes and legacy source-authoring paths still need their
native-only cutover.

## Start through the project launcher

Run `F:\NanoEngine\main.py` as usual. Choose a directory, enter a new project
name, click **Create**, then **Copy Default LBE v1 Editor**. Newly created projects
copy the updated editor and sample sources automatically. No PowerShell project
creation is necessary.

Existing project directories and their customized scripts have not been replaced.
Project versions 0–3 are now rejected, not converted. Create a new project for
this migration test; older project directories stay untouched. The existing explicit
`--upgrade-template --project <directory>` mechanism upgrades only unchanged,
managed template files and retains backups; unmanaged/customized files need a
deliberate manual update. Do not copy an entire template over your game.

## A player that walks and shoots

1. Right-click **Game** in the hierarchy and choose **Create walk-and-shoot demo**.
2. Click the viewport. **WASD / arrows** move; **Space** shoots in the most recent
   movement direction. **F5** pauses/resumes the game. The initial two example
   rectangles remain in the scene; they are not obstacles and have no collision.
3. Inspect **Player**. It has ordinary position, size, colour and aiming components.
   Scroll the **ITEMS** list to see **speed**. Names are editable tinted pills;
   the symbol/type badge underneath identifies the stored record type.
4. Inspect **PlayerBlueprint**. It has a speed value but no position, size, physics
   or drawing requirement. Change its speed: the player picks up the change.
5. Inspect Player again. Its speed label is purple because the declaration is
   inherited. Editing the value creates a local replacement patch. The blueprint
   is untouched. Right-click speed and choose **Reset local patch** to follow the
   blueprint again. Inspector value edits support undo/redo, including the patch.
6. Inspect Game, find its **walk_shoot** item and click its source/data field.
   The normal project file
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

The inspector's **+ Add** menu creates values, inherited components, tags,
relationships, parent links and behaviours. A tag is its own UUID item, not text
in a comma-separated tags box. Rename a relationship's pill without changing
its UUID; its type badge opens target selection and removal. Clicking relationship
data navigates to the target. Missing targets remain explicit visible items.
Custom dataclass records expose their data fields as an editable dictionary;
identity and name are not part of that data edit. Child and affecting-system
navigation is in the Entity identity menu, not mixed into the owned item list.

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

`Entity.components`, `Entity.tags`, `Entity.relations`, `Entity.systems` and
`Entity.scripts` have been removed,
including their backing slots and projection classes. Named convenience
operations now read or mutate the actual UUID records:

```python
player.items.set_value('x', 2.0)
player.items.add_tag('player')
link = player.items.connect('target', enemy)
player.items.rename(link.id, 'aim_target')
target = player.items.require_target('aim_target')
```

Names identify records within a type category; UUIDs remain the dictionary keys.
`value_dict()` and `link_dict()` return disposable snapshots, not live collections.
Behaviour attachment uses `items.attach_system(...)` or `items.attach_script(...)`;
the returned record is an actual UUID item. Reload, relocation and removal
select its item UUID. `items.behaviour_dict(kind)` is a disposable query snapshot.
Dynamic `entity.x` still exists at this checkpoint and is outstanding removal
work. Ordinary
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
`items.edit_value(name)` or explicit `items.patch_value(item_uuid, operations)`; modifying
a resolved inherited copy alone does not persist an edit. The old nearest-ancestor
`entity.inherit("name")` helper keeps its existing meaning.

Project format v4 stores Entity documents containing only `id` and `items`.
Item dictionary keys are UUIDs; each record stores its type, editable name and
payload. Parent items also encode sibling position. No duplicate named component,
tag, relation, parent, system or script fields are emitted or accepted. Older
formats are rejected before any project, template or user-state writes.
Missing links and source declarations remain identified items, not parallel
pending collections or synthesized targets. Restore registers all entities and
items, compiles available sources, links/initializes all behaviours, then starts
them. Forward references are therefore available during linking.

Application dataclasses with `id` and `name` fields can opt in to persistence
through `register_item_type(MyType)` before loading their documents. Codecs
preserve their concrete type and payload; unknown types fail explicitly rather
than importing arbitrary Python modules or silently becoming plain components.

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

One historical comparison of checkpoint `ace82b8` against `9f37a27` (median
milliseconds; not a measurement of the latest cutover):

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
native persistence, legacy rejection, forward references, reference lexing,
GUI inheritance edits/undo, movement/shooting/reopen and reference pills. The
graphics walkthrough uses real desktop rendering with synthetic input; it does
not substitute for your interactive acceptance test.
