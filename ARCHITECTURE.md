# LittleBigEngine - Design Overview

LittleBigEngine aims to make complex behavior emerge from a small set of generic
primitives. The entity/script runtime and desktop rendering adapter are implemented;
the self-hosted editor remains under development.

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

The editor is intended to use the same entities, components and systems as an
application. Hierarchy views, inspectors and editing panels expose the structures
from which they are built. New data and scripts can introduce behavior without
adding domain-specific logic to the kernel.

## Platform boundary

The optional desktop adapter uses pyglet 2.1 for window events, font rendering and
OpenGL batches. LBE retains control of the entity model, behavior and UI. Graphics
objects are cached across frames; a spatial hash is derived from observable
coordinate changes. The core has no third-party runtime dependency.

This choice provides a direct GPU path without committing the public engine API
to a GUI framework. Windows graphics smoke tests use a hidden native window;
Linux headless tests use EGL.
