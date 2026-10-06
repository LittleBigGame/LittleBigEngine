"""Profile saved bouncy-box projects with actual graphics and fixed simulation time.

Raw unthrottled frame timings and cProfile replay are separate measurements.
GPU completion is synchronized, so rendering is not just counting API calls.
"""
import argparse
import cProfile
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import pstats
import shutil
import statistics
import subprocess
import sys
import time


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))]


def healthy(runtime):
    failures = list(runtime.events.errors) + list(runtime.changes.errors)
    for entity in runtime.entities:
        for instance in (*entity.systems.values(), *entity.scripts.values()):
            failures.extend(instance.errors)
            if not instance.running:
                failures.append(f'Stopped attachment: {instance.name}')
    if failures:
        raise RuntimeError(failures[:10])
    game = runtime.services['game']
    for ball in game.children:
        if any(not math.isfinite(v) for v in (ball.x, ball.y, ball.vx, ball.vy, ball.temperature)):
            raise RuntimeError(f'Non-finite ball state: {ball.id}')
        if not -1e-6 <= ball.x <= game.box_w - ball.w + 1e-6 or not -1e-6 <= ball.y <= game.box_h - ball.h + 1e-6:
            raise RuntimeError(f'Ball escaped box: {ball.id}')
        if len(ball.payload['trace']) > 8:
            raise RuntimeError('Unbounded contact history')


def measure_case(directory, mode, output, *, frames, warmup, profile_frames, visible=False, resolution=(1440, 900)):
    import pyglet
    from pyglet import gl
    from lbe.desktop import Graphics, Input
    from lbe.project import load_project
    window = pyglet.window.Window(*resolution, visible=visible, vsync=False, caption=f'LBE profile: {directory.name} {mode}')
    window.switch_to()
    graphics = Graphics(window)
    runtime = None
    start = time.perf_counter()
    try:
        runtime = load_project(window, graphics, Input(), directory)
        load_ms = (time.perf_counter() - start) * 1000
        game = runtime.services['game']
        game.physics_enabled = mode != 'render_only'
        game.render_enabled = mode != 'physics_only'
        for _ in range(warmup):
            graphics.begin()
            runtime.step(1 / 60)
            graphics.finish()
            gl.glFinish()
            window.flip()
        healthy(runtime)
        phase = {'physics': 0.0, 'render': 0.0}
        for name in phase:
            instance = game.systems[name]
            original = instance.call
            def timed(stage, *values, original=original, name=name):
                before = time.perf_counter()
                try:
                    return original(stage, *values)
                finally:
                    phase[name] += time.perf_counter() - before
            instance.call = timed
        timings, update, submissions, gpu = [], [], [], []
        contacts, walls, messages, pairs = game.contacts, game.wall_contacts, game.messages, game.candidate_pairs
        sequence, activity = runtime.changes.sequence, runtime.services['log'].sequence
        tick = game.tick
        baseline_checksums = {b.id: b.checksum for b in game.children}
        for frame in range(frames):
            window.dispatch_events()
            before = time.perf_counter()
            graphics.begin()
            phase['physics'] = phase['render'] = 0.0
            runtime.step(1 / 60)
            step_end = time.perf_counter()
            graphics.finish()
            gl.glFinish()
            completed = time.perf_counter()
            window.flip()
            timings.append((time.perf_counter() - before) * 1000)
            update.append(phase['physics'] * 1000)
            submissions.append(phase['render'] * 1000)
            gpu.append((completed - step_end) * 1000)
            if frame % 16 == 0:
                healthy(runtime)
        healthy(runtime)
        result = dict(scene=directory.name, mode=mode, balls=len(game.children), frames=frames,
                      warmup_frames=warmup, timestep=game.timestep, substeps=game.tick - tick,
                      simulated_seconds=(game.tick - tick) * game.timestep,
                      load_ms=load_ms, mean_frame_ms=statistics.mean(timings),
                      median_frame_ms=statistics.median(timings), p95_frame_ms=percentile(timings, 0.95),
                      max_frame_ms=max(timings), throughput_fps=1000 / statistics.mean(timings),
                      physics_ms=statistics.mean(update), render_submission_ms=statistics.mean(submissions),
                      batch_and_gpu_completion_ms=statistics.mean(gpu),
                      ball_contacts=game.contacts - contacts, wall_contacts=game.wall_contacts - walls,
                      messages=game.messages - messages, candidate_pairs=game.candidate_pairs - pairs,
                      changed_checksums=sum(b.checksum != baseline_checksums[b.id] for b in game.children),
                      observable_changes=runtime.changes.sequence - sequence,
                      activity_records=runtime.services['log'].sequence - activity,
                      entities=len(runtime.entities), sprites=sum(k[0] == 'sprite' for k in graphics._pool),
                      gpu_textures=len(graphics._textures), graphics_objects=len(graphics._pool),
                      kinetic_energy=game.kinetic_energy, raw_frame_ms=timings,
                      healthy=True)
        if mode != 'render_only' and frames >= 20 and result['messages'] == 0:
            raise RuntimeError('Physics workload exchanged no collision messages')
        output.mkdir(parents=True, exist_ok=True)
        if mode == 'combined':
            # Capture an actual framebuffer, excluded from raw timed samples.
            graphics.begin()
            runtime.step(0)
            graphics.finish()
            gl.glFinish()
            pyglet.image.get_buffer_manager().get_color_buffer().save(str(output / 'scene.png'))
        profiler = cProfile.Profile()
        profiler.enable()
        for _ in range(profile_frames):
            graphics.begin()
            runtime.step(1 / 60)
            graphics.finish()
            gl.glFinish()
            window.flip()
        profiler.disable()
        healthy(runtime)
        profiler.dump_stats(str(output / 'cpu.pstats'))
        stream = io.StringIO()
        stats = pstats.Stats(profiler, stream=stream)
        stats.sort_stats('cumulative').print_stats(40)
        stats.sort_stats('tottime').print_stats(40)
        (output / 'cpu.txt').write_text(stream.getvalue(), encoding='utf-8')
        result['profile_frames'] = profile_frames
        result['profile_total_seconds'] = stats.total_tt
        result['top_cumulative'] = [dict(file=file, line=line, function=function, primitive_calls=data[0],
                                       calls=data[1], self_seconds=data[2], cumulative_seconds=data[3])
            for (file, line, function), data in sorted(stats.stats.items(), key=lambda item: item[1][3], reverse=True)[:30]]
        (output / 'timings.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result
    finally:
        if runtime is not None:
            runtime.close()
        graphics.close()
        window.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenes', nargs='?', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--counts', type=int, nargs='+')
    parser.add_argument('--frames', type=int, default=120)
    parser.add_argument('--warmup', type=int, default=30)
    parser.add_argument('--profile-frames', type=int, default=30)
    parser.add_argument('--modes', nargs='+', choices=['physics_only', 'render_only', 'combined'],
                        default=['physics_only', 'render_only', 'combined'])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--visible', action='store_true')
    args = parser.parse_args()
    if args.frames < 1 or args.warmup < 0 or args.profile_frames < 1:
        parser.error('frames/profile-frames must be positive and warmup nonnegative')
    import pyglet
    if not args.visible and sys.platform != 'win32':
        pyglet.options['headless'] = True
    from pyglet import gl
    scenes = sorted(args.scenes.glob('BouncyBox_*'))
    if args.counts is not None:
        scenes = [p for p in scenes if int(p.name.rsplit('_', 1)[1]) in args.counts]
    if not scenes:
        parser.error('No matching saved scenes found')
    output = args.output or args.scenes / 'profiles'
    if output.resolve().exists() and any(output.iterdir()):
        parser.error('Output exists and is not empty; choose a new --output to preserve previous measurements')
    output.mkdir(parents=True, exist_ok=True)
    probe = pyglet.window.Window(visible=False)
    probe.switch_to()
    environment = dict(timestamp=datetime.now(timezone.utc).isoformat(), python=sys.version,
                       platform=platform.platform(), machine=platform.machine(), cpu=platform.processor(),
                       logical_cpus=os.cpu_count(), graphics_vendor=gl.gl_info.get_vendor(),
                       graphics_renderer=gl.gl_info.get_renderer(), graphics_version=gl.gl_info.get_version_string(),
                       pyglet=pyglet.version, resolution=[1440, 900], visible=args.visible,
                       interpretation='Unthrottled throughput; synchronized GL completion. Not interactive vsync FPS. '
                       'Raw timings exclude cProfile, startup, warmup, screenshots, and health checks. '
                       'All default runtime activity/effects/spatial/persistence observers remain enabled.')
    probe.close()
    import lbe
    kernel = Path(lbe.__file__).resolve().parents[2]
    revision = subprocess.run(['git', '-C', str(kernel), 'rev-parse', 'HEAD'],
                              capture_output=True, text=True, check=False) if shutil.which('git') else None
    environment['kernel_revision'] = revision.stdout.strip() if revision is not None and revision.returncode == 0 else 'installed package; Git metadata unavailable'
    environment['sample_frames'] = args.frames
    environment['warmup_frames'] = args.warmup
    environment['cpu_profile_frames'] = args.profile_frames
    results = []
    for directory in scenes:
        for mode in args.modes:
            print(f'Profiling {directory.name}: {mode}', flush=True)
            result = measure_case(directory, mode, output / directory.name / mode,
                                  frames=args.frames, warmup=args.warmup, profile_frames=args.profile_frames,
                                  visible=args.visible)
            results.append(result)
            print(f"  {result['throughput_fps']:.1f} fps, {result['mean_frame_ms']:.2f} ms mean, "
                  f"{result['p95_frame_ms']:.2f} ms p95, {result['messages']} messages", flush=True)
            # Save progress after every case; interrupted runs retain completed results.
            (output / 'summary.json').write_text(json.dumps(dict(environment=environment, results=results), indent=2), encoding='utf-8')
    rows = ['# LBE bouncy-box profile', '', f"Renderer: `{environment['graphics_renderer']}`", '',
            environment['interpretation'], '',
            '| Balls | Mode | Mean ms | P95 ms | Throughput fps | Physics ms | Render submission ms | Batch + GL completion ms | Messages |',
            '|---:|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in results:
        rows.append(f"| {r['balls']} | {r['mode']} | {r['mean_frame_ms']:.2f} | {r['p95_frame_ms']:.2f} | "
                    f"{r['throughput_fps']:.1f} | {r['physics_ms']:.2f} | {r['render_submission_ms']:.2f} | "
                    f"{r['batch_and_gpu_completion_ms']:.2f} | {r['messages']} |")
    rows += ['', 'CPU profiles (`cpu.txt`, `cpu.pstats`), raw frame samples (`timings.json`), and actual',
             'framebuffer captures (`scene.png`) accompany each case. cProfile replay is a separate',
             'later simulation window and its profiled timings are not used as the throughput numbers.', '']
    (output / 'REPORT.md').write_text('\n'.join(rows), encoding='utf-8')
    manifest = {str(p.relative_to(args.scenes)): hashlib.sha256(p.read_bytes()).hexdigest()
                for directory in scenes for p in directory.rglob('*')
                if p.is_file() and '__pycache__' not in p.parts}
    (output / 'scene-sha256.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(output / 'REPORT.md')


if __name__ == '__main__':
    main()
