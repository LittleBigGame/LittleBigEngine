"""Run the suite with isolated preferences, caches and Linux EGL graphics."""

import argparse
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pattern', default='test_*.py')
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    os.chdir(root)
    from lbe import user_state

    with tempfile.TemporaryDirectory(prefix='lbe-tests-') as directory:
        cache = Path(directory)
        try:
            import pyglet
        except ImportError:
            pass
        else:
            if sys.platform != 'win32':
                pyglet.options['headless'] = True
        try:
            import jedi
        except ImportError:
            pass
        else:
            jedi.settings.cache_directory = str(cache / 'jedi')
        with patch.object(user_state, 'STATE_DIR', cache / 'preferences'), \
             patch.object(user_state, 'STATE_FILE', cache / 'preferences' / 'state.json'), \
             patch.dict(os.environ, {'XDG_CACHE_HOME': str(cache)}):
            suite = unittest.defaultTestLoader.discover('tests', pattern=args.pattern)
            result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
        return 0 if result.wasSuccessful() and result.testsRun else 1


if __name__ == '__main__':
    sys.exit(main())
