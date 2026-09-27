"""Tests for LittleBigEngine Asset Registry, File Explorer, and Inline GUI Pills."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from uuid import UUID

from lbe.assets import AssetRef, AssetRegistry, ASSET_ICONS
from lbe.desktop import Input
from lbe.project import load_project, save_project, template_path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from test_scene import RecordingGraphics


class AssetSystemTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.project_path = Path(self.directory.name)

        # Create sample project files
        self.img_dir = self.project_path / "textures"
        self.img_dir.mkdir(parents=True, exist_ok=True)
        self.player_img = self.img_dir / "player.png"
        self.player_img.write_bytes(b"\x89PNG\r\n\x1a\n")

        self.sound_dir = self.project_path / "audio"
        self.sound_dir.mkdir(parents=True, exist_ok=True)
        self.jump_snd = self.sound_dir / "jump.wav"
        self.jump_snd.write_bytes(b"RIFF....WAVE")

        self.enemy_script = self.project_path / "enemy.py"
        self.enemy_script.write_text("def update(dt):\n    pass\n", encoding="utf-8")

        self.input = Input()
        self.graphics = RecordingGraphics()
        self.clipboard = ""
        self.window = SimpleNamespace(width=1440, height=900,
                                      set_clipboard_text=lambda text: setattr(self, "clipboard", text),
                                      get_clipboard_text=lambda: self.clipboard)
        self.runtime = load_project(self.window, self.graphics, self.input, self.project_path, template=template_path("editor"))
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
        self.send(("click", entity.x + entity.w / 2, entity.y + entity.h / 2, 1, 0))

    def test_asset_registry_scan_lookup_and_persistence(self):
        """AssetRegistry registers project files, maps UUIDs, and roundtrips in project.json."""
        reg = getattr(self.runtime.assets, "registry", None)
        self.assertIsNotNone(reg)

        # Check scanned files
        player_id = reg.get_id(self.player_img)
        self.assertIsNotNone(player_id)
        entry = reg.get(player_id)
        self.assertEqual(entry["name"], "player.png")
        self.assertEqual(entry["type"], "image")
        self.assertEqual(entry["path"], "textures/player.png")

        jump_id = reg.get_id(self.jump_snd)
        self.assertIsNotNone(jump_id)
        self.assertEqual(reg.get(jump_id)["type"], "audio")

        enemy_id = reg.get_id(self.enemy_script)
        self.assertIsNotNone(enemy_id)
        self.assertEqual(reg.get(enemy_id)["type"], "system")

        # Save and reload project; UUIDs must remain stable
        self.editor.save_editor_project()
        new_runtime = load_project(self.window, self.graphics, self.input, self.project_path, template=template_path("editor"))
        self.addCleanup(new_runtime.close)
        new_reg = new_runtime.assets.registry
        self.assertEqual(new_reg.get_id(self.player_img), player_id)
        self.assertEqual(new_reg.get_id(self.jump_snd), jump_id)
        self.assertEqual(new_reg.get_id(self.enemy_script), enemy_id)

    def test_file_explorer_tabs_and_navigation(self):
        """Switch between Hierarchy and Project Files using tab buttons and F2."""
        ed = self.editor

        # Default tab is hierarchy
        self.assertEqual(getattr(ed, "active_left_tab", "hierarchy"), "hierarchy")
        self.assertTrue(ed.hierarchy.visible)
        self.assertFalse(ed.file_explorer.visible)

        # Click TabFiles
        self.click(ed.tab_files)
        self.assertEqual(ed.active_left_tab, "files")
        self.assertFalse(ed.hierarchy.visible)
        self.assertTrue(ed.file_explorer.visible)

        # F2 toggles back to hierarchy
        self.send(("key", "F2", False, False))
        self.assertEqual(ed.active_left_tab, "hierarchy")
        self.assertTrue(ed.hierarchy.visible)
        self.assertFalse(ed.file_explorer.visible)

        # F2 toggles back to files
        self.send(("key", "F2", False, False))
        self.assertEqual(ed.active_left_tab, "files")
        self.assertTrue(ed.file_explorer.visible)

    def test_drag_asset_to_code_editor_renders_inline_pill(self):
        """Dragging an asset into the Code Editor inserts a UUID token and renders an inline GUI pill."""
        ed = self.editor
        reg = self.runtime.assets.registry
        player_id = reg.get_id(self.player_img)

        # Drag player.png asset
        drag_data = {
            "id": player_id,
            "name": "player.png",
            "path": "textures/player.png",
            "type": "image",
            "icon": "🖼️",
        }
        ed.app.components["asset_drag"] = drag_data

        # Drop onto Code Editor
        drop_event = ("release", ed.code.x + 50, ed.code.y + 50, 0, 0)
        self.editor.app.components["on_asset_drop"](drag_data, drop_event)

        # Token inserted into buffer
        expected_token = f'asset("{player_id}")'
        self.assertIn(expected_token, ed.code.buffer.text)

        # Step runtime to run _sync_text
        self.runtime.step(0)

        # Find the inline asset pill control
        pills = [c for c in ed.ui.controls() if "asset_pill" in c.tags and c.visible]
        self.assertTrue(len(pills) >= 1)
        pill = pills[0]
        self.assertEqual(pill.components.get("asset_id"), str(player_id))
        self.assertIn("player.png", pill.text)
        self.assertIn("🖼️", pill.text)

    def test_asset_pill_context_menu_actions(self):
        """Right-clicking an inline pill offers Locate, Copy UUID, Replace, and Remove actions."""
        ed = self.editor
        reg = self.runtime.assets.registry
        player_id = reg.get_id(self.player_img)
        jump_id = reg.get_id(self.jump_snd)

        # Insert reference
        ed.code.buffer.text = f'snd = asset("{jump_id}")\n'
        self.runtime.step(0)

        pills = [c for c in ed.ui.controls() if "asset_pill" in c.tags and c.visible]
        self.assertTrue(len(pills) >= 1)
        pill = pills[0]

        # Right-click the pill
        self.send(("click", pill.x + 5, pill.y + 5, 4, 0))
        menu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(menu)

        # Verify Locate in Project Files
        locate_item = next(c for c in menu.children if "Locate" in c.components.get("text", ""))
        self.click(locate_item)
        self.assertEqual(ed.active_left_tab, "files")
        self.assertIn("audio", ed.file_explorer.expanded)

        # Verify Copy Asset UUID
        self.send(("click", pill.x + 5, pill.y + 5, 4, 0))
        menu = ed.app.relations.get("context_menu")
        copy_item = next(c for c in menu.children if "Copy Asset UUID" in c.components.get("text", ""))
        self.click(copy_item)
        self.assertEqual(self.clipboard, str(jump_id))

        # Verify Replace reference
        self.send(("click", pill.x + 5, pill.y + 5, 4, 0))
        menu = ed.app.relations.get("context_menu")
        replace_item = next(c for c in menu.children if "Replace" in c.components.get("text", ""))
        self.click(replace_item)
        picker_menu = ed.app.relations.get("context_menu")
        self.assertIsNotNone(picker_menu)
        player_picker_item = next(c for c in picker_menu.children if "player.png" in c.components.get("text", ""))
        self.click(player_picker_item)
        self.assertIn(f'asset("{player_id}")', ed.code.buffer.text)

        # Verify Remove reference
        self.runtime.step(0)
        new_pill = next(c for c in ed.ui.controls() if "asset_pill" in c.tags and c.visible)
        self.send(("click", new_pill.x + 5, new_pill.y + 5, 4, 0))
        menu = ed.app.relations.get("context_menu")
        remove_item = next(c for c in menu.children if "Remove reference" in c.components.get("text", ""))
        self.click(remove_item)
        self.assertNotIn('asset(', ed.code.buffer.text)

    def test_drag_asset_to_inspector_assigns_asset_ref(self):
        """Dropping an image asset onto the Inspector sets sprite = AssetRef(uuid)."""
        ed = self.editor
        reg = self.runtime.assets.registry
        player_id = reg.get_id(self.player_img)

        hero = self.runtime.create(parent=ed.game, name="Hero")
        self.editor.select(hero)
        self.runtime.step(0)

        drag_data = {
            "id": player_id,
            "name": "player.png",
            "path": "textures/player.png",
            "type": "image",
            "icon": "🖼️",
        }

        # Drop onto Inspector
        drop_event = ("release", ed.inspector.x + 50, ed.inspector.y + 50, 0, 0)
        self.editor.app.components["on_asset_drop"](drag_data, drop_event)

        # Hero has sprite component of type AssetRef
        self.assertIn("sprite", hero.components)
        sprite_val = hero.components["sprite"]
        self.assertIsInstance(sprite_val, AssetRef)
        self.assertEqual(sprite_val.id, player_id)
        self.assertEqual(sprite_val.name, "player.png")

        # Inspector renders it as a chip button with icon + name
        self.runtime.step(0)
        lbl, fld = next((lbl, fld) for (lbl, fld) in ed.component_rows if fld.visible and fld.component_key == "sprite")
        self.assertIn("🖼️", fld.buffer.text)
        self.assertIn("player.png", fld.buffer.text)

    def test_renaming_file_updates_registry_and_pills_without_modifying_script_source(self):
        """Renaming a file on disk updates registry and display pills, keeping source code stable."""
        ed = self.editor
        reg = self.runtime.assets.registry
        player_id = reg.get_id(self.player_img)

        # Code editor references player by UUID
        raw_code = f'sprite = asset("{player_id}")\n'
        ed.code.buffer.text = raw_code
        self.runtime.step(0)

        # Pill displays "player.png"
        pill = next(c for c in ed.ui.controls() if "asset_pill" in c.tags and c.visible)
        self.assertIn("player.png", pill.text)

        # Rename file on disk & in registry
        new_img_path = self.img_dir / "hero_warrior.png"
        self.player_img.rename(new_img_path)
        reg.rename(player_id, new_img_path)

        # Step runtime
        self.runtime.step(0)

        # 1. Source code in buffer is UNCHANGED! (Still references player_id)
        self.assertEqual(ed.code.buffer.text, raw_code)

        # 2. Inline pill automatically reflects the new name!
        updated_pill = next(c for c in ed.ui.controls() if "asset_pill" in c.tags and c.visible)
        self.assertIn("hero_warrior.png", updated_pill.text)
