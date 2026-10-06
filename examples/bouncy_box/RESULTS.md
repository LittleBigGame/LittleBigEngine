# Bouncy-box profiling results

Measured 2026-10-06 on kernel commit `a25534b6e35f5499c7c2c4c32dbbfd6ecea046f0`.
These are historical measurements of that commit and the original scene scripts.
The replacement bundle preserves initial entity state and UUIDs, but updates the
scripts for older-kernel compatibility. Rerun its profiler to measure those scripts;
the texture-free round-shape renderer is a different workload from these results.

## Method and limits

Linux x86-64, Python 3.12.14, 5 reported logical CPUs, pyglet 2.1.16,
1440x900 offscreen EGL. OpenGL renderer: **Mesa llvmpipe (LLVM 19.1.7)**.
This is software rendering, not a hardware-GPU or Windows acceptance benchmark.

Each mode reloads the same saved initial project: 20 warmup frames, 40 measured
frames at 1/60 simulated seconds, then a separate 8-frame cProfile replay.
Physics uses two 1/120 substeps per frame. GL completion is synchronized.
Startup, warmup, screenshots, health checks and cProfile overhead are excluded
from raw frame timings. Values are unthrottled throughput, not vsync FPS.
These short samples are a reproducible baseline, not a statistical hardware survey.

Normal change/event notifications, spatial indexing, activity logging, system
effects and persistent graph tracking are all enabled. No diagnostics were
silently disabled to improve the result. Scene dimensions grow with population
to keep initial density comparable; contacts still depend on the evolving state.

## Raw results

| Balls | Physics-only mean ms | Render-only mean ms | Combined mean ms | Combined p95 ms | Combined throughput fps |
|---:|---:|---:|---:|---:|---:|
| 128 | 41.94 | 11.03 | 59.03 | 71.50 | 16.9 |
| 512 | 189.54 | 34.64 | 249.99 | 305.93 | 4.0 |
| 2048 | 696.76 | 113.65 | 808.13 | 969.81 | 1.2 |
| 4096 | 1356.23 | 244.91 | 1653.24 | 1910.44 | 0.6 |

**The engine does not achieve real-time performance for this fully observable,
collision-heavy workload on this machine.** Rendering alone is also CPU-heavy.
These results should not be presented as a production-ready physics engine.

All twelve cases completed without script/change/event errors, non-finite
states, escaped balls or unbounded per-ball traces. The 4096-ball combined case
exchanged **45,826 collision messages** and published **2,804,532 changes** during
the 40 measured frames. Physics-only and combined message/change counts matched
for every population. All render cases used exactly **one shared GPU texture**
and one pooled sprite per ball.

## What the CPU profiles show

- Change publication and listener dispatch dominate physics. At 4096 balls the
  cProfile physics replay spent 27.51s inclusive in `Changes.publish`, out of
  40.34s inclusive in the physics update (about 68%). The activity-change handler
  accounted for 11.34s (about 28%); the spatial-change handler accounted for 5.32s.
  These are nested times: do not add the percentages.
- Actual circle impulse arithmetic is not the main isolated cost. Every position,
  velocity, material, relation and nested payload update fans out to observers.
  The collision loop's inclusive time contains many of those same notifications.
- Rendering is primarily Python-side submission/UUID script/query work.
  At 4096 balls, combined raw mean render submission was 258.42ms, while batch
  drawing plus synchronized GL completion was 6.93ms. CPU/GPU timer queries were
  not used; that latter figure is wall time for the completed graphics phase.
- Early profiling exposed per-ball filesystem probes when resolving texture
  UUIDs. These were removed: lazy UUID resolution now does no filesystem lookup,
  and the shared image is checked once per rendered frame. A 512-ball render-only
  sample changed from 46.16ms to 34.64ms after this correction. This is a useful
  directional comparison, not a controlled engine-wide speedup claim.

## Next optimization targets

First reduce repeated activity-source/UUID formatting and snapshot work, and
design coalesced observer notifications without breaking live spatial queries.
Then cache callback signature/binding plans per attachment (invalidate on reload)
and reduce repeated UUID/query dispatch in drawing. Keep the single shared
texture and native sprite batching already implemented. Remeasure before
choosing native physics or a renderer rewrite; a faster GPU alone will not
remove the measured Python observation/submission overhead.

## Reproduce and inspect

Extract the scene ZIP into any directory and follow its README. On Windows:

```powershell
python F:/LBETestScenes/profile_scenes.py --warmup 20 --frames 40 --profile-frames 8 --output F:/LBETestScenes/profiles-my-pc
```

The GitHub scene ZIP includes this summary and the exact initial projects.
A full local profiling bundle additionally contains raw frame samples, CPU
profiles, input SHA-256 manifests and real framebuffer captures under `profiles/`.
Raw logs/screenshots remain outside the source repository.
