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
