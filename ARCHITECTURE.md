# LittleBigEngine - Design Overview

LittleBigEngine aims to make complex behavior emerge from a small set of generic
primitives. The entity/script runtime, desktop rendering adapter and initial
entity-based editor are implemented.

## Entities and data

Entities provide identity, arbitrary components, tags, relations and hierarchy.
Components are normally flat values, accessible through attributes or a mapping.
Component storage remains the source of truth for derived indexes and views.

### UUID-keyed item storage and linking

The native mutation boundary is `entity.items`: UUID-selected add/remove,
replacement, rename, behaviour reload and ordering update the actual records
and their lifecycle/change observations. Application-defined typed records are
accepted without adding Entity fields. Type/MRO indexes are disposable views
rebuilt from the UUID dictionary; they retain canonical record order after edits.
Named value/link helpers operate on those records, and `value_dict()` returns a
disposable snapshot, not writable authoritative state. Engine UI, editor template
and backend component consumers now use these native item operations. The older
dynamic data attributes still exist at this intermediate checkpoint; their
removal, native persistence and unified item inspector are outstanding cutover
work. `Entity.components`, `Entity.tags`, `Entity.relations`, `Entity.systems`
and `Entity.scripts`, their storage slots and their projection classes have been
removed. Tags, links and behaviours are actual UUID records; named helpers mutate those
records and maintain the disposable incoming-link index. `Runtime.create(items=...)`
accepts actual typed UUID records; the old `components=` argument is rejected.

On `codex/uuid-kernel-gui`, entity data is owned by one UUID-keyed `Items` store.
Named behaviour queries return disposable snapshots, not mutable collections.
Attachment/removal, reload, source relocation and file-history recovery use
item UUIDs at the mutation boundary. Execution namespaces no longer inject a
mutable `systems` collection. Source-asset identity is distinct from attachment
identity; script name edits do not invalidate UUID or source-asset bindings.
Components, inherited declarations, tags, relation/parent links and
behavior attachments have persistent UUIDs; links store target UUIDs. Name/type
indexes and ordered child adjacency are derived runtime state.

Inherited declarations retain a source UUID plus explicit operations; resolved
values are derived private copies. The linker maintains object/dependency indexes
and runtime-scoped slot/generation handles, not another authoritative model.
Project v3 prefers canonical item records and migrates legacy named declarations.
Restore registers all behavior attachments before linking/initializing/starting.
`<|Type:uuid|>` source references are lexically lowered outside strings/comments.
The editor displays typed reference pills, identity menus and inheritance controls.
See [UUID kernel guide](docs/UUID_KERNEL_GUIDE.md) for APIs, GUI usage and limits.

## Hierarchy and queries

Hierarchy organizes entities and establishes query boundaries. It does not imply
transform inheritance. An attached system normally queries its owner's direct
children, selecting entities by the data they contain.

## Systems

Python scripts supply behavior. A shared system definition can create independent
runtime instances, each with its own mutable script state. A frame executes all
updates before drawing.

## World space

Coordinates are continuous, with one world unit conventionally representing one
metre. Cameras map world units to screen pixels. Spatial indexes derive from
component values and remain implementation details.

## A self-hosted editor

The editor uses the same entities, components and systems as an application.
Hierarchy rows, inspector fields, source lines, selections, buttons and panels
are entities. The editor is a bundled application template, loaded from the user's
project directory.

The editor's architecture is decomposed into modular attached systems:
- `hierarchy.py` attached to the hierarchy panel entity drives tree traversal,
  expansion toggles, and row recycling.
- `inspector.py` attached to the inspector panel entity drives collapsible sections,
  inline component renaming, quick-add preset menus, component type conversions,
  and system/relation links.
- `code_editor.py` attached to the code panel provides syntax highlighting, diagnostics,
  bracket matching, and off-thread autocomplete and hover inspections.
- `render.py` attached to the game entity renders the scene through the camera view.
- `app.py` coordinates layout, viewport navigation, splitters, project persistence,
  and context menu routing.

The public UI API supplies control creation, focus, input routing, text editing,
layout engines (`stack`, `dock`, `apply_layout`), and rendering. A separate ordinary
`ui.py` attachment drives those facilities. The same facilities power the independent
counter/notes template. There is no engine-side Editor class or editor runtime service.

The text buffer is an independent editing data structure stored as a component;
it does not use an external code editor. New data and scripts introduce behavior
without adding domain-specific logic to the kernel.

## Platform boundary

The optional desktop adapter uses pyglet 2.1 for window events, font rendering and
OpenGL batches. LBE retains control of the entity model, behavior and UI. Graphics
objects are cached across frames; a spatial hash is derived from observable
coordinate changes. The core has no third-party runtime dependency.

This choice provides a direct GPU path without committing the public engine API
to a GUI framework. Windows graphics smoke tests use a hidden native window;
Linux headless tests use EGL.

## Dependency boundary

```text
Project app.py / render.py / ui.py
              |
      Public entity + UI APIs
              |
   Generic runtime and platform services
```

The project loader knows how to load script files; it does not construct scenes or
editor panels. Templates initialize new projects without overwriting existing
project files. Applications can omit the UI entirely or replace it with their own
systems while retaining the entity/runtime APIs.

Context menus use `lbe.menus` above Core. Popup panels and action rows are normal
UI entities, with the active popup referenced by the UI root's `context_menu`
relation. Applications resolve pointer targets and supply action providers;
editor-specific actions remain in the editor template scripts.
A unified `+ Add Component...` action operates identically across Viewport, Hierarchy,
and Inspector. Context menus on components provide type conversions (`Change type...`)
and contextual entity actions when referencing other entities. Continuous Ctrl-key tracking
provides full ancestor stack highlighting and deep context inspection.

Optional Python completion uses Jedi static analysis in a serialized background
worker outside Core. Editor entities own request state and discard stale results;
UI and text selection remain reusable control behavior. The desktop extra includes
Jedi, while the core package retains no runtime dependencies.

### Asset Registry, File Explorer & Inline GUI Pills

Project assets (scripts, images, audio, data) are managed by `AssetRegistry` (`lbe.assets`)
using persistent UUID handles stored in `project.json`. Components reference assets via
`AssetRef(uuid, type, name)` primitives. The File Explorer (`file_explorer.py`) provides
an interactive project directory tree with drag-and-drop capability.

Dragging assets into the Code Editor inserts persistent UUID tokens (`asset("<uuid>")`),
which are rendered as rich inline GUI pills (chip buttons). To preserve exact caret navigation
and text buffer indices, the underlying token characters are visually masked with whitespace
in the text line label while an inline pill button is rendered directly above. Right-clicking
an inline pill provides context actions to locate the file in the explorer, rename the file,
replace the asset reference, copy its UUID, or remove the reference.

Because references are bound by persistent UUIDs, files can be renamed on disk and in the
registry without modifying script source code or component values, updating all visual pills
and inspector chips automatically.

## Activity observation

The runtime publishes bounded value descriptions and source context with changes.
Named-event observers and generic system lifecycle emissions support derived
activity tooling. `ActivityLog` subscribes above Core, retains bounded immutable
records, and excludes its presentation subtree to prevent logging feedback. The
editor's `system_log.py` composes ordinary UI entities; no log panel concepts enter
Core. Observation preserves direct-child queries, independent system namespaces,
listener failure isolation, and all-update-before-all-draw ordering.


Query iteration publishes a generic `query.result` observation containing the
snapshot returned to its caller. `SystemEffects` derives per-attachment queried
and written entity UUID sets from that observation and existing source-attributed
changes. It retains no entity handles and discards detached/deleted attachments.
Registry identities and current attachment paths remain authoritative. Editor
colouring, menu actions and overlays are ordinary template system behavior above
Core; the runtime does not know about inspection colours or panels. Nested
template files retain per-file upgrade provenance and recovery.


Hierarchy view scope is an ordinary panel `view_root` relation; file view scope
is a project-relative `view_root` component on the file panel. Template systems
derive rows from those scopes and promote them to containing ancestors when
revealing outside selections. Actual hierarchy, project paths and asset identity
remain authoritative and unchanged. View scope defaults are applied each session.


`History` stores reversible session commands above Core. ProjectFiles registers
transactional file actions; inspector systems record explicit component commits,
rather than treating runtime simulation writes as user edits. Components remain
authoritative. Retained deletion uses the existing file-operation journal and a
hidden trash location. Required editor-source checks are template policy, not
Core entity or filesystem semantics.


Attached scripts (`lbe.scripts`) reuse generic definition and instance execution
semantics, declare required components, and expose per-entity `run` calls. Core
queries accept stable asset references to match script/system attachments, or
explicit requirement tuples to match data. Systems orchestrate these calls;
script exceptions are caught at the backend boundary and emitted as
`script.error` changes with source attribution. Editor templates consume those
records to open the log panel. Persistence retains script UUIDs and source paths.
The runtime does not schedule scripts automatically or add domain-specific
rendering semantics. Legacy named system attachments remain compatible.
