"""In-editor Code Editor Panel with interactive hover-box tokens, syntax highlighting, and live hot-reloading."""

from __future__ import annotations

import ast
from collections.abc import Mapping
import io
import keyword
from pathlib import Path
import re
import tokenize
from typing import TYPE_CHECKING, Any

import dearpygui.dearpygui as dpg

from LBE.preprocessor import (
    extract_script_symbols,
    project_display_to_source_with_symbols,
    project_source_to_display,
)
from LBE.types import Error, InvalidResourceDataError, RuntimeID, Script
from .pills import get_code_token_pill_theme, render_code_token_pill

if TYPE_CHECKING:
    from .session import EditorSession


def _is_theme_valid(tag: str) -> bool:
    try:
        return dpg.does_item_exist(tag) and dpg.get_item_type(tag) == "mvAppItemType::mvTheme"
    except Exception:
        return False


def get_code_editor_input_theme() -> str:
    """Return a dark monospace theme for the code editor text input."""
    tag = "lbe_theme_code_editor_input"
    if _is_theme_valid(tag):
        return tag
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)
    with dpg.theme(tag=tag):
        with dpg.theme_component(dpg.mvInputText):
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (20, 23, 29, 255))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (225, 230, 245, 255))
            dpg.add_theme_color(dpg.mvThemeCol_TextSelectedBg, (42, 72, 120, 255))
            dpg.add_theme_color(dpg.mvThemeCol_InputTextCursor, (120, 200, 255, 255))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 4)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 8, 6)
    return tag


def get_syntax_line_theme() -> str:
    """Return a zero-spacing theme for syntax-highlighted code lines so tokens sit seamlessly."""
    tag = "lbe_theme_syntax_line"
    if _is_theme_valid(tag):
        return tag
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)
    with dpg.theme(tag=tag):
        with dpg.theme_component(dpg.mvGroup):
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
        with dpg.theme_component(dpg.mvText):
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 3)
    return tag


def get_token_ribbon_theme() -> str:
    """Return a theme for the interactive token ribbon."""
    tag = "lbe_theme_token_ribbon"
    if _is_theme_valid(tag):
        return tag
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)
    with dpg.theme(tag=tag):
        with dpg.theme_component(dpg.mvGroup):
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 6, 4)
    return tag


class CodeEditorPanel:
    """Dear PyGui Code Editor panel supporting interactive draggable hover-tokens, syntax highlighting, and live hot-reloading."""

    def __init__(self, session: EditorSession, tag: str = "window_code_editor") -> None:
        self.session = session
        self.kernel = session.kernel
        self.tag = tag

        self.current_script_id: RuntimeID | None = None
        self.current_disk_code: str = ""
        self.current_display_code: str = ""
        self.current_symbols: dict[str, str] = {}
        self.active_mode: str = "Interactive Editor"
        self.status_message: str = "Ready — Edit functions like normal Python (saved with persistent UUIDs)"
        self.status_color: tuple[int, int, int, int] = (140, 185, 235, 255)

        self._script_options: list[tuple[str, RuntimeID]] = []
        self._key_handler_tag: str = f"{self.tag}_key_handler_reg"

    def build(self) -> None:
        """Construct the Code Editor panel window and UI layout."""
        if dpg.does_item_exist(self.tag):
            dpg.delete_item(self.tag)

        self._refresh_script_list()

        # Global or local shortcut handler for Ctrl+S
        if dpg.does_item_exist(self._key_handler_tag):
            dpg.delete_item(self._key_handler_tag)
        try:
            with dpg.handler_registry(tag=self._key_handler_tag):
                dpg.add_key_press_handler(
                    key=dpg.mvKey_S,
                    callback=self._on_ctrl_s_pressed,
                )
        except Exception:
            pass

        with dpg.window(
            tag=self.tag,
            label="Code Editor",
            width=700,
            height=500,
            pos=(280, 480),
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
                    width=230,
                    callback=self._on_combo_selected,
                )

                # Modern view selector
                mode_items = ["Interactive Editor", "Syntax & Live Tokens", "Split View"]
                default_mode = (
                    self.active_mode
                    if self.active_mode in mode_items
                    else ("Syntax & Live Tokens" if "Interactive" in self.active_mode else "Interactive Editor")
                )
                dpg.add_radio_button(
                    tag=f"{self.tag}_mode_radio",
                    items=mode_items,
                    default_value=default_mode,
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

            # Interactive Token Ribbon Container
            with dpg.group(tag=f"{self.tag}_token_container"):
                self._render_token_bar()

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
        self._rebuild_all()

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
            self.current_symbols = {}
            return

        res = self.kernel.get_resource(self.current_script_id)
        if isinstance(res, Error) or not isinstance(res, (dict, Mapping)):
            self.current_disk_code = ""
            self.current_display_code = ""
            self.current_symbols = {}
            return

        data = res.get("data", {})
        code = ""
        symbols: dict[str, str] = {}
        if isinstance(data, (dict, Mapping)):
            code = data.get("code", "")
            symbols = dict(data.get("symbols", {}))
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

        if not symbols and code:
            symbols = extract_script_symbols(code)
        self.current_symbols = symbols

        display_code, _ = project_source_to_display(code, symbols=symbols, kernel=self.kernel)
        self.current_display_code = display_code

    def _render_token_bar(self) -> None:
        """Render the horizontal interactive symbol deck above the editor."""
        container_tag = f"{self.tag}_token_container"
        if not dpg.does_item_exist(container_tag):
            return

        dpg.delete_item(container_tag, children_only=True)

        with dpg.group(parent=container_tag, horizontal=True):
            dpg.bind_item_theme(dpg.last_item(), get_token_ribbon_theme())
            dpg.add_text("⚡ Exported Tokens:", color=(120, 175, 230, 255))

            rendered_any = False
            for sym_key, disp_name in list(self.current_symbols.items()):
                clean_uuid = sym_key.removeprefix("fn_").removeprefix("_fn_")
                if len(clean_uuid) in (32, 64):
                    render_code_token_pill(
                        display_name=f"def {disp_name}",
                        uuid_hex=clean_uuid,
                        token_type="function",
                        kernel=self.kernel,
                    )
                    rendered_any = True

            # Also check if script references any known entities
            if hasattr(self.kernel, "resources"):
                for rid, r in list(self.kernel.resources.items()):
                    if isinstance(r, (dict, Mapping)) and hasattr(self.kernel, "is_entity") and self.kernel.is_entity(rid):
                        ename = r.get("name")
                        if ename and ename in self.current_display_code:
                            sid = self.kernel.get_storage_id(rid)
                            if hasattr(sid, "hex"):
                                render_code_token_pill(
                                    display_name=ename,
                                    uuid_hex=sid.hex().lower(),
                                    token_type="entity",
                                    kernel=self.kernel,
                                )
                                rendered_any = True

            if not rendered_any:
                dpg.add_text("(No exported functions yet — define `def my_func():` and Apply)", color=(130, 140, 155, 255))

    def _render_editor_body(self) -> None:
        """Render editor according to active mode."""
        if self.current_script_id is None:
            dpg.add_text("No script selected.", color=(160, 160, 160, 255))
            return

        is_legacy_source = self.active_mode == "Source Code"
        is_syntax_only = self.active_mode in ("Syntax & Live Tokens", "Code View (Interactive)")
        is_split = self.active_mode == "Split View"

        if is_syntax_only:
            self._render_syntax_pane()
        elif is_split:
            with dpg.group(horizontal=True):
                # Left: Editor pane (50% width)
                with dpg.child_window(border=True, width=335, autosize_y=True):
                    dpg.add_text("Python Editor (Normal Code):", color=(130, 180, 240, 255))
                    self._render_input_editor()
                # Right: Syntax & Live Token Canvas (50% width)
                with dpg.child_window(border=True, width=-1, autosize_y=True):
                    dpg.add_text("Interactive Token & Syntax Canvas:", color=(220, 220, 170, 255))
                    self._render_syntax_pane()
        else:
            # Primary mode: Interactive Editor (Full normal Python editor)
            self._render_input_editor(is_raw=is_legacy_source)

    def _render_input_editor(self, is_raw: bool = False) -> None:
        """Render the primary multiline text editor containing projected human Python code."""
        initial_text = self.current_disk_code if is_raw else self.current_display_code

        input_tag = f"{self.tag}_input"
        dpg.add_input_text(
            tag=input_tag,
            default_value=initial_text,
            multiline=True,
            tab_input=True,
            width=-1,
            height=-1,
        )
        dpg.bind_item_theme(input_tag, get_code_editor_input_theme())

    def _render_syntax_pane(self) -> None:
        """Render syntax-highlighted code with embedded interactive hover-box tokens and 0-spacing."""
        code_to_display = self.current_display_code or self.current_disk_code
        if not code_to_display.strip():
            dpg.add_text("# (Empty script)", color=(120, 120, 120, 255))
            return

        token_lines = self._parse_code_tokens(code_to_display)
        line_theme = get_syntax_line_theme()

        for idx, line_toks in enumerate(token_lines, start=1):
            with dpg.group(horizontal=True):
                dpg.bind_item_theme(dpg.last_item(), line_theme)
                # Line gutter
                dpg.add_text(f"{idx:3d} | ", color=(100, 110, 128, 255))

                for tok in line_toks:
                    if tok["is_pill"] and tok["pill_data"]:
                        p = tok["pill_data"]
                        render_code_token_pill(
                            display_name=p["display_name"],
                            uuid_hex=p["uuid"],
                            token_type=p["token_type"],
                            kernel=self.kernel,
                        )
                    else:
                        dpg.add_text(tok["text"], color=tok["color"])

        dpg.add_spacer(height=10)
        dpg.add_text(
            "ℹ️ Hover over function names to reveal outline box. Drag boxes into Inspector slots.",
            color=(100, 150, 200, 220),
        )

    def _parse_code_tokens(self, code: str) -> list[list[dict[str, Any]]]:
        """Tokenize code preserving exact whitespace, syntax colors, and interactive symbol tokens."""
        syms = self.current_symbols
        inv_syms: dict[str, str] = {}
        for k, v in syms.items():
            if v and (k.startswith(("fn_", "_fn_")) or len(k) in (32, 64)):
                inv_syms[v] = k

        entity_names: dict[str, str] = {}
        if hasattr(self.kernel, "resources"):
            for rid, r in list(self.kernel.resources.items()):
                if isinstance(r, (dict, Mapping)) and hasattr(self.kernel, "is_entity") and self.kernel.is_entity(rid):
                    ename = r.get("name")
                    if ename:
                        sid = self.kernel.get_storage_id(rid)
                        if hasattr(sid, "hex"):
                            entity_names[ename] = sid.hex().lower()

        raw_tokens: list[tokenize.TokenInfo] = []
        try:
            raw_tokens = list(tokenize.generate_tokens(io.StringIO(code).readline))
        except Exception:
            pass

        lines = code.splitlines()
        tok_by_line: dict[int, list[tokenize.TokenInfo]] = {}
        for t in raw_tokens:
            if t.type not in (tokenize.ENCODING, tokenize.NEWLINE, tokenize.NL, tokenize.ENDMARKER):
                tok_by_line.setdefault(t.start[0], []).append(t)

        result: list[list[dict[str, Any]]] = []
        for lineno, line_text in enumerate(lines, start=1):
            line_items: list[dict[str, Any]] = []
            cur_col = 0
            line_toks = tok_by_line.get(lineno, [])

            if not line_toks:
                # Fallback regex tokenization for unparsed / empty / syntax-error line
                res_line = self._regex_tokenize_line(line_text, inv_syms, entity_names)
                result.append(res_line)
                continue

            for i, t in enumerate(line_toks):
                if t.start[1] > cur_col:
                    ws = line_text[cur_col:t.start[1]]
                    line_items.append({"text": ws, "color": (212, 212, 212, 255), "is_pill": False, "pill_data": None})
                cur_col = t.end[1]

                prev_tok = line_toks[i - 1] if i > 0 else None
                is_def_name = prev_tok is not None and prev_tok.string in ("def", "async")
                is_kw = keyword.iskeyword(t.string)

                pill_data: dict[str, Any] | None = None
                if t.type == tokenize.COMMENT:
                    col = (106, 153, 85, 255)  # Green
                elif t.type == tokenize.STRING:
                    col = (214, 157, 133, 255)  # Peach
                elif t.type == tokenize.NUMBER:
                    col = (181, 206, 168, 255)  # Mint green
                elif is_kw:
                    col = (86, 156, 214, 255)  # Blue
                elif is_def_name or t.string in inv_syms:
                    col = (220, 220, 170, 255)  # Yellow
                    sym_k = inv_syms.get(t.string, f"fn_{t.string}")
                    clean_uuid = sym_k.removeprefix("fn_").removeprefix("_fn_")
                    pill_data = {"display_name": t.string, "uuid": clean_uuid, "token_type": "function"}
                elif t.string in entity_names:
                    col = (78, 201, 176, 255)  # Cyan
                    pill_data = {"display_name": t.string, "uuid": entity_names[t.string], "token_type": "entity"}
                elif t.string in (
                    "Entity", "Transform", "Health", "Platform", "Stats", "True", "False", "None",
                    "self", "int", "float", "str", "bool", "list", "dict", "set", "tuple", "min", "max",
                ):
                    col = (78, 201, 176, 255)  # Teal
                elif t.type == tokenize.OP:
                    col = (212, 212, 212, 255)  # Gray
                else:
                    col = (156, 220, 254, 255)  # Light Blue

                line_items.append({
                    "text": t.string,
                    "color": col,
                    "is_pill": pill_data is not None,
                    "pill_data": pill_data,
                })

            if cur_col < len(line_text):
                line_items.append({
                    "text": line_text[cur_col:],
                    "color": (212, 212, 212, 255),
                    "is_pill": False,
                    "pill_data": None,
                })

            result.append(line_items)

        return result

    def _regex_tokenize_line(
        self,
        line_text: str,
        inv_syms: dict[str, str],
        entity_names: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Fallback regex tokenizer for lines during syntax errors or comments."""
        if not line_text:
            return [{"text": "", "color": (212, 212, 212, 255), "is_pill": False, "pill_data": None}]

        tok_re = re.compile(
            r"(?P<comment>#[^\r\n]*)"
            r"|(?P<string>f?\"[^\"]*\"|f?'[^']*')"
            r"|(?P<number>\b\d+\.?\d*\b)"
            r"|(?P<word>[a-zA-Z_]\w*)"
            r"|(?P<space>\s+)"
            r"|(?P<op>[^\s\w])"
        )
        items: list[dict[str, Any]] = []
        is_after_def = False

        for m in tok_re.finditer(line_text):
            val = m.group(0)
            if m.group("comment"):
                items.append({"text": val, "color": (106, 153, 85, 255), "is_pill": False, "pill_data": None})
            elif m.group("string"):
                items.append({"text": val, "color": (214, 157, 133, 255), "is_pill": False, "pill_data": None})
            elif m.group("number"):
                items.append({"text": val, "color": (181, 206, 168, 255), "is_pill": False, "pill_data": None})
            elif m.group("space"):
                items.append({"text": val, "color": (212, 212, 212, 255), "is_pill": False, "pill_data": None})
            elif m.group("word"):
                pill_data = None
                if keyword.iskeyword(val):
                    col = (86, 156, 214, 255)
                    is_after_def = val in ("def", "async")
                elif is_after_def or val in inv_syms:
                    col = (220, 220, 170, 255)
                    sym_k = inv_syms.get(val, f"fn_{val}")
                    clean_uuid = sym_k.removeprefix("fn_").removeprefix("_fn_")
                    pill_data = {"display_name": val, "uuid": clean_uuid, "token_type": "function"}
                    is_after_def = False
                elif val in entity_names:
                    col = (78, 201, 176, 255)
                    pill_data = {"display_name": val, "uuid": entity_names[val], "token_type": "entity"}
                elif val in ("Entity", "Transform", "Health", "Stats", "True", "False", "None", "self"):
                    col = (78, 201, 176, 255)
                else:
                    col = (156, 220, 254, 255)
                items.append({"text": val, "color": col, "is_pill": pill_data is not None, "pill_data": pill_data})
            else:
                items.append({"text": val, "color": (212, 212, 212, 255), "is_pill": False, "pill_data": None})

        return items

    def _on_mode_changed(self, sender: Any, app_data: str) -> None:
        self.active_mode = app_data
        self._rebuild_content()

    def _on_combo_selected(self, sender: Any, app_data: str) -> None:
        for label, rid in self._script_options:
            if label == app_data:
                self.current_script_id = rid
                self._load_current_script()
                self._rebuild_all()
                break

    def _on_reload_button(self) -> None:
        self._refresh_script_list()
        self._load_current_script()
        self._rebuild_all()

    def _on_ctrl_s_pressed(self, sender: Any, app_data: Any) -> None:
        """Handle Ctrl+S keyboard shortcut."""
        if dpg.is_key_down(dpg.mvKey_Control):
            self._on_apply_code()

    def _on_apply_code(self) -> None:
        """Apply edited code to script resource and hot-reload.

        Translates projected human-readable Python functions back to persistent UUIDs on disk,
        allocating new 32-hex UUIDs for any newly defined functions and updating script symbols.
        """
        if self.current_script_id is None:
            return

        input_tag = f"{self.tag}_input"
        if not dpg.does_item_exist(input_tag):
            return

        edited_code = dpg.get_value(input_tag)

        if self.active_mode == "Source Code":
            disk_code = edited_code
            updated_symbols = self.current_symbols
        else:
            disk_code, updated_symbols = project_display_to_source_with_symbols(
                edited_code,
                symbols=dict(self.current_symbols),
                kernel=self.kernel,
            )

        # Update script in kernel
        if hasattr(self.kernel, "update_script_source"):
            err = self.kernel.update_script_source(self.current_script_id, disk_code)
            if isinstance(err, Error):
                self._set_status(f"Error: {err.description}", color=(255, 100, 100, 255))
                return

        # Synchronize symbols in kernel memory and function exports
        res = self.kernel.get_resource(self.current_script_id)
        if isinstance(res, (dict, Mapping)):
            data = res.get("data")
            if isinstance(data, dict):
                data["symbols"] = updated_symbols
                data["code"] = disk_code

        # Register any newly allocated function UUIDs into kernel.function_exports
        if hasattr(self.kernel, "function_exports"):
            sid = self.kernel.get_storage_id(self.current_script_id)
            if hasattr(sid, "hex"):
                for sym_key, disp_name in updated_symbols.items():
                    clean = sym_key.removeprefix("fn_").removeprefix("_fn_").lower()
                    if len(clean) in (32, 64):
                        self.kernel.function_exports[clean] = (sid, sym_key)

        if hasattr(self.kernel, "save_dirty_resources"):
            self.kernel.save_dirty_resources()

        self.current_disk_code = disk_code
        self.current_display_code = edited_code if self.active_mode != "Source Code" else disk_code
        self.current_symbols = updated_symbols

        fn_count = len([k for k in updated_symbols if k.startswith(("fn_", "_fn_")) or len(k) in (32, 64)])
        self._set_status(f"Hot-reloaded successfully! Saved {fn_count} functions with persistent UUIDs.", color=(100, 220, 120, 255))
        self._rebuild_all()

    def _set_status(self, msg: str, color: tuple[int, int, int, int] = (140, 185, 235, 255)) -> None:
        self.status_message = msg
        self.status_color = color
        if dpg.does_item_exist(f"{self.tag}_status"):
            dpg.set_value(f"{self.tag}_status", msg)
            dpg.configure_item(f"{self.tag}_status", color=color)

    def _rebuild_content(self) -> None:
        """Clear and re-render the content body area."""
        if not dpg.does_item_exist(f"{self.tag}_content"):
            return
        dpg.delete_item(f"{self.tag}_content", children_only=True)
        with dpg.child_window(parent=f"{self.tag}_content", border=False, autosize_x=True, autosize_y=True):
            self._render_editor_body()

    def _rebuild_all(self) -> None:
        """Re-render both the token ribbon and the content area."""
        self._render_token_bar()
        self._rebuild_content()
