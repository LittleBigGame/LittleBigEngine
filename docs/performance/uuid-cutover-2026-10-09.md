# Native UUID persistence checkpoint

Scope: engine checkpoint `17fe722` plus the repaired benchmark harness. This is
an intermediate measurement, not completion of the full migration. The unified
inspector and removal of dynamic Entity data attributes are still outstanding.

## Verification

Full unittest discovery passed 343 tests in 158.758 seconds. Native v4 documents
contain Entity `id` and `items` only. Tests cover rejection of old formats before
writes, preservation/recovery of missing declarations, item UUIDs, source asset
identities, runtime handles, forward references and application dataclass codecs.
Startup and the synthetic real-desktop walk/shoot/reference-pill walkthrough
also passed during the persistence cutover.

## Reproducible comparison

Run `.venv/Scripts/python.exe benchmarks/kernel.py`, then the same command with
`--baseline 9f37a27`. The baseline now runs in a fresh subprocess against the
entire historical source tree and its historical recording graphics fixture.
It does not combine old core modules with current collaborators. Both workloads
use isolated temporary projects; user projects and the checkout are untouched.

The historical workload uses its historical public API; the current workload
uses native Items operations. Workloads perform the same logical work. These are
local CPU/recording-backend results, not GPU FPS or portable performance promises.
Three-repeat workload medians (15 repeats for the warmed editor frame):

| Workload | Historical `9f37a27` | Native cutover |
| --- | ---: | ---: |
| Create/destroy 1,000 entities, ms | 18.438 | 86.467 |
| Query 1,000 entities, 20 times, ms | 27.466 | 27.499 |
| 20,000 public component reads, ms | 4.094 | 34.456 |
| 1,000 moving entities, 20 steps, ms | 114.608 | 411.524 |
| Serialize 1,000 entities, ms | 15.880 | 31.080 |
| Serialized fixture bytes | 282,205 | 670,324 |
| Warm editor frame, ms | 10.747 | 24.443 |
| Editor entities | 205 | 205 |

The migration is not a speed improvement. Persistent per-item UUIDs and typed
records still cost substantially more than the old value dictionaries. Native
serialization no longer emits redundant compatibility projections, but the
fixture remains larger than the historical one because item identities and
typed payloads are now persisted.

## Measured bottlenecks and decision

`benchmarks/kernel.py --profile` provides cumulative cProfile output; profiled
timings are not substituted for the unprofiled table above. In this workload:

- `Items.set_value` accounted for 2.320 seconds cumulatively across 62,738 calls;
  `Items.replace` accounted for 1.896 seconds across 62,509 calls.
- `Items.value` accounted for 1.693 seconds across 378,526 calls, including 0.948
  seconds in `Linker.component_value`.
- Native named reads, immutable record replacement and repeated UUID lookup are
  meaningful costs. UUID hashing occurred 2,077,517 times, costing 0.593 seconds
  cumulatively. Change publication and record/index updates also contribute.

These identify specific general-purpose runtime boundaries to optimize after
the functional cutover. They do not demonstrate a need to rewrite the whole
engine. Continue evolving the current engine provisionally; do not claim that
performance is now acceptable for large worlds. The final migration audit must
repeat this comparison and profiling after the remaining changes, then decide
whether targeted runtime representation changes are sufficient. Issue #95
tracks the regression; this checkpoint does not close it.
