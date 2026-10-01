"""General entity UI primitives shared by applications and tools."""

from pathlib import Path
import re
import io
import tokenize
from time import monotonic

from .syntax import slice_spans
from .text import TextBuffer

ASSET_PATTERN = re.compile(
    r'(?:asset|resolve)\(\s*["\']([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})["\']\s*\)|assets\[\s*["\']([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})["\']\s*\]'
)

def reference_matches(text):
    """Recognize reference calls only in Python code, never inside comments or strings."""
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    names = set()
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.NAME and token.string in ("asset", "resolve", "assets"):
                names.add(offsets[token.start[0] - 1] + token.start[1])
    except (tokenize.TokenError, IndentationError):
        pass
    return tuple(match for match in ASSET_PATTERN.finditer(text) if match.start() in names)


PITCH = 8
LINE = 20
BG = (17, 23, 31)
PANEL = (25, 34, 45)
FIELD = (34, 45, 59)
SELECTION = (45, 85, 135)
ACCENT = (69, 182, 199)
INK = (220, 230, 239, 255)
MUTED = (145, 163, 183, 255)
ERROR = (248, 81, 73, 255)
STACK_COLORS = [
    (56, 189, 248, 255),   # 0: Cyan (Leaf / innermost target)
    (52, 211, 153, 255),   # 1: Emerald Green (Direct parent)
    (251, 191, 36, 255),   # 2: Amber (Grandparent)
    (232, 121, 249, 255),  # 3: Fuchsia / Purple
    (251, 113, 133, 255),  # 4: Coral / Rose
]


def put(entity, **values):
    """Set changed scalar/control properties without redundant notifications."""
    for key, value in values.items():
        if entity.components.get(key) != value:
            entity.components[key] = value


def bind_callbacks(system, target, callbacks):
    """Register panel-owned operations and release only this attachment's bindings."""
    bindings = {}
    for name, callback in callbacks.items():
        def guarded(*args, _callback=callback, **kwargs):
            if system.running:
                return _callback(*args, **kwargs)
        bindings[name] = guarded
        setattr(target, name, guarded)

    def release():
        for name, callback in bindings.items():
            if getattr(target, name, None) is callback:
                delattr(target, name)
        for control in (system.entity,) + system.entity.descendants:
            for key, callback in tuple(control.components.items()):
                if callable(callback) and getattr(callback, "__globals__", None) is system.namespace:
                    del control.components[key]
    return release


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
    """Layout operations, optionally installed as an ordinary script system."""
    def __init__(self, entity):
        self.entity = entity

    def update(self, dt):
        apply_layout(self.entity, recursive=True)

    def install(self, name="layout"):
        from .systems import SystemDefinition
        return self.entity.systems.attach(name, SystemDefinition(
            'from lbe.ui import apply_layout\ndef update(dt):\n    apply_layout(entity, recursive=True)\n',
            '<layout>'))


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
        normal = values.get("color", FIELD)
        values.setdefault("color", normal)
        values.setdefault("normal_color", normal)
        if "hover_color" not in values:
            if isinstance(normal, tuple) and len(normal) >= 3:
                values["hover_color"] = tuple(min(255, c + 22) for c in normal[:3])
            else:
                values["hover_color"] = (52, 70, 92)
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
                self.runtime.events.emit('ui.error', message)
                callback = self.root.components.get("on_ui_error")
                if callback:
                    callback(message)
        # Continuous selection drag autoscroll when mouse is held outside multiline control
        text_drag = self.root.relations.get("text_drag")
        if text_drag is not None and self.visible(text_drag) and hasattr(self, "mouse_pos"):
            mx, my = self.mouse_pos
            pitch = text_drag.components.get("pitch", self.pitch)
            line = text_drag.components.get("line_height", self.line_height)
            rows = max(1, int((text_drag.h - 12) // line))
            cols = max(1, int((text_drag.w - 64) // pitch))
            lines_count = len(text_drag.buffer.lines)
            changed = False
            if my < text_drag.y + 6 and text_drag.buffer.scroll > 0:
                text_drag.buffer.scroll = max(0, text_drag.buffer.scroll - 1)
                text_drag.buffer.cursor = self.text_index(text_drag, mx, my)
                changed = True
            elif my > text_drag.y + text_drag.h - 6 and text_drag.buffer.scroll < max(0, lines_count - rows):
                text_drag.buffer.scroll = min(max(0, lines_count - rows), text_drag.buffer.scroll + 1)
                text_drag.buffer.cursor = self.text_index(text_drag, mx, my)
                changed = True
            if changed:
                text_drag.buffer.reveal(rows, cols)
                text_drag.components.touch("buffer")
        for control in tuple(self.controls()):
            if "multiline" in control.tags and self.visible(control):
                try:
                    self._sync_text(control)
                except Exception as error:
                    message = f"{type(error).__name__}: {error}"
                    self.root.components["ui_error"] = message
                    self.runtime.events.emit('ui.error', message)
                    callback = self.root.components.get("on_ui_error")
                    if callback:
                        callback(message)

    def dispatch(self, event):
        from .menus import dispatch_menu
        kind = event[0]
        if kind == "motion":
            if len(event) > 3 and isinstance(event[3], int):
                self.ctrl_held = bool(event[3] & 2)
        elif kind in ("click", "release"):
            if len(event) > 4 and isinstance(event[4], int):
                self.ctrl_held = bool(event[4] & 2)
        elif kind == "drag":
            if len(event) > 4 and isinstance(event[4], int):
                self.ctrl_held = bool(event[4] & 2)
        elif kind == "key":
            if len(event) > 1 and event[1] in ("LCTRL", "RCTRL", "CTRL"):
                self.ctrl_held = True
            elif len(event) > 2 and isinstance(event[2], bool):
                self.ctrl_held = event[2]
        elif kind == "key_up":
            if len(event) > 1 and event[1] in ("LCTRL", "RCTRL", "CTRL"):
                self.ctrl_held = False
            elif len(event) > 2 and isinstance(event[2], bool):
                self.ctrl_held = event[2]

        if kind in ("motion", "drag") and len(event) >= 3 and isinstance(event[1], (int, float)) and isinstance(event[2], (int, float)):
            self.mouse_pos = (event[1], event[2])

        if dispatch_menu(self, event):
            if kind == 'release':
                self.root.relations.pop('text_drag', None)
                for name in ('entity_drag', 'asset_drag', 'dock_drag'):
                    self.root.components.pop(name, None)
                active_drag = self.root.relations.pop('active_drag', None)
                if active_drag is not None:
                    if any(tag in active_drag.tags for tag in ('splitter', 'scrollbar_thumb', 'button', 'chip')):
                        normal = active_drag.components.get('normal_color', active_drag.components.get('color', FIELD))
                        put(active_drag, color=normal)
                    callback = active_drag.components.get('on_release')
                    if callback:
                        callback(active_drag, event)
            return
        if kind == "motion":
            mx, my = event[1], event[2]
            for control in self.controls():
                if ("splitter" in control.tags or "scrollbar_thumb" in control.tags or "button" in control.tags or "chip" in control.tags or "hoverable" in control.tags) and self.visible(control):
                    active = self.root.relations.get("active_drag")
                    hovered = (active is control) or (active is None and contains(control, mx, my))
                    normal = control.components.get("normal_color")
                    if normal is None:
                        normal = control.components.get("color", FIELD)
                        control.components["normal_color"] = normal
                    target_color = control.components.get("hover_color", ACCENT) if hovered else normal
                    if control.color != target_color:
                        control.color = target_color
            return
        if kind == "release":
            self.root.relations.pop("text_drag", None)
            entity_drag = self.root.components.pop("entity_drag", None)
            if entity_drag is not None:
                cb = self.root.components.get("on_entity_drop")
                if cb:
                    cb(entity_drag, event)
                return
            asset_drag = self.root.components.pop("asset_drag", None)
            if asset_drag is not None:
                cb = self.root.components.get("on_asset_drop")
                if cb:
                    cb(asset_drag, event)
                return
            dock_drag = self.root.components.pop("dock_drag", None)
            if dock_drag is not None:
                cb = self.root.components.get("on_dock_drop")
                if cb:
                    cb(dock_drag, event)
                return
            active_drag = self.root.relations.pop("active_drag", None)
            if active_drag is not None:
                if "splitter" in active_drag.tags or "scrollbar_thumb" in active_drag.tags or "button" in active_drag.tags or "chip" in active_drag.tags:
                    normal = active_drag.components.get("normal_color", active_drag.components.get("color", FIELD))
                    if active_drag.color != normal:
                        active_drag.color = normal
                cb = active_drag.components.get("on_release")
                if cb:
                    cb(active_drag, event)
            return
        if kind == "drag":
            if self.root.components.get("asset_drag") is not None or self.root.components.get("entity_drag") is not None:
                return
            dock_drag = self.root.components.get("dock_drag")
            if dock_drag is not None:
                cb = self.root.components.get("on_dock_drag")
                if cb:
                    cb(dock_drag, event)
                return
            text_drag = self.root.relations.get("text_drag")
            if text_drag is not None and self.visible(text_drag) and event[3] & 1:
                mx, my = event[1], event[2]
                pitch = text_drag.components.get("pitch", self.pitch)
                line = text_drag.components.get("line_height", self.line_height)
                rows = max(1, int((text_drag.h - 12) // line))
                cols = max(1, int((text_drag.w - 64) // pitch))

                # Autoscroll when dragging outside visible bounds
                if my < text_drag.y + 6:
                    dy_lines = max(1, int((text_drag.y + 6 - my) // line))
                    text_drag.buffer.scroll = max(0, text_drag.buffer.scroll - dy_lines)
                elif my > text_drag.y + text_drag.h - 6:
                    lines_count = len(text_drag.buffer.lines)
                    dy_lines = max(1, int((my - (text_drag.y + text_drag.h - 6)) // line))
                    text_drag.buffer.scroll = max(0, min(text_drag.buffer.scroll + dy_lines, max(0, lines_count - rows)))

                text_drag.buffer.cursor = self.text_index(text_drag, mx, my)
                text_drag.buffer.reveal(rows, cols)
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
                if control.components.get('modal', False):
                    return
            return
        if kind in ("click", "scroll"):
            if kind == "click":
                self.root.relations.pop("text_drag", None)
                mx, my = event[1], event[2]
                now = monotonic()
                last_time, last_x, last_y, last_count, last_ctl = getattr(self, "_click_state", (0, 0, 0, 0, None))
                if len(event) >= 6:
                    click_count = event[5]
                elif (0.05 <= now - last_time <= 0.40) and abs(mx - last_x) <= 6 and abs(my - last_y) <= 6:
                    click_count = (last_count % 3) + 1
                else:
                    click_count = 1
                self._click_state = (now, mx, my, click_count, None)
                if len(event) < 6:
                    event = (*event, click_count)
            self.root.relations.pop("active_drag", None)
            controls = [e for e in self.controls() if self.visible(e) and contains(e, event[1], event[2])]
            controls.sort(key=lambda e: (e.components.get("layer", 2), e.depth), reverse=True)
            for control in controls:
                if kind == 'click' and event[3] == 1 and ("splitter" in control.tags or "scrollbar_thumb" in control.tags):
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
                    self.runtime.events.emit('ui.action', control, getattr(control.action, '__qualname__', type(control.action).__name__))
                    control.action()
                    return
                if "field" in control.tags and not control.components.get("readonly", False):
                    self.focus(control)
                    control.buffer.cursor = control.buffer.anchor = len(control.buffer.text)
                    return
                if "multiline" in control.tags:
                    self.focus(control)
                    click_count = event[5]
                    idx = self.text_index(control, mx, my)
                    text = control.buffer.text

                    if click_count == 2:
                        start = end = idx
                        if idx < len(text) and (text[idx].isalnum() or text[idx] == '_'):
                            while start > 0 and (text[start - 1].isalnum() or text[start - 1] == '_'):
                                start -= 1
                            while end < len(text) and (text[end].isalnum() or text[end] == '_'):
                                end += 1
                        elif idx < len(text) and not text[idx].isspace():
                            while start > 0 and not text[start - 1].isspace() and not (text[start - 1].isalnum() or text[start - 1] == '_'):
                                start -= 1
                            while end < len(text) and not text[end].isspace() and not (text[end].isalnum() or text[end] == '_'):
                                end += 1
                        control.buffer.anchor = start
                        control.buffer.cursor = end
                    elif click_count >= 3:
                        line_start = text.rfind("\n", 0, idx) + 1
                        line_end = text.find("\n", idx)
                        if line_end == -1:
                            line_end = len(text)
                        else:
                            line_end += 1
                        control.buffer.anchor = line_start
                        control.buffer.cursor = line_end
                    else:
                        control.buffer.cursor = idx
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
            if multiline:
                for m in self.references(control):
                    s, e = m.span()
                    if s < buffer.cursor < e:
                        buffer.cursor = buffer.anchor = e
                        break
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
                if multiline and key in ("LEFT", "RIGHT") and not ctrl:
                    jumped = False
                    for m in self.references(control):
                        s, e = m.span()
                        if key == "LEFT" and s < buffer.cursor <= e:
                            buffer.cursor = s
                            if not shift:
                                buffer.anchor = s
                            jumped = True
                            break
                        elif key == "RIGHT" and s <= buffer.cursor < e:
                            buffer.cursor = e
                            if not shift:
                                buffer.anchor = e
                            jumped = True
                            break
                    if not jumped:
                        move_dir = key
                        if ctrl and key == "LEFT":
                            move_dir = "WORD_LEFT"
                        elif ctrl and key == "RIGHT":
                            move_dir = "WORD_RIGHT"
                        buffer.move(move_dir, select=shift)
                else:
                    move_dir = key
                    if ctrl and key == "LEFT":
                        move_dir = "WORD_LEFT"
                    elif ctrl and key == "RIGHT":
                        move_dir = "WORD_RIGHT"
                    buffer.move(move_dir, select=shift)
            elif key in ("BACKSPACE", "DELETE"):
                deleted_pill = False
                if multiline and buffer.anchor == buffer.cursor:
                    for m in self.references(control):
                        s, e = m.span()
                        if (key == "BACKSPACE" and s < buffer.cursor <= e) or (key == "DELETE" and s <= buffer.cursor < e):
                            buffer.cursor = e
                            buffer.anchor = s
                            buffer.insert("")
                            deleted_pill = True
                            break
                if not deleted_pill:
                    if ctrl:
                        buffer.delete_word(backward=key == "BACKSPACE")
                    else:
                        buffer.delete(backward=key == "BACKSPACE")
            elif key in ("ENTER", "RETURN", "NUM_ENTER"):
                if multiline:
                    buffer.newline()
                elif "on_commit" in control.components:
                    control.on_commit()
                    self.focus()
            elif key == "TAB":
                if multiline:
                    buffer.indent(dedent=shift)
                else:
                    fields = [e for e in self.controls() if "field" in e.tags and self.visible(e) and not e.components.get("readonly", False)]
                    self.focus(fields[(fields.index(control)+(-1 if shift else 1)) % len(fields)])
            elif ctrl and key in ("SLASH", "/"):
                if multiline and hasattr(buffer, "toggle_comment"):
                    buffer.toggle_comment()
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
        lines = buffer.lines
        if row < len(lines):
            line_str = lines[row]
            for m in reference_matches(line_str) if control.components.get("inline_references") else ():
                s, e = m.span()
                if s < column < e:
                    column = s if (column - s) < (e - column) else e
                    break
        return buffer.index(row, column)

    def references(self, control):
        if not control.components.get("inline_references"):
            return ()
        text = control.buffer.text
        cached = control.components.get("reference_cache")
        if cached is None or cached[0] != text:
            cached = (text, reference_matches(text))
            control.components["reference_cache"] = cached
        return cached[1]

    def _sync_text(self, control):
        pitch = control.components.get("pitch", self.pitch)
        line_height = control.components.get("line_height", self.line_height)
        buffer = control.buffer
        rows = max(1, int((control.h-12)//line_height))
        columns = max(1, int((control.w-64)//pitch))
        lines = buffer.lines
        buffer.scroll = max(0, min(buffer.scroll, max(0, len(lines)-rows)))
        max_col = max((len(l) for l in lines), default=0)
        buffer.horizontal = max(0, min(buffer.horizontal, max(0, max_col-columns)))
        cursor_state = (buffer.text, buffer.cursor)
        if self.focused is control and control.components.get("_view_cursor") != cursor_state:
            buffer.reveal(rows, columns)
        put(control, _view_cursor=cursor_state)
        children = {child.components.get("part"): child for child in control.children}

        def part(name, kind, **values):
            if name not in children:
                children[name] = self.create(control, name, kind, part=name, text_part=True, **values)
            return children[name]

        caret = part("cursor", "rect", color=ACCENT, layer=control.layer+3)
        scroll_track = part("scroll_track", "scrollbar_track", color=(28, 36, 48), layer=control.layer+3)
        scrollbar = part("scrollbar", "scrollbar_thumb", color=(55, 75, 95), hover_color=(75, 115, 155), layer=control.layer+4)
        scrollbar.tags.add("scrollbar_thumb")
        scroll_track.tags.add("scrollbar_track")
        selection_start, selection_end = buffer.selection
        offset = sum(len(line)+1 for line in lines[:buffer.scroll])
        used = {"cursor", "scrollbar", "scroll_track"}
        reference_starts = {match.start() for match in self.references(control)}
        line_spans = control.components.get("line_spans")
        diag = control.components.get("diagnostic")
        err_row = (diag.get("line", 0) - 1) if diag else -1
        matching_brackets = control.components.get("matching_brackets")
        for index in range(rows):
            row = index+buffer.scroll
            if row >= len(lines):
                break
            highlight = part(f"selection:{index}", "rect", color=SELECTION, layer=control.layer+1)
            number = part(f"number:{index}", "label", text="", ink=MUTED, layer=control.layer+1)
            line = part(f"line:{index}", "label", text="", layer=control.layer+1)
            err_rect = part(f"error:{index}", "rect", color=ERROR, layer=control.layer+2)
            used.update((highlight.part, number.part, line.part, err_rect.part))
            y = control.y+6+index*line_height
            is_error = (row == err_row)
            put(number, visible=True, x=control.x+6, y=y, w=40, h=line_height, text=str(row+1), ink=(ERROR if is_error else MUTED), layer=control.layer+1)
            raw_line = lines[row]
            matches = [m for m in ASSET_PATTERN.finditer(raw_line) if offset + m.start() in reference_starts]
            display_line = raw_line
            if matches:
                line_chars = list(display_line)
                for m in matches:
                    cs, ce = m.span()
                    line_chars[cs:ce] = [" "] * (ce - cs)
                display_line = "".join(line_chars)

            spans = None
            if line_spans and row < len(line_spans):
                masked_spans, column = [], 0
                for chunk, color in line_spans[row]:
                    masked_spans.append((display_line[column:column + len(chunk)], color))
                    column += len(chunk)
                spans = slice_spans(masked_spans, buffer.horizontal, columns)
            put(line, visible=True, x=control.x+48, y=y, w=control.w-64, h=line_height,
                text=display_line[buffer.horizontal:buffer.horizontal+columns], spans=spans, layer=control.layer+1)

            pill_index = 0
            for m in matches:
                uid_str = m.group(1) or m.group(2)
                reg = getattr(self.runtime.assets, "registry", None) if hasattr(self.runtime, "assets") else None
                entry = reg.get(uid_str) if reg else None
                if entry:
                    etype = entry.get("type", "asset")
                    if etype == "system":
                        pill_label = f" ⚡ System: {entry['name']} "
                    elif etype == "image":
                        pill_label = f" 🖼️ Image: {entry['name']} "
                    elif etype == "audio":
                        pill_label = f" 🔊 Audio: {entry['name']} "
                    else:
                        pill_label = f" 📄 {etype.capitalize()}: {entry['name']} "
                else:
                    resolved_ent = None
                    if hasattr(self.runtime, "resolve"):
                        try:
                            resolved_ent = self.runtime.resolve(uid_str)
                        except Exception:
                            pass
                        if resolved_ent is None:
                            try:
                                from uuid import UUID
                                resolved_ent = self.runtime.resolve(UUID(uid_str))
                            except Exception:
                                pass
                    if resolved_ent is not None:
                        ename = resolved_ent.components.get("name") or str(resolved_ent.id)[:8]
                        pill_label = f" 🔷 Entity: {ename} "
                    elif m.group(0).startswith(("entity", "resolve", "entity_ref")):
                        pill_label = f" 🔷 Entity: {uid_str[:8]} "
                    else:
                        pill_label = f" 📦 Asset: {uid_str[:8]} "

                col_start, col_end = m.span()
                c_vis_start = max(0, col_start - buffer.horizontal)
                c_vis_end = min(columns, col_end - buffer.horizontal)

                if c_vis_end <= c_vis_start:
                    continue
                pill_part_name = f"pill:{index}:{pill_index}"
                pill_index += 1
                used.add(pill_part_name)
                pill = part(pill_part_name, "button", layer=control.layer+3)
                pill.tags.add("asset_pill")
                if c_vis_end > c_vis_start and (col_start >= buffer.horizontal or col_end > buffer.horizontal):
                    pill_x = line.x + c_vis_start * pitch
                    span_w = (c_vis_end - c_vis_start) * pitch
                    pill_w = min(max(span_w, len(pill_label) * pitch + 16), control.x + control.w - pill_x - 12)
                    pill.components["asset_id"] = uid_str
                    pill.components["asset_token"] = m.group(0)
                    pill.components["asset_name"] = entry["name"] if entry else pill_label.strip()
                    pill.components["asset_row"] = row
                    pill.components["asset_span"] = (col_start, col_end)
                    pill.components["text_control"] = control

                    if "on_click" not in pill.components:
                        def on_pill_click(control, event=None):
                            target = control.components["text_control"]
                            self.focus(target)
                            start, end = control.components["asset_span"]
                            column = start if event and event[1] < control.x + control.w / 2 else end
                            target.buffer.cursor = target.buffer.anchor = target.buffer.index(control.components["asset_row"], column)
                            target.components.touch("buffer")
                        pill.components["action"] = on_pill_click
                        pill.components["on_click"] = on_pill_click

                    pill_selected = (selection_start < offset + col_end and selection_end > offset + col_start)
                    pill_col = (60, 110, 165) if pill_selected else (35, 55, 75)
                    pill_hover = (75, 130, 190) if pill_selected else (50, 80, 110)
                    pill_ink = (255, 255, 255, 255) if pill_selected else (230, 245, 255)

                    put(pill, visible=True, x=pill_x, y=y + 1, w=pill_w, h=line_height - 2,
                        text=pill_label, color=pill_col, normal_color=pill_col, hover_color=pill_hover,
                        ink=pill_ink, layer=control.layer+3)
                else:
                    put(pill, visible=False)
            if is_error:
                col_start = max(0, diag.get("column", 1) - 1)
                col_end = max(col_start + 1, diag.get("end_column", col_start + 1) - 1)
                err_x = line.x + max(0, col_start - buffer.horizontal) * pitch
                err_w = max(pitch, (col_end - col_start) * pitch)
                put(err_rect, visible=True, x=err_x, y=y + line_height - 2, w=min(err_w, line.w), h=2, layer=control.layer+2)
            else:
                put(err_rect, visible=False)
            start = max(selection_start-offset-buffer.horizontal, 0)
            selected_width = len(lines[row]) + (1 if row < len(lines)-1 else 0)
            end = min(selection_end-offset-buffer.horizontal, selected_width-buffer.horizontal, columns)
            has_selection = (end > start and
                             selection_start < offset + len(lines[row]) + 1 and
                             selection_end > offset)
            put(highlight, visible=has_selection, x=line.x+start*pitch, y=y, w=max(0, end-start)*pitch, h=line_height, layer=control.layer+1, color=SELECTION)
            offset += len(lines[row])+1
        used.update(("bracket:0", "bracket:1"))
        for b_i in range(2):
            b_part = part(f"bracket:{b_i}", "rect", color=(88, 166, 255, 120), layer=control.layer+2)
            if matching_brackets and b_i < len(matching_brackets):
                b_row, b_col = matching_brackets[b_i]
                if (buffer.scroll <= b_row < buffer.scroll + rows and
                        buffer.horizontal <= b_col <= buffer.horizontal + columns):
                    b_x = control.x + 48 + (b_col - buffer.horizontal) * pitch
                    b_y = control.y + 6 + (b_row - buffer.scroll) * line_height
                    put(b_part, visible=True, x=b_x, y=b_y, w=pitch, h=line_height, layer=control.layer+2)
                else:
                    put(b_part, visible=False)
            else:
                put(b_part, visible=False)
        for name, child in children.items():
            if child.components.get("text_part") and name not in used:
                put(child, visible=False)
        row, column = buffer.position
        caret_visible = (self.focused is control and
                         buffer.scroll <= row < buffer.scroll+rows and
                         buffer.horizontal <= column <= buffer.horizontal+columns)
        put(caret, visible=caret_visible,
            x=control.x+48+(column-buffer.horizontal)*pitch, y=control.y+6+(row-buffer.scroll)*line_height, w=2, h=line_height, layer=control.layer+3)
        has_scrollbar = len(lines) > rows
        max_scroll = max(0, len(lines) - rows)
        if has_scrollbar:
            sb_w = 8
            track_x = control.x + control.w - sb_w - 2
            track_y = control.y + 4
            track_h = max(20, control.h - 8)
            thumb_h = max(16, int(track_h * (rows / len(lines))))
            travel = max(0, track_h - thumb_h)
            thumb_y = track_y + int(travel * (buffer.scroll / max_scroll)) if max_scroll > 0 else track_y

            def on_thumb_drag(t, ev):
                if max_scroll <= 0 or travel <= 0:
                    return
                rel_y = max(0, min(travel, ev[2] - track_y - thumb_h / 2))
                ratio = rel_y / travel
                control.buffer.scroll = int(round(ratio * max_scroll))
                control.components.touch("buffer")

            def on_track_click(tr, ev):
                click_y = ev[2]
                curr_thumb_y = thumb_y
                for c in tr.parent.children:
                    if c.components.get("part") == "scrollbar":
                        curr_thumb_y = c.y
                        break
                if click_y < curr_thumb_y:
                    control.buffer.scroll = max(0, control.buffer.scroll - rows)
                elif click_y > curr_thumb_y + thumb_h:
                    control.buffer.scroll = min(max_scroll, control.buffer.scroll + rows)
                else:
                    return
                control.components.touch("buffer")

            scrollbar.components["on_drag"] = on_thumb_drag
            scroll_track.components["on_click"] = on_track_click
            put(scroll_track, visible=True, x=track_x, y=track_y, w=sb_w, h=track_h)
            put(scrollbar, visible=True, x=track_x, y=thumb_y, w=sb_w, h=thumb_h)
        else:
            put(scroll_track, visible=False)
            put(scrollbar, visible=False)

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
                                      SELECTION, key=(control.id, "selection"), layer=layer+1)
                    graphics.rect(control.x, control.y+control.h-2, control.w, 2, ACCENT, key=(control.id, "focus"), layer=layer+1)
                    graphics.rect(control.x+6+(buffer.cursor-buffer.horizontal)*pitch, control.y+4, 1, control.h-8,
                                   ACCENT, key=(control.id, "caret"), layer=layer+2)
                text = buffer.text.replace("\n", " ")[buffer.horizontal:buffer.horizontal+width]
                text = text or control.components.get("hint", "")[:width]
                ink = INK if self.focused is control else control.components.get("ink", INK)
                graphics.text(text, control.x+6, control.y+5, color=ink, key=(control.id, "text"), layer=layer+2)
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

        is_ctrl = bool(getattr(self.input, "ctrl", False) or getattr(self, "ctrl_held", False))
        if is_ctrl:
            mx, my = getattr(self, "mouse_pos", (getattr(self.input, "x", 0), getattr(self.input, "y", 0)))
            provider = self.root.components.get("highlight_provider")
            if provider:
                stack = provider(mx, my)
            else:
                hits = [c for c in self.controls() if self.visible(c) and contains(c, mx, my)]
                stack = []
                if hits:
                    hits.reverse()
                    hits.sort(key=lambda c: (c.components.get("layer", 2), c.depth), reverse=True)
                    leaf = hits[0]
                    curr = leaf
                    idx = 0
                    while curr is not None and hasattr(curr, "w"):
                        if curr.w > 0 and curr.h > 0:
                            stack.append((curr, (curr.x, curr.y, curr.w, curr.h), STACK_COLORS[idx % len(STACK_COLORS)]))
                            idx += 1
                        curr = curr.parent

            outline_w = 2
            for i, (item, (rx, ry, rw, rh), color) in enumerate(reversed(stack)):
                layer = 6 + i
                item_key = getattr(item, "id", i)
                graphics.rect(rx, ry, rw, outline_w, color, key=("ctrl_hl", item_key, "top"), layer=layer)
                graphics.rect(rx, ry + rh - outline_w, rw, outline_w, color, key=("ctrl_hl", item_key, "bottom"), layer=layer)
                graphics.rect(rx, ry, outline_w, rh, color, key=("ctrl_hl", item_key, "left"), layer=layer)
                graphics.rect(rx + rw - outline_w, ry, outline_w, rh, color, key=("ctrl_hl", item_key, "right"), layer=layer)

        active_drag = self.root.components.get("entity_drag") or self.root.components.get("asset_drag")
        if active_drag and hasattr(self, "mouse_pos"):
            mx, my = self.mouse_pos
            if "entity" in active_drag or active_drag.get("type") == "entity":
                ename = active_drag.get("name", "Entity")
                label_text = f" 🔷 Entity: {ename} "
            else:
                icon = active_drag.get("icon", "📦")
                name = active_drag.get("name", "Asset")
                etype = active_drag.get("type", "asset")
                label_text = f" {icon} {etype.capitalize()}: {name} "
            pitch = getattr(self, "pitch", 8)
            chip_w = max(60, len(label_text) * pitch + 16)
            chip_h = 24
            graphics.rect(mx + 12, my + 12, chip_w, chip_h, (25, 45, 68, 245), key="active_drag_bg", layer=30)
            graphics.rect(mx + 12, my + 12, chip_w, 1, (88, 166, 255, 200), key="active_drag_top", layer=31)
            graphics.text(label_text, mx + 16, my + 16, color=(240, 248, 255, 255), key="active_drag_txt", layer=32)

        dock_drag = self.root.components.get("dock_drag")
        if dock_drag and hasattr(self, "mouse_pos"):
            mx, my = self.mouse_pos
            target_rect = dock_drag.get("target_rect")
            drop_zones = dock_drag.get("drop_zones")
            active_zone = dock_drag.get("zone")
            preview_rect = dock_drag.get("preview_rect")

            if preview_rect:
                px, py, pw, ph = preview_rect
                graphics.rect(px, py, pw, ph, (69, 182, 199, 50), key="dock_prev_fill", layer=24)
                graphics.rect(px, py, pw, 2, ACCENT, key="dock_prev_t", layer=25)
                graphics.rect(px, py + ph - 2, pw, 2, ACCENT, key="dock_prev_b", layer=25)
                graphics.rect(px, py, 2, ph, ACCENT, key="dock_prev_l", layer=25)
                graphics.rect(px + pw - 2, py, 2, ph, ACCENT, key="dock_prev_r", layer=25)

            if target_rect and drop_zones:
                tx, ty, tw, th = target_rect
                cx, cy = tx + tw // 2, ty + th // 2
                box_sz = 32
                guide_boxes = {
                    "center": (cx - box_sz // 2, cy - box_sz // 2, "Tab", "+"),
                    "left": (tx + 12, cy - box_sz // 2, "Left", "<"),
                    "right": (tx + tw - box_sz - 12, cy - box_sz // 2, "Right", ">"),
                    "top": (cx - box_sz // 2, ty + 12, "Top", "^"),
                    "bottom": (cx - box_sz // 2, ty + th - box_sz - 12, "Bottom", "v"),
                }
                for z_name, (gx, gy, z_label, z_icon) in guide_boxes.items():
                    is_active = (active_zone == z_name)
                    bg_col = (45, 95, 145, 240) if is_active else (25, 35, 48, 210)
                    border_col = ACCENT if is_active else (65, 85, 115, 220)
                    text_col = (255, 255, 255, 255) if is_active else (180, 200, 220, 240)

                    graphics.rect(gx, gy, box_sz, box_sz, bg_col, key=("dock_gbg", z_name), layer=26)
                    graphics.rect(gx, gy, box_sz, 1, border_col, key=("dock_gbt", z_name), layer=27)
                    graphics.rect(gx, gy + box_sz - 1, box_sz, 1, border_col, key=("dock_gbb", z_name), layer=27)
                    graphics.rect(gx, gy, 1, box_sz, border_col, key=("dock_gbl", z_name), layer=27)
                    graphics.rect(gx + box_sz - 1, gy, 1, box_sz, border_col, key=("dock_gbr", z_name), layer=27)
                    graphics.text(z_icon, gx + box_sz // 2 - 4, gy + box_sz // 2 - 8, color=text_col, key=("dock_gic", z_name), layer=28)

            panel_title = dock_drag.get("panel", "Panel").replace("_", " ").title()
            chip_text = f" Dock: {panel_title} "
            pitch = getattr(self, "pitch", 8)
            cw = max(70, len(chip_text) * pitch + 16)
            graphics.rect(mx + 14, my + 14, cw, 24, (20, 36, 54, 240), key="dock_chip_bg", layer=30)
            graphics.rect(mx + 14, my + 14, cw, 1, ACCENT, key="dock_chip_top", layer=31)
            graphics.text(chip_text, mx + 18, my + 18, color=(240, 248, 255, 255), key="dock_chip_txt", layer=32)
