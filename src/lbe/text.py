"""Small platform-independent text buffer used by entity-based controls."""


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
            while target > 0 and self.text[target-1].isspace():
                target -= 1
            while target > 0 and not self.text[target-1].isspace():
                target -= 1
        elif direction == "WORD_RIGHT":
            target = self.cursor
            while target < len(self.text) and not self.text[target].isspace():
                target += 1
            while target < len(self.text) and self.text[target].isspace():
                target += 1
        else:
            return
        if not select and self.cursor != self.anchor and direction in ("LEFT", "RIGHT"):
            target = min(self.selection) if direction == "LEFT" else max(self.selection)
        self.cursor = max(0, min(target, len(self.text)))
        if not select:
            self.anchor = self.cursor

    def newline(self):
        start = self.text.rfind("\n", 0, self.cursor) + 1
        line = self.text[start:self.cursor]
        indent = line[:len(line) - len(line.lstrip(" "))]
        if line.rstrip().endswith(":"):
            indent += "    "
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
