"""General entity UI primitives shared by applications and tools."""

from pathlib import Path

from .syntax import slice_spans
from .text import TextBuffer

PITCH = 8
LINE = 20
BG = (17, 23, 31)
PANEL = (25, 34, 45)
FIELD = (34, 45, 59)
ACCENT = (69, 182, 199)
INK = (220, 230, 239, 255)
MUTED = (145, 163, 183, 255)
ERROR = (248, 81, 73, 255)


def put(entity, **values):
    """Set changed scalar/control properties without redundant notifications."""
    for key, value in values.items():
        if entity.components.get(key) != value:
            entity.components[key] = value


def contains(entity, x, y):
    return entity.x <= x < entity.x+entity.w and entity.y <= y < entity.y+entity.h


def parse_box(value, default=0):
    """Normalize padding/margin into a (top, right, bottom, left) tuple."""
    if value is None:
        return (default, default, default, default)
    if isinstance(value, (int, float)):
        v = int(value)
        return (v, v, v, v)
    if isinstance(value, (tuple, list)):
        if len(value) == 0:
            return (default, default, default, default)
        if len(value) == 1:
            v = int(value[0])
            return (v, v, v, v)
        if len(value) == 2:
            y, x = int(value[0]), int(value[1])
            return (y, x, y, x)
        if len(value) == 3:
            top, x, bottom = int(value[0]), int(value[1]), int(value[2])
            return (top, x, bottom, x)
        if len(value) >= 4:
            return (int(value[0]), int(value[1]), int(value[2]), int(value[3]))
    return (default, default, default, default)


def content_rect(entity):
    """Return the content bounding box (x, y, w, h) of an entity inside its padding."""
    top, right, bottom, left = parse_box(entity.components.get("padding", 0) if hasattr(entity, "components") else 0)
    x = entity.x + left
    y = entity.y + top
    w = max(0, entity.w - left - right)
    h = max(0, entity.h - top - bottom)
    return (x, y, w, h)


def stack(parent, children=None, *, axis="y", gap=None, padding=None, align=None):
    """Lay out ordinary child entities along an axis; supports padding, margins, flex, and alignment."""
    if axis not in ("x", "y"):
        raise ValueError("axis must be x or y")
    if children is None:
        children = [c for c in parent.children if c.components.get("visible", True) and not c.components.get("ignore_layout", False)]
    else:
        children = list(children)
    if not children:
        return

    if padding is not None:
        pad_top, pad_right, pad_bottom, pad_left = parse_box(padding)
    elif hasattr(parent, "components") and "padding" in parent.components:
        pad_top, pad_right, pad_bottom, pad_left = parse_box(parent.components["padding"])
    else:
        pad_top, pad_right, pad_bottom, pad_left = parse_box(8)

    gap_val = gap if gap is not None else (parent.components.get("gap", 8) if hasattr(parent, "components") else 8)

    parent_w = getattr(parent, "w", 0)
    parent_h = getattr(parent, "h", 0)
    content_w = max(0, parent_w - pad_left - pad_right)
    content_h = max(0, parent_h - pad_top - pad_bottom)

    flex_children = [c for c in children if hasattr(c, "components") and c.components.get("flex", 0) > 0]
    if flex_children:
        total_flex = sum(c.components.get("flex", 1) for c in flex_children)
        if axis == "x" and content_w > 0:
            fixed = sum(c.w + parse_box(c.components.get("margin", 0))[3] + parse_box(c.components.get("margin", 0))[1]
                        for c in children if c not in flex_children)
            total_gaps = (len(children) - 1) * gap_val
            flex_margins = sum(parse_box(c.components.get("margin", 0))[3] + parse_box(c.components.get("margin", 0))[1]
                               for c in flex_children)
            rem = max(0, content_w - fixed - total_gaps - flex_margins)
            for c in flex_children:
                put(c, w=max(0, int(rem * (c.components.get("flex", 1) / total_flex))))
        elif axis == "y" and content_h > 0:
            fixed = sum(c.h + parse_box(c.components.get("margin", 0))[0] + parse_box(c.components.get("margin", 0))[2]
                        for c in children if c not in flex_children)
            total_gaps = (len(children) - 1) * gap_val
            flex_margins = sum(parse_box(c.components.get("margin", 0))[0] + parse_box(c.components.get("margin", 0))[2]
                               for c in flex_children)
            rem = max(0, content_h - fixed - total_gaps - flex_margins)
            for c in flex_children:
                put(c, h=max(0, int(rem * (c.components.get("flex", 1) / total_flex))))

    offset = pad_left if axis == "x" else pad_top
    for child in children:
        m_top, m_right, m_bottom, m_left = parse_box(child.components.get("margin", 0) if hasattr(child, "components") else 0)
        c_align = child.components.get("align", align) if hasattr(child, "components") else align

        if axis == "x":
            child_x = parent.x + offset + m_left
            if c_align == "stretch" and parent_h > 0:
                child_y = parent.y + pad_top + m_top
                child_h = max(0, content_h - m_top - m_bottom)
                put(child, x=child_x, y=child_y, h=child_h)
            elif c_align == "start":
                child_y = parent.y + pad_top + m_top
                put(child, x=child_x, y=child_y)
            elif c_align == "end" and parent_h > 0:
                child_y = parent.y + parent_h - pad_bottom - m_bottom - child.h
                put(child, x=child_x, y=child_y)
            elif c_align == "center" and parent_h > 0:
                child_y = parent.y + pad_top + m_top + max(0, (content_h - m_top - m_bottom - child.h) // 2)
                put(child, x=child_x, y=child_y)
            else:
                child_y = parent.y + pad_top + m_top
                put(child, x=child_x, y=child_y)
            offset += m_left + child.w + m_right + gap_val
        else:
            child_y = parent.y + offset + m_top
            if c_align == "stretch" and parent_w > 0:
                child_x = parent.x + pad_left + m_left
                child_w = max(0, content_w - m_left - m_right)
                put(child, x=child_x, y=child_y, w=child_w)
            elif c_align == "start":
                child_x = parent.x + pad_left + m_left
                put(child, x=child_x, y=child_y)
            elif c_align == "end" and parent_w > 0:
                child_x = parent.x + parent_w - pad_right - m_right - child.w
                put(child, x=child_x, y=child_y)
            elif c_align == "center" and parent_w > 0:
                child_x = parent.x + pad_left + m_left + max(0, (content_w - m_left - m_right - child.w) // 2)
                put(child, x=child_x, y=child_y)
            else:
                child_x = parent.x + pad_left + m_left
                put(child, x=child_x, y=child_y)
            offset += m_top + child.h + m_bottom + gap_val


def row(parent, children=None, *, gap=None, padding=None, align=None):
    """Lay out child entities horizontally."""
    return stack(parent, children, axis="x", gap=gap, padding=padding, align=align)


def column(parent, children=None, *, gap=None, padding=None, align=None):
    """Lay out child entities vertically."""
    return stack(parent, children, axis="y", gap=gap, padding=padding, align=align)


def dock(parent, children=None, *, padding=None):
    """Arrange child entities by docking edges (top, bottom, left, right, fill, float/none)."""
    if children is None:
        children = [c for c in parent.children if c.components.get("visible", True) and not c.components.get("ignore_layout", False)]
    else:
        children = list(children)

    pad_top, pad_right, pad_bottom, pad_left = parse_box(
        padding if padding is not None else parent.components.get("padding", 0) if hasattr(parent, "components") else 0
    )

    cur_x = parent.x + pad_left
    cur_y = parent.y + pad_top
    cur_w = max(0, parent.w - pad_left - pad_right)
    cur_h = max(0, parent.h - pad_top - pad_bottom)

    for child in children:
        mode = child.components.get("dock") if hasattr(child, "components") else None
        if mode in ("float", "none", None):
            if hasattr(child, "components") and "rel_x" in child.components and "rel_y" in child.components:
                put(child, x=parent.x + child.components["rel_x"], y=parent.y + child.components["rel_y"])
            continue

        m_top, m_right, m_bottom, m_left = parse_box(child.components.get("margin", 0) if hasattr(child, "components") else 0)

        if mode == "top":
            h = child.components.get("h", child.h)
            put(child, x=cur_x + m_left, y=cur_y + m_top, w=max(0, cur_w - m_left - m_right), h=h)
            advance = h + m_top + m_bottom
            cur_y += advance
            cur_h = max(0, cur_h - advance)
        elif mode == "bottom":
            h = child.components.get("h", child.h)
            advance = h + m_top + m_bottom
            cur_h = max(0, cur_h - advance)
            put(child, x=cur_x + m_left, y=cur_y + cur_h + m_top, w=max(0, cur_w - m_left - m_right), h=h)
        elif mode == "left":
            w = child.components.get("w", child.w)
            put(child, x=cur_x + m_left, y=cur_y + m_top, w=w, h=max(0, cur_h - m_top - m_bottom))
            advance = w + m_left + m_right
            cur_x += advance
            cur_w = max(0, cur_w - advance)
        elif mode == "right":
            w = child.components.get("w", child.w)
            advance = w + m_left + m_right
            cur_w = max(0, cur_w - advance)
            put(child, x=cur_x + cur_w + m_left, y=cur_y + m_top, w=w, h=max(0, cur_h - m_top - m_bottom))
        elif mode == "fill":
            put(child, x=cur_x + m_left, y=cur_y + m_top, w=max(0, cur_w - m_left - m_right), h=max(0, cur_h - m_top - m_bottom))


def apply_layout(entity, recursive=False):
    """Apply layout to entity based on its layout component ('dock', 'column', 'row', etc.)."""
    mode = entity.components.get("layout") if hasattr(entity, "components") else None
    if mode == "dock":
        dock(entity)
    elif mode in ("column", "stack", "stack_y"):
        stack(entity, axis="y")
    elif mode in ("row", "stack_x"):
        stack(entity, axis="x")

    if recursive:
        for child in entity.children:
            if hasattr(child, "components") and "layout" in child.components:
                apply_layout(child, recursive=True)


class Layout:
    """Attached entity system that automatically evaluates layout rules on update."""
    def __init__(self, entity):
        self.entity = entity

    def update(self, dt):
        apply_layout(self.entity, recursive=True)


class UI:
    """Controls are entities; this object provides operations and derived indexes.

    Callbacks are component values: action(), on_commit(), on_click(control,event),
    on_scroll(control,event), on_key(event), and on_ui_error(message).
    """

    def __init__(self, root, window, graphics, input_state, *, pitch=None, line_height=LINE):
        self.root = root
        self.runtime = root.runtime
        self.window = window
        self.graphics = graphics
        self.input = input_state
        if pitch is not None:
            self.pitch = pitch
        elif hasattr(graphics, "char_width") and callable(graphics.char_width):
            self.pitch = graphics.char_width(10)
        else:
            self.pitch = PITCH
        self.line_height = line_height

    def install(self, name="ui", definition=None):
        self.root.components["ui"] = self
        definition = definition or self.runtime.assets.system(Path(__file__).parent / "scripts" / "ui.py")
        return self.root.systems.attach(name, definition)

    @property
    def focused(self):
        return self.root.relations.get("focus")

    def focus(self, control=None):
        if control is None:
            self.root.relations.pop("focus", None)
        else:
            self.root.relations["focus"] = control

    def controls(self):
        return self.root.query(tags="ui", recursive=True)

    def visible(self, control):
        return all(e.components.get("visible", True) for e in (control,)+control.ancestors)

    def create(self, parent, name, kind, **values):
        defaults = dict(name=name, x=0, y=0, w=0, h=0, visible=True, layer=2, color=PANEL)
        defaults.update(values)
        return self.runtime.create(parent=parent, tags=["ui", kind], **defaults)

    def field(self, parent, name, text="", **values):
        values.setdefault("buffer", TextBuffer(text))
        values.setdefault("color", FIELD)
        values.setdefault("pitch", self.pitch)
        return self.create(parent, name, "field", **values)

    def button(self, parent, name, text, action, **values):
        values.setdefault("color", FIELD)
        return self.create(parent, name, "button", text=text, action=action, **values)

    def splitter(self, parent, name, *, axis="x", thickness=6, on_drag=None, **values):
        normal = values.pop("color", (38, 50, 66))
        hover = values.pop("hover_color", ACCENT)
        values.setdefault("axis", axis)
        values.setdefault("thickness", thickness)
        values.setdefault("color", normal)
        values.setdefault("normal_color", normal)
        values.setdefault("hover_color", hover)
        values.setdefault("layer", 3)
        if on_drag:
            values["on_drag"] = on_drag
        return self.create(parent, name, "splitter", **values)

    def multiline(self, parent, name, text="", **values):
        values.setdefault("buffer", TextBuffer(text))
        values.setdefault("color", BG)
        values.setdefault("pitch", self.pitch)
        values.setdefault("line_height", self.line_height)
        control = self.create(parent, name, "multiline", **values)
        bundled = Path(__file__).parent / "scripts" / "text_area.py"
        if bundled.exists() and "text_area" not in control.systems:
            control.systems.attach("text_area", self.runtime.assets.system(bundled))
        return control

    def set_text(self, field, text):
        if self.focused is not field and field.buffer.text != text:
            field.buffer = TextBuffer(text)

    def process(self):
        for event in self.input.drain():
            try:
                self.dispatch(event)
            except Exception as error:
                message = f"{type(error).__name__}: {error}"
                self.root.components["ui_error"] = message
                callback = self.root.components.get("on_ui_error")
                if callback:
                    callback(message)
        for control in tuple(self.controls()):
            if "multiline" in control.tags and self.visible(control):
                try:
                    self._sync_text(control)
                except Exception as error:
                    message = f"{type(error).__name__}: {error}"
                    self.root.components["ui_error"] = message
                    callback = self.root.components.get("on_ui_error")
                    if callback:
                        callback(message)

    def dispatch(self, event):
        from .menus import dispatch_menu
        if dispatch_menu(self, event):
            return
        kind = event[0]
        if kind == "motion":
            mx, my = event[1], event[2]
            for control in self.controls():
                if ("splitter" in control.tags or "scrollbar_thumb" in control.tags) and self.visible(control):
                    active = self.root.relations.get("active_drag")
                    hovered = (active is control) or (active is None and contains(control, mx, my))
                    target_color = control.components.get("hover_color", ACCENT) if hovered else control.components.get("normal_color", control.components.get("color", PANEL))
                    if control.color != target_color:
                        control.color = target_color
            return
        if kind == "release":
            self.root.relations.pop("text_drag", None)
            active_drag = self.root.relations.pop("active_drag", None)
            if active_drag is not None:
                if "splitter" in active_drag.tags or "scrollbar_thumb" in active_drag.tags:
                    normal = active_drag.components.get("normal_color", active_drag.components.get("color", PANEL))
                    if active_drag.color != normal:
                        active_drag.color = normal
                cb = active_drag.components.get("on_release")
                if cb:
                    cb(active_drag, event)
            return
        if kind == "drag":
            text_drag = self.root.relations.get("text_drag")
            if text_drag is not None and self.visible(text_drag) and event[3] & 1:
                text_drag.buffer.cursor = self.text_index(text_drag, event[1], event[2])
                text_drag.buffer.reveal(max(1, int((text_drag.h-12)//text_drag.components.get("line_height", self.line_height))),
                                        max(1, int((text_drag.w-64)//text_drag.components.get("pitch", self.pitch))))
                text_drag.components.touch("buffer")
                return
            active_drag = self.root.relations.get("active_drag")
            if active_drag is not None and self.visible(active_drag):
                cb = active_drag.components.get("on_drag")
                if cb:
                    if cb(active_drag, event) is not False:
                        return
            controls = [e for e in self.controls() if self.visible(e) and contains(e, event[1], event[2])]
            controls.sort(key=lambda e: (e.components.get("layer", 2), e.depth), reverse=True)
            for control in controls:
                if "splitter" in control.tags or "scrollbar_thumb" in control.tags:
                    continue  # Splitters and scrollbars must be directly clicked/pressed to initiate dragging
                cb = control.components.get("on_drag")
                if cb:
                    if cb(control, event) is not False:
                        return
            return
        if kind in ("click", "scroll"):
            if kind == "click":
                self.root.relations.pop("text_drag", None)
            self.root.relations.pop("active_drag", None)
            controls = [e for e in self.controls() if self.visible(e) and contains(e, event[1], event[2])]
            controls.sort(key=lambda e: (e.components.get("layer", 2), e.depth), reverse=True)
            for control in controls:
                if "splitter" in control.tags or "scrollbar_thumb" in control.tags:
                    self.root.relations["active_drag"] = control
                    control.color = control.components.get("hover_color", ACCENT)
                callback = control.components.get("on_"+kind)
                if callback:
                    if callback(control, event) is not False:
                        return
                if kind == "scroll":
                    if "multiline" in control.tags:
                        control.buffer.scroll = max(0, control.buffer.scroll-int(event[4])*3)
                        control.components.touch("buffer")
                        return
                    continue
                if "button" in control.tags:
                    control.action()
                    return
                if "field" in control.tags and not control.components.get("readonly", False):
                    self.focus(control)
                    control.buffer.cursor = control.buffer.anchor = len(control.buffer.text)
                    return
                if "multiline" in control.tags:
                    self.focus(control)
                    control.buffer.cursor = self.text_index(control, event[1], event[2])
                    if not event[4] & 1:
                        control.buffer.anchor = control.buffer.cursor
                    if event[3] == 1:
                        self.root.relations["text_drag"] = control
                    control.components.touch("buffer")
                    pitch = control.components.get("pitch", self.pitch)
                    line = control.components.get("line_height", self.line_height)
                    control.buffer.reveal(max(1, int((control.h-12)//line)), max(1, int((control.w-64)//pitch)))
                    return
                if control.components.get("modal", False):
                    return
            return
        callback = self.root.components.get("on_key")
        if kind == "key" and callback and callback(event):
            return
        control = self.focused
        if control is None or not self.visible(control) or "buffer" not in control.components:
            return
        if kind == "key":
            on_key = control.components.get("on_key")
            if on_key and on_key(control, event):
                return
        elif kind == "text":
            on_text = control.components.get("on_text")
            if on_text and on_text(control, event):
                return
        buffer = control.buffer
        multiline = "multiline" in control.tags
        if kind == "text":
            buffer.insert(event[1] if multiline else event[1].replace("\r\n", " ").replace("\r", " ").replace("\n", " "))
        elif kind == "key":
            key, ctrl, shift = event[1:]
            if ctrl and key == "A":
                buffer.anchor, buffer.cursor = 0, len(buffer.text)
            elif ctrl and key == "C":
                self.window.set_clipboard_text(buffer.selected_text)
            elif ctrl and key == "X":
                self.window.set_clipboard_text(buffer.selected_text)
                buffer.insert("")
            elif ctrl and key == "V":
                text = self.window.get_clipboard_text()
                buffer.insert(text if multiline else text.replace("\r\n", " ").replace("\r", " ").replace("\n", " "))
            elif ctrl and key == "Z":
                buffer.undo(redo=shift)
            elif key in ("LEFT", "RIGHT", "UP", "DOWN", "HOME", "END", "FILE_HOME", "FILE_END", "PAGEUP", "PAGEDOWN", "WORD_LEFT", "WORD_RIGHT"):
                buffer.move(key, select=shift)
            elif key in ("BACKSPACE", "DELETE"):
                buffer.delete(backward=key == "BACKSPACE")
            elif key in ("ENTER", "RETURN", "NUM_ENTER"):
                if multiline:
                    buffer.newline()
                elif "on_commit" in control.components:
                    control.on_commit()
                    self.focus()
            elif key == "TAB":
                if multiline:
                    buffer.insert("    ")
                else:
                    fields = [e for e in self.controls() if "field" in e.tags and self.visible(e) and not e.components.get("readonly", False)]
                    self.focus(fields[(fields.index(control)+(-1 if shift else 1)) % len(fields)])
            elif key == "ESCAPE":
                self.focus()
        if control.alive:
            control.components.touch("buffer")
            if multiline:
                pitch = control.components.get("pitch", self.pitch)
                line = control.components.get("line_height", self.line_height)
                buffer.reveal(max(1, int((control.h-12)//line)), max(1, int((control.w-64)//pitch)))

    def text_index(self, control, x=None, y=None):
        if y is None and x is not None:
            control, x, y = self, control, x
            ui = getattr(control, "root", control).components.get("ui") if hasattr(control, "components") else None
            pitch = getattr(ui, "pitch", PITCH)
            line = getattr(ui, "line_height", LINE)
        else:
            pitch = control.components.get("pitch", getattr(self, "pitch", PITCH))
            line = control.components.get("line_height", getattr(self, "line_height", LINE))
        buffer = control.buffer
        row = max(0, int((y-control.y-6)//line))+buffer.scroll
        column = max(0, round((x-control.x-48)/pitch))+buffer.horizontal
        return buffer.index(row, column)

    def _sync_text(self, control):
        pitch = control.components.get("pitch", self.pitch)
        line_height = control.components.get("line_height", self.line_height)
        buffer = control.buffer
        rows = max(1, int((control.h-12)//line_height))
        columns = max(1, int((control.w-64)//pitch))
        lines = buffer.text.split("\n")
        buffer.scroll = max(0, min(buffer.scroll, max(0, len(lines)-rows)))
        max_col = max((len(l) for l in lines), default=0)
        buffer.horizontal = max(0, min(buffer.horizontal, max(0, max_col-columns)))
        cursor_state = (buffer.text, buffer.cursor)
        if self.focused is control and control.components.get("_view_cursor") != cursor_state:
            buffer.reveal(rows, columns)
        control.components["_view_cursor"] = cursor_state
        children = {child.components.get("part"): child for child in control.children}

        def part(name, kind, **values):
            if name not in children:
                children[name] = self.create(control, name, kind, part=name, **values)
            return children[name]

        caret = part("cursor", "rect", color=ACCENT, layer=control.layer+2)
        scrollbar = part("scrollbar", "rect", color=ACCENT, layer=control.layer+2)
        selection_start, selection_end = buffer.selection
        offset = sum(len(line)+1 for line in lines[:buffer.scroll])
        used = {"cursor", "scrollbar"}
        line_spans = control.components.get("line_spans")
        diag = control.components.get("diagnostic")
        err_row = (diag.get("line", 0) - 1) if diag else -1
        matching_brackets = control.components.get("matching_brackets")
        for index in range(rows):
            row = index+buffer.scroll
            if row >= len(lines):
                break
            highlight = part(f"selection:{index}", "rect", color=(44, 76, 105), layer=control.layer)
            number = part(f"number:{index}", "label", text="", ink=MUTED, layer=control.layer)
            line = part(f"line:{index}", "label", text="", layer=control.layer)
            err_rect = part(f"error:{index}", "rect", color=ERROR, layer=control.layer+1)
            used.update((highlight.part, number.part, line.part, err_rect.part))
            y = control.y+6+index*line_height
            is_error = (row == err_row)
            put(number, visible=True, x=control.x+6, y=y, w=40, h=line_height, text=str(row+1), ink=(ERROR if is_error else MUTED))
            spans = slice_spans(line_spans[row], buffer.horizontal, columns) if (line_spans and row < len(line_spans)) else None
            put(line, visible=True, x=control.x+48, y=y, w=control.w-64, h=line_height,
                text=lines[row][buffer.horizontal:buffer.horizontal+columns], spans=spans)
            if is_error:
                col_start = max(0, diag.get("column", 1) - 1)
                col_end = max(col_start + 1, diag.get("end_column", col_start + 1) - 1)
                err_x = line.x + max(0, col_start - buffer.horizontal) * pitch
                err_w = max(pitch, (col_end - col_start) * pitch)
                put(err_rect, visible=True, x=err_x, y=y + line_height - 2, w=min(err_w, line.w), h=2)
            else:
                put(err_rect, visible=False)
            start = max(selection_start-offset-buffer.horizontal, 0)
            selected_width = len(lines[row]) + (1 if row < len(lines)-1 else 0)
            end = min(selection_end-offset-buffer.horizontal, selected_width-buffer.horizontal, columns)
            has_selection = (end > start and
                             selection_start < offset + len(lines[row]) + 1 and
                             selection_end > offset)
            put(highlight, visible=has_selection, x=line.x+start*pitch, y=y, w=max(0, end-start)*pitch, h=line_height)
            offset += len(lines[row])+1
        used.update(("bracket:0", "bracket:1"))
        for b_i in range(2):
            b_part = part(f"bracket:{b_i}", "rect", color=(88, 166, 255, 120), layer=control.layer+1)
            if matching_brackets and b_i < len(matching_brackets):
                b_row, b_col = matching_brackets[b_i]
                if (buffer.scroll <= b_row < buffer.scroll + rows and
                        buffer.horizontal <= b_col <= buffer.horizontal + columns):
                    b_x = control.x + 48 + (b_col - buffer.horizontal) * pitch
                    b_y = control.y + 6 + (b_row - buffer.scroll) * line_height
                    put(b_part, visible=True, x=b_x, y=b_y, w=pitch, h=line_height)
                else:
                    put(b_part, visible=False)
            else:
                put(b_part, visible=False)
        for name, child in children.items():
            if name not in used:
                put(child, visible=False)
        row, column = buffer.position
        caret_visible = (self.focused is control and
                         buffer.scroll <= row < buffer.scroll+rows and
                         buffer.horizontal <= column <= buffer.horizontal+columns)
        put(caret, visible=caret_visible,
            x=control.x+48+(column-buffer.horizontal)*pitch, y=control.y+6+(row-buffer.scroll)*line_height, w=2, h=line_height)
        put(scrollbar, x=control.x+control.w-5, y=control.y+control.h*buffer.scroll/max(len(lines), rows),
            w=3, h=max(12, control.h*min(1, rows/len(lines))))

    def draw(self):
        graphics = self.graphics
        for control in self.controls():
            if not self.visible(control):
                continue
            layer = control.components.get("layer", 2)
            if "label" not in control.tags:
                graphics.rect(control.x, control.y, control.w, control.h, control.color, key=control.id, layer=layer)
            if "field" in control.tags:
                pitch = control.components.get("pitch", self.pitch)
                buffer = control.buffer
                width = max(1, int((control.w-12)//pitch))
                if self.focused is control:
                    buffer.reveal(1, width)
                    start, end = buffer.selection
                    start, end = max(0, start-buffer.horizontal), min(width, end-buffer.horizontal)
                    if end > start:
                        graphics.rect(control.x+6+start*pitch, control.y+3, (end-start)*pitch, control.h-6,
                                      (44, 76, 105), key=(control.id, "selection"), layer=layer+1)
                    graphics.rect(control.x, control.y+control.h-2, control.w, 2, ACCENT, key=(control.id, "focus"), layer=layer+1)
                    graphics.rect(control.x+6+(buffer.cursor-buffer.horizontal)*pitch, control.y+4, 1, control.h-8,
                                   ACCENT, key=(control.id, "caret"), layer=layer+2)
                text = buffer.text.replace("\n", " ")[buffer.horizontal:buffer.horizontal+width]
                text = text or control.components.get("hint", "")[:width]
                graphics.text(text, control.x+6, control.y+5, color=INK, key=(control.id, "text"), layer=layer+2)
            elif "text" in control.components:
                pitch = control.components.get("pitch", self.pitch)
                inset = 8 if "panel" in control.tags or "button" in control.tags else 0
                width = max(1, int((control.w-inset*2)//pitch))
                spans = control.components.get("spans")
                if spans:
                    x_cursor = control.x + inset
                    col = 0
                    for span_idx, (chunk, ink) in enumerate(spans):
                        if col >= width:
                            break
                        chunk_str = str(chunk)[:width - col]
                        graphics.text(chunk_str, x_cursor, control.y+(8 if "panel" in control.tags else 4),
                                      color=ink, key=(control.id, "span", span_idx), layer=layer+1)
                        x_cursor += len(chunk_str) * pitch
                        col += len(chunk_str)
                else:
                    graphics.text(str(control.text)[:width], control.x+inset, control.y+(8 if "panel" in control.tags else 4),
                                  color=control.components.get("ink", INK), key=(control.id, "text"), layer=layer+1)
