"""Code editor panel and coding-specific specialization system."""

import ast
import re

from lbe.syntax import highlight_python_lines
from lbe.completion import request_completion, request_hover, code_context
from time import monotonic
from lbe.ui import put, contains, ERROR, MUTED, ACCENT, PANEL, FIELD, INK

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


VISIBLE_ITEMS = 8


def find_open_bracket_indent(text, cursor, close_char):
    if close_char not in CLOSING:
        return None
    open_char = CLOSING[close_char]
    depth = 1
    idx = cursor - 1
    while idx >= 0:
        c = text[idx]
        if c == close_char:
            depth += 1
        elif c == open_char:
            depth -= 1
            if depth == 0:
                line_start = text.rfind("\n", 0, idx) + 1
                open_line = text[line_start:idx]
                return open_line[:len(open_line) - len(open_line.lstrip(" "))]
        idx -= 1
    return None


def handle_editor_text(control, event):
    hover_state = control.components.get("hover_state")
    if hover_state:
        hover_state["active"] = False

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

    # 2. Type-over or dedent closing delimiter
    if start == end and char in CLOSING:
        line_start = buffer.text.rfind("\n", 0, buffer.cursor) + 1
        line_prefix = buffer.text[line_start:buffer.cursor]
        if line_prefix.strip() == "":
            target_indent = find_open_bracket_indent(buffer.text, buffer.cursor, char)
            if target_indent is not None and len(line_prefix) > len(target_indent):
                buffer.anchor = line_start
                buffer.cursor = line_start + len(line_prefix)
                buffer.insert(target_indent)

        if buffer.cursor < len(buffer.text) and buffer.text[buffer.cursor] == char:
            buffer.move("RIGHT")
            control.components.touch("buffer")
            return True
        elif line_prefix.strip() == "":
            buffer.insert(char)
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


def handle_editor_scroll(control, event):
    hover_state = control.components.get("hover_state")
    if hover_state:
        hover_state["active"] = False

    ac_state = control.components.get("autocomplete_state")
    if ac_state and ac_state.get("active") and ac_state.get("matches"):
        children = {c.components.get("part"): c for c in control.children}
        popup = children.get("autocomplete_popup")
        if popup and popup.visible and contains(popup, event[1], event[2]):
            scroll = ac_state.get("scroll", 0)
            max_scroll = max(0, len(ac_state["matches"]) - VISIBLE_ITEMS)
            scroll_dy = event[4]
            ac_state["scroll"] = max(0, min(max_scroll, scroll - int(scroll_dy)))
            control.components.touch("buffer")
            return True
    return False


def handle_editor_key(control, event):
    hover_state = control.components.get("hover_state")
    if hover_state:
        hover_state["active"] = False

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
            new_sel = (selected + (-1 if key == "UP" else 1)) % len(matches)
            ac_state["selected"] = new_sel
            scroll = ac_state.get("scroll", 0)
            if new_sel < scroll:
                ac_state["scroll"] = new_sel
            elif new_sel >= scroll + VISIBLE_ITEMS:
                ac_state["scroll"] = new_sel - VISIBLE_ITEMS + 1
            return True
        if key in ("PAGEUP", "PAGEDOWN"):
            delta = -VISIBLE_ITEMS if key == "PAGEUP" else VISIBLE_ITEMS
            new_sel = max(0, min(len(matches) - 1, selected + delta))
            ac_state["selected"] = new_sel
            scroll = ac_state.get("scroll", 0)
            if new_sel < scroll:
                ac_state["scroll"] = new_sel
            elif new_sel >= scroll + VISIBLE_ITEMS:
                ac_state["scroll"] = new_sel - VISIBLE_ITEMS + 1
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
    state["scroll"] = 0
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
    scrollbar_track = part("ac_scroll_track", "panel", color=(20, 26, 35), layer=target.layer + 4)
    scrollbar_thumb = part("ac_scroll_thumb", "panel", color=ACCENT, layer=target.layer + 5)

    if not ac_state.get("active") or not ac_state.get("matches"):
        put(popup, visible=False)
        put(scrollbar_track, visible=False)
        put(scrollbar_thumb, visible=False)
        for i in range(VISIBLE_ITEMS):
            item = part(f"ac_item:{i}", "button", layer=target.layer + 4)
            put(item, visible=False)
        return

    matches = ac_state["matches"]
    selected = ac_state.get("selected", 0)
    scroll = max(0, min(ac_state.get("scroll", 0), max(0, len(matches) - VISIBLE_ITEMS)))
    ac_state["scroll"] = scroll

    pitch = target.components.get("pitch", 8)
    line_height = target.components.get("line_height", 20)
    row, col = target.buffer.position
    caret_x = target.x + 48 + (col - target.buffer.horizontal) * pitch
    caret_y = target.y + 6 + (row - target.buffer.scroll) * line_height

    num_visible = min(len(matches), VISIBLE_ITEMS)
    item_h = 20
    pop_h = num_visible * item_h + 8
    max_name_len = max(len(m[0]) for m in matches[:50])
    pop_w = min(max(180, max_name_len * pitch + 32), max(40, target.w - 64))
    pop_x = max(target.x + 48, min(caret_x, target.x + target.w - pop_w - 10))
    pop_y = caret_y + line_height + 2
    if pop_y + pop_h > target.y + target.h:
        pop_y = max(target.y, caret_y - pop_h - 2)

    put(popup, visible=True, x=pop_x, y=pop_y, w=pop_w, h=pop_h)

    has_scrollbar = len(matches) > VISIBLE_ITEMS
    btn_w = pop_w - 18 if has_scrollbar else pop_w - 8

    for i in range(VISIBLE_ITEMS):
        item = part(f"ac_item:{i}", "button", layer=target.layer + 4)
        match_idx = scroll + i
        if match_idx < len(matches):
            name, kind = matches[match_idx]
            is_sel = (match_idx == selected)
            bg_col = (44, 76, 105) if is_sel else FIELD
            def make_action(idx):
                def action():
                    accept_completion(target, ac_state, idx)
                return action
            put(item, visible=True, x=pop_x + 4, y=pop_y + 4 + i * item_h, w=btn_w, h=item_h - 2,
                text=name, color=bg_col, action=make_action(match_idx))
        else:
            put(item, visible=False)

    if has_scrollbar:
        track_x = pop_x + pop_w - 10
        track_y = pop_y + 4
        track_h = pop_h - 8
        put(scrollbar_track, visible=True, x=track_x, y=track_y, w=6, h=track_h)
        thumb_h = max(8, int(track_h * (VISIBLE_ITEMS / len(matches))))
        max_scroll = len(matches) - VISIBLE_ITEMS
        thumb_y = track_y + int((track_h - thumb_h) * (scroll / max_scroll))
        put(scrollbar_thumb, visible=True, x=track_x, y=thumb_y, w=6, h=thumb_h)
    else:
        put(scrollbar_track, visible=False)
        put(scrollbar_thumb, visible=False)


def sync_hover_tooltip(target, ui, hover_state):
    children = {c.components.get("part"): c for c in target.children}

    def part(name, kind, **values):
        if name not in children:
            children[name] = ui.create(target, name, kind, part=name, **values)
        return children[name]

    tip_panel = part("hover_panel", "panel", color=(25, 34, 45), layer=target.layer + 6)
    tip_title = part("hover_title", "label", layer=target.layer + 7, ink=ACCENT)
    tip_doc = part("hover_doc", "label", layer=target.layer + 7, ink=INK)

    if not hover_state.get("active") or not hover_state.get("info"):
        put(tip_panel, visible=False)
        put(tip_title, visible=False)
        put(tip_doc, visible=False)
        return

    info = hover_state["info"]
    mx, my = hover_state.get("hover_pos", (target.x, target.y))
    pitch = target.components.get("pitch", 8)

    title_text = info.get("description", info.get("name", ""))
    doc_text = info.get("docstring", "")
    if len(doc_text) > 300:
        doc_text = doc_text[:300] + "..."

    has_doc = bool(doc_text)
    tip_w = min(max(200, max(len(title_text) * pitch + 24, 200)), max(100, target.w - 32))
    tip_h = 24 + (24 if has_doc else 0)

    tip_x = max(target.x + 8, min(mx + 10, target.x + target.w - tip_w - 8))
    tip_y = my + 18
    if tip_y + tip_h > target.y + target.h:
        tip_y = max(target.y + 4, my - tip_h - 6)

    put(tip_panel, visible=True, x=tip_x, y=tip_y, w=tip_w, h=tip_h)
    put(tip_title, visible=True, x=tip_x + 8, y=tip_y + 4, w=tip_w - 16, h=16, text=title_text)
    if has_doc:
        first_line = doc_text.split("\n")[0][:65]
        put(tip_doc, visible=True, x=tip_x + 8, y=tip_y + 22, w=tip_w - 16, h=16, text=first_line)
    else:
        put(tip_doc, visible=False)


def update(dt):
    """Specialized behaviors for code editing (synchronization, shortcuts, status)."""
    target = entity if "buffer" in entity.components else None
    if target is None:
        return

    # Ensure input hooks are attached
    target.components["on_text"] = handle_editor_text
    target.components["on_key"] = handle_editor_key
    target.components["on_scroll"] = handle_editor_scroll

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
    ac_state = target.components.setdefault("autocomplete_state", {"active": False, "matches": [], "selected": 0, "scroll": 0, "prefix": ""})

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
                ac_state.update(active=bool(matches), matches=matches, prefix=prefix, selected=0, scroll=0)

    # 5. Hover inspection
    hover_state = target.components.setdefault("hover_state", {"active": False, "dwell_start": 0.0, "last_mouse": (-100, -100)})
    mouse_pos = getattr(ui, "mouse_pos", None)
    if ui and mouse_pos and contains(target, mouse_pos[0], mouse_pos[1]) and not ac_state.get("active"):
        mx, my = mouse_pos
        last_mx, last_my = hover_state.get("last_mouse", (-100, -100))
        if abs(mx - last_mx) > 4 or abs(my - last_my) > 4:
            hover_state["last_mouse"] = (mx, my)
            hover_state["dwell_start"] = monotonic()
            hover_state["active"] = False
            fut = hover_state.pop("future", None)
            if fut:
                fut.cancel()
        else:
            if not hover_state.get("active") and not hover_state.get("future"):
                if monotonic() - hover_state.get("dwell_start", monotonic()) >= 0.35:
                    pitch = target.components.get("pitch", 8)
                    line_h = target.components.get("line_height", 20)
                    h_row = max(0, int((my - target.y - 6) // line_h)) + buffer.scroll
                    h_col = max(0, round((mx - target.x - 48) / pitch)) + buffer.horizontal
                    lines = text.split("\n")
                    if 0 <= h_row < len(lines) and h_col < len(lines[h_row]):
                        line_str = lines[h_row]
                        if line_str and (line_str[min(h_col, len(line_str) - 1)].isalnum() or line_str[min(h_col, len(line_str) - 1)] == "_"):
                            context = target.components.get("completion_context") or target.components.get("completion_components", ())
                            hover_state["future"] = request_hover(text, h_row, h_col, target.components.get("source_path", project / "untitled.py"), context)
                            hover_state["hover_pos"] = (mx, my)
    else:
        hover_state["active"] = False
        fut = hover_state.pop("future", None)
        if fut:
            fut.cancel()

    h_fut = hover_state.get("future")
    if h_fut is not None and h_fut.done():
        hover_state.pop("future")
        try:
            info = h_fut.result()
            if info and (info.get("name") or info.get("description")):
                hover_state.update(active=True, info=info)
        except Exception:
            pass

    # Sync UI Popups
    if ui:
        sync_autocomplete_popup(target, ui, ac_state)
        sync_hover_tooltip(target, ui, hover_state)


def stop():
    state = entity.components.get('autocomplete_state')
    if state is not None:
        dismiss_completion(entity, state)
    hover_state = entity.components.get('hover_state')
    if hover_state:
        fut = hover_state.pop("future", None)
        if fut:
            fut.cancel()

