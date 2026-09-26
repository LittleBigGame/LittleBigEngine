from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from lbe.desktop import Input
from lbe.project import load_project, template_path
from test_scene import RecordingGraphics


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.input = Input()
        self.graphics = RecordingGraphics()
        self.clipboard = ""
        self.window = SimpleNamespace(width=1440, height=900,
                                      set_clipboard_text=lambda text: setattr(self, "clipboard", text),
                                      get_clipboard_text=lambda: self.clipboard)
        self.runtime = load_project(self.window, self.graphics, self.input, self.directory.name, template=template_path("editor"))
        self.addCleanup(self.runtime.close)
        self.editor = self.runtime.entities[0].components["application_state"]
        self.runtime.step(0)
        self.assert_healthy()

    def assert_healthy(self):
        instance = self.editor.app.systems["app"]
        self.assertTrue(instance.running, list(instance.errors))
        self.assertEqual(list(instance.errors), [])

    def send(self, *events, dt=0):
        self.input.pending.extend(events)
        self.runtime.step(dt)
        self.assert_healthy()

    def click(self, entity):
        self.send(("click", entity.x+entity.w/2, entity.y+entity.h/2, 1, 0))

    def type(self, entity, text, commit=False):
        self.click(entity)
        self.send(("key", "A", True, False), ("text", text))
        if commit:
            self.send(("key", "ENTER", False, False))

    def select(self, target):
        row = next((row for row in self.editor.hierarchy_rows if row.visible and row.relations.get("target") is target), None)
        if row is None:
            for _ in range(20):
                self.send(("scroll", self.editor.hierarchy.x + 20, self.editor.hierarchy.y + 20, 0, -1))
                self.runtime.step(0)
                row = next((row for row in self.editor.hierarchy_rows if row.visible and row.relations.get("target") is target), None)
                if row is not None:
                    break
        if row is None:
            for _ in range(40):
                self.send(("scroll", self.editor.hierarchy.x + 20, self.editor.hierarchy.y + 20, 0, 1))
                self.runtime.step(0)
                row = next((row for row in self.editor.hierarchy_rows if row.visible and row.relations.get("target") is target), None)
                if row is not None:
                    break
        if row is not None:
            self.click(row)
            self.runtime.step(0)
        else:
            self.editor.app.relations["selection"] = target
            self.editor.game.relations["selection"] = target
            self.runtime.step(0)

    def test_live_component_editing_and_spatial_refresh(self):
        selected = self.editor.app.relations["selection"]
        x_field = next(field for _, field in self.editor.component_rows if field.visible and field.component_key == "x")
        self.type(x_field, "10.0", commit=True)
        self.assertEqual(selected.x, 10)
        self.assertIn(selected, self.runtime.services["space"].query(10, 0))
        color = next(field for _, field in self.editor.component_rows if field.visible and field.component_key == "color")
        self.type(color, "(255, 0, 128)", commit=True)
        self.assertEqual(selected.color, (255, 0, 128))
        self.assertIn((255, 0, 128), [kwargs["color"] for _, kwargs in self.graphics.rectangles if "color" in kwargs])

    def test_complete_system_authoring_path_through_input(self):
        moving, still = self.editor.game.children
        original = moving.x, moving.y
        stationary = still.x, still.y
        for name, value in (("vx", "2.0"), ("vy", "-1.0")):
            self.type(self.editor.add_name, name)
            self.type(self.editor.add_value, value)
            self.click(self.editor.add_button)
        self.assertEqual((moving.vx, moving.vy), (2, -1))
        self.click(self.editor.new_button)
        self.type(self.editor.path_field, "physics.py")
        self.type(self.editor.code, 'def update(dt):\n    for child in query("x", "y", "vx", "vy"):\n        child.x += child.vx * dt\n        child.y += child.vy * dt\n')
        self.click(self.editor.save_button)
        self.assertTrue((Path(self.directory.name)/"physics.py").exists())
        self.select(self.editor.game)
        self.click(self.editor.attach_button)
        self.runtime.step(0.5)
        self.assertEqual((moving.x, moving.y), (original[0]+1, original[1]-0.5))
        self.assertEqual((still.x, still.y), stationary)
        instance = self.editor.game.systems["physics"]
        self.assertTrue(instance.running)
        self.assertEqual(tuple(instance.errors), ())
        self.click(self.editor.system_panel_button)
        self.assertEqual(self.editor.extra_panels[-1].view_type, "system")
        self.assertIs(self.editor.extra_panels[-1].relations["target"], self.editor.game)

    def test_syntax_error_preserves_editor_and_previous_renderer(self):
        old = self.editor.game.systems["render"]
        self.type(self.editor.code, "def broken(")
        self.click(self.editor.save_button)
        self.assertIs(self.editor.game.systems["render"], old)
        self.assertTrue(old.running)
        self.assertIn("SyntaxError", self.editor.app.status)
        self.assert_healthy()

    def test_editor_source_is_visible_and_reload_keeps_spatial_index(self):
        self.select(self.editor.app)
        self.runtime.step(0)
        button = self.editor.system_rows[0]
        self.click(button)
        self.assertEqual(self.editor.path_field.buffer.text, "app.py")
        self.click(self.editor.save_button)
        self.runtime.step(0)
        self.assert_healthy()
        moving = self.editor.game.children[0]
        moving.x = 10
        self.assertIn(moving, self.runtime.services["space"].query(10, 0))

    def test_tags_relations_parent_and_generic_panel(self):
        moving = self.editor.app.relations["selection"]
        self.type(self.editor.tags_field, "visible, selected", commit=True)
        self.assertEqual(set(moving.tags), {"visible", "selected"})
        self.type(self.editor.relation_field, "friend=Entity B", commit=True)
        self.assertIs(moving.relations["friend"], self.editor.game.children[1])
        self.type(self.editor.parent_field, "Application", commit=True)
        self.assertIs(moving.parent, self.editor.app)
        self.click(self.editor.panel_button)
        panel = self.editor.extra_panels[-1]
        self.assertIs(panel.relations["target"], moving)
        self.assertIn(panel, self.editor.app.children)
        self.assertTrue(all("ui" in child.tags for child in panel.children))

    def test_clipboard_and_undo(self):
        self.type(self.editor.code, "hello")
        self.send(("key", "A", True, False), ("key", "C", True, False))
        self.assertEqual(self.clipboard, "hello")
        self.send(("text", "replacement"), ("key", "Z", True, False))
        self.assertEqual(self.editor.code.buffer.text, "hello")

    def test_unsupported_value_is_readonly(self):
        self.editor.app.relations["selection"].components.clear()
        self.editor.app.relations["selection"].opaque = object()
        self.runtime.step(0)
        field = next(field for _, field in self.editor.component_rows if field.visible)
        self.assertTrue(field.readonly)
        self.click(field)
        self.assertIsNot(self.editor.ui.focused, field)

    def test_source_cannot_escape_project_directory(self):
        self.type(self.editor.path_field, "../outside.py")
        self.click(self.editor.save_button)
        self.assertIn("inside the project", self.editor.app.status)

    def test_new_source_requires_repeat_before_discarding_edits(self):
        self.type(self.editor.code, "unsaved = 1")
        self.click(self.editor.new_button)
        self.assertEqual(self.editor.code.buffer.text, "unsaved = 1")
        self.assertIn("Unsaved", self.editor.app.status)
        self.click(self.editor.new_button)
        self.assertEqual(self.editor.code.buffer.text, "def update(dt):\n    pass\n")

    def test_component_panel_and_save_preserve_cursor(self):
        field = next(field for _, field in self.editor.component_rows if field.visible and field.component_key == "color")
        self.send(("click", field.x+10, field.y+10, 4, 0))
        self.send(("key", "DOWN", False, False))
        self.send(("key", "ENTER", False, False))
        self.assertEqual(self.editor.extra_panels[-1].view_type, "component")
        self.editor.extra_panels[-1].destroy()
        self.type(self.editor.code, "def draw():\n    pass\n")
        position = self.editor.code.buffer.cursor
        self.click(self.editor.save_button)
        self.assertEqual(self.editor.code.buffer.cursor, position)

    def test_game_runtime_error_keeps_editor_interactive(self):
        self.click(self.editor.new_button)
        self.type(self.editor.path_field, "broken.py")
        self.type(self.editor.code, "def update(dt): raise ValueError('script failed')")
        self.select(self.editor.game)
        self.click(self.editor.attach_button)
        self.runtime.step(1)
        self.assertFalse(self.editor.game.systems["broken"].running)
        self.assert_healthy()
        self.click(self.editor.panel_button)
        self.assertEqual(len(self.editor.extra_panels), 1)

    def test_project_source_reload_rebinds_actions_without_rebuilding_controls(self):
        from lbe import SystemDefinition
        root = self.editor.app
        old = root.systems["app"]
        source = old.definition.source.replace("New source:", "Revised source:")
        before = set(self.runtime.entities)
        replacement = root.systems.reload("app", SystemDefinition(source, old.definition.path))
        self.assertIsNot(replacement, old)
        self.assertEqual(set(self.runtime.entities), before)
        self.click(self.editor.new_button)
        self.assertIn("Revised source:", root.status)
        self.assertNotIn("editor", self.runtime.services)

    def test_source_editor_cursor_and_selection_alignment(self):
        code = self.editor.code
        pitch = code.components.get("pitch", 8.0)
        line_height = code.components.get("line_height", 20)
        self.click(code)
        self.send(("key", "A", True, False), ("text", "abcdefghijklmnopqrstuvwxyz\n1234567890"))

        # Click on character 15 of line 0 (before midpoint)
        click_x = code.x + 48 + 15 * pitch + pitch * 0.2
        click_y = code.y + 6 + line_height / 2
        self.send(("click", click_x, click_y, 1, 0))
        self.assertEqual(code.buffer.cursor, 15)

        # Click on character 15 of line 0 (after midpoint -> rounds to caret 16)
        self.send(("click", code.x + 48 + 15 * pitch + pitch * 0.8, click_y, 1, 0))
        self.assertEqual(code.buffer.cursor, 16)

        # Restore cursor to 15
        self.send(("click", click_x, click_y, 1, 0))
        self.assertEqual(code.buffer.cursor, 15)

        # Caret entity alignment
        caret = next(c for c in code.children if c.components.get("part") == "cursor")
        self.assertTrue(caret.visible)
        self.assertAlmostEqual(caret.x, code.x + 48 + 15 * pitch, delta=0.01)
        self.assertAlmostEqual(caret.y, code.y + 6, delta=0.01)

        # Select columns 5 to 12 on line 0
        code.buffer.anchor = 5
        code.buffer.cursor = 12
        code.components.touch("buffer")
        self.runtime.step(0)

        highlight = next(c for c in code.children if c.components.get("part") == "selection:0")
        self.assertTrue(highlight.visible)
        line = next(c for c in code.children if c.components.get("part") == "line:0")
        self.assertAlmostEqual(highlight.x, line.x + 5 * pitch, delta=0.01)
        self.assertAlmostEqual(highlight.w, (12 - 5) * pitch, delta=0.01)

        # Caret reveal and alignment on line 1
        code.buffer.cursor = code.buffer.anchor = len(code.buffer.text)
        code.components.touch("buffer")
        self.runtime.step(0)
        caret = next(c for c in code.children if c.components.get("part") == "cursor")
        row, col = code.buffer.position
        self.assertAlmostEqual(caret.x, code.x + 48 + (col - code.buffer.horizontal) * pitch, delta=0.01)
        self.assertAlmostEqual(caret.y, code.y + 6 + (row - code.buffer.scroll) * line_height, delta=0.01)

    def test_source_editor_crlf_pasting_and_cursor_alignment(self):
        code = self.editor.code
        pitch = code.components.get("pitch", 8.0)
        line_height = code.components.get("line_height", 20)
        self.click(code)
        # Select all and paste text containing CRLF
        self.window.set_clipboard_text("hello world\r\nnext line\r\n")
        self.send(("key", "A", True, False), ("key", "V", True, False))
        self.assertEqual(code.buffer.text, "hello world\nnext line\n")

        # Move to line 0 end (END key)
        code.buffer.cursor = code.buffer.anchor = 0
        code.components.touch("buffer")
        self.runtime.step(0)
        self.send(("key", "END", False, False))
        self.assertEqual(code.buffer.position, (0, 11))
        caret = next(c for c in code.children if c.components.get("part") == "cursor")
        self.assertAlmostEqual(caret.x, code.x + 48 + 11 * pitch, delta=0.01)

        # Type character at line end; typed character appears directly at previous cursor position
        self.send(("text", "!"))
        self.assertEqual(code.buffer.position, (0, 12))
        self.assertEqual(code.buffer.text, "hello world!\nnext line\n")
        self.assertAlmostEqual(caret.x, code.x + 48 + 12 * pitch, delta=0.01)

    def test_selection_visual_highlight_in_hierarchy_and_viewport(self):
        first, second = self.editor.game.children

        # Initially, first entity is selected
        self.select(first)
        self.runtime.step(0)

        # Check hierarchy row has clear visual highlight indicator
        row_first = next(r for r in self.editor.hierarchy_rows if r.visible and r.relations.get("target") is first)
        row_second = next(r for r in self.editor.hierarchy_rows if r.visible and r.relations.get("target") is second)
        self.assertIn("> ", row_first.text)
        self.assertNotIn("> ", row_second.text)
        self.assertEqual(row_first.color, (45, 95, 125))
        self.assertNotEqual(row_second.color, (45, 95, 125))

        # Check viewport draws highlight around first entity
        keys = [kwargs.get("key") for _, kwargs in self.graphics.rectangles]
        self.assertIn((first.id, "sel_bot"), keys)
        self.assertIn((first.id, "sel_top"), keys)
        self.assertNotIn((second.id, "sel_bot"), keys)

        # Switch selection to second entity
        self.select(second)
        self.graphics.rectangles.clear()
        self.runtime.step(0)

        self.assertNotIn("> ", row_first.text)
        self.assertIn("> ", row_second.text)
        self.assertNotEqual(row_first.color, (45, 95, 125))
        self.assertEqual(row_second.color, (45, 95, 125))

        keys = [kwargs.get("key") for _, kwargs in self.graphics.rectangles]
        self.assertNotIn((first.id, "sel_bot"), keys)
        self.assertIn((second.id, "sel_bot"), keys)

        # Select an entity without drawable spatial bounds (e.g. Game)
        self.select(self.editor.game)
        self.graphics.rectangles.clear()
        self.runtime.step(0)

        row_game = next(r for r in self.editor.hierarchy_rows if r.visible and r.relations.get("target") is self.editor.game)
        self.assertIn("> ", row_game.text)
        self.assertEqual(row_game.color, (45, 95, 125))
        # No selection borders drawn in viewport for Game
        keys = [kwargs.get("key") for _, kwargs in self.graphics.rectangles]
        self.assertFalse(any(isinstance(k, tuple) and len(k) == 2 and str(k[1]).startswith("sel_") for k in keys))

    def test_viewport_camera_mouse_navigation(self):
        vp = self.editor.viewport
        cam = self.editor.camera
        initial_cam_x, initial_cam_y = cam.x, cam.y
        initial_zoom = cam.zoom

        # Drag inside viewport with dx=48, dy=-24
        self.send(("drag", vp.x + 100, vp.y + 100, 1, 0, 48, -24))
        self.assertAlmostEqual(cam.x, initial_cam_x - 48 / initial_zoom, delta=0.01)
        self.assertAlmostEqual(cam.y, initial_cam_y - 24 / initial_zoom, delta=0.01)

        # Drag using incremental positions (without explicit dx/dy in event)
        self.editor.viewport.drag_pos = None
        cam_x_before = cam.x
        cam_y_before = cam.y
        self.send(("drag", vp.x + 200, vp.y + 200, 1, 0))
        self.send(("drag", vp.x + 248, vp.y + 224, 1, 0))
        self.assertAlmostEqual(cam.x, cam_x_before - 48 / initial_zoom, delta=0.01)
        self.assertAlmostEqual(cam.y, cam_y_before + 24 / initial_zoom, delta=0.01)

        # Scroll inside viewport zooms camera towards cursor
        cam_before_zoom = (cam.x, cam.y, cam.zoom)
        from lbe.space import screen_to_world
        cursor_world = screen_to_world(cam, vp, vp.x + 100, vp.y + 100)
        self.send(("scroll", vp.x + 100, vp.y + 100, 0, 1))
        self.assertGreater(cam.zoom, cam_before_zoom[2])
        cursor_world_after = screen_to_world(cam, vp, vp.x + 100, vp.y + 100)
        self.assertAlmostEqual(cursor_world[0], cursor_world_after[0], delta=0.01)
        self.assertAlmostEqual(cursor_world[1], cursor_world_after[1], delta=0.01)

        # Dragging outside viewport (e.g. in code editor) does not move camera
        cam_state = (cam.x, cam.y, cam.zoom)
        code = self.editor.code
        self.click(code)
        self.send(("drag", code.x + 60, code.y + 20, 1, 0, 50, 50))
        self.assertEqual((cam.x, cam.y, cam.zoom), cam_state)

    def test_editor_panel_layout_and_window_reflow(self):
        ed = self.editor
        self.assertEqual((ed.header.x, ed.header.y, ed.header.w, ed.header.h), (0, 0, 1440, 44))
        self.assertEqual(ed.hierarchy.x, 8)
        self.assertEqual(ed.hierarchy.w, 354)
        self.assertEqual(ed.inspector.x, 8)
        self.assertEqual(ed.inspector.w, 354)
        self.assertEqual(ed.status.y, 875)

        # Window resized to 1600x1000
        self.window.width, self.window.height = 1600, 1000
        self.runtime.step(0)

        # Check reflow
        self.assertEqual((ed.header.x, ed.header.y, ed.header.w, ed.header.h), (0, 0, 1600, 44))
        self.assertEqual((ed.status.x, ed.status.y, ed.status.w, ed.status.h), (16, 975, 1568, 20))
        self.assertEqual(ed.viewport.w, 1600 - 370 - 24)
        self.assertEqual(ed.code_panel.w, 1600 - 370 - 24)

        # Hit test in reflowed header button
        self.assertEqual(ed.panel_button.x, 1600 - 190)
        self.click(ed.panel_button)
        self.assertEqual(len(ed.extra_panels), 1)

    def test_editor_resizable_and_movable_panels(self):
        ed = self.editor

        # 1. Resize left column width from 370 to 420
        ed.app.components["left_column_w"] = 420
        self.runtime.step(0)
        self.assertEqual(ed.hierarchy.w, 404)
        self.assertEqual(ed.inspector.w, 404)
        self.assertEqual(ed.viewport.x, 428)
        self.assertEqual(ed.code_panel.x, 428)
        self.assertEqual(ed.viewport.w, 1440 - 420 - 24)

        # 2. Resize hierarchy panel height from 240 to 300
        ed.hierarchy.panel_h = 300
        self.runtime.step(0)
        self.assertEqual(ed.hierarchy.h, 300)
        self.assertEqual(ed.inspector.y, 52 + 300 + 4 + 4)

        # 3. Resize split position between viewport and code panel
        ed.code_panel.split_y = 500
        self.runtime.step(0)
        self.assertEqual(ed.code_panel.y, 500)
        self.assertEqual(ed.viewport.h, 500 - 44 - 48)

        # 4. Floating panel: dock="float" preserves custom moved coordinates
        ed.hierarchy.dock = "float"
        ed.hierarchy.x = 250
        ed.hierarchy.y = 150
        self.runtime.step(0)
        self.assertEqual((ed.hierarchy.x, ed.hierarchy.y), (250, 150))

        # 5. Inspection panels from open_panel are movable floating panels
        self.click(ed.panel_button)
        panel = ed.extra_panels[-1]
        self.assertEqual(panel.dock, "float")
        close_btn = next(c for c in panel.children if "button" in c.tags)
        line0 = next(c for c in panel.children if c.components.get("line_index") == 0)

        initial_close_x = close_btn.x
        initial_line_x = line0.x
        panel.x += 100
        panel.y += 50
        self.runtime.step(0)
        self.assertEqual(close_btn.x, initial_close_x + 100)
        self.assertEqual(line0.x, initial_line_x + 100)

        # 6. Verify input hit testing after layout changes
        self.click(close_btn)
        self.runtime.step(0)
        self.assertFalse(panel.alive)

    def test_inspectable_editor_control_systems_and_navigation(self):
        ed = self.editor

        # 1. Select CodeEditorPanel and discover its behavior
        self.select(ed.code_panel)
        self.runtime.step(0)
        self.assertIs(ed.app.relations["selection"], ed.code_panel)

        sys_buttons = [b for b in ed.system_rows if b.visible]
        self.assertTrue(any(b.components.get("text") == "code_editor" for b in sys_buttons))

        # Clicking system button opens its source in code editor
        code_sys_btn = next(b for b in sys_buttons if b.components.get("text") == "code_editor")
        self.click(code_sys_btn)
        self.assertEqual(ed.path_field.buffer.text, "code_editor.py")
        self.assertIn("Code editor panel and coding-specific specialization system", ed.code.buffer.text)

        # 2. Navigate to child control (TextArea) from CodeEditorPanel
        child_buttons = [b for b in ed.child_rows if b.visible]
        text_area_btn = next(b for b in child_buttons if b.components.get("text") == "TextArea")
        self.click(text_area_btn)
        self.runtime.step(0)

        # TextArea is now selected and hierarchy automatically expanded
        self.assertIs(ed.app.relations["selection"], ed.code)
        self.assertIn(ed.code_panel.id, ed.hierarchy.expanded)

        # 3. Inspect TextArea's reusable behavior and coding-specific behavior
        text_area_sys = [b.components.get("text") for b in ed.system_rows if b.visible]
        self.assertIn("text_area", text_area_sys)
        self.assertIn("code_editor", text_area_sys)

        # Open text_area system source
        ta_btn = next(b for b in ed.system_rows if b.visible and b.components.get("text") == "text_area")
        self.click(ta_btn)
        self.assertEqual(ed.path_field.buffer.text, "text_area.py")
        self.assertIn("Reusable multiline text area entity system", ed.code.buffer.text)

        # Open code_editor specialization system source
        ce_btn = next(b for b in ed.system_rows if b.visible and b.components.get("text") == "code_editor")
        self.click(ce_btn)
        self.assertEqual(ed.path_field.buffer.text, "code_editor.py")

        # 4. Verify same approach works for other controls (e.g. HierarchyPanel, InspectorPanel)
        self.select(ed.hierarchy)
        self.runtime.step(0)
        h_btn = next(b for b in ed.system_rows if b.visible and b.components.get("text") == "hierarchy")
        self.click(h_btn)
        self.assertEqual(ed.path_field.buffer.text, "hierarchy.py")

        self.select(ed.inspector)
        self.runtime.step(0)
        i_btn = next(b for b in ed.system_rows if b.visible and b.components.get("text") == "inspector")
        self.click(i_btn)
        self.assertEqual(ed.path_field.buffer.text, "inspector.py")

    def test_project_persistence_and_movement_scene_recovery(self):
        ed = self.editor
        moving, still = ed.game.children
        orig_game_id = ed.game.id
        orig_moving_id = moving.id
        orig_still_id = still.id
        orig_moving_pos = (moving.x, moving.y)
        orig_still_pos = (still.x, still.y)

        # 1. Edit components on moving entity
        self.select(moving)
        for name, value in (("vx", "2.0"), ("vy", "-1.0")):
            self.type(ed.add_name, name)
            self.type(ed.add_value, value)
            self.click(ed.add_button)
        self.assertEqual((moving.vx, moving.vy), (2, -1))

        # 2. Add relation with reference to another entity
        moving.relations["partner"] = still

        # 3. Author physics system and attach to Game
        self.click(ed.new_button)
        self.type(ed.path_field, "physics.py")
        self.type(ed.code, 'def update(dt):\n    for child in query("x", "y", "vx", "vy"):\n        child.x += child.vx * dt\n        child.y += child.vy * dt\n')
        self.click(ed.save_button)
        self.select(ed.game)
        self.click(ed.attach_button)
        self.assertIn("physics", ed.game.systems)

        # 4. Modify panel layout
        ed.app.left_column_w = 420
        ed.hierarchy.panel_h = 280
        ed.code_panel.split_y = 390
        ed.camera.x = 5.0
        ed.camera.y = 10.0
        ed.camera.zoom = 64.0

        # 5. Save project state
        self.click(ed.save_project_button)
        project_json = Path(self.directory.name) / "project.json"
        self.assertTrue(project_json.exists())

        # 6. Close runtime
        self.runtime.close()

        # 7. Reopen project
        runtime2 = load_project(self.window, self.graphics, self.input, self.directory.name, template=template_path("editor"))
        self.addCleanup(runtime2.close)
        ed2 = runtime2.entities[0].components["application_state"]
        runtime2.step(0)

        # 8. Verify recovered entities and UUID identity
        game2 = ed2.game
        self.assertEqual(game2.id, orig_game_id)
        self.assertEqual(len(game2.children), 2)
        moving2, still2 = game2.children
        self.assertEqual(moving2.id, orig_moving_id)
        self.assertEqual(still2.id, orig_still_id)
        self.assertEqual((moving2.vx, moving2.vy), (2, -1))

        # 9. Verify reference integrity
        self.assertIn("partner", moving2.relations)
        self.assertIs(moving2.relations["partner"], still2)

        # 10. Verify system attachment is reconstructed and running
        self.assertIn("physics", game2.systems)
        self.assertTrue(game2.systems["physics"].running)

        # 11. Verify movement execution
        runtime2.step(0.5)
        self.assertEqual((moving2.x, moving2.y), (orig_moving_pos[0] + 1.0, orig_moving_pos[1] - 0.5))
        self.assertEqual((still2.x, still2.y), orig_still_pos)

        # 12. Verify panel layout recovery
        self.assertEqual(ed2.app.left_column_w, 420)
        self.assertEqual(ed2.hierarchy.panel_h, 280)
        self.assertEqual(ed2.code_panel.split_y, 390)
        self.assertEqual((ed2.camera.x, ed2.camera.y, ed2.camera.zoom), (5.0, 10.0, 64.0))

    def test_syntax_highlighting_in_code_editor(self):
        code = self.editor.code
        self.click(code)
        # Type Python code
        self.send(("key", "A", True, False), ("text", "def update(dt):\n    entity.x = 42\n    name = \"LBE\""))
        self.runtime.step(0)

        # Check line_spans on code
        spans = code.components.get("line_spans")
        self.assertIsNotNone(spans)
        self.assertEqual(len(spans), 3)

        # Verify line 0 spans (def in keyword color, update in definition color)
        line0 = next(c for c in code.children if c.components.get("part") == "line:0")
        line0_spans = line0.components.get("spans")
        self.assertIsNotNone(line0_spans)
        self.assertTrue(any(chunk == "def" and color == (255, 123, 114) for chunk, color in line0_spans))
        self.assertTrue(any(chunk == "update" and color == (220, 180, 255) for chunk, color in line0_spans))

        # Verify line 1 spans (number 42 in warm orange color)
        line1 = next(c for c in code.children if c.components.get("part") == "line:1")
        line1_spans = line1.components.get("spans")
        self.assertTrue(any(chunk == "42" and color == (255, 166, 87) for chunk, color in line1_spans))

        # Verify line 2 spans (string "LBE" in soft blue color)
        line2 = next(c for c in code.children if c.components.get("part") == "line:2")
        line2_spans = line2.components.get("spans")
        self.assertTrue(any(chunk == '"LBE"' and color == (165, 214, 255) for chunk, color in line2_spans))

    def test_inline_syntax_and_compile_error_diagnostics(self):
        code = self.editor.code
        info = self.editor.code_info
        self.click(code)
        # Type invalid syntax (unclosed parenthesis)
        self.send(("key", "A", True, False), ("text", "def update(dt:\n    pass\n"))
        self.runtime.step(0)

        # Diagnostic component on code
        diag = code.components.get("diagnostic")
        self.assertIsNotNone(diag)
        self.assertEqual(diag["type"], "syntax")
        self.assertEqual(diag["line"], 1)

        # Gutter number:0 ink is red (ERROR)
        num0 = next(c for c in code.children if c.components.get("part") == "number:0")
        self.assertEqual(num0.ink, (248, 81, 73, 255))

        # Error underline rect is visible
        err0 = next(c for c in code.children if c.components.get("part") == "error:0")
        self.assertTrue(err0.visible)

        # Status info displays error message in red
        self.assertIn("SyntaxError", info.text)
        self.assertEqual(info.ink, (248, 81, 73, 255))

        # Fix syntax error
        self.send(("key", "A", True, False), ("text", "def update(dt):\n    pass\n"))
        self.runtime.step(0)
        self.assertIsNone(code.components.get("diagnostic"))
        self.assertFalse(err0.visible)
        self.assertNotIn("SyntaxError", info.text)

    def test_bracket_matching_and_auto_closing(self):
        code = self.editor.code
        self.click(code)
        # Clear buffer
        self.send(("key", "A", True, False), ("key", "BACKSPACE", False, False))

        # 1. Auto-close opening parenthesis
        self.send(("text", "("))
        self.assertEqual(code.buffer.text, "()")
        self.assertEqual(code.buffer.cursor, 1)

        # 2. Type-over closing parenthesis
        self.send(("text", ")"))
        self.assertEqual(code.buffer.text, "()")
        self.assertEqual(code.buffer.cursor, 2)

        # 3. Backspace deleting empty pair
        code.buffer.cursor = code.buffer.anchor = 1
        self.send(("key", "BACKSPACE", False, False))
        self.assertEqual(code.buffer.text, "")

        # 4. Selection wrapping
        self.send(("text", "target"))
        self.assertEqual(code.buffer.text, "target")
        self.send(("key", "A", True, False)) # select all
        self.send(("text", "["))
        self.assertEqual(code.buffer.text, "[target]")

        # 5. Matching bracket visual highlight
        code.buffer.cursor = code.buffer.anchor = 1 # inside [target], adjacent to [
        self.runtime.step(0)
        matching = code.components.get("matching_brackets")
        self.assertIsNotNone(matching)
        self.assertEqual(matching, ((0, 0), (0, 7)))
        b0 = next(c for c in code.children if c.components.get("part") == "bracket:0")
        b1 = next(c for c in code.children if c.components.get("part") == "bracket:1")
        self.assertTrue(b0.visible)
        self.assertTrue(b1.visible)

    def test_autocomplete_and_code_completion(self):
        code = self.editor.code
        self.click(code)
        self.send(("key", "A", True, False), ("key", "BACKSPACE", False, False))

        # Type 'entity.c' to trigger autocomplete
        self.send(("text", "entity.c"))
        self.runtime.step(0)

        ac_state = code.components.get("autocomplete_state")
        self.assertIsNotNone(ac_state)
        self.assertTrue(ac_state.get("active"))
        match_names = [m[0] for m in ac_state.get("matches", [])]
        self.assertIn("color", match_names)
        self.assertIn("components", match_names)

        # Popup panel entity is visible
        popup = next(c for c in code.children if c.components.get("part") == "autocomplete_popup")
        self.assertTrue(popup.visible)

        # Press DOWN to select next suggestion and TAB to complete
        orig_selected = ac_state.get("selected", 0)
        self.send(("key", "DOWN", False, False))
        self.assertEqual(ac_state.get("selected"), (orig_selected + 1) % len(match_names))
        expected_chosen = ac_state["matches"][ac_state["selected"]][0]

        self.send(("key", "TAB", False, False))
        self.runtime.step(0)
        self.assertEqual(code.buffer.text, f"entity.{expected_chosen}")
        self.assertFalse(ac_state.get("active"))
        self.assertFalse(popup.visible)

        # Mouse click on autocomplete item
        self.send(("key", "A", True, False), ("key", "BACKSPACE", False, False))
        self.send(("text", "entity.t"))
        self.runtime.step(0)
        self.assertTrue(ac_state.get("active"))
        item0 = next(c for c in code.children if c.components.get("part") == "ac_item:0")
        self.assertTrue(item0.visible)
        self.click(item0)
        self.runtime.step(0)
        self.assertIn("entity.tags", code.buffer.text)
        self.assertFalse(ac_state.get("active"))

    def test_f5_toggles_game_run_pause_and_period_does_not_run_game(self):
        # 1. Verify initial running state and attach a movement system
        moving, still = self.editor.game.children
        moving.vx, moving.vy = 2.0, 0.0
        self.click(self.editor.new_button)
        self.type(self.editor.path_field, "mover.py")
        self.type(self.editor.code, 'def update(dt):\n    for child in query("x", "y", "vx", "vy"):\n        child.x += child.vx * dt\n')
        self.click(self.editor.save_button)
        self.select(self.editor.game)
        self.click(self.editor.attach_button)

        # Initial state: running, moving entity advances
        pos_before = moving.x
        self.runtime.step(0.5)
        self.assertEqual(moving.x, pos_before + 1.0)
        self.assertFalse(self.editor.game.components.get("paused", False))
        self.assertEqual(self.editor.run_button.text, "Pause (F5)")

        # 2. Press F5: pauses the game
        self.send(("key", "F5", False, False))
        self.runtime.step(0)
        self.assertTrue(self.editor.game.components.get("paused"))
        self.assertEqual(self.editor.run_button.text, "Run (F5)")
        self.assertIn("Game paused", self.editor.app.status)

        # Stepping when paused does NOT advance game entities
        pos_paused = moving.x
        self.runtime.step(0.5)
        self.assertEqual(moving.x, pos_paused)

        # 3. Type '.' in the code editor: must insert '.' and MUST NOT unpause/run the game
        self.click(self.editor.code)
        text_before = self.editor.code.buffer.text
        self.send(("key", "PERIOD", False, False), ("text", "."))
        self.runtime.step(0)
        # Still paused!
        self.assertTrue(self.editor.game.components.get("paused"))
        self.assertEqual(self.editor.code.buffer.text, text_before + ".")
        # Position did not advance
        self.runtime.step(0.5)
        self.assertEqual(moving.x, pos_paused)

        # 4. Press F5 again while focused in the editor: resumes/runs the game
        self.send(("key", "F5", False, False))
        self.runtime.step(0)
        self.assertFalse(self.editor.game.components.get("paused"))
        self.assertEqual(self.editor.run_button.text, "Pause (F5)")
        self.assertIn("Game running", self.editor.app.status)

        # Position now advances again
        self.runtime.step(0.5)
        self.assertEqual(moving.x, pos_paused + 1.0)

        # 5. Clicking the header Run/Pause button also toggles state
        self.click(self.editor.run_button)
        self.runtime.step(0)
        self.assertTrue(self.editor.game.components.get("paused"))
        self.assertEqual(self.editor.run_button.text, "Run (F5)")

    def test_typing_period_in_code_editor_retains_all_panels_and_ui_systems(self):
        code = self.editor.code
        self.click(code)
        self.send(("key", "A", True, False), ("key", "BACKSPACE", False, False))
        self.send(("text", "entity."))
        self.runtime.step(0)

        # Autocomplete popup is active and rendered
        ac_state = code.components.get("autocomplete_state")
        self.assertIsNotNone(ac_state)
        self.assertTrue(ac_state.get("active"))
        popup = next((c for c in code.children if c.components.get("part") == "autocomplete_popup"), None)
        self.assertIsNotNone(popup)
        self.assertTrue(popup.visible)

        # All editor panels and UI systems remain running and visible
        self.assertTrue(self.editor.app.systems["ui"].running)
        self.assertEqual(tuple(self.editor.app.systems["ui"].errors), ())
        self.assertNotIn("ui_error", self.editor.app.components)

        self.assertTrue(self.editor.hierarchy.visible)
        self.assertTrue(self.editor.inspector.visible)
        self.assertTrue(self.editor.code_panel.visible)
        self.assertTrue(self.editor.viewport.visible)
        self.assertTrue(self.editor.status.visible)
        self.assertTrue(self.editor.header.visible)

        # Press ESCAPE to dismiss autocomplete popup
        self.send(("key", "ESCAPE", False, False))
        self.runtime.step(0)
        self.assertFalse(ac_state.get("active"))
        self.assertFalse(popup.visible)

        # UI system remains active and panels remain visible
        self.assertTrue(self.editor.app.systems["ui"].running)
        self.assertTrue(self.editor.hierarchy.visible)
        self.assertTrue(self.editor.inspector.visible)

    def test_interactive_panel_resizing_with_splitters(self):
        ed = self.editor
        self.assertIsNotNone(ed.col_splitter)
        self.assertIsNotNone(ed.hierarchy_splitter)
        self.assertIsNotNone(ed.code_splitter)
        self.assertTrue(ed.col_splitter.visible)
        self.assertTrue(ed.hierarchy_splitter.visible)
        self.assertTrue(ed.code_splitter.visible)

        # 1. Hover color feedback
        normal_color = ed.col_splitter.components.get("normal_color", (38, 50, 66))
        hover_color = ed.col_splitter.components.get("hover_color", (69, 182, 199))
        self.send(("motion", ed.col_splitter.x + 2, ed.col_splitter.y + 100))
        self.assertEqual(ed.col_splitter.color, hover_color)
        self.send(("motion", 10, 10))
        self.assertEqual(ed.col_splitter.color, normal_color)

        # 2. Drag column splitter horizontally
        orig_col_w = ed.app.components.get("left_column_w", 370)
        orig_hier_w = ed.hierarchy.w
        orig_vp_x = ed.viewport.x

        self.send(("drag", ed.col_splitter.x + 2, ed.col_splitter.y + 100, 1, 0, 50, 0))
        self.send(("release", ed.col_splitter.x + 2, ed.col_splitter.y + 100, 1, 0))
        self.assertEqual(ed.app.components.get("left_column_w"), orig_col_w + 50)
        self.assertEqual(ed.hierarchy.w, orig_hier_w + 50)
        self.assertEqual(ed.inspector.w, orig_hier_w + 50)
        self.assertEqual(ed.viewport.x, orig_vp_x + 50)
        self.assertEqual(ed.code_panel.x, orig_vp_x + 50)

        # 3. Drag hierarchy splitter vertically
        orig_hier_h = ed.hierarchy.components.get("panel_h", 240)
        orig_insp_y = ed.inspector.y
        orig_insp_h = ed.inspector.h

        self.send(("drag", ed.hierarchy_splitter.x + 20, ed.hierarchy_splitter.y + 2, 1, 0, 0, 40))
        self.send(("release", ed.hierarchy_splitter.x + 20, ed.hierarchy_splitter.y + 2, 1, 0))
        self.assertEqual(ed.hierarchy.components.get("panel_h"), orig_hier_h + 40)
        self.assertEqual(ed.hierarchy.h, orig_hier_h + 40)
        self.assertEqual(ed.inspector.y, orig_insp_y + 40)
        self.assertEqual(ed.inspector.h, orig_insp_h - 40)

        # 4. Drag code panel splitter vertically
        orig_split_y = ed.code_panel.components.get("split_y", ed.code_panel.y)
        orig_vp_h = ed.viewport.h
        orig_cp_h = ed.code_panel.h

        self.send(("drag", ed.code_splitter.x + 50, ed.code_splitter.y + 2, 1, 0, 0, -30))
        self.send(("release", ed.code_splitter.x + 50, ed.code_splitter.y + 2, 1, 0))
        self.assertEqual(ed.code_panel.components.get("split_y"), orig_split_y - 30)
        self.assertEqual(ed.viewport.h, orig_vp_h - 30)
        self.assertEqual(ed.code_panel.h, orig_cp_h + 30)

        # 5. Release clears active drag
        self.assertNotIn("active_drag", ed.app.relations)

        # 6. Save project and verify layout persistence across reopen
        self.click(ed.save_project_button)
        self.runtime.close()

        from lbe.project import load_project, template_path
        runtime2 = load_project(self.window, self.graphics, self.input, self.directory.name, template=template_path("editor"))
        self.addCleanup(runtime2.close)
        ed2 = runtime2.entities[0].components["application_state"]
        runtime2.step(0)

        self.assertEqual(ed2.app.left_column_w, orig_col_w + 50)
        self.assertEqual(ed2.hierarchy.panel_h, orig_hier_h + 40)
        self.assertEqual(ed2.code_panel.split_y, orig_split_y - 30)

    def test_inspector_clean_flow_and_bounded_child_navigation(self):
        ed = self.editor

        # Select TextArea entity which has ~95 children (parts for lines, errors, etc.)
        self.select(ed.code)
        self.runtime.step(0)

        self.assertIs(ed.app.relations["selection"], ed.code)
        children_count = len(ed.code.children)
        self.assertGreater(children_count, 20)

        # Verify child buttons count is strictly bounded (max 9 visible buttons)
        visible_children = [b for b in ed.child_rows if b.visible]
        self.assertLessEqual(len(visible_children), 9)
        self.assertGreater(len(visible_children), 0)

        # Verify all visible child buttons are positioned inside the inspector bounds
        ip = ed.inspector
        for btn in visible_children:
            self.assertGreaterEqual(btn.x, ip.x)
            self.assertLessEqual(btn.x + btn.w, ip.x + ip.w + 1)
            self.assertGreaterEqual(btn.y, ip.y)
            self.assertLessEqual(btn.y + btn.h, ip.y + ip.h + 2)

        # Verify metadata correctly reflects total children without layout overflow
        self.assertIn(f"{children_count} children", ed.metadata.components.get("text", ""))

        # Verify component rows do NOT overlap the bottom section
        visible_comp_rows = [(lbl, fld) for lbl, fld in ed.component_rows if fld.visible]
        if visible_comp_rows:
            max_comp_y = max(fld.y + fld.h for _, fld in visible_comp_rows)
            # Add component row must start strictly below the last visible component row
            self.assertLessEqual(max_comp_y, ed.add_name.y)

        # Verify bottom section controls do not overlap each other
        self.assertLessEqual(ed.add_name.y + ed.add_name.h, ed.tags_field.y)
        self.assertLessEqual(ed.tags_field.y + ed.tags_field.h, ed.parent_field.y)
        self.assertLessEqual(ed.parent_field.y + ed.parent_field.h, ed.relation_field.y)
        self.assertLessEqual(ed.relation_field.y + ed.relation_field.h, ed.metadata.y)

        # If systems exist, they start below metadata
        visible_sys = [b for b in ed.system_rows if b.visible]
        if visible_sys:
            self.assertLessEqual(ed.metadata.y + ed.metadata.h, ed.system_label.y)
            for btn in visible_sys:
                self.assertGreaterEqual(btn.y, ed.system_label.y)
                self.assertLessEqual(btn.y + btn.h, ip.y + ip.h + 2)




