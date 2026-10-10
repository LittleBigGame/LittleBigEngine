"""Reproducible kernel/editor comparison; optionally execute a Git baseline.

Run with .venv/Scripts/python.exe benchmarks/kernel.py [--baseline 9f37a27].
Only isolated temporary projects are used. No checkout or user project changes.
"""
import argparse
import io
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


def baseline(ref):
    """Measure a wholly isolated historical source tree, never mixed modules."""
    archive = subprocess.check_output(['git', '-c', f'safe.directory={ROOT.as_posix()}',
        'archive', ref, 'src', 'tests/test_scene.py'], cwd=ROOT)
    import tarfile
    with tempfile.TemporaryDirectory() as directory:
        with tarfile.open(fileobj=io.BytesIO(archive)) as files:
            files.extractall(directory, filter='data')
        output = subprocess.check_output([sys.executable, str(Path(__file__).resolve()),
            '--source-root', directory, '--historical-api'], cwd=directory)
        return json.loads(output)


def measure(call, repeats=3):
    samples = []
    for _ in range(repeats):
        start = perf_counter()
        call()
        samples.append((perf_counter() - start) * 1000)
    return round(statistics.median(samples), 3)


def run(source_root=ROOT, historical_api=False):
    sys.path.insert(0, str(source_root / 'src'))
    from lbe import Runtime, SystemDefinition
    from lbe.project import serialize_entities, load_project, template_path
    from lbe.desktop import Input
    sys.path.insert(0, str(source_root / 'tests'))
    from test_scene import RecordingGraphics
    results = {}

    def create():
        runtime = Runtime()
        root = runtime.create(tags=['root'])
        for _ in range(1000):
            runtime.create(parent=root, x=1., y=2., w=1., h=1., vx=3.)
        runtime.close()

    results['create_destroy_1000_ms'] = measure(create)
    runtime = Runtime()
    root = runtime.create(tags=['root'])
    for _ in range(1000):
        runtime.create(parent=root, x=1., y=2., w=1., h=1., vx=3.)
    results['query_1000_x20_ms'] = measure(lambda: [tuple(root.query('x', 'y')) for _ in range(20)])
    if historical_api:
        results['reads_20000_ms'] = measure(lambda: [e.x for _ in range(20) for e in root.children])
        root.systems.attach('movement', SystemDefinition('def update(dt):\n    for e in query("x", "vx"):\n        e.x += e.vx * dt\n'))
    else:
        results['reads_20000_ms'] = measure(lambda: [e.items.require_value('x') for _ in range(20) for e in root.children])
        root.items.attach_system('movement', SystemDefinition('def update(dt):\n    for e in query("x", "vx"):\n        e.items.set_value("x", e.items.require_value("x") + e.items.require_value("vx") * dt)\n'))
    results['step_1000_x20_ms'] = measure(lambda: [runtime.step(.016) for _ in range(20)])
    results['serialize_1000_ms'] = measure(lambda: serialize_entities(runtime.entities))
    results['serialized_bytes'] = len(json.dumps(serialize_entities(runtime.entities)))
    runtime.close()

    with tempfile.TemporaryDirectory() as directory, patch('lbe.user_state.save_last_project'):
        template = template_path('editor')
        window = SimpleNamespace(width=1440, height=900, set_clipboard_text=lambda text: None, get_clipboard_text=lambda: '')
        graphics = RecordingGraphics()
        editor_runtime = load_project(window, graphics, Input(), Path(directory) / 'project', template=template)
        for _ in range(3):
            editor_runtime.step(0)
        def frame():
            graphics.rectangles.clear()
            graphics.texts.clear()
            editor_runtime.step(0)
        results['editor_frame_ms'] = measure(frame, repeats=15)
        results['editor_entities'] = len(editor_runtime.entities)
        editor_runtime.close()
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline')
    parser.add_argument('--profile', action='store_true', help='Print cumulative bottlenecks for this workload')
    parser.add_argument('--source-root', type=Path, default=ROOT, help=argparse.SUPPRESS)
    parser.add_argument('--historical-api', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.profile:
        if args.baseline:
            parser.error('--profile measures the current source; use --baseline separately for timing comparison')
        import cProfile
        import pstats
        profile = cProfile.Profile()
        results = profile.runcall(run, args.source_root, args.historical_api)
        print(json.dumps(results, indent=2))
        pstats.Stats(profile).strip_dirs().sort_stats('cumulative').print_stats(24)
    else:
        print(json.dumps(baseline(args.baseline) if args.baseline else run(args.source_root, args.historical_api), indent=2))
