import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from lbe import Component, InheritedComponent, Tag, Relation, SystemDefinition
from lbe.desktop import Input
from lbe.project import load_project, template_path
from lbe.text import TextBuffer
from test_scene import RecordingGraphics


class KernelEditorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(patch.stopall)
        patch('lbe.user_state.save_last_project').start()
        self.clipboard = ''
        self.input = Input()
        self.window = SimpleNamespace(width=1440, height=900,
            set_clipboard_text=lambda text: setattr(self, 'clipboard', text),
            get_clipboard_text=lambda: self.clipboard)
        self.graphics = RecordingGraphics()
        self.runtime = load_project(self.window, self.graphics, self.input, self.directory.name, template=template_path('editor'))
        self.addCleanup(lambda: self.runtime.close())
        self.editor = self.runtime.entities[0].items.require_value('application_state')
        self.runtime.step(0)

    def create_demo(self):
        app = self.editor.app.items.behaviour('app', kind='system').namespace
        action = next(a for a in app['context_actions'](self.editor.game) if a and a['label'] == 'Create walk-and-shoot demo')
        return action['run'](self.editor.game)

    def test_inspector_lists_actual_items_in_canonical_uuid_order(self):
        target = self.runtime.create(name='Typed', items=(Component('x', 2), Tag('player')))
        target.items.connect('friend', self.editor.game)
        behaviour = target.items.attach_system('movement', SystemDefinition('def update(dt): pass'))
        self.editor.inspect_entity(target)
        self.runtime.step(0)
        rows = [(name, data) for name, data in self.editor.component_rows if data.visible]
        self.assertEqual([data.item_id for _, data in rows], list(target.items))
        self.assertEqual([name.buffer.text for name, _ in rows], [item.name for item in target.items.values()])
        self.assertIn('ITEMS', self.editor.components_title.text)
        self.assertFalse(self.editor.system_label.visible)
        self.assertFalse(self.editor.links_header.visible)
        badges = [b for b in self.editor.item_type_buttons if b.visible]
        self.assertTrue(any('Tag' in b.text and '#' in b.text for b in badges))
        self.assertTrue(any('System' in b.text and 'λ' in b.text for b in badges))
        system_field = next(data for _, data in rows if data.item_id == behaviour.id)
        self.assertTrue(system_field.readonly)

    def test_inspector_tag_pill_renames_actual_uuid_item(self):
        target = self.runtime.create(items=(Tag('player'),))
        self.editor.inspect_entity(target)
        self.runtime.step(0)
        item = target.items.named(Tag, 'player')
        name = next(name for name, data in self.editor.component_rows if data.visible and data.item_id == item.id)
        name.buffer = TextBuffer('hero')
        name.on_commit()
        self.assertEqual(target[item.id].name, 'hero')
        self.assertEqual(target.items.named(Tag, 'hero').id, item.id)

    def test_add_menu_creates_native_tag_and_relationship(self):
        self.editor.inspect_entity(self.editor.game.children[0])
        self.editor.open_add_component_menu()
        menu = self.editor.app.items.require_target('context_menu')
        action = next(c for c in menu.children if c.items.get_value('text') == '# Tag')
        self.editor.ui.dispatch(('click', action.x+4, action.y+4, 1))
        owner = self.editor.inspected()
        tag = owner.items.named(Tag, 'tag')
        self.assertEqual(owner[tag.id].name, 'tag')
        self.assertTrue(any(name.visible and name.item_id == tag.id for name, _ in self.editor.component_rows))

    def test_inspector_uuid_value_edit_preserves_inheritance_and_undo(self):
        source = self.runtime.create(speed=6.0)
        target = self.runtime.create()
        original = target.items.inherit_value('speed', source.items.component('speed').id)
        self.editor.inspect_entity(target)
        self.runtime.step(0)
        field = next(data for _, data in self.editor.component_rows if data.visible and data.item_id == original.id)
        field.buffer = TextBuffer('9.0')
        field.on_commit()
        self.assertEqual(target.items.value(original.id), 9.0)
        self.assertEqual(source.items.require_value('speed'), 6.0)
        self.editor.files.history.undo()
        self.assertEqual(target[original.id], original)

    def test_inspector_retains_missing_relationship_as_visible_item(self):
        from uuid import uuid4
        target = self.runtime.create()
        record = Relation('missing', uuid4())
        target.items._put(record)
        self.editor.inspect_entity(target)
        self.runtime.step(0)
        field = next(data for _, data in self.editor.component_rows if data.visible and data.item_id == record.id)
        self.assertIn('Missing Entity', field.buffer.text)
        self.assertIs(target[record.id], record)

    def test_custom_typed_data_edits_same_uuid_without_core_special_case(self):
        from dataclasses import dataclass, field
        from uuid import uuid4
        @dataclass(frozen=True)
        class Inventory:
            name: str
            contents: tuple
            capacity: int
            id: object = field(default_factory=uuid4)
        original = Inventory('bag', ('key',), 4)
        target = self.runtime.create(items=(original,))
        self.editor.inspect_entity(target)
        self.runtime.step(0)
        field_control = next(data for _, data in self.editor.component_rows if data.visible and data.item_id == original.id)
        field_control.buffer = TextBuffer("{'contents': ('key', 'apple'), 'capacity': 5}")
        field_control.on_commit()
        self.assertIsInstance(target[original.id], Inventory)
        self.assertEqual(target[original.id].contents, ('key', 'apple'))
        self.assertEqual(target[original.id].capacity, 5)
        self.editor.files.history.undo()
        self.assertEqual(target[original.id], original)

    def test_gui_demo_moves_shoots_expires_and_reopens_with_identity(self):
        player = self.create_demo()
        uid = player.items.component('speed').id
        self.assertIsInstance(player[uid], InheritedComponent)
        self.assertNotIn('x', next(e for e in self.editor.game.children if e.items.has_tag('blueprint')).items.value_dict())
        self.input.press('D')
        self.input.press('SPACE')
        self.runtime.step(0.1)
        self.assertAlmostEqual(player.x, 0.6)
        bullets = tuple(self.editor.game.query(tags=('bullet',)))
        self.assertEqual(len(bullets), 1)
        self.assertTrue(bullets[0].items.behaviour_dict('script'))
        self.input.release('D')
        self.input.release('SPACE')
        self.runtime.step(1.3)
        self.assertFalse(tuple(self.editor.game.query(tags=('bullet',))))
        self.editor.save_editor_project()
        self.runtime.close()
        self.runtime = load_project(self.window, self.graphics, self.input, self.directory.name)
        self.editor = self.runtime.entities[0].items.require_value('application_state')
        restored = self.runtime.resolve(player.id)
        self.assertEqual(restored.items.component('speed').id, uid)
        self.assertTrue(self.editor.game.items.behaviour('walk_shoot', kind='system').running)

    def test_component_reference_menu_inheritance_edit_undo_and_reset(self):
        app = self.editor.app.items.behaviour('app', kind='system').namespace
        source = self.runtime.create(parent=self.editor.game, name='Source', speed=6.0)
        target = self.runtime.create(parent=self.editor.game, name='Target')
        actions = app['context_actions']({'entity': source, 'component': 'speed'})
        copy = next(a for a in actions if a and a['label'].startswith('Copy Component reference'))
        copy['run'](None)
        self.editor.select(target)
        self.editor.inherit_copied_component(target)
        item = target.items.component('speed')
        self.assertIsInstance(item, InheritedComponent)
        self.assertEqual(item.source, source.items.component('speed').id)
        self.runtime.step(0)
        field = next(f for _, f in self.editor.component_rows if f.visible and f.component_key == 'speed')
        self.assertEqual(field.provenance, 'inherited')
        field.buffer = TextBuffer('9.0')
        self.editor.commit_component(field)
        self.assertEqual(target.speed, 9.0)
        self.assertEqual(source.speed, 6.0)
        self.editor.files.history.undo()
        self.assertEqual(target.items.component('speed').patch, ())
        source.speed = 7.0
        self.assertEqual(target.speed, 7.0)
        target.speed = 12.0
        self.editor.reset_component_patch(target, 'speed')
        self.assertEqual(target.speed, 7.0)

    def test_typed_pills_are_atomic_and_missing_references_are_visible(self):
        source = self.runtime.create(parent=self.editor.game, name='Referenced', x=2)
        code = self.editor.code
        token = f'<|Component:{source.items.component("x").id}|>'
        code.buffer = TextBuffer('value = ' + token)
        self.editor.ui.focus(code)
        self.runtime.step(0)
        pills = [e for e in code.children if e.items.has_tag('asset_pill') and e.visible]
        self.assertEqual(len(pills), 1)
        self.assertIn('Component: x', pills[0].text)
        code.buffer.cursor = code.buffer.anchor = len(code.buffer.text)
        self.input.pending.append(('key', 'BACKSPACE', False, False))
        self.runtime.step(0)
        self.assertEqual(code.buffer.text, 'value = ')
        code.buffer = TextBuffer('value = ' + token)
        del source.x
        self.runtime.step(0)
        pill = next(e for e in code.children if e.items.has_tag('asset_pill') and e.visible)
        self.assertIn('Missing Component', pill.text)

    def test_inspector_rename_and_failed_save_preserve_typed_identity(self):
        source = self.runtime.create(parent=self.editor.game, speed=6.0)
        target = self.runtime.create(parent=self.editor.game)
        original = target.items.inherit_value('speed', source.items.component('speed').id)
        handle = self.runtime.linker.handle(original.id)
        self.editor.select(target)
        self.editor.add_name.items.set_value('renaming_key', 'speed')
        self.editor.add_name.buffer = TextBuffer('movement_speed')
        self.editor.add_value.buffer = TextBuffer('9.0')
        with patch.object(self.editor, 'save_editor_project', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.editor.add_component()
        self.assertIs(target.items[original.id], original)
        self.assertIs(self.runtime.linker.resolve_handle(handle), original)
        self.assertEqual(target.items.value(original.id), 6.0)
        self.assertFalse(target.items.has_value('movement_speed'))

        self.editor.add_name.items.set_value('renaming_key', 'speed')
        self.editor.add_name.buffer = TextBuffer('movement_speed')
        self.editor.add_value.buffer = TextBuffer('9.0')
        self.editor.add_component()
        renamed = target.items.component('movement_speed')
        self.assertEqual(renamed.id, original.id)
        self.assertIsInstance(renamed, InheritedComponent)
        self.assertEqual(renamed.source, original.source)
        self.assertEqual(target.items.value(original.id), 9.0)
        self.assertEqual(source.items.require_value('speed'), 6.0)
        self.assertIs(self.runtime.linker.resolve_handle(handle), renamed)

    def test_inspector_tag_rename_preserves_uuid(self):
        target = self.runtime.create(parent=self.editor.game, tags=('player', 'visible'))
        original = target.items.named(Tag, 'player')
        handle = self.runtime.linker.handle(original.id)
        self.editor.select(target)
        self.editor.tags_field.items.set_value('renaming_tag', 'player')
        self.editor.tags_field.buffer = TextBuffer('hero, visible')
        self.editor.commit_tags()
        renamed = target.items.named(Tag, 'hero')
        self.assertEqual(renamed.id, original.id)
        self.assertIs(self.runtime.linker.resolve_handle(handle), renamed)
        self.assertEqual(set(target.items.tag_names()), {'hero', 'visible'})
