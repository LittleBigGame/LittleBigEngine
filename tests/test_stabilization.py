"""Contracts protecting durable projects and ordinary application/editor behavior."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from uuid import uuid4

from lbe import Runtime, SystemDefinition
from lbe.assets import AssetRegistry
from lbe.project import (EntityRef, activate_entities, deserialize_entities, deserialize_value,
                         load_project_data, save_project, serialize_entities, serialize_value)


class PersistenceContracts(TestCase):
    def test_repeated_restart_preserves_graph_order_values_and_start_dependencies(self):
        with TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / 'inspect.py').write_text('def start():\n    entity.seen = [c.name for c in entity.children]\n')
            runtime = Runtime()
            root = runtime.create(name='Game', tags=['root'])
            a = runtime.create(parent=root, name='A', nullable=None,
                               settings={'__type__': 'tuple', 'values': [1, 2]})
            b = runtime.create(parent=root, name='B')
            root.move_child(b, 0)
            a.link = b
            a.items.connect('peer', b)
            root.items.attach_system('inspect', runtime.assets.system(folder / 'inspect.py'))
            identities = root.id, a.id, b.id
            for _ in range(3):
                save_project(folder, entities=runtime.entities)
                runtime.close()
                runtime = Runtime()
                restored = deserialize_entities(load_project_data(folder)['entities'], runtime, project_dir=folder)
                root, a, b = (restored[identity] for identity in identities)
                self.assertEqual(root.children, (b, a))
                self.assertEqual(root.seen, ['B', 'A'])
                self.assertIs(a.link, b)
                self.assertIs(a.items.require_target('peer'), b)
                self.assertIsNone(a.nullable)
                self.assertEqual(a.settings, {'__type__': 'tuple', 'values': [1, 2]})
            runtime.close()

    def test_missing_declarations_survive_save_and_recover(self):
        with TemporaryDirectory() as folder:
            folder = Path(folder)
            identity, absent = uuid4(), uuid4()
            data = [dict(id=str(identity), items={
                str(uuid4()): {'type': 'Component', 'name': 'target', 'value': {'__type__': 'entity', 'id': str(absent)}},
                str(uuid4()): {'type': 'Relation', 'name': 'target', 'target': str(absent)},
                str(uuid4()): {'type': 'System', 'name': 'late', 'definition': {'path': 'late.py', 'asset_id': None}},
            })]
            runtime = Runtime()
            entity = deserialize_entities(data, runtime, project_dir=folder)[identity]
            self.assertIsInstance(entity.target, EntityRef)
            saved = serialize_entities(runtime.entities, project_dir=folder)
            self.assertEqual(saved[0]['items'], data[0]['items'])
            (folder / 'late.py').write_text('def start():\n    entity.started = True\n')
            activate_entities([entity], runtime, project_dir=folder)
            self.assertTrue(entity.started)
            runtime.close()

    def test_invalid_structure_rolls_back_and_outside_reference_cannot_replace_save(self):
        runtime = Runtime()
        old = runtime.create(name='Existing')
        identity = str(uuid4())
        with self.assertRaises(ValueError):
            deserialize_entities([dict(id=identity, components={'': 1})], runtime)
        self.assertEqual(runtime.entities, (old,))
        with TemporaryDirectory() as folder:
            save_project(folder, entities=[old])
            path = Path(folder, 'project.json')
            previous = path.read_bytes()
            old.reference = runtime.create()
            with self.assertRaises(ValueError):
                save_project(folder, entities=[old])
            self.assertEqual(path.read_bytes(), previous)
        runtime.close()

    def test_deferred_activation_sees_application_links_and_inline_source_survives(self):
        runtime = Runtime()
        entity = runtime.create()
        entity.items.attach_system('inline', SystemDefinition('def start():\n    entity.ready = entity.items.has_link("camera")\n'))
        data = serialize_entities([entity])
        other = Runtime()
        restored = deserialize_entities(data, other, activate=False)[entity.id]
        camera = other.create()
        restored.items.connect('camera', camera)
        activate_entities([restored], other)
        self.assertTrue(restored.ready)
        runtime.close()
        other.close()

    def test_escaping_and_none_skip_contract(self):
        value = {'__type__': 'dict', 'values': {'__type__': 'anything'}, 'nested': [None, (1, 2)]}
        self.assertEqual(deserialize_value(serialize_value(value)), value)
        runtime = Runtime()
        entity = runtime.create(nullable=None, unsupported=object())
        self.assertEqual([item['name'] for item in serialize_entities([entity], on_unsupported='skip')[0]['items'].values()], ['nullable'])
        runtime.close()


class AssetContracts(TestCase):
    def test_identity_updates_collisions_and_entry_snapshots(self):
        registry = AssetRegistry()
        old = registry.register('a.py')
        replacement = uuid4()
        self.assertEqual(registry.register('a.py', asset_id=replacement), replacement)
        self.assertIsNone(registry.get(old))
        snapshot = registry.get(replacement)
        snapshot['path'] = 'corrupt.py'
        self.assertEqual(registry.get(replacement)['path'], 'a.py')
        other = registry.register('b.py')
        before = registry.to_dict()
        with self.assertRaises(ValueError):
            registry.rename(other, 'a.py')
        with self.assertRaises(ValueError):
            registry.register('c.py', asset_id=replacement)
        self.assertEqual(registry.to_dict(), before)

    def test_subtree_relocation_preserves_identities_and_failed_import_is_atomic(self):
        registry = AssetRegistry()
        a, b = registry.register('src/a.py'), registry.register('src/sub/b.png')
        registry.relocate('src', 'lib/src')
        self.assertEqual(registry.get_id('lib/src/a.py'), a)
        self.assertEqual(registry.get_id('lib/src/sub/b.png'), b)
        before = registry.to_dict()
        with self.assertRaises(ValueError):
            registry.from_dict({str(uuid4()): {'path': '../outside.py'}})
        self.assertEqual(registry.to_dict(), before)

    def test_entity_handles_are_not_deep_copied(self):
        runtime = Runtime()
        target = runtime.create()
        owner = runtime.create(settings={'target': target, 'values': []})
        with owner.items.edit_value('settings') as copy:
            self.assertIs(copy['target'], target)
            copy['values'].append(1)
        self.assertEqual(owner.settings['values'], [1])
        runtime.close()


class EditorContracts(TestCase):
    def setUp(self):
        from lbe.desktop import Input
        from lbe.project import load_project, template_path
        from test_scene import RecordingGraphics
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.input = Input()
        self.window = SimpleNamespace(width=1440, height=900, set_clipboard_text=lambda text: None,
                                      get_clipboard_text=lambda: '')
        self.graphics = RecordingGraphics()
        self.runtime = load_project(self.window, self.graphics, self.input, self.directory.name, template=template_path('editor'))
        self.addCleanup(self.runtime.close)
        self.editor = self.runtime.entities[0].application_state
        self.runtime.step(0)

    def send(self, *events):
        self.input.pending.extend(events)
        self.runtime.step(0)
        self.assertNotIn('ui_error', self.editor.app.items.value_dict())
        for entity in self.runtime.entities:
            for instance in entity.items.behaviour_dict('system').values():
                self.assertFalse(instance.errors, list(instance.errors))

    def click(self, control):
        self.assertTrue(self.editor.ui.visible(control), control)
        self.send(('click', control.x + control.w / 2, control.y + control.h / 2, 1, 0))

    def type(self, control, text, *, commit=False):
        self.assertFalse(control.items.get_value('readonly', False))
        self.click(control)
        self.send(('key', 'A', True, False), ('text', text))
        if commit:
            self.send(('key', 'ENTER', False, False))

    def menu_item(self, text):
        menu = self.editor.app.items.require_target('context_menu')
        return next(child for child in menu.children if text in child.items.get_value('text', ''))

    def test_visible_authoring_workflow_and_restart(self):
        from lbe.project import load_project
        ed = self.editor
        moving = ed.game.children[0]
        self.click(ed.add_item_button)
        self.click(self.menu_item('+ Velocity'))
        vx = next(field for _, field in ed.item_rows if field.visible and field.component_key == 'vx')
        self.type(vx, '2.0', commit=True)
        self.send(('click', ed.code.x + 90, ed.code.y + 90, 4, 0))
        self.click(self.menu_item('+ New system script'))
        self.send(('click', ed.code.x + 90, ed.code.y + 90, 4, 0))
        self.click(self.menu_item('Rename'))
        self.type(ed.path_field, 'physics.py', commit=True)
        self.type(ed.code, 'def update(dt):\n    for child in query("x", "vx"):\n        child.x += child.vx * dt\n')
        self.send(('key', 'S', True, False))
        row = next(row for row in ed.hierarchy_rows if row.visible and row.items.target('target') is ed.game)
        self.send(('click', row.x + row.w / 2, row.y + row.h / 2, 1, 0, 2))
        self.click(ed.add_item_button)
        self.click(self.menu_item('System /'))
        self.click(self.menu_item('physics'))
        self.assertIn('physics', ed.game.items.behaviour_dict('system'))
        before = moving.x
        self.runtime.step(0.5)
        self.assertEqual(moving.x, before + 1)
        self.click(ed.menu_file_btn)
        self.click(self.menu_item('Save Project'))
        identity, expected = moving.id, moving.x
        self.runtime.close()
        restarted = load_project(self.window, self.graphics, self.input, self.directory.name)
        self.addCleanup(restarted.close)
        self.assertEqual(restarted.resolve(identity).x, expected)
        restarted.step(0.5)
        self.assertEqual(restarted.resolve(identity).x, expected + 1)

    def test_panel_detach_stops_retained_behavior_and_reload_rebinds_once(self):
        ed = self.editor
        original = ed.identity_label.text
        definition = ed.inspector.items.behaviour('inspector', kind='system').definition
        ed.inspector.items.remove(ed.inspector.items.behaviour('inspector', kind='system').id)
        ed.game.children[0].name = 'ChangedWhileDetached'
        self.runtime.step(0)
        self.assertEqual(ed.identity_label.text, original)
        self.assertFalse(hasattr(ed, 'inspector_sync'))
        ed.inspector.items.attach_system('inspector', definition)
        self.runtime.step(0)
        self.assertIn('ChangedWhileDetached', ed.identity_label.text)
        before = ed.inspector_sync
        ed.inspector.items.reload(ed.inspector.items.behaviour('inspector', kind='system').id, definition)
        self.assertIsNot(before, ed.inspector_sync)
        self.send()

    def test_popup_and_reparenting_do_not_change_persistent_ownership(self):
        from lbe.menus import open_menu
        ed = self.editor
        entity = self.runtime.create(parent=ed.game, name='Owned')
        entity.parent = ed.inspector
        open_menu(ed.ui, ed.app, 100, 100, actions=[dict(label='Probe', run=lambda _: None)])
        ed.save_editor_project()
        data = load_project_data(ed.project)
        self.assertIn(str(entity.id), {record['id'] for record in data['entities']})
        self.assertFalse(any('ui' in record.get('tags', []) for record in data['entities']))

    def test_rename_preserves_unrelated_systems_dirty_buffer_and_order(self):
        ed = self.editor
        other = ed.project / 'other.py'
        other.write_text('def update(dt):\n    entity.marker = "other"\n')
        entity = self.runtime.create(parent=ed.game, label='render')
        instance = entity.items.attach_system('render', self.runtime.assets.system(other))
        ed.code.buffer.insert('# dirty\n')
        dirty = ed.code.buffer.text
        original = (ed.project / 'render.py').read_text()
        game_instance = ed.game.items.behaviour('render', kind='system')
        destination = ed.rename_file('renamed.py')
        self.assertIs(entity.items.behaviour('render', kind='system'), instance)
        self.assertEqual(entity.label, 'render')
        self.assertIs(ed.game.items.behaviour('renamed', kind='system'), game_instance)
        self.assertEqual(destination.read_text(), original)
        self.assertEqual(ed.code.buffer.text, dirty)
        self.assertNotEqual(ed._saved_source[1], dirty)
        folder = ed.project / 'folder'
        folder.mkdir()
        ed.app.items.behaviour('app', kind='system').namespace['move_file_or_folder'](destination, folder)
        self.assertEqual(ed.path_field.buffer.text, 'folder/renamed.py')
        self.assertNotEqual(ed._saved_source[1], dirty)

    def test_component_collision_duplication_and_unchanged_float_commit(self):
        from lbe.text import TextBuffer
        ed = self.editor
        entity = self.runtime.create(parent=ed.game, name='Clone', data=[1], a=1, b=99, precise=1.234567891)
        ed.select(entity)
        self.runtime.step(0)
        label = next(label for label, field in ed.item_rows if field.visible and field.component_key == 'a')
        label.buffer = TextBuffer('b')
        label.renaming_key = 'a'
        with self.assertRaises(ValueError):
            ed.commit_component_key(label)
        self.assertEqual((entity.a, entity.b), (1, 99))
        field = next(field for _, field in ed.item_rows if field.visible and field.component_key == 'precise')
        ed.commit_component(field)
        self.assertEqual(entity.precise, 1.234567891)
        ed.inspector_duplicate_entity()
        duplicate = ed.app.items.require_target('inspected')
        duplicate.data.append(2)
        self.assertEqual(entity.data, [1])


    def test_non_script_rename_uses_visible_field_and_preserves_uuid(self):
        path = Path(self.directory.name) / 'texture.png'
        path.write_bytes(b'image')
        registry = self.runtime.assets.registry
        identity = registry.register(path)
        original = self.editor.code.buffer.text
        self.editor.app.items.behaviour('app', kind='system').globals['prompt_rename_file_item'](
            {'type': 'image', 'name': path.name, 'path': path})
        self.type(self.editor.path_field, 'renamed.png', commit=True)
        self.assertEqual(registry.get_id('renamed.png'), identity)
        self.assertFalse(path.exists())
        self.assertEqual(self.editor.code.buffer.text, original)


    def test_failed_component_rename_save_rolls_back_data(self):
        from lbe.text import TextBuffer
        ed = self.editor
        target = ed.game.children[0]
        label = next(label for label, field in ed.item_rows if field.visible and field.component_key == 'x')
        label.buffer = TextBuffer('position')
        label.renaming_key = 'x'
        before = dict(target.items.value_dict())
        original = ed.save_editor_project
        def fail():
            raise OSError('injected write failure')
        ed.save_editor_project = fail
        try:
            with self.assertRaises(OSError):
                ed.commit_component_key(label)
        finally:
            ed.save_editor_project = original
        self.assertEqual(dict(target.items.value_dict()), before)


class FileOperationContracts(TestCase):
    def test_subtree_move_and_rollback_preserve_disk_registry_and_attachments(self):
        from lbe.project_files import ProjectFiles
        with TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / 'src').mkdir()
            script = folder / 'src/a.py'
            script.write_text('def update(dt): pass\n')
            runtime = Runtime()
            registry = runtime.assets.registry = AssetRegistry(folder)
            identity = registry.register(script)
            entity = runtime.create()
            instance = entity.items.attach_system('custom', runtime.assets.system(script))
            files = ProjectFiles(runtime, folder)
            save = lambda: save_project(folder, entities=runtime.entities, assets=registry)
            save()
            previous = (folder / 'project.json').read_bytes()
            def fail():
                save()
                raise OSError('injected save failure')
            with self.assertRaises(OSError):
                files.relocate(folder / 'src', folder / 'lib', save=fail)
            self.assertTrue(script.exists())
            self.assertEqual((folder / 'project.json').read_bytes(), previous)
            self.assertEqual(registry.get_id(script), identity)
            self.assertTrue(Path(instance.definition.path).samefile(script))
            files.relocate(folder / 'src', folder / 'lib', save=save)
            self.assertEqual(registry.get_id(folder / 'lib/a.py'), identity)
            self.assertIs(entity.items.behaviour('custom', kind='system'), instance)
            files.delete(folder / 'lib', save=save)
            self.assertEqual(registry.get_id(folder / 'lib/a.py'), identity)
            self.assertFalse((folder / 'lib').exists())
            runtime.close()


class ApplicationContracts(TestCase):
    def test_demo_input_and_scoped_world_coordinates(self):
        from lbe.desktop import Input
        from lbe.project import load_project, template_path
        from test_scene import RecordingGraphics
        with TemporaryDirectory() as folder:
            input_state = Input()
            runtime = load_project(SimpleNamespace(width=900, height=600), RecordingGraphics(), input_state,
                                   folder, template=template_path('demo'))
            self.addCleanup(runtime.close)
            game = next(e for e in runtime.entities if e.items.get_value('name') == 'Game')
            player = game.children[0]
            x = player.x
            input_state.pending.extend([('key', 'RIGHT', False, False), ('key', 'F3', False, False)])
            runtime.step(0.1)
            self.assertGreater(player.x, x)
            self.assertTrue(game.show_spatial_debug)
            self.assertFalse(input_state.pending)
            index = runtime.services['space']
            screen = runtime.create(parent=runtime.entities[0], tags=['ui'], x=100, y=100, w=1, h=1)
            parent = runtime.create(parent=game, x=100, y=100)
            child = runtime.create(parent=parent, x=1, y=1, w=1, h=1)
            self.assertIn(child, index.query(101, 101))
            self.assertNotIn(child, index.query(1, 1))
            self.assertNotIn(screen, index.query(100, 100))
            parent.x = 200
            self.assertIn(child, index.query(201, 101))
            child.parent = runtime.entities[0]
            self.assertNotIn(child, index.query(1, 1))

    def test_template_upgrade_keeps_customized_files(self):
        from lbe.project_templates import initialize_template, template_updates, upgrade_template
        with TemporaryDirectory() as folder:
            folder = Path(folder)
            template, project = folder / 'editor', folder / 'project'
            template.mkdir()
            project.mkdir()
            (template / 'app.py').write_text('entity.version = 1\n')
            (template / 'ui.py').write_text('def update(dt): pass\n')
            initialize_template(project, template)
            (project / 'ui.py').write_text('# customized\n')
            (template / 'app.py').write_text('entity.version = 2\n')
            self.assertEqual(template_updates(project, template), {'app.py': 'update', 'ui.py': 'customized'})
            upgrade_template(project, template)
            self.assertEqual((project / 'app.py').read_text(), 'entity.version = 2\n')
            self.assertEqual((project / 'ui.py').read_text(), '# customized\n')

    def test_kernel_import_boundary_and_completion_injection(self):
        import ast
        import lbe.core
        from lbe.completion import build_prelude
        for filename in ('core.py', 'events.py'):
            tree = ast.parse(Path(lbe.core.__file__).with_name(filename).read_text())
            imports = [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            self.assertFalse(any(name.startswith(('lbe.ui', 'lbe.desktop', 'lbe.templates', 'ui', 'desktop', 'templates')) for name in imports))
        prelude = build_prelude({'entities': {'HeroShip': {'components': {'vx': 'float'}}}, 'all_components': {'vx': 'float'}})
        self.assertNotIn('HeroShip:', prelude)
        self.assertNotIn('entities:', prelude)
        runtime = Runtime()
        entity = runtime.create()
        instance = entity.items.attach_system('api', SystemDefinition('assert runtime is entity.runtime\nassert callable(asset)\n'))
        self.assertFalse(instance.errors)
        runtime.close()


class RecoveryContracts(TestCase):
    def test_interrupted_file_move_restores_disk_and_project(self):
        from lbe.project import write_json
        from lbe.project_files import JOURNAL, recover_file_operation
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'new.py').write_text('original')
            write_json(folder / 'project.json', {'changed': True})
            write_json(folder / JOURNAL, dict(source='old.py', destination='new.py', operation='relocate',
                                             phase='prepared', project={'original': True}))
            recover_file_operation(folder)
            self.assertEqual((folder / 'old.py').read_text(), 'original')
            self.assertFalse((folder / 'new.py').exists())
            import json
            self.assertEqual(json.loads((folder / 'project.json').read_text()), {'original': True})
            recover_file_operation(folder)

    def test_missing_script_retains_order_through_restart_and_recovery(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'second.py').write_text('def update(dt):\n    pass\n')
            identity = uuid4()
            data = [dict(id=str(identity), items={str(uuid4()): {'type': 'System', 'name': name,
                        'definition': {'path': name + '.py', 'asset_id': None}} for name in ('first', 'second')})]
            runtime = Runtime()
            self.addCleanup(runtime.close)
            entity = deserialize_entities(data, runtime, project_dir=folder)[identity]
            saved = serialize_entities([entity], project_dir=folder)
            self.assertEqual([item['name'] for item in saved[0]['items'].values()], ['first', 'second'])
            (folder / 'first.py').write_text('def update(dt):\n    pass\n')
            activate_entities([entity], runtime, project_dir=folder)
            self.assertEqual(list(entity.items.behaviour_dict('system')), ['first', 'second'])

    def test_inline_references_are_code_only_and_layout_is_attachable(self):
        from lbe.ui import Layout, reference_matches
        identity = str(uuid4())
        source = f'# resolve("{identity}")\nnote = \'resolve("{identity}")\'\nvalue = resolve("{identity}")\n'
        self.assertEqual(len(reference_matches(source)), 1)
        runtime = Runtime()
        self.addCleanup(runtime.close)
        root = runtime.create()
        instance = Layout(root).install()
        runtime.step(0)
        self.assertTrue(instance.running)
        self.assertFalse(instance.errors)


    def test_interrupted_template_upgrade_restores_all_files_and_manifest(self):
        from lbe.project import write_json
        from lbe.project_templates import JOURNAL, MANIFEST, recover_template_upgrade
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            backup = folder / '.lbe-template-backups' / 'test'
            backup.mkdir(parents=True)
            (backup / 'app.py').write_text('original')
            write_json(backup / MANIFEST, {'original': True})
            (folder / 'app.py').write_text('partial upgrade')
            (folder / 'new.py').write_text('new')
            write_json(folder / MANIFEST, {'changed': True})
            write_json(folder / JOURNAL, dict(phase='prepared', backup='.lbe-template-backups/test',
                                             files={'app.py': 'update', 'new.py': 'new'}))
            recover_template_upgrade(folder)
            self.assertEqual((folder / 'app.py').read_text(), 'original')
            self.assertFalse((folder / 'new.py').exists())
            import json
            self.assertEqual(json.loads((folder / MANIFEST).read_text()), {'original': True})
            recover_template_upgrade(folder)
