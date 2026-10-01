# UI and Application Scripting

The engine loads a project directory's `app.py` as a normal script attachment on
an Application entity. The file uses the same public API as any other system.
It receives platform services such as `window`, `graphics`, `input`, `space` and
the project directory `project`, alongside `entity`, `create`, `query` and `assets`.

## A small application

Place this in a new project's `app.py`:

```python
from lbe.ui import UI, stack

ui = UI(entity, window, graphics, input)
panel = ui.create(entity, "Panel", "panel", x=20, y=20, w=400, h=300)
label = ui.create(panel, "Greeting", "label", text="Hello", w=340, h=28)
notes = ui.multiline(panel, "Notes", w=340, h=150)

def greet():
    label.text = "Hello from an ordinary button entity"

button = ui.button(panel, "Greet", "Greet", greet, w=160, h=30)

def start():
    ui.install()

def update(dt):
    stack(panel, (label, button, notes), padding=32)
```

Run `python -m lbe --project path/to/project`. An existing `app.py` is loaded
directly; no editor panels or game objects are created by the loader.

## Controls and state

`create`, `button`, `field` and `multiline` return normal entities. Their components
hold bounds, text, buffers, colors, visibility and callbacks. You can construct
equivalent entities yourself: no required widget classes exist.

- `x`, `y`, `w`, `h` use screen coordinates with a top-left origin.
- `layer` controls drawing and hit-test priority.
- `visible=False` hides a control and its descendants and blocks their input.
- `modal=True` prevents a hit on that surface from reaching underlying controls.
- `buffer` is a `TextBuffer` for single-line or multiline editing.
- `action()` handles a button activation; `on_commit()` applies a field on Enter.
- `on_click(control, event)` and `on_scroll(control, event)` add custom behavior.
  Return `False` to continue default handling.
- The UI root's `on_key(event)` may consume shortcuts by returning `True`.
- `on_ui_error(message)` receives callback errors; `ui_error` records the latest.

`ui.focus(control)` sets focus through a relation on the UI root. `ui.focus()`
clears it. `ui.controls()` queries descendants of that root, so separate UI roots
do not share a widget registry or focus state.

`put(entity, **values)` applies changed scalar/control properties without redundant notifications.

## Layout system

LBE provides pure entity layout helpers that operate without introducing transform inheritance:
- `parse_box(value)`: Normalizes padding or margins into `(top, right, bottom, left)` integers.
- `content_rect(entity)`: Calculates `(x, y, w, h)` available inside padding.
- `stack(parent, children=None, axis="y", gap=8, padding=None, align=None)`: Positions ordinary entities
  along `x` or `y`, supporting margins, `flex` distribution for remaining space, and alignments
  (`"start"`, `"center"`, `"end"`, `"stretch"`).
- `row(parent, ...)` and `column(parent, ...)`: Convenience wrappers for horizontal and vertical stacks.
- `dock(parent, children=None, padding=None)`: Arranges children against edges (`"top"`, `"bottom"`,
  `"left"`, `"right"`, `"fill"`, or `"float"`/`"none"`).
- `apply_layout(entity, recursive=False)`: Evaluates layout rules from an entity's `layout` component.
- `Layout`: Attached entity system that automatically evaluates layout rules on update.
- `ui.splitter(parent, name, axis="x", thickness=6, on_drag=...)`: Interactive draggable divider control.

Holding `Ctrl` displays continuous entity hierarchy overlays via the root's `highlight_provider(mx, my)` callback,
highlighting the hover target and each ancestor in distinct colors (`STACK_COLORS`).

## Systems and composition

`ui.install()` attaches a generic input/render system. Pass a compiled definition
with `ui.install(definition=assets.system(project / "ui.py"))` to use a project-owned
system source. The standard source calls `entity.components["ui"].process()` during
update and `.draw()` during drawing.

Multiline controls generate their own line, gutter, selection, cursor and scrollbar
entities. They do not know about source files, compilers or script attachment. The
editor application adds those policies by composing controls and public runtime
operations. The counter template uses the same text control for notes.

For custom interaction, compose components and callbacks or attach another normal
system. Game selection, tree expansion, property inspection and saving Python
files are application-level behavior, not built-in UI control rules.
# Context menus

Right-click menus use ordinary UI entities. Register a `context_actions(target)`
callback on the UI root or a target entity; both providers contribute actions.
The optional root `context_target(control, event)` callback resolves a clicked
control into an entity or any custom object. Providers are queried each time the
menu opens, so actions can depend on current components or capabilities.

```python
from lbe.menus import open_menu

root.context_actions = lambda target: [
    {"label": "Inspect", "run": inspect_target},
    None,  # separator
    {"label": "Run", "run": run_target, "enabled": can_run(target)},
]
open_menu(ui, custom_target, x=200, y=100)
```

Each `run` callback receives the target. Pass `actions=[...]` to `open_menu` to
provide a one-off menu instead of querying providers. No Core changes or entity
subclasses are required. Menu panels and rows are inspectable entities; layout,
selection, scrolling and action data live in their components.

Click an enabled item or use Up/Down and Enter. Escape or an outside click closes
the menu without activating controls underneath it. The wheel scrolls long
menus. Disabled items cannot execute. Text focus is retained while popup input
is captured. Callback errors use the UI's existing error reporting path.

`Layout(entity).install()` attaches layout through the ordinary script-system API;
`Layout(entity).update(dt)` remains available for direct application scheduling.
`lbe.ui.bind_callbacks(system, owner, callbacks)` registers lifecycle-owned handlers;
call the returned release function in `stop()` to remove them. Panel scripts should
retain their application state when initialized rather than rediscovering it from
an assumed parent after a dock/reparent operation.

Inline UUID reference pills are opt-in: set `inline_references=True` on a code
text area. Only actual `asset(...)`, `resolve(...)`, and `assets[...]` expressions
are recognized; comments, string contents, and ordinary text fields remain text.
