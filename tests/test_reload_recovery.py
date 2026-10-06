"""Activation failures must leave a usable previous world and attachment."""

import unittest
from types import SimpleNamespace
from uuid import uuid4

from lbe import Runtime, SystemDefinition
from lbe.space import SpatialIndex
from lbe.project import PersistentGraph


class ReloadRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        self.addCleanup(self.runtime.close)
        self.owner = self.runtime.create(name='Owner', x=1, y=2, values={'items': [1]})

    def test_failed_start_restores_previous_lifecycle_listeners_and_state(self):
        original = self.owner.systems.attach('worker', SystemDefinition('''
def start(): system.listen('ping', lambda: setattr(entity, 'x', entity.x + 1))
def update(dt): entity.x += dt
def stop(): entity.values['items'].append(2)
'''))
        values = self.owner.values
        items = values['items']
        replacement = self.owner.systems.reload('worker', '''
def start():
    entity.x = 999
    system.listen('ping', lambda: setattr(entity, 'x', -100))
    create(parent=entity, name='Leak')
    raise ValueError('bad start')
''')
        self.assertIs(replacement, original)
        self.assertTrue(original.running)
        self.assertIs(self.owner.values, values)
        self.assertIs(values['items'], items)
        self.assertEqual(items, [1])
        self.assertEqual(self.owner.children, ())
        self.runtime.events.emit('ping')
        self.runtime.step(1)
        self.assertEqual(self.owner.x, 3)
        self.assertEqual(len(self.runtime.events._listeners['ping']), 1)
        self.assertIn('bad start', original.errors[-1].message)
        del self.owner.systems['worker']
        self.assertEqual(items, [1, 2])
        self.assertEqual(self.runtime.events._listeners['ping'], [])

    def test_failed_initialize_restores_destroyed_graph_and_derived_services(self):
        child = self.runtime.create(parent=self.owner, name='Child', x=4, y=5)
        self.owner.relations['child'] = child
        space = self.runtime.services['space'] = SpatialIndex(self.runtime)
        graph = self.runtime.services['graph'] = PersistentGraph(self.runtime, [self.owner, child])
        self.runtime.services['shared'] = SimpleNamespace(values=[1])
        original = self.owner.systems.attach('worker', SystemDefinition('def update(dt): pass'))
        result = self.owner.systems.reload('worker', '''
entity.values['items'].append(9)
shared.values.append(9)
destroy(resolve('Child'))
create(parent=entity, name='Leak', x=20, y=20)
raise ValueError('bad initialize')
''')
        self.assertIs(result, original)
        self.assertTrue(child.alive)
        self.assertEqual(self.owner.children, (child,))
        self.assertIs(self.owner.relations['child'], child)
        self.assertEqual(self.owner.values, {'items': [1]})
        self.assertEqual(self.runtime.services['shared'].values, [1])
        self.assertEqual(graph.entities, (self.owner, child))
        self.assertIn(child, space.query(4, 5))
        self.assertEqual(space.query(20, 20), ())
        child.destroy()
        self.assertNotIn('child', self.owner.relations)

    def test_failed_uuid_script_reload_restores_previous_instance(self):
        uid = uuid4()
        original = self.owner.scripts.attach(SystemDefinition('def run(dt): self.x += dt', asset_id=uid))
        result = self.owner.scripts.reload(uid, SystemDefinition('''
def run(dt): pass
def start():
    self.x = 999
    raise ValueError('bad script start')
''', asset_id=uid))
        self.assertIs(result, original)
        self.assertTrue(original.running)
        self.owner.run(uid, 2)
        self.assertEqual(self.owner.x, 3)

    def test_body_type_error_executes_once_and_restores_self(self):
        self.owner.calls = 0
        child = self.runtime.create(parent=self.owner)
        instance = self.owner.systems.attach('worker', SystemDefinition('''
def run(dt, *args, **kwargs):
    entity.calls += 1
    raise TypeError('body failed')
'''))
        self.runtime.step(1)
        self.assertEqual(self.owner.calls, 1)
        self.assertIs(instance.namespace['self'], self.owner)
        self.assertIn('body failed', instance.errors[-1].message)

    def test_keyword_only_and_self_signatures_receive_correct_arguments(self):
        instance = self.owner.systems.attach('worker', SystemDefinition('''
def start(self): self.started = True
def update(*, self, dt): self.x += dt
'''))
        self.runtime.step(2)
        self.assertTrue(self.owner.started)
        self.assertEqual(self.owner.x, 3)
        self.assertTrue(instance.running, list(instance.errors))
        uid = uuid4()
        script = self.owner.scripts.attach(SystemDefinition('def run(self, *, amount=1): self.x += amount', asset_id=uid))
        script.run(amount=4)
        self.assertEqual(self.owner.x, 7)
        self.assertEqual(list(script.errors), [])

    def test_single_self_argument_receives_each_target_not_delta_time(self):
        child = self.runtime.create(parent=self.owner, x=1)
        instance = self.owner.systems.attach('worker', SystemDefinition('def run(self): self.x += 1'))
        self.runtime.step(2)
        self.assertEqual(child.x, 2)
        self.assertEqual(list(instance.errors), [])
