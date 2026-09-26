"""Small platform-independent text buffer used by entity-based controls."""

import re


class TextBuffer:
    def __init__(self, text=""):
        self.text = text
        self.cursor = 0
        self.anchor = 0
        self.scroll = 0
        self.horizontal = 0
        self._undo = []
        self._redo = []

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        self._text = value.replace("\r\n", "\n").replace("\r", "\n") if value else ""


    @property
    def selection(self):
        return tuple(sorted((self.anchor, self.cursor)))

    @property
    def selected_text(self):
        start, end = self.selection
        return self.text[start:end]

    @property
    def position(self):
        prefix = self.text[:self.cursor]
        return prefix.count("\n"), len(prefix.rsplit("\n", 1)[-1])

    def index(self, row, column):
        lines = self.text.split("\n")
        row = max(0, min(row, len(lines) - 1))
        return sum(len(line) + 1 for line in lines[:row]) + max(0, min(column, len(lines[row])))

    def _snapshot(self):
        return self.text, self.cursor, self.anchor

    def insert(self, text):
        if not text:
            text = ""
        else:
            text = text.replace("\r\n", "\n").replace("\r", "\n")
        self._undo.append(self._snapshot())
        del self._undo[:-200]
        self._redo.clear()
        start, end = self.selection
        self.text = self.text[:start] + text + self.text[end:]
        self.cursor = self.anchor = start + len(text)

    def delete(self, backward=True):
        if self.cursor == self.anchor:
            self.anchor = max(0, self.cursor - 1) if backward else min(len(self.text), self.cursor + 1)
        if self.cursor != self.anchor:
            self.insert("")

    def delete_word(self, backward=True):
        if self.cursor != self.anchor:
            self.insert("")
            return
        orig = self.cursor
        if backward:
            target = orig
            while target > 0 and self.text[target - 1].isspace():
                target -= 1
            if target > 0:
                ch = self.text[target - 1]
                if ch.isalnum() or ch == '_':
                    while target > 0 and (self.text[target - 1].isalnum() or self.text[target - 1] == '_'):
                        target -= 1
                else:
                    p_char = ch
                    while target > 0 and self.text[target - 1] == p_char:
                        target -= 1
            self.anchor = max(0, target)
        else:
            target = orig
            while target < len(self.text) and self.text[target].isspace():
                target += 1
            if target < len(self.text):
                ch = self.text[target]
                if ch.isalnum() or ch == '_':
                    while target < len(self.text) and (self.text[target].isalnum() or self.text[target] == '_'):
                        target += 1
                else:
                    p_char = ch
                    while target < len(self.text) and self.text[target] == p_char:
                        target += 1
            self.anchor = min(len(self.text), target)
        if self.cursor != self.anchor:
            self.insert("")

    def move(self, direction, select=False):
        row, column = self.position
        if direction == "LEFT":
            target = self.cursor - 1
        elif direction == "RIGHT":
            target = self.cursor + 1
        elif direction == "UP":
            target = self.index(row - 1, column)
        elif direction == "DOWN":
            target = self.index(row + 1, column)
        elif direction == "HOME":
            target = self.index(row, 0)
        elif direction == "END":
            target = self.index(row, 10**9)
        elif direction == "FILE_HOME":
            target = 0
        elif direction == "FILE_END":
            target = len(self.text)
        elif direction in ("PAGEUP", "PAGEDOWN"):
            target = self.index(row + (-20 if direction == "PAGEUP" else 20), column)
        elif direction == "WORD_LEFT":
            target = self.cursor
            while target > 0 and self.text[target - 1].isspace():
                target -= 1
            if target > 0:
                is_id = self.text[target - 1].isalnum() or self.text[target - 1] == '_'
                while target > 0 and not self.text[target - 1].isspace() and (self.text[target - 1].isalnum() or self.text[target - 1] == '_') == is_id:
                    target -= 1
        elif direction == "WORD_RIGHT":
            target = self.cursor
            if target < len(self.text):
                is_id = self.text[target].isalnum() or self.text[target] == '_'
                while target < len(self.text) and not self.text[target].isspace() and (self.text[target].isalnum() or self.text[target] == '_') == is_id:
                    target += 1
            while target < len(self.text) and self.text[target].isspace():
                target += 1
        else:
            return
        if not select and self.cursor != self.anchor and direction in ("LEFT", "RIGHT", "WORD_LEFT", "WORD_RIGHT"):
            target = min(self.selection) if direction in ("LEFT", "WORD_LEFT") else max(self.selection)
        self.cursor = max(0, min(target, len(self.text)))
        if not select:
            self.anchor = self.cursor

    def newline(self):
        start = self.text.rfind("\n", 0, self.cursor) + 1
        line = self.text[start:self.cursor]
        base_indent = line[:len(line) - len(line.lstrip(" "))]
        indent = base_indent
        code_part = re.sub(r"#.*$", "", line).rstrip()
        if code_part.endswith(":"):
            indent += "    "
        else:
            line_opens = sum(1 for c in code_part if c in "([{")
            line_closes = sum(1 for c in code_part if c in ")]}")
            if line_opens > line_closes:
                indent += "    "
        # Check if cursor is between an open and close bracket pair, e.g. ( | )
        if 0 < self.cursor < len(self.text):
            pair = (self.text[self.cursor - 1], self.text[self.cursor])
            if pair in (('(', ')'), ('[', ']'), ('{', '}')):
                start_cursor = self.cursor
                self.insert("\n" + indent + "\n" + base_indent)
                self.cursor = self.anchor = start_cursor + len("\n" + indent)
                return
        self.insert("\n" + indent)

    def undo(self, redo=False):
        source, target = (self._redo, self._undo) if redo else (self._undo, self._redo)
        if source:
            target.append(self._snapshot())
            self.text, self.cursor, self.anchor = source.pop()

    def reveal(self, rows, columns):
        row, col = self.position
        self.scroll = max(0, min(self.scroll, row))
        if row >= self.scroll + rows:
            self.scroll = row - rows + 1
        self.horizontal = max(0, min(self.horizontal, col))
        if col >= self.horizontal + columns:
            self.horizontal = col - columns + 1
