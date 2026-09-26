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

    def test_crlf_normalization_and_cursor_alignment(self):
        buffer = TextBuffer("first line\r\nsecond line\r\n")
        self.assertEqual(buffer.text, "first line\nsecond line\n")
        # Moving to end of first line
        buffer.move("END")
        self.assertEqual(buffer.position, (0, 10))
        self.assertEqual(buffer.cursor, 10)
        # Type character at end of line
        buffer.insert("!")
        self.assertEqual(buffer.text, "first line!\nsecond line\n")
        self.assertEqual(buffer.position, (0, 11))
        # Move down to second line end
        buffer.move("DOWN")
        buffer.move("END")
        self.assertEqual(buffer.position, (1, 11))
        self.assertEqual(buffer.cursor, 23)

    def test_crlf_paste_and_assignment_normalization(self):
        buffer = TextBuffer("alpha\nbeta")
        buffer.cursor = buffer.anchor = 5
        buffer.insert("\r\ngamma\r\n")
        self.assertEqual(buffer.text, "alpha\ngamma\n\nbeta")
        # Direct property assignment normalizes as well
        buffer.text = "line1\r\nline2\rline3"
        self.assertEqual(buffer.text, "line1\nline2\nline3")

    def test_delete_word_and_smart_indentation(self):
        # 1. Word deletion backward
        buffer = TextBuffer("def update(dt):")
        buffer.cursor = buffer.anchor = len(buffer.text)
        buffer.delete_word(backward=True)
        self.assertEqual(buffer.text, "def update(dt)")
        buffer.delete_word(backward=True)
        self.assertEqual(buffer.text, "def update(dt")
        buffer.delete_word(backward=True)
        self.assertEqual(buffer.text, "def update(")
        buffer.delete_word(backward=True)
        self.assertEqual(buffer.text, "def update")

        # 2. Indentation after comment following colon
        b2 = TextBuffer("def foo():  # function comment")
        b2.cursor = b2.anchor = len(b2.text)
        b2.newline()
        self.assertEqual(b2.text, "def foo():  # function comment\n    ")

        # 3. Indentation inside open bracket
        b3 = TextBuffer("items = (")
        b3.cursor = b3.anchor = len(b3.text)
        b3.newline()
        self.assertEqual(b3.text, "items = (\n    ")

        # 4. Pressing Enter between empty brackets
        b4 = TextBuffer("x = ()")
        b4.cursor = b4.anchor = 5  # between ( and )
        b4.newline()
        self.assertEqual(b4.text, "x = (\n    \n)")
        self.assertEqual(b4.cursor, 10)  # on the middle indented line

        # 5. Multiline call/bracket auto-indent alignment with opening statement
        snippet = (
            "def draw():\n"
            "    with graphics.view(entity.relations[\"camera\"], entity.relations[\"viewport\"]):\n"
            "        for child in query(\"x\", \"y\", \"w\", \"h\", \"color\"):\n"
            "            graphics.rect(child.x, child.y, child.w, child.h,\n"
            "                          color=child.color, key=child.id, layer=1)"
        )
        b5 = TextBuffer(snippet)
        b5.cursor = b5.anchor = len(snippet)
        b5.newline()
        lines5 = b5.text.split("\n")
        self.assertEqual(lines5[-1], "            ")  # Aligns with graphics.rect (12 spaces)

        # 6. Multiline tuple auto-indent
        tuple_code = "    t = (\n        1,\n        2,\n    )"
        b6 = TextBuffer(tuple_code)
        b6.cursor = b6.anchor = len(tuple_code)
        b6.newline()
        lines6 = b6.text.split("\n")
        self.assertEqual(lines6[-1], "    ")  # Aligns with t = ( (4 spaces)

        # 7. Multiline def with colon
        def_code = "    def long_func(\n        arg1,\n        arg2,\n    ):"
        b7 = TextBuffer(def_code)
        b7.cursor = b7.anchor = len(def_code)
        b7.newline()
        lines7 = b7.text.split("\n")
        self.assertEqual(lines7[-1], "        ")  # 8 spaces (4 spaces + 4 for def body)

    def test_delete_word_whitespace_isolation(self):
        # 1. Ctrl+Backspace on trailing spaces stops at preceding punctuation/bracket
        b1 = TextBuffer("foo)   ")
        b1.cursor = b1.anchor = len(b1.text)
        b1.delete_word(backward=True)
        self.assertEqual(b1.text, "foo)")  # Deletes spaces, leaves ')' intact
        b1.delete_word(backward=True)
        self.assertEqual(b1.text, "foo")   # Deletes ')'
        b1.delete_word(backward=True)
        self.assertEqual(b1.text, "")      # Deletes 'foo'

        # 2. Ctrl+Backspace on indented line deletes only line spaces, does not eat across newline
        b2 = TextBuffer("def foo():\n        ")
        b2.cursor = b2.anchor = len(b2.text)
        b2.delete_word(backward=True)
        self.assertEqual(b2.text, "def foo():\n")  # Clears indentation spaces on current line
        b2.delete_word(backward=True)
        self.assertEqual(b2.text, "def foo():")    # Deletes newline
        b2.delete_word(backward=True)
        self.assertEqual(b2.text, "def foo()")     # Deletes colon
        b2.delete_word(backward=True)
        self.assertEqual(b2.text, "def foo(")      # Deletes ')'

        # 3. Forward delete_word whitespace isolation
        b3 = TextBuffer("   foo(123)")
        b3.cursor = b3.anchor = 0
        b3.delete_word(backward=False)
        self.assertEqual(b3.text, "foo(123)")      # Deletes leading spaces only
        b3.delete_word(backward=False)
        self.assertEqual(b3.text, "(123)")         # Deletes 'foo'


