import unittest

from lbe import Runtime, SystemDefinition


class LifecycleTests(unittest.TestCase):
    def test_start_is_once_and_stop_can_detach_itself(self):
        runtime = Runtime()
        entity = runtime.create(count=0)
        instance = entity.items.attach_system("worker", SystemDefinition('''
def start(): entity.count += 1
def stop():
    if system.id in entity.items:
        entity.items.remove(system.id)
'''))
        instance.start()
        self.assertEqual(entity.count, 1)
        instance.stop()
        self.assertFalse(instance.running)
        self.assertEqual(len(entity.items.behaviour_dict('system')), 0)

    def test_new_attachment_waits_until_next_frame(self):
        runtime = Runtime()
        entity = runtime.create(ticks=0)
        runtime.services["definition"] = SystemDefinition("def update(dt): entity.ticks += 1")
        entity.items.attach_system("spawner", SystemDefinition('''
def update(dt):
    if not entity.items.has_behaviour("new"): entity.items.attach_system("new", definition)
'''))
        runtime.step(1)
        self.assertEqual(entity.ticks, 0)
        runtime.step(1)
        self.assertEqual(entity.ticks, 1)

    def test_reloaded_attachment_waits_until_next_frame(self):
        runtime = Runtime()
        entity = runtime.create(ticks=0)
        entity.items.attach_system("reload", SystemDefinition('''
done = False
def update(dt):
    global done
    if not done:
        done = True
        entity.items.reload(entity.items.behaviour("target").id, "def update(dt): entity.ticks += 10")
'''))
        entity.items.attach_system("target", SystemDefinition("def update(dt): entity.ticks += 1"))
        runtime.step(1)
        self.assertEqual(entity.ticks, 0)
        runtime.step(1)
        self.assertEqual(entity.ticks, 10)

    def test_stop_cannot_add_children_to_destroying_parent(self):
        runtime = Runtime()
        entity = runtime.create()
        instance = entity.items.attach_system("worker", SystemDefinition("def stop(): create(parent=entity)"))
        entity.destroy()
        self.assertEqual(runtime.entities, ())
        self.assertIn("destruction", instance.errors[-1].message)

    def test_failed_reload_unsubscribes_staged_listeners(self):
        runtime = Runtime()
        entity = runtime.create()
        original = entity.items.attach_system("worker", SystemDefinition("value = 1"))
        for _ in range(3):
            entity.items.reload(entity.items.behaviour("worker", kind='system').id, 'system.listen("ping", lambda: None)\nraise ValueError("fail")')
        self.assertIs(entity.items.behaviour("worker", kind='system'), original)
        self.assertEqual(runtime.events._listeners["ping"], [])
