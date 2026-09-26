"""Code editor panel and coding-specific specialization system."""

import ast
import re

from lbe.syntax import highlight_python_lines
from lbe.completion import request_completion, code_context
from time import monotonic
from lbe.ui import put, ERROR, MUTED, ACCENT, PANEL, FIELD, INK

PAIRS = {'(': ')', '[': ']', '{': '}', '"': '"', "'": "'"}
CLOSING = {')': '(', ']': '[', '}': '{', '"': '"', "'": "'"}
EMPTY_PAIRS = {('(', ')'), ('[', ']'), ('{', '}'), ('"', '"'), ("'", "'")}

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


def handle_editor_text(control, event):
    char = event[1]
    control.components["completion_request"] = "auto" if len(char) == 1 and (char.isidentifier() or char == ".") else None
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

    ac_state = control.components.setdefault("autocomplete_state", {"active": False})
    if ctrl and key == "SPACE":
        control.completion_request = "explicit"
        return True
    if ac_state.get("active") and ac_state.get("matches") and not ctrl and not shift:
        matches = ac_state["matches"]
        selected = ac_state.get("selected", 0)
        if key in ("UP", "DOWN"):
            ac_state["selected"] = (selected + (-1 if key == "UP" else 1)) % len(matches)
            return True
        if key == "TAB":
            accept_completion(control, ac_state, selected)
            return True
        if key == "ESCAPE":
            dismiss_completion(control, ac_state)
            return True
    # Navigation, selection, deletion and Enter retain their normal text behavior.
    dismiss_completion(control, ac_state)

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

    return False


def dismiss_completion(control, state):
    state["active"] = False
    state.pop("scheduled", None)
    future = state.pop("future", None)
    if future:
        future.cancel()
    control.components["completion_request"] = None


def accept_completion(control, state, index):
    buffer = control.buffer
    if state.get("snapshot") != (buffer.text, buffer.cursor, buffer.anchor):
        dismiss_completion(control, state)
        return
    chosen = state["matches"][index][0]
    start = buffer.cursor - len(state["prefix"])
    end = buffer.cursor
    while end < len(buffer.text) and (buffer.text[end].isalnum() or buffer.text[end] == "_"):
        end += 1
    buffer.anchor, buffer.cursor = start, end
    buffer.insert(chosen)
    control.components.touch("buffer")
    dismiss_completion(control, state)


def sync_autocomplete_popup(target, ui, ac_state):
    children = {c.components.get("part"): c for c in target.children}

    def part(name, kind, **values):
        if name not in children:
            children[name] = ui.create(target, name, kind, part=name, **values)
        return children[name]

    popup = part("autocomplete_popup", "panel", color=PANEL, layer=target.layer + 3)
    if not ac_state.get("active") or not ac_state.get("matches"):
        put(popup, visible=False)
        for i in range(6):
            item = part(f"ac_item:{i}", "button", layer=target.layer + 4)
            put(item, visible=False)
        return

    matches = ac_state["matches"]
    selected = ac_state.get("selected", 0)
    pitch = target.components.get("pitch", 8)
    line_height = target.components.get("line_height", 20)
    row, col = target.buffer.position
    caret_x = target.x + 48 + (col - target.buffer.horizontal) * pitch
    caret_y = target.y + 6 + (row - target.buffer.scroll) * line_height

    pop_w = min(max(160, max(len(name) for name, _ in matches)*pitch+16), max(40, target.w-64))
    item_h = 20
    pop_h = len(matches) * item_h + 8
    pop_x = max(target.x + 48, min(caret_x, target.x + target.w - pop_w - 10))
    pop_y = caret_y + line_height + 2
    if pop_y + pop_h > target.y + target.h:
        pop_y = max(target.y, caret_y - pop_h - 2)

    put(popup, visible=True, x=pop_x, y=pop_y, w=pop_w, h=pop_h)
    for i in range(6):
        item = part(f"ac_item:{i}", "button", layer=target.layer + 4)
        if i < len(matches):
            name, kind = matches[i]
            is_sel = (i == selected)
            bg_col = (44, 76, 105) if is_sel else FIELD
            def make_action(idx):
                def action():
                    accept_completion(target, ac_state, idx)
                return action
            put(item, visible=True, x=pop_x + 4, y=pop_y + 4 + i * item_h, w=pop_w - 8, h=item_h - 2,
                text=name, color=bg_col, action=make_action(i))
        else:
            put(item, visible=False)


def update(dt):
    """Specialized behaviors for code editing (synchronization, shortcuts, status)."""
    target = entity if "buffer" in entity.components else None
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

    snapshot = (text, buffer.cursor, buffer.anchor)
    request = target.components.pop("completion_request", None)
    if not ui or ui.focused is not target or buffer.cursor != buffer.anchor:
        dismiss_completion(target, ac_state)
    else:
        if ac_state.get("snapshot") != snapshot:
            dismiss_completion(target, ac_state)
        if request:
            prefix = re.search(r"[A-Za-z_]\w*$", text[:buffer.cursor])
            member = bool(re.search(r"\.[A-Za-z_]*$", text[:buffer.cursor]))
            if code_context(text, buffer.cursor) and (request == "explicit" or member or (prefix and len(prefix.group()) >= 2)):
                ac_state["snapshot"] = snapshot
                ac_state["scheduled"] = monotonic() + (0.2 if request == "auto" else 0)
        if "scheduled" in ac_state and monotonic() >= ac_state["scheduled"]:
            ac_state.pop("scheduled")
            context = target.components.get("completion_context")
            if context is None:
                context = target.components.get("completion_components", ())
            ac_state["future"] = request_completion(text, buffer.cursor,
                target.components.get("source_path", project / "untitled.py"),
                context)
        future = ac_state.get("future")
        if future is not None and future.done():
            ac_state.pop("future")
            try:
                prefix, matches = future.result()
                target.components.pop("completion_error", None)
            except Exception as error:
                target.components["completion_error"] = str(error)
                prefix, matches = "", []
            if ac_state.get("snapshot") == snapshot:
                ac_state.update(active=bool(matches), matches=matches, prefix=prefix, selected=0)

    # Sync Autocomplete Popup UI
    if ui:
        sync_autocomplete_popup(target, ui, ac_state)


def stop():
    state = entity.components.get('autocomplete_state')
    if state is not None:
        dismiss_completion(entity, state)
