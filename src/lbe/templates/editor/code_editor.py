"""Code editor panel and coding-specific specialization system."""

import ast
import keyword
import re

from lbe.syntax import highlight_python_lines, KEYWORDS, BUILTINS, LITERALS
from lbe.ui import put, ERROR, MUTED, ACCENT, PANEL, FIELD, INK

PAIRS = {'(': ')', '[': ']', '{': '}', '"': '"', "'": "'"}
CLOSING = {')': '(', ']': '[', '}': '{', '"': '"', "'": "'"}
EMPTY_PAIRS = {('(', ')'), ('[', ']'), ('{', '}'), ('"', '"'), ("'", "'")}

COMPLETIONS_ENTITY = [
    ("x", "comp"), ("y", "comp"), ("w", "comp"), ("h", "comp"),
    ("vx", "comp"), ("vy", "comp"), ("color", "comp"), ("layer", "comp"),
    ("visible", "comp"), ("name", "comp"), ("pitch", "comp"), ("line_height", "comp"),
    ("components", "prop"), ("tags", "prop"), ("relations", "prop"), ("systems", "prop"),
    ("children", "prop"), ("parent", "prop"), ("id", "prop"), ("alive", "prop"),
    ("depth", "prop"), ("touch", "method"), ("ancestors", "prop"), ("descendants", "prop"),
    ("root", "prop"), ("runtime", "prop"),
]

COMPLETIONS_COMPONENTS = [
    ("get", "method"), ("touch", "method"), ("setdefault", "method"),
    ("keys", "method"), ("values", "method"), ("items", "method"), ("pop", "method"),
]

COMPLETIONS_SYSTEMS = [
    ("attach", "method"), ("reload", "method"), ("detach", "method"),
    ("keys", "method"), ("values", "method"), ("items", "method"),
]

COMPLETIONS_CONVENTIONS = [
    ("update", "func"), ("draw", "func"), ("start", "func"), ("stop", "func"),
    ("entity", "var"), ("dt", "var"), ("runtime", "var"), ("self", "var"),
    ("print", "builtin"), ("len", "builtin"), ("range", "builtin"),
    ("int", "builtin"), ("float", "builtin"), ("str", "builtin"), ("bool", "builtin"),
    ("list", "builtin"), ("dict", "builtin"), ("set", "builtin"), ("tuple", "builtin"),
    ("isinstance", "builtin"), ("True", "literal"), ("False", "literal"), ("None", "literal"),
] + [(kw, "kw") for kw in keyword.kwlist]


def check_diagnostics(source):
    """Detect syntax and compile errors via ast.parse."""
    if not source:
        return None
    try:
        ast.parse(source)
        return None
    except SyntaxError as err:
        return {
            "type": "syntax",
            "line": err.lineno or 1,
            "column": err.offset or 1,
            "end_line": getattr(err, "end_lineno", err.lineno) or (err.lineno or 1),
            "end_column": getattr(err, "end_col_offset", (err.offset or 1) + 1) or ((err.offset or 1) + 1),
            "message": err.msg or "syntax error",
        }


def text_index_to_pos(text, index):
    prefix = text[:index]
    return prefix.count("\n"), len(prefix.rsplit("\n", 1)[-1])


def find_matching_brackets(text, cursor):
    """Find (open_pos, close_pos) for a bracket adjacent to the cursor."""
    if not text or cursor < 0 or cursor > len(text):
        return None
    candidates = []
    if cursor > 0:
        candidates.append((cursor - 1, text[cursor - 1]))
    if cursor < len(text):
        candidates.append((cursor, text[cursor]))

    for pos, ch in candidates:
        if ch in ('(', '[', '{'):
            open_ch = ch
            close_ch = PAIRS[open_ch]
            depth = 1
            idx = pos + 1
            while idx < len(text):
                c = text[idx]
                if c == open_ch:
                    depth += 1
                elif c == close_ch:
                    depth -= 1
                    if depth == 0:
                        return (text_index_to_pos(text, pos), text_index_to_pos(text, idx))
                idx += 1
        elif ch in (')', ']', '}'):
            close_ch = ch
            open_ch = CLOSING[close_ch]
            depth = 1
            idx = pos - 1
            while idx >= 0:
                c = text[idx]
                if c == close_ch:
                    depth += 1
                elif c == open_ch:
                    depth -= 1
                    if depth == 0:
                        return (text_index_to_pos(text, idx), text_index_to_pos(text, pos))
                idx -= 1
    return None


def get_completion_candidates(line_prefix, doc_text):
    """Determine context-sensitive completion candidates and matching prefix."""
    m = re.search(r'(?:entity|self|target|parent|child|other)\.([a-zA-Z_]*)$', line_prefix)
    if m:
        return m.group(1), COMPLETIONS_ENTITY
    m = re.search(r'(?:components|relations|tags)\.([a-zA-Z_]*)$', line_prefix)
    if m:
        return m.group(1), COMPLETIONS_COMPONENTS
    m = re.search(r'systems\.([a-zA-Z_]*)$', line_prefix)
    if m:
        return m.group(1), COMPLETIONS_SYSTEMS
    m = re.search(r'\.([a-zA-Z_]*)$', line_prefix)
    if m:
        return m.group(1), COMPLETIONS_ENTITY + COMPLETIONS_COMPONENTS
    m = re.search(r'\b([a-zA-Z_]\w*)$', line_prefix)
    if m:
        word_prefix = m.group(1)
        doc_words = set(re.findall(r'\b[a-zA-Z_]\w*\b', doc_text)) - {word_prefix}
        extra = [(w, "word") for w in sorted(doc_words) if not any(w == c[0] for c in COMPLETIONS_CONVENTIONS)]
        return word_prefix, COMPLETIONS_CONVENTIONS + extra
    return "", []


def handle_editor_text(control, event):
    char = event[1]
    buffer = control.buffer
    start, end = buffer.selection

    # 1. Selection wrapping
    if start < end and char in PAIRS:
        close_char = PAIRS[char]
        selected = buffer.selected_text
        buffer.insert(char + selected + close_char)
        buffer.anchor = start + 1
        buffer.cursor = start + 1 + len(selected)
        control.components.touch("buffer")
        return True

    # 2. Type-over closing delimiter
    if start == end and char in CLOSING:
        if buffer.cursor < len(buffer.text) and buffer.text[buffer.cursor] == char:
            buffer.move("RIGHT")
            control.components.touch("buffer")
            return True

    # 3. Auto-close opening delimiter
    if start == end and char in PAIRS:
        # Don't auto-close quotes inside words
        if char in ("'", '"') and buffer.cursor > 0 and buffer.text[buffer.cursor - 1].isalnum():
            return False
        close_char = PAIRS[char]
        buffer.insert(char + close_char)
        buffer.cursor = buffer.anchor = start + 1
        control.components.touch("buffer")
        return True

    return False


def handle_editor_key(control, event):
    key, ctrl, shift = event[1:]
    buffer = control.buffer
    start, end = buffer.selection

    ac_state = control.components.get("autocomplete_state")
    if ac_state and ac_state.get("active") and ac_state.get("matches"):
        matches = ac_state["matches"]
        selected = ac_state.get("selected", 0)
        if key == "UP":
            ac_state["selected"] = (selected - 1) % len(matches)
            control.components.touch("autocomplete_state")
            return True
        elif key == "DOWN":
            ac_state["selected"] = (selected + 1) % len(matches)
            control.components.touch("autocomplete_state")
            return True
        elif key in ("TAB", "ENTER", "RETURN"):
            prefix = ac_state.get("prefix", "")
            chosen = matches[selected][0]
            prefix_len = len(prefix)
            buffer.anchor = buffer.cursor - prefix_len
            buffer.insert(chosen)
            buffer.anchor = buffer.cursor
            ac_state["active"] = False
            control.components.touch("autocomplete_state")
            control.components.touch("buffer")
            return True
        elif key == "ESCAPE":
            ac_state["active"] = False
            control.components.touch("autocomplete_state")
            return True

    # Backspace deleting empty pair
    if key == "BACKSPACE" and not ctrl and start == end:
        if 0 < buffer.cursor < len(buffer.text):
            pair = (buffer.text[buffer.cursor - 1], buffer.text[buffer.cursor])
            if pair in EMPTY_PAIRS:
                buffer.anchor = buffer.cursor - 1
                buffer.cursor = buffer.cursor + 1
                buffer.insert("")
                control.components.touch("buffer")
                return True

    # Dismiss autocomplete on navigation keys
    if key in ("LEFT", "RIGHT", "HOME", "END", "PAGEUP", "PAGEDOWN"):
        if ac_state and ac_state.get("active"):
            ac_state["active"] = False
            control.components.touch("autocomplete_state")

    return False


def sync_autocomplete_popup(target, ui, ac_state):
    children = {c.components.get("part"): c for c in target.children}

    def part(name, kind, **values):
        if name not in children:
            children[name] = ui.create(target, name, kind, part=name, **values)
        return children[name]

    popup = part("autocomplete_popup", "panel", color=PANEL, layer=target.layer + 5)
    if not ac_state.get("active") or not ac_state.get("matches"):
        put(popup, visible=False)
        for i in range(6):
            item = part(f"ac_item:{i}", "button", layer=target.layer + 6)
            put(item, visible=False)
        return

    matches = ac_state["matches"]
    selected = ac_state.get("selected", 0)
    pitch = target.components.get("pitch", 8)
    line_height = target.components.get("line_height", 20)
    row, col = target.buffer.position
    caret_x = target.x + 48 + (col - target.buffer.horizontal) * pitch
    caret_y = target.y + 6 + (row - target.buffer.scroll) * line_height

    pop_w = 180
    item_h = 20
    pop_h = len(matches) * item_h + 8
    pop_x = max(target.x + 48, min(caret_x, target.x + target.w - pop_w - 10))
    pop_y = caret_y + line_height + 2
    if pop_y + pop_h > target.y + target.h:
        pop_y = max(target.y, caret_y - pop_h - 2)

    put(popup, visible=True, x=pop_x, y=pop_y, w=pop_w, h=pop_h)
    for i in range(6):
        item = part(f"ac_item:{i}", "button", layer=target.layer + 6)
        if i < len(matches):
            name, kind = matches[i]
            is_sel = (i == selected)
            bg_col = (44, 76, 105) if is_sel else FIELD
            def make_action(idx):
                def action():
                    chosen = matches[idx][0]
                    prefix_len = len(ac_state.get("prefix", ""))
                    target.buffer.anchor = target.buffer.cursor - prefix_len
                    target.buffer.insert(chosen)
                    target.buffer.anchor = target.buffer.cursor
                    ac_state["active"] = False
                    target.components.touch("autocomplete_state")
                    target.components.touch("buffer")
                return action
            put(item, visible=True, x=pop_x + 4, y=pop_y + 4 + i * item_h, w=pop_w - 8, h=item_h - 2,
                text=f"{name}  [{kind}]", color=bg_col, action=make_action(i))
        else:
            put(item, visible=False)


def update(dt):
    """Specialized behaviors for code editing (synchronization, shortcuts, status)."""
    target = entity if "buffer" in entity.components else next((c for c in entity.descendants if "buffer" in c.components), None)
    if target is None:
        return

    # Ensure input hooks are attached
    target.components["on_text"] = handle_editor_text
    target.components["on_key"] = handle_editor_key

    buffer = target.buffer
    text = buffer.text

    # 1. Syntax highlighting
    last_text = target.components.get("_last_highlight_text")
    if last_text != text:
        target.components["line_spans"] = highlight_python_lines(text)
        target.components["_last_highlight_text"] = text

    # 2. Syntax / compile error diagnostics
    last_diag_text = target.components.get("_last_diag_text")
    if last_diag_text != text:
        target.components["diagnostic"] = check_diagnostics(text)
        target.components["_last_diag_text"] = text

    # 3. Bracket matching
    target.components["matching_brackets"] = find_matching_brackets(text, buffer.cursor)

    # 4. Autocomplete
    ui = target.root.components.get("ui")
    ac_state = target.components.setdefault("autocomplete_state", {"active": False, "matches": [], "selected": 0, "prefix": ""})

    is_focused = ui and ui.focused is target
    if not is_focused:
        ac_state["active"] = False
    else:
        line_prefix = text[:buffer.cursor].rsplit("\n", 1)[-1]
        word_prefix, candidates = get_completion_candidates(line_prefix, text)
        is_member_access = bool(re.search(r'\.[a-zA-Z_]*$', line_prefix))
        if word_prefix or (is_member_access and candidates):
            matches = [c for c in candidates if c[0].lower().startswith(word_prefix.lower()) and c[0] != word_prefix]
            matches.sort(key=lambda c: (not c[0].startswith(word_prefix), len(c[0]), c[0]))
            matches = matches[:6]
            if matches and (ac_state.get("active") or is_member_access or len(word_prefix) >= 2):
                ac_state["active"] = True
                ac_state["matches"] = matches
                ac_state["prefix"] = word_prefix
                if ac_state["selected"] >= len(matches):
                    ac_state["selected"] = 0
            else:
                ac_state["active"] = False
        else:
            ac_state["active"] = False

    # Sync Autocomplete Popup UI
    if ui:
        sync_autocomplete_popup(target, ui, ac_state)
