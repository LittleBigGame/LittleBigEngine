import tempfile
from pathlib import Path
import unittest
from lbe.project_templates import initialize_template, template_updates, upgrade_template


class NestedTemplateTests(unittest.TestCase):
    def test_nested_initialization_upgrade_and_customization(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            template, project = root/'template', root/'project'
            template.mkdir(); project.mkdir()
            (template/'app.py').write_text('pass')
            source = template/'systems/editor/layout/docking.py'
            source.parent.mkdir(parents=True)
            source.write_text('version = 1')
            initialize_template(project,template)
            target = project/'systems/editor/layout/docking.py'
            self.assertEqual(target.read_text(), 'version = 1')
            source.write_text('version = 2')
            self.assertEqual(template_updates(project,template)['systems/editor/layout/docking.py'], 'update')
            upgrade_template(project,template)
            self.assertEqual(target.read_text(), 'version = 2')
            target.write_text('custom = True')
            source.write_text('version = 3')
            upgrade_template(project,template)
            self.assertEqual(target.read_text(), 'custom = True')
