import tempfile
from pathlib import Path
import unittest
from lbe.assets import AssetRegistry


class AssetRescanTests(unittest.TestCase):
    def test_recreated_old_path_after_rename_preserves_both_identities(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old = root / 'text_area.py'
            old.write_text('original')
            registry = AssetRegistry(root)
            registry.scan()
            original_id = registry.get_id(old)
            renamed = root / 'renamed_text_area.py'
            old.rename(renamed)
            registry.rename(original_id, renamed)
            old.write_text('new asset')
            registry.scan()
            new_id = registry.get_id(old)
            self.assertNotEqual(new_id, original_id)
            self.assertEqual(registry.get_path(original_id), renamed)
            registry.scan()
            self.assertEqual(registry.get_id(old), new_id)
            loaded = AssetRegistry(root)
            loaded.from_dict(registry.to_dict())
            loaded.scan()
            self.assertEqual(loaded.get_id(old), new_id)
            with self.assertRaises(ValueError):
                loaded.register(old, asset_id=original_id)
