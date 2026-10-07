import tempfile
import unittest
from pathlib import Path
from lbe import Runtime
from lbe.assets import AssetRegistry
from lbe.activity import ActivityLog
from lbe.project import save_project,load_project_data,deserialize_entities,activate_entities
from lbe.project_files import ProjectFiles

class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)
        self.runtime=Runtime()
        self.addCleanup(self.runtime.close)
        self.runtime.assets.registry=AssetRegistry(self.path)
        self.log=ActivityLog(self.runtime)
        self.addCleanup(self.log.close)

    def definition(self,name,source):
        path=self.path/name
        path.write_text(source,encoding='utf-8')
        uid=self.runtime.assets.registry.register(path)
        return self.runtime.assets[uid]

    def test_queries_requirements_and_per_entity_failure_isolation(self):
        script=self.definition('move.py','components=("x","vx")\ndef run(entity,dt):\n    entity.x += entity.vx * dt')
        owner=self.runtime.create()
        bad=self.runtime.create(parent=owner,x=0,vx='broken')
        good=self.runtime.create(parent=owner,x=0,vx=2)
        absent=self.runtime.create(parent=owner,x=0)
        for target in (bad,good,absent):
            target.items.attach_script(script)
        source=f'def update(dt):\n    pill=assets["{script.asset_id}"]\n    for target in query(pill,*pill.components):\n        target.run(pill,dt)'
        system=self.definition('movement.py',source)
        attachment=owner.items.attach_system(system)
        self.runtime.step(1)
        self.assertEqual(good.x,2)
        self.assertTrue(attachment.running)
        self.assertEqual(tuple(owner.query(script)),(bad,good,absent))
        self.assertEqual(tuple(owner.query(script.components)),(bad,good))
        absent.run(script,1)
        errors=[r for r in self.log.records if r.kind=='script.error']
        self.assertEqual(len(errors),2)
        self.assertIn('Missing components: vx',errors[-1].detail)
        self.assertIn('move.py',errors[0].source)
        self.assertIn(str(bad.id),errors[0].target)
        del good.vx
        self.assertEqual(tuple(owner.query(*script.components)),(bad,))
        parent=self.runtime.create()
        child=self.runtime.create(parent=parent)
        parent.parent=owner
        self.assertEqual(tuple(owner.query(child)),(parent,))

    def test_script_roundtrip_move_delete_undo_and_identity(self):
        script=self.definition('move.py','components=("x",)\ndef run(entity):\n    entity.x += 1')
        target=self.runtime.create(x=0)
        target.items.attach_script(script)
        files=ProjectFiles(self.runtime,self.path)
        save=lambda:save_project(self.path,entities=self.runtime.entities,assets=self.runtime.assets.registry)
        renamed=self.path/'renamed.py'
        files.relocate(Path(script.path),renamed,save=save)
        target.run(script)
        self.assertEqual(target.x,1)
        save()
        data=load_project_data(self.path)
        restored=Runtime()
        self.addCleanup(restored.close)
        restored.assets.registry=AssetRegistry(self.path)
        restored.assets.registry.from_dict(data['assets'])
        entities=deserialize_entities(data['entities'],restored,project_dir=self.path,activate=False)
        activate_entities(entities.values(),restored,project_dir=self.path)
        entity=entities[target.id]
        entity.run(restored.assets[script.asset_id])
        self.assertEqual(entity.x,2)
        files.delete(renamed,save=save)
        target.run(script)
        self.assertEqual(target.x,1)
        files.history.undo()
        target.run(script)
        self.assertEqual(target.x,2)
