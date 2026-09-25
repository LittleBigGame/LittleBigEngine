"""Entity-based editor composition and generic editing operations."""

import ast
from pathlib import Path
import tempfile

from .scene import build_demo
from .space import screen_to_world
from .text import TextBuffer

BG = (17, 23, 31)
PANEL = (25, 34, 45)
FIELD = (34, 45, 59)
ACCENT = (69, 182, 199)
INK = (220, 230, 239, 255)
MUTED = (145, 163, 183, 255)
PITCH = 8
LINE = 20


def safe_repr(value):
    try:
        return repr(value)
    except Exception:
        return f"<{type(value).__name__}>"


def parse_value(text):
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        raise ValueError("Use a Python literal; put text in quotes") from None


def put(entity, **values):
    for key, value in values.items():
        if entity.components.get(key) != value:
            entity.components[key] = value


def contains(entity, x, y):
    return entity.x <= x < entity.x + entity.w and entity.y <= y < entity.y + entity.h


class Editor:
    """Coordinator over real entities; widget state lives on those entities."""

    def __init__(self, runtime, project):
        self.runtime = runtime
        self.project = Path(project).resolve()
        self.project.mkdir(parents=True, exist_ok=True)
        self.window = runtime.services["window"]
        self.graphics = runtime.services["graphics"]
        self.input = runtime.services["input"]
        self.app = next(e for e in runtime.entities if e.components.get("name") == "Application")
        self.game = next(e for e in runtime.entities if e.components.get("name") == "Game")
        self.viewport = self.game.relations["viewport"]
        self.camera = self.game.relations["camera"]
        self.widgets = {}
        self.hierarchy_rows = []
        self.component_rows = []
        self.system_rows = []
        self.line_rows = []
        self.extra_panels = []
        self._saved_source = None
        self._pending_discard = None
        self.app.status = "Ready | Select an entity to inspect its data"
        self.app.relations["selection"] = self.game.children[0]
        self.header = self.make(self.app, "Header", "panel", text="LBE  /  LittleBigEngine", color=BG)
        self.hierarchy = self.make(self.app, "HierarchyPanel", "panel", text="HIERARCHY", scroll=0,
                                   expanded={self.app.id, self.game.id})
        self.inspector = self.make(self.app, "InspectorPanel", "panel", text="INSPECTOR", scroll=0)
        self.code_panel = self.make(self.app, "CodeEditorPanel", "panel", text="SYSTEM SOURCE")
        self.status = self.make(self.app, "StatusBar", "label", text="")
        self.code = self.make(self.code_panel, "TextArea", "code", buffer=TextBuffer(), color=BG)
        self.caret = self.make(self.code, "Cursor", "rect", color=ACCENT, layer=4)
        self.scrollbar = self.make(self.code, "VerticalScrollbar", "rect", color=ACCENT, layer=4)
        self.path_field = self.field(self.code_panel, "SourcePath", "render.py", hint="system_name.py")
        self.path_field.on_commit = self.open_path
        self.new_button = self.button(self.code_panel, "NewSource", "New", self.new_source)
        self.open_button = self.button(self.code_panel, "OpenSource", "Open", self.open_path)
        self.save_button = self.button(self.code_panel, "SaveSource", "Save / reload", self.save)
        self.attach_button = self.button(self.code_panel, "AttachSource", "Attach", self.attach)
        self.panel_button = self.button(self.header, "OpenPanel", "Inspect in panel", self.open_panel)
        self.system_panel_button = self.button(self.header, "InspectSystem", "Inspect system", self.inspect_system)
        self.detach_button = self.button(self.header, "DetachSystem", "Detach system", self.detach_system)
        self.zoom_label = self.make(self.app, "ViewportCaption", "label", text="WORLD", ink=MUTED)
        self.selection_label = self.make(self.inspector, "Selection", "label", text="")
        self.identity_label = self.make(self.inspector, "Identity", "label", text="", ink=MUTED)
        self.add_name = self.field(self.inspector, "ComponentName", "", hint="component name")
        self.add_value = self.field(self.inspector, "ComponentValue", "", hint="value, e.g. 2.0")
        self.add_button = self.button(self.inspector, "AddComponent", "+", self.add_component)
        self.tags_field = self.field(self.inspector, "Tags", "", hint="tags, comma separated")
        self.tags_field.on_commit = self.commit_tags
        self.parent_field = self.field(self.inspector, "Parent", "", hint="parent name or UUID; blank detaches")
        self.parent_field.on_commit = self.commit_parent
        self.relation_field = self.field(self.inspector, "Relations", "", hint="relation=entity name (blank target removes)")
        self.relation_field.on_commit = self.commit_relation
        self.metadata = self.make(self.inspector, "Metadata", "label", text="", ink=MUTED)
        self.system_label = self.make(self.inspector, "SystemsTitle", "label", text="SYSTEMS", ink=MUTED)
        self.tags_label = self.make(self.inspector, "TagsLabel", "label", text="Tags", ink=MUTED)
        self.parent_label = self.make(self.inspector, "ParentLabel", "label", text="Parent", ink=MUTED)
        self.relations_label = self.make(self.inspector, "RelationsLabel", "label", text="Link", ink=MUTED)
        self.code_info = self.make(self.code_panel, "SourceInfo", "label", text="", ink=MUTED)
        for name in ("render", "editor"):
            destination = self.project / f"{name}.py"
            if not destination.exists():
                destination.write_text((Path(__file__).parent / "scripts" / f"{name}.py").read_text(encoding="utf-8"), encoding="utf-8")
        self.game.systems.reload("render", runtime.assets.system(self.project / "render.py"))
        self.open_system(self.game, "render")

    @property
    def selected(self):
        return self.app.relations.get("selection", self.game)

    @property
    def focused(self):
        return self.app.relations.get("focus")

    def make(self, parent, name, kind, **values):
        defaults = dict(name=name, x=0, y=0, w=0, h=0, visible=True, layer=2, color=PANEL)
        defaults.update(values)
        entity = self.runtime.create(parent=parent, tags=["ui", kind], **defaults)
        self.widgets[name] = entity
        return entity

    def field(self, parent, name, text, **values):
        return self.make(parent, name, "field", buffer=TextBuffer(text), color=FIELD, **values)

    def button(self, parent, name, text, action):
        return self.make(parent, name, "button", text=text, action=action, color=FIELD)

    def message(self, text):
        self.app.status = text

    def select(self, entity):
        self.app.relations["selection"] = entity
        self.inspector.scroll = 0
        if "focus" in self.app.relations:
            del self.app.relations["focus"]

    def field_text(self, field, text):
        if self.focused is not field and field.buffer.text != text:
            field.buffer = TextBuffer(text)

    def layout(self):
        w, h = self.window.width, self.window.height
        left = 370
        split = max(330, int(h * 0.45))
        put(self.header, x=0, y=0, w=w, h=44)
        put(self.panel_button, x=w-190, y=8, w=174, h=28)
        put(self.system_panel_button, x=w-350, y=8, w=150, h=28)
        put(self.detach_button, x=w-510, y=8, w=150, h=28)
        put(self.hierarchy, x=8, y=52, w=left-16, h=240)
        put(self.inspector, x=8, y=300, w=left-16, h=h-336)
        put(self.viewport, x=left+8, y=80, w=w-left-24, h=split-92)
        put(self.zoom_label, x=left+12, y=56, w=500, h=20,
            text=f"WORLD  /  {self.camera.zoom:.0f} px per metre  /  scroll to zoom")
        put(self.code_panel, x=left+8, y=split, w=w-left-24, h=h-split-36)
        put(self.status, x=16, y=h-25, w=w-32, h=20, text=self.app.status)
        cp = self.code_panel
        put(self.path_field, x=cp.x+12, y=cp.y+32, w=max(130, cp.w-380), h=28)
        for button, offset, width in ((self.new_button, -360, 52), (self.open_button, -302, 52),
                                     (self.save_button, -244, 126), (self.attach_button, -112, 100)):
            put(button, x=cp.x+cp.w+offset, y=cp.y+32, w=width, h=28)
        put(self.code, x=cp.x+12, y=cp.y+68, w=cp.w-24, h=cp.h-100)
        put(self.code_info, x=cp.x+12, y=cp.y+cp.h-25, w=cp.w-24, h=20)
        ip = self.inspector
        put(self.selection_label, x=ip.x+12, y=ip.y+32, w=ip.w-24, h=20,
            text=self.selected.components.get("name", str(self.selected.id)))
        put(self.identity_label, x=ip.x+12, y=ip.y+54, w=ip.w-24, h=20,
            text=str(self.selected.id))
        bottom = ip.y+ip.h
        put(self.add_name, x=ip.x+12, y=bottom-206, w=120, h=26)
        put(self.add_value, x=ip.x+138, y=bottom-206, w=ip.w-186, h=26)
        put(self.add_button, x=ip.x+ip.w-42, y=bottom-206, w=30, h=26)
        put(self.tags_field, x=ip.x+76, y=bottom-172, w=ip.w-88, h=26)
        put(self.parent_field, x=ip.x+76, y=bottom-140, w=ip.w-88, h=26)
        put(self.relation_field, x=ip.x+76, y=bottom-108, w=ip.w-88, h=26)
        for label, field in ((self.tags_label, self.tags_field), (self.parent_label, self.parent_field), (self.relations_label, self.relation_field)):
            put(label, x=ip.x+12, y=field.y+4, w=64, h=22)
        put(self.metadata, x=ip.x+12, y=bottom-78, w=ip.w-24, h=18,
            text=f"{len(self.selected.children)} children | {len(self.selected.relations)} relations")
        put(self.system_label, x=ip.x+12, y=bottom-55, w=90, h=18)

    def hierarchy_sync(self):
        visible = []
        stack = [(e, 0) for e in reversed(self.runtime.entities) if e.parent is None]
        expanded = self.hierarchy.expanded
        while stack and len(visible) < 10000:
            entity, depth = stack.pop()
            visible.append((entity, depth))
            if entity.id in expanded:
                stack.extend((child, depth+1) for child in reversed(entity.children))
        capacity = int((self.hierarchy.h-34) // 22)
        put(self.hierarchy, scroll=max(0, min(self.hierarchy.scroll, max(0, len(visible)-capacity))))
        while len(self.hierarchy_rows) < capacity:
            row = self.make(self.hierarchy, f"HierarchyRow{len(self.hierarchy_rows)}", "hierarchy_row", text="", indent=0)
            self.hierarchy_rows.append(row)
        for index, row in enumerate(self.hierarchy_rows):
            source = index + self.hierarchy.scroll
            if index >= capacity or source >= len(visible):
                put(row, visible=False)
                continue
            target, depth = visible[source]
            if row.relations.get("target") is not target:
                row.relations["target"] = target
            name = str(target.components.get("name", str(target.id)[:8]))
            marker = "-" if target.id in expanded else "+"
            text = "  " * min(depth, 8) + (marker if target.children else " ") + " " + name
            put(row, visible=True, x=self.hierarchy.x+8, y=self.hierarchy.y+32+index*22,
                w=self.hierarchy.w-16, h=22, text=text, indent=min(depth, 8)*16,
                color=(39, 78, 92) if target is self.selected else PANEL)

    def inspector_sync(self):
        entity = self.selected
        items = tuple(entity.components.items())
        capacity = max(1, int((self.inspector.h-292)//28))
        put(self.inspector, scroll=max(0, min(self.inspector.scroll, max(0, len(items)-capacity))))
        while len(self.component_rows) < capacity:
            n = len(self.component_rows)
            label = self.make(self.inspector, f"ComponentLabel{n}", "label", text="", ink=MUTED)
            field = self.field(self.inspector, f"ComponentField{n}", "")
            self.component_rows.append((label, field))
        for index, (label, field) in enumerate(self.component_rows):
            source = index + self.inspector.scroll
            shown = index < capacity and source < len(items)
            put(label, visible=shown)
            put(field, visible=shown)
            if not shown:
                continue
            key, value = items[source]
            editable = type(value) in (int, float, bool, str, tuple, list, dict, type(None))
            y = self.inspector.y+82+index*28
            put(label, x=self.inspector.x+12, y=y+4, w=112, h=24, text=key)
            put(field, x=self.inspector.x+126, y=y, w=self.inspector.w-138, h=25, readonly=not editable)
            if field.components.get("component_key") != key or field.relations.get("target") is not entity:
                if self.focused is field:
                    del self.app.relations["focus"]
                field.component_key = key
                field.relations["target"] = entity
                field.on_commit = lambda f=field: self.commit_component(f)
            self.field_text(field, safe_repr(value))
        self.field_text(self.tags_field, ", ".join(entity.tags))
        self.field_text(self.parent_field, str(entity.parent.components.get("name", entity.parent.id)) if entity.parent else "")
        systems = tuple(entity.systems.items())
        while len(self.system_rows) < len(systems):
            index = len(self.system_rows)
            button = self.button(self.inspector, f"System{index}", "", lambda: None)
            self.system_rows.append(button)
        for index, button in enumerate(self.system_rows):
            put(button, visible=index < len(systems))
            if index < len(systems):
                name, instance = systems[index]
                put(button, x=self.inspector.x+12+index*108, y=self.inspector.y+self.inspector.h-32,
                    w=102, h=24, text=name + (" !" if instance.errors else ""))
                if button.components.get("system_key") != (entity.id, name):
                    button.system_key = (entity.id, name)
                    button.action = lambda e=entity, n=name: self.open_system(e, n)
        for owner in self.runtime.entities:
            for name, instance in owner.systems.items():
                if instance.errors:
                    error = instance.errors[-1]
                    self.message(f"{error.source}: {error.message}")

    def code_sync(self):
        buffer = self.code.buffer
        rows = max(1, int((self.code.h-12)//LINE))
        columns = max(1, int((self.code.w-64)//PITCH))
        lines = buffer.text.split("\n")
        buffer.scroll = max(0, min(buffer.scroll, max(0, len(lines)-1)))
        while len(self.line_rows) < rows:
            index = len(self.line_rows)
            highlight = self.make(self.code, f"Selection{index}", "rect", color=(44, 76, 105))
            number = self.make(self.code, f"LineNumber{index}", "label", text="", ink=MUTED)
            line = self.make(self.code, f"SourceLine{index}", "label", text="")
            self.line_rows.append((highlight, number, line))
        selection_start, selection_end = buffer.selection
        offset = sum(len(line)+1 for line in lines[:buffer.scroll])
        for index, (highlight, number, line) in enumerate(self.line_rows):
            row = index+buffer.scroll
            shown = index < rows and row < len(lines)
            for item in (highlight, number, line):
                put(item, visible=shown)
            if not shown:
                continue
            y = self.code.y+6+index*LINE
            put(number, x=self.code.x+6, y=y, w=40, h=LINE, text=str(row+1))
            put(line, x=self.code.x+48, y=y, w=self.code.w-64, h=LINE,
                text=lines[row][buffer.horizontal:buffer.horizontal+columns])
            start = max(selection_start-offset-buffer.horizontal, 0)
            end = min(selection_end-offset-buffer.horizontal, len(lines[row])-buffer.horizontal, columns)
            put(highlight, x=line.x+start*PITCH, y=y, w=max(0, end-start)*PITCH, h=LINE)
            offset += len(lines[row])+1
        row, col = buffer.position
        put(self.caret, visible=self.focused is self.code and buffer.scroll <= row < buffer.scroll+rows,
            x=self.code.x+48+(col-buffer.horizontal)*PITCH, y=self.code.y+6+(row-buffer.scroll)*LINE, w=2, h=LINE)
        put(self.scrollbar, x=self.code.x+self.code.w-5,
            y=self.code.y+self.code.h*buffer.scroll/max(len(lines), rows), w=3,
            h=max(12, self.code.h*min(1, rows/len(lines))))
        put(self.code_info, text=f"Ln {row+1}, Col {col+1} | Attach target: {self.selected.components.get('name', self.selected.id)} | Ctrl+S save")

    def draw(self):
        graphics = self.graphics
        graphics.rect(0, 0, self.window.width, self.window.height, BG, key="background", layer=0)
        graphics.rect(self.viewport.x, self.viewport.y, self.viewport.w, self.viewport.h,
                      (12, 18, 25), key="viewport-background", layer=0)
        for entity in self.runtime.query(tags="ui"):
            if not entity.components.get("visible", True):
                continue
            layer = entity.components.get("layer", 2)
            if any(tag in entity.tags for tag in ("panel", "button", "field", "hierarchy_row", "code", "rect")):
                graphics.rect(entity.x, entity.y, entity.w, entity.h, entity.color, key=entity.id, layer=layer)
            if "field" in entity.tags:
                buffer = entity.buffer
                text = buffer.text.replace("\n", " ")
                width = max(1, int((entity.w-12)//PITCH))
                if self.focused is entity:
                    buffer.reveal(1, width)
                    graphics.rect(entity.x, entity.y+entity.h-2, entity.w, 2, ACCENT, key=(entity.id, "focus"), layer=layer+1)
                    start, end = buffer.selection
                    start = max(0, start-buffer.horizontal)
                    end = min(width, end-buffer.horizontal)
                    if end > start:
                        graphics.rect(entity.x+6+start*PITCH, entity.y+3, (end-start)*PITCH, entity.h-6,
                                      (44, 76, 105), key=(entity.id, "selection"), layer=layer+1)
                    column = buffer.cursor-buffer.horizontal
                    graphics.rect(entity.x+6+column*PITCH, entity.y+4, 1, entity.h-8,
                                  ACCENT, key=(entity.id, "caret"), layer=layer+2)
                text = text[buffer.horizontal:buffer.horizontal+width] or entity.components.get("hint", "")[:width]
                graphics.text(text, entity.x+6, entity.y+5, color=INK, key=(entity.id, "text"), layer=layer+2)
            elif "text" in entity.components:
                inset = 8 if "panel" in entity.tags or "button" in entity.tags or "hierarchy_row" in entity.tags else 0
                width = max(1, int((entity.w-inset*2)//PITCH))
                graphics.text(str(entity.text)[:width], entity.x+inset, entity.y+(8 if "panel" in entity.tags else 4),
                              color=entity.components.get("ink", INK), key=(entity.id, "text"), layer=layer+1)

    def _safe(self, action):
        try:
            action()
        except Exception as error:
            self.message(f"{type(error).__name__}: {error}")

    def update(self, dt):
        self.layout()
        self.hierarchy_sync()
        self.inspector_sync()
        for event in self.input.drain():
            self._safe(lambda event=event: self.handle(event))
        self.code_sync()
        self.panels_sync()

    def handle(self, event):
        kind = event[0]
        if kind in ("click", "drag"):
            x, y = event[1:3]
            if kind == "drag" and self.focused is self.code:
                self.code.buffer.cursor = self.code_index(x, y)
                return
            controls = [e for e in self.runtime.query(tags="ui")
                        if e.components.get("visible", True) and contains(e, x, y)]
            controls.sort(key=lambda e: (e.components.get("layer", 2), e.depth), reverse=True)
            for entity in controls:
                if "button" in entity.tags:
                    entity.action()
                    return
                if "hierarchy_row" in entity.tags:
                    target = entity.relations["target"]
                    if x < entity.x+entity.indent+24:
                        expanded = set(self.hierarchy.expanded)
                        expanded.symmetric_difference_update({target.id})
                        self.hierarchy.expanded = expanded
                    self.select(target)
                    return
                if "field" in entity.tags and not entity.components.get("readonly", False):
                    if event[3] == 4 and "component_key" in entity.components:
                        self.open_panel(target=entity.relations["target"], component=entity.component_key)
                        return
                    self.app.relations["focus"] = entity
                    entity.buffer.cursor = entity.buffer.anchor = len(entity.buffer.text)
                    return
                if entity is self.code or self.code in entity.ancestors:
                    self.app.relations["focus"] = self.code
                    self.code.buffer.cursor = self.code.buffer.anchor = self.code_index(x, y)
                    return
                if entity in self.extra_panels:
                    return
            if contains(self.viewport, x, y):
                wx, wy = screen_to_world(self.camera, self.viewport, x, y)
                hits = set(self.runtime.services["space"].query(wx, wy))
                target = next((e for e in reversed(self.game.children) if e in hits), None)
                if target:
                    self.select(target)
            return
        if kind == "scroll":
            x, y, _, amount = event[1:]
            if contains(self.hierarchy, x, y):
                self.hierarchy.scroll = max(0, self.hierarchy.scroll-int(amount)*3)
            elif contains(self.inspector, x, y):
                self.inspector.scroll = max(0, self.inspector.scroll-int(amount)*3)
            elif contains(self.code, x, y):
                self.code.buffer.scroll = max(0, self.code.buffer.scroll-int(amount)*3)
            elif contains(self.viewport, x, y):
                self.camera.zoom = max(4, min(512, self.camera.zoom*1.1**amount))
            return
        focus = self.focused
        if kind == "key" and event[1] == "S" and event[2]:
            self.save()
            return
        if focus is None or "buffer" not in focus.components:
            return
        buffer = focus.buffer
        if kind == "text":
            buffer.insert(event[1] if focus is self.code else event[1].replace("\n", " "))
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
                buffer.insert(text if focus is self.code else text.replace("\n", " "))
            elif ctrl and key == "Z":
                buffer.undo(redo=shift)
            elif key in ("LEFT", "RIGHT", "UP", "DOWN", "HOME", "END", "FILE_HOME", "FILE_END",
                         "PAGEUP", "PAGEDOWN", "WORD_LEFT", "WORD_RIGHT"):
                buffer.move(key, select=shift)
            elif key == "BACKSPACE":
                buffer.delete()
            elif key == "DELETE":
                buffer.delete(backward=False)
            elif key in ("ENTER", "RETURN", "NUM_ENTER"):
                if focus is self.code:
                    buffer.newline()
                elif "on_commit" in focus.components:
                    focus.on_commit()
                    if "focus" in self.app.relations:
                        del self.app.relations["focus"]
            elif key == "TAB":
                if focus is self.code:
                    buffer.insert("    ")
                else:
                    fields = [e for e in self.runtime.query(tags="field") if e.visible and not e.components.get("readonly", False)]
                    self.app.relations["focus"] = fields[(fields.index(focus)+(-1 if shift else 1)) % len(fields)]
            elif key == "ESCAPE":
                del self.app.relations["focus"]
        if focus.alive:
            focus.components.touch("buffer")
        if focus is self.code:
            buffer.reveal(max(1, int((self.code.h-12)//LINE)), max(1, int((self.code.w-64)//PITCH)))

    def code_index(self, x, y):
        buffer = self.code.buffer
        row = max(0, int((y-self.code.y-6)//LINE))+buffer.scroll
        col = max(0, round((x-self.code.x-48)/PITCH))+buffer.horizontal
        return buffer.index(row, col)

    def commit_component(self, field):
        target, key = field.relations["target"], field.component_key
        target.components[key] = parse_value(field.buffer.text)
        self.message(f"Updated {key}")

    def add_component(self):
        name = self.add_name.buffer.text.strip()
        if not name:
            raise ValueError("Enter a component name")
        self.selected.components[name] = parse_value(self.add_value.buffer.text)
        self.add_name.buffer = TextBuffer()
        self.add_value.buffer = TextBuffer()
        self.message(f"Added {name}")

    def commit_tags(self):
        tags = {tag.strip() for tag in self.tags_field.buffer.text.split(",") if tag.strip()}
        for tag in set(self.selected.tags)-tags:
            self.selected.tags.discard(tag)
        for tag in tags:
            self.selected.tags.add(tag)
        self.message("Tags updated")

    def resolve_name(self, text):
        text = text.strip()
        try:
            return self.runtime.resolve(text)
        except (ValueError, KeyError):
            matches = [e for e in self.runtime.entities if e.components.get("name") == text]
            if len(matches) != 1:
                raise ValueError("Use a unique entity name or UUID") from None
            return matches[0]

    def commit_parent(self):
        text = self.parent_field.buffer.text.strip()
        self.selected.parent = self.resolve_name(text) if text else None
        self.message("Parent updated")

    def commit_relation(self):
        name, separator, text = self.relation_field.buffer.text.partition("=")
        if not separator or not name.strip():
            raise ValueError("Use relation=entity name or UUID")
        if text.strip():
            self.selected.relations[name.strip()] = self.resolve_name(text)
        else:
            self.selected.relations.pop(name.strip(), None)
        self.relation_field.buffer = TextBuffer()
        self.message("Relation updated")

    def source_path(self):
        name = self.path_field.buffer.text.strip()
        path = (self.project / name).resolve()
        if not name or path.suffix != ".py" or not path.is_relative_to(self.project):
            raise ValueError("Use a .py path inside the project folder")
        return path

    def new_source(self):
        if not self.confirm_discard("new"):
            return
        self.path_field.buffer = TextBuffer("new_system.py")
        self.code.buffer = TextBuffer("def update(dt):\n    pass\n")
        self._saved_source = (self.path_field.buffer.text, self.code.buffer.text)
        self.message("New source: choose a filename, edit, then Save / reload")

    def open_path(self):
        path = self.source_path()
        text = path.read_text(encoding="utf-8")
        if not self.confirm_discard("open"):
            return
        self.code.buffer = TextBuffer(text)
        self._saved_source = (self.path_field.buffer.text, text)
        self.message(f"Opened {path.name}")

    def open_system(self, owner, name):
        if not self.confirm_discard((owner.id, name)):
            return
        instance = owner.systems[name]
        path = Path(instance.definition.path)
        if path.is_relative_to(self.project):
            self.path_field.buffer = TextBuffer(str(path.relative_to(self.project)))
        else:
            self.path_field.buffer = TextBuffer(f"{name}.py")
        self.code.buffer = TextBuffer(instance.definition.source)
        self._saved_source = (self.path_field.buffer.text, self.code.buffer.text)
        self.code.system_name = name
        self.code.relations["owner"] = owner
        self.message(f"{name} | {'running' if instance.running else 'stopped'} | {', '.join(instance.lifecycle)}")

    def confirm_discard(self, action):
        dirty = self._saved_source is not None and self._saved_source[1] != self.code.buffer.text
        if dirty and self._pending_discard != (action, self.code.buffer.text):
            self._pending_discard = (action, self.code.buffer.text)
            self.message("Unsaved source. Save first, or repeat the action to discard edits.")
            return False
        self._pending_discard = None
        return True

    def save(self):
        path = self.source_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as stream:
            stream.write(self.code.buffer.text)
            temporary = Path(stream.name)
        temporary.replace(path)
        self._saved_source = (self.path_field.buffer.text, self.code.buffer.text)
        definition = self.runtime.assets.system(path)
        count = 0
        for entity in self.runtime.entities:
            for name, instance in tuple(entity.systems.items()):
                if Path(instance.definition.path) == path:
                    updated = entity.systems.reload(name, definition)
                    if updated.definition is not definition or not updated.running:
                        raise RuntimeError(f"{name}: {updated.errors[-1].message if updated.errors else 'reload failed'}")
                    count += 1
        self.message(f"Saved {path.name}; reloaded {count} attachment(s)")

    def attach(self):
        self.save()
        path = self.source_path()
        definition = self.runtime.assets.system(path)
        if path.stem in self.selected.systems:
            instance = self.selected.systems.reload(path.stem, definition)
        else:
            instance = self.selected.systems.attach(path.stem, definition)
        if not instance.running:
            raise RuntimeError(instance.errors[-1].message)
        self.code.system_name = path.stem
        self.code.relations["owner"] = self.selected
        self.message(f"Attached {path.stem} to {self.selected.components.get('name', self.selected.id)}")

    def inspect_system(self):
        owner = self.code.relations.get("owner")
        name = self.code.components.get("system_name")
        if owner is None or name not in owner.systems:
            raise ValueError("Open an attached system first")
        self.open_panel(name, owner)

    def detach_system(self):
        owner = self.code.relations.get("owner")
        name = self.code.components.get("system_name")
        if owner is None or name not in owner.systems:
            raise ValueError("Open an attached system first")
        if owner is self.app and name == "editor":
            raise ValueError("The active editor cannot detach itself")
        del owner.systems[name]
        self.message(f"Detached {name}")

    def open_panel(self, system_name=None, target=None, component=None):
        target = target or self.selected
        n = len(self.extra_panels)
        view_type = "system" if system_name else "component" if component else "entity"
        panel = self.make(self.app, f"InspectionPanel{n}", "panel", text=view_type.upper()+" INSPECTION",
                          x=self.viewport.x+20+n*20, y=self.viewport.y+20+n*20, w=440, h=270,
                          layer=4, view_type=view_type, system_name=system_name, component=component)
        panel.relations["target"] = target
        close = self.button(panel, f"ClosePanel{n}", "X", panel.destroy)
        put(close, x=panel.x+400, y=panel.y+5, w=30, h=24, layer=6)
        for index in range(10):
            self.make(panel, f"Panel{n}Line{index}", "label", text="", x=panel.x+12,
                      y=panel.y+35+index*22, w=416, h=20, layer=5, line_index=index)
        self.extra_panels.append(panel)

    def panels_sync(self):
        self.extra_panels[:] = [panel for panel in self.extra_panels if panel.alive]
        for panel in self.extra_panels:
            target = panel.relations.get("target")
            if target is None:
                lines = ["Target no longer exists"]
            elif panel.view_type == "system":
                instance = target.systems.get(panel.system_name)
                if instance is None:
                    lines = ["System detached"]
                else:
                    lines = [f"{instance.name} | running={instance.running}", str(instance.definition.path),
                             "Lifecycle: " + ", ".join(instance.lifecycle)]
                    lines += [f"ERROR: {error.message}" for error in instance.errors]
                    lines += [f"{k}: {safe_repr(v)}" for k, v in instance.globals.items()]
            elif panel.view_type == "component":
                value = safe_repr(target.components.get(panel.component, "<removed>"))
                lines = [panel.component] + [value[i:i+50] for i in range(0, len(value), 50)]
            else:
                lines = [str(target.id), "Tags: " + ", ".join(target.tags)]
                lines += [f"{k}: {safe_repr(v)}" for k, v in target.components.items()]
                lines += [f"{k} -> {v.components.get('name', v.id)}" for k, v in target.relations.items()]
            for child in panel.children:
                if "line_index" in child.components:
                    index = child.line_index
                    put(child, text=lines[index] if index < len(lines) else "")


def build_editor(window, graphics, input_state, project="workspace"):
    runtime = build_demo(window, graphics, input_state)
    app = next(e for e in runtime.entities if e.components.get("name") == "Application")
    del app.systems["window"]
    editor = Editor(runtime, project)
    runtime.services["editor"] = editor
    app.systems.attach("editor", runtime.assets.system(editor.project / "editor.py"))
    return runtime
