import importlib.util
from pathlib import Path
import tempfile
import unittest
from lbe.completion import complete, code_context


@unittest.skipUnless(importlib.util.find_spec('jedi'), 'optional Jedi dependency')
class CompletionTests(unittest.TestCase):
    def test_infers_local_type_instead_of_assuming_entity(self):
        source = 'class Tool:\n    def perform(self): pass\nthing = Tool()\nthing.per'
        prefix, matches = complete(source, len(source), 'scratch.py')
        self.assertEqual(prefix, 'per')
        self.assertIn(('perform', 'function'), matches)
        self.assertFalse(any(name in ('components', 'color') for name, _ in matches))

    def test_imports_project_source_without_executing_it(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'helper.py').write_text('raise RuntimeError("must not execute")\nclass Widget:\n    def refresh(self): pass\n')
            source = 'from helper import Widget\nw = Widget()\nw.ref'
            _, matches = complete(source, len(source), Path(folder, 'app.py'))
            self.assertIn(('refresh', 'function'), matches)

    def test_real_owner_component_names(self):
        source = 'entity.sta'
        _, matches = complete(source, len(source), 'scratch.py', ('stamina',))
        self.assertIn(('stamina', 'statement'), matches)

    def test_no_suggestions_in_comments_or_strings(self):
        for source in ['# entity.co', 'x = "entity.co', "x = '''entity.co", 'x = "abc"']:
            self.assertFalse(code_context(source, len(source)), source)
        self.assertTrue(code_context('x = "abc"\nx.up', len('x = "abc"\nx.up')))

    def test_live_game_entities_and_query_child_typing(self):
        context = {
            'owner': {'components': {'speed': 'float', 'target': 'str'}},
            'entities': {
                'HeroShip': {'components': {'x': 'float', 'y': 'float', 'vx': 'float', 'health': 'int'}},
                'DockingBay': {'components': {'status': 'str', 'docked': 'bool'}},
            },
            'all_components': {'x': 'float', 'y': 'float', 'vx': 'float', 'health': 'int', 'status': 'str', 'docked': 'bool', 'speed': 'float'},
        }

        # 1. Direct entity symbols and their components
        src1 = 'def update(dt):\n    resolve("HeroShip").v'
        prefix1, matches1 = complete(src1, len(src1), 'test.py', context)
        self.assertEqual(prefix1, 'v')
        self.assertIn(('vx', 'statement'), matches1)

        # 2. entities container namespace
        src2 = 'def update(dt):\n    resolve("DockingBay").'
        _, matches2 = complete(src2, len(src2), 'test.py', context)
        names2 = [m[0] for m in matches2]
        self.assertIn('status', names2)
        self.assertIn('docked', names2)

        # 3. query child return type with game components
        src3 = 'def update(dt):\n    for child in query("ship"):\n        child.v'
        prefix3, matches3 = complete(src3, len(src3), 'test.py', context)
        self.assertEqual(prefix3, 'v')
        self.assertIn(('vx', 'statement'), matches3)

        # 4. Known components prioritized ahead of generic Entity properties
        src4 = 'def update(dt):\n    resolve("HeroShip").'
        _, matches4 = complete(src4, len(src4), 'test.py', context)
        first_match_names = [m[0] for m in matches4[:len(context["all_components"])]]
        # Components health, vx, x, y should appear first
        for comp in ('health', 'vx', 'x', 'y'):
            self.assertIn(comp, first_match_names)

        # 5. More than 6 completions available for scrolling
        self.assertGreater(len(matches4), 6)

    def test_hover_info_extracts_signature_and_docstring(self):
        from lbe.completion import hover_info
        context = {
            'entities': {'HeroShip': {'components': {'x': 'float', 'vx': 'float'}}},
            'all_components': {'x': 'float', 'vx': 'float'}
        }
        source = 'def update(dt):\n    for child in query("x"):\n        child.x = 10\n'

        # Hover on 'query' (line 1, col 18)
        info = hover_info(source, 1, 18, 'test.py', context)
        self.assertIsNotNone(info)
        self.assertEqual(info['name'], 'query')
        self.assertEqual(info['type'], 'function')
        self.assertIn('query(*components', info['description'])

    def test_self_completion_and_type_hints(self):
        context = {
            'owner': {'components': {'x': 'float', 'y': 'float', 'vx': 'float', 'vy': 'float'}},
            'all_components': {'x': 'float', 'y': 'float', 'vx': 'float', 'vy': 'float'}
        }
        source = 'def run(dt):\n    self.v'
        prefix, matches = complete(source, len(source), 'test.py', context)
        self.assertEqual(prefix, 'v')
        match_names = [m[0] for m in matches]
        self.assertIn('vx', match_names)
        self.assertIn('vy', match_names)

        source_full = 'def run(dt):\n    self.'
        _, all_matches = complete(source_full, len(source_full), 'test.py', context)
        all_names = [m[0] for m in all_matches]
        self.assertIn('x', all_names)
        self.assertIn('y', all_names)
        self.assertIn('vx', all_names)
        self.assertIn('vy', all_names)
        self.assertIn('query', all_names)
        self.assertIn('destroy', all_names)
        self.assertIn('children', all_names)


