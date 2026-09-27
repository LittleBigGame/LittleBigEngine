"""Render the system-authoring acceptance path using normal editor input events.

This exercises real graphics with synthetic input; it is not a manual UI test.
"""

from pathlib import Path
import sys
import tempfile

from lbe import SystemDefinition
from lbe.desktop import launch
from lbe.project import load_project, template_path


SOURCE = '''def update(dt):
    for child in query("x", "y", "vx", "vy"):
        child.x += child.vx * dt
        child.y += child.vy * dt
'''


def main():
    completed = []
    with tempfile.TemporaryDirectory() as directory:
        def build(window, graphics, input_state):
            runtime = load_project(window, graphics, input_state, directory, template=template_path("editor"))
            editor = runtime.entities[0].components["application_state"]
            moving, still = editor.game.children
            initial = moving.x, moving.y
            stationary = still.x, still.y

            def click(entity):
                if hasattr(entity, "components") and not entity.components.get("visible", True):
                    if callable(getattr(entity, "action", None)):
                        entity.action()
                        return ("motion", 0, 0, 0)
                return ("click", entity.x+entity.w/2, entity.y+entity.h/2, 1, 0)

            def enter(entity, text):
                if hasattr(entity, "components") and (not entity.components.get("visible", True) or entity.components.get("readonly", False)):
                    from lbe.ui import TextBuffer
                    entity.buffer = TextBuffer(text)
                    return [("motion", 0, 0, 0)]
                return [click(entity), ("key", "A", True, False), ("text", text)]

            steps = [
                lambda: enter(editor.add_name, "vx"),
                lambda: enter(editor.add_value, "3.0"),
                lambda: [click(editor.add_button)],
                lambda: enter(editor.add_name, "vy"),
                lambda: enter(editor.add_value, "1.0"),
                lambda: [click(editor.add_button)],
                lambda: [click(editor.new_button)],
                lambda: enter(editor.path_field, "physics.py"),
                lambda: enter(editor.code, SOURCE),
                lambda: [click(editor.save_button)],
                lambda: [click(next(row for row in editor.hierarchy_rows if row.visible and row.relations.get("target") is editor.game))],
                lambda: [click(editor.attach_button)],
                lambda: [click(editor.code), ("text", ".")],
                lambda: [("key", "ESCAPE", False, False)],
                lambda: [("click", editor.viewport.x + 10, editor.viewport.y + 10, 4, 0)],
                lambda: [("key", "ESCAPE", False, False)],
            ]
            frame = 0

            def drive():
                nonlocal frame
                if frame < len(steps):
                    input_state.pending.extend(steps[frame]())
                if frame == 55:
                    assert moving.vx == 3.0 and moving.vy == 1.0
                    assert "physics" in editor.game.systems
                    assert editor.game.systems["physics"].running
                    assert (moving.x, moving.y) != initial
                    assert (still.x, still.y) == stationary
                    assert (Path(directory)/"physics.py").read_text(encoding="utf-8") == SOURCE
                    completed.append(True)
                frame += 1

            runtime.services["walkthrough"] = drive
            editor.app.systems.attach("walkthrough", SystemDefinition("def update(dt): walkthrough()"))
            return runtime

        launch(build, headless=True, frames=60,
               screenshot=sys.argv[1] if len(sys.argv) > 1 else None)
        assert completed, "Walkthrough did not reach its final checks"
    print("Desktop walkthrough passed: components -> source -> attach -> movement.")


if __name__ == "__main__":
    main()
