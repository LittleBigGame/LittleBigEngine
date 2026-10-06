# Portable LBE test scenes

Extract the bundle's contents into `F:/LBETestScenes`. Nothing in a scene depends
on that drive letter: move/copy the whole project, including `project.json`, to
any machine. Install the `feature/textures-physics-profiling` GitHub branch (which
includes the stabilization changes) with Python 3.11+:

```powershell
git clone --branch feature/textures-physics-profiling https://github.com/LittleBigGame/LittleBigEngine.git
cd LittleBigEngine
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[desktop]"
.\.venv\Scripts\python.exe -m lbe --project F:/LBETestScenes/BouncyBox_00512
```

The ZIP includes saved **128, 512, 2048 and 4096-ball** projects, initial entity
state, seeds/settings, shared RGBA ball texture, UUID-attached scripts and profiles.
Space/F5 pauses; S saves the current scene. Closing without S leaves the measured
initial state intact. Choose a lower-count scene first on a slower machine.

## Reproduce profiles on your PC

```powershell
.\.venv\Scripts\python.exe F:/LBETestScenes/profile_scenes.py --output F:/LBETestScenes/profiles-my-pc
```

Add `--visible` to watch rendering, `--counts 128 512` to select loads, or
`--frames 300 --warmup 60 --profile-frames 60` for a longer sample. Output must be
new/empty, so old measurements are not overwritten. The prebuilt cloud results
are in `profiles/`; compare on your own hardware rather than treating software
EGL throughput as your Windows GPU performance.

There are independent **physics-only, render-only and combined** runs, each loaded
from the exact same saved initial state. Frames use 1/60 simulated seconds and
two 1/120 physics substeps. Real sprite batches are drawn and GL completion is
synchronized. Raw mean/p95 frame times are measured without cProfile; CPU call
profiles are a separate replay. Startup/warmup/health checks are excluded from
throughput. Inspect `summary.json`, `timings.json`, `cpu.txt`, `cpu.pstats`, and
combined-mode `scene.png` captures. Scene file SHA-256 manifests are included.

## Workload

Circle/circle and circle/wall collisions use mass-weighted normal impulses,
near-elastic restitution, overlap correction, tangential friction and angular
velocity. Gravity is enabled. This is discrete small-step 2D physics, not a
continuous collision solver or a validated production physics library.

The box grows with population, keeping initial density similar. Neighbours are
found through LBE's observable spatial hash, not an all-pairs shortcut. Every
impact routes events by entity UUID to independent UUID-attached contact scripts.
Balls exchange heat, rolling checksums and bounded signal/history payloads, link
their last collision partner, read linked neighbours, update tags/material
restitution and tint, and feed these values back into later physics/rendering.
Each ball also has an independent UUID drawing script and a shared texture UUID.

Normal component/change notifications, event routing, activity log, system-effect
attribution and persistent graph tracking remain enabled. Histories are bounded.
This is intra-engine message exchange, **not network/socket performance**. Profiling
does not silently disable diagnostics to inflate throughput.

## Build more scenes from the repository

```console
python examples/bouncy_box/build.py --output /path/to/new-scenes --counts 128 512 2048 4096
python examples/bouncy_box/profile_scenes.py /path/to/new-scenes --output /path/to/new-profile
```

Scene construction is deterministic for the saved seed, refuses to overwrite
existing projects, and uses no optional graphics dependencies. Rendering and
profiling require `.[desktop]`. Archive generation excludes caches and hidden
working state; use `build.zip_bundle(...)` after profiling to package results.
