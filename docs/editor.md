# LittleBigEngine Editor

Launch with `python -m lbe` after installing `.[desktop]`.

## Workspace

The hierarchy is at the upper left, the inspector below it, the world viewport
at the upper right and the system source editor below the viewport. Editor panels
and their controls appear in the same hierarchy as Game and its entities.

Click a hierarchy row to select it. Click its `+` or `-` to expand or collapse it.
Scroll the hierarchy to reach additional entities. Clicking a rectangle in the
viewport selects that entity. Scroll the viewport to change camera zoom.

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

- System source files persist. Entity edits, attachments and panel layout currently
  reset on relaunch; project serialization is not implemented yet.
- The source editor is intentionally small: no syntax coloring, completion, search
  or full Unicode grapheme layout yet.
- Native nested Python containers use the core's explicit edit/touch mechanism.
- Scripts execute trusted Python. Deliberately breaking the editor's own runtime
  script can interrupt its UI; restore `editor.py` externally if necessary.
- Inspection panels show a compact view; larger structured objects may be truncated.
