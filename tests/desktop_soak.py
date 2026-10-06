"""Timed real-graphics editing soak with synthetic input, not native acceptance."""

import argparse
from pathlib import Path
import tempfile
import time

from lbe import SystemDefinition
from lbe.desktop import launch
from lbe.project import load_project, template_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=90)
    parser.add_argument('--visible', action='store_true')
    args = parser.parse_args()
    if args.seconds < 1:
        parser.error('--seconds must be at least 1')
    failures, completed = [], []
    with tempfile.TemporaryDirectory(prefix='lbe-soak-') as directory:
        def build(window, graphics, input_state):
            import pyglet
            runtime = load_project(window, graphics, input_state, directory,
                                   template=template_path('editor'))
            runtime.step(0)
            editor = runtime.entities[0].application_state
            identity = editor.game.children[0].id
            frame = cycle = step = 0
            deadline = time.monotonic() + args.seconds

            def click(control, count=1):
                assert editor.ui.visible(control), control
                x, y = control.x + control.w / 2, control.y + control.h / 2
                return [('click', x, y, 1, 0, count), ('release', x, y, 1, 0)]

            def key(name, ctrl=False, shift=False):
                return [('key', name, ctrl, shift), ('key_up', name, ctrl, shift)]

            def select():
                target = runtime.resolve(identity)
                row = next(r for r in editor.hierarchy_rows
                           if r.visible and r.relations.get('target') is target)
                return click(row, 2)

            def edit():
                field = next(f for _, f in editor.component_rows
                             if f.visible and f.component_key == 'x')
                return click(field) + key('A', True) + [('text', str(cycle % 11))] + key('ENTER')

            def save():
                menu = editor.app.relations['context_menu']
                item = next(c for c in menu.children
                            if 'Save Project' in c.components.get('text', ''))
                return click(item)

            actions = [select, edit, lambda: key('Z', True), lambda: key('Z', True, True),
                       lambda: key('ESCAPE'), lambda: click(editor.menu_view_btn),
                       lambda: key('ESCAPE'), lambda: key('F3'), lambda: key('F3'),
                       lambda: click(editor.menu_file_btn), save,
                       lambda: [('cancel',)]]

            def drive():
                nonlocal frame, cycle, step
                try:
                    assert not runtime.events.errors, list(runtime.events.errors)
                    assert not runtime.changes.errors, list(runtime.changes.errors)
                    assert 'ui_error' not in editor.app.components, editor.app.components.get('ui_error')
                    for entity in runtime.entities:
                        for instance in (*entity.systems.values(), *entity.scripts.values()):
                            assert instance.running and not instance.errors, (instance.name, list(instance.errors))
                    assert len(runtime.entities) < 600, len(runtime.entities)
                    assert len(graphics._pool) < 5000, len(graphics._pool)
                    if time.monotonic() >= deadline:
                        assert cycle > 0, 'No complete editing cycle'
                        assert (Path(directory) / 'project.json').exists()
                        completed.append((frame, cycle, len(runtime.entities), len(graphics._pool)))
                        pyglet.app.exit()
                        return
                    if frame % 4 == 0:
                        input_state.pending.extend(actions[step]())
                        step += 1
                        if step == len(actions):
                            step = 0
                            cycle += 1
                    frame += 1
                except Exception as error:
                    failures.append(error)
                    pyglet.app.exit()

            runtime.services['soak'] = drive
            editor.app.systems.attach('soak', SystemDefinition('def draw(): soak()'))
            return runtime

        launch(build, headless=not args.visible)
    if failures:
        raise failures[0]
    assert completed, 'Soak did not reach its deadline'
    frames, cycles, entities, objects = completed[0]
    print(f'Desktop soak passed: {args.seconds:g}s, {frames} frames, {cycles} editing cycles, '
          f'{entities} entities, {objects} graphics objects.')


if __name__ == '__main__':
    main()
