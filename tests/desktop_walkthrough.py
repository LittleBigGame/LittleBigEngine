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
            runtime.step(0)
            editor = runtime.entities[0].items.require_value("application_state")
            moving, still = editor.game.children
            initial = moving.x, moving.y
            stationary = still.x, still.y

            def click(entity):
                assert editor.ui.visible(entity), entity
                return ("click", entity.x+entity.w/2, entity.y+entity.h/2, 1, 0)

            def enter(entity, text):
                assert not entity.items.get_value("readonly", False), entity
                return [click(entity), ("key", "A", True, False), ("text", text)]

            def menu_item(text):
                menu = editor.app.items.require_target("context_menu")
                return next(child for child in menu.children if text in child.items.get_value("text", ""))

            def component(key):
                return next(field for _, field in editor.item_rows
                            if field.visible and field.component_key == key)

            def code_menu():
                return ("click", editor.code.x+90, editor.code.y+90, 4, 0)

            steps = [
                lambda: [click(editor.add_item_button)],
                lambda: [click(menu_item("+ Velocity"))],
                lambda: enter(component("vx"), "3.0") + [("key", "ENTER", False, False)],
                lambda: enter(component("vy"), "1.0") + [("key", "ENTER", False, False)],
                lambda: [code_menu()],
                lambda: [click(menu_item("+ New system script"))],
                lambda: [code_menu()],
                lambda: [click(menu_item("Rename"))],
                lambda: enter(editor.path_field, "physics.py") + [("key", "ENTER", False, False)],
                lambda: enter(editor.code, SOURCE),
                lambda: [("key", "S", True, False)],
                lambda: [("click", row.x+row.w/2, row.y+row.h/2, 1, 0, 2)
                         for row in editor.hierarchy_rows if row.visible and row.items.target("target") is editor.game],
                lambda: [click(editor.add_item_button)],
                lambda: [click(menu_item('System /'))],
                lambda: [click(menu_item("physics"))],
            ]
            frame = 0

            def drive():
                nonlocal frame
                # Input is queued after this frame's UI update; give it a frame to dispatch.
                if frame % 2 == 0 and frame // 2 < len(steps):
                    input_state.pending.extend(steps[frame // 2]())
                if frame == 55:
                    assert moving.vx == 3.0 and moving.vy == 1.0
                    assert editor.game.items.has_behaviour("physics", kind='system')
                    assert editor.game.items.behaviour("physics", kind='system').running
                    assert (moving.x, moving.y) != initial
                    assert (still.x, still.y) == stationary
                    assert (Path(directory)/"physics.py").read_text(encoding="utf-8") == SOURCE
                    completed.append(True)
                frame += 1

            runtime.services["walkthrough"] = drive
            editor.app.items.attach_system("walkthrough", SystemDefinition("def update(dt): walkthrough()"))
            return runtime

        launch(build, headless=True, frames=60,
               screenshot=sys.argv[1] if len(sys.argv) > 1 else None)
        assert completed, "Walkthrough did not reach its final checks"
    print("Desktop walkthrough passed: components -> source -> attach -> movement.")


if __name__ == "__main__":
    main()
