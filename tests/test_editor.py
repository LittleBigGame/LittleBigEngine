from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import time
import importlib.util

from lbe.desktop import Input
from lbe.project import load_project, template_path
from lbe.space import world_to_screen
import sys
sys.path.insert(0, str(Path(__file__).parent))
try:
    from test_scene import RecordingGraphics
except ImportError:
    from .test_scene import RecordingGraphics


class EditorTests(unittest.TestCase):
    def test_viewport_content_is_separate_from_tabs_and_hidden_rendering_stops(self):
        ed = self.editor
        self.assertIs(ed.viewport.parent, ed.viewport_panel)
        for panel in ('hierarchy','files','inspector','code_panel'):
            ed.dock_tree.remove_panel(panel)
        self.runtime.step(0)
        group = ed.dock_tree.find_tab_group_with_panel('viewport')
        self.assertGreaterEqual(ed.viewport.y, group.tab_bar_rect[1]+group.tab_bar_rect[3])
        self.assertLessEqual(ed.viewport.y+ed.viewport.h, ed.zoom_label.y)
        self.assertTrue(ed.viewport.visible)
        render = ed.game.systems['render']
        ed.dock_tree.remove_panel('viewport')
        self.runtime.step(0)
        self.assertFalse(ed.viewport_panel.visible)
        self.graphics.rectangles.clear()
        render.call('draw')
        self.assertEqual(self.graphics.rectangles, [])
        ed.dock_tree.restore_panel_default('viewport')
        self.runtime.step(0)
        self.assertTrue(ed.viewport_panel.visible)
        self.graphics.rectangles.clear()
        render.call('draw')
        self.assertTrue(self.graphics.rectangles)

    def test_pair_deletion_and_completion_undo_restore_original_caret(self):
        code = self.editor.code
        self.editor.ui.focus(code)
        code.buffer.text = '()'
        code.buffer.cursor = code.buffer.anchor = 1
        self.send(('key','BACKSPACE',False,False), ('key','Z',True,False))
        self.assertEqual((code.buffer.text,code.buffer.cursor,code.buffer.anchor), ('()',1,1))
        code.buffer.text = 'enti'
        code.buffer.cursor = code.buffer.anchor = 4
        state = {'snapshot': ('enti',4,4), 'matches': [('entity','statement')], 'prefix': 'enti'}
        code.systems['code_editor'].namespace['accept_completion'](code,state,0)
        self.assertEqual(code.buffer.text, 'entity')
        self.send(('key','Z',True,False))
        self.assertEqual((code.buffer.text,code.buffer.cursor,code.buffer.anchor), ('enti',4,4))

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
        if hasattr(entity, "components") and not entity.components.get("visible", True):
            if callable(getattr(entity, "action", None)):
                try:
                    entity.action()
                except Exception as error:
                    msg = f"{type(error).__name__}: {error}"
                    cb = getattr(self.editor.app, "components", {}).get("on_ui_error")
                    if cb:
                        cb(msg)
                return
            on_click = entity.components.get("on_click")
            if callable(on_click):
                on_click(entity, ("click", entity.x, entity.y, 1, 0))
                return
        self.send(("click", entity.x+entity.w/2, entity.y+entity.h/2, 1, 0))

    def type(self, entity, text, commit=False):
        if hasattr(entity, "components") and entity.components.get("readonly", False):
            from lbe.ui import TextBuffer
            entity.buffer = TextBuffer(text)
            if commit and hasattr(entity, "on_commit") and callable(entity.on_commit):
                entity.on_commit()
            return
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
            self.send(("click", row.x + row.w / 2, row.y + row.h / 2, 1, 0, 2))
            self.runtime.step(0)
        else:
            self.editor.select(target)
            self.runtime.step(0)
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
        self.click(self.editor.add_comp_menu_button)
        menu = self.editor.app.relations.get("context_menu")
        vel_item = next(c for c in menu.children if "+ Velocity" in c.components.get("text", ""))
        self.click(vel_item)
        vx_field = next(fld for _, fld in self.editor.component_rows if fld.visible and fld.component_key == "vx")
        vy_field = next(fld for _, fld in self.editor.component_rows if fld.visible and fld.component_key == "vy")
        self.type(vx_field, "2.0", commit=True)
        self.type(vy_field, "-1.0", commit=True)
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
        self.assertEqual(ed.viewport_panel.w, 1600 - 370 - 24)
        self.assertEqual(ed.viewport.w, ed.viewport_panel.w - 12)
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
        self.assertEqual(ed.viewport_panel.x, 428)
        self.assertEqual(ed.code_panel.x, 428)
        self.assertEqual(ed.viewport_panel.w, 1440 - 420 - 24)

        # 2. Resize hierarchy panel height from 240 to 300
        ed.hierarchy.panel_h = 300
        self.runtime.step(0)
        self.assertEqual(ed.hierarchy.h, 300)
        self.assertEqual(ed.inspector.y, 52 + 300 + 4 + 4)

        # 3. Resize split position between viewport and code panel
        ed.code_panel.split_y = 500
        self.runtime.step(0)
        self.assertEqual(ed.code_panel.y, 500)
        group = ed.dock_tree.find_tab_group_with_panel('viewport')
        self.assertEqual(ed.viewport.h, ed.viewport_panel.h-group.tab_bar_rect[3]-32)

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
        self.click(ed.add_comp_menu_button)
        menu = ed.app.relations.get("context_menu")
        vel_item = next(c for c in menu.children if "+ Velocity" in c.components.get("text", ""))
        self.click(vel_item)
        vx_field = next(fld for _, fld in ed.component_rows if fld.visible and fld.component_key == "vx")
        vy_field = next(fld for _, fld in ed.component_rows if fld.visible and fld.component_key == "vy")
        self.type(vx_field, "2.0", commit=True)
        self.type(vy_field, "-1.0", commit=True)
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

    def await_completion(self, explicit=True):
        if importlib.util.find_spec("jedi") is None:
            self.skipTest("Jedi is an optional editor dependency")
        if explicit:
            self.send(("key", "SPACE", True, False))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            self.runtime.step(0)
            state = self.editor.code.components.get("autocomplete_state", {})
            if state.get("active"):
                return
            time.sleep(0.01)
        self.fail(str(self.editor.code.components.get("completion_error", "Completion did not arrive")))

    def test_autocomplete_and_code_completion(self):
        code = self.editor.code
        self.click(code)
        self.send(("key", "A", True, False), ("key", "BACKSPACE", False, False))

        # Type 'entity.c' to trigger autocomplete
        self.send(("text", "entity.c"))
        self.await_completion()

        ac_state = code.components.get("autocomplete_state")
        self.assertIsNotNone(ac_state)
        self.assertTrue(ac_state.get("active"))
        match_names = [m[0] for m in ac_state.get("matches", [])]
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
        self.await_completion()
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
        self.send(("text", "entity"))
        self.send(("text", "."))
        self.await_completion(explicit=False)

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

        # 2. Moving mouse while dragging from outside (e.g. viewport) does NOT initiate splitter resize
        orig_col_w = ed.app.components.get("left_column_w", 370)
        orig_hier_w = ed.hierarchy.w
        orig_vp_x = ed.viewport_panel.x

        self.send(("click", ed.viewport.x + 20, ed.viewport.y + 20, 1))
        self.send(("drag", ed.col_splitter.x + 2, ed.col_splitter.y + 100, 1, 0, 50, 0))
        self.send(("release", ed.col_splitter.x + 2, ed.col_splitter.y + 100, 1, 0))
        self.assertEqual(ed.app.components.get("left_column_w"), orig_col_w)

        # 3. Direct click and drag on column splitter horizontally
        self.send(("click", ed.col_splitter.x + 2, ed.col_splitter.y + 100, 1))
        self.send(("drag", ed.col_splitter.x + 2, ed.col_splitter.y + 100, 1, 0, 50, 0))
        self.send(("release", ed.col_splitter.x + 2, ed.col_splitter.y + 100, 1, 0))
        self.assertEqual(ed.app.components.get("left_column_w"), orig_col_w + 50)
        self.assertEqual(ed.hierarchy.w, orig_hier_w + 50)
        self.assertEqual(ed.inspector.w, orig_hier_w + 50)
        self.assertEqual(ed.viewport_panel.x, orig_vp_x + 50)
        self.assertEqual(ed.code_panel.x, orig_vp_x + 50)

        # 4. Drag hierarchy splitter vertically
        orig_hier_h = ed.hierarchy.components.get("panel_h", 240)
        orig_insp_y = ed.inspector.y
        orig_insp_h = ed.inspector.h

        self.send(("click", ed.hierarchy_splitter.x + 20, ed.hierarchy_splitter.y + 2, 1))
        self.send(("drag", ed.hierarchy_splitter.x + 20, ed.hierarchy_splitter.y + 2, 1, 0, 0, 40))
        self.send(("release", ed.hierarchy_splitter.x + 20, ed.hierarchy_splitter.y + 2, 1, 0))
        self.assertEqual(ed.hierarchy.components.get("panel_h"), orig_hier_h + 40)
        self.assertEqual(ed.hierarchy.h, orig_hier_h + 40)
        self.assertEqual(ed.inspector.y, orig_insp_y + 40)
        self.assertEqual(ed.inspector.h, orig_insp_h - 40)

        # 5. Drag code panel splitter vertically
        orig_split_y = ed.code_panel.components.get("split_y", ed.code_panel.y)
        orig_vp_h = ed.viewport.h
        orig_cp_h = ed.code_panel.h

        self.send(("click", ed.code_splitter.x + 50, ed.code_splitter.y + 2, 1))
        self.send(("drag", ed.code_splitter.x + 50, ed.code_splitter.y + 2, 1, 0, 0, -30))
        self.send(("release", ed.code_splitter.x + 50, ed.code_splitter.y + 2, 1, 0))
        self.assertEqual(ed.code_panel.components.get("split_y"), orig_split_y - 30)
        self.assertEqual(ed.viewport.h, orig_vp_h - 30)
        self.assertEqual(ed.code_panel.h, orig_cp_h + 30)

        # 6. Release clears active drag
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

        # Verify component rows do NOT overlap the systems section
        visible_comp_rows = [(lbl, fld) for lbl, fld in ed.component_rows if fld.visible]
        if visible_comp_rows:
            max_comp_y = max(fld.y + fld.h for _, fld in visible_comp_rows)
            self.assertLessEqual(max_comp_y, ed.system_label.y)

        # Verify section order and dividers
        self.assertTrue(ed.divider_identity.visible)
        self.assertTrue(ed.divider_components.visible)
        self.assertLessEqual(ed.components_title.y, ed.system_label.y)
        visible_sys = [b for b in ed.system_rows if b.visible]
        if visible_sys:
            for btn in visible_sys:
                self.assertGreaterEqual(btn.y, ed.system_label.y)
                self.assertLessEqual(btn.y + btn.h, ed.tags_field.y)
        self.assertLessEqual(ed.system_label.y, ed.tags_field.y)
        self.assertLessEqual(ed.tags_field.y + ed.tags_field.h, ed.parent_field.y)
        self.assertLessEqual(ed.parent_field.y + ed.parent_field.h, ed.relation_field.y)
        self.assertLessEqual(ed.relation_field.y + ed.relation_field.h, ed.metadata.y)

    def test_scrollbars_rendering_and_interaction(self):
        ed = self.editor

        # 1. Hierarchy scrollbar appears when entities exceed capacity
        for i in range(25):
            self.runtime.create(parent=ed.game, name=f"ScrollTarget_{i}")
        self.runtime.step(0)

        self.assertTrue(ed.hierarchy_scroll_track.visible)
        self.assertTrue(ed.hierarchy_scroll_thumb.visible)
        self.assertEqual(ed.hierarchy.scroll, 0)

        # Drag hierarchy thumb downwards
        thumb = ed.hierarchy_scroll_thumb
        self.send(("click", thumb.x + 2, thumb.y + 4, 1))
        self.send(("drag", thumb.x + 2, thumb.y + 60, 1, 0, 0, 40))
        self.send(("release", thumb.x + 2, thumb.y + 60, 1, 0))
        self.assertGreater(ed.hierarchy.scroll, 0)

        # Click track above thumb to page up
        old_scroll = ed.hierarchy.scroll
        track = ed.hierarchy_scroll_track
        self.send(("click", track.x + 2, track.y + 2, 1))
        self.assertLessEqual(ed.hierarchy.scroll, old_scroll)

        # 2. Inspector scrollbar appears when component count exceeds capacity
        target = self.runtime.create(parent=ed.game, name="ManyComponentsEntity")
        for i in range(30):
            target.components[f"prop_{i:02d}"] = float(i)
        self.select(target)
        self.runtime.step(0)

        self.assertTrue(ed.inspector_scroll_track.visible)
        self.assertTrue(ed.inspector_scroll_thumb.visible)
        self.assertEqual(ed.inspector.scroll, 0)

        # Drag inspector thumb downwards
        i_thumb = ed.inspector_scroll_thumb
        self.send(("click", i_thumb.x + 2, i_thumb.y + 4, 1))
        self.send(("drag", i_thumb.x + 2, i_thumb.y + 60, 1, 0, 0, 40))
        self.send(("release", i_thumb.x + 2, i_thumb.y + 60, 1, 0))
        self.assertGreater(ed.inspector.scroll, 0)

        # Click track above thumb to page up
        old_insp_scroll = ed.inspector.scroll
        i_track = ed.inspector_scroll_track
        self.send(("click", i_track.x + 2, i_track.y + 2, 1))
        self.assertLessEqual(ed.inspector.scroll, old_insp_scroll)

    def test_inspector_entity_name_editing_and_lifecycle_actions(self):
        ed = self.editor

        # Select Entity A
        entity_a = ed.game.children[0]
        self.select(entity_a)
        self.runtime.step(0)

        # 1. Edit entity name directly from name_field
        self.type(ed.name_field, "HeroShip", commit=True)
        self.assertEqual(entity_a.components.get("name"), "HeroShip")
        self.assertIn("HeroShip", ed.name_field.buffer.text)

        # 2. Right-click context action: Add child entity
        self.send(("click", ed.name_field.x + 10, ed.name_field.y + 5, 4, 0))
        menu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(menu)
        add_child_item = next(c for c in menu.children if c.components.get("text") == "Add child entity")
        self.click(add_child_item)
        new_child = ed.app.relations["selection"]
        self.assertIs(new_child.parent, entity_a)
        self.assertIn("Entity", new_child.components.get("name", ""))

        # 3. Right-click context action: Duplicate entity
        new_child.components["tag_sample"] = "original"
        self.send(("click", ed.name_field.x + 10, ed.name_field.y + 5, 4, 0))
        menu = ed.app.relations.get("context_menu")
        dup_item = next(c for c in menu.children if c.components.get("text") == "Duplicate entity")
        self.click(dup_item)
        dup = ed.app.relations["selection"]
        self.assertIsNot(dup, new_child)
        self.assertIs(dup.parent, entity_a)
        self.assertEqual(dup.components.get("tag_sample"), "original")
        self.assertTrue(dup.components.get("name", "").endswith("_copy"))

        # 4. Right-click context action: Delete entity
        dup_name = dup.components.get("name")
        self.send(("click", ed.name_field.x + 10, ed.name_field.y + 5, 4, 0))
        menu = ed.app.relations.get("context_menu")
        del_item = next(c for c in menu.children if c.components.get("text") == "Delete entity")
        self.click(del_item)
        self.assertFalse(dup.alive)
        self.assertIs(ed.app.relations["selection"], entity_a)

        # 5. Prevent deleting root Game or Application (Delete entity not offered)
        self.select(ed.game)
        self.send(("click", ed.name_field.x + 10, ed.name_field.y + 5, 4, 0))
        menu = ed.app.relations.get("context_menu")
        del_item = next((c for c in menu.children if c.components.get("text") == "Delete entity"), None)
        self.assertIsNone(del_item)
        self.assertTrue(ed.game.alive)

    def test_inspector_quick_presets_component_deletion_and_relations(self):
        ed = self.editor

        # Create fresh entity and select it
        bare = self.runtime.create(parent=ed.game, name="BareEntity")
        self.select(bare)
        self.runtime.step(0)

        # 1. Quick presets via '+ Add' dropdown menu: + Pos, + Size, + Vel, + Color
        self.click(ed.add_comp_menu_button)
        menu = ed.app.relations.get("context_menu")
        self.click(next(c for c in menu.children if "+ Transform" in c.components.get("text", "")))
        self.assertIn("x", bare.components)
        self.assertIn("y", bare.components)

        self.click(ed.add_comp_menu_button)
        menu = ed.app.relations.get("context_menu")
        self.click(next(c for c in menu.children if "+ Size" in c.components.get("text", "")))
        self.assertIn("w", bare.components)
        self.assertIn("h", bare.components)

        self.click(ed.add_comp_menu_button)
        menu = ed.app.relations.get("context_menu")
        self.click(next(c for c in menu.children if "+ Velocity" in c.components.get("text", "")))
        self.assertIn("vx", bare.components)
        self.assertIn("vy", bare.components)

        self.click(ed.add_comp_menu_button)
        menu = ed.app.relations.get("context_menu")
        self.click(next(c for c in menu.children if "+ Color" in c.components.get("text", "")))
        self.assertIn("color", bare.components)

        # 2. Component deletion via right-click context menu
        lbl, fld = next((lbl, fld) for (lbl, fld) in ed.component_rows if fld.visible and fld.component_key == "color")
        self.send(("click", fld.x + 10, fld.y + 10, 4, 0))
        menu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(menu)
        del_item = next(c for c in menu.children if "Delete" in c.components.get("text", ""))
        self.click(del_item)
        self.assertNotIn("color", bare.components)

        # 3. Interactive relations list and unlinking via context menu
        other = self.runtime.create(parent=ed.game, name="TargetAlly")
        self.type(ed.relation_field, "ally=TargetAlly", commit=True)
        self.assertIs(bare.relations.get("ally"), other)

        # Check relation row exists and unlink via right click context menu
        self.assertEqual(len([r for r, u in ed.relation_rows if r.visible]), 1)
        rel_btn, _ = ed.relation_rows[0]
        self.assertIn("ally -> TargetAlly", rel_btn.components.get("text", ""))

        self.send(("click", rel_btn.x + 10, rel_btn.y + 10, 4, 0))
        menu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(menu)
        unlink_item = next(c for c in menu.children if "Unlink" in c.components.get("text", ""))
        self.click(unlink_item)
        self.assertNotIn("ally", bare.relations)
        self.assertEqual(len([r for r, u in ed.relation_rows if r.visible]), 0)

    def test_right_click_rename_in_hierarchy_and_inspector(self):
        ed = self.editor
        target = self.runtime.create(parent=ed.game, name="RenameTarget")
        self.runtime.step(0)

        # 1. Right click row in hierarchy
        row = next(r for r in ed.hierarchy_rows if r.visible and r.relations.get("target") is target)
        self.send(("click", row.x + 20, row.y + 10, 4, 0))
        menu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(menu)
        rename_btn = next(c for c in menu.children if c.components.get("text") == "Rename")
        self.click(rename_btn)

        # Verify target is selected and name_field is focused with all text selected
        self.assertIs(ed.app.relations["selection"], target)
        self.assertIs(ed.ui.focused, ed.name_field)
        self.assertEqual(ed.name_field.buffer.selected_text, "RenameTarget")

        # Type new name and commit with Enter
        self.type(ed.name_field, "RenamedHero", commit=True)
        self.assertEqual(target.components.get("name"), "RenamedHero")

        # 2. Right click inside Inspector background / identity label
        self.send(("click", ed.identity_label.x + 10, ed.identity_label.y + 5, 4, 0))
        menu2 = ed.app.relations.get("context_menu")
        self.assertIsNotNone(menu2)
        self.assertIs(menu2.context_target, target)
        rename_btn2 = next(c for c in menu2.children if c.components.get("text") == "Rename")
        self.click(rename_btn2)
        self.assertIs(ed.ui.focused, ed.name_field)
        self.assertEqual(ed.name_field.buffer.selected_text, "RenamedHero")

    def test_right_click_add_component_presets_and_custom(self):
        ed = self.editor
        ent = self.runtime.create(parent=ed.game, name="CompEntity")
        self.select(ent)
        self.runtime.step(0)

        # 1. Context menu on entity provides unified + Add Component...
        self.send(("click", ed.identity_label.x + 10, ed.identity_label.y + 5, 4, 0))
        menu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(menu)

        add_item = next(c for c in menu.children if "+ Add Component" in c.components.get("text", ""))
        self.click(add_item)
        menu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(menu)

        speed_item = next(c for c in menu.children if "+ Speed" in c.components.get("text", ""))
        self.click(speed_item)
        self.assertEqual(ent.components.get("speed"), 100.0)

        # 2. Context menu '+ Custom Component...' focuses add_name
        self.send(("click", ed.identity_label.x + 10, ed.identity_label.y + 5, 4, 0))
        menu = ed.app.relations.get("context_menu")
        add_item = next(c for c in menu.children if "+ Add Component" in c.components.get("text", ""))
        self.click(add_item)
        menu = ed.app.relations.get("context_menu")
        custom_item = next(c for c in menu.children if "+ Custom Component..." in c.components.get("text", ""))
        self.click(custom_item)
        custom_lbl = next(l for l, _ in ed.component_rows if l.visible and l.component_key == "custom_component")
        self.assertIs(ed.ui.focused, custom_lbl)

        # 3. Dedicated '+ Component' button opens preset menu
        self.assertTrue(ed.add_comp_menu_button.visible)
        self.click(ed.add_comp_menu_button)
        menu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(menu)
        color_item = next(c for c in menu.children if "+ Color" in c.components.get("text", ""))
        self.click(color_item)
        self.assertEqual(ent.components.get("color"), (200, 200, 200))

    def test_relation_add_and_edit_workflow(self):
        ed = self.editor
        ship = self.runtime.create(parent=ed.game, name="HeroShip")
        dock = self.runtime.create(parent=ed.game, name="DockingBay")
        self.select(ship)
        self.runtime.step(0)

        # 1. Add link using '+' button with case-insensitive bare target name
        self.type(ed.relation_field, "dockingbay")
        self.click(ed.link_add_button)
        self.assertIs(ship.relations.get("dockingbay"), dock)

        # 2. Existing relation row has [Edit] button
        self.assertEqual(len([r for r, u in ed.relation_rows if r.visible]), 1)
        rel_btn, unlink_btn = ed.relation_rows[0]
        edit_btn = ed.relation_edit_buttons[0]
        self.assertTrue(edit_btn.visible)
        self.click(edit_btn)

        # Check relation_field is populated and focused for editing
        self.assertEqual(ed.relation_field.buffer.text, "dockingbay=DockingBay")
        self.assertIs(ed.ui.focused, ed.relation_field)

        # Update relation name to 'home_port' and click '+' button
        self.type(ed.relation_field, "home_port=DockingBay")
        self.click(ed.link_add_button)
        self.assertIs(ship.relations.get("home_port"), dock)
        self.assertNotIn("dockingbay", ship.relations)

        # 3. Right-clicking relation row shows context menu
        self.send(("click", rel_btn.x + 10, rel_btn.y + 5, 4, 0))
        menu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(menu)
        unlink_item = next(c for c in menu.children if "Unlink 'home_port'" in c.components.get("text", ""))
        self.click(unlink_item)
        self.assertNotIn("home_port", ship.relations)

    def test_inspector_header_layout_and_button_dimensions(self):
        ed = self.editor
        self.select(ed.game)
        self.runtime.step(0)

        ip = ed.inspector
        # Check streamlined header layout: name_field, identity_label, and divider_identity visible
        self.assertTrue(ed.name_field.visible)
        self.assertTrue(ed.identity_label.visible)
        self.assertTrue(ed.divider_identity.visible)

        # Removed action buttons are not visible in header
        self.assertFalse(ed.add_child_button.visible)
        self.assertFalse(ed.duplicate_button.visible)
        self.assertFalse(ed.delete_button.visible)

        # Check section header COMPONENTS and divider
        self.assertTrue(ed.components_title.visible)
        self.assertIn("COMPONENTS", ed.components_title.components.get("text"))
        self.assertTrue(ed.add_comp_menu_button.visible)
        self.assertLess(ed.divider_identity.y, ed.components_title.y)






    def test_selection_capture_shift_click_and_newline_highlights(self):
        code = self.editor.code
        self.type(code, 'abc\n\nxyz')
        pitch = code.pitch
        y = code.y+12
        self.send(('click', code.x+48+pitch, y, 1, 0))
        self.send(('release', code.x+48+pitch, y, 1, 0))
        self.send(('click', code.x+48+3*pitch, y, 1, 1))
        self.assertEqual(code.buffer.selection, (1, 3))
        camera_before = (self.editor.camera.x, self.editor.camera.y)
        viewport = self.editor.viewport
        self.send(('drag', viewport.x+100, viewport.y+100, 1, 0, 50, 50))
        self.assertEqual((self.editor.camera.x, self.editor.camera.y), camera_before)
        self.send(('release', viewport.x+100, viewport.y+100, 1, 0))
        self.assertNotIn('text_drag', self.editor.app.relations)
        code.buffer.anchor, code.buffer.cursor = 3, 5
        self.runtime.step(0)
        parts = {c.components.get('part'): c for c in code.children}
        self.assertTrue(parts['selection:0'].visible)
        self.assertTrue(parts['selection:1'].visible)
        self.assertEqual(parts['selection:1'].w, pitch)

    def test_completion_does_not_reopen_on_navigation_or_swallow_enter(self):
        code = self.editor.code
        self.type(code, 'entity.components')
        self.assertFalse(code.autocomplete_state['active'])
        self.send(('key', 'HOME', False, False))
        self.send(('key', 'RIGHT', False, False))
        self.runtime.step(0)
        self.assertFalse(code.autocomplete_state['active'])
        self.type(code, 'entity.c')
        self.await_completion()
        self.send(('key', 'ENTER', False, False))
        self.assertEqual(code.buffer.text, 'entity.c\n')
        self.assertFalse(code.autocomplete_state['active'])
        self.type(code, 'entity.c')
        self.await_completion()
        self.send(('key', 'RIGHT', False, True))
        self.assertFalse(code.autocomplete_state['active'])
        self.runtime.step(0)
        self.assertFalse(code.autocomplete_state['active'])

    def test_late_completion_cannot_replace_new_text(self):
        from concurrent.futures import Future
        code = self.editor.code
        self.type(code, 'entity.c')
        future = Future()
        future.set_running_or_notify_cancel()
        code.autocomplete_state.update(snapshot=(code.buffer.text, code.buffer.cursor, code.buffer.anchor), future=future)
        self.send(('key', 'A', True, False), ('text', 'different'))
        future.set_result(('c', [('components', 'property')]))
        self.runtime.step(0)
        self.assertEqual(code.buffer.text, 'different')
        self.assertFalse(code.autocomplete_state['active'])

    def test_manual_scroll_is_not_reset_to_caret_each_frame(self):
        code = self.editor.code
        self.type(code, '\n'.join(str(i) for i in range(100)))
        before = code.buffer.scroll
        self.send(('scroll', code.x+80, code.y+40, 0, 3))
        self.assertLess(code.buffer.scroll, before)
        scrolled = code.buffer.scroll
        self.runtime.step(0)
        self.assertEqual(code.buffer.scroll, scrolled)

    def test_completion_hints_live_game_entities(self):
        if importlib.util.find_spec("jedi") is None:
            self.skipTest("Jedi is an optional editor dependency")
        ship = self.editor.game.children[0]
        ship.components["name"] = "HeroShip"
        ship.components["vx"] = 5.0
        self.runtime.step(0)

        code = self.editor.code
        self.click(code)
        self.send(("key", "A", True, False), ("key", "BACKSPACE", False, False))
        self.send(("text", 'resolve("HeroShip").v'))
        self.await_completion()

        ac_state = code.components.get("autocomplete_state", {})
        self.assertTrue(ac_state.get("active"))
        match_names = [m[0] for m in ac_state.get("matches", [])]
        self.assertIn("vx", match_names)

    def test_autocomplete_only_triggers_on_typing(self):
        code = self.editor.code
        code.buffer.text = "HeroShip = 1\nHeroShip.vx = 2\n"
        code.buffer.cursor = code.buffer.anchor = 0
        self.runtime.step(0)

        # 1. Clicking to focus or navigate does not trigger autocomplete
        self.click(code)
        self.runtime.step(0)
        self.assertFalse(code.components.get("autocomplete_state", {}).get("active", False))

        # 2. Moving cursor via Arrow keys does not trigger autocomplete
        self.send(("key", "DOWN", False, False))
        self.send(("key", "RIGHT", False, False))
        self.runtime.step(0)
        self.assertFalse(code.components.get("autocomplete_state", {}).get("active", False))

        # 3. Mouse scrolling does not trigger autocomplete
        self.send(("scroll", code.x + 80, code.y + 40, 0, 1))
        self.runtime.step(0)
        self.assertFalse(code.components.get("autocomplete_state", {}).get("active", False))

        # 4. Text selection does not trigger autocomplete
        code.buffer.anchor = 0
        code.buffer.cursor = 8
        self.runtime.step(0)
        self.assertFalse(code.components.get("autocomplete_state", {}).get("active", False))

        # 5. Idling across frames does not trigger autocomplete
        for _ in range(5):
            self.runtime.step(0.1)
            self.assertFalse(code.components.get("autocomplete_state", {}).get("active", False))

    def test_scrollable_autocomplete_and_scrolling(self):
        if importlib.util.find_spec("jedi") is None:
            self.skipTest("Jedi is an optional editor dependency")
        code = self.editor.code
        self.click(code)
        self.send(("key", "A", True, False), ("key", "BACKSPACE", False, False))
        self.send(("text", "entity."))
        self.await_completion()

        ac_state = code.components.get("autocomplete_state", {})
        self.assertTrue(ac_state.get("active"))
        matches = ac_state.get("matches", [])
        self.assertGreater(len(matches), 8)

        # Popup and scrollbar thumb are visible
        thumb = next(c for c in code.children if c.components.get("part") == "ac_scroll_thumb")
        self.assertTrue(thumb.visible)

        # Scrolling down with DOWN arrow key
        for _ in range(8):
            self.send(("key", "DOWN", False, False))
        self.assertGreater(ac_state.get("scroll", 0), 0)

        # Scrolling with mouse wheel on popup
        popup = next(c for c in code.children if c.components.get("part") == "autocomplete_popup")
        self.send(("scroll", popup.x + 10, popup.y + 10, 0, -2))
        self.runtime.step(0)
        self.assertGreater(ac_state.get("scroll", 0), 1)

    def test_word_navigation_and_ctrl_backspace(self):
        code = self.editor.code
        self.click(code)
        self.send(("key", "A", True, False), ("key", "BACKSPACE", False, False))
        self.send(("text", "ship.speed = 100"))
        self.assertEqual(code.buffer.text, "ship.speed = 100")

        # 1. Ctrl+Left moves word by word
        self.send(("key", "LEFT", True, False))
        self.assertEqual(code.buffer.text[:code.buffer.cursor], "ship.speed = ")
        self.send(("key", "LEFT", True, False))
        self.assertEqual(code.buffer.text[:code.buffer.cursor], "ship.speed ")
        self.send(("key", "LEFT", True, False))
        self.assertEqual(code.buffer.text[:code.buffer.cursor], "ship.")

        # 2. Ctrl+Shift+Left selects word
        code.buffer.cursor = code.buffer.anchor = 10  # after 'speed'
        self.send(("key", "LEFT", True, True))
        self.assertEqual(code.buffer.selected_text, "speed")

        # 3. Ctrl+Backspace deletes previous word
        code.buffer.cursor = code.buffer.anchor = len(code.buffer.text)
        self.send(("key", "BACKSPACE", True, False))
        self.assertEqual(code.buffer.text, "ship.speed = ")

    def test_double_click_and_triple_click_selection(self):
        code = self.editor.code
        pitch = code.components.get("pitch", 8.0)
        line_height = code.components.get("line_height", 20)
        code.buffer.text = "def update(dt):\n    pass\n"
        code.buffer.cursor = code.buffer.anchor = 0
        self.runtime.step(0)

        # Double click on 'update' (x at col 6, y at row 0)
        click_x = code.x + 48 + 6 * pitch + pitch / 2
        click_y = code.y + 6 + line_height / 2
        self.send(("click", click_x, click_y, 1, 0, 2))
        self.assertEqual(code.buffer.selected_text, "update")

        # Triple click on first line
        self.send(("click", click_x, click_y, 1, 0, 3))
        self.assertEqual(code.buffer.selected_text, "def update(dt):\n")

    def test_multiline_tuple_closing_dedent(self):
        code = self.editor.code
        self.click(code)
        self.send(("key", "A", True, False), ("key", "BACKSPACE", False, False))
        self.send(("text", "def test():\n    data = (\n        1,\n        2,\n        "))
        self.assertEqual(code.buffer.position[0], 4)

        # Type ')' on line with 8 spaces indent
        self.send(("text", ")"))
        lines = code.buffer.text.split("\n")
        self.assertEqual(lines[4], "    )")

    def test_hover_inspection_tooltip(self):
        if importlib.util.find_spec("jedi") is None:
            self.skipTest("Jedi is an optional editor dependency")
        code = self.editor.code
        pitch = code.components.get("pitch", 8.0)
        line_height = code.components.get("line_height", 20)
        self.click(code)
        self.send(("key", "A", True, False), ("key", "BACKSPACE", False, False))
        self.send(("text", "def update(dt):\n    for child in query('x'):\n        pass\n"))
        self.runtime.step(0)

        # Position mouse over 'query' (row 1, col 18)
        mx = code.x + 48 + 18 * pitch
        my = code.y + 6 + 1 * line_height + line_height / 2
        self.send(("motion", mx, my))

        # Dwell for 0.4 seconds
        self.runtime.step(0.4)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            self.runtime.step(0.05)
            h_state = code.components.get("hover_state", {})
            if h_state.get("active"):
                break
            time.sleep(0.01)

        self.assertTrue(h_state.get("active"), "Hover tooltip should activate")
        self.assertEqual(h_state["info"]["name"], "query")

        # Hover panel is visible
        tip = next((c for c in code.children if c.components.get("part") == "hover_panel"), None)
        self.assertIsNotNone(tip)
        self.assertTrue(tip.visible)

        # Moving mouse away dismisses hover
        self.send(("motion", code.x - 100, code.y - 100))
        self.runtime.step(0)
        self.assertFalse(code.components.get("hover_state", {}).get("active", False))

    def test_hover_range_overloads_and_docstrings(self):
        """Issue #55: Multi-signature overloads and multi-line docstring rendering for range."""
        if importlib.util.find_spec("jedi") is None:
            self.skipTest("Jedi is an optional editor dependency")
        from lbe.completion import hover_info
        info = hover_info("x = range(10)", 0, 6, "main.py")
        self.assertIsNotNone(info)
        self.assertEqual(info["name"], "range")
        self.assertGreaterEqual(len(info.get("signatures", [])), 2)
        self.assertTrue(any("stop" in s for s in info["signatures"]))
        self.assertTrue(any("step" in s for s in info["signatures"]))
        self.assertIn("sequence of integers", info.get("docstring", ""))
        self.assertFalse(info["docstring"].startswith("range("))

        # Test editor UI hover rendering
        code = self.editor.code
        pitch = code.components.get("pitch", 8.0)
        line_height = code.components.get("line_height", 20)
        self.click(code)
        self.send(("key", "A", True, False), ("key", "BACKSPACE", False, False))
        self.send(("text", "x = range(10)\n"))
        self.runtime.step(0)

        # Position mouse over 'range' (row 0, col 6)
        mx = code.x + 48 + 6 * pitch
        my = code.y + 6 + line_height / 2
        self.send(("motion", mx, my))

        # Dwell for hover activation
        self.runtime.step(0.4)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            self.runtime.step(0.05)
            h_state = code.components.get("hover_state", {})
            if h_state.get("active"):
                break
            time.sleep(0.01)

        self.assertTrue(h_state.get("active"), "Hover tooltip should activate for range")
        tip = next((c for c in code.children if c.components.get("part") == "hover_panel"), None)
        self.assertIsNotNone(tip)
        self.assertTrue(tip.visible)

        # Check that hover_line:0 displays the alternate signature and hover_line:1 displays docstring
        line0 = next((c for c in code.children if c.components.get("part") == "hover_line:0"), None)
        self.assertIsNotNone(line0)
        self.assertTrue(line0.visible)
        self.assertIn("range", line0.text)
        self.assertIn("step", line0.text)

        line1 = next((c for c in code.children if c.components.get("part") == "hover_line:1"), None)
        self.assertIsNotNone(line1)
        self.assertTrue(line1.visible)
        self.assertTrue(len(line1.text) > 0)

        # Calling stop() cleans up hover child parts
        code.systems["code_editor"].stop()
        self.assertFalse(tip.visible)
        self.assertFalse(line0.visible)
        self.assertFalse(line1.visible)


    def test_multiline_call_newline_and_safe_ctrl_backspace(self):
        code = self.editor.code
        self.click(code)
        self.send(("key", "A", True, False), ("key", "BACKSPACE", False, False))
        snippet = (
            "def draw():\n"
            "    with graphics.view(entity.relations[\"camera\"], entity.relations[\"viewport\"]):\n"
            "        for child in query(\"x\", \"y\", \"w\", \"h\", \"color\"):\n"
            "            graphics.rect(child.x, child.y, child.w, child.h,\n"
            "                          color=child.color, key=child.id, layer=1)"
        )
        self.send(("text", snippet))
        # Cursor is at the end of layer=1)
        self.send(("key", "ENTER", False, False))
        lines = code.buffer.text.split("\n")
        # Line 5 should have 12 spaces (aligning with graphics.rect), NOT 26 spaces
        self.assertEqual(lines[-1], "            ")

        # Press Ctrl+Backspace to clear indentation spaces
        self.send(("key", "BACKSPACE", True, False))
        lines_after_bs = code.buffer.text.split("\n")
        # The line spaces should be cleared, but layer=1) on the previous line MUST remain intact!
        self.assertEqual(lines_after_bs[-1], "")
        self.assertTrue(lines_after_bs[-2].endswith("layer=1)"))

    def test_escape_preserves_editor_focus_when_autocomplete_inactive(self):
        """Issue #47: Escape when autocomplete is not active must not drop editor focus."""
        code = self.editor.code
        self.click(code)
        self.assertIs(self.editor.ui.focused, code)

        # Autocomplete is not active
        ac_state = code.components.get("autocomplete_state", {})
        self.assertFalse(ac_state.get("active", False))

        # Press Escape - should NOT drop focus
        self.send(("key", "ESCAPE", False, False))
        self.assertIs(self.editor.ui.focused, code)

    def test_callbacks_attached_once_not_per_frame(self):
        """Issue #47: on_text/on_key/on_scroll should be set once in start(), not every frame."""
        code = self.editor.code
        self.assertIsNotNone(code.components.get("on_text"))
        self.assertIsNotNone(code.components.get("on_key"))
        self.assertIsNotNone(code.components.get("on_scroll"))

        on_text = code.components["on_text"]
        on_key = code.components["on_key"]

        for _ in range(5):
            self.runtime.step(0)
        self.assertIs(code.components["on_text"], on_text)
        self.assertIs(code.components["on_key"], on_key)

    def test_bracket_match_cached_when_unchanged(self):
        """Issue #47: matching_brackets should not be recomputed when text+cursor unchanged."""
        code = self.editor.code
        self.click(code)
        self.send(("key", "A", True, False), ("text", "(hello)"))
        self.runtime.step(0)

        match1 = code.components.get("matching_brackets")

        for _ in range(3):
            self.runtime.step(0)

        match2 = code.components.get("matching_brackets")
        self.assertIs(match1, match2)

    def test_hover_does_not_spam_requests_on_non_symbol(self):
        """Issue #47: hover should set resolved_empty sentinel on non-symbol."""
        code = self.editor.code
        self.click(code)
        self.send(("key", "A", True, False), ("text", "   "))

        hover_state = code.components.setdefault("hover_state",
            {"active": False, "dwell_start": 0.0, "last_mouse": (-100, -100)})

        # Position inside the code editor over whitespace
        mx, my = code.x + 55, code.y + 10
        from time import monotonic
        hover_state["last_mouse"] = (mx, my)
        hover_state["dwell_start"] = monotonic() - 1.0
        hover_state.pop("resolved_empty", None)
        # Also set ui.mouse_pos so the hover entry condition passes
        self.editor.ui.mouse_pos = (mx, my)

        self.runtime.step(0)
        self.assertTrue(hover_state.get("resolved_empty", False))

        # Further steps should NOT spawn a future
        self.assertNotIn("future", hover_state)
        self.runtime.step(0)
        self.assertNotIn("future", hover_state)

    def test_popup_entities_hidden_on_code_editor_stop(self):
        """Issue #47: popup entities should be hidden when code_editor system stops."""
        code = self.editor.code
        self.click(code)
        self.send(("text", "entity."))
        self.runtime.step(0)
        popup = next((c for c in code.children if c.components.get("part") == "autocomplete_popup"), None)
        if popup is not None:
            code.systems["code_editor"].stop()
            self.assertFalse(popup.visible)
    def test_quote_auto_pairing_on_indented_empty_line(self):
        """Issue #48: Typing quote on an indented line must auto-close with cursor between."""
        code = self.editor.code
        self.click(code)
        self.send(("key", "A", True, False), ("key", "BACKSPACE", False, False))
        self.send(("text", "    "))  # 4 spaces indent
        self.assertEqual(code.buffer.text, "    ")
        self.assertEqual(code.buffer.cursor, 4)

        # Type double quote
        self.send(("text", '"'))
        self.assertEqual(code.buffer.text, '    ""')
        self.assertEqual(code.buffer.cursor, 5)

        # Type-over closing double quote
        self.send(("text", '"'))
        self.assertEqual(code.buffer.text, '    ""')
        self.assertEqual(code.buffer.cursor, 6)

    def test_string_prefix_quote_auto_pairing(self):
        """Issue #48: String prefix letters (f, r, b, u, fr, etc.) must allow quote auto-close."""
        code = self.editor.code
        self.click(code)

        for prefix in ("f", "r", "b", "u", "fr", "rf"):
            self.send(("key", "A", True, False), ("key", "BACKSPACE", False, False))
            self.send(("text", prefix))
            self.send(("text", '"'))
            self.assertEqual(code.buffer.text, f'{prefix}""', f"Failed for prefix {prefix}")
            self.assertEqual(code.buffer.cursor, len(prefix) + 1)

        # Non-prefix word must NOT auto-close
        self.send(("key", "A", True, False), ("key", "BACKSPACE", False, False))
        self.send(("text", "word"))
        self.send(("text", '"'))
        self.assertEqual(code.buffer.text, 'word"')
        self.assertEqual(code.buffer.cursor, 5)

    def test_bracket_matching_ignores_comments_and_strings(self):
        """Issue #48: Brackets inside comments and string literals must not fool bracket matcher."""
        code = self.editor.code
        self.click(code)
        self.send(("key", "A", True, False), ("key", "BACKSPACE", False, False))
        source = (
            "# A comment with (unmatched paren\n"
            "s = 'also (unmatched'\n"
            "def foo(x):\n"
            "    return x"
        )
        self.send(("text", source))

        # Cursor right after ( in foo(x)
        idx_open = source.index("def foo(") + len("def foo(")
        code.buffer.cursor = code.buffer.anchor = idx_open
        self.runtime.step(0)
        matching = code.components.get("matching_brackets")
        self.assertIsNotNone(matching)
        # Should match foo(x)'s closing paren on line 2
        self.assertEqual(matching[0][0], 2)
        self.assertEqual(matching[1][0], 2)

        # Cursor adjacent to bracket inside comment must NOT match
        idx_comment_paren = source.index("(unmatched")
        code.buffer.cursor = code.buffer.anchor = idx_comment_paren
        self.runtime.step(0)
        self.assertIsNone(code.components.get("matching_brackets"))

    def test_editor_tab_and_shift_tab_multiline_indent_dedent(self):
        """Issue #49: Tab and Shift+Tab in code editor indents/dedents selected lines."""
        code = self.editor.code
        self.click(code)
        self.send(("key", "A", True, False), ("key", "BACKSPACE", False, False))
        text = "def test():\n    a = 1\n    b = 2"
        self.send(("text", text))

        # Select lines 1-2
        code.buffer.anchor = code.buffer.text.index("    a")
        code.buffer.cursor = len(code.buffer.text)
        code.components.touch("buffer")
        self.runtime.step(0)

        # Tab indents both lines to 8 spaces
        self.send(("key", "TAB", False, False))
        self.assertEqual(code.buffer.text, "def test():\n        a = 1\n        b = 2")

        # Shift+Tab dedents both lines back to 4 spaces
        self.send(("key", "TAB", False, True))
        self.assertEqual(code.buffer.text, "def test():\n    a = 1\n    b = 2")

    def test_editor_ctrl_slash_comment_toggle(self):
        """Issue #49: Ctrl+/ toggles line comment with atomic undo."""
        code = self.editor.code
        self.click(code)
        self.send(("key", "A", True, False), ("key", "BACKSPACE", False, False))
        self.send(("text", "x = 10"))

        # Ctrl+/ comments line
        self.send(("key", "SLASH", True, False))
        self.assertEqual(code.buffer.text, "# x = 10")

        # Ctrl+/ again uncomments line
        self.send(("key", "SLASH", True, False))
        self.assertEqual(code.buffer.text, "x = 10")

        # Undo restores commented state in one step
        self.send(("key", "Z", True, False))
        self.assertEqual(code.buffer.text, "# x = 10")

    def test_code_editor_scrollbar_track_and_thumb_interaction(self):
        """Issue #50: Code editor scrollbar thumb dragging and track click-to-jump."""
        code = self.editor.code
        self.click(code)
        self.send(("key", "A", True, False), ("key", "BACKSPACE", False, False))

        # Insert 100 lines so scrollbar appears
        long_code = "\n".join(f"line_{i} = {i}" for i in range(100))
        self.send(("text", long_code))
        code.buffer.cursor = code.buffer.anchor = 0
        code.buffer.scroll = 0
        code.components.touch("buffer")
        self.runtime.step(0)

        # Find scroll_track and scrollbar (thumb)
        track = next((c for c in code.children if c.components.get("part") == "scroll_track"), None)
        thumb = next((c for c in code.children if c.components.get("part") == "scrollbar"), None)
        self.assertIsNotNone(track)
        self.assertIsNotNone(thumb)
        self.assertTrue(track.visible)
        self.assertTrue(thumb.visible)
        self.assertEqual(code.buffer.scroll, 0)

        # 1. Drag thumb downwards
        self.send(("click", thumb.x + 2, thumb.y + 4, 1, 0))
        self.send(("drag", thumb.x + 2, thumb.y + 100, 1, 0, 0, 96))
        self.send(("release", thumb.x + 2, thumb.y + 100, 1, 0))
        self.runtime.step(0)
        self.assertGreater(code.buffer.scroll, 0)

        # 2. Click track above thumb to page up
        scrolled = code.buffer.scroll
        self.send(("click", track.x + 2, track.y + 2, 1, 0))
        self.send(("release", track.x + 2, track.y + 2, 1, 0))
        self.runtime.step(0)
        self.assertLess(code.buffer.scroll, scrolled)

    def test_code_editor_selection_drag_autoscroll(self):
        """Issue #50: Selection drag beyond editor bounds autoscrolls the viewport."""
        code = self.editor.code
        self.click(code)
        self.send(("key", "A", True, False), ("key", "BACKSPACE", False, False))

        # Insert 100 lines
        long_code = "\n".join(f"line_{i} = {i}" for i in range(100))
        self.send(("text", long_code))
        code.buffer.cursor = code.buffer.anchor = 0
        code.buffer.scroll = 0
        code.components.touch("buffer")
        self.runtime.step(0)

        # Click near top of code editor to start selection drag
        self.send(("click", code.x + 60, code.y + 20, 1, 0))
        self.assertEqual(code.buffer.scroll, 0)

        # Drag beyond the bottom of the code editor
        self.send(("drag", code.x + 60, code.y + code.h + 50, 1, 0, 0, 100))
        self.runtime.step(0)
        # Scroll should have increased due to autoscroll
        self.assertGreater(code.buffer.scroll, 0)

        # Drag back above top of code editor
        scrolled = code.buffer.scroll
        self.send(("drag", code.x + 60, code.y - 100, 1, 0, 0, -150))
        self.runtime.step(0)
        self.assertLess(code.buffer.scroll, scrolled)

        self.send(("release", code.x + 60, code.y + 20, 1, 0))

    def test_inspector_systems_management_attach_and_detach(self):
        """Issue #57: Inspector systems section is always visible with attach/detach controls."""
        ed = self.editor
        ent = self.runtime.create(parent=ed.game, name="ActorEntity")
        self.select(ent)
        self.runtime.step(0)

        # 1. Systems section is always visible, showing 'No systems attached' placeholder
        self.assertTrue(ed.system_label.visible)
        self.assertTrue(ed.add_system_button.visible)
        self.assertTrue(ed.no_systems_label.visible)

        # 2. Click '+ Attach' button to open system menu
        self.click(ed.add_system_button)
        menu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(menu)
        render_item = next((c for c in menu.children if "render" in c.components.get("text", "")), None)
        self.assertIsNotNone(render_item)

        # Click to attach render system to ActorEntity
        self.click(render_item)
        self.assertIn("render", ent.systems)
        self.assertFalse(ed.no_systems_label.visible)

        # 3. System appears in inspector row with Edit button
        sys_btn = next((b for b in ed.system_rows if b.visible and "render" in b.components.get("text", "")), None)
        self.assertIsNotNone(sys_btn)
        edit_btn = ed.system_edit_buttons[0]
        self.assertTrue(edit_btn.visible)

        # Click Edit to open in code editor
        self.click(edit_btn)
        self.assertEqual(ed.path_field.buffer.text, "render.py")

        # 4. Right click system row to detach
        self.send(("click", sys_btn.x + 10, sys_btn.y + 10, 4, 0))
        detach_menu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(detach_menu)
        detach_item = next((c for c in detach_menu.children if "Detach" in c.components.get("text", "")), None)
        self.assertIsNotNone(detach_item)
        self.click(detach_item)

        # Verify system is cleanly detached
        self.assertNotIn("render", ent.systems)
        self.assertTrue(ed.no_systems_label.visible)

    def test_clean_float_formatting_in_inspector(self):
        """Issue #57: Float precision is cleanly formatted in component fields."""
        ed = self.editor
        ent = self.runtime.create(parent=ed.game, name="FloatEntity",
                                  x=0.0, y=-103.77000000000001,
                                  coords=(0.0, -103.77000000000001))
        self.select(ent)
        self.runtime.step(0)

        # Check y field text is formatted cleanly
        y_fld = next(fld for lbl, fld in ed.component_rows if fld.visible and fld.component_key == "y")
        self.assertEqual(y_fld.buffer.text, "-103.77")

        # Check coords tuple is formatted cleanly
        coords_fld = next(fld for lbl, fld in ed.component_rows if fld.visible and fld.component_key == "coords")
        self.assertEqual(coords_fld.buffer.text, "(0.0, -103.77)")

    def test_quick_component_bar_and_renaming(self):
        """Issue #59: Dropdown presets, inline renaming, and smart focus."""
        ed = self.editor
        ent = self.runtime.create(parent=ed.game, name="Hero")
        self.select(ent)
        self.runtime.step(0)

        # 1. Preset via + Add button focuses value with highlight
        self.click(ed.add_comp_menu_button)
        menu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(menu)
        pos_item = next(c for c in menu.children if "+ Transform" in c.components.get("text", ""))
        self.click(pos_item)
        self.assertIn("x", ent.components)
        self.assertIn("y", ent.components)
        # Value field is focused with text highlighted
        x_fld = next(fld for _, fld in ed.component_rows if fld.visible and fld.component_key == "x")
        self.assertIs(ed.ui.focused, x_fld)
        self.assertEqual(x_fld.buffer.selection, (0, len(x_fld.buffer.text)))

        # 2. Right-click 'y' component to rename inline
        lbl, y_fld = next((lbl, fld) for (lbl, fld) in ed.component_rows if fld.visible and fld.component_key == "y")
        self.send(("click", y_fld.x + 10, y_fld.y + 10, 4, 0))
        menu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(menu)
        rename_item = next(c for c in menu.children if "Rename" in c.components.get("text", ""))
        self.click(rename_item)

        # Label field is now focused with 'y' selected
        self.assertIs(ed.ui.focused, lbl)
        self.assertEqual(lbl.buffer.text, "y")
        self.assertEqual(lbl.buffer.selection, (0, len("y")))

        # Commit rename to 'pos_y'
        self.type(lbl, "pos_y", commit=True)
        self.assertNotIn("y", ent.components)
        self.assertIn("pos_y", ent.components)

        # 3. Add Custom Component automatically focuses name field with highlight
        self.click(ed.add_comp_menu_button)
        menu = ed.app.relations.get("context_menu")
        custom_item = next(c for c in menu.children if "Custom Component" in c.components.get("text", ""))
        self.click(custom_item)
        self.assertIn("custom_component", ent.components)
        custom_lbl = next(l for l, _ in ed.component_rows if l.visible and l.component_key == "custom_component")
        self.assertIs(ed.ui.focused, custom_lbl)
        self.assertEqual(custom_lbl.buffer.selection, (0, len("custom_component")))

    def test_inspector_collapsible_sections(self):
        """Issue #59: Inspector sections can be collapsed and expanded with dividers."""
        ed = self.editor
        ent = self.runtime.create(parent=ed.game, name="CollapsibleEntity", x=1.0, y=2.0)
        self.select(ent)
        self.runtime.step(0)

        # Components are visible initially, as is divider
        visible_comps = [fld for lbl, fld in ed.component_rows if fld.visible]
        self.assertGreater(len(visible_comps), 0)
        self.assertTrue(ed.divider_components.visible)

        # Click COMPONENTS header to collapse
        self.click(ed.components_title)
        visible_comps_after = [fld for lbl, fld in ed.component_rows if fld.visible]
        self.assertEqual(len(visible_comps_after), 0)
        self.assertFalse(ed.divider_components.visible)

        # Click COMPONENTS header again to re-expand
        self.click(ed.components_title)
        visible_comps_reexpanded = [fld for lbl, fld in ed.component_rows if fld.visible]
        self.assertGreater(len(visible_comps_reexpanded), 0)
        self.assertTrue(ed.divider_components.visible)

    def test_hierarchy_hover_color_and_no_flashing(self):
        """Hierarchy row colors have matching normal/hover colors between sync and motion, preventing flashing."""
        ed = self.editor
        row = next(r for r in ed.hierarchy_rows if r.visible)
        self.assertIn("normal_color", row.components)
        self.assertIn("hover_color", row.components)
        self.assertEqual(row.hover_color, (35, 45, 58))

        # Mouse motion over row sets hover_color
        self.send(("motion", row.x + 10, row.y + 10))
        self.assertEqual(row.color, row.hover_color)

        # Step update preserves hover_color while mouse remains on row (no flashing to normal)
        self.runtime.step(0)
        self.assertEqual(row.color, row.hover_color)

        # Mouse motion away restores normal_color
        self.send(("motion", ed.viewport.x + 10, ed.viewport.y + 10))
        self.assertEqual(row.color, row.normal_color)

    def test_system_edit_button_dimensions_and_visibility(self):
        """System Edit button width is at least 52px so 'Edit' text fits without truncation to 'Edi'."""
        ed = self.editor
        ent = self.runtime.create(parent=ed.game, name="SysEntity")
        self.select(ent)
        self.runtime.step(0)
        # Attach a system
        from lbe.systems import SystemDefinition
        ent.systems.attach("sample", SystemDefinition('def update(dt): pass'))
        self.runtime.step(0)
        edit_btn = next(b for b in ed.system_edit_buttons if b.visible)
        self.assertEqual(edit_btn.text, "Edit")
        self.assertGreaterEqual(edit_btn.w, 52)
        # Pitch is 8, 4 chars * 8 = 32px; width 52 leaves 20px padding (>= 16px required)
        self.assertGreaterEqual(edit_btn.w - 16, 4 * 8)

    def test_hierarchy_right_click_selects_target(self):
        """Right-clicking a hierarchy row immediately selects the entity in hierarchy and inspector."""
        ed = self.editor
        child = self.runtime.create(parent=ed.game, name="RightClickTarget")
        self.runtime.step(0)
        row = next(r for r in ed.hierarchy_rows if r.visible and r.relations.get("target") is child)
        self.send(("click", row.x + 40, row.y + 10, 4, 0))
        # Child is now selected
        self.assertIs(ed.app.relations.get("selection"), child)
        # Context menu is open targeting child
        menu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(menu)
        self.assertIs(menu.context_target, child)

    def test_ctrl_right_click_deep_selection_and_highlight(self):
        """Normal right-click uses game workflows; Ctrl+Right-Click provides deep inspect on any UI element."""
        ed = self.editor

        # 1. Normal right-click on Code Editor provides code actions, not selecting CodeEditor in hierarchy
        self.send(("click", ed.code.x + 20, ed.code.y + 20, 4, 0))
        menu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(menu)
        self.assertIsInstance(menu.context_target, dict)
        self.assertTrue(menu.context_target.get("code"))
        action_labels = [c.text for c in menu.children if "text" in c.components]
        self.assertIn("Select All", action_labels)
        self.assertIn("Copy", action_labels)
        self.assertNotIn("Select 'CodeEditor' in hierarchy", action_labels)
        self.send(("key", "ESCAPE", False, False))

        # 2. Holding Ctrl immediately highlights the stack without clicking
        self.send(("key", "LCTRL", True, False))
        self.send(("motion", ed.header.x + 20, ed.header.y + 10, 2))
        self.assertTrue(ed.ui.ctrl_held)
        # Call draw and verify outline rects for Header (leaf) and App (parent) are generated
        self.graphics.rectangles.clear()
        ed.ui.draw()
        hl_keys = [kw.get("key") for _, kw in self.graphics.rectangles if kw.get("key") and isinstance(kw["key"], tuple) and kw["key"][0] == "ctrl_hl"]
        self.assertEqual(len(hl_keys), 8)  # 4 for Header + 4 for App

        # 3. Holding Ctrl over a game entity highlights both entity and viewport
        player = self.runtime.create(parent=ed.game, name="Player", x=0.0, y=0.0, w=1.0, h=1.0)
        self.runtime.step(0)
        from lbe.space import world_to_screen
        sx, sy = world_to_screen(ed.camera, ed.viewport, 0.0, 0.0)
        self.send(("motion", sx, sy, 2))
        self.graphics.rectangles.clear()
        ed.ui.draw()
        hl_rects = [kw for _, kw in self.graphics.rectangles if kw.get("key") and isinstance(kw["key"], tuple) and kw["key"][0] == "ctrl_hl"]
        self.assertEqual(len(hl_rects), 12)  # 4 for Player + 4 for Viewport + 4 for App

        # Releasing Ctrl removes outlines on next draw
        self.send(("key_up", "LCTRL", False, False))
        self.assertFalse(ed.ui.ctrl_held)
        self.graphics.rectangles.clear()
        ed.ui.draw()
        hl_keys_after = [kw.get("key") for _, kw in self.graphics.rectangles if kw.get("key") and isinstance(kw["key"], tuple) and kw["key"][0] == "ctrl_hl"]
        self.assertEqual(len(hl_keys_after), 0)

        # 4. Ctrl + Right-Click on game entity provides color-coded stack selection
        self.send(("click", sx, sy, 4, 2))  # Modifier 2 = MOD_CTRL
        menu_game = ed.app.relations.get("context_menu")
        self.assertIsNotNone(menu_game)
        self.assertTrue(menu_game.context_target.get("deep"))
        game_items = [c for c in menu_game.children if "text" in c.components]
        sel_labels = [c.text for c in game_items if "Select" in c.text]
        self.assertTrue(any("Player" in lbl and "Leaf" in lbl for lbl in sel_labels))
        self.assertTrue(any("Viewport" in lbl and "Parent" in lbl for lbl in sel_labels))
        self.assertTrue(any("Application" in lbl and "Root" in lbl for lbl in sel_labels))

        # Clicking '> Select 'Viewport' (Parent)' selects the viewport
        vp_btn = next(c for c in game_items if "Viewport" in c.text and "Select" in c.text)
        self.click(vp_btn)
        self.assertIs(ed.app.relations.get("selection"), ed.viewport)
        self.send(("key", "ESCAPE", False, False))

        # 5. Ctrl + Right-Click on RunButton deeply targets it and allows selection
        self.send(("click", ed.run_button.x + 10, ed.run_button.y + 10, 4, 2))
        menu_btn = ed.app.relations.get("context_menu")
        self.assertIsNotNone(menu_btn)
        self.assertTrue(menu_btn.context_target.get("deep"))
        self.assertIs(menu_btn.context_target.get("entity"), ed.run_button)
        deep_labels = [c.text for c in menu_btn.children if "text" in c.components]
        self.assertTrue(any("Select" in lbl and "ToggleRun" in lbl for lbl in deep_labels))
        self.send(("key", "ESCAPE", False, False))

        # 6. Child entity under Player is drawn, highlighted in full stack, and selectable
        turret = self.runtime.create(parent=player, name="Turret", x=0.2, y=0.2, w=0.6, h=0.6, color=(255, 100, 100))
        self.runtime.step(0)
        tx, ty = world_to_screen(ed.camera, ed.viewport, 0.5, 0.5)
        ed.ui.mouse_pos = (tx, ty)
        ed.input.ctrl = True
        self.graphics.rectangles.clear()
        ed.ui.draw()
        hl_rects = [kw for _, kw in self.graphics.rectangles if kw.get("key") and isinstance(kw["key"], tuple) and kw["key"][0] == "ctrl_hl"]
        # 4 for Turret (Leaf) + 4 for Player (Parent) + 4 for Viewport (Parent) + 4 for App (Root) = 16
        self.assertEqual(len(hl_rects), 16)

        # Viewport click directly on child entity selects the child entity
        self.send(("click", tx, ty, 1, 0))
        self.assertIs(ed.app.relations.get("selection"), turret)

        # Ctrl + Right-Click on turret includes Turret as Leaf and Player as Parent
        self.send(("click", tx, ty, 4, 2))
        menu_turret = ed.app.relations.get("context_menu")
        self.assertIsNotNone(menu_turret)
        turret_items = [c.text for c in menu_turret.children if "text" in c.components and "Select" in c.text]
        self.assertTrue(any("Turret" in lbl and "Leaf" in lbl for lbl in turret_items))
        self.assertTrue(any("Player" in lbl and "Parent" in lbl for lbl in turret_items))
        self.send(("key", "ESCAPE", False, False))

        # 7. Moving parent automatically moves child entity's rendered world position
        player.x = 2.0
        player.y = 3.0
        self.runtime.step(0)
        tx_moved, ty_moved = world_to_screen(ed.camera, ed.viewport, 2.5, 3.5)
        # Clicking at new world position selects turret
        self.send(("click", tx_moved, ty_moved, 1, 0))
        self.assertIs(ed.app.relations.get("selection"), turret)

    def test_component_context_menu_change_type(self):
        """Issue #65: Context menu on component row provides Change type... to convert values."""
        ed = self.editor
        ent = self.runtime.create(parent=ed.game, name="TypeTestEntity", score=42.5)
        self.select(ent)
        self.runtime.step(0)

        # Right-click score component
        _, score_fld = next((lbl, fld) for (lbl, fld) in ed.component_rows if fld.visible and fld.component_key == "score")
        self.send(("click", score_fld.x + 10, score_fld.y + 10, 4, 0))
        menu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(menu)

        # Verify Change type item exists
        change_item = next(c for c in menu.children if "Change type" in c.components.get("text", ""))
        self.assertIn("float", change_item.components.get("text", ""))

        # Click Change type to open types submenu
        self.click(change_item)
        type_menu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(type_menu)

        # Change to int
        int_choice = next(c for c in type_menu.children if "int" in c.components.get("text", ""))
        self.click(int_choice)
        self.assertEqual(ent.components["score"], 42)
        self.assertIsInstance(ent.components["score"], int)

        # Change to bool
        _, score_fld = next((lbl, fld) for (lbl, fld) in ed.component_rows if fld.visible and fld.component_key == "score")
        self.send(("click", score_fld.x + 10, score_fld.y + 10, 4, 0))
        menu = ed.app.relations.get("context_menu")
        change_item = next(c for c in menu.children if "Change type" in c.components.get("text", ""))
        self.click(change_item)
        type_menu = ed.app.relations.get("context_menu")
        bool_choice = next(c for c in type_menu.children if "bool" in c.components.get("text", ""))
        self.click(bool_choice)
        self.assertEqual(ent.components["score"], True)
        self.assertIsInstance(ent.components["score"], bool)

        # Change to str
        _, score_fld = next((lbl, fld) for (lbl, fld) in ed.component_rows if fld.visible and fld.component_key == "score")
        self.send(("click", score_fld.x + 10, score_fld.y + 10, 4, 0))
        menu = ed.app.relations.get("context_menu")
        change_item = next(c for c in menu.children if "Change type" in c.components.get("text", ""))
        self.click(change_item)
        type_menu = ed.app.relations.get("context_menu")
        str_choice = next(c for c in type_menu.children if "str" in c.components.get("text", ""))
        self.click(str_choice)
        self.assertEqual(ent.components["score"], "True")
        self.assertIsInstance(ent.components["score"], str)

    def test_component_context_menu_entity_type_actions(self):
        """Issue #65: Right-clicking an entity-typed component reveals entity-specific context actions."""
        ed = self.editor
        target_ent = self.runtime.create(parent=ed.game, name="BossShip", x=10.0, y=10.0)
        hero = self.runtime.create(parent=ed.game, name="PlayerHero", target_entity=target_ent)
        self.select(hero)
        self.runtime.step(0)

        # Right-click target_entity component row
        _, tgt_fld = next((lbl, fld) for (lbl, fld) in ed.component_rows if fld.visible and fld.component_key == "target_entity")
        self.send(("click", tgt_fld.x + 10, tgt_fld.y + 10, 4, 0))
        menu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(menu)

        texts = [c.components.get("text", "") for c in menu.children if "text" in c.components]
        # Should have component actions
        self.assertTrue(any("Inspect component" in t for t in texts))
        self.assertTrue(any("Change type" in t for t in texts))
        self.assertTrue(any("Delete 'target_entity'" in t for t in texts))

        # Should ALSO have entity actions for BossShip
        self.assertTrue(any("Select Entity 'BossShip'" in t for t in texts))
        self.assertTrue(any("Inspect Entity 'BossShip'" in t for t in texts))
        self.assertTrue(any("Rename Entity 'BossShip'" in t for t in texts))
        self.assertTrue(any("Add Component to 'BossShip'" in t for t in texts))

        # Clicking select entity selects BossShip
        select_item = next(c for c in menu.children if "Select Entity 'BossShip'" in c.components.get("text", ""))
        self.click(select_item)
        self.assertIs(ed.app.relations.get("selection"), target_ent)

    def test_add_component_context_menu_unification(self):
        """Issue #65: Viewport, hierarchy, and inspector context menus all offer unified + Add Component... expanding presets."""
        ed = self.editor
        unit = self.runtime.create(parent=ed.game, name="UnifiedUnit", x=0.0, y=0.0, w=2.0, h=2.0)
        self.select(unit)
        self.runtime.step(0)

        # 1. Viewport right-click on entity
        sx, sy = world_to_screen(ed.camera, ed.viewport, 0.5, 0.5)
        self.send(("click", sx, sy, 4, 0))
        vp_menu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(vp_menu)
        vp_texts = [c.components.get("text", "") for c in vp_menu.children if "text" in c.components]
        self.assertIn("+ Add Component...", vp_texts)
        self.assertNotIn("+ Add Pos (x, y)", vp_texts)  # Inlined items removed

        # Click + Add Component... and verify presets expand
        add_btn = next(c for c in vp_menu.children if c.components.get("text") == "+ Add Component...")
        self.click(add_btn)
        vp_submenu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(vp_submenu)
        sub_texts = [c.components.get("text", "") for c in vp_submenu.children if "text" in c.components]
        self.assertTrue(any("+ Transform / Pos" in t for t in sub_texts))
        self.assertTrue(any("+ Velocity" in t for t in sub_texts))
        self.assertTrue(any("+ Custom Component" in t for t in sub_texts))
        self.send(("key", "ESCAPE", False, False))

        # 2. Hierarchy right-click on row
        row = next(r for r in ed.hierarchy_rows if r.visible and r.relations.get("target") is unit)
        self.send(("click", row.x + 40, row.y + 10, 4, 0))
        h_menu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(h_menu)
        h_texts = [c.components.get("text", "") for c in h_menu.children if "text" in c.components]
        self.assertIn("+ Add Component...", h_texts)
        self.assertNotIn("+ Add Pos (x, y)", h_texts)

    def test_code_editor_path_field_readonly_and_toolbar_hidden(self):
        ed = self.editor
        self.runtime.step(0)
        # Verify path_field is read-only
        self.assertTrue(ed.path_field.components.get("readonly", False))
        # Verify toolbar action buttons are hidden (visible=False)
        self.assertFalse(ed.new_button.components.get("visible", True))
        self.assertFalse(ed.open_button.components.get("visible", True))
        self.assertFalse(ed.save_button.components.get("visible", True))
        self.assertFalse(ed.attach_button.components.get("visible", True))

    def test_code_editor_context_menu_actions(self):
        ed = self.editor
        self.runtime.step(0)
        # Right click in the code editor area
        self.send(("click", ed.code.x + 40, ed.code.y + 40, 4, 0))
        menu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(menu)
        texts = [c.components.get("text", "") for c in menu.children if "text" in c.components]
        self.assertTrue(any("Save / reload" in t for t in texts))
        self.assertTrue(any("Rename" in t for t in texts))
        self.assertTrue(any("Open file..." in t for t in texts))
        self.assertTrue(any("+ New system script..." in t for t in texts))
        self.assertIn("Select All", texts)
        self.assertIn("Copy", texts)
        self.assertIn("Cut", texts)
        self.assertIn("Paste", texts)
        self.send(("key", "ESCAPE", False, False))

    def test_code_editor_rename_file_updates_disk_systems_and_references(self):
        ed = self.editor
        self.runtime.step(0)
        # Ensure render.py is open and attached to Game
        self.assertIn("render", ed.game.systems)
        self.assertEqual(ed.path_field.buffer.text, "render.py")
        old_file = ed.project / "render.py"
        self.assertTrue(old_file.exists())

        # Perform rename via rename_file
        new_path = ed.rename_file("custom_render.py")
        self.runtime.step(0)

        # 1. File on disk renamed
        self.assertFalse(old_file.exists())
        self.assertTrue(new_path.exists())
        self.assertEqual(new_path.name, "custom_render.py")

        # 2. System attachments on entities updated
        self.assertNotIn("render", ed.game.systems)
        self.assertIn("custom_render", ed.game.systems)
        self.assertTrue(ed.game.systems["custom_render"].running)

        # 3. Code editor state updated
        self.assertEqual(ed.path_field.buffer.text, "custom_render.py")
        self.assertEqual(ed.code.system_name, "custom_render")

        # 4. Project data saved with new system name
        import json
        data = json.loads((ed.project / "project.json").read_text(encoding="utf-8"))
        game_entry = next(e for e in data["entities"] if e.get("components", {}).get("name") == "Game")
        self.assertIn("custom_render", game_entry.get("systems", {}))

    def test_code_editor_rename_prompt_and_escape_cancel(self):
        ed = self.editor
        self.runtime.step(0)
        orig_name = ed.path_field.buffer.text
        # Trigger rename prompt
        ed.prompt_rename_file()
        self.assertFalse(ed.path_field.components.get("readonly", True))
        self.assertEqual(self.runtime.entities[0].components["ui"].focused, ed.path_field)

        # Press Escape to cancel
        self.send(("key", "ESCAPE", False, False))
        self.runtime.step(0)
        self.assertTrue(ed.path_field.components.get("readonly", False))
        self.assertEqual(ed.path_field.buffer.text, orig_name)

    def test_f3_key_toggles_spatial_debug_grid(self):
        ed = self.editor
        self.runtime.step(0)
        self.assertFalse(ed.app.components.get("show_spatial_debug", False))

        # Press F3 to enable
        self.send(("key", "F3", False, False))
        self.runtime.step(0)
        self.assertTrue(ed.app.components.get("show_spatial_debug", False))
        self.assertTrue(ed.game.components.get("show_spatial_debug", False))
        self.assertIn("Spatial debug partition: ON", ed.app.status)

        # Press F3 again to disable
        self.send(("key", "F3", False, False))
        self.runtime.step(0)
        self.assertFalse(ed.app.components.get("show_spatial_debug", True))
        self.assertFalse(ed.game.components.get("show_spatial_debug", True))
        self.assertIn("Spatial debug partition: OFF", ed.app.status)

    def test_interactive_panel_docking_and_drop_overlay(self):
        ed = self.editor
        self.runtime.step(0)

        # 1. Initiating drag on Inspector panel header
        insp_x = ed.inspector.x + 20
        insp_y = ed.inspector.y + 10
        self.send(("drag", insp_x, insp_y, 1, 0, 5, 5))
        dock_drag = ed.app.components.get("dock_drag")
        self.assertIsNotNone(dock_drag)
        self.assertEqual(dock_drag.get("panel"), "inspector")

        # 2. Moving drag over the Viewport panel center
        vp_cx = ed.viewport.x + ed.viewport.w // 2
        vp_cy = ed.viewport.y + ed.viewport.h // 2
        self.send(("drag", vp_cx, vp_cy, 1, 0, 0, 0))
        dock_drag = ed.app.components.get("dock_drag")
        self.assertIsNotNone(dock_drag.get("target_group"))
        self.assertEqual(dock_drag.get("zone"), "center")
        self.assertIsNotNone(dock_drag.get("preview_rect"))

        # 3. Drawing while dock_drag is active renders preview rect and guide boxes
        self.graphics.rectangles.clear()
        ed.ui.draw()
        guide_rects = [kw for _, kw in self.graphics.rectangles if kw.get("key") and isinstance(kw["key"], tuple) and kw["key"][0] == "dock_gbg"]
        self.assertEqual(len(guide_rects), 5)  # center, left, right, top, bottom guide boxes

        # 4. Moving drag to right side of viewport
        vp_rx = ed.viewport.x + ed.viewport.w - 15
        self.send(("drag", vp_rx, vp_cy, 1, 0, 0, 0))
        dock_drag = ed.app.components.get("dock_drag")
        self.assertEqual(dock_drag.get("zone"), "right")

        # 5. Releasing mouse drops inspector into right side of viewport
        self.send(("release", vp_rx, vp_cy, 1, 0))
        self.assertIsNone(ed.app.components.get("dock_drag"))

        # Verify layout reflowed: Inspector and Viewport are now docked side by side
        self.runtime.step(0)
        self.assertLess(ed.viewport.x, ed.inspector.x)
        self.assertAlmostEqual(ed.viewport.y, ed.inspector.y, delta=40)
        self.assertIn("Docked Inspector (right)", ed.app.status)

    def test_interactive_panel_docking_as_tab_center(self):
        ed = self.editor
        self.runtime.step(0)

        # Drag Inspector panel header onto Hierarchy center
        insp_x = ed.inspector.x + 20
        insp_y = ed.inspector.y + 10
        self.send(("drag", insp_x, insp_y, 1, 0, 5, 5))

        hier_cx = ed.hierarchy.x + ed.hierarchy.w // 2
        hier_cy = ed.hierarchy.y + ed.hierarchy.h // 2
        self.send(("drag", hier_cx, hier_cy, 1, 0, 0, 0))

        dock_drag = ed.app.components.get("dock_drag")
        self.assertIsNotNone(dock_drag)
        self.assertEqual(dock_drag.get("zone"), "center")

        # Drop into center to create tab
        self.send(("release", hier_cx, hier_cy, 1, 0))
        self.assertIsNone(ed.app.components.get("dock_drag"))

        # Verify Inspector is now in the tab group with hierarchy
        group = ed.dock_tree.find_tab_group_with_panel("hierarchy")
        self.assertIn("inspector", group.panels)
        self.assertEqual(group.active_panel, "inspector")
        self.assertIn("Docked Inspector (center)", ed.app.status)

    def test_tab_strip_renders_for_multi_panel_group(self):
        """Req 1: Verify tabs are clearly visible and switchable when panels are grouped into one spot."""
        ed = self.editor

        # Tab Inspector into Viewport
        success = ed.dock_tree.dock_panel("inspector", "viewport", "center")
        self.assertTrue(success)
        ed.app.systems["app"].namespace["layout"]()

        # Check tab buttons rendered for the group
        visible_tabs = [b for b in ed.dock_tab_buttons if b.components.get("visible", False)]
        self.assertGreaterEqual(len(visible_tabs), 2)
        tab_texts = [b.text for b in visible_tabs]
        self.assertIn("VIEWPORT", tab_texts)
        self.assertIn("INSPECTOR", tab_texts)

        # Inspector was just docked so it is active
        self.assertTrue(ed.inspector.components.get("visible", False))
        self.assertFalse(ed.viewport.components.get("visible", False))

        # Click the Viewport tab button
        vp_tab = next(b for b in visible_tabs if b.text == "VIEWPORT")
        vp_tab.action()

        # Now Viewport is active and Inspector is inactive
        self.assertTrue(ed.viewport.components.get("visible", False))
        self.assertFalse(ed.inspector.components.get("visible", False))

    def test_close_panel_removes_panel_and_expands_sibling(self):
        """Req 2: Closing a panel expands remaining panels and removes the splitter."""
        ed = self.editor
        orig_code_h = ed.code_panel.h

        # Click close button on Viewport
        self.assertTrue(ed.close_viewport_btn.components.get("visible", False))
        ed.close_viewport_btn.action()

        # Viewport is now closed and not in layout
        self.assertFalse(ed.viewport.components.get("visible", False))
        self.assertIsNone(ed.dock_tree.find_tab_group_with_panel("viewport"))

        # code_panel expanded into the space left by viewport
        self.assertGreater(ed.code_panel.h, orig_code_h + 100)

        # Splitter between viewport and code_panel was pruned and is hidden
        self.assertFalse(ed.code_splitter.components.get("visible", False))

    def test_view_menu_toggles_and_restores_panels(self):
        """Req 3: Classic top menu buttons exist, close minimizes, and View menu restores to default."""
        ed = self.editor

        # Top menu buttons exist and are visible
        self.assertTrue(ed.menu_file_btn.components.get("visible", False))
        self.assertTrue(ed.menu_edit_btn.components.get("visible", False))
        self.assertTrue(ed.menu_view_btn.components.get("visible", False))

        # Close Inspector via close button
        orig_hier_h = ed.hierarchy.h
        ed.close_inspector_btn.action()
        self.assertFalse(ed.inspector.components.get("visible", False))
        self.assertFalse(ed.close_inspector_btn.components.get("visible", False))

        # Hierarchy expanded to fill left column and splitter is hidden
        self.assertGreater(ed.hierarchy.h, orig_hier_h + 100)
        self.assertFalse(ed.hierarchy_splitter.components.get("visible", False))

        # Restore Inspector from View menu
        ed.app.systems["app"].namespace["toggle_panel_view"]("inspector")

        # Inspector is restored and visible
        self.assertTrue(ed.inspector.components.get("visible", False))
        self.assertTrue(ed.close_inspector_btn.components.get("visible", False))
        self.assertTrue(ed.hierarchy_splitter.components.get("visible", False))
        # Hierarchy returned to its upper half and inspector is below it
        self.assertLess(ed.hierarchy.h, orig_hier_h + 50)
        self.assertGreater(ed.inspector.y, ed.hierarchy.y)
