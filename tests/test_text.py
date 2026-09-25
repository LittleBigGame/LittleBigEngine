import unittest

from lbe.text import TextBuffer


class TextTests(unittest.TestCase):
    def test_selection_replacement_undo_and_redo(self):
        buffer = TextBuffer("hello world")
        buffer.anchor, buffer.cursor = 6, 11
        buffer.insert("LBE")
        self.assertEqual(buffer.text, "hello LBE")
        buffer.undo()
        self.assertEqual(buffer.text, "hello world")
        self.assertEqual(buffer.selected_text, "world")
        buffer.undo(redo=True)
        self.assertEqual(buffer.text, "hello LBE")

    def test_multiline_navigation_and_indentation(self):
        buffer = TextBuffer("def update(dt):")
        buffer.cursor = buffer.anchor = len(buffer.text)
        buffer.newline()
        buffer.insert("pass")
        self.assertEqual(buffer.text, "def update(dt):\n    pass")
        buffer.move("HOME")
        buffer.move("RIGHT", select=True)
        self.assertEqual(buffer.selected_text, " ")
        buffer.delete()
        self.assertEqual(buffer.text, "def update(dt):\n   pass")
        buffer.move("UP")
        self.assertEqual(buffer.position, (0, 0))

    def test_unicode_and_boundary_deletion(self):
        buffer = TextBuffer()
        buffer.delete()
        buffer.insert("λ🙂")
        buffer.delete()
        self.assertEqual(buffer.text, "λ")
        buffer.move("HOME")
        buffer.delete(backward=False)
        self.assertEqual(buffer.text, "")

    def test_scroll_reveals_caret(self):
        buffer = TextBuffer("\n".join("abcdefghij" for _ in range(20)))
        buffer.cursor = buffer.anchor = len(buffer.text)
        buffer.reveal(4, 5)
        self.assertEqual(buffer.scroll, 16)
        self.assertEqual(buffer.horizontal, 6)

    def test_word_navigation_and_selection_collapse(self):
        buffer = TextBuffer("one two three")
        buffer.move("WORD_RIGHT")
        self.assertEqual(buffer.cursor, 4)
        buffer.move("WORD_RIGHT", select=True)
        self.assertEqual(buffer.selected_text, "two ")
        buffer.move("LEFT")
        self.assertEqual(buffer.cursor, 4)
        self.assertEqual(buffer.anchor, 4)
        buffer.move("FILE_END")
        buffer.move("WORD_LEFT")
        self.assertEqual(buffer.cursor, 8)
