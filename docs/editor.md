# LittleBigEngine Editor

Launch with `python -m lbe` after installing `.[desktop]`.

On first launch, a project is initialized from the editor template. `app.py` is
the editor application; `ui.py` attaches general UI behavior, and `render.py` draws
the game entities. These are ordinary editable system sources. Existing project
files are not overwritten by later launches.

## Workspace

The hierarchy is at the upper left, the inspector below it, the world viewport
at the upper right and the system source editor below the viewport. Editor panels
and their controls appear in the same hierarchy as Game and its entities.

Click a hierarchy row to select it. Click its `+` or `-` to expand or collapse it.
Scroll the hierarchy to reach additional entities. Clicking a rectangle in the
viewport selects that entity. Drag inside the viewport to pan the camera, and
scroll the viewport to zoom towards the cursor.

## Live data

The inspector discovers components automatically. Edit a value and press Enter.
Use Python literals: `2.0`, `True`, `"text"`, `(255, 0, 0)`, `[1, 2]`, or `{"a": 1}`.
Ctrl+A selects a field's current contents. Unsupported objects are shown read-only.
Scroll the inspector to reach more components.

To add data, fill the component-name and value fields, then click `+`.
The Tags field accepts comma-separated names. Parent accepts a unique entity name
or UUID; clearing it detaches the entity. Link accepts `relation=Entity Name` or
`relation=UUID`; an empty target removes that relation. Press Enter to apply.

Right-click an editable component field to open a component view. `Inspect in panel`
opens another view of the selected entity. Additional panels are ordinary entities.

## Systems and source

Select an entity and click a system name at the bottom of the inspector to open
its source. `Inspect system` shows the opened attachment's definition path,
lifecycle, running state, errors and public globals. `Detach system` removes that
attachment; the active editor attachment is protected from accidental detachment.

The source path is relative to the selected project directory. `Open` reads that
file, and `New` starts a small blank system. `Save / reload` writes the file and
reloads matching attachments. `Attach` saves and attaches the current file to the
selected entity, using the filename without `.py` as the instance name.

The source editor supports multiline typing, cursor movement, mouse selection,
Shift selection, Home/End, page and word navigation, indentation, scrolling,
Ctrl+A/C/X/V, Ctrl+Z and Ctrl+Shift+Z. Ctrl+S saves. Repeating New or Open after an
unsaved-change warning discards the current edits; save first to retain them.
F5 (or the Run / Pause button in the header) toggles the game between running and paused,
pausing game entity updates while viewport rendering and the editor remain fully active.
Typing `.` (period) in the editor or text fields operates solely as text input and never runs the game.

Syntax errors leave existing attachments running and appear in the status bar.
A game script's runtime error stops that attachment while the editor continues.
Fix its source and save to reload. Runtime diagnostics are also visible in the
system inspection panel.

## Extend behavior from the editor

1. Select Entity A. Add `vx` with value `2.0`, then `vy` with value `1.0`.
2. Click New. Change the source path to `physics.py`.
3. Replace the source with:

   ```python
   def update(dt):
       for child in query("x", "y", "vx", "vy"):
           child.x += child.vx * dt
           child.y += child.vy * dt
   ```

4. Save, select Game, then click Attach.
5. Entity A moves; Entity B stays fixed because it lacks the new components.

The behavior comes from this script. There is no physics-specific code in the kernel.

## Current boundaries

- System source files, entity component edits, hierarchy changes, system attachments
  and panel layout persist across relaunches in versioned project serialization format (`project.json`).
- The source editor supports Python syntax coloring and completion, but not search
  or full Unicode grapheme layout yet.
- Native nested Python containers use the core's explicit edit/touch mechanism.
- Scripts execute trusted Python. Deliberately breaking the editor's own runtime
  script can interrupt its UI; restore `app.py` externally if necessary.
- Inspection panels show a compact view; larger structured objects may be truncated.

## Context actions

Right-click a hierarchy row, viewport object, empty viewport area, editor panel,
or component field to open its available actions. Use the mouse or Up/Down and
Enter to choose; Escape or an outside click dismisses the menu. Long menus scroll
with the mouse wheel. Component fields offer inspection; entity menus offer
selection, inspection and component creation. Game entities also offer child
creation and camera focus when they have position data.

These actions are defined by the editor project's `app.py` using the reusable
context-menu API described in `docs/ui.md`. Existing projects retain their own
scripts: the updated editor menu bindings are included in newly initialized
editor projects; upgrading an existing custom editor requires porting those
bindings into its `app.py`.

## Python-aware completion and selection

The desktop extra includes Jedi for static completion based on the current source,
project imports, inferred Python types and the attached owner's component names.
It analyzes source without running the edited script. Core-only installations stay
independent of Jedi; install `.[editor]` for analysis without the desktop backend.

- Type a member access (`value.`) or at least three identifier characters, then
  pause briefly for suggestions. Pasting and moving the caret do not open popups.
- Ctrl+Space explicitly requests completion. Comments and strings are excluded.
- Up/Down selects a suggestion; Tab or a mouse click accepts it. Enter always
  inserts a newline. Escape, selection, navigation or focus changes dismiss it.
- Analysis runs in a background worker. Results for old text or cursor positions
  are discarded. Only six suggestions are shown; arbitrary dynamic Python values
  may not be inferable. This is completion, not a full type checker.
- Left-drag selection remains captured by its text area until mouse release,
  including outside its bounds. Shift-click extends the existing selection.
  Newline and empty-line selections have a visible highlight. Scrolling no longer
  jumps back to the caret unless the caret or text changes.

Existing project scripts are never overwritten automatically. To adopt these
changes in an existing project, compare its `code_editor.py` and `app.py` against
`src/lbe/templates/editor/` and port the coding system plus the `source_path` and
`completion_components` assignments in `app.py`'s update function. A new editor
project receives the updated scripts automatically.
