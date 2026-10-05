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

Use `systems.reload(name, source_or_definition)` to reload. Compilation,
initialization, or start failure preserves the previous attachment and records
diagnostics. Reload restores the managed entity graph, attachment state, native
mutable containers, subscriptions and LBE service state in place. On success the
old instance stops and the replacement runs. UUID script reloads use the same
recovery boundary. External files, imported modules, native resources and opaque
user objects are outside this checkpoint; acquire external resources explicitly
and release them in `stop()`. Python execution remains trusted and synchronous.

Callbacks are bound before execution and called once. Both `update(dt)` and
`update(self, dt)` are supported, including keyword-only `self`/`dt`. A body
`TypeError` is reported without retrying the callback with different arguments.
The injected `self` is reset to the attachment owner after each system call.

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

## Persistent application state

`lbe.project.save_project(directory, entities=...)` saves an explicitly owned graph.
Save persistent application entities, not platform services or UI callbacks. Runtime
objects are rejected by default; `on_unsupported="skip"` is an explicit lossy option.
References to live entities outside that graph are rejected rather than silently
lost. `transient_relations` explicitly excludes links such as editor viewports.

Version 2 preserves detached parents and sibling order, escapes dictionary type
markers, and atomically replaces `project.json`. Versions 0 and 1 migrate on load.
Keep backups when upgrading; older engines cannot read version 2 projects.
Missing entity references become `EntityRef`; missing parent, relation and script
declarations remain available for recovery and resaving. Inspect
`restoration(runtime).diagnostics` for missing resources and initialization errors.

`deserialize_entities(..., activate=False)` first restores data and links. Set up
application services and temporary camera/viewport links, then call
`activate_entities(...)`. Script `start()` runs against the complete graph. It must
remain idempotent: avoid creating a second copy of children already restored from
storage. Project loading exposes `project_data` and `restoring` as runtime services;
application templates decide which state they own and restore. Loading a template
alone does not make all its arbitrary Python objects persistent.

`PersistentGraph` tracks explicit application ownership independently of UI
placement. Call `include(entity)` for additional owned entities and `close()` to
release its change subscription. Entity handles retain their identity when copied
inside `components.edit(...)`; containers are still copied.

`lbe.project_files.ProjectFiles` validates project-local moves/deletes and preserves
asset UUIDs and attached script instances. Its save callback must synchronously
save the same project's graph. Interrupted operations recover at project startup.
Deletion retains missing asset identities so restoring a resource recovers links.
This protects process interruption and ordinary write failures; it is not a
multi-process transaction or a substitute for backups against disk failure.


## Attached scripts and orchestration

A script declares its required component names and a callable:

```python
components = ("x", "y", "vx", "vy")

def run(entity, dt):
    entity.x += entity.vx * dt
    entity.y += entity.vy * dt
```

Resolve the file using its asset UUID (shown as a filename pill in the editor):

```python
movement = assets["<asset UUID>"]
player.scripts.attach(movement)
```

An orchestration system can run that script on matching descendants:

```python
def update(dt):
    for child in query(movement, *movement.components, recursive=True):
        child.run(movement, dt)
```

`query(movement)` selects entities with that attachment.
`query(*movement.components)` selects by component presence. Combining the two
requires both. An entity reference in a query selects entities containing that
specific direct child. Systems can also attach with `entity.systems.attach(pill)`;
the UUID supplies their identity without a registration alias. Existing named
system attachments remain supported for older projects.

The backend checks requirements and catches each script call's exception. It
records a source-attributed `script.error` and lets orchestration continue to
other entities. The editor opens System Log on such failures; Ctrl+L also opens
it. Calls do not roll back writes made before an exception, and trusted Python
can still modify shared state. This is failure containment, not a sandbox.

Script attachments persist through project save/load and asset moves. Deleting
their source through Project Files stops them; undo restores the attachment.
