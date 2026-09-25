"""Load a directory of application scripts through the public runtime API."""

from pathlib import Path
import shutil

from .core import Runtime
from .space import SpatialIndex


def template_path(name):
    root = Path(__file__).parent / "templates"
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_dir():
        raise ValueError("Unknown bundled application template")
    return path


def load_project(window, graphics, input_state, directory, *, template=None, entry="app.py"):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if template is not None and not (directory / entry).exists():
        for source in Path(template).glob("*.py"):
            destination = directory / source.name
            if not destination.exists():
                shutil.copyfile(source, destination)
    path = (directory / entry).resolve()
    if not path.is_relative_to(directory):
        raise ValueError("Entry point must be inside the project")
    runtime = Runtime()
    runtime.services.update(window=window, graphics=graphics, input=input_state, project=directory)
    runtime.services["space"] = SpatialIndex(runtime)
    root = runtime.create(name="Application", tags=["root"])
    try:
        instance = root.systems.attach(path.stem, runtime.assets.system(path))
        if not instance.running:
            raise RuntimeError(instance.errors[-1].traceback)
    except Exception:
        runtime.close()
        runtime.services["space"].close()
        raise
    return runtime
