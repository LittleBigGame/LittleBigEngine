"""Reproducible kernel/editor comparison; optionally execute a Git baseline.

Run with .venv/Scripts/python.exe benchmarks/kernel.py [--baseline 9f37a27].
Only isolated temporary projects are used. No checkout or user project changes.
"""
import argparse
import importlib.util
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
sys.path.insert(0, str(ROOT / 'src'))


def baseline(ref):
    import lbe
    for name in ('systems', 'scripts', 'core', 'project', 'ui'):
        code = subprocess.check_output(['git', '-c', f'safe.directory={ROOT.as_posix()}', 'show', f'{ref}:src/lbe/{name}.py'], cwd=ROOT).decode('utf-8')
        spec = importlib.util.spec_from_loader(f'lbe.{name}', loader=None, origin=str(ROOT / f'src/lbe/{name}.py'))
        module = importlib.util.module_from_spec(spec)
        module.__file__ = spec.origin
        sys.modules[spec.name] = module
        setattr(lbe, name, module)
        exec(compile(code, module.__file__, 'exec'), module.__dict__)
    lbe.Runtime, lbe.Entity = lbe.core.Runtime, lbe.core.Entity
    lbe.SystemDefinition, lbe.SystemInstance = lbe.systems.SystemDefinition, lbe.systems.SystemInstance


def measure(call, repeats=3):
    samples = []
    for _ in range(repeats):
        start = perf_counter()
        call()
        samples.append((perf_counter() - start) * 1000)
    return round(statistics.median(samples), 3)


def run(ref=None):
    if ref:
        baseline(ref)
    from lbe import Runtime, SystemDefinition
    from lbe.project import serialize_entities, load_project, template_path
    from lbe.desktop import Input
    sys.path.insert(0, str(ROOT / 'tests'))
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
    results['reads_20000_ms'] = measure(lambda: [e.x for _ in range(20) for e in root.children])
    root.systems.attach('movement', SystemDefinition('def update(dt):\n    for e in query("x", "vx"):\n        e.x += e.vx * dt\n'))
    results['step_1000_x20_ms'] = measure(lambda: [runtime.step(.016) for _ in range(20)])
    results['serialize_1000_ms'] = measure(lambda: serialize_entities(runtime.entities))
    results['serialized_bytes'] = len(json.dumps(serialize_entities(runtime.entities)))
    runtime.close()

    with tempfile.TemporaryDirectory() as directory, patch('lbe.user_state.save_last_project'):
        template = template_path('editor')
        if ref:
            archive = subprocess.check_output(['git', '-c', f'safe.directory={ROOT.as_posix()}', 'archive', ref, 'src/lbe/templates/editor'], cwd=ROOT)
            import tarfile
            with tarfile.open(fileobj=io.BytesIO(archive)) as files:
                files.extractall(Path(directory) / 'baseline', filter='data')
            template = Path(directory) / 'baseline/src/lbe/templates/editor'
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
    args = parser.parse_args()
    print(json.dumps(run(args.baseline), indent=2))
