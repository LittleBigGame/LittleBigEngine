import unittest
from lbe import Runtime, SystemDefinition
from lbe.activity import ActivityLog


class ActivityTests(unittest.TestCase):
    def test_editor_errors_remain_visible_with_editor_noise_disabled(self):
        runtime = Runtime()
        self.addCleanup(runtime.close)
        log = ActivityLog(runtime)
        owner = runtime.create(tags=['ui'])
        owner.systems.attach('broken', SystemDefinition('def update(dt):\n    raise ValueError("editor failure")'))
        runtime.step(0)
        self.assertTrue(any(r.kind == 'system.error' for r in log.view()))
        self.assertFalse(any(r.kind == 'system.call' for r in log.view()))
        log.clear()
        excluded = runtime.create(tags=['ui'])
        log.exclude(excluded)
        excluded.systems.attach('panel_error', SystemDefinition('def update(dt):\n    raise ValueError("log panel failure")'))
        runtime.step(0)
        self.assertTrue(any(r.kind == 'system.error' and 'log panel failure' in r.detail for r in log.view()))

    def test_mutations_have_immutable_values_and_system_source(self):
        runtime = Runtime()
        log = ActivityLog(runtime)
        runtime.services['log'] = log
        owner = runtime.create(name='Mover', x=1)
        owner.systems.attach('move', SystemDefinition('def update(dt):\n    entity.x += 2\n    events.emit("moved", entity.x)'))
        runtime.step(1)
        record = next(r for r in log.records if r.kind == 'component.set' and 'x:' in r.detail)
        self.assertIn('1 -> 3', record.detail)
        self.assertIn('.move.update', record.source)
        self.assertTrue(any(r.kind == 'event.moved' for r in log.records))
        owner.x = 10
        self.assertIn('1 -> 3', record.detail)
        runtime.close()
        count = len(log.records)
        runtime.create()
        self.assertEqual(count, len(log.records))

    def test_nested_attribution_errors_and_bounded_records(self):
        runtime = Runtime()
        log = ActivityLog(runtime, capacity=8)
        root = runtime.create(name='Owner')
        root.systems.attach('broken', SystemDefinition('def update(dt):\n    raise ValueError("broken action")'))
        runtime.step(0)
        errors = [r for r in log.records if r.kind == 'system.error']
        self.assertTrue(errors)
        self.assertIn('broken action', errors[-1].detail)
        self.assertIn('.broken.update', errors[-1].source)
        self.assertIsNone(runtime.changes.source)
        for i in range(20):
            root.x = i
        self.assertEqual(len(log.records), 8)
        log.close()
        runtime.close()

    def test_editor_filter_self_exclusion_and_frame_calls(self):
        runtime = Runtime()
        log = ActivityLog(runtime)
        editor = runtime.create(tags=['ui'])
        game = runtime.create()
        log.clear()
        editor.x = 1
        self.assertFalse(log.records)
        log.include_editor = True
        editor.x = 2
        self.assertEqual(len(log.records), 1)
        log.exclude(editor)
        child = runtime.create(parent=editor)
        child.x = 3
        self.assertEqual(len(log.records), 1)
        game.systems.attach('tick', SystemDefinition('def update(dt): pass\ndef draw(): pass'))
        log.clear()
        runtime.step(0)
        self.assertFalse(log.records)
        log.frame_calls = True
        runtime.step(0)
        self.assertEqual([r.detail for r in log.records], ['tick.update', 'tick.draw'])
        log.close()
        runtime.close()

    def test_snapshots_do_not_execute_user_repr_or_fail_on_large_values(self):
        class Explosive:
            def __repr__(self):
                raise RuntimeError('repr must not run')
        runtime = Runtime()
        owner = runtime.create()
        owner.value = Explosive()
        owner.value = 10**5000
        value = []; value.append(value)
        owner.value = value
        self.assertFalse(runtime.changes.errors)
        runtime.close()

    def test_listener_error_is_logged_without_interrupting_other_listeners(self):
        runtime = Runtime()
        log = ActivityLog(runtime)
        called = []
        def broken():
            raise ValueError('listener failed')
        runtime.events.on('ping', broken)
        runtime.events.on('ping', lambda: called.append(True))
        runtime.events.emit('ping')
        self.assertEqual(called, [True])
        self.assertTrue(any(r.kind == 'event.error' and 'listener failed' in r.detail for r in log.records))
        log.close()
        runtime.close()

    def test_log_panel_and_save_with_transient_editor_links(self):
        import tempfile
        from types import SimpleNamespace
        from lbe.desktop import Input
        from lbe.project import load_project, template_path
        from test_scene import RecordingGraphics
        with tempfile.TemporaryDirectory() as folder:
            runtime = load_project(SimpleNamespace(width=1440, height=900), RecordingGraphics(), Input(), folder, template=template_path('editor'))
            self.addCleanup(runtime.close)
            runtime.step(0)
            app = runtime.entities[0]
            state = app.application_state
            state.ui.dispatch(('key', 'L', True, False))
            runtime.step(0)
            panel = app.relations['system_log_panel']
            self.assertIn('ui', panel.tags)
            self.assertIn('system_log', panel.systems)
            state.game.test_value = 12
            runtime.step(0)
            self.assertTrue(any(r.kind == 'component.set' and 'test_value' in r.detail for r in runtime.services['log'].view()))
            self.assertTrue(any(c.text and 'test_value' in c.text for c in panel.children if 'text' in c.components))
            state.save_editor_project()
            self.assertFalse(runtime.changes.errors)
            self.assertFalse(runtime.events.errors)
            self.assertTrue(all(not s.errors for e in runtime.entities for s in e.systems.values()))

    def test_component_named_entity_class_does_not_confuse_snapshot(self):
        runtime = Runtime()
        owner = runtime.create()
        impostor = type('Entity', (), {})()
        owner.value = impostor
        self.assertEqual(runtime.changes.history[-1].new, '<Entity>')
        runtime.close()

    def test_nested_listener_actor_restores_caller_and_frame_order(self):
        runtime = Runtime()
        log = ActivityLog(runtime)
        log.frame_calls = True
        a = runtime.create(name='A', value=0)
        b = runtime.create(name='B', value=0)
        b.systems.attach('listener', SystemDefinition('def start():\n    system.listen("ping", receive)\ndef receive():\n    entity.value = 2\ndef draw(): pass'))
        a.systems.attach('caller', SystemDefinition('def update(dt):\n    events.emit("ping")\n    entity.value = 3\ndef draw(): pass'))
        log.clear()
        runtime.step(0)
        mutations = [r for r in log.records if r.kind == 'component.set']
        self.assertIn('.listener.event:ping', mutations[0].source)
        self.assertIn('.caller.update', mutations[1].source)
        calls = [r.detail for r in log.records if r.kind == 'system.call']
        self.assertEqual(calls, ['caller.update', 'listener.event:ping', 'caller.draw', 'listener.draw'])
        self.assertIsNone(runtime.changes.source)
        log.close()
        runtime.close()

    def test_observer_cannot_add_listener_to_current_emission(self):
        from lbe.events import Events
        events = Events()
        called = []
        events.observe(lambda name,args,kwargs:events.on('ping',lambda:called.append('late')))
        events.emit('ping')
        self.assertEqual(called, [])
        events.emit('ping')
        self.assertEqual(called, ['late'])

    def test_log_panel_moving_resizing_and_controls(self):
        import tempfile
        from types import SimpleNamespace
        from lbe.desktop import Input
        from lbe.project import load_project, template_path
        from test_scene import RecordingGraphics
        with tempfile.TemporaryDirectory() as folder:
            window=SimpleNamespace(width=1440,height=900)
            runtime=load_project(window,RecordingGraphics(),Input(),folder,template=template_path('editor'))
            self.addCleanup(runtime.close)
            runtime.step(0)
            state=runtime.entities[0].application_state
            ui=state.ui
            ui.dispatch(('key','L',True,False));runtime.step(0)
            panel=state.app.relations['system_log_panel']
            start=panel.x,panel.y
            ui.dispatch(('click',panel.x+20,panel.y+10,1,0))
            ui.dispatch(('drag',panel.x+70,panel.y+30,1,0,50,20))
            ui.dispatch(('release',panel.x+20,panel.y+10,1,0));runtime.step(0)
            self.assertEqual((panel.x,panel.y),(min(start[0]+50,window.width-panel.w),start[1]+20))
            controls={c.name:c for c in panel.children}
            ui.dispatch(('click',controls['PauseLog'].x+5,controls['PauseLog'].y+5,1,0))
            self.assertTrue(runtime.services['log'].paused)
            panel.selected_record = runtime.services['log'].records[-1]
            panel.offset = 3
            ui.dispatch(('click',controls['ClearLog'].x+5,controls['ClearLog'].y+5,1,0))
            runtime.step(0)
            self.assertIsNone(panel.selected_record)
            self.assertEqual(panel.offset, 0)
            self.assertEqual(controls['LogDetail'].text, '')
            count=len(runtime.services['log'].records)
            state.game.health=4
            self.assertEqual(count,len(runtime.services['log'].records))
            window.width,window.height=800,600
            runtime.step(0)
            self.assertLessEqual(panel.x+panel.w,window.width)
            self.assertLessEqual(panel.y+panel.h,window.height)
            self.assertFalse(runtime.changes.errors)
            self.assertTrue(all(not s.errors for e in runtime.entities for s in e.systems.values()))

    def test_log_panel_reload_and_detach_release_owned_controls(self):
        import tempfile
        from types import SimpleNamespace
        from lbe.desktop import Input
        from lbe.project import load_project, template_path
        from test_scene import RecordingGraphics
        with tempfile.TemporaryDirectory() as folder:
            runtime = load_project(SimpleNamespace(width=1440,height=900), RecordingGraphics(),
                                   Input(), folder, template=template_path('editor'))
            self.addCleanup(runtime.close)
            runtime.step(0)
            app = runtime.entities[0]
            app.application_state.ui.dispatch(('key','L',True,False))
            panel = app.relations['system_log_panel']
            original = tuple(panel.children)
            definition = panel.systems['system_log'].definition
            panel.systems.reload('system_log', definition)
            self.assertEqual(len(panel.children), len(original))
            self.assertTrue(all(not child.alive for child in original))
            custom = runtime.create(parent=panel, name='Custom')
            replacement = lambda control,event: False
            panel.on_click = replacement
            del panel.systems['system_log']
            self.assertEqual(panel.children, (custom,))
            self.assertIs(panel.on_click, replacement)
            self.assertNotIn('on_drag', panel.components)
            self.assertNotIn(panel.id, runtime.services['log'].excluded)
            self.assertFalse(runtime.changes.errors)
