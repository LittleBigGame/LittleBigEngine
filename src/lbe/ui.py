"""General entity UI primitives shared by applications and tools."""

from pathlib import Path

from .text import TextBuffer

PITCH = 8
LINE = 20
BG = (17, 23, 31)
PANEL = (25, 34, 45)
FIELD = (34, 45, 59)
ACCENT = (69, 182, 199)
INK = (220, 230, 239, 255)
MUTED = (145, 163, 183, 255)


def put(entity, **values):
    """Set changed scalar/control properties without redundant notifications."""
    for key, value in values.items():
        if entity.components.get(key) != value:
            entity.components[key] = value


def contains(entity, x, y):
    return entity.x <= x < entity.x+entity.w and entity.y <= y < entity.y+entity.h


def stack(parent, children, *, axis="y", gap=8, padding=8):
    """Lay out ordinary child entities along an axis; sizes remain explicit."""
    if axis not in ("x", "y"):
        raise ValueError("axis must be x or y")
    offset = padding
    for child in children:
        put(child, x=parent.x+(offset if axis == "x" else padding),
            y=parent.y+(offset if axis == "y" else padding))
        offset += (child.w if axis == "x" else child.h)+gap


class UI:
    """Controls are entities; this object provides operations and derived indexes.

    Callbacks are component values: action(), on_commit(), on_click(control,event),
    on_scroll(control,event), on_key(event), and on_ui_error(message).
    """

    def __init__(self, root, window, graphics, input_state):
        self.root = root
        self.runtime = root.runtime
        self.window = window
        self.graphics = graphics
        self.input = input_state

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
        return self.create(parent, name, "field", **values)

    def button(self, parent, name, text, action, **values):
        values.setdefault("color", FIELD)
        return self.create(parent, name, "button", text=text, action=action, **values)

    def multiline(self, parent, name, text="", **values):
        values.setdefault("buffer", TextBuffer(text))
        values.setdefault("color", BG)
        return self.create(parent, name, "multiline", **values)

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
                self._sync_text(control)

    def dispatch(self, event):
        kind = event[0]
        if kind == "drag" and self.focused is not None and "multiline" in self.focused.tags:
            control = self.focused
            control.buffer.cursor = self.text_index(control, event[1], event[2])
            control.components.touch("buffer")
            return
        if kind in ("click", "scroll"):
            controls = [e for e in self.controls() if self.visible(e) and contains(e, event[1], event[2])]
            controls.sort(key=lambda e: (e.components.get("layer", 2), e.depth), reverse=True)
            for control in controls:
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
                    control.buffer.cursor = control.buffer.anchor = self.text_index(control, event[1], event[2])
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
        buffer = control.buffer
        multiline = "multiline" in control.tags
        if kind == "text":
            buffer.insert(event[1] if multiline else event[1].replace("\n", " "))
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
                buffer.insert(text if multiline else text.replace("\n", " "))
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
                buffer.reveal(max(1, int((control.h-12)//LINE)), max(1, int((control.w-64)//PITCH)))

    @staticmethod
    def text_index(control, x, y):
        buffer = control.buffer
        row = max(0, int((y-control.y-6)//LINE))+buffer.scroll
        column = max(0, round((x-control.x-48)/PITCH))+buffer.horizontal
        return buffer.index(row, column)

    def _sync_text(self, control):
        buffer = control.buffer
        rows = max(1, int((control.h-12)//LINE))
        columns = max(1, int((control.w-64)//PITCH))
        lines = buffer.text.split("\n")
        buffer.scroll = max(0, min(buffer.scroll, max(0, len(lines)-1)))
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
        for index in range(rows):
            row = index+buffer.scroll
            if row >= len(lines):
                break
            highlight = part(f"selection:{index}", "rect", color=(44, 76, 105), layer=control.layer)
            number = part(f"number:{index}", "label", text="", ink=MUTED, layer=control.layer)
            line = part(f"line:{index}", "label", text="", layer=control.layer)
            used.update((highlight.part, number.part, line.part))
            y = control.y+6+index*LINE
            put(number, visible=True, x=control.x+6, y=y, w=40, h=LINE, text=str(row+1))
            put(line, visible=True, x=control.x+48, y=y, w=control.w-64, h=LINE,
                text=lines[row][buffer.horizontal:buffer.horizontal+columns])
            start = max(selection_start-offset-buffer.horizontal, 0)
            end = min(selection_end-offset-buffer.horizontal, len(lines[row])-buffer.horizontal, columns)
            put(highlight, visible=True, x=line.x+start*PITCH, y=y, w=max(0, end-start)*PITCH, h=LINE)
            offset += len(lines[row])+1
        for name, child in children.items():
            if name not in used:
                put(child, visible=False)
        row, column = buffer.position
        put(caret, visible=self.focused is control and buffer.scroll <= row < buffer.scroll+rows,
            x=control.x+48+(column-buffer.horizontal)*PITCH, y=control.y+6+(row-buffer.scroll)*LINE, w=2, h=LINE)
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
                buffer = control.buffer
                width = max(1, int((control.w-12)//PITCH))
                if self.focused is control:
                    buffer.reveal(1, width)
                    start, end = buffer.selection
                    start, end = max(0, start-buffer.horizontal), min(width, end-buffer.horizontal)
                    if end > start:
                        graphics.rect(control.x+6+start*PITCH, control.y+3, (end-start)*PITCH, control.h-6,
                                      (44, 76, 105), key=(control.id, "selection"), layer=layer+1)
                    graphics.rect(control.x, control.y+control.h-2, control.w, 2, ACCENT, key=(control.id, "focus"), layer=layer+1)
                    graphics.rect(control.x+6+(buffer.cursor-buffer.horizontal)*PITCH, control.y+4, 1, control.h-8,
                                  ACCENT, key=(control.id, "caret"), layer=layer+2)
                text = buffer.text.replace("\n", " ")[buffer.horizontal:buffer.horizontal+width]
                text = text or control.components.get("hint", "")[:width]
                graphics.text(text, control.x+6, control.y+5, color=INK, key=(control.id, "text"), layer=layer+2)
            elif "text" in control.components:
                inset = 8 if "panel" in control.tags or "button" in control.tags else 0
                width = max(1, int((control.w-inset*2)//PITCH))
                graphics.text(str(control.text)[:width], control.x+inset, control.y+(8 if "panel" in control.tags else 4),
                              color=control.components.get("ink", INK), key=(control.id, "text"), layer=layer+1)
