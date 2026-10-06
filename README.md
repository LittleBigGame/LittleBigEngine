# LittleBigEngine

**A small engine that can inspect and extend itself.**

LittleBigEngine (LBE) is a Python project exploring a hierarchical entity model:
entities hold arbitrary data, systems supply behavior, and an editor is built from
the same primitives as the applications it edits.

## Current release

Little Core provides entities, arbitrary components, hierarchy, tags, relations,
live queries, changes, events and independent Python script systems. The desktop
runtime renders a two-entity scene through an ordinary script, with camera
transforms and automatically refreshed spatial indexing. The first entity-based
editor includes a hierarchy, live component inspector, source editor and script
attachment/reload. This is an early functional release, not a finished production engine.

## Run

Requires Python 3.11 or later.

```console
python -m pip install -e ".[desktop]"
python -m lbe
```

The `lbe` command and `python main.py` launch the same entry point.
Use `python -m lbe --check` to check the core without opening a window.
The core alone installs with `python -m pip install -e .`.
System sources are saved under `workspace/` by default. Choose a different folder
with `python -m lbe --project path/to/project`. Use `--demo` for the rendering-only scene.

See the [editor guide](docs/editor.md) for controls and the live movement walkthrough.
The editor is a project template made with the public APIs, not an engine-side
application service. Its `app.py`, `ui.py` and `render.py` are editable project files.
Try an unrelated application built with the same UI API:

```console
python -m lbe --template counter
```

See [UI and application scripting](docs/ui.md) to build your own application.
See [Project textures](docs/textures.md) to import images, use UUID texture pills,
and draw camera-aware sprites.
The [bouncy-box test scenes](examples/bouncy_box/README.md) exercise observable
physics, UUID-routed collision data and texture rendering at several entity loads.

## Test

```console
python tests/run_suite.py -v
python tests/desktop_walkthrough.py
python tests/desktop_soak.py --seconds 90
```

Continuous integration checks Python 3.11 and 3.14 on Windows and Linux.
The desktop walkthrough uses real graphics and synthetic editor input.
The timed soak repeats visible editing, undo/redo, menus and project saves while
checking script health and bounded entity/graphics counts. Use `--seconds 1800`
for a 30-minute run or `--visible` to watch it.
The suite runner isolates preferences and caches and enables EGL on Linux.
The desktop CI job runs the full suite with completion and graphics installed.

## Design

See [Architecture](ARCHITECTURE.md) for the intended engine model.
See [Little Core](docs/core.md) for the implemented API. Run
`python examples/movement.py` for a script-driven movement example.

Created by **LittleBigGame**.
