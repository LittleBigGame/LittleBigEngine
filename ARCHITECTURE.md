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
project directory. Its `app.py` owns selection, hierarchy views, inspection,
source-file operations and system attachment decisions. Those policies are absent
from the engine and generic UI layer.

The public UI API supplies control creation, focus, input routing, text editing,
stack layout and rendering. A separate ordinary `ui.py` attachment drives those
facilities. The same facilities power the independent counter/notes template.
There is no engine-side Editor class or editor runtime service.

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
