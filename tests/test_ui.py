import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from lbe import Runtime
from lbe.desktop import Input, Graphics
from lbe.project import load_project, template_path
from lbe.ui import UI, stack, row, column, dock, apply_layout, Layout, parse_box, content_rect
from test_scene import RecordingGraphics


class UITests(unittest.TestCase):
    def setUp(self):
        self.window = SimpleNamespace(width=900, height=700)
        self.graphics = RecordingGraphics()
        self.input = Input()

    def test_resize_handles_require_left_press_before_capture(self):
        runtime = Runtime()
        self.addCleanup(runtime.close)
        root = runtime.create()
        ui = UI(root, self.window, self.graphics, self.input)
        calls = []
        for tag in ('splitter', 'scrollbar_thumb'):
            handle = ui.create(root, tag, tag, x=10, y=10, w=10, h=100,
                               on_drag=lambda control,event: calls.append(control))
            for event in (('scroll',12,12,0,-1), ('click',12,12,2,0)):
                ui.dispatch(event)
                self.assertNotIn('active_drag', root.relations)
                ui.dispatch(('drag',30,20,1,0,18,8))
                self.assertEqual(calls, [])
            ui.dispatch(('click',12,12,1,0))
            self.assertIs(root.relations['active_drag'], handle)
            ui.dispatch(('drag',30,20,1,0,18,8))
            self.assertEqual(calls, [handle])
            ui.dispatch(('release',30,20,1,0))
            runtime.destroy(handle)
            calls.clear()

    def test_unrelated_application_runs_without_editor_services(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = load_project(self.window, self.graphics, self.input, directory,
                                   template=template_path("counter"))
            root = runtime.entities[0]
            runtime.step(0)
            button = next(e for e in root.descendants if e.components.get("name") == "Increment")
            self.input.pending.append(("click", button.x+10, button.y+10, 1, 0))
            runtime.step(0)
            self.assertEqual(root.count, 1)
            self.assertNotIn("editor", runtime.services)
            self.assertNotIn("application_state", root.components)
            self.assertFalse(any(e.components.get("name") in ("Game", "InspectorPanel", "CodeEditorPanel")
                                 for e in runtime.entities))
            notes = next(e for e in root.descendants if "multiline" in e.tags)
            self.input.pending.extend([("click", notes.x+60, notes.y+10, 1, 0),
                                       ("key", "A", True, False), ("text", "Independent app\nSecond line")])
            runtime.step(0)
            self.assertEqual(notes.buffer.text, "Independent app\nSecond line")
            self.assertTrue(any(e.components.get("part") == "cursor" for e in notes.children))
            self.assertTrue(all(not instance.errors for e in runtime.entities for instance in e.systems.values()))
            runtime.close()

    def test_ui_ownership_is_scoped_to_its_entity(self):
        runtime = Runtime()
        first, second = runtime.create(), runtime.create()
        ui = UI(first, self.window, self.graphics, self.input)
        other = UI(second, self.window, self.graphics, Input())
        first.count = second.count = 0
        a = ui.button(first, "A", "A", lambda: setattr(first, "count", first.count+1), x=0, y=0, w=40, h=30)
        other.button(second, "B", "B", lambda: setattr(second, "count", second.count+1), x=0, y=0, w=40, h=30)
        ui.install()
        other.install()
        self.input.pending.append(("click", 10, 10, 1, 0))
        runtime.step(0)
        self.assertEqual((first.count, second.count), (1, 0))
        self.assertEqual(tuple(ui.controls()), (a,))

    def test_hidden_parent_blocks_control_input(self):
        runtime = Runtime()
        root = runtime.create(count=0)
        ui = UI(root, self.window, self.graphics, self.input)
        panel = ui.create(root, "Panel", "panel", x=0, y=0, w=100, h=100, visible=False)
        ui.button(panel, "Button", "Click", lambda: setattr(root, "count", 1), x=0, y=0, w=50, h=30)
        ui.install()
        self.input.pending.append(("click", 10, 10, 1, 0))
        runtime.step(0)
        self.assertEqual(root.count, 0)

    def test_stack_layout_works_with_plain_entities(self):
        runtime = Runtime()
        parent = runtime.create(x=10, y=20)
        a = runtime.create(parent=parent, w=30, h=40)
        b = runtime.create(parent=parent, w=50, h=60)
        stack(parent, (a, b), padding=5, gap=3)
        self.assertEqual((a.x, a.y, b.x, b.y), (15, 25, 15, 68))

    def test_layout_box_and_content_rect(self):
        self.assertEqual(parse_box(10), (10, 10, 10, 10))
        self.assertEqual(parse_box((5, 12)), (5, 12, 5, 12))
        self.assertEqual(parse_box((5,)), (5, 5, 5, 5))
        self.assertEqual(parse_box((5, 10, 15)), (5, 10, 15, 10))
        self.assertEqual(parse_box(()), (0, 0, 0, 0))
        self.assertEqual(parse_box((1, 2, 3, 4)), (1, 2, 3, 4))
        self.assertEqual(parse_box(None, default=8), (8, 8, 8, 8))
        self.assertEqual(parse_box("invalid", default=4), (4, 4, 4, 4))

        runtime = Runtime()
        e = runtime.create(x=100, y=50, w=200, h=100, padding=(5, 10, 15, 20))
        self.assertEqual(content_rect(e), (120, 55, 170, 80))

        # Horizontal flex stack
        p_row = runtime.create(x=0, y=0, w=300, h=50, padding=10, gap=5)
        c_fix = runtime.create(parent=p_row, w=50)
        c_flex = runtime.create(parent=p_row, flex=1)
        stack(p_row, (c_fix, c_flex), axis="x")
        self.assertEqual(c_fix.x, 10)
        self.assertEqual(c_fix.w, 50)
        self.assertEqual(c_flex.x, 65)
        self.assertEqual(c_flex.w, 225)

        # Invalid axis raises ValueError
        with self.assertRaises(ValueError):
            stack(p_row, axis="z")


    def test_stack_with_margins_padding_and_flex(self):
        runtime = Runtime()
        parent = runtime.create(x=0, y=0, w=300, h=400, padding=10, gap=5)
        c1 = runtime.create(parent=parent, h=50, margin=(5, 10, 5, 10))
        c2 = runtime.create(parent=parent, flex=1, margin=(0, 10, 0, 10))
        stack(parent, (c1, c2), axis="y", align="stretch")

        self.assertEqual(c1.y, 15)
        self.assertEqual(c1.x, 20)
        self.assertEqual(c1.w, 260)
        self.assertEqual(c2.h, 315)
        self.assertEqual(c2.y, 75)
        self.assertEqual(c2.w, 260)

    def test_dock_layout_and_reflow(self):
        runtime = Runtime()
        root = runtime.create(x=0, y=0, w=800, h=600, padding=10)
        header = runtime.create(parent=root, dock="top", h=50, margin=0)
        footer = runtime.create(parent=root, dock="bottom", h=40, margin=(5, 0, 5, 0))
        sidebar = runtime.create(parent=root, dock="left", w=200, margin=0)
        content = runtime.create(parent=root, dock="fill", margin=0)
        floating = runtime.create(parent=root, dock="float", x=350, y=250, w=100, h=100)

        dock(root, (header, footer, sidebar, content, floating))

        self.assertEqual((header.x, header.y, header.w, header.h), (10, 10, 780, 50))
        self.assertEqual((footer.x, footer.y, footer.w, footer.h), (10, 545, 780, 40))
        self.assertEqual((sidebar.x, sidebar.y, sidebar.w, sidebar.h), (10, 60, 200, 480))
        self.assertEqual((content.x, content.y, content.w, content.h), (210, 60, 580, 480))
        self.assertEqual((floating.x, floating.y, floating.w, floating.h), (350, 250, 100, 100))

        root.w, root.h = 1000, 800
        dock(root, (header, footer, sidebar, content, floating))
        self.assertEqual((header.x, header.y, header.w, header.h), (10, 10, 980, 50))
        self.assertEqual((content.x, content.y, content.w, content.h), (210, 60, 780, 680))

    def test_apply_layout_and_layout_system(self):
        runtime = Runtime()
        container = runtime.create(x=0, y=0, w=400, h=300, layout="dock", padding=5)
        top_bar = runtime.create(parent=container, dock="top", h=30)
        main_area = runtime.create(parent=container, dock="fill")

        sys = Layout(container)
        sys.update(0)
        self.assertEqual((top_bar.x, top_bar.y, top_bar.w, top_bar.h), (5, 5, 390, 30))
        self.assertEqual((main_area.x, main_area.y, main_area.w, main_area.h), (5, 35, 390, 260))

    def test_existing_project_is_not_populated_with_template_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"app.py"
            path.write_text("entity.answer = 42", encoding="utf-8")
            runtime = load_project(self.window, self.graphics, self.input, directory,
                                   template=template_path("counter"))
            self.assertEqual(runtime.entities[0].answer, 42)
            self.assertEqual({p.name for p in Path(directory).iterdir()}, {"app.py"})
            runtime.close()

    def test_desktop_graphics_dynamic_layer_groups(self):
        try:
            import pyglet
        except ImportError:
            self.skipTest("pyglet is an optional desktop dependency")
        graphics = Graphics(self.window)
        # Test layers that exceed the old fixed 0..7 range and negative layers
        for layer in (-2, 0, 2, 7, 8, 9, 15, 42):
            graphics.rect(10, 10, 40, 20, layer=layer)
            graphics.text("label", 10, 10, layer=layer)
            group = graphics._group(layer)
            self.assertEqual(group.order, layer)
            self.assertIn(layer, graphics._groups)

        # Confirm arbitrary layer lookup via dictionary key also auto-instantiates
        self.assertEqual(graphics._groups[99].order, 99)
        graphics.close()


    def test_modal_panel_blocks_drag_from_reaching_underlying_viewport(self):
        runtime = Runtime()
        root = runtime.create()
        ui = UI(root, self.window, self.graphics, self.input)
        calls = []
        ui.create(root, 'Viewport', 'surface', x=0,y=0,w=400,h=300,layer=0,on_drag=lambda c,e:calls.append(e))
        ui.create(root, 'Overlay', 'panel', x=20,y=20,w=200,h=200,layer=4,modal=True)
        ui.dispatch(('drag', 40, 40, 1, 0, 10, 10))
        self.assertFalse(calls)
        runtime.close()
