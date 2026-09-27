# LittleBigEngine - Design Overview

LittleBigEngine aims to make complex behavior emerge from a small set of generic
primitives. The entity/script runtime, desktop rendering adapter and initial
entity-based editor are implemented.

## Entities and data

Entities provide identity, arbitrary components, tags, relations and hierarchy.
Components are normally flat values, accessible through attributes or a mapping.
Component storage remains the source of truth for derived indexes and views.

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
