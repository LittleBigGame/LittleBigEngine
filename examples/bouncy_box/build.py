"""Build portable, saved LBE physics test projects and an optional ZIP bundle."""
import argparse
import json
import math
from pathlib import Path
import shutil
import struct
import sys
from types import SimpleNamespace
import zipfile
import zlib

from lbe.project import load_project


class BuildGraphics:
    """Construction only: no rendered-frame or timing claims use this adapter."""
    pass


def ball_png(size=48):
    """Small shaded RGBA circle with a stripe so spin is visible; no image deps."""
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            nx, ny = (x + 0.5) / size * 2 - 1, (y + 0.5) / size * 2 - 1
            radius_squared = nx * nx + ny * ny
            if radius_squared > 1:
                raw.extend((0, 0, 0, 0))
            else:
                nz = math.sqrt(1 - radius_squared)
                shade = int(255 * max(0.25, min(1.0, 0.45 + 0.5 * nz - 0.2 * nx - 0.2 * ny)))
                if abs(nx - ny * 0.4) < 0.1:
                    shade = max(30, shade // 2)
                raw.extend((shade, shade, shade, 255))
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', size, size, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def build_scene(directory, count, *, seed=271828):
    if type(count) is not int or not 2 <= count <= 100000:
        raise ValueError('Ball count must be an integer from 2 to 100000')
    directory = Path(directory).resolve()
    if directory.exists() and any(directory.iterdir()):
        raise FileExistsError(f'Refusing to overwrite scene: {directory}')
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copytree(Path(__file__).parent / 'template', directory, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (directory / 'textures').mkdir()
    (directory / 'textures/ball.png').write_bytes(ball_png())
    config = dict(balls=count, seed=seed, gravity=-7.5, timestep=1 / 120,
                  restitution=0.995, scene_version=1)
    (directory / 'scene.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    window = SimpleNamespace(width=1440, height=900)
    runtime = load_project(window, BuildGraphics(), None, directory)
    try:
        for entity in runtime.entities:
            for instance in (*entity.systems.values(), *entity.scripts.values()):
                if not instance.running or instance.errors:
                    raise RuntimeError((instance.name, list(instance.errors)))
        runtime.entities[0].systems['app'].namespace['save_scene']()
    finally:
        runtime.close()
    return directory


def zip_bundle(directory, destination):
    directory, destination = Path(directory).resolve(), Path(destination).resolve()
    if destination.is_relative_to(directory):
        raise ValueError('ZIP must be outside the scene bundle')
    if destination.exists():
        raise FileExistsError(destination)
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(directory.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and not any(p.startswith('.') for p in path.relative_to(directory).parts):
                archive.write(path, path.relative_to(directory).as_posix())
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--counts', type=int, nargs='+', default=[128, 512, 2048, 4096])
    parser.add_argument('--seed', type=int, default=271828)
    parser.add_argument('--zip', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for count in args.counts:
        path = build_scene(args.output / f'BouncyBox_{count:05d}', count, seed=args.seed)
        print(f'Saved {count} balls: {path}', flush=True)
    shutil.copy2(Path(__file__).parent / 'profile_scenes.py', args.output / 'profile_scenes.py')
    shutil.copy2(Path(__file__).parent / 'README.md', args.output / 'README.md')
    if args.zip:
        print(zip_bundle(args.output, args.zip))


if __name__ == '__main__':
    main()
