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
    def test_source_badges_follow_entry_points_and_edits(self):
        from lbe.assets import asset_icon
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "behavior.py"
            for names, expected in (((), "{·}"), (("run",), "{▶}"),
                    (("update",), "{↻}"), (("draw",), "{◇}"),
                    (("run", "update"), "{▶↻}"), (("run", "draw"), "{▶◇}"),
                    (("update", "draw"), "{↻◇}"), (("run", "update", "draw"), "{*}")):
                path.write_text("raise RuntimeError('never execute')\n" +
                    "".join(f"def {name}(*args):\n    pass\n" for name in names), encoding="utf8")
                self.assertEqual(asset_icon(path), expected)
            path.write_text("def helper():\n    def draw(): pass\n", encoding="utf8")
            self.assertEqual(asset_icon(path), "{·}")
            path.write_text("def run(:", encoding="utf8")
            self.assertEqual(asset_icon(path), "{?}")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.project_path = Path(self.directory.name).resolve()

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
        self.editor = self.runtime.entities[0].items.require_value("application_state")
        self.runtime.step(0)
        self.assert_healthy()

    def assert_healthy(self):
        instance = self.editor.app.items.behaviour("app", kind='system')
        self.assertTrue(instance.running, list(instance.errors))
        self.assertEqual(list(instance.errors), [])

    def send(self, *events, dt=0):
        self.input.pending.extend(events)
        self.runtime.step(dt)
        self.assert_healthy()

    def click(self, entity):
        if hasattr(entity, "items") and not entity.items.get_value("visible", True):
            if callable(getattr(entity, "action", None)):
                try:
                    entity.action()
                except Exception as error:
                    msg = f"{type(error).__name__}: {error}"
                    cb = self.editor.app.items.get_value("on_ui_error")
                    if cb:
                        cb(msg)
                return
            on_click = entity.items.get_value("on_click")
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
        ed.app.items.set_value("asset_drag", drag_data)

        # Drop onto Code Editor
        drop_event = ("release", ed.code.x + 50, ed.code.y + 50, 0, 0)
        self.editor.app.items.require_value("on_asset_drop")(drag_data, drop_event)

        # Token inserted into buffer
        expected_token = f'asset("{player_id}")'
        self.assertIn(expected_token, ed.code.buffer.text)

        # Step runtime to run _sync_text
        self.runtime.step(0)

        # Find the inline asset pill control
        pills = [c for c in ed.ui.controls() if c.items.has_tag("asset_pill") and c.visible]
        self.assertTrue(len(pills) >= 1)
        pill = pills[0]
        self.assertEqual(pill.items.get_value("asset_id"), str(player_id))
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

        pills = [c for c in ed.ui.controls() if c.items.has_tag("asset_pill") and c.visible]
        self.assertTrue(len(pills) >= 1)
        pill = pills[0]

        # Right-click the pill
        self.send(("click", pill.x + 5, pill.y + 5, 4, 0))
        menu = ed.app.items.target("context_menu")
        self.assertIsNotNone(menu)

        # Verify Locate in Project Files
        locate_item = next(c for c in menu.children if "Locate" in c.items.get_value("text", ""))
        self.click(locate_item)
        self.assertEqual(ed.active_left_tab, "files")
        self.assertIn("audio", ed.file_explorer.expanded)

        # Verify Copy Asset UUID
        self.send(("click", pill.x + 5, pill.y + 5, 4, 0))
        menu = ed.app.items.target("context_menu")
        copy_item = next(c for c in menu.children if "Copy Asset UUID" in c.items.get_value("text", ""))
        self.click(copy_item)
        self.assertEqual(self.clipboard, str(jump_id))

        # Verify Replace reference
        self.send(("click", pill.x + 5, pill.y + 5, 4, 0))
        menu = ed.app.items.target("context_menu")
        replace_item = next(c for c in menu.children if "Replace" in c.items.get_value("text", ""))
        self.click(replace_item)
        picker_menu = ed.app.items.target("context_menu")
        self.assertIsNotNone(picker_menu)
        player_picker_item = next(c for c in picker_menu.children if "player.png" in c.items.get_value("text", ""))
        self.click(player_picker_item)
        self.assertIn(f'asset("{player_id}")', ed.code.buffer.text)

        # Verify Remove reference
        self.runtime.step(0)
        new_pill = next(c for c in ed.ui.controls() if c.items.has_tag("asset_pill") and c.visible)
        self.send(("click", new_pill.x + 5, new_pill.y + 5, 4, 0))
        menu = ed.app.items.target("context_menu")
        remove_item = next(c for c in menu.children if "Remove reference" in c.items.get_value("text", ""))
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
        self.editor.app.items.require_value("on_asset_drop")(drag_data, drop_event)

        # Hero has sprite component of type AssetRef
        self.assertIn("sprite", hero.items.value_dict())
        sprite_val = hero.items.require_value("sprite")
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
        pill = next(c for c in ed.ui.controls() if c.items.has_tag("asset_pill") and c.visible)
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
        updated_pill = next(c for c in ed.ui.controls() if c.items.has_tag("asset_pill") and c.visible)
        self.assertIn("hero_warrior.png", updated_pill.text)

    def test_atomic_pill_navigation_and_deletion(self):
        """Arrow keys jump across pills atomically and Backspace/Delete remove whole pill."""
        ed = self.editor
        reg = self.runtime.assets.registry
        player_id = reg.get_id(self.player_img)

        # "x = asset('<id>') + 1"
        token = f'asset("{player_id}")'
        ed.code.buffer.text = f"x = {token} + 1"
        ed.ui.focus(ed.code)
        self.runtime.step(0)

        # Cursor after pill (at 4 + len(token))
        token_start = 4
        token_end = token_start + len(token)
        ed.code.buffer.cursor = ed.code.buffer.anchor = token_end

        # Pressing LEFT jumps completely over the pill to token_start
        self.send(("key", "LEFT", False, False))
        self.assertEqual(ed.code.buffer.cursor, token_start)

        # Pressing RIGHT jumps completely over the pill to token_end
        self.send(("key", "RIGHT", False, False))
        self.assertEqual(ed.code.buffer.cursor, token_end)

        # Pressing BACKSPACE at token_end deletes the entire pill token in one go
        self.send(("key", "BACKSPACE", False, False))
        self.assertEqual(ed.code.buffer.text, "x =  + 1")
        self.assertEqual(ed.code.buffer.cursor, token_start)

        # Reset text and test DELETE from before the pill
        ed.code.buffer.text = f"x = {token} + 1"
        ed.code.buffer.cursor = ed.code.buffer.anchor = token_start
        self.send(("key", "DELETE", False, False))
        self.assertEqual(ed.code.buffer.text, "x =  + 1")
        self.assertEqual(ed.code.buffer.cursor, token_start)

    def test_drag_isolation_and_camera_freeze(self):
        """Active asset_drag freezes viewport panning and prevents row retargeting."""
        ed = self.editor
        reg = self.runtime.assets.registry
        player_id = reg.get_id(self.player_img)

        cam_x_orig = ed.camera.x
        cam_y_orig = ed.camera.y

        # Initiate drag
        drag_data = {
            "id": player_id,
            "name": "player.png",
            "path": "textures/player.png",
            "type": "image",
            "icon": "🖼️",
        }
        ed.app.items.set_value("asset_drag", drag_data)

        # Dragging across viewport does not pan camera
        vp = ed.viewport
        self.send(("drag", vp.x + 100, vp.y + 100, 1, 0, 50, 50))
        self.assertEqual(ed.camera.x, cam_x_orig)
        self.assertEqual(ed.camera.y, cam_y_orig)

        # Clicking viewport while dragging does not change selection
        selected_before = ed.selected()
        self.send(("click", vp.x + 100, vp.y + 100, 1, 0))
        self.assertEqual(ed.selected(), selected_before)

    def test_folder_creation_and_file_moving_with_stable_uuid(self):
        """Folders can be created and files moved between folders while preserving asset UUID."""
        app_ns = self.editor.app.items.behaviour("app", kind='system').namespace
        create_new_folder = app_ns["create_new_folder"]
        move_file_or_folder = app_ns["move_file_or_folder"]
        ed = self.editor
        reg = self.runtime.assets.registry
        player_id = reg.get_id(self.player_img)

        # Create "Game" folder
        create_new_folder(self.project_path)
        game_folder = self.project_path / "New Folder"
        self.assertTrue(game_folder.exists() and game_folder.is_dir())

        # Move player.png into New Folder
        move_file_or_folder(self.player_img, game_folder)
        moved_player = game_folder / "player.png"
        self.assertTrue(moved_player.exists())
        self.assertFalse(self.player_img.exists())

        # UUID is still preserved and points to the new relative path
        self.assertEqual(reg.get_id(moved_player), player_id)
        entry = reg.get(player_id)
        self.assertEqual(entry["path"], "New Folder/player.png")

    def test_inspector_identity_hides_raw_uuid(self):
        """Inspector identity label displays clean Entity: <name> instead of raw UUID."""
        ed = self.editor
        hero = self.runtime.create(parent=ed.game, name="HeroPlayer")
        ed.select(hero)
        self.runtime.step(0)

        # Identity label displays 🔷 Entity: HeroPlayer
        self.assertIn("HeroPlayer", ed.identity_label.text)
        self.assertNotIn("id:", ed.identity_label.text)
        self.assertNotIn(str(hero.id), ed.identity_label.text)

    def test_floating_drag_preview_attached_to_mouse(self):
        """While dragging an asset or entity, a floating pill badge is drawn at mouse coordinates."""
        ed = self.editor
        reg = self.runtime.assets.registry
        player_id = reg.get_id(self.player_img)

        # 1. Asset drag preview
        ed.app.items.set_value("asset_drag", {
            "id": player_id,
            "name": "player.png",
            "path": "textures/player.png",
            "type": "image",
            "icon": "🖼️",
        })
        # Send motion to move cursor
        self.send(("motion", 320, 240, 0))
        self.runtime.step(0)

        # Check graphics for active_drag badge
        bg_matches = [rect for rect in self.graphics.rectangles if rect[1].get("key") == "active_drag_bg"]
        self.assertTrue(len(bg_matches) >= 1)
        x, y = bg_matches[-1][0][:2]
        self.assertEqual(x, 320 + 12)
        self.assertEqual(y, 240 + 12)

        txt_matches = [txt for txt in self.graphics.texts if txt[1].get("key") == "active_drag_txt"]
        self.assertTrue(len(txt_matches) >= 1)
        self.assertIn("player.png", txt_matches[-1][0][0])

        # 2. Entity drag preview
        ed.app.items.remove_value("asset_drag", None)
        hero = self.runtime.create(parent=ed.game, name="DragonBoss")
        ed.app.items.set_value("entity_drag", {
            "id": str(hero.id),
            "name": "DragonBoss",
            "type": "entity",
            "entity": hero,
        })
        self.send(("motion", 450, 350, 0))
        self.runtime.step(0)

        bg_matches2 = [rect for rect in self.graphics.rectangles if rect[1].get("key") == "active_drag_bg"]
        self.assertTrue(len(bg_matches2) >= 1)
        self.assertEqual(bg_matches2[-1][0][:2], (450 + 12, 350 + 12))

        txt_matches2 = [txt for txt in self.graphics.texts if txt[1].get("key") == "active_drag_txt"]
        self.assertTrue(len(txt_matches2) >= 1)
        self.assertIn("DragonBoss", txt_matches2[-1][0][0])
        self.assertIn("🔷", txt_matches2[-1][0][0])

    def test_drag_source_attaches_behaviour_or_edits_exact_uuid_value_row(self):
        ed = self.editor
        uid = self.runtime.assets.registry.get_id(self.enemy_script)
        owner = self.runtime.create(parent=ed.game, name="PlayerTarget", source=None)
        ed.inspect_entity(owner)
        self.runtime.step(0)
        data = dict(id=uid, name="enemy.py", path="enemy.py", type="system", icon="λ")
        ed.app.items.require_value("on_asset_drop")(data, ("release", ed.inspector.x+30, ed.components_title.y+15, 0, 0))
        self.assertIn("enemy", owner.items.behaviour_dict('system'))
        self.assertFalse(owner.items.has_value('enemy'))
        record = owner.items.component('source')
        ed.focus_item(owner, record.id)
        _, field = next((name, field) for name, field in ed.component_rows if field.visible and field.item_id == record.id)
        ed.app.items.require_value("on_asset_drop")(data, ("release", field.x+8, field.y+8, 0, 0))
        self.assertEqual(owner.items.component('source').id, record.id)
        self.assertIsInstance(owner.items.value(record.id), AssetRef)
        self.assertEqual(owner.items.value(record.id).id, uid)
        self.assertIn('enemy', owner.items.behaviour_dict('system'))

    def test_drag_entity_from_hierarchy(self):
        """Dragging entity from hierarchy allows dropping into code editor, inspector, or reparenting."""
        ed = self.editor

        parent_ent = self.runtime.create(parent=ed.game, name="FolderNode")
        child_ent = self.runtime.create(parent=ed.game, name="HeroNode")
        self.runtime.step(0)

        # 1. Dropping entity into Code Editor inserts resolve("<id>") token and renders inline pill
        ent_drag = {
            "id": str(child_ent.id),
            "name": "HeroNode",
            "type": "entity",
            "entity": child_ent,
        }
        drop_code = ("release", ed.code.x + 50, ed.code.y + 50, 0, 0)
        ed.app.items.require_value("on_entity_drop")(ent_drag, drop_code)

        expected_token = f'resolve("{child_ent.id}")'
        self.assertIn(expected_token, ed.code.buffer.text)

        # Step to sync text and render inline pill
        self.runtime.step(0)
        pills = [c for c in ed.ui.controls() if c.items.has_tag("asset_pill") and c.visible]
        self.assertTrue(len(pills) >= 1)
        self.assertIn("HeroNode", pills[0].text)
        self.assertIn("🔷", pills[0].text)

        # 2. Dropping entity into Inspector adds component pointing to the entity
        ed.select(parent_ent)
        self.runtime.step(0)

        drop_insp = ("release", ed.inspector.x + 50, ed.components_title.y + 15, 0, 0)
        ed.app.items.require_value("on_entity_drop")(ent_drag, drop_insp)

        self.assertIn("heronode", parent_ent.items.value_dict())
        self.assertIs(parent_ent.items.require_value("heronode"), child_ent)

        # 3. Dropping entity onto another entity row in Hierarchy reparents it
        # Find row for parent_ent
        row = next(r for r in ed.hierarchy_rows if r.visible and r.items.target("target") is parent_ent)
        drop_hier = ("release", row.x + 20, row.y + 10, 0, 0)
        ed.app.items.require_value("on_entity_drop")(ent_drag, drop_hier)

        self.assertIs(child_ent.parent, parent_ent)

    def test_drop_asset_and_entity_inserts_at_mouse_position(self):
        """Dropping an asset or entity into the code editor inserts it at the mouse position."""
        ed = self.editor

        ed.code.buffer.text = "def start():\n    x = 1\n"
        ed.code.buffer.cursor = ed.code.buffer.anchor = 0
        self.runtime.step(0)

        # Drop asset at line 1, column 8 (after "x = ")
        pitch = ed.code.items.get_value("pitch", 8)
        line_h = ed.code.items.get_value("line_height", 20)
        # line 1 y is code.y + 6 + 1 * line_h + line_h / 2
        drop_x = ed.code.x + 48 + 8 * pitch
        drop_y = ed.code.y + 6 + 1 * line_h + 10

        reg = self.runtime.assets.registry
        enemy_id = reg.get_id(self.enemy_script)
        asset_drag = dict(id=str(enemy_id), name="enemy.py", type="system", path="scripts/enemy.py")

        drop_event = ("release", drop_x, drop_y, 0, 0)
        ed.app.items.require_value("on_asset_drop")(asset_drag, drop_event)

        expected_token = f'asset("{enemy_id}")'
        self.assertIn(f"x = {expected_token}1", ed.code.buffer.text)

    def test_selection_highlight_visibility_and_layering(self):
        """Selection highlights in multiline editor are on layer+1 with SELECTION color and visible."""
        ed = self.editor
        ed.code.buffer.text = "line one\nline two\nline three\n"
        ed.code.buffer.cursor = ed.code.buffer.anchor = 0
        ed.ui.focus(ed.code)
        self.runtime.step(0)

        pitch = ed.code.items.get_value("pitch", 8)
        line_h = ed.code.items.get_value("line_height", 20)

        # 1. Drag selection
        # Click at line 0, col 5
        click_x = ed.code.x + 48 + 5 * pitch
        click_y = ed.code.y + 6 + line_h // 2
        ed.ui.dispatch(("click", click_x, click_y, 1, 0))

        self.assertEqual(ed.code.buffer.cursor, 5)
        self.assertEqual(ed.code.buffer.anchor, 5)

        # Drag to line 1, col 4
        drag_x = ed.code.x + 48 + 4 * pitch
        drag_y = ed.code.y + 6 + line_h + line_h // 2
        ed.ui.dispatch(("drag", drag_x, drag_y, 1, 0, drag_x - click_x, drag_y - click_y))
        ed.ui.dispatch(("release", drag_x, drag_y, 1, 0))

        self.runtime.step(0)

        # Verify selection is established
        self.assertTrue(ed.code.buffer.has_selection)
        self.assertEqual(ed.code.buffer.anchor, 5)
        self.assertEqual(ed.code.buffer.cursor, 13)  # len("line one\n") = 9 + 4 = 13

        # Verify highlight rects are visible and on layer+1
        sel_rects = [c for c in ed.code.children if c.name.startswith("selection:") and c.items.get_value("visible")]
        self.assertTrue(len(sel_rects) >= 2)
        for r in sel_rects:
            self.assertEqual(r.layer, ed.code.layer + 1)
            self.assertEqual(r.color, (45, 85, 135))

        # 2. Shift-click to extend selection
        ed.code.buffer.cursor = ed.code.buffer.anchor = 0
        self.runtime.step(0)

        # Click at col 0
        ed.ui.dispatch(("click", ed.code.x + 48, ed.code.y + 10, 1, 0))
        self.assertEqual(ed.code.buffer.cursor, 0)
        self.assertEqual(ed.code.buffer.anchor, 0)

        # Shift-click at col 8 (modifiers has 1 for MOD_SHIFT)
        shift_click_x = ed.code.x + 48 + 8 * pitch
        shift_click_y = ed.code.y + 10
        ed.ui.dispatch(("click", shift_click_x, shift_click_y, 1, 1))

        self.assertEqual(ed.code.buffer.anchor, 0)
        self.assertEqual(ed.code.buffer.cursor, 8)
        self.assertTrue(ed.code.buffer.has_selection)

        self.runtime.step(0)
        sel_rects = [c for c in ed.code.children if c.name.startswith("selection:") and c.items.get_value("visible")]
        self.assertEqual(len(sel_rects), 1)
        self.assertEqual(sel_rects[0].layer, ed.code.layer + 1)
        self.assertEqual(sel_rects[0].color, (45, 85, 135))

    def test_file_explorer_single_click_selects_double_click_opens(self):
        """Single click selects file in file explorer; double click opens it in code editor."""
        ed = self.editor

        # Locate enemy.py in file explorer
        ed.locate_in_file_explorer("enemy.py")
        self.runtime.step(0)

        # Ensure a base file is open in editor
        ed.code.buffer.text = "# Original file\ndef original():\n    pass\n"
        ed.code.items.set_value("source_path", self.project_path / "original.py")
        ed._saved_source = ("original.py", ed.code.buffer.text)
        self.runtime.step(0)

        # Find enemy.py row in file explorer
        ed.reveal_file(self.enemy_script)
        ed.file_explorer_sync()
        row = next(r for r in ed.file_explorer_rows if r.visible and "enemy.py" in r.items.get_value("text", ""))

        # 1. Single click on enemy.py row
        self.send(("click", row.x + 20, row.y + 10, 1, 0))
        self.runtime.step(0)

        # Selected file in file explorer is updated
        self.assertEqual(ed.file_explorer.items.get_value("selected_file"), "enemy.py")
        # BUT code editor buffer is NOT overwritten (original file still open!)
        self.assertIn("def original():", ed.code.buffer.text)

        # 2. Double click on enemy.py row
        self.send(("click", row.x + 20, row.y + 10, 1, 0, 2))
        self.runtime.step(0)

        # Now enemy.py IS opened in code editor
        self.assertIn("def update(dt):", ed.code.buffer.text)

    def test_drag_system_into_open_system_without_replacing_open_file(self):
        """Dragging a system into an open system in code editor does not replace the open system."""
        ed = self.editor
        reg = self.runtime.assets.registry
        enemy_id = reg.get_id(self.enemy_script)

        # Locate enemy.py in file explorer
        ed.locate_in_file_explorer("enemy.py")
        self.runtime.step(0)

        # Main script open in code editor
        ed.code.buffer.text = "def start():\n    physics_sys = None\n"
        ed.code.buffer.cursor = ed.code.buffer.anchor = len(ed.code.buffer.text)
        self.runtime.step(0)

        # Start dragging enemy.py from File Explorer
        ed.reveal_file(self.enemy_script)
        ed.file_explorer_sync()
        row = next(r for r in ed.file_explorer_rows if r.visible and "enemy.py" in r.items.get_value("text", ""))
        # Mouse press initiates drag on enemy.py
        self.send(("drag", row.x + 20, row.y + 10, 1, 0, 10, 0))
        self.runtime.step(0)

        # Active asset_drag is set for enemy.py
        drag_data = ed.app.items.get_value("asset_drag")
        self.assertIsNotNone(drag_data)
        self.assertEqual(drag_data["name"], "enemy.py")

        # Code editor STILL has main script (not replaced!)
        self.assertIn("def start():", ed.code.buffer.text)

        # Drop onto code editor
        drop_pos = ("release", ed.code.x + 50, ed.code.y + 50, 0, 0)
        ed.app.items.require_value("on_asset_drop")(drag_data, drop_pos)
        self.runtime.step(0)

        # Main script now references enemy.py without having been overwritten!
        self.assertIn("def start():", ed.code.buffer.text)
        self.assertIn(f'asset("{enemy_id}")', ed.code.buffer.text)

    def test_hierarchy_single_click_selects_double_click_inspects(self):
        """Single click on hierarchy row selects entity without inspecting; double click inspects."""
        ed = self.editor

        # Start by inspecting Game
        ed.select(ed.game)
        self.runtime.step(0)
        self.assertEqual(ed.identity_label.text, "◆ Entity: Game")

        # Create two entities
        ent_a = self.runtime.create(parent=ed.game, name="EntityAlpha")
        ent_b = self.runtime.create(parent=ed.game, name="EntityBeta")
        self.runtime.step(0)

        # Inspect EntityAlpha first
        ed.select(ent_a)
        self.runtime.step(0)
        self.assertIn("EntityAlpha", ed.identity_label.text)

        # Find row for EntityBeta
        row_b = next(r for r in ed.hierarchy_rows if r.visible and r.items.target("target") is ent_b)

        # 1. Single click on EntityBeta row
        self.send(("click", row_b.x + 40, row_b.y + 10, 1, 0))
        self.runtime.step(0)

        # Selection relation is updated to EntityBeta (for hierarchy/viewport highlight)
        self.assertIs(ed.app.items.target("selection"), ent_b)
        # BUT Inspector STILL inspects EntityAlpha!
        self.assertIn("EntityAlpha", ed.identity_label.text)

        # 2. Double click on EntityBeta row
        self.send(("click", row_b.x + 40, row_b.y + 10, 1, 0, 2))
        self.runtime.step(0)

        # Now Inspector inspects EntityBeta!
        self.assertIn("EntityBeta", ed.identity_label.text)

    def test_drag_entity_from_hierarchy_into_other_entity_inspector_preserves_inspected(self):
        """Dragging entity from hierarchy into inspector adds component to inspected entity without switching inspector."""
        ed = self.editor

        # Create TargetEntity (inspected) and DraggedEntity (dragged from hierarchy)
        target_ent = self.runtime.create(parent=ed.game, name="TargetEntity")
        dragged_ent = self.runtime.create(parent=ed.game, name="DraggedEntity")
        self.runtime.step(0)

        # Inspect TargetEntity
        ed.select(target_ent)
        self.runtime.step(0)
        self.assertIn("TargetEntity", ed.identity_label.text)

        # Single-click/drag DraggedEntity from Hierarchy
        row_drag = next(r for r in ed.hierarchy_rows if r.visible and r.items.target("target") is dragged_ent)
        self.send(("drag", row_drag.x + 40, row_drag.y + 10, 1, 0, 10, 0))
        self.runtime.step(0)

        # Active entity_drag is set
        ent_drag = ed.app.items.get_value("entity_drag")
        self.assertIsNotNone(ent_drag)
        self.assertEqual(ent_drag["name"], "DraggedEntity")

        # Inspector STILL inspects TargetEntity!
        self.assertIn("TargetEntity", ed.identity_label.text)

        # Drop onto TargetEntity's Inspector components section
        drop_insp = ("release", ed.inspector.x + 50, ed.components_title.y + 15, 0, 0)
        ed.app.items.require_value("on_entity_drop")(ent_drag, drop_insp)
        self.runtime.step(0)

        # TargetEntity has component pointing to DraggedEntity
        self.assertIn("draggedentity", target_ent.items.value_dict())
        self.assertIs(target_ent.items.require_value("draggedentity"), dragged_ent)
        # Inspector remains on TargetEntity showing the new component
        self.assertIn("TargetEntity", ed.identity_label.text)


