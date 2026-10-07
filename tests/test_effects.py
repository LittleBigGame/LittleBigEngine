import unittest
from lbe import Runtime, SystemDefinition
from lbe.effects import SystemEffects


class EffectsTests(unittest.TestCase):
    def test_query_and_write_attribution_reset_and_detach(self):
        runtime = Runtime()
        self.addCleanup(runtime.close)
        effects = SystemEffects(runtime)
        owner = runtime.create()
        child = runtime.create(parent=owner, x=1)
        owner.items.attach_system('physics', SystemDefinition('def update(dt):\n    for target in query("x"):\n        target.x += dt'))
        runtime.step(1)
        record, = effects.affecting(child)
        self.assertEqual(record.queried, frozenset([child.id]))
        self.assertEqual(record.changed, frozenset([child.id]))
        child.parent = None
        runtime.step(1)
        self.assertEqual(effects.affecting(child), ())
        owner.items.remove(owner.items.behaviour('physics', kind='system').id)
        self.assertEqual(effects.records(), ())
        self.assertFalse(runtime.events.errors)

    def test_nested_query_observation_preserves_actor_and_snapshot(self):
        runtime = Runtime()
        self.addCleanup(runtime.close)
        effects = SystemEffects(runtime)
        root = runtime.create()
        child = runtime.create(parent=root, x=1)
        root.items.attach_system('reader', SystemDefinition('def update(dt):\n    list(query("x"))'))
        runtime.step(0)
        record, = effects.affecting(child)
        self.assertEqual(record.queried, frozenset([child.id]))
        self.assertFalse(record.changed)
        runtime.destroy(child)
        self.assertFalse(effects.affecting(child))
