# LittleBigEngine

**A small foundation for a composable engine.**

LittleBigEngine (LBE) is a Python project exploring a hierarchical entity model:
entities hold arbitrary data, systems supply behavior, and an editor is built from
the same primitives as the applications it edits.

## Current release

Little Core provides entities, arbitrary components, hierarchy, tags, relations,
live queries, changes, events and independent Python script systems. Graphics and
the editor are under development.

## Run

Requires Python 3.11 or later.

```console
python -m pip install -e .
python -m lbe
```

The `lbe` command and `python main.py` launch the same entry point.

## Test

```console
python -m unittest discover -s tests -v
```

Continuous integration checks Python 3.11 and 3.14 on Windows and Linux.

## Design

See [Architecture](ARCHITECTURE.md) for the intended engine model.
See [Little Core](docs/core.md) for the implemented API. Run
`python examples/movement.py` for a script-driven movement example.

Created by **LittleBigGame**.
