"""Visual pill tokens and script function display projection for LittleBigEngine Editor."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import io
from pathlib import Path
import re
import tokenize
from typing import Any

import dearpygui.dearpygui as dpg

from LBE.preprocessor import ReferencePreprocessor, extract_script_symbols
from LBE.types import Error, InvalidResourceDataError, RuntimeIDNotFoundOnMemoryError, Script


PILL_REF_REGEX = re.compile(
    r"^<\|(?P<res_type>\d+)\|(?P<sid>[0-9a-fA-F]{32,64})\|>(?:\.(?P<fn>[a-zA-Z_][a-zA-Z0-9_]*))?$"
)

def _is_theme_valid(tag: str) -> bool:
    try:
        return dpg.does_item_exist(tag) and dpg.get_item_type(tag) == "mvAppItemType::mvTheme"
    except Exception:
        return False


def get_pill_theme() -> str:
    """Return a Dear PyGui theme for visual pill badges with cyan/purple accents."""
    tag = "lbe_theme_pill"
    if _is_theme_valid(tag):
        return tag
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)
    with dpg.theme(tag=tag):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (38, 54, 78, 255))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (52, 78, 115, 255))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (68, 102, 150, 255))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (120, 215, 255, 255))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 12)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 8, 4)
    return tag


@dataclass(slots=True)
class PillData:
    """Projected visual pill token representation for an engine resource or script function."""

    res_type: int
    storage_id_hex: str
    res_name: str
    fn_symbol: str | None = None
    fn_display_name: str | None = None
    raw_ref: str = ""

    @property
    def display_label(self) -> str:
        """User-facing projected badge text."""
        if self.res_type == 0:
            return f"[{self.res_name}]"
        target = self.fn_display_name or self.fn_symbol or (self.storage_id_hex[:8] if self.storage_id_hex else "")
        if target:
            return f"[{self.res_name} :: {target}]"
        return f"[{self.res_name}]"


def parse_reference_pill(ref_str: str, kernel: Any) -> PillData | None:
    """Parse reference string into a PillData projection if it matches LittleBigEngine syntax.

    Matches `<|res_type|sid_hex|>` or `<|res_type|sid_hex|>.fn_name`.
    Queries kernel for resource name and function display names.
    """
    if not isinstance(ref_str, str):
        return None

    match = PILL_REF_REGEX.match(ref_str.strip())
    if not match:
        return None

    sid_hex = match.group("sid").lower()
    if len(sid_hex) % 2 != 0 or len(sid_hex) not in (32, 64):
        return None

    res_type = int(match.group("res_type"))
    fn = match.group("fn")
    raw_ref = ref_str.strip()

    res_name = f"Resource_{sid_hex[:8]}" if res_type != Script else f"Script_{sid_hex[:8]}"
    symbols: dict[str, str] = {}

    if kernel is not None:
        rid = None
        try:
            sid_bytes = bytes.fromhex(sid_hex)
            if hasattr(kernel, "get_resource_id"):
                candidate_rid = kernel.get_resource_id(sid_bytes)
                if not isinstance(candidate_rid, Error):
                    rid = candidate_rid
        except Exception:
            pass

        if rid is None and hasattr(kernel, "resource_storage_ids"):
            for candidate_rid, s_val in kernel.resource_storage_ids.items():
                if isinstance(s_val, (bytes, bytearray)) and s_val.hex().lower() == sid_hex:
                    rid = candidate_rid
                    break

        if rid is not None and hasattr(kernel, "resources") and rid in kernel.resources:
            res_dict = kernel.resources[rid]
            if isinstance(res_dict, dict):
                r_name = res_dict.get("name")
                if r_name:
                    res_name = r_name
                elif hasattr(kernel, "is_entity") and kernel.is_entity(rid):
                    res_name = f"Entity_{rid}"
                elif res_type == Script:
                    res_name = f"Script_{rid}"
                else:
                    res_name = f"Resource_{rid}"

            if res_type == Script:
                if hasattr(kernel, "get_script_proxy"):
                    proxy = kernel.get_script_proxy(rid)
                    if not isinstance(proxy, Error) and proxy is not None and hasattr(proxy, "symbols"):
                        symbols = proxy.symbols

                if not symbols and isinstance(res_dict, dict):
                    s_data = res_dict.get("data", {})
                    if isinstance(s_data, dict):
                        symbols = s_data.get("symbols", {})
                        if not symbols and "code" in s_data:
                            symbols = extract_script_symbols(s_data["code"])

    fn_symbol: str | None = None
    fn_display_name: str | None = None

    if fn is not None:
        if res_type == Script and symbols:
            if fn in symbols:
                fn_symbol = fn
                fn_display_name = symbols[fn]
            else:
                sym_match = next((k for k, v in symbols.items() if v == fn), None)
                if sym_match is not None:
                    fn_symbol = sym_match
                    fn_display_name = fn
                elif fn.startswith("_fn_"):
                    fn_symbol = fn
                    fn_display_name = fn
                else:
                    fn_symbol = None
                    fn_display_name = fn
        else:
            if fn.startswith("_fn_"):
                fn_symbol = fn
                fn_display_name = fn
            else:
                fn_symbol = None
                fn_display_name = fn

    return PillData(
        res_type=res_type,
        storage_id_hex=sid_hex,
        res_name=res_name,
        fn_symbol=fn_symbol,
        fn_display_name=fn_display_name,
        raw_ref=raw_ref,
    )


def get_available_function_pills(kernel: Any) -> list[PillData]:
    """Scan kernel resources for all Script resources and return PillData for each exported function."""
    if kernel is None or not hasattr(kernel, "resources"):
        return []

    results: list[PillData] = []
    for rid, res in list(kernel.resources.items()):
        if not isinstance(res, dict) or res.get("type") != Script:
            continue

        sid = None
        if hasattr(kernel, "get_storage_id"):
            sid = kernel.get_storage_id(rid)
        if sid is None and hasattr(kernel, "resource_storage_ids"):
            sid = kernel.resource_storage_ids.get(rid)

        sid_hex = sid.hex().lower() if isinstance(sid, (bytes, bytearray)) else ""
        if not sid_hex:
            continue

        res_name = res.get("name") or f"Script_{rid}"

        symbols: dict[str, str] = {}
        if hasattr(kernel, "get_script_proxy"):
            proxy = kernel.get_script_proxy(rid)
            if not isinstance(proxy, Error) and proxy is not None and hasattr(proxy, "symbols"):
                symbols = proxy.symbols

        if not symbols:
            s_data = res.get("data", {})
            if isinstance(s_data, dict):
                symbols = s_data.get("symbols", {})
                if not symbols and "code" in s_data:
                    symbols = extract_script_symbols(s_data["code"])

        for fn_sym, display_name in symbols.items():
            results.append(
                PillData(
                    res_type=Script,
                    storage_id_hex=sid_hex,
                    res_name=res_name,
                    fn_symbol=fn_sym,
                    fn_display_name=display_name,
                    raw_ref=f"<|1|{sid_hex}|>.{fn_sym}",
                )
            )

    return results


def rename_script_function_display_name(
    kernel: Any, sid_hex: str, fn_symbol: str, new_display_name: str
) -> None | Error:
    """Rename a function's human display name by updating the trailing comment on its definition line.

    Preserves durable identity (_fn_<id>) while updating human presentation.
    Mutates resource in kernel and writes to script file on disk if source_path exists.
    """
    if "\n" in new_display_name or "\r" in new_display_name:
        return Error(
            message="Invalid display name",
            description="Display name cannot contain newline characters",
            data={"new_display_name": new_display_name},
            code=InvalidResourceDataError,
        )

    clean_name = new_display_name.strip().lstrip("#").strip()
    if not clean_name:
        return Error(
            message="Invalid display name",
            description="Display name cannot be empty or only hash characters",
            data={"new_display_name": new_display_name},
            code=InvalidResourceDataError,
        )

    sid_hex_norm = sid_hex.strip().lower()
    try:
        sid_bytes = bytes.fromhex(sid_hex_norm)
    except ValueError:
        return Error(
            message="Invalid storage ID",
            description=f"Cannot parse hex storage ID '{sid_hex}'",
            data={"sid_hex": sid_hex},
            code=InvalidResourceDataError,
        )

    rid = None
    if hasattr(kernel, "get_resource_id"):
        candidate = kernel.get_resource_id(sid_bytes)
        if not isinstance(candidate, Error):
            rid = candidate

    if rid is None and hasattr(kernel, "resource_storage_ids"):
        for r_id, s_val in kernel.resource_storage_ids.items():
            if isinstance(s_val, (bytes, bytearray)) and s_val.hex().lower() == sid_hex_norm:
                rid = r_id
                break

    if rid is None or not hasattr(kernel, "resources") or rid not in kernel.resources:
        return Error(
            message="Resource not found",
            description=f"Script with storage ID '{sid_hex}' not found in kernel memory",
            data={"sid_hex": sid_hex},
            code=RuntimeIDNotFoundOnMemoryError,
        )

    res = kernel.resources[rid]
    if not isinstance(res, dict) or res.get("type") != Script:
        return Error(
            message="Resource is not a script",
            description=f"RuntimeID {rid} has type {res.get('type') if isinstance(res, dict) else type(res)}, expected Script ({Script})",
            data={"rid": rid},
            code=InvalidResourceDataError,
        )

    script_data = res.get("data", {})
    if not isinstance(script_data, dict):
        return Error(
            message="Invalid script payload",
            description=f"Script resource {rid} has invalid payload",
            data={"rid": rid},
            code=InvalidResourceDataError,
        )

    code = script_data.get("code", "")
    source_path = script_data.get("source_path", "")
    s_file: Path | None = None
    if source_path:
        p = Path(source_path)
        if not p.is_absolute() and hasattr(kernel, "folder_location"):
            p = kernel.folder_location / p
        s_file = p

    if not code and s_file is not None and s_file.exists():
        try:
            code = s_file.read_text(encoding="utf-8")
        except Exception as ex:
            return Error(
                message="File read error",
                description=f"Could not read source_path '{s_file}': {ex}",
                data={"s_file": str(s_file), "error": str(ex)},
                code=InvalidResourceDataError,
            )

    if not code:
        return Error(
            message="Empty script source",
            description=f"Script resource {rid} has no source code to rename",
            data={"rid": rid},
            code=InvalidResourceDataError,
        )

    prep_source = code
    if "<|" in code:
        try:
            prep_source, _ = ReferencePreprocessor.preprocess(code)
        except Exception:
            prep_source = code

    try:
        tree = ast.parse(prep_source)
    except SyntaxError as ex:
        return Error(
            message="Script syntax error",
            description=f"Cannot parse script for symbol renaming: {ex}",
            data={"error": str(ex)},
            code=InvalidResourceDataError,
        )

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(code).readline))
    except (SyntaxError, tokenize.TokenError) as ex:
        return Error(
            message="Script syntax error",
            description=f"Cannot tokenize script for symbol renaming: {ex}",
            data={"error": str(ex)},
            code=InvalidResourceDataError,
        )

    target_node = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn_symbol:
            target_node = node
            break

    if target_node is None:
        return Error(
            message="Symbol not found",
            description=f"Function definition '{fn_symbol}' was not found in script {rid}",
            data={"fn_symbol": fn_symbol, "rid": rid},
            code=InvalidResourceDataError,
        )

    tok_idx = 0
    num_tokens = len(tokens)
    while tok_idx < num_tokens:
        tok = tokens[tok_idx]
        if tok.type == tokenize.NAME and tok.string == target_node.name and tok.start[0] >= target_node.lineno:
            break
        tok_idx += 1

    depth = 0
    colon_line: int | None = None
    while tok_idx < num_tokens:
        tok = tokens[tok_idx]
        if tok.type == tokenize.OP and tok.string in ("(", "[", "{"):
            depth += 1
        elif tok.type == tokenize.OP and tok.string in (")", "]", "}"):
            depth -= 1
        elif depth == 0 and tok.type == tokenize.OP and tok.string == ":":
            colon_line = tok.start[0]
            break
        tok_idx += 1

    if colon_line is None:
        return Error(
            message="Header colon not found",
            description=f"Could not locate header colon for function '{fn_symbol}'",
            data={"fn_symbol": fn_symbol},
            code=InvalidResourceDataError,
        )

    comment_tok: tokenize.TokenInfo | None = None
    for tok in tokens:
        if tok.type == tokenize.COMMENT and tok.start[0] == colon_line:
            comment_tok = tok
            break

    code_lines = code.splitlines(keepends=True)
    line_idx = colon_line - 1
    if line_idx < 0 or line_idx >= len(code_lines):
        return Error(
            message="Line index out of bounds",
            description=f"Calculated colon line {colon_line} is outside source code line count ({len(code_lines)})",
            data={"colon_line": colon_line},
            code=InvalidResourceDataError,
        )

    orig_line = code_lines[line_idx]
    newline = ""
    if orig_line.endswith("\r\n"):
        newline = "\r\n"
        line_body = orig_line[:-2]
    elif orig_line.endswith("\n"):
        newline = "\n"
        line_body = orig_line[:-1]
    else:
        line_body = orig_line

    if comment_tok is not None:
        prefix = line_body[: comment_tok.start[1]].rstrip()
        new_line = f"{prefix} # {clean_name}{newline}"
    else:
        prefix = line_body.rstrip()
        new_line = f"{prefix} # {clean_name}{newline}"

    code_lines[line_idx] = new_line
    new_code = "".join(code_lines)

    prep_new = new_code
    if "<|" in new_code:
        try:
            prep_new, _ = ReferencePreprocessor.preprocess(new_code)
        except Exception as ex:
            return Error(
                message="Verification failed",
                description=f"Reference preprocessor failed after rename: {ex}",
                data={"error": str(ex)},
                code=InvalidResourceDataError,
            )

    try:
        new_tree = ast.parse(prep_new)
    except SyntaxError as ex:
        return Error(
            message="Verification failed",
            description=f"Mutated script failed syntax validation: {ex}",
            data={"error": str(ex)},
            code=InvalidResourceDataError,
        )

    fn_found = any(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn_symbol
        for n in new_tree.body
    )
    if not fn_found:
        return Error(
            message="Verification failed",
            description=f"Function definition for '{fn_symbol}' was corrupted during rename",
            data={"fn_symbol": fn_symbol},
            code=InvalidResourceDataError,
        )

    new_symbols = extract_script_symbols(new_code)
    if new_symbols.get(fn_symbol) != clean_name:
        return Error(
            message="Verification failed",
            description=f"Function '{fn_symbol}' display name extracted as '{new_symbols.get(fn_symbol)}', expected '{clean_name}'",
            data={"actual": new_symbols.get(fn_symbol), "expected": clean_name},
            code=InvalidResourceDataError,
        )

    mutated_data = dict(script_data)
    mutated_data["code"] = new_code
    mutated_data["symbols"] = new_symbols

    if s_file is not None and s_file.exists():
        try:
            s_file.write_text(new_code, encoding="utf-8")
        except Exception as ex:
            return Error(
                message="Failed to write script to disk",
                description=f"Could not write updated script to '{s_file}': {ex}",
                data={"s_file": str(s_file), "error": str(ex)},
                code=InvalidResourceDataError,
            )

    if hasattr(kernel, "mutate_resource"):
        mutate_err = kernel.mutate_resource(rid, mutated_data)
        if isinstance(mutate_err, Error):
            return mutate_err

    return None
