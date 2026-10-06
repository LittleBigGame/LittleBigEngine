"""Built-in in-engine Project Manager GUI system for LittleBigEngine kernel."""

import os
from pathlib import Path
import shutil
import sys

from .core import Runtime
from .project import template_path
from .systems import SystemDefinition
from .ui import UI, stack, put


def get_system_drives():
    if sys.platform == "win32":
        import string
        return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
    return ["/"]


def create_launcher_runtime(window, graphics, input_state, on_select_project):
    """Create full-window Project Manager GUI runtime with 1-Step Open and 2-Step Project Creation."""
    runtime = Runtime()
    runtime.services.update(window=window, graphics=graphics, input=input_state)

    root = runtime.create(name="ProjectManager", tags=["root"])
    ui = UI(root, window, graphics, input_state)
    ui.install()

    # Full window container
    container = ui.create(root, "Container", "panel", x=0, y=0, w=window.width, h=window.height, color=(17, 23, 31))

    title = ui.create(container, "Title", "label", text="LittleBigEngine - Project Manager (LBE v1)", size=16, w=1100, h=26, color=(69, 182, 199, 255))
    subtitle = ui.create(container, "Subtitle", "label", text="UUID item kernel | Typed references | Inherited components", size=10, w=1100, h=18, color=(145, 163, 183, 255))

    # Browser state (Default starting dir from user state or Documents)
    from .user_state import get_last_directory
    start_dir = get_last_directory()

    state = type("BrowserState", (), {})()
    state.current_dir = start_dir.resolve()
    state.page = 0
    state.items_per_page = 10
    state.last_dir = None
    state.last_page = -1
    state.mode = "browse"  # "browse" or "pick_template"
    state.target_project_path = None
    root.components["browser_state"] = state

    # --- TOP TOOLBAR ---
    # Row 1: Address Bar & Navigation
    path_row = ui.create(container, "PathRow", "panel", w=1100, h=32, color=(25, 34, 45))
    path_lbl = ui.create(path_row, "PathLbl", "label", text="Location:", size=10, w=70, h=26, color=(145, 163, 183, 255))
    path_field = ui.field(path_row, "PathField", text=str(state.current_dir), w=700, h=32)

    from .user_state import save_last_directory

    def do_navigate_path():
        target_str = path_field.buffer.text.strip()
        if target_str:
            p = Path(target_str).resolve()
            if p.exists() and p.is_dir():
                state.current_dir = p
                state.page = 0
                save_last_directory(state.current_dir)
            else:
                status_lbl.text = f"Invalid directory path: {target_str}"
                status_lbl.color = (248, 81, 73, 255)

    path_field.on_commit = do_navigate_path
    btn_go = ui.button(path_row, "BtnGo", "Go", do_navigate_path, w=45, h=30)

    def do_navigate_up():
        if state.current_dir.parent != state.current_dir:
            state.current_dir = state.current_dir.parent.resolve()
            state.page = 0
            save_last_directory(state.current_dir)

    btn_up = ui.button(path_row, "BtnUp", "⯅ Up", do_navigate_up, w=65, h=30)

    def do_refresh():
        state.last_dir = None  # Force re-scan

    btn_refresh = ui.button(path_row, "BtnRefresh", "🔄 Refresh", do_refresh, w=90, h=30)

    # Row 2: Action / Drive Toolbar
    action_row = ui.create(container, "ActionRow", "panel", w=1100, h=32, color=(25, 34, 45))
    
    drive_buttons = []
    for d in get_system_drives():
        def make_drive_handler(drive_path=d):
            def handler():
                state.current_dir = Path(drive_path).resolve()
                state.page = 0
                save_last_directory(state.current_dir)
            return handler
        d_btn = ui.button(action_row, f"Drive_{d}", d, make_drive_handler(d), w=45, h=28, color=(38, 55, 75))
        drive_buttons.append(d_btn)

    name_lbl = ui.create(action_row, "NameLbl", "label", text="New Project:", size=10, w=90, h=26, color=(145, 163, 183, 255))
    
    # Generate an initial unique default name
    def get_unused_name(base_dir, base="my_project"):
        cand = base
        cand_lbe = cand if cand.endswith(".lbe") else (cand + ".lbe")
        if not (base_dir / cand_lbe).exists() or not any((base_dir / cand_lbe).iterdir()):
            return cand
        clean = base[:-4] if base.endswith(".lbe") else base
        idx = 1
        while (base_dir / f"{clean}_{idx}.lbe").exists() and any((base_dir / f"{clean}_{idx}.lbe").iterdir()):
            idx += 1
        return f"{clean}_{idx}"

    name_field = ui.field(action_row, "NameField", text=get_unused_name(state.current_dir, "my_project"), w=160, h=28)

    status_lbl = ui.create(container, "StatusLbl", "label", text="", size=10, w=1100, h=18, color=(248, 81, 73, 255))

    def do_initiate_new_project():
        name_str = name_field.buffer.text.strip()
        if not name_str:
            status_lbl.text = "Error: Please specify a project name in the input box"
            status_lbl.color = (248, 81, 73, 255)
            return
        folder_name = name_str if name_str.endswith(".lbe") else (name_str + ".lbe")
        target_dir = state.current_dir / folder_name
        if target_dir.exists() and any(target_dir.iterdir()):
            name_str = get_unused_name(state.current_dir, name_str)
            folder_name = name_str if name_str.endswith(".lbe") else (name_str + ".lbe")
            target_dir = state.current_dir / folder_name
            ui.set_text(name_field, name_str)
        
        save_last_directory(state.current_dir)
        state.target_project_path = target_dir
        state.mode = "pick_template"
        try:
            state.current_dir = template_path("editor").parent.resolve()
        except Exception:
            state.current_dir = Path.home().resolve()
        state.page = 0
        state.last_dir = None

    btn_create_proj = ui.button(action_row, "BtnCreate", "+ New Project (.lbe)", do_initiate_new_project, w=170, h=28, color=(38, 75, 95))

    def do_create_folder():
        fname = name_field.buffer.text.strip()
        if not fname:
            status_lbl.text = "Error: Enter a folder name in Name field"
            status_lbl.color = (248, 81, 73, 255)
            return
        target_dir = state.current_dir / fname
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            status_lbl.text = f"Folder created: {fname}"
            status_lbl.color = (52, 211, 153, 255)
            state.last_dir = None
        except Exception as err:
            status_lbl.text = f"Create folder error: {err}"
            status_lbl.color = (248, 81, 73, 255)

    btn_create_folder = ui.button(action_row, "BtnFolder", "+ New Folder", do_create_folder, w=110, h=28, color=(45, 65, 85))

    # Step 2 specific buttons (Default template & Cancel)
    def do_use_default_editor():
        if state.target_project_path:
            save_last_directory(state.target_project_path.parent)
            on_select_project(state.target_project_path, template=template_path("editor"))

    btn_use_default_editor = ui.button(action_row, "BtnDefaultEditor", "🚀 Copy Default LBE v1 Editor", do_use_default_editor, w=240, h=28, color=(38, 95, 85))

    def do_cancel_template_picker():
        state.mode = "browse"
        target = state.target_project_path.parent if state.target_project_path else start_dir
        state.target_project_path = None
        state.current_dir = target.resolve()
        state.page = 0
        state.last_dir = None
        save_last_directory(state.current_dir)
        status_lbl.text = "Project creation cancelled"
        status_lbl.color = (145, 163, 183, 255)

    btn_cancel_picker = ui.button(action_row, "BtnCancelPicker", "◄ Cancel", do_cancel_template_picker, w=90, h=28, color=(65, 40, 45))

    # --- FILE LIST AREA ---
    items_container = ui.create(container, "ItemsContainer", "panel", w=1100, h=450, color=(20, 27, 36))

    # --- BOTTOM PAGINATION BAR ---
    page_row = ui.create(container, "PageRow", "panel", w=1100, h=34, color=(25, 34, 45))
    page_lbl = ui.create(page_row, "PageLbl", "label", text="Page 1 of 1", size=10, w=350, h=26, color=(145, 163, 183, 255))
    
    def prev_page():
        if state.page > 0:
            state.page -= 1

    def next_page():
        state.page += 1

    btn_prev = ui.button(page_row, "BtnPrev", "◄ Prev", prev_page, w=75, h=28)
    btn_next = ui.button(page_row, "BtnNext", "Next ►", next_page, w=75, h=28)

    def do_open_current():
        if state.mode == "pick_template":
            if state.target_project_path:
                on_select_project(state.target_project_path, template=state.current_dir)
        else:
            on_select_project(state.current_dir, template=None)

    open_current_btn = ui.button(page_row, "BtnOpenCurrent", "Open Current Folder as Project", 
                                 do_open_current, w=270, h=28, color=(45, 60, 80))

    dynamic_rows = []

    def refresh_file_list():
        nonlocal dynamic_rows
        # Destroy existing row entities and their children
        for r in dynamic_rows:
            try:
                for child in list(r.children):
                    child.destroy()
                r.destroy()
            except Exception:
                pass
        dynamic_rows.clear()

        # Update Titles & Status for Mode
        if state.mode == "pick_template":
            title.text = "LittleBigEngine - Step 2: Select Application / Template Project to Copy From"
            subtitle.text = f"Creating New Project: {state.target_project_path.name if state.target_project_path else ''}"
            status_lbl.text = f"🎯 STEP 2: Click any project/template below to copy it into '{state.target_project_path.name if state.target_project_path else ''}'"
            status_lbl.color = (251, 191, 36, 255)
            open_current_btn.text = "Copy Current Folder as Template"
        else:
            title.text = "LittleBigEngine - Project Manager (LBE v1)"
            subtitle.text = "UUID item kernel | Typed references | Inherited components"
            open_current_btn.text = "Open Current Folder as Project"

        # Read directory
        try:
            entries = list(state.current_dir.iterdir())
            entries.sort(key=lambda p: (
                0 if (p.is_dir() and p.name.endswith(".lbe")) else (1 if p.is_dir() else 2),
                p.name.lower()
            ))
        except Exception:
            entries = []

        total_items = len(entries)
        max_pages = max(1, (total_items + state.items_per_page - 1) // state.items_per_page)
        if state.page >= max_pages:
            state.page = max_pages - 1
        if state.page < 0:
            state.page = 0

        page_lbl.text = f"Items {state.page * state.items_per_page + 1 if total_items else 0}-{min((state.page + 1) * state.items_per_page, total_items)} of {total_items} (Page {state.page + 1}/{max_pages})"

        start_idx = state.page * state.items_per_page
        visible_entries = entries[start_idx : start_idx + state.items_per_page]

        row_w = max(200, items_container.w - 24)

        try:
            template_root = template_path("editor").parent.resolve()
        except Exception:
            template_root = None

        for p in visible_entries:
            is_dir = p.is_dir()
            is_lbe = is_dir and p.name.endswith(".lbe")
            is_legacy = is_dir and not is_lbe and ((p / "app.py").exists() or (p / "project.json").exists())
            is_template_item = is_dir and (template_root is not None and p.parent.resolve() == template_root)

            if state.mode == "pick_template":
                # In Step 2: Projects and template items copy into new project; normal folders navigate
                if p.name == "editor" or (template_root is not None and p.resolve() == (template_root / "editor").resolve()):
                    display_name = "🚀  Editor (Default Application - LBE v1)  [Click to Copy & Create]"
                    btn_color = (28, 85, 75)
                    btn_hover = (45, 125, 105)
                    ink_color = (75, 230, 185, 255)
                    action = (lambda target=p: lambda: on_select_project(state.target_project_path, template=target))()
                elif is_lbe or is_legacy or is_template_item:
                    display_name = f"🚀  Copy '{p.name}' & Create Project"
                    btn_color = (65, 55, 25)
                    btn_hover = (115, 95, 40)
                    ink_color = (251, 191, 36, 255)
                    action = (lambda target=p: lambda: on_select_project(state.target_project_path, template=target))()
                elif is_dir:
                    display_name = f"📁  {p.name}"
                    btn_color = (30, 42, 56)
                    btn_hover = (48, 68, 90)
                    ink_color = (220, 230, 239, 255)
                    action = (lambda target=p: lambda: (setattr(state, "current_dir", target), setattr(state, "page", 0)))()
                else:
                    display_name = f"📄  {p.name}"
                    btn_color = (26, 35, 46)
                    btn_hover = (38, 50, 66)
                    ink_color = (175, 193, 213, 255)
                    action = (lambda target=p: lambda: None)()

                row_entity = ui.create(items_container, f"Row_{p.name}", "panel", w=row_w, h=34, color=(25, 34, 45))
                main_btn = ui.button(row_entity, f"Btn_{p.name}", text=display_name, action=action,
                                     w=max(100, row_w - 12), h=30, color=btn_color, hover_color=btn_hover, ink=ink_color)
                main_btn.tags.add("main_act")
                stack(row_entity, [main_btn], axis="x", padding=2, gap=0)
                dynamic_rows.append(row_entity)
            else:
                # In Step 1: One-step opening
                if is_lbe:
                    display_name = f"🚀  {p.name}   [LBE Project - Click to Open]"
                    btn_color = (28, 55, 75)
                    btn_hover = (45, 95, 125)
                    ink_color = (69, 182, 199, 255)
                    action = (lambda target=p: lambda: on_select_project(target, template=None))()
                elif is_legacy:
                    display_name = f"📦  {p.name}   [Legacy Project - Click to Open]"
                    btn_color = (55, 45, 30)
                    btn_hover = (95, 75, 40)
                    ink_color = (232, 165, 80, 255)
                    action = (lambda target=p: lambda: on_select_project(target, template=None))()
                elif is_dir:
                    display_name = f"📁  {p.name}"
                    btn_color = (30, 42, 56)
                    btn_hover = (48, 68, 90)
                    ink_color = (220, 230, 239, 255)
                    action = (lambda target=p: lambda: (setattr(state, "current_dir", target), setattr(state, "page", 0), save_last_directory(target)))()
                else:
                    ext = p.suffix.lower()
                    icon = "🐍" if ext == ".py" else ("⚙️" if ext == ".json" else ("🖼️" if ext in (".png", ".jpg") else "📄"))
                    display_name = f"{icon}  {p.name}"
                    btn_color = (26, 35, 46)
                    btn_hover = (38, 50, 66)
                    ink_color = (175, 193, 213, 255)
                    action = (lambda target=p: lambda: (setattr(status_lbl, "text", f"File: {target.name} ({target.stat().st_size} bytes)"), setattr(status_lbl, "color", (145, 163, 183, 255))))()

                row_entity = ui.create(items_container, f"Row_{p.name}", "panel", w=row_w, h=34, color=(25, 34, 45))

                main_btn = ui.button(row_entity, f"Btn_{p.name}", text=display_name, action=action,
                                     w=max(100, row_w - 210), h=30, color=btn_color, hover_color=btn_hover, ink=ink_color)
                main_btn.tags.add("main_act")

                def make_rename_action(target=p):
                    def handler():
                        new_name = name_field.buffer.text.strip()
                        if not new_name:
                            status_lbl.text = "Error: Type new name into 'New Project' input box to rename"
                            status_lbl.color = (248, 81, 73, 255)
                            return
                        new_path = state.current_dir / new_name
                        try:
                            target.rename(new_path)
                            status_lbl.text = f"Renamed '{target.name}' -> '{new_name}'"
                            status_lbl.color = (52, 211, 153, 255)
                            state.last_dir = None
                        except Exception as err:
                            status_lbl.text = f"Rename error: {err}"
                            status_lbl.color = (248, 81, 73, 255)
                    return handler

                rename_btn = ui.button(row_entity, f"Ren_{p.name}", text="✏️ Rename", action=make_rename_action(p),
                                       w=95, h=28, color=(40, 55, 75), hover_color=(60, 85, 115))

                def make_delete_action(target=p):
                    def handler():
                        try:
                            if target.is_dir():
                                shutil.rmtree(target)
                            else:
                                target.unlink()
                            status_lbl.text = f"Deleted: {target.name}"
                            status_lbl.color = (52, 211, 153, 255)
                            state.last_dir = None
                        except Exception as err:
                            status_lbl.text = f"Delete error: {err}"
                            status_lbl.color = (248, 81, 73, 255)
                    return handler

                del_btn = ui.button(row_entity, f"Del_{p.name}", text="🗑️ Delete", action=make_delete_action(p),
                                    w=95, h=28, color=(75, 35, 38), hover_color=(115, 45, 50))

                stack(row_entity, [main_btn, rename_btn, del_btn], axis="x", padding=2, gap=6)
                dynamic_rows.append(row_entity)

        stack(items_container, dynamic_rows, axis="y", padding=8, gap=4)

    def update(dt):
        w = max(800, window.width)
        h = max(550, window.height)
        
        # Container fills full window
        put(container, x=0, y=0, w=w, h=h)

        # 1. Update widths and heights of main panels
        path_row.w = w - 30
        action_row.w = w - 30
        status_lbl.w = w - 30
        items_container.w = w - 30
        items_container.h = max(180, h - 220)
        page_row.w = w - 30

        # 2. Position all main container panels FIRST so items_container gets its true screen (x, y) coordinates!
        stack(container, [title, subtitle, path_row, action_row, status_lbl, items_container, page_row], axis="y", padding=8, gap=6)

        # 3. Position children of toolbar rows
        path_field.w = max(200, path_row.w - 300)
        stack(path_row, [path_lbl, path_field, btn_go, btn_up, btn_refresh], axis="x", padding=0, gap=6)

        if state.mode == "pick_template":
            put(name_lbl, visible=False)
            put(name_field, visible=False)
            put(btn_create_proj, visible=False)
            put(btn_create_folder, visible=False)
            put(btn_use_default_editor, visible=True)
            put(btn_cancel_picker, visible=True)
            action_children = drive_buttons + [btn_use_default_editor, btn_cancel_picker]
        else:
            put(name_lbl, visible=True)
            put(name_field, visible=True)
            put(btn_create_proj, visible=True)
            put(btn_create_folder, visible=True)
            put(btn_use_default_editor, visible=False)
            put(btn_cancel_picker, visible=False)
            action_children = drive_buttons + [name_lbl, name_field, btn_create_proj, btn_create_folder]

        stack(action_row, action_children, axis="x", padding=0, gap=6)

        # 4. Check if directory, page, or items_per_page changed
        new_per_page = max(4, (items_container.h - 16) // 38)
        if state.last_dir != state.current_dir or state.last_page != state.page or state.items_per_page != new_per_page:
            state.last_dir = state.current_dir
            state.last_page = state.page
            state.items_per_page = new_per_page
            ui.set_text(path_field, str(state.current_dir))
            refresh_file_list()

        # 5. Position dynamic row children and stack dynamic rows inside items_container
        for r in dynamic_rows:
            r.w = items_container.w - 20
            main_btn = next((c for c in r.children if "main_act" in c.tags), None)
            if main_btn:
                if state.mode == "pick_template":
                    main_btn.w = max(100, r.w - 12)
                else:
                    main_btn.w = max(100, r.w - 210)
            stack(r, list(r.children), axis="x", padding=2, gap=6)

        stack(items_container, dynamic_rows, axis="y", padding=8, gap=4)

        # 6. Position pagination row children
        stack(page_row, [page_lbl, btn_prev, btn_next, open_current_btn], axis="x", padding=2, gap=10)

    sys_def = SystemDefinition("""
def update(dt):
    pass
""")
    system = root.systems.attach("launcher_layout", sys_def)
    system.namespace["update"] = update

    # Perform initial layout pass synchronously before first render frame
    update(0)

    return runtime
