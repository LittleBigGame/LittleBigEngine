from pathlib import Path
import tempfile
import unittest

from lbe import Runtime, SystemDefinition


class SystemTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        self.owner = self.runtime.create()

    def test_same_definition_has_independent_script_globals(self):
        definition = SystemDefinition("items = []\ndef update(dt):\n    items.append(dt)\n")
        other = self.runtime.create()
        a = self.owner.systems.attach("worker", definition)
        b = other.systems.attach("worker", definition)
        self.runtime.step(0.5)
        a.namespace["items"].append(99)
        self.assertEqual(a.globals["items"], [0.5, 99])
        self.assertEqual(b.globals["items"], [0.5])
        self.assertIs(a.definition, b.definition)
        self.assertNotIn("entity", a.globals)

    def test_all_updates_precede_draws(self):
        log = []
        self.runtime.services["log"] = log
        source = "def update(dt): log.append(system.name + ':update')\ndef draw(): log.append(system.name + ':draw')"
        self.owner.systems.attach("a", SystemDefinition(source))
        self.owner.systems.attach("b", SystemDefinition(source))
        self.runtime.step(1)
        self.assertEqual(log, ["a:update", "b:update", "a:draw", "b:draw"])
        self.owner.systems.move("b", 0)
        log.clear()
        self.runtime.step(1)
        self.assertEqual(log, ["b:update", "a:update", "b:draw", "a:draw"])

    def test_dynamic_components_enable_user_authored_movement(self):
        moving = self.runtime.create(parent=self.owner, x=0, y=0)
        still = self.runtime.create(parent=self.owner, x=4, y=4)
        script = SystemDefinition('def update(dt):\n    for child in query("x", "y", "vx", "vy"):\n        child.x += child.vx * dt\n        child.y += child.vy * dt\n')
        self.owner.systems.attach("movement", script)
        self.runtime.step(1)
        moving.vx, moving.vy = 2, -3
        self.runtime.step(0.5)
        self.assertEqual((moving.x, moving.y), (1, -1.5))
        self.assertEqual((still.x, still.y), (4, 4))

    def test_script_errors_do_not_stop_other_systems(self):
        failed = self.owner.systems.attach("bad", SystemDefinition("def update(dt): raise RuntimeError('bad script')"))
        good = self.owner.systems.attach("good", SystemDefinition("ticks = 0\ndef update(dt):\n    global ticks\n    ticks += 1"))
        self.runtime.step(1)
        self.runtime.step(1)
        self.assertFalse(failed.running)
        self.assertIn("bad script", failed.errors[-1].traceback)
        self.assertEqual(good.globals["ticks"], 2)

    def test_reload_preserves_working_instance_on_compile_or_init_failure(self):
        old = self.owner.systems.attach("worker", SystemDefinition("state = []"))
        self.assertIs(self.owner.systems.reload("worker", "def invalid("), old)
        self.assertTrue(old.running)
        self.assertIs(self.owner.systems.reload("worker", "raise ValueError('bad init')"), old)
        self.assertTrue(old.running)
        self.assertEqual(len(old.errors), 2)
        new = self.owner.systems.reload("worker", "state = [1]")
        self.assertIsNot(new, old)
        self.assertFalse(old.running)
        self.assertTrue(new.running)

    def test_lifecycle_and_subscription_cleanup(self):
        self.owner.calls = []
        script = SystemDefinition('''
def start():
    entity.calls.append("start")
    system.listen("ping", lambda: entity.calls.append("ping"))
def stop():
    entity.calls.append("stop")
''')
        instance = self.owner.systems.attach("worker", script)
        self.runtime.events.emit("ping")
        del self.owner.systems["worker"]
        self.runtime.events.emit("ping")
        instance.stop()
        self.assertEqual(self.owner.calls, ["start", "ping", "stop"])

    def test_detaching_during_update_skips_draw_and_other_attachment(self):
        log = []
        self.runtime.services["log"] = log
        self.owner.systems.attach("first", SystemDefinition('def update(dt): del systems["second"]'))
        second = self.owner.systems.attach("second", SystemDefinition('def update(dt): log.append("update")\ndef draw(): log.append("draw")'))
        self.runtime.step(1)
        self.assertEqual(log, [])
        self.assertFalse(second.running)

    def test_destroy_runs_stop_and_closes_runtime(self):
        log = []
        self.runtime.services["log"] = log
        self.owner.systems.attach("worker", SystemDefinition('def stop(): log.append("stopped")'))
        self.runtime.close()
        self.runtime.close()
        self.assertEqual(log, ["stopped"])
        self.assertEqual(self.runtime.entities, ())

    def test_failed_initialization_is_inspectable(self):
        instance = self.owner.systems.attach("worker", SystemDefinition('raise ValueError("initialization")'))
        self.assertIs(self.owner.systems["worker"], instance)
        self.assertFalse(instance.running)
        self.assertEqual(instance.errors[0].message, "initialization")

    def test_asset_cache_tracks_content_and_rejects_bad_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worker.py"
            path.write_text("value = 1", encoding="utf-8")
            first = self.runtime.assets.system(path)
            self.assertIs(first, self.runtime.assets.system(path))
            path.write_text("def broken(", encoding="utf-8")
            with self.assertRaises(SyntaxError):
                self.runtime.assets.system(path)
            path.write_text("value = 2", encoding="utf-8")
            self.assertIsNot(first, self.runtime.assets.system(path))

    def test_recursive_step_becomes_script_diagnostic(self):
        instance = self.owner.systems.attach("worker", SystemDefinition("def update(dt): entity.runtime.step(dt)"))
        self.runtime.step(1)
        self.assertFalse(instance.running)
        self.assertIn("recursively", instance.errors[-1].message)
