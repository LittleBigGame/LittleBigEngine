"""Source editing and managed project-file operations, independently attachable."""
import os
from pathlib import Path
import tempfile
from lbe.ui import INK
from lbe.text import TextBuffer
from lbe.menus import open_menu
from lbe.ui import bind_callbacks

state = entity.inherit("application_state")

def inspector_sync(*args, **kwargs):
    return state.inspector_sync(*args, **kwargs)

def message(*args, **kwargs):
    return state.message(*args, **kwargs)

def save_editor_project(*args, **kwargs):
    return state.save_editor_project(*args, **kwargs)

def selected(*args, **kwargs):
    return state.selected(*args, **kwargs)

def source_path():
    name = state.path_field.buffer.text.strip()
    path = (state.project / name).resolve()
    if not name or path.suffix != '.py' or (not path.is_relative_to(state.project)):
        raise ValueError('Use a .py path inside the project folder')
    return path

def new_source():
    if not confirm_discard('new'):
        return
    state.path_field.buffer = TextBuffer('new_system.py')
    state.code.buffer = TextBuffer('def update(dt):\n    pass\n')
    state._saved_source = (state.path_field.buffer.text, state.code.buffer.text)
    state.code.components.pop('system_name', None)
    state.code.relations.pop('owner', None)
    message('New source: right-click to Rename file... or Save / reload')

def open_path():
    path = source_path()
    if not path.exists():
        message(f"File not found: {path.name}")
        return
    text = path.read_text(encoding='utf-8')
    if not confirm_discard('open'):
        return
    state.code.buffer = TextBuffer(text)
    state._saved_source = (state.path_field.buffer.text, text)
    state.code.source_path = str(path)
    state.code.components['system_name'] = path.stem
    sel = selected()
    if sel and path.stem in sel.systems:
        state.code.relations['owner'] = sel
    else:
        state.code.relations.pop('owner', None)
    message(f'Opened {path.name}')

def open_specific_file(path):
    path = Path(path).resolve()
    if not path.exists():
        message(f"File not found: {path.name}")
        return
    if not confirm_discard('open'):
        return
    text = path.read_text(encoding='utf-8')
    rel_name = str(path.relative_to(state.project)) if path.is_relative_to(state.project) else path.name
    state.path_field.buffer = TextBuffer(rel_name)
    state.code.buffer = TextBuffer(text)
    state._saved_source = (rel_name, text)
    state.code.source_path = str(path)
    state.code.components['system_name'] = path.stem
    sel = selected()
    if sel and path.stem in sel.systems:
        state.code.relations['owner'] = sel
    else:
        state.code.relations.pop('owner', None)
    state.reveal_file(path)
    message(f"Opened {rel_name}")
    return True

def open_file_menu(x=None, y=None):
    candidates = []
    if state.project and state.project.exists():
        for p in sorted(state.project.rglob("*.py")):
            candidates.append(p)
    actions = []
    cur_text = state.path_field.buffer.text.strip()
    for p in candidates:
        rel = str(p.relative_to(state.project)) if p.is_relative_to(state.project) else p.name
        is_cur = (rel == cur_text or p.name == cur_text)
        label = f"• {rel}" if is_cur else f"  {rel}"
        actions.append(dict(label=label, run=lambda _, path=p: open_specific_file(path)))
    if not actions:
        actions.append(dict(label="(No .py files in project)", run=None))
    if x is None or y is None:
        mouse = getattr(state.ui, "mouse_pos", None)
        if mouse:
            x, y = mouse
        else:
            x, y = state.path_field.x, state.path_field.y + state.path_field.h + 2
    open_menu(state.ui, state.code_panel, x, y, actions=actions)

def on_path_field_click(control, event):
    if len(event) > 3 and event[3] in (2, 4):
        return False
    click_count = event[5] if len(event) >= 6 else 1
    if click_count >= 2:
        prompt_rename_file()
        return True
    return False

def show_source_panel():
    if not state.dock_tree.find_tab_group_with_panel('code_panel'):
        state.toggle_panel_view('code_panel')
    group = state.dock_tree.find_tab_group_with_panel('code_panel')
    group.active = group.panels.index('code_panel')
    state.layout()


def prompt_rename_file():
    show_source_panel()
    state.path_field.components["readonly"] = False
    state.path_field.components["ink"] = INK
    state.ui.focus(state.path_field)
    state.path_field.buffer.anchor = 0
    state.path_field.buffer.cursor = len(state.path_field.buffer.text)
    state.path_field.on_commit = commit_rename_file
    message(f"Type new name for '{state.path_field.buffer.text}' and press Enter (Esc to cancel)")

def commit_rename_file():
    new_name = state.path_field.buffer.text.strip()
    state.path_field.components["readonly"] = True
    state.path_field.components["ink"] = (160, 180, 205)
    state.path_field.on_commit = None
    old_text = state._saved_source[0] if state._saved_source else state.path_field.buffer.text
    if not new_name or new_name == old_text:
        state.path_field.buffer = TextBuffer(old_text)
        return
    try:
        rename_file(new_name, old_name=old_text)
    except Exception as e:
        message(f"Rename failed: {e}")
        state.path_field.buffer = TextBuffer(old_text)

def rename_file(new_name, old_name=None):
    new_name = new_name.strip()
    if not new_name.endswith('.py'):
        new_name += '.py'
    old_path = source_path() if old_name is None else (state.project / old_name).resolve()
    destination = (state.project / new_name).resolve()
    if not destination.is_relative_to(state.project):
        raise ValueError('Rename destination must be inside the project folder')
    if old_path.exists():
        state.files.relocate(old_path, destination, save=save_editor_project)
    else:
        if destination.exists():
            raise FileExistsError(destination)
        # Naming a new unsaved buffer does not claim its contents were written.
    update_open_source_location(old_path, destination)
    inspector_sync()
    message(f"Renamed {old_path.name} to {destination.name}")
    return destination

def update_open_source_location(source, destination):
    open_path = Path(state.code.components.get("source_path", source_path())).resolve()
    if open_path == source or open_path.is_relative_to(source):
        new_path = destination / open_path.relative_to(source) if open_path != source else destination
        relative = new_path.relative_to(state.project).as_posix()
        state.path_field.buffer = TextBuffer(relative)
        if state._saved_source:
            state._saved_source = (relative, state._saved_source[1])
        state.code.source_path = str(new_path)
        if state.code.components.get("system_name") == open_path.stem:
            state.code.system_name = new_path.stem

def open_system(owner, name):
    if not confirm_discard((owner.id, name)):
        return
    instance = owner.systems[name]
    path = Path(instance.definition.path)
    if path.is_relative_to(state.project):
        state.path_field.buffer = TextBuffer(str(path.relative_to(state.project)))
    else:
        state.path_field.buffer = TextBuffer(f'{name}.py')
    state.code.buffer = TextBuffer(instance.definition.source)
    state._saved_source = (state.path_field.buffer.text, state.code.buffer.text)
    state.code.system_name = name
    state.code.relations['owner'] = owner
    if getattr(state, 'ready', False) and path.is_relative_to(state.project):
        state.reveal_file(path)
    message(f"{name} | {('running' if instance.running else 'stopped')} | {', '.join(instance.lifecycle)}")

def confirm_discard(action):
    dirty = state._saved_source is not None and state._saved_source[1] != state.code.buffer.text
    if dirty and state._pending_discard != (action, state.code.buffer.text):
        state._pending_discard = (action, state.code.buffer.text)
        message('Unsaved source. Save first, or repeat the action to discard edits.')
        return False
    state._pending_discard = None
    return True

def save():
    path = source_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=path.parent, delete=False, suffix='.tmp') as stream:
        stream.write(state.code.buffer.text)
        temporary = Path(stream.name)
    temporary.replace(path)
    state._saved_source = (state.path_field.buffer.text, state.code.buffer.text)
    definition = state.runtime.assets.system(path)
    count = 0
    for entity in state.runtime.entities:
        for name, instance in tuple(entity.systems.items()):
            if Path(instance.definition.path) == path:
                updated = entity.systems.reload(name, definition)
                if updated.definition is not definition or not updated.running:
                    raise RuntimeError(f"{name}: {(updated.errors[-1].message if updated.errors else 'reload failed')}")
                count += 1
    save_editor_project()
    message(f'Saved {path.name}; reloaded {count} attachment(s)')

def attach():
    save()
    path = source_path()
    definition = state.runtime.assets.system(path)
    if path.stem in selected().systems:
        instance = selected().systems.reload(path.stem, definition)
    else:
        instance = selected().systems.attach(path.stem, definition)
    if not instance.running:
        raise RuntimeError(instance.errors[-1].message)
    state.code.system_name = path.stem
    state.code.relations['owner'] = selected()
    save_editor_project()
    message(f"Attached {path.stem} to {selected().components.get('name', selected().id)}")

def refresh_project_files():
    reg = getattr(state.runtime.assets, "registry", None)
    if reg:
        reg.scan(state.project)
    state.file_tree_key = None
    if hasattr(state, "file_explorer_sync"):
        state.file_explorer_sync()
    message("Refreshed project files")

def new_source_in_dir(folder_path):
    if not confirm_discard(("new", str(folder_path))):
        return
    f_path = Path(folder_path).resolve()
    if not f_path.is_relative_to(state.project) or not f_path.is_dir():
        raise ValueError('Choose an existing folder inside the project')
    rel_folder = f_path.relative_to(state.project) if f_path.is_relative_to(state.project) else f_path.name
    i = 1
    while (f_path / f"system_{i}.py").exists():
        i += 1
    new_name = str(rel_folder / f"system_{i}.py").replace("\\", "/")
    state.path_field.buffer = TextBuffer(new_name)
    state.code.buffer = TextBuffer("def update(dt):\n    pass\n")
    state._saved_source = (new_name, state.code.buffer.text)
    state.code.source_path = str(state.project / new_name)
    state.code.components["system_name"] = f"system_{i}"
    state.code.relations.pop('owner', None)
    save()
    state.reveal_file(f_path / f"system_{i}.py")
    show_source_panel()
    refresh_project_files()
    message(f"Created {new_name}")

def prompt_rename_file_item(item):
    if item["type"] == "system":
        if not open_specific_file(item["path"]):
            return
        prompt_rename_file()
    else:
        path = Path(item['path']).resolve()
        original = state.path_field.buffer.text
        state.path_field.buffer = TextBuffer(path.name)
        prompt_rename_file()

        def commit():
            name = state.path_field.buffer.text.strip()
            state.path_field.buffer = TextBuffer(original)
            state.path_field.readonly = True
            state.path_field.on_commit = None
            if not name or Path(name).name != name or name in ('.', '..'):
                raise ValueError('Enter a file or folder name without a directory')
            destination = path.with_name(name)
            state.files.relocate(path, destination, save=save_editor_project)
            update_open_source_location(path, destination)
            refresh_project_files()
            message(f"Renamed '{path.name}' to '{name}'")

        state.path_field.on_commit = commit

def delete_file_item(item):
    path = Path(item["path"]).resolve()
    open_path = Path(state.code.components.get("source_path", source_path())).resolve()
    is_open = open_path == path or open_path.is_relative_to(path)
    if is_open and not confirm_discard(('delete', str(path))):
        return
    state.files.delete(path, save=save_editor_project)
    if is_open:
        state.path_field.buffer = TextBuffer('new_system.py')
        state.code.buffer = TextBuffer('def update(dt):\n    pass\n')
        state.code.source_path = str(state.project / 'new_system.py')
        state._saved_source = None
        state.code.components.pop('system_name', None)
        state.code.relations.pop('owner', None)
    refresh_project_files()
    message(f"Deleted '{path.name}'; references remain recoverable")

def create_new_folder(parent_dir=None):
    pdir = Path(parent_dir).resolve() if parent_dir else (state.project / state.file_explorer.components.get('view_root','systems/game')).resolve()
    if not pdir.is_relative_to(state.project) or not pdir.is_dir():
        raise ValueError('Choose an existing folder inside the project')
    base_name = "New Folder"
    candidate = pdir / base_name
    idx = 1
    while candidate.exists():
        candidate = pdir / f"{base_name} ({idx})"
        idx += 1
    try:
        candidate.mkdir()
        state.reveal_file(candidate)
        refresh_project_files()
        message(f"Created folder '{candidate.name}'")
    except Exception as e:
        message(f"Failed to create folder: {e}")

def move_file_or_folder(src_path, dst_folder):
    source = Path(src_path).resolve()
    destination = Path(dst_folder).resolve() / source.name
    state.files.relocate(source, destination, save=save_editor_project)
    update_open_source_location(source, destination)
    refresh_project_files()
    message(f"Moved '{source.name}' to '{destination.parent.name}'")

def open_move_file_menu(src_path):
    pdir = Path(state.project).resolve()
    dirs = [pdir]
    for root, dirnames, _ in os.walk(pdir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("__pycache__", "venv", ".venv")]
        for d in dirnames:
            dirs.append(Path(root) / d)

    actions = []
    for d in sorted(dirs, key=lambda p: str(p).lower()):
        rel = "." if d == pdir else str(d.relative_to(pdir)).replace("\\", "/")
        label = f"📁 /{rel}" if rel != "." else "📁 / (Project root)"
        actions.append(dict(
            label=label,
            run=lambda _, target_dir=d: move_file_or_folder(src_path, target_dir)
        ))
    mouse = getattr(state.ui, "mouse_pos", None)
    x, y = mouse if mouse else (200, 200)
    open_menu(state.ui, state.file_explorer, x, y, actions=actions)


def start():
    global release
    release = bind_callbacks(system, state, {'source_path':source_path,'new_source':new_source,'open_path':open_path,'open_specific_file':open_specific_file,'open_file_menu':open_file_menu,'on_path_field_click':on_path_field_click,'prompt_rename_file':prompt_rename_file,'commit_rename_file':commit_rename_file,'rename_file':rename_file,'update_open_source_location':update_open_source_location,'open_system':open_system,'confirm_discard':confirm_discard,'save':save,'attach':attach,'refresh_project_files':refresh_project_files,'new_source_in_dir':new_source_in_dir,'prompt_rename_file_item':prompt_rename_file_item,'delete_file_item':delete_file_item,'create_new_folder':create_new_folder,'move_file_or_folder':move_file_or_folder,'open_move_file_menu':open_move_file_menu})


def stop():
    if "release" in globals():
        release()
