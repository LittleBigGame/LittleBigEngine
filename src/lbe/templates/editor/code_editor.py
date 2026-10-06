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
        from lbe.references import lower_references
        ast.parse(lower_references(source, "<editor>")[0])
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


def mask_code(text):
    """Return text of identical length where characters inside strings and comments are replaced with spaces.

    Newlines are preserved so row and column mapping is unchanged.
    """
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "#":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
            if i < n and text[i] == "\n":
                out.append("\n")
                i += 1
            continue

        if text[i:i + 3] in ('"""', "'''"):
            q = text[i:i + 3]
            out.extend([" ", " ", " "])
            i += 3
            while i < n:
                if text[i:i + 3] == q:
                    out.extend([" ", " ", " "])
                    i += 3
                    break
                elif text[i] == "\\":
                    out.append(" ")
                    i += 1
                    if i < n:
                        out.append("\n" if text[i] == "\n" else " ")
                        i += 1
                elif text[i] == "\n":
                    out.append("\n")
                    i += 1
                else:
                    out.append(" ")
                    i += 1
            continue

        if c in ('"', "'"):
            q = c
            out.append(" ")
            i += 1
            while i < n:
                if text[i] == q:
                    out.append(" ")
                    i += 1
                    break
                elif text[i] == "\\":
                    out.append(" ")
                    i += 1
                    if i < n:
                        out.append("\n" if text[i] == "\n" else " ")
                        i += 1
                elif text[i] == "\n":
                    out.append("\n")
                    i += 1
                    break
                else:
                    out.append(" ")
                    i += 1
            continue

        out.append(c)
        i += 1

    return "".join(out)


def find_matching_brackets(text, cursor):
    """Find (open_pos, close_pos) for a bracket adjacent to the cursor, ignoring strings/comments."""
    if not text or cursor < 0 or cursor > len(text):
        return None
    masked = mask_code(text)
    candidates = []
    if cursor > 0:
        candidates.append((cursor - 1, masked[cursor - 1]))
    if cursor < len(text):
        candidates.append((cursor, masked[cursor]))

    for pos, ch in candidates:
        if ch in ('(', '[', '{'):
            open_ch = ch
            close_ch = PAIRS[open_ch]
            depth = 1
            idx = pos + 1
            while idx < len(masked):
                c = masked[idx]
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
                c = masked[idx]
                if c == close_ch:
                    depth += 1
                elif c == open_ch:
                    depth -= 1
                    if depth == 0:
                        return (text_index_to_pos(text, idx), text_index_to_pos(text, pos))
                idx -= 1
    return None


VISIBLE_ITEMS = 8


def start():
    """Attach input callbacks once at system start, not every frame."""
    entity.components["inline_references"] = True
    target = entity if "buffer" in entity.components else None
    if target is not None:
        target.components["on_text"] = handle_editor_text
        target.components["on_key"] = handle_editor_key
        target.components["on_scroll"] = handle_editor_scroll


def find_open_bracket_indent(text, cursor, close_char):
    if close_char not in CLOSING:
        return None
    open_char = CLOSING[close_char]
    masked = mask_code(text)
    depth = 1
    idx = cursor - 1
    while idx >= 0:
        c = masked[idx]
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
    #    Skip quotes on indented empty lines so they fall through to auto-close.
    is_quote = char in ("'", '"')
    if start == end and char in CLOSING:
        line_start = buffer.text.rfind("\n", 0, buffer.cursor) + 1
        line_prefix = buffer.text[line_start:buffer.cursor]

        # Type-over: next char matches this closing delimiter
        if buffer.cursor < len(buffer.text) and buffer.text[buffer.cursor] == char:
            # Dedent indented closer first if applicable
            if not is_quote and line_prefix.strip() == "":
                target_indent = find_open_bracket_indent(buffer.text, buffer.cursor, char)
                if target_indent is not None and len(line_prefix) > len(target_indent):
                    buffer.anchor = line_start
                    buffer.cursor = line_start + len(line_prefix)
                    buffer.insert(target_indent)
            buffer.move("RIGHT")
            control.components.touch("buffer")
            return True

        # Dedent + insert for bracket closers on empty lines (not quotes)
        if not is_quote and line_prefix.strip() == "":
            target_indent = find_open_bracket_indent(buffer.text, buffer.cursor, char)
            if target_indent is not None and len(line_prefix) > len(target_indent):
                buffer.anchor = line_start
                buffer.cursor = line_start + len(line_prefix)
                buffer.insert(target_indent)
            buffer.insert(char)
            control.components.touch("buffer")
            return True

    # 3. Auto-close opening delimiter
    if start == end and char in PAIRS:
        # Don't auto-close quotes inside words, but allow Python string prefixes
        if char in ("'", '"') and buffer.cursor > 0:
            prefix_match = re.search(r"[A-Za-z0-9_]+$", buffer.text[:buffer.cursor])
            if prefix_match:
                word = prefix_match.group()
                if word.lower() not in ("f", "r", "b", "u", "fr", "rf", "br", "rb"):
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

    # Escape always consumed to prevent ui.py from dropping editor focus
    if key == "ESCAPE":
        return True

    # Ctrl+/ comment toggle
    if ctrl and key in ("SLASH", "/"):
        buffer.toggle_comment()
        control.components.touch("buffer")
        return True

    # Tab / Shift+Tab indent and dedent
    if key == "TAB":
        buffer.indent(dedent=shift)
        control.components.touch("buffer")
        return True

    # Backspace deleting empty pair
    if key == "BACKSPACE" and not ctrl and start == end:
        if 0 < buffer.cursor < len(buffer.text):
            pair = (buffer.text[buffer.cursor - 1], buffer.text[buffer.cursor])
            if pair in EMPTY_PAIRS:
                buffer.replace(buffer.cursor - 1, buffer.cursor + 1, "")
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
    buffer.replace(start, end, chosen)
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


MAX_HOVER_DOC_LINES = 6


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
        for i in range(MAX_HOVER_DOC_LINES):
            lbl = children.get(f"hover_line:{i}")
            if lbl:
                put(lbl, visible=False)
        return

    info = hover_state["info"]
    mx, my = hover_state.get("hover_pos", (target.x, target.y))
    pitch = target.components.get("pitch", 8)

    title_text = info.get("description", info.get("name", ""))
    signatures = info.get("signatures", [])
    doc_text = info.get("docstring", "")

    display_lines = []
    # If multiple signatures or signature is distinct from title
    if signatures:
        for sig in signatures[:2]:
            sig_line = sig.strip()
            if sig_line and sig_line != title_text and f"{info.get('type', '')} {sig_line}" != title_text:
                display_lines.append((sig_line, (165, 214, 255)))

    if doc_text:
        import textwrap
        for paragraph in doc_text.split("\n\n"):
            clean_para = " ".join(paragraph.split())
            if not clean_para:
                continue
            wrapped = textwrap.wrap(clean_para, width=54)
            for w_line in wrapped:
                if len(display_lines) >= MAX_HOVER_DOC_LINES:
                    break
                display_lines.append((w_line, INK))
            if len(display_lines) >= MAX_HOVER_DOC_LINES:
                break

    # Calculate layout dimensions
    max_line_len = len(title_text)
    for l_text, _ in display_lines:
        max_line_len = max(max_line_len, len(l_text))

    line_h = 18
    pad_y = 6
    pad_x = 8
    tip_w = min(max(220, max_line_len * pitch + pad_x * 2 + 8), max(120, target.w - 32))
    tip_h = pad_y * 2 + (1 + len(display_lines)) * line_h

    tip_x = max(target.x + 8, min(mx + 10, target.x + target.w - tip_w - 8))
    tip_y = my + 18
    if tip_y + tip_h > target.y + target.h:
        tip_y = max(target.y + 4, my - tip_h - 6)

    put(tip_panel, visible=True, x=tip_x, y=tip_y, w=tip_w, h=tip_h)
    put(tip_title, visible=True, x=tip_x + pad_x, y=tip_y + pad_y, w=tip_w - pad_x * 2, h=line_h, text=title_text)

    # Position each display line
    curr_y = tip_y + pad_y + line_h
    for i in range(MAX_HOVER_DOC_LINES):
        line_lbl = part(f"hover_line:{i}", "label", layer=target.layer + 7)
        if i < len(display_lines):
            l_text, l_color = display_lines[i]
            put(line_lbl, visible=True, x=tip_x + pad_x, y=curr_y, w=tip_w - pad_x * 2, h=line_h, text=l_text, ink=l_color)
            curr_y += line_h
        else:
            put(line_lbl, visible=False)

    put(tip_doc, visible=False)


def update(dt):
    """Specialized behaviors for code editing (synchronization, shortcuts, status)."""
    target = entity if "buffer" in entity.components else None
    if target is None:
        return

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

    # 3. Bracket matching (skip if text+cursor unchanged)
    bracket_key = (text, buffer.cursor)
    if target.components.get("_last_bracket_key") != bracket_key:
        target.components["matching_brackets"] = find_matching_brackets(text, buffer.cursor)
        target.components["_last_bracket_key"] = bracket_key

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
    hover_snapshot = (text, str(target.components.get("source_path")), target.components.get("completion_context"))
    if hover_state.get("snapshot") != hover_snapshot:
        future = hover_state.pop("future", None)
        if future:
            future.cancel()
        hover_state.update(active=False, snapshot=hover_snapshot, dwell_start=monotonic())
        hover_state.pop("resolved_empty", None)
    mouse_pos = getattr(ui, "mouse_pos", None)
    if ui and mouse_pos and contains(target, mouse_pos[0], mouse_pos[1]) and not ac_state.get("active"):
        mx, my = mouse_pos
        last_mx, last_my = hover_state.get("last_mouse", (-100, -100))
        if abs(mx - last_mx) > 4 or abs(my - last_my) > 4:
            hover_state["last_mouse"] = (mx, my)
            hover_state["dwell_start"] = monotonic()
            hover_state["active"] = False
            hover_state.pop("resolved_empty", None)  # reset sentinel on move
            fut = hover_state.pop("future", None)
            if fut:
                fut.cancel()
        else:
            if not hover_state.get("active") and not hover_state.get("future") and not hover_state.get("resolved_empty"):
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
                            hover_state["resolved_empty"] = True
                    else:
                        hover_state["resolved_empty"] = True
    else:
        hover_state["active"] = False
        hover_state.pop("resolved_empty", None)
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
            else:
                hover_state["resolved_empty"] = True
        except Exception:
            hover_state["resolved_empty"] = True

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
        hover_state["active"] = False
        fut = hover_state.pop("future", None)
        if fut:
            fut.cancel()
    for key in ("on_key", "on_text", "on_scroll"):
        callback = entity.components.get(key)
        if getattr(callback, "__globals__", None) is globals():
            entity.components.pop(key, None)
    # Hide popup child entities so they don't linger after system stop
    popup_parts = ("autocomplete_popup", "ac_scroll_track", "ac_scroll_thumb",
                   "hover_panel", "hover_title", "hover_doc")
    for child in entity.children:
        p = child.components.get("part", "")
        if p in popup_parts or p.startswith("hover_line:") or p.startswith("ac_item:"):
            child.visible = False

