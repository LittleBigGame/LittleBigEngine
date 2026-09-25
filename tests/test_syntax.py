import unittest

from lbe.syntax import highlight_python_lines, slice_spans, SYNTAX_THEME


class SyntaxTests(unittest.TestCase):
    def test_highlight_keywords_strings_numbers_and_comments(self):
        source = 'def update(dt):\n    # comment\n    entity.x = 42\n    name = "hello"'
        lines = highlight_python_lines(source)
        self.assertEqual(len(lines), 4)

        # Line 0: def update(dt):
        line0 = lines[0]
        self.assertIn(('def', SYNTAX_THEME['keyword']), line0)
        self.assertIn(('update', SYNTAX_THEME['definition']), line0)
        self.assertIn(('dt', SYNTAX_THEME['builtin']), line0)

        # Line 1: comment
        line1 = lines[1]
        self.assertIn(('    ', SYNTAX_THEME['default']), line1)
        self.assertIn(('# comment', SYNTAX_THEME['comment']), line1)

        # Line 2: number
        line2 = lines[2]
        self.assertIn(('42', SYNTAX_THEME['number']), line2)

        # Line 3: string
        line3 = lines[3]
        self.assertIn(('"hello"', SYNTAX_THEME['string']), line3)

    def test_multiline_string_tokenization(self):
        source = '"""First line\nSecond line\nThird line"""\nval = 1'
        lines = highlight_python_lines(source)
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[0][0][1], SYNTAX_THEME['string'])
        self.assertEqual(lines[1][0][1], SYNTAX_THEME['string'])
        self.assertEqual(lines[2][0][1], SYNTAX_THEME['string'])
        self.assertIn(('1', SYNTAX_THEME['number']), lines[3])

    def test_slice_spans_for_horizontal_scrolling(self):
        spans = [('def', (1, 1, 1)), (' ', (2, 2, 2)), ('update', (3, 3, 3))]
        # No offset: full spans
        self.assertEqual(slice_spans(spans, 0, 10), spans)
        # Offset skipping first two characters of 'def'
        sliced = slice_spans(spans, 2, 6)
        self.assertEqual(sliced, [('f', (1, 1, 1)), (' ', (2, 2, 2)), ('upda', (3, 3, 3))])
        # Slicing past the end
        self.assertEqual(slice_spans(spans, 20, 5), [])
