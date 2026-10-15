"""In-editor Code Editor Panel with interactive hover-box tokens and live hot-reloading."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any

import dearpygui.dearpygui as dpg

from LBE.preprocessor import (
    extract_script_symbols,
    project_display_to_source,
    project_source_to_display,
)
from LBE.types import Error, InvalidResourceDataError, RuntimeID, Script
from .pills import render_code_token_pill

if TYPE_CHECKING:
    from .session import EditorSession


class CodeEditorPanel:
    """Dear PyGui Code Editor panel supporting interactive draggable hover-tokens and live hot-reloading."""

    def __init__(self, session: EditorSession, tag: str = "window_code_editor") -> None:
        self.session = session
        self.kernel = session.kernel
        self.tag = tag

        self.current_script_id: RuntimeID | None = None
        self.current_disk_code: str = ""
        self.current_display_code: str = ""
        self.active_mode: str = "Code View (Interactive)"
        self.status_message: str = "Ready"
        self.status_color: tuple[int, int, int, int] = (140, 180, 220, 255)

        self._script_options: list[tuple[str, RuntimeID]] = []

    def build(self) -> None:
        """Construct the Code Editor panel window and UI layout."""
        if dpg.does_item_exist(self.tag):
            dpg.delete_item(self.tag)

        self._refresh_script_list()

        with dpg.window(
            tag=self.tag,
            label="Code Editor",
            width=650,
            height=450,
            pos=(280, 540),
            no_collapse=False,
        ):
            # Toolbar
            with dpg.group(horizontal=True):
                combo_items = [opt[0] for opt in self._script_options]
                default_combo = combo_items[0] if combo_items else "No Scripts Found"
                dpg.add_combo(
                    tag=f"{self.tag}_script_combo",
                    items=combo_items,
                    default_value=default_combo,
                    width=240,
                    callback=self._on_combo_selected,
                )

                dpg.add_radio_button(
                    tag=f"{self.tag}_mode_radio",
                    items=["Code View (Interactive)", "Source Code"],
                    default_value=self.active_mode,
                    horizontal=True,
                    callback=self._on_mode_changed,
                )

                dpg.add_button(
                    label="Apply & Hot-Reload",
                    callback=self._on_apply_code,
                )

                dpg.add_button(
                    label="Refresh",
                    callback=self._on_reload_button,
                )

            # Status bar under toolbar
            dpg.add_text(
                tag=f"{self.tag}_status",
                default_value=self.status_message,
                color=self.status_color,
            )
            dpg.add_separator()

            # Content container
            with dpg.child_window(tag=f"{self.tag}_content", border=False, autosize_x=True, autosize_y=True):
                self._render_editor_body()

    def open_script(self, script_id: RuntimeID) -> None:
        """Switch active script to target script_id and rebuild view."""
        self.current_script_id = script_id
        self._load_current_script()
        if dpg.does_item_exist(f"{self.tag}_script_combo"):
            for opt_label, rid in self._script_options:
                if rid == script_id:
                    dpg.set_value(f"{self.tag}_script_combo", opt_label)
                    break
        self._rebuild_content()

    def _refresh_script_list(self) -> None:
        """Scan kernel for all loaded Script resources."""
        self._script_options.clear()
        if not hasattr(self.kernel, "resources"):
            return

        for rid, res in list(self.kernel.resources.items()):
            if isinstance(res, (dict, Mapping)) and res.get("type") == Script:
                name = res.get("name") or f"Script_{rid}"
                sid = self.kernel.get_storage_id(rid)
                sid_short = sid.hex()[:8] if not isinstance(sid, Error) else "local"
                label = f"{name} ({sid_short})"
                self._script_options.append((label, rid))

        if self.current_script_id is None and self._script_options:
            self.current_script_id = self._script_options[0][1]
            self._load_current_script()

    def _load_current_script(self) -> None:
        """Load on-disk and projected display code for current_script_id."""
        if self.current_script_id is None:
            self.current_disk_code = ""
            self.current_display_code = ""
            return

        res = self.kernel.get_resource(self.current_script_id)
        if isinstance(res, Error) or not isinstance(res, (dict, Mapping)):
            self.current_disk_code = ""
            self.current_display_code = ""
            return

        data = res.get("data", {})
        code = ""
        if isinstance(data, (dict, Mapping)):
            code = data.get("code", "")
            s_path = data.get("source_path", "")
            if not code and s_path:
                try:
                    p = Path(s_path)
                    if not p.is_absolute() and hasattr(self.kernel, "folder_location"):
                        p = self.kernel.folder_location / p
                    if p.exists():
                        code = p.read_text(encoding="utf-8")
                except Exception:
                    pass

        self.current_disk_code = code

        symbols = {}
        if isinstance(data, (dict, Mapping)):
            symbols = dict(data.get("symbols", {}))
        if not symbols and code:
            symbols = extract_script_symbols(code)

        display_code, _ = project_source_to_display(code, symbols=symbols, kernel=self.kernel)
        self.current_display_code = display_code

    def _render_editor_body(self) -> None:
        """Render either the interactive token view or raw text input."""
        if self.current_script_id is None:
            dpg.add_text("No script selected.", color=(160, 160, 160, 255))
            return

        if self.active_mode == "Source Code":
            dpg.add_input_text(
                tag=f"{self.tag}_input",
                default_value=self.current_disk_code,
                multiline=True,
                tab_input=True,
                width=-1,
                height=-1,
            )
            return

        # Interactive Mode: line-by-line rendering with hover-box token pills
        lines = self.current_disk_code.splitlines()
        if not lines:
            dpg.add_text("# (Empty script)", color=(120, 120, 120, 255))
            return

        res = self.kernel.get_resource(self.current_script_id)
        symbols = {}
        if isinstance(res, (dict, Mapping)):
            data = res.get("data", {})
            if isinstance(data, (dict, Mapping)):
                symbols = dict(data.get("symbols", {}))
        if not symbols:
            symbols = extract_script_symbols(self.current_disk_code)

        fn_def_re = re.compile(r'^(?P<indent>\s*)(?P<prefix>(?:def|async\s+def)\s+)(?P<fn_sym>(?:_fn_|fn_)[0-9a-fA-F]{32,64})\s*\((?P<rest>.*)$')
        ref_re = re.compile(r'<lbe\.ref\(\s*["\'](?P<sid>[0-9a-fA-F]{32,64})["\'](?:\s*,\s*["\'](?P<alias>[^"\']*)["\'])?\s*\)>')

        for idx, line in enumerate(lines, start=1):
            with dpg.group(horizontal=True):
                # Line gutter
                dpg.add_text(f"{idx:3d} |", color=(100, 105, 115, 255))

                # Check if line is a function definition with UUID
                fn_match = fn_def_re.match(line)
                if fn_match:
                    indent = fn_match.group("indent")
                    prefix = fn_match.group("prefix")
                    fn_sym = fn_match.group("fn_sym")
                    rest = fn_match.group("rest")

                    display_name = symbols.get(fn_sym)
                    clean_uuid = fn_sym[3:] if fn_sym.startswith("fn_") else (fn_sym[4:] if fn_sym.startswith("_fn_") else fn_sym)
                    if not display_name:
                        display_name = symbols.get(clean_uuid.lower(), fn_sym)

                    if indent:
                        dpg.add_text(indent)
                    dpg.add_text(prefix, color=(86, 156, 214, 255))  # Python keyword blue
                    # Render the token pill (looks like plain text until hovered, revealing box)
                    render_code_token_pill(
                        display_name=display_name,
                        uuid_hex=clean_uuid,
                        token_type="function",
                        kernel=self.kernel,
                    )
                    dpg.add_text(f"({rest}")
                    continue

                # Check if line contains <lbe.ref(...)>
                ref_match = ref_re.search(line)
                if ref_match:
                    start_pos = ref_match.start()
                    end_pos = ref_match.end()
                    pre_text = line[:start_pos]
                    post_text = line[end_pos:]

                    sid = ref_match.group("sid").lower()
                    alias = ref_match.group("alias")
                    display_name = alias
                    if not display_name and hasattr(self.kernel, "resources"):
                        try:
                            sid_b = bytes.fromhex(sid)
                            rid = self.kernel.get_resource_id(sid_b)
                            if not isinstance(rid, Error) and hasattr(self.kernel, "get_resource"):
                                r = self.kernel.get_resource(rid)
                                if isinstance(r, (dict, Mapping)) and r.get("name"):
                                    display_name = r["name"]
                        except Exception:
                            pass
                    if not display_name:
                        display_name = symbols.get(sid, f"Entity_{sid[:8]}")

                    if pre_text:
                        dpg.add_text(pre_text)
                    render_code_token_pill(
                        display_name=display_name,
                        uuid_hex=sid,
                        token_type="entity",
                        kernel=self.kernel,
                    )
                    if post_text:
                        dpg.add_text(post_text)
                    continue

                # Plain line
                dpg.add_text(line)

        dpg.add_spacer(height=10)
        dpg.add_text(
            "ℹ️ Hover over function or entity names to reveal the outline box. Drag boxes into Inspector slots.",
            color=(100, 150, 200, 220),
        )

    def _on_mode_changed(self, sender: Any, app_data: str) -> None:
        self.active_mode = app_data
        self._rebuild_content()

    def _on_combo_selected(self, sender: Any, app_data: str) -> None:
        for label, rid in self._script_options:
            if label == app_data:
                self.current_script_id = rid
                self._load_current_script()
                self._rebuild_content()
                break

    def _on_reload_button(self) -> None:
        self._refresh_script_list()
        self._load_current_script()
        self._rebuild_content()

    def _on_apply_code(self) -> None:
        """Apply edited code to script resource and hot-reload."""
        if self.current_script_id is None:
            return

        new_code = self.current_disk_code
        if self.active_mode == "Source Code" and dpg.does_item_exist(f"{self.tag}_input"):
            new_code = dpg.get_value(f"{self.tag}_input")

        # Update script in kernel
        if hasattr(self.kernel, "update_script_source"):
            err = self.kernel.update_script_source(self.current_script_id, new_code)
            if isinstance(err, Error):
                self._set_status(f"Error: {err.description}", color=(255, 100, 100, 255))
                return

        self.current_disk_code = new_code
        self._load_current_script()
        self._set_status("Hot-reloaded successfully!", color=(100, 220, 120, 255))
        self._rebuild_content()

    def _set_status(self, msg: str, color: tuple[int, int, int, int] = (140, 180, 220, 255)) -> None:
        self.status_message = msg
        self.status_color = color
        if dpg.does_item_exist(f"{self.tag}_status"):
            dpg.set_value(f"{self.tag}_status", msg)
            dpg.configure_item(f"{self.tag}_status", color=color)

    def _rebuild_content(self) -> None:
        """Clear and re-render the content area."""
        if not dpg.does_item_exist(f"{self.tag}_content"):
            return
        dpg.delete_item(f"{self.tag}_content", children_only=True)
        with dpg.child_window(parent=f"{self.tag}_content", border=False, autosize_x=True, autosize_y=True):
            self._render_editor_body()
