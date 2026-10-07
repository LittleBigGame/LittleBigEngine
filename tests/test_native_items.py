"""The native mutation boundary uses UUID records, not legacy collections."""
from dataclasses import dataclass, field, replace
from uuid import UUID, uuid4
import unittest

from lbe import Component, InheritedComponent, Parent, Relation, Runtime, SystemDefinition, SystemInstance, Tag


@dataclass(frozen=True)
class TransformComponent(Component):
    """An application-defined component; Core has no transform semantics."""


@dataclass(frozen=True)
class CustomRecord:
    name: str
    data: object
    id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class DefinitionMetadata:
    name: str
    definition: object
    id: UUID = field(default_factory=uuid4)


class NativeItemTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        self.addCleanup(self.runtime.close)

    def test_mixed_typed_records_are_actual_uuid_dictionary_entries(self):
        owner = self.runtime.create()
        target = self.runtime.create()
        records = (Component('x', 2), TransformComponent('transform', {'angle': 90}),
                   Tag('player'), Relation('target', target.id), CustomRecord('custom', [1, 2]),
                   SystemInstance(owner, 'movement', SystemDefinition('def update(dt): pass')))
        for record in records:
            self.assertIs(owner.items.add(record), record)
            self.assertIs(owner.items[record.id], record)
        self.assertEqual(tuple(owner.items), tuple(record.id for record in records))
        self.assertTrue(records[-1].running)
        self.assertEqual(owner.items.value(records[1].id), {'angle': 90})
        for record in reversed(records):
            owner.items.remove(record.id)
            with self.assertRaises(KeyError):
                self.runtime.linker.resolve(record.id)
        self.assertFalse(owner.items)
        self.assertFalse(records[-1].running)
        self.assertNotIn(target, self.runtime._incoming)

    def test_uuid_value_edit_and_name_edit_preserve_handle(self):
        owner = self.runtime.create()
        record = owner.items.add(TransformComponent('position', {'x': 1}))
        handle = self.runtime.linker.handle(record.id)
        edited = owner.items.replace(record.id, replace(record, value={'x': 2}))
        renamed = owner.items.rename(record.id, 'spawn')
        self.assertEqual(renamed.id, record.id)
        self.assertEqual(owner.items.value(record.id), {'x': 2})
        self.assertIs(self.runtime.linker.resolve_handle(handle), renamed)
        self.assertIsInstance(edited, TransformComponent)
        self.assertIsInstance(renamed, TransformComponent)

    def test_native_inherited_data_edit_keeps_source_and_identity(self):
        source = self.runtime.create().items.add(Component('speed', 3))
        owner = self.runtime.create()
        inherited = owner.items.add(InheritedComponent('speed', source.id))
        owner.items.replace(inherited.id, replace(inherited, patch=({'op': 'multiply', 'value': 2},)))
        self.assertEqual(owner.items.value(inherited.id), 6)
        self.assertEqual(self.runtime.linker.component_value(source.id), 3)
        self.assertEqual(owner.items[inherited.id].source, source.id)

    def test_native_relationship_rename_updates_destruction_index(self):
        owner = self.runtime.create()
        target = self.runtime.create()
        link = owner.items.add(Relation('target', target.id))
        renamed = owner.items.rename(link.id, 'friend')
        self.assertEqual(renamed.id, link.id)
        self.assertEqual(self.runtime._incoming[target], {(owner, 'friend')})
        target.destroy()
        self.assertNotIn(link.id, owner.items)

    def test_named_tag_helpers_mutate_actual_uuid_records(self):
        owner = self.runtime.create(tags=('player', 'player'))
        original, = owner.all(Tag)
        self.assertIs(owner.items.add_tag('player'), original)
        renamed = owner.items.rename(original.id, 'enemy')
        self.assertTrue(owner.items.has_tag('enemy'))
        self.assertFalse(owner.items.has_tag('player'))
        self.assertIs(owner.items[original.id], renamed)
        owner.items.remove_tag('enemy')
        self.assertFalse(owner.all(Tag))
        with self.assertRaises(KeyError):
            self.runtime.linker.resolve(original.id)

    def test_retarget_link_preserves_uuid_and_handle_and_cleans_indexes(self):
        owner, first, second = (self.runtime.create() for _ in range(3))
        link = owner.items.connect('target', first)
        handle = self.runtime.linker.handle(link.id)
        edited = owner.items.connect('target', second)
        self.assertEqual(edited.id, link.id)
        self.assertIs(self.runtime.linker.resolve_handle(handle), edited)
        self.assertNotIn(first, self.runtime._incoming)
        self.assertEqual(self.runtime._incoming[second], {(owner, 'target')})
        first.destroy()
        self.assertIs(owner.items.require_target('target'), second)
        second.destroy()
        self.assertFalse(owner.items.has_link('target'))
        self.assertNotIn(link.id, owner.items)

    def test_invalid_named_tag_and_link_names_do_not_insert_records(self):
        owner, target = self.runtime.create(), self.runtime.create()
        for name in (None, '', 3, []):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    owner.items.add_tag(name)
                with self.assertRaises(ValueError):
                    owner.items.connect(name, target)
        self.assertFalse(owner.items)
        self.assertFalse(self.runtime._incoming)

    def test_native_parent_record_controls_real_hierarchy(self):
        parent = self.runtime.create()
        child = self.runtime.create()
        record = Parent(parent.id)
        child.items.add(record)
        self.assertEqual(child.items[record.id], record)
        self.assertEqual(parent.children, (child,))
        child.items.remove(record.id)
        self.assertFalse(parent.children)

    def test_behaviour_rename_and_remove_preserve_lifecycle(self):
        owner = self.runtime.create()
        calls = []
        self.runtime.services['calls'] = calls
        source = SystemDefinition('def start(): calls.append("start")\ndef update(dt): calls.append("update")\ndef stop(): calls.append("stop")')
        record = owner.items.add(SystemInstance(owner, 'old', source))
        handle = self.runtime.linker.handle(record.id)
        owner.items.rename(record.id, 'new')
        self.runtime.step(0)
        self.assertIs(self.runtime.linker.resolve_handle(handle), record)
        owner.items.remove(record.id)
        self.assertEqual(calls, ['start', 'update', 'stop'])

    def test_failed_edits_do_not_replace_records(self):
        owner = self.runtime.create()
        record = owner.items.add(Component('x', 1))
        with self.assertRaises(ValueError):
            owner.items.replace(record.id, Component('x', 2))
        self.assertIs(owner.items[record.id], record)
        with self.assertRaises(KeyError):
            owner.items.add(InheritedComponent('missing', uuid4()))
        self.assertEqual(len(owner.items), 1)

    def test_native_reload_preserves_uuid_handle_and_failed_source_keeps_live_item(self):
        owner = self.runtime.create()
        record = owner.items.add(SystemInstance(owner, 'tick', SystemDefinition('def update(dt): pass')))
        handle = self.runtime.linker.handle(record.id)
        self.assertIs(owner.items.reload(record.id, 'def broken('), record)
        self.assertTrue(record.running)
        replacement = owner.items.reload(record.id, 'def update(dt): pass')
        self.assertIsNot(replacement, record)
        self.assertEqual(replacement.id, record.id)
        self.assertIs(self.runtime.linker.resolve_handle(handle), replacement)
        self.assertTrue(replacement.running)
        self.assertFalse(record.running)

    def test_native_reorder_uses_one_dictionary(self):
        owner = self.runtime.create()
        data = owner.items.add(Component('x', 1))
        first = owner.items.add(SystemInstance(owner, 'a', SystemDefinition('def update(dt): pass')))
        second = owner.items.add(SystemInstance(owner, 'b', first.definition))
        owner.items.move(second.id, 0)
        self.assertEqual(tuple(owner.items), (second.id, data.id, first.id))
        self.assertEqual(owner.items.all(SystemInstance), (second, first))

    def test_native_staged_behaviour_is_registered_before_activation(self):
        owner = self.runtime.create()
        record = owner.items.add(SystemInstance(owner, 'deferred', SystemDefinition('def update(dt): pass')), activate=False)
        self.assertIs(self.runtime.linker.resolve(record.id), record)
        self.assertFalse(record.running)
        self.assertFalse(record._initialized)

    def test_named_value_operations_preserve_concrete_type_and_uuid(self):
        owner = self.runtime.create()
        transform = owner.items.add(TransformComponent('transform', {'angle': 0}))
        owner.items.set_value('transform', {'angle': 90})
        edited = owner.items.component('transform')
        self.assertIsInstance(edited, TransformComponent)
        self.assertEqual(edited.id, transform.id)
        with owner.items.edit_value('transform') as value:
            value['angle'] = 180
        self.assertEqual(owner.items.require_value('transform'), {'angle': 180})
        self.assertEqual(owner.items.component('transform').id, transform.id)
        with self.assertRaises(RuntimeError):
            with owner.items.edit_value('transform') as value:
                value['angle'] = 270
                raise RuntimeError('rollback')
        self.assertEqual(owner.items.require_value('transform'), {'angle': 180})

    def test_snapshots_cannot_become_an_authoritative_collection(self):
        owner = self.runtime.create()
        owner.items.update_values({'x': 1, 'y': 2})
        snapshot = owner.items.value_dict()
        snapshot['x'] = 99
        snapshot['new'] = 3
        self.assertEqual(owner.items.require_value('x'), 1)
        self.assertFalse(owner.items.has_value('new'))
        self.assertEqual(set(owner.items.value_names()), {'x', 'y'})
        self.assertEqual(owner.items.remove_value('x'), 1)
        self.assertEqual(owner.items.remove_value('x', 'missing'), 'missing')

    def test_native_link_retarget_keeps_uuid_and_cleans_old_incoming_index(self):
        owner = self.runtime.create()
        first, second = self.runtime.create(), self.runtime.create()
        relation = owner.items.connect('target', first)
        handle = self.runtime.linker.handle(relation.id)
        edited = owner.items.connect('target', second)
        self.assertEqual(edited.id, relation.id)
        self.assertIs(self.runtime.linker.resolve_handle(handle), edited)
        self.assertNotIn(first, self.runtime._incoming)
        first.destroy()
        self.assertIs(owner.items.target('target'), second)
        self.assertIs(owner.items.disconnect('target'), second)
        self.assertNotIn(second, self.runtime._incoming)

    def test_type_index_tracks_subclass_edit_rename_remove_and_order(self):
        owner = self.runtime.create()
        first = owner.items.add(Component('x', 1))
        transform = owner.items.add(TransformComponent('transform', {'x': 0}))
        self.assertEqual(owner.all(Component), (first, transform))
        self.assertEqual(owner.all(TransformComponent), (transform,))
        owner.items.set_value('transform', {'x': 1})
        edited = owner.items.component('transform')
        self.assertEqual(owner.all(TransformComponent), (edited,))
        owner.items.move(edited.id, 0)
        self.assertEqual(owner.all(Component), (edited, first))
        renamed = owner.items.rename(edited.id, 'pose')
        self.assertEqual(owner.all(Component), (renamed, first))
        owner.items.remove(edited.id)
        self.assertFalse(owner.all(TransformComponent))
        self.assertEqual(owner.all(Component), (first,))

    def test_custom_record_field_names_do_not_imply_behaviour(self):
        owner = self.runtime.create()
        record = DefinitionMetadata('metadata', {'description': 'ordinary data'})
        self.assertIs(owner.items.add(record), record)
        self.assertEqual(owner.all(DefinitionMetadata), (record,))
        self.assertNotIn(record.id, self.runtime.linker.dependencies)

    def test_entity_has_no_legacy_data_collection_facades(self):
        owner = self.runtime.create(x=1)
        for old_name in ('components', 'tags', 'relations', 'systems', 'scripts'):
            self.assertNotIn(old_name, type(owner).__dict__)
            self.assertNotIn('_' + old_name, type(owner).__slots__)
            self.assertFalse(hasattr(owner, old_name))
            with self.assertRaises(AttributeError):
                getattr(owner, old_name)
        self.assertEqual(owner.items.require_value('x'), 1)

    def test_entity_creation_accepts_actual_typed_uuid_records(self):
        source = Component('speed', 4)
        inherited = InheritedComponent('speed_copy', source.id)
        transform = TransformComponent('transform', {'x': 1})
        record = CustomRecord('arbitrary', {'kind': 'data'})
        owner = self.runtime.create(items=(inherited, source, transform, record))
        self.assertEqual(tuple(owner.items), (inherited.id, source.id, transform.id, record.id))
        self.assertEqual(owner.items.value(inherited.id), 4)
        self.assertIs(owner.items[transform.id], transform)
        with self.assertRaises(TypeError):
            self.runtime.create(components={'x': 1})

    def test_native_creation_rejects_duplicate_item_uuid_without_mutation(self):
        record = Component('x', 1)
        before = self.runtime.entities
        with self.assertRaises(ValueError):
            self.runtime.create(items=(record, record))
        self.assertEqual(self.runtime.entities, before)
        with self.assertRaises(ValueError):
            self.runtime.create(items={uuid4(): record})
        self.assertEqual(self.runtime.entities, before)

    def test_behaviour_snapshots_are_not_mutable_attachment_collections(self):
        owner = self.runtime.create()
        record = owner.items.attach_system('worker', SystemDefinition('def update(dt): pass'))
        snapshot = owner.items.behaviour_dict()
        snapshot.clear()
        self.assertIs(owner.items[record.id], record)
        self.assertTrue(record.running)
        self.assertNotIn('systems', record.namespace)
        owner.items.remove(record.id)
        self.assertFalse(record.running)

    def test_script_name_edit_preserves_item_and_source_identities(self):
        owner = self.runtime.create()
        asset_id = uuid4()
        definition = SystemDefinition('def run(): return 7', 'example.py', asset_id)
        record = owner.items.attach_script(definition)
        handle = self.runtime.linker.handle(record.id)
        owner.items.rename(record.id, 'action')
        self.assertIs(owner.items.behaviour('action', 'script'), record)
        self.assertIs(owner.items.behaviour(record.id, 'script'), record)
        self.assertIs(owner.items.behaviour(definition, 'script'), record)
        self.assertIs(self.runtime.linker.resolve_handle(handle), record)
        self.assertNotEqual(record.id, asset_id)
        self.assertEqual(record.definition.asset_id, asset_id)
        self.assertEqual(owner.items.run_script(definition), 7)
