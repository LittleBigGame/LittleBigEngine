import unittest
from uuid import uuid4
from lbe import Runtime, SystemDefinition
from lbe.references import lower_references, source_references
from lbe.project import deserialize_entities, serialize_entities


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        self.addCleanup(self.runtime.close)

    def test_lexing_ignores_strings_comments_multiline_and_fstrings(self):
        uid = uuid4()
        token = f"<|Entity:{uid}|>"
        source = f'''# {token}
plain = "{token}"
multi = """first
{token}
"""
formatted = f"{token}"
actual = {token}
'''
        lowered, references = lower_references(source)
        self.assertEqual(len(references), 1)
        self.assertEqual(len(source), len(lowered))
        self.assertEqual(source.count("\n"), lowered.count("\n"))
        compile(lowered, "<test>", "exec")
        self.assertEqual(lowered.count(token), 4)

    def test_neutral_symbols_cannot_collide_with_author_code(self):
        source = f"_lbe_ref_0 = 'author'\nx = <|Entity:{uuid4()}|>"
        lowered, references = lower_references(source)
        self.assertNotEqual(references[0].symbol, "_lbe_ref_0")
        compile(lowered, "<test>", "exec")

    def test_bound_entity_and_component_follow_live_changes(self):
        source = self.runtime.create(x=1)
        component = source.components.item("x")
        owner = self.runtime.create()
        definition = SystemDefinition(f"target = <|Entity:{source.id}|>\nvalue = <|Component:{component.id}|>\ndef update(dt):\n    target.x = value.value + 1\n")
        attachment = owner.systems.attach("worker", definition)
        self.assertTrue(attachment.running)
        self.runtime.step(0)
        self.runtime.step(0)
        self.assertEqual(source.x, 3)
        self.assertIn(attachment.id, self.runtime.linker.dependents(component.id))
        self.assertEqual(definition.source.count("<|"), 2)

    def test_missing_wrong_type_and_malformed_references_are_diagnostics(self):
        e = self.runtime.create(x=1)
        before = len(self.runtime.entities)
        for token in (f"<|Entity:{uuid4()}|>", f"<|Component:{e.id}|>"):
            attachment = e.systems.attach(str(uuid4()), SystemDefinition(f"target = {token}"))
            self.assertFalse(attachment.running)
            self.assertTrue(attachment.errors)
        self.assertEqual(len(self.runtime.entities), before)
        with self.assertRaises(SyntaxError) as caught:
            SystemDefinition("x = 1\ny = <|Entity:not-a-uuid|>", "author.py")
        self.assertEqual(caught.exception.lineno, 2)
        self.assertEqual(caught.exception.filename, "author.py")

    def test_restore_links_forward_behavior_references_before_initializing(self):
        a, b = self.runtime.create(), self.runtime.create()
        behavior = b.systems.attach("later", SystemDefinition("def update(dt): pass"))
        a.systems.attach("earlier", SystemDefinition(f"target = <|System:{behavior.id}|>\ndef update(dt):\n    self.other = target.id"))
        data = serialize_entities([a, b])
        other = Runtime()
        self.addCleanup(other.close)
        restored = deserialize_entities(data, other)
        self.assertTrue(restored[a.id].systems["earlier"].running)
        other.step(0)
        self.assertEqual(restored[a.id].other, behavior.id)

    def test_gui_recognition_matches_runtime_lexer(self):
        from lbe.ui import reference_matches
        token = f"<|Component:{uuid4()}|>"
        matches = reference_matches(f"# {token}\n'{token}'\nx = {token}")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].group(3), "Component")
