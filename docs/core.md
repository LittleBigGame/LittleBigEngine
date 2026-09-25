# Little Core

```python
from lbe import Runtime, SystemDefinition

runtime = Runtime()
game = runtime.create(tags=["root"], name="Game")
player = runtime.create(parent=game, x=0.0, y=0.0)
player.vx = 2.0
player.vy = 1.0

game.systems.attach("movement", SystemDefinition('''
def update(dt):
    for child in query("x", "y", "vx", "vy"):
        child.x += child.vx * dt
        child.y += child.vy * dt
'''))
runtime.step(0.5)
assert (player.x, player.y) == (1.0, 0.5)
```

## Entities

Each runtime owns its entities. `entity.id` is a UUID; `runtime.resolve(id)` accepts
a UUID or its string representation. Entities from different runtimes cannot be
parented or related. Destroying an entity destroys its subtree, stops attached
systems and removes incoming relations. A destroyed handle rejects further access
to mutable data; its identity and `alive` flag remain inspectable.

Components are arbitrary Python values. Attribute access and `entity.components`
share the same storage. Names reserved by the entity API remain usable as mapping
keys: `entity.components["id"]` does not replace its identity.

Assignment and deletion publish changes automatically. For nested objects, use
`with entity.components.edit("settings") as settings:` to edit a deep copy and
commit once on successful exit. Exceptions discard that copy. Objects that cannot
be copied can be mutated externally followed by `entity.components.touch(name)`.
Unannounced in-place mutations of native Python containers are not intercepted.

## Hierarchy, tags and relations

Set `entity.parent` to reparent or `None` to detach. Cycles are rejected before
mutation. Children are an ordered, read-only tuple; `move_child(child, index)`
changes their order. `ancestors`, `descendants`, `siblings` and `depth` are derived.

`root` is the nearest entity tagged `root`, including the entity itself, falling
back to the topmost ancestor. `inherit(name, default)` searches self then ancestors.
Without a default, a missing value raises `KeyError`.

`tags.add(name)` and `tags.discard(name)` manage string tags.
`relations[name] = target` creates a named directed link to one live entity.

## Queries

`entity.query("x", "y", tags=("visible",))` matches direct children.
`recursive=True` includes descendants. `runtime.query(...)` searches the runtime.
Queries are reusable: each iteration captures a fresh membership snapshot in
hierarchy or creation order. Component changes and reparenting need no query reset.

`closest(...)` finds the first compatible entity among self and ancestors.
`find(...)` finds the first compatible descendant in depth-first order.

## Script systems

`SystemDefinition(source, path)` compiles immutable source. `runtime.assets.system(path)`
caches definitions by canonical path and content. Each attachment executes source
in a fresh namespace, including fresh script-defined mutable globals. Imported
modules and intentionally injected runtime services remain shared Python objects.

Scripts receive `entity`, `system`, `systems`, `create`, `resolve`, `destroy`,
`query`, `events`, `changes` and `assets`. `create(parent=entity, ...)` makes a child.
Applications may provide platform services through `runtime.services`.

Top-level execution initializes an attachment, followed by optional `start()`.
Each `step(dt)` executes all `update(dt)` callbacks before all `draw()` callbacks.
Attachment order is deterministic; `systems.move(name, index)` reorders it.
New or reloaded attachments join on the next frame. Detaching stops immediately.

Use `systems.reload(name, source_or_definition)` to reload. Compilation or staged
initialization failure preserves the previous attachment and records diagnostics.
On success the old instance stops and the new instance starts. Top-level script
side effects outside its own namespace cannot be rolled back; acquire external
resources in `start()` and release them in `stop()`.

Script errors stop that instance's frame callbacks and remain in `instance.errors`.
Other systems continue. `globals`, `lifecycle`, `definition`, `entity`, `name` and
`running` support inspection. This is trusted Python execution, not a sandbox.

## Events and changes

`runtime.events.on(name, callback)` returns an unsubscribe function; `emit` calls
subscribers synchronously. `system.listen` owns a subscription and removes it on
stop. Event listener failures are recorded without aborting other listeners.

`runtime.changes.subscribe(callback)` observes structural operations. Each change
has a monotonic sequence, kind, entity and optional key. Re-read live state for the
current value. Recent history is bounded to 4,096 records; subscribe for a complete
live stream. Listener errors are available through `changes.errors`.
