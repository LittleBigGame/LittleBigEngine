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

The inspector discovers components, systems, tags, and relations automatically.
The inspector is organized into three collapsible sections:
- **COMPONENTS**: Shows each component name and value. Edit a value and press Enter to commit.
  Components can be renamed inline by editing the component name label and pressing Enter, or via
  the context menu. Use Python literals: `2.0`, `True`, `"text"`, `(255, 0, 0)`, `[1, 2]`, or `{"a": 1}`.
  Ctrl+A selects a field's current contents. Unsupported objects are shown read-only.
  To add data, click **+ Add** to choose from quick presets (`+ Transform / Pos (x, y)`, `+ Size (w, h)`,
  `+ Velocity (vx, vy)`, `+ Color (r, g, b)`, `+ Speed`) or `+ Custom Component...`.
  Scroll the inspector to reach more components.
- **SYSTEMS**: Displays all systems attached to the entity, their status, errors, and an **Edit** button.
  Click **+ Attach** to attach existing scripts or create a new system.
- **LINKS & HIERARCHY**:
  - The **Tags** field accepts comma-separated names.
  - The **Parent** field accepts a unique entity name or UUID; clearing it detaches the entity.
  - The **Link** field accepts `relation=Entity Name` or `relation=UUID`; an empty target unlinks it.
  - Lists existing relations with quick-navigation and **Edit** buttons.
  - Displays child entity navigation chips for instant selection.

Right-click any component label or value to open its context menu, allowing you to inspect,
rename, delete, change its Python type (`Change type...`), or add components. `Inspect in panel`
opens an independent view of the selected entity. Additional panels are ordinary entities.

## Systems and source

Select an entity and click a system name at the bottom of the inspector to open
its source. `Inspect system` shows the opened attachment's definition path,
lifecycle, running state, errors and public globals. `Detach system` removes that
attachment; the active editor attachment is protected from accidental detachment.

The source path is displayed in a read-only header field relative to the project directory.
Double-click the path field or right-click anywhere in the code editor and choose `Rename '<file>'...`
to safely rename the script on disk; the editor automatically updates all attached system instances
across entities, updates matching component references, and saves project state.

File operations (`Save / reload`, `Rename...`, `Open file...`, and `+ New system script...`) are
available from the code editor right-click context menu (and `Ctrl+S` to save). Attaching scripts
to entities is managed directly in the Inspector panel via **+ Attach**.

The source editor supports multiline typing, cursor movement, mouse selection,
double-click word selection, triple-click line selection, Shift selection, Home/End,
page and word navigation (Ctrl+Left/Right), word deletion (Ctrl+Backspace/Delete with line whitespace isolation),
delimiter-aware smart multiline call and tuple auto-indentation and closing bracket dedent, scrolling,
Ctrl+A/C/X/V, Ctrl+Z and Ctrl+Shift+Z. Ctrl+S saves. Repeating New or Open after an
unsaved-change warning discards the current edits; save first to retain them.
F5 (or the Run / Pause button in the header) toggles the game between running and paused,
pausing game entity updates while viewport rendering and the editor remain fully active.
Typing `.` (period) in the editor or text fields operates solely as text input and never runs the game.

Autocomplete displays contextual completions for live entities, components, and LBE APIs,
with a scrollable popup supporting arrow keys, PageUp/PageDown, and mouse wheel scrolling.
Resting the mouse over any code symbol displays a hover inspection tooltip showing its
signature, definition, and docstring via off-thread static code analysis.

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

## Context actions and stack inspection

Right-click a hierarchy row, viewport object, empty viewport area, editor panel,
or component field to open its available actions. Use the mouse or Up/Down and
Enter to choose; Escape or an outside click dismisses the menu. Long menus scroll
with the mouse wheel.

- **Unified Add Component**: Right-clicking in the Viewport, Hierarchy, or Inspector
  provides an identical `+ Add Component...` action that opens the component presets menu.
- **Component Context Menu**: Right-clicking any component provides `Inspect component`,
  `Rename '<comp>'...`, `Change type... (<current_type>)` (allowing interactive type conversion
  between float, int, str, bool, tuple, list, dict, and NoneType), and `Delete '<comp>'`.
  If the component's value is an `Entity`, the context menu automatically presents contextual
  entity sub-actions (`> Select Entity`, `Inspect Entity`, `Rename Entity`, `+ Add Component to Entity`,
  `Add child`, `Duplicate Entity`, `Delete Entity`).
- **Continuous Ctrl Stack Highlighting**: Holding `Ctrl` at any time continuously highlights the
  entity or UI control under the mouse and its entire ancestor stack in distinct hierarchy colors
  (Cyan for leaf, Emerald Green for parent, Amber for grandparent, Fuchsia, Coral).
  Right-clicking while holding `Ctrl` opens a deep inspection context menu containing color-coded
  selection options for every entity in the stack, along with editing actions for the leaf.

These actions are defined by the editor project's `app.py`, `hierarchy.py`, and `inspector.py`
using the reusable context-menu API described in `docs/ui.md`.

## Python-aware completion and selection

The desktop extra includes Jedi for static completion based on the current source,
project imports, inferred Python types and the attached owner's component names.
It analyzes source without running the edited script. Core-only installations stay
independent of Jedi; install `.[editor]` for analysis without the desktop backend.

- Type a member access (`value.`) or at least two identifier characters, then
  pause briefly for suggestions. Pasting and moving the caret do not open popups.
- Ctrl+Space explicitly requests completion. Comments and strings are excluded.
- Up/Down or PageUp/PageDown selects a suggestion; Tab or a mouse click accepts it.
  Enter always inserts a newline. Escape, selection, navigation or focus changes dismiss it.
- Autocomplete displays up to eight suggestions with a scrollable popup track.
- Resting the mouse over code displays a hover tooltip with signatures and docstrings.
- Left-drag selection remains captured by its text area until mouse release,
  including outside its bounds with auto-scrolling. Shift-click extends the existing selection.
  Newline and empty-line selections have a visible highlight. Scrolling no longer
  jumps back to the caret unless the caret or text changes.

Existing project scripts are never overwritten automatically. To adopt these
changes in an existing project, compare its `code_editor.py` and `app.py` against
`src/lbe/templates/editor/` and port the coding system plus the `source_path` and
`completion_components` assignments in `app.py`'s update function. A new editor
project receives the updated scripts automatically.

## Safe project and template updates

New projects record template provenance. To adopt engine-supplied script updates,
run `python -m lbe --project path/to/project --template editor --upgrade-template`.
Only unchanged managed files are updated. Customized files remain yours; compare
and port their changes manually. Backups are retained under `.lbe-template-backups`.
Existing projects without provenance require manual comparison; the engine never
assumes their scripts are disposable copies.

Project entities retain persistence ownership when reparented; popup UI entities
are excluded. File and folder moves preserve registered UUIDs and attached script
instances, including their ordering. They do not rewrite arbitrary component
strings that happen to match a file name. A deleted asset remains a missing UUID
reference rather than silently becoming another asset.

The current Duplicate Entity action copies component containers and tags only;
it does not duplicate children, system instances, or relation edges. Entity-valued
components keep references to the existing target entities.

Dockable panels remain work in progress. Custom dock trees retain their own split
ratios; the default layout still supports the existing scalar split controls during
migration. Completing panel drag/drop is separate from project stabilization.

## System activity log

Open **View → System Log** or press **Ctrl+L**. The panel is an ordinary editor
entity with a `system_log` attachment and inspectable child controls. Drag its
header to move it; drag the lower-right handle to resize it.

The log records entity/component/tag/relation/hierarchy changes, system lifecycle
entry points, named events, UI actions and failures. Select a row to inspect its
target, responsible system/phase and details, including bounded before/after
value snapshots. Arbitrary objects use safe type descriptions; `touch()` cannot
recover an unknown prior in-place value. Direct internal Python mutations and
arbitrary Python function calls are not automatically intercepted.

Game activity and errors are shown by default, including editor and log-panel system failures. **Editor** enables routine editor activity capture;
**Calls** includes noisy per-frame update/draw entries. Filter by kind, target,
source or value; use the wheel to review history. **Pause** stops capture without
pausing the game, **Clear** clears retained records, and **X** hides the panel.
The buffer retains at most 2,000 entries and does not persist session logs.

Application scripts receive the reusable `log` service and can report custom
operations with `log.write("info", "loading level")`. It captures the current
system source automatically. Runtime changes also expose immutable `old`, `new`
and `source` metadata; event observers can use `events.observe(callback)`.
These are generic runtime observations, while panel presentation and filtering
policy live in the editor project scripts.
