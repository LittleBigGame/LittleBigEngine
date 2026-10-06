import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path

from lbe.desktop import Input
from lbe.launcher import create_launcher_runtime
from lbe.ui import UI


class MockGraphics:
    def char_width(self, size=10):
        return 8.0

    def line_height(self, size=10):
        return 20.0


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base_dir = Path(self.directory.name).resolve()
        self.input = Input()
        self.graphics = MockGraphics()
        self.window = SimpleNamespace(width=1440, height=900)
        self.selected_project = None
        self.selected_template = None

    def on_select(self, project_path, template=None):
        self.selected_project = project_path
        self.selected_template = template

    def test_launcher_runtime_initialization_and_creation(self):
        runtime = create_launcher_runtime(self.window, self.graphics, self.input, self.on_select)
        self.addCleanup(runtime.close)
        
        root = runtime.entities[0]
        self.assertEqual(root.name, "ProjectManager")
        
        # Step layout system
        runtime.step(0)
        
        container = next((e for e in root.descendants if e.components.get("name") == "Container"), None)
        self.assertIsNotNone(container)
        
        items_container = next((e for e in root.descendants if e.components.get("name") == "ItemsContainer"), None)
        self.assertIsNotNone(items_container)
        
        action_row = next((e for e in root.descendants if e.components.get("name") == "ActionRow"), None)
        self.assertIsNotNone(action_row)

    def test_lbe_project_folder_creation(self):
        runtime = create_launcher_runtime(self.window, self.graphics, self.input, self.on_select)
        self.addCleanup(runtime.close)
        runtime.step(0)

        root = runtime.entities[0]
        btn_create = next(e for e in root.descendants if e.components.get("name") == "BtnCreate")
        name_field = next(e for e in root.descendants if e.components.get("name") == "NameField")
        
        # Step 1: Set project name and click + New Project (.lbe)
        name_field.buffer.text = "test_game"
        btn_create.action()
        runtime.step(0)
        
        # Step 2: Pick default LBE v1 Editor template
        btn_default = next(e for e in root.descendants if e.components.get("name") == "BtnDefaultEditor")
        btn_default.action()
        
        self.assertIsNotNone(self.selected_project)
        self.assertTrue(str(self.selected_project).endswith("test_game.lbe"))
        from lbe.project import template_path
        self.assertEqual(self.selected_template, template_path("editor"))

    def test_lbe_folder_recognition_and_opening(self):
        # Create a sample .lbe project folder in temp directory
        lbe_dir = self.base_dir / "my_existing_game.lbe"
        lbe_dir.mkdir(parents=True, exist_ok=True)
        (lbe_dir / "app.py").write_text("# app", encoding="utf-8")

        runtime_obj = create_launcher_runtime(self.window, self.graphics, self.input, self.on_select)
        self.addCleanup(runtime_obj.close)
        root = runtime_obj.entities[0]
        root.components["browser_state"].current_dir = self.base_dir
        runtime_obj.step(0)

        open_btn = next((e for e in root.descendants if e.components.get("name") == "Btn_my_existing_game.lbe"), None)
        self.assertIsNotNone(open_btn)
        
        # Click the Open Project button
        open_btn.action()
        self.assertEqual(self.selected_project, lbe_dir)
        self.assertIsNone(self.selected_template)

    def test_create_folder_delete_and_rename(self):
        runtime_obj = create_launcher_runtime(self.window, self.graphics, self.input, self.on_select)
        self.addCleanup(runtime_obj.close)
        root = runtime_obj.entities[0]
        root.components["browser_state"].current_dir = self.base_dir
        runtime_obj.step(0)

        name_field = next(e for e in root.descendants if e.components.get("name") == "NameField")
        btn_folder = next(e for e in root.descendants if e.components.get("name") == "BtnFolder")

        # Create folder
        name_field.buffer.text = "sub_folder"
        btn_folder.action()
        runtime_obj.step(0)

        created_dir = self.base_dir / "sub_folder"
        self.assertTrue(created_dir.exists())
        self.assertTrue(created_dir.is_dir())

        # Rename folder
        name_field.buffer.text = "renamed_folder"
        ren_btn = next(e for e in root.descendants if e.components.get("name") == "Ren_sub_folder")
        ren_btn.action()
        runtime_obj.step(0)

        renamed_dir = self.base_dir / "renamed_folder"
        self.assertFalse(created_dir.exists())
        self.assertTrue(renamed_dir.exists())

        # Delete folder
        del_btn = next(e for e in root.descendants if e.components.get("name") == "Del_renamed_folder")
        del_btn.action()
        runtime_obj.step(0)

        self.assertFalse(renamed_dir.exists())

    def test_project_contents_are_recognized_without_lbe_suffix(self):
        for name, filename in (('saved_scene', 'project.json'), ('script_app', 'app.py')):
            directory = self.base_dir / name
            directory.mkdir()
            (directory / filename).write_text('{}' if filename.endswith('.json') else '# app', encoding='utf-8')
        (self.base_dir / 'ordinary_folder').mkdir()
        runtime = create_launcher_runtime(self.window, self.graphics, self.input, self.on_select)
        self.addCleanup(runtime.close)
        root = runtime.entities[0]
        root.browser_state.current_dir = self.base_dir
        runtime.step(0)
        for name in ('saved_scene', 'script_app'):
            button = next(e for e in root.descendants if e.name == f'Btn_{name}')
            self.assertIn('LBE Project', button.text)
            self.assertNotIn('Legacy', button.text)
            button.action()
            self.assertEqual(self.selected_project, self.base_dir / name)
            self.assertIsNone(self.selected_template)
        folder = next(e for e in root.descendants if e.name == 'Btn_ordinary_folder')
        folder.action()
        self.assertEqual(root.browser_state.current_dir, self.base_dir / 'ordinary_folder')

    def test_custom_base_editor_template_selection(self):
        # Create a custom base template folder
        custom_tpl = self.base_dir / "my_custom_editor.lbe"
        custom_tpl.mkdir(parents=True, exist_ok=True)
        (custom_tpl / "app.py").write_text("# custom app", encoding="utf-8")

        runtime_obj = create_launcher_runtime(self.window, self.graphics, self.input, self.on_select)
        self.addCleanup(runtime_obj.close)
        root = runtime_obj.entities[0]
        runtime_obj.step(0)

        # Step 1: Click New Project to enter Step 2 Template Picker View
        name_field = next(e for e in root.descendants if e.components.get("name") == "NameField")
        btn_create = next(e for e in root.descendants if e.components.get("name") == "BtnCreate")
        name_field.buffer.text = "game_from_custom_tpl"
        btn_create.action()
        
        # In Step 2, navigate browser state to base_dir containing custom_tpl
        root.components["browser_state"].current_dir = self.base_dir
        root.components["browser_state"].last_dir = None
        runtime_obj.step(0)

        # Step 2: Select custom template row from browser
        tpl_row_btn = next(e for e in root.descendants if e.components.get("name") == "Btn_my_custom_editor.lbe")
        tpl_row_btn.action()

        self.assertIsNotNone(self.selected_project)
        self.assertEqual(self.selected_template, custom_tpl)


if __name__ == "__main__":
    unittest.main()
