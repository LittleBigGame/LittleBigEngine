"""Source saves must not strand a partially activated project."""

from pathlib import Path
import tempfile
import unittest

from lbe import Runtime
from lbe.assets import AssetRegistry
from lbe.project import save_project, load_project_data, deserialize_entities
from lbe.source import activate_source, recover_source_operation, SourceActivationError, JOURNAL


class SourceActivationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.directory = Path(folder.name)
        self.path = self.directory / 'worker.py'
        self.original = 'def update(dt): self.x += dt\n'
        self.path.write_text(self.original, encoding='utf-8')
        self.runtime = Runtime()
        self.addCleanup(self.runtime.close)
        self.runtime.assets.registry = AssetRegistry(self.directory)
        self.runtime.assets.registry.register(self.path)
        self.first = self.runtime.create(name='First', x=1)
        self.second = self.runtime.create(name='Second', x=2)
        definition = self.runtime.assets.system(self.path)
        self.first_instance = self.first.systems.attach('worker', definition)
        self.second_instance = self.second.systems.attach('worker', definition)
        self.save()

    def save(self):
        save_project(self.directory, entities=self.runtime.entities,
                     assets=self.runtime.assets.registry)

    def activate(self, source, save=None):
        return activate_source(self.runtime, self.directory, self.path, source,
                               save=save or self.save)

    def test_later_attachment_failure_restores_entire_group_and_draft(self):
        project = (self.directory / 'project.json').read_bytes()
        source = '''
def update(dt): self.x += 100
def start():
    self.x = 999
    if self.name == 'Second': raise ValueError('second cannot activate')
'''
        with self.assertRaisesRegex(SourceActivationError, 'second cannot activate'):
            self.activate(source)
        self.assertIs(self.first.systems['worker'], self.first_instance)
        self.assertIs(self.second.systems['worker'], self.second_instance)
        self.assertTrue(self.first_instance.running)
        self.assertTrue(self.second_instance.running)
        self.assertEqual((self.first.x, self.second.x), (1, 2))
        self.assertEqual(self.path.read_text(), self.original)
        self.assertEqual((self.directory / 'project.json').read_bytes(), project)
        self.assertEqual((self.directory / '.lbe-drafts/worker.py').read_text(), source)
        self.assertFalse((self.directory / JOURNAL).exists())
        self.runtime.step(1)
        self.assertEqual((self.first.x, self.second.x), (2, 3))

    def test_syntax_failure_preserves_active_source(self):
        with self.assertRaisesRegex(SourceActivationError, 'SyntaxError'):
            self.activate('def broken(')
        self.assertEqual(self.path.read_text(), self.original)
        self.assertTrue(self.first_instance.running)

    def test_failed_project_write_restores_source_graph_and_project(self):
        previous = (self.directory / 'project.json').read_bytes()
        def failed_save():
            self.save()
            raise OSError('disk failed after project replacement')
        with self.assertRaisesRegex(SourceActivationError, 'disk failed'):
            self.activate('def update(dt): self.x += 20\n', failed_save)
        self.assertEqual((self.directory / 'project.json').read_bytes(), previous)
        self.assertIs(self.first.systems['worker'], self.first_instance)
        self.assertEqual(self.path.read_text(), self.original)

    def test_successful_save_activates_every_attachment_and_survives_restart(self):
        source = 'def update(dt): self.x += 2 * dt\n'
        self.assertEqual(self.activate(source), 2)
        self.assertFalse(self.first_instance.running)
        other = Runtime()
        self.addCleanup(other.close)
        entities = deserialize_entities(load_project_data(self.directory)['entities'], other,
                                        project_dir=self.directory)
        other.step(1)
        self.assertEqual(entities[self.first.id].x, 3)
        self.assertEqual(entities[self.second.id].x, 4)

    def test_external_invalid_edit_does_not_replace_saved_active_revision(self):
        self.path.write_text('def invalid(', encoding='utf-8')
        other = Runtime()
        self.addCleanup(other.close)
        entities = deserialize_entities(load_project_data(self.directory)['entities'], other,
                                        project_dir=self.directory)
        other.step(1)
        self.assertTrue(entities[self.first.id].systems['worker'].running)
        self.assertEqual(entities[self.first.id].x, 2)
        self.assertEqual(self.path.read_text(), 'def invalid(')

    def test_external_start_failure_recovers_without_leaked_state(self):
        self.path.write_text('''
def update(dt): self.x += 100
def start():
    self.x = 999
    create(parent=self, name='Leak')
    raise ValueError('external start failure')
''', encoding='utf-8')
        other = Runtime()
        self.addCleanup(other.close)
        entities = deserialize_entities(load_project_data(self.directory)['entities'], other,
                                        project_dir=self.directory)
        other.step(1)
        self.assertEqual(entities[self.first.id].x, 2)
        self.assertEqual(entities[self.first.id].children, ())
        self.assertEqual(len(other.entities), 2)

    def test_interrupted_activation_recovers_original_files(self):
        project = (self.directory / 'project.json').read_bytes()
        def interrupted_save():
            self.save()
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.activate('def update(dt): self.x += 100\n', interrupted_save)
        self.assertTrue((self.directory / JOURNAL).exists())
        recover_source_operation(self.directory)
        self.assertEqual(self.path.read_text(), self.original)
        self.assertEqual((self.directory / 'project.json').read_bytes(), project)

    def test_deleted_source_remains_missing_instead_of_resurrecting(self):
        self.path.unlink()
        other = Runtime()
        self.addCleanup(other.close)
        entities = deserialize_entities(load_project_data(self.directory)['entities'], other,
                                        project_dir=self.directory)
        self.assertNotIn('worker', entities[self.first.id].systems)
