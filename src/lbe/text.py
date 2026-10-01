"""Small platform-independent text buffer used by entity-based controls."""

import re


def compute_newline_indent(text, cursor):
    line_start = text.rfind("\n", 0, cursor) + 1
    current_line = text[line_start:cursor]
    base_indent = current_line[:len(current_line) - len(current_line.lstrip(" "))]
    code_part = re.sub(r"#.*$", "", current_line).rstrip()

    BRACKETS = {")": "(", "]": "[", "}": "{"}
    stack = []  # list of (char, line_start, first_arg_col)
    closed_from_prev = []  # list of (char, line_start, first_arg_col)
    cur_line_start = 0
    i = 0
    in_str = None
    while i < cursor:
        c = text[i]
        if c == "\n":
            cur_line_start = i + 1
            i += 1
            continue
        if in_str:
            if c == "\\":
                i += 2
                continue
            if in_str in ('"""', "'''"):
                if text[i:i + 3] == in_str:
                    in_str = None
                    i += 3
                    continue
            elif c == in_str:
                in_str = None
                i += 1
                continue
            i += 1
            continue
        if text[i:i + 3] in ('"""', "'''"):
            in_str = text[i:i + 3]
            i += 3
            continue
        if c in ('"', "'"):
            in_str = c
            i += 1
            continue
        if c == "#":
            next_nl = text.find("\n", i, cursor)
            if next_nl == -1:
                break
            i = next_nl
            continue
        if c in "([{":
            j = i + 1
            while j < cursor and text[j] not in "\n#)]}":
                if not text[j].isspace():
                    break
                j += 1
            first_arg_col = (j - cur_line_start) if (j < cursor and text[j] not in "\n#)]}") else None
            stack.append((c, cur_line_start, first_arg_col))
        elif c in ")]}":
            if stack and stack[-1][0] == BRACKETS[c]:
                opened = stack.pop()
                if cur_line_start == line_start and opened[1] < line_start:
                    closed_from_prev.append(opened)
        i += 1

    # 1. Closed multiline bracket on this line
    if closed_from_prev:
        outer = closed_from_prev[0]
        open_line_end = text.find("\n", outer[1])
        if open_line_end == -1 or open_line_end > len(text):
            open_line_end = len(text)
        open_line = text[outer[1]:open_line_end]
        open_base = open_line[:len(open_line) - len(open_line.lstrip(" "))]
        if code_part.endswith(":"):
            return open_base + "    "
        return open_base

    # 2. Ends with colon
    if code_part.endswith(":"):
        return base_indent + "    "

    # 3. Inside unclosed bracket
    if stack:
        top = stack[-1]
        if top[2] is not None:
            return " " * top[2]
        return base_indent + "    "

    return base_indent


class TextBuffer:
    def __init__(self, text=""):
        self.text = text
        self.cursor = 0
        self.anchor = 0
        self.scroll = 0
        self.horizontal = 0
        self.preferred_column = None
        self._undo = []
        self._redo = []

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        self._text = value.replace("\r\n", "\n").replace("\r", "\n") if value else ""
        self._lines = None

    @property
    def lines(self):
        if self._lines is None:
            self._lines = tuple(self.text.split("\n"))
        return self._lines

    @property
    def selection(self):
        return tuple(sorted((self.anchor, self.cursor)))

    @property
    def has_selection(self):
        return self.anchor != self.cursor

    @property
    def selected_text(self):
        start, end = self.selection
        return self.text[start:end]

    @property
    def position(self):
        prefix = self.text[:self.cursor]
        return prefix.count("\n"), len(prefix.rsplit("\n", 1)[-1])

    def index(self, row, column):
        lines = self.lines
        row = max(0, min(row, len(lines) - 1))
        return sum(len(line) + 1 for line in lines[:row]) + max(0, min(column, len(lines[row])))

    def _snapshot(self):
        return self.text, self.cursor, self.anchor

    def insert(self, text):
        self.preferred_column = None
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
            if target == 0:
                return
            if self.text[target - 1] == "\n":
                target -= 1
            elif self.text[target - 1] in " \t":
                while target > 0 and self.text[target - 1] in " \t":
                    target -= 1
            elif self.text[target - 1].isalnum() or self.text[target - 1] == "_":
                while target > 0 and (self.text[target - 1].isalnum() or self.text[target - 1] == "_"):
                    target -= 1
            else:
                p_char = self.text[target - 1]
                while target > 0 and self.text[target - 1] == p_char:
                    target -= 1
            self.anchor = max(0, target)
        else:
            target = orig
            if target >= len(self.text):
                return
            if self.text[target] == "\n":
                target += 1
            elif self.text[target] in " \t":
                while target < len(self.text) and self.text[target] in " \t":
                    target += 1
            elif self.text[target].isalnum() or self.text[target] == "_":
                while target < len(self.text) and (self.text[target].isalnum() or self.text[target] == "_"):
                    target += 1
            else:
                p_char = self.text[target]
                while target < len(self.text) and self.text[target] == p_char:
                    target += 1
            self.anchor = min(len(self.text), target)
        if self.cursor != self.anchor:
            self.insert("")

    def move(self, direction, select=False):
        row, column = self.position
        if direction in ("UP", "DOWN", "PAGEUP", "PAGEDOWN"):
            if self.preferred_column is None:
                self.preferred_column = column
            target_col = self.preferred_column
        else:
            self.preferred_column = None
            target_col = column

        if direction == "LEFT":
            target = self.cursor - 1
        elif direction == "RIGHT":
            target = self.cursor + 1
        elif direction == "UP":
            target = self.index(row - 1, target_col)
        elif direction == "DOWN":
            target = self.index(row + 1, target_col)
        elif direction == "HOME":
            lines = self.lines
            line = lines[row] if row < len(lines) else ""
            first_non_ws = len(line) - len(line.lstrip(" \t"))
            if column == first_non_ws:
                target = self.index(row, 0)
            else:
                target = self.index(row, first_non_ws)
        elif direction == "END":
            target = self.index(row, 10**9)
        elif direction == "FILE_HOME":
            target = 0
        elif direction == "FILE_END":
            target = len(self.text)
        elif direction in ("PAGEUP", "PAGEDOWN"):
            target = self.index(row + (-20 if direction == "PAGEUP" else 20), target_col)
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
        line_start = self.text.rfind("\n", 0, self.cursor) + 1
        line = self.text[line_start:self.cursor]
        base_indent = line[:len(line) - len(line.lstrip(" "))]
        indent = compute_newline_indent(self.text, self.cursor)
        # Check if cursor is between an open and close bracket pair, e.g. ( | )
        if 0 < self.cursor < len(self.text):
            pair = (self.text[self.cursor - 1], self.text[self.cursor])
            if pair in (('(', ')'), ('[', ']'), ('{', '}')):
                start_cursor = self.cursor
                self.insert("\n" + indent + "\n" + base_indent)
                self.cursor = self.anchor = start_cursor + len("\n" + indent)
                return
        self.insert("\n" + indent)

    def indent(self, dedent=False):
        """Indent or dedent the current line or selected lines by 4 spaces with atomic undo."""
        self.preferred_column = None
        start, end = self.selection
        if start == end and not dedent:
            self.insert("    ")
            return

        self._undo.append(self._snapshot())
        del self._undo[:-200]
        self._redo.clear()

        start_row = self.text[:start].count("\n")
        if end > start and self.text[end - 1] == "\n":
            end_row = self.text[:end - 1].count("\n")
        else:
            end_row = self.text[:end].count("\n")

        lines = self.lines
        new_lines = list(lines)
        first_line_shift = 0

        for r in range(start_row, end_row + 1):
            line = new_lines[r]
            if dedent:
                count = 0
                for ch in line[:4]:
                    if ch == " ":
                        count += 1
                    elif ch == "\t":
                        count += 1
                        break
                    else:
                        break
                new_lines[r] = line[count:]
                if r == start_row:
                    first_line_shift = -count
            else:
                if line or start == end:
                    new_lines[r] = "    " + line
                    if r == start_row:
                        first_line_shift = 4

        self.text = "\n".join(new_lines)
        if start == end:
            line_start_idx = self.text.rfind("\n", 0, self.cursor) + 1 if self.cursor > 0 else 0
            cur_col = max(0, start - line_start_idx)
            self.cursor = self.anchor = self.index(start_row, max(0, cur_col + first_line_shift))
        else:
            new_start = sum(len(new_lines[i]) + 1 for i in range(start_row))
            new_end = sum(len(new_lines[i]) + 1 for i in range(end_row)) + len(new_lines[end_row])
            if self.anchor <= self.cursor:
                self.anchor = new_start
                self.cursor = new_end
            else:
                self.anchor = new_end
                self.cursor = new_start

    def toggle_comment(self):
        """Toggle Python comment (# ) on the current line or selected lines with atomic undo."""
        self.preferred_column = None
        self._undo.append(self._snapshot())
        del self._undo[:-200]
        self._redo.clear()

        start, end = self.selection
        start_row = self.text[:start].count("\n")
        if end > start and self.text[end - 1] == "\n":
            end_row = self.text[:end - 1].count("\n")
        else:
            end_row = self.text[:end].count("\n")

        lines = self.lines
        new_lines = list(lines)

        non_empty = [new_lines[r] for r in range(start_row, end_row + 1) if new_lines[r].strip()]
        all_commented = bool(non_empty) and all(line.lstrip().startswith("#") for line in non_empty)

        if all_commented:
            for r in range(start_row, end_row + 1):
                line = new_lines[r]
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    ws = line[:len(line) - len(stripped)]
                    rest = stripped[1:]
                    if rest.startswith(" "):
                        rest = rest[1:]
                    new_lines[r] = ws + rest
        else:
            min_indent = min((len(l) - len(l.lstrip(" ")) for l in non_empty), default=0)
            for r in range(start_row, end_row + 1):
                line = new_lines[r]
                if line.strip():
                    ws = line[:min_indent]
                    rest = line[min_indent:]
                    new_lines[r] = ws + "# " + rest
                elif start == end:
                    new_lines[r] = "# "

        self.text = "\n".join(new_lines)
        if start == end:
            self.cursor = self.anchor = self.index(start_row, len(new_lines[start_row]))
        else:
            new_start = sum(len(new_lines[i]) + 1 for i in range(start_row))
            new_end = sum(len(new_lines[i]) + 1 for i in range(end_row)) + len(new_lines[end_row])
            if self.anchor <= self.cursor:
                self.anchor = new_start
                self.cursor = new_end
            else:
                self.anchor = new_end
                self.cursor = new_start

    def undo(self, redo=False):
        self.preferred_column = None
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
