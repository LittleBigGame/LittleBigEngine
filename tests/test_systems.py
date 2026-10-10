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
        a = self.owner.items.attach_system("worker", definition)
        b = other.items.attach_system("worker", definition)
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
        self.owner.items.attach_system("a", SystemDefinition(source))
        self.owner.items.attach_system("b", SystemDefinition(source))
        self.runtime.step(1)
        self.assertEqual(log, ["a:update", "b:update", "a:draw", "b:draw"])
        self.owner.items.move_behaviour(self.owner.items.behaviour("b", kind='system').id, 0)
        log.clear()
        self.runtime.step(1)
        self.assertEqual(log, ["b:update", "a:update", "b:draw", "a:draw"])

    def test_dynamic_components_enable_user_authored_movement(self):
        moving = self.runtime.create(parent=self.owner, x=0, y=0)
        still = self.runtime.create(parent=self.owner, x=4, y=4)
        script = SystemDefinition('def update(dt):\n    for child in query("x", "y", "vx", "vy"):\n        child.x += child.vx * dt\n        child.y += child.vy * dt\n')
        self.owner.items.attach_system("movement", script)
        self.runtime.step(1)
        moving.vx, moving.vy = 2, -3
        self.runtime.step(0.5)
        self.assertEqual((moving.x, moving.y), (1, -1.5))
        self.assertEqual((still.x, still.y), (4, 4))

    def test_script_errors_do_not_stop_other_systems(self):
        failed = self.owner.items.attach_system("bad", SystemDefinition("def update(dt): raise RuntimeError('bad script')"))
        good = self.owner.items.attach_system("good", SystemDefinition("ticks = 0\ndef update(dt):\n    global ticks\n    ticks += 1"))
        self.runtime.step(1)
        self.runtime.step(1)
        self.assertFalse(failed.running)
        self.assertIn("bad script", failed.errors[-1].traceback)
        self.assertEqual(good.globals["ticks"], 2)

    def test_reload_preserves_working_instance_on_compile_or_init_failure(self):
        old = self.owner.items.attach_system("worker", SystemDefinition("state = []"))
        self.assertIs(self.owner.items.reload(self.owner.items.behaviour("worker", kind='system').id, "def invalid("), old)
        self.assertTrue(old.running)
        self.assertIs(self.owner.items.reload(self.owner.items.behaviour("worker", kind='system').id, "raise ValueError('bad init')"), old)
        self.assertTrue(old.running)
        self.assertEqual(len(old.errors), 2)
        new = self.owner.items.reload(self.owner.items.behaviour("worker", kind='system').id, "state = [1]")
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
        instance = self.owner.items.attach_system("worker", script)
        self.runtime.events.emit("ping")
        self.owner.items.remove(self.owner.items.behaviour("worker", kind='system').id)
        self.runtime.events.emit("ping")
        instance.stop()
        self.assertEqual(self.owner.calls, ["start", "ping", "stop"])

    def test_detaching_during_update_skips_draw_and_other_attachment(self):
        log = []
        self.runtime.services["log"] = log
        self.owner.items.attach_system("first", SystemDefinition('def update(dt): entity.items.remove(entity.items.behaviour("second").id)'))
        second = self.owner.items.attach_system("second", SystemDefinition('def update(dt): log.append("update")\ndef draw(): log.append("draw")'))
        self.runtime.step(1)
        self.assertEqual(log, [])
        self.assertFalse(second.running)

    def test_destroy_runs_stop_and_closes_runtime(self):
        log = []
        self.runtime.services["log"] = log
        self.owner.items.attach_system("worker", SystemDefinition('def stop(): log.append("stopped")'))
        self.runtime.close()
        self.runtime.close()
        self.assertEqual(log, ["stopped"])
        self.assertEqual(self.runtime.entities, ())

    def test_failed_initialization_is_inspectable(self):
        instance = self.owner.items.attach_system("worker", SystemDefinition('raise ValueError("initialization")'))
        self.assertIs(self.owner.items.behaviour("worker", kind='system'), instance)
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
        instance = self.owner.items.attach_system("worker", SystemDefinition("def update(dt): entity.runtime.step(dt)"))
        self.runtime.step(1)
        self.assertFalse(instance.running)
        self.assertIn("recursively", instance.errors[-1].message)

    def test_run_dt_iterates_over_matching_children_with_self_injected(self):
        c1 = self.runtime.create(parent=self.owner, x=0, y=0, vx=5, vy=-2)
        c2 = self.runtime.create(parent=self.owner, x=10, y=20, vx=-1, vy=3)
        static = self.runtime.create(parent=self.owner, x=5, y=5)
        
        script = SystemDefinition('''
components = ("x", "y", "vx", "vy")

def run(dt):
    self.x += self.vx * dt
    self.y += self.vy * dt
''')
        self.owner.items.attach_system("mover", script)
        self.runtime.step(0.5)
        self.assertEqual((c1.x, c1.y), (2.5, -1.0))
        self.assertEqual((c2.x, c2.y), (9.5, 21.5))
        self.assertEqual((static.x, static.y), (5, 5))

    def test_update_dt_with_self_and_space_near(self):
        from lbe.space import SpatialIndex
        self.runtime.services["space"] = SpatialIndex(self.runtime, cell_size=1.0)
        
        p1 = self.runtime.create(parent=self.owner, x=0.2, y=0.3, w=0.5, h=0.5, name="ball1")
        p2 = self.runtime.create(parent=self.owner, x=0.6, y=0.7, w=0.5, h=0.5, name="ball2")
        far = self.runtime.create(parent=self.owner, x=50.0, y=50.0, w=0.5, h=0.5, name="ball_far")
        
        collected = []
        self.runtime.services["collected"] = collected
        
        script = SystemDefinition('''
components = ("x", "y")

def run(dt):
    nearby = space.near(self)
    for other in nearby:
        collected.append((self.name, other.name))
''')
        self.owner.items.attach_system("collider", script)
        self.runtime.step(0.1)
        self.assertIn(("ball1", "ball2"), collected)
        self.assertIn(("ball2", "ball1"), collected)
        self.assertNotIn(("ball1", "ball_far"), collected)
        self.runtime.services["space"].close()

    def test_run_dt_attached_directly_to_entity_runs_without_parent_system(self):
        ball = self.runtime.create(parent=self.owner, x=1.0, y=2.0, vx=3.0, vy=-1.0)
        script = SystemDefinition('''
components = ("x", "y", "vx", "vy")

def run(dt):
    self.x += self.vx * dt
    self.y += self.vy * dt
''')
        # Attached directly to ball, NOT to self.owner (Game/world)!
        attachment = ball.items.attach_system("phys", script)
        self.assertTrue(attachment.running)
        self.runtime.step(0.5)
        self.assertEqual(ball.x, 2.5)
        self.assertEqual(ball.y, 1.5)

