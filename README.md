# LittleBigEngine

**A small foundation for a composable engine.**

LittleBigEngine (LBE) is a Python project exploring a hierarchical entity model:
entities hold arbitrary data, systems supply behavior, and an editor is built from
the same primitives as the applications it edits.

## Current release

The initial source package provides a command-line entry point and automated
installation checks. The entity runtime, graphics and editor are in development
and are not included in this release.

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

Created by **LittleBigGame**.
