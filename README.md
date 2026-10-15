# LittleBigEngine

LBE is a Python 3.13+ engine prototype built around persistent resource IDs, entities, components and scripts. The runtime has no third-party dependencies. The optional desktop editor uses Dear PyGui.

From a checkout, install the development tools and editor:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[editor,dev]"
.\.venv\Scripts\python.exe main.py
```

The default checkout opens `Example World` beside `main.py` and Application `2e4b8702e1e9514338d026d79d39f704`. It loads only that root's reachable resources. Missing selected data reports an error rather than creating another Application.

Select a different existing project and root:

```powershell
lbe --world "F:\MyProject" --application-id <32-character-persistent-id>
```

World data is kept outside the installed package. A wheel installation must supply `--world` and `--application-id`; the source checkout contains the sample project.

Verify changes:

```powershell
python -m pytest -q
python tools/check_architecture.py
ruff check tools tests
```

## Code map

- `LBE/kernel.py`: public API and the authoritative in-memory state.
- `LBE/registry.py`: runtime handles, identity, lifetime and controlled resource access.
- `LBE/storage.py`: JSON persistence, project loading, transactions and staged batch saves.
- `LBE/world.py`: entity components, hierarchy, queries and spawning.
- `LBE/scripts.py`: script source editing, compilation, activation and invocation.
- `LBE/ui.py`: UI component schemas, validation and event adapters.
- `LBE/proxy.py`, `LBE/views.py`: tracked mutation and immutable read projections.
- `editor/`: editor state and Dear PyGui panels.
- `tests/`, `tools/`: regression tests and architecture checks.

Reads return immutable projections; component writes go through tracked proxies or explicit mutation methods. Retrieve a new component view after replacing a component, reloading or rolling back a transaction.

Failed script reloads keep the last working module and expose diagnostics. Scripts execute as trusted Python in the host process: exception handling is not a sandbox or protection against infinite loops. A separate preview process remains a future capability.

See [current state](docs/CURRENT_STATE.md), [architecture](docs/ARCHITECTURE.md), and [verification](docs/TESTING.md). The `scratch/` folder contains historical experiments and is excluded from the installable packages; some experiments access the sample project and should be reviewed before running.
