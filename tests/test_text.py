import unittest

from lbe.text import TextBuffer


class TextTests(unittest.TestCase):
    def test_replacing_contents_clamps_selection_before_next_edit(self):
        buffer = TextBuffer('long document')
        buffer.cursor, buffer.anchor = 13, 5
        buffer.text = 'x'
        self.assertEqual((buffer.cursor,buffer.anchor), (1,1))
        buffer.insert('y')
        self.assertEqual(buffer.text, 'xy')
        buffer.undo()
        self.assertEqual((buffer.text,buffer.cursor,buffer.anchor), ('x',1,1))

    def test_range_replacement_validation_and_atomic_undo(self):
        buffer = TextBuffer('abcdef')
        buffer.cursor = buffer.anchor = 3
        for start,end in ((-1,2),(3,2),(0,7),(1.5,2)):
            with self.assertRaises(ValueError):
                buffer.replace(start,end,'x')
        self.assertEqual((buffer.text,buffer.cursor,buffer.anchor), ('abcdef',3,3))
        self.assertFalse(buffer._undo)
        buffer.replace(1,5,'X')
        self.assertEqual(buffer.text, 'aXf')
        buffer.undo()
        self.assertEqual((buffer.text,buffer.cursor,buffer.anchor), ('abcdef',3,3))

    def test_dedent_keeps_caret_on_original_character_before_a_newline(self):
        buffer = TextBuffer('    x\n    y')
        buffer.cursor = buffer.anchor = 5
        buffer.indent(dedent=True)
        self.assertEqual(buffer.text, 'x\n    y')
        self.assertEqual(buffer.position, (0, 1))
        buffer.undo()
        self.assertEqual((buffer.text,buffer.cursor,buffer.anchor), ('    x\n    y',5,5))

    def test_deletion_undo_restores_original_caret_and_selection(self):
        for word in (False, True):
            for backward in (False, True):
                with self.subTest(word=word, backward=backward):
                    buffer = TextBuffer('one two')
                    buffer.cursor = buffer.anchor = 4
                    delete = buffer.delete_word if word else buffer.delete
                    delete(backward=backward)
                    changed = buffer.text, buffer.cursor, buffer.anchor
                    buffer.undo()
                    self.assertEqual((buffer.text,buffer.cursor,buffer.anchor), ('one two',4,4))
                    buffer.undo(redo=True)
                    self.assertEqual((buffer.text,buffer.cursor,buffer.anchor), changed)

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

    def test_delete_word_selection_and_page_navigation(self):
        # delete_word with selection replaces selection
        buf = TextBuffer("hello world")
        buf.anchor, buf.cursor = 0, 5
        buf.delete_word(backward=True)
        self.assertEqual(buf.text, " world")

        # Boundary no-ops
        buf_empty = TextBuffer()
        buf_empty.delete_word(backward=True)
        self.assertEqual(buf_empty.text, "")
        buf_empty.delete_word(backward=False)
        self.assertEqual(buf_empty.text, "")

        # Forward delete at newline
        buf_nl = TextBuffer("line1\nline2")
        buf_nl.cursor = buf_nl.anchor = 5
        buf_nl.delete_word(backward=False)
        self.assertEqual(buf_nl.text, "line1line2")

        # PageUp / PageDown navigation
        lines_text = "\n".join(f"line {i}" for i in range(50))
        buf_lines = TextBuffer(lines_text)
        self.assertEqual(buf_lines.position[0], 0)
        buf_lines.move("PAGEDOWN")
        self.assertEqual(buf_lines.position[0], 20)
        buf_lines.move("PAGEDOWN")
        self.assertEqual(buf_lines.position[0], 40)
        buf_lines.move("PAGEUP")
        self.assertEqual(buf_lines.position[0], 20)

    def test_smart_home_toggle(self):
        """Issue #49: Home toggles between first non-whitespace character and column 0."""
        buf = TextBuffer("    hello world")
        buf.cursor = buf.anchor = len(buf.text)  # at end of line (col 15)

        # 1st Home -> moves to col 4 (first non-whitespace)
        buf.move("HOME")
        self.assertEqual(buf.position, (0, 4))

        # 2nd Home -> moves to col 0
        buf.move("HOME")
        self.assertEqual(buf.position, (0, 0))

        # 3rd Home -> toggles back to col 4
        buf.move("HOME")
        self.assertEqual(buf.position, (0, 4))

        # Shift+Home extends selection
        buf.cursor = buf.anchor = len(buf.text)
        buf.move("HOME", select=True)
        self.assertEqual(buf.selected_text, "hello world")
        buf.move("HOME", select=True)
        self.assertEqual(buf.selected_text, "    hello world")

    def test_preferred_column_preservation(self):
        """Issue #49: Vertical movement through short lines preserves target column."""
        text = (
            "abcdefghijklmnopqrst\n"  # 20 chars
            "12345\n"                 # 5 chars
            "ABCDEFGHIJKLMNOPQRSTUVWXY" # 25 chars
        )
        buf = TextBuffer(text)
        buf.cursor = buf.anchor = 15  # col 15 on line 0
        self.assertEqual(buf.position, (0, 15))

        # Move DOWN to short line 1 -> clamped to col 5
        buf.move("DOWN")
        self.assertEqual(buf.position, (1, 5))

        # Move DOWN to long line 2 -> preferred column 15 restored!
        buf.move("DOWN")
        self.assertEqual(buf.position, (2, 15))

        # Move UP to short line 1 -> clamped to col 5
        buf.move("UP")
        self.assertEqual(buf.position, (1, 5))

        # Move UP to line 0 -> preferred column 15 restored!
        buf.move("UP")
        self.assertEqual(buf.position, (0, 15))

        # Horizontal movement resets preferred column
        buf.move("LEFT")
        self.assertEqual(buf.position, (0, 14))
        buf.move("DOWN")
        self.assertEqual(buf.position, (1, 5))
        buf.move("DOWN")
        self.assertEqual(buf.position, (2, 14))

    def test_tab_and_shift_tab_multiline_indent_dedent(self):
        """Issue #49: Tab indents, Shift+Tab dedents selected lines, with atomic undo."""
        text = "def foo():\n    x = 1\n    y = 2"
        buf = TextBuffer(text)

        # Select lines 1 and 2
        buf.anchor = text.index("    x")
        buf.cursor = len(text)

        # Tab: indent selected lines
        buf.indent(dedent=False)
        self.assertEqual(buf.text, "def foo():\n        x = 1\n        y = 2")

        # Shift+Tab: dedent selected lines
        buf.indent(dedent=True)
        self.assertEqual(buf.text, "def foo():\n    x = 1\n    y = 2")

        # Atomic undo reverses operation in one step
        buf.undo()
        self.assertEqual(buf.text, "def foo():\n        x = 1\n        y = 2")
        buf.undo()
        self.assertEqual(buf.text, "def foo():\n    x = 1\n    y = 2")

        # Single cursor (no selection): Tab inserts 4 spaces
        buf.text = "def foo():\n    x = 1"
        buf.cursor = buf.anchor = len(buf.text)
        buf.indent(dedent=False)
        self.assertEqual(buf.text, "def foo():\n    x = 1    ")

        # Single cursor dedent: removes up to 4 leading spaces from current line
        buf.text = "def foo():\n        x = 1"
        buf.cursor = buf.anchor = len(buf.text)
        buf.indent(dedent=True)
        self.assertEqual(buf.text, "def foo():\n    x = 1")

    def test_toggle_comment_single_and_multiline(self):
        """Issue #49: Ctrl+/ comment toggling on single and multiple lines with atomic undo."""
        text = "def foo():\n    x = 1\n    y = 2"
        buf = TextBuffer(text)

        # 1. Single line comment toggle
        buf.cursor = buf.anchor = text.index("x = 1")
        buf.toggle_comment()
        self.assertEqual(buf.text, "def foo():\n    # x = 1\n    y = 2")
        buf.toggle_comment()
        self.assertEqual(buf.text, "def foo():\n    x = 1\n    y = 2")

        # 2. Multi-line comment toggle
        buf.anchor = text.index("    x")
        buf.cursor = len(text)
        buf.toggle_comment()
        self.assertEqual(buf.text, "def foo():\n    # x = 1\n    # y = 2")

        # Toggle again uncomments
        buf.toggle_comment()
        self.assertEqual(buf.text, "def foo():\n    x = 1\n    y = 2")

        # Atomic undo
        buf.undo()
        self.assertEqual(buf.text, "def foo():\n    # x = 1\n    # y = 2")
        buf.undo()
        self.assertEqual(buf.text, "def foo():\n    x = 1\n    y = 2")

