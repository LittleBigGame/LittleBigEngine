"""Real rendering with synthetic editor input; not a native input acceptance test."""
from pathlib import Path
import sys
import tempfile
import time

from lbe.desktop import launch
from lbe.project import load_project, template_path


def main():
    with tempfile.TemporaryDirectory() as directory:
        def build(window, graphics, input_state):
            runtime = load_project(window, graphics, input_state, directory, template=template_path('editor'))
            runtime.step(0)
            editor = runtime.entities[0].application_state
            code = editor.code
            editor.ui.focus(code)
            source = 'from pathlib import Path\n\nlocation = Path(".")\nlocation.ex'
            input_state.pending.extend([('key', 'A', True, False), ('text', source), ('key', 'SPACE', True, False)])
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                runtime.step(0)
                state = code.items.get_value('autocomplete_state', {})
                if state.get('active'):
                    break
                time.sleep(0.01)
            assert any(name == 'exists' for name, _ in state.get('matches', ())), state
            assert code.buffer.text == source
            if '--selection' in sys.argv:
                input_state.pending.append(('key', 'ESCAPE', False, False))
                runtime.step(0)
                code.buffer.anchor = 0
                code.buffer.cursor = source.index('location.ex')
                runtime.step(0)
                assert any(c.items.get_value('part') == 'selection:1' and c.visible for c in code.children)
            return runtime
        screenshot = next((a for a in sys.argv[1:] if a.endswith('.png')), None)
        launch(build, headless=True, frames=4, screenshot=screenshot)


if __name__ == '__main__':
    main()
