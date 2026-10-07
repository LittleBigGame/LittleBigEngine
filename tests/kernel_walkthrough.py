"""Real desktop rendering with synthetic input (not a manual GUI test)."""
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from lbe import SystemDefinition
from lbe.desktop import launch
from lbe.project import load_project, template_path
from lbe.text import TextBuffer


def main():
    complete = []
    with tempfile.TemporaryDirectory() as directory, patch('lbe.user_state.save_last_project'):
        def build(window, graphics, input_state):
            runtime = load_project(window, graphics, input_state, directory, template=template_path('editor'))
            runtime.step(0)
            editor = runtime.entities[0].items.require_value('application_state')
            player = editor.app.systems['app'].namespace['create_walk_shoot_demo']()
            speed = player.items.component('speed')
            editor.code.buffer = TextBuffer(
                '# Persistent references: friendly pills, UUID source on disk.\n'
                f'player = <|Entity:{player.id}|>\n'
                f'speed = <|Component:{speed.id}|>\n\n'
                '# Game / walk_shoot.py drives WASD movement and Space shooting.\n'
                '# Player.speed inherits PlayerBlueprint.speed; edits are patches.\n'
                'def update(dt):\n    pass\n')
            frame = 0
            initial = player.x

            def drive():
                nonlocal frame
                if frame == 2:
                    input_state.press('D')
                    input_state.press('SPACE')
                if frame == 12:
                    input_state.release('D')
                    input_state.release('SPACE')
                if frame == 24:
                    assert player.x > initial
                    assert tuple(editor.game.query(tags=('bullet',)))
                    assert any(e.items.has_tag('asset_pill') and e.visible for e in editor.code.children)
                    assert not editor.app.systems['app'].errors
                    assert not editor.game.systems['walk_shoot'].errors
                    complete.append(True)
                frame += 1

            runtime.services['kernel_walkthrough'] = drive
            editor.app.systems.attach('kernel_walkthrough', SystemDefinition('def update(dt): kernel_walkthrough()'))
            return runtime

        launch(build, headless=True, frames=30, screenshot=sys.argv[1] if len(sys.argv) > 1 else None)
        assert complete
    print('Kernel GUI rendering passed: inherited player speed, movement, bullets, reference pills.')


if __name__ == '__main__':
    main()
