import tempfile
import unittest
from pathlib import Path
from lbe import Runtime
from lbe.assets import AssetRegistry
from lbe.project_files import ProjectFiles

class FileHistoryTests(unittest.TestCase):
    def test_rename_delete_create_redo_preserve_identity_and_contents(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            runtime=Runtime()
            self.addCleanup(runtime.close)
            runtime.assets.registry=AssetRegistry(folder)
            files=ProjectFiles(runtime,folder)
            path=folder/'a.py'
            path.write_text('original',encoding='utf-8')
            identity=runtime.assets.registry.register(path)
            save=lambda:None
            moved=folder/'b.py'
            files.relocate(path,moved,save=save)
            files.history.undo()
            self.assertTrue(path.exists())
            self.assertEqual(runtime.assets.registry.get_id(path),identity)
            files.history.undo(redo=True)
            files.delete(moved,save=save)
            files.history.undo()
            self.assertEqual(moved.read_text(encoding='utf-8'),'original')
            self.assertEqual(runtime.assets.registry.get_id(moved),identity)
            files.history.undo(redo=True)
            self.assertFalse(moved.exists())
            created=folder/'new'
            created.mkdir()
            files.record_create(created)
            files.history.undo()
            self.assertFalse(created.exists())
            files.history.undo(redo=True)
            self.assertTrue(created.is_dir())

    def test_deleted_folder_stops_attached_updates_and_undo_resumes(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            runtime=Runtime()
            self.addCleanup(runtime.close)
            runtime.assets.registry=AssetRegistry(folder)
            directory=folder/'systems'
            directory.mkdir()
            path=directory/'counter.py'
            path.write_text('def update(dt):\n    entity.count += 1',encoding='utf-8')
            entity=runtime.create(count=0)
            entity.items.attach_system('counter', runtime.assets.system(path))
            files=ProjectFiles(runtime,folder)
            runtime.step(0)
            self.assertEqual(entity.count,1)
            files.delete(directory,save=lambda:None)
            runtime.step(0)
            self.assertEqual(entity.count,1)
            self.assertFalse(entity.items.behaviour('counter', kind='system').running)
            files.history.undo()
            runtime.step(0)
            self.assertEqual(entity.count,2)
            files.history.undo(redo=True)
            runtime.step(0)
            self.assertEqual(entity.count,2)

    def test_failed_undo_keeps_command_and_restored_file_can_be_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            runtime=Runtime()
            self.addCleanup(runtime.close)
            runtime.assets.registry=AssetRegistry(folder)
            files=ProjectFiles(runtime,folder)
            path=folder/'file.txt'
            path.write_text('original',encoding='utf-8')
            files.delete(path,save=lambda:None)
            path.write_text('replacement',encoding='utf-8')
            with self.assertRaises(FileExistsError):
                files.history.undo()
            self.assertEqual(path.read_text(encoding='utf-8'),'replacement')
            path.unlink()
            files.history.undo()
            self.assertEqual(path.read_text(encoding='utf-8'),'original')
