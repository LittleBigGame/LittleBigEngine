from __future__ import annotations

import ast
import io
import re
import tokenize
import types
from types import MappingProxyType
from typing import TYPE_CHECKING, Any
import uuid

from .types import Error

if TYPE_CHECKING:
    from .kernel import Kernel


class LBEReferenceSyntaxError(SyntaxError):
    """Raised when an invalid or malformed LittleBigEngine resource reference is encountered."""


def _make_syntax_error(message: str, source: str, filename: str, pos: int) -> LBEReferenceSyntaxError:
    lineno = source[:pos].count("\n") + 1
    last_newline = source.rfind("\n", 0, pos)
    col_offset = pos + 1 if last_newline == -1 else pos - last_newline
    line_end = source.find("\n", pos)
    line_start = last_newline + 1 if last_newline != -1 else 0
    text = source[line_start:line_end] if line_end != -1 else source[line_start:]
    return LBEReferenceSyntaxError(message, (filename, lineno, col_offset, text))


_SCANNER_RE = re.compile(
    r'(?P<comment>#[^\r\n]*)'
    r'|(?P<triple_quote>(?:[rRuUbBfF]{0,2})'
    r'(?:"""(?:\\.|[^"\\]|"{1,2}(?!"))*"""'
    r"|'''(?:\\.|[^'\\]|'{1,2}(?!'))*'''))"
    r'|(?P<single_quote>(?:[rRuUbBfF]{0,2})'
    r'(?:"(?:\\.|[^"\\\r\n])*"'
    r"|'(?:\\.|[^'\\\r\n])*'))"
    r'|(?P<valid_lbe_ref><lbe\.ref\(\s*["\'](?P<lbe_storage_id>[0-9a-fA-F]+)["\'](?:\s*,\s*["\'](?P<lbe_alias>[^"\']*)["\'])?\s*\)>)'
    r'|(?P<malformed_lbe_ref><lbe\.ref\([^\r\n]*\)>|<lbe\.ref\([^\r\n]*)'
    r'|(?P<valid_ref><\|(?P<res_type>\d+)\|(?P<storage_id>[0-9a-fA-F]+)\|>)'
    r'|(?P<malformed><\|(?:.*?\|>|[^\r\n]*))'
)


class ReferencePreprocessor:
    """Preprocesses LittleBigEngine resource reference bracket syntax `<lbe.ref("...")>` and `<|type|storage_id|>`."""

    @staticmethod
    def preprocess(
        source: str,
        filename: str = "<lbe_source>",
    ) -> tuple[str, set[tuple[int, str]]]:
        dependencies: set[tuple[int, str]] = set()

        def _replace_token(match: re.Match) -> str:
            if match.group("comment") is not None:
                return match.group(0)
            if match.group("triple_quote") is not None:
                return match.group(0)
            if match.group("single_quote") is not None:
                return match.group(0)
            if match.group("malformed_lbe_ref") is not None:
                raise _make_syntax_error(
                    f"Malformed LittleBigEngine reference syntax: {match.group(0)!r}",
                    source,
                    filename,
                    match.start(),
                )
            if match.group("malformed") is not None:
                raise _make_syntax_error(
                    f"Malformed LittleBigEngine reference syntax: {match.group(0)!r}",
                    source,
                    filename,
                    match.start(),
                )
            if match.group("valid_lbe_ref") is not None:
                storage_id = match.group("lbe_storage_id")
                if len(storage_id) not in (32, 64):
                    raise _make_syntax_error(
                        f"Invalid reference storage ID length ({len(storage_id)} hex digits). Expected 32 or 64: {match.group(0)!r}",
                        source,
                        filename,
                        match.start(),
                    )
                storage_id_lower = storage_id.lower()
                dependencies.add((-1, storage_id_lower))
                return f'__lbe_resolve_ref__("{storage_id_lower}")'
            if match.group("valid_ref") is not None:
                storage_id = match.group("storage_id")
                if len(storage_id) not in (32, 64):
                    raise _make_syntax_error(
                        f"Invalid reference storage ID length ({len(storage_id)} hex digits). Expected 32 or 64: {match.group(0)!r}",
                        source,
                        filename,
                        match.start(),
                    )
                res_type = int(match.group("res_type"))
                storage_id_lower = storage_id.lower()
                dependencies.add((res_type, storage_id_lower))
                return f"_{res_type}_{storage_id_lower}"
            return match.group(0)

        transformed = _SCANNER_RE.sub(_replace_token, source)
        return transformed, dependencies


class RuntimeBinder:
    """Binds resolved engine references into module execution environments."""

    @staticmethod
    def bind_module(
        module: types.ModuleType,
        source: str,
        kernel: Kernel | Any,
        filename: str = "<lbe_module>",
    ) -> set[tuple[int, str]]:
        transformed_code, dependencies = ReferencePreprocessor.preprocess(source, filename=filename)

        def __lbe_resolve_ref__(ref_hex: str) -> Any:
            clean = ref_hex.replace("-", "").strip().lower()
            if hasattr(kernel, "resolve_reference"):
                ref = kernel.resolve_reference(clean)
                if not isinstance(ref, Error):
                    return ref
            if hasattr(kernel, "resolve_function_export"):
                res = kernel.resolve_function_export(clean)
                if not isinstance(res, Error):
                    return res[0]
            try:
                sid_bytes = bytes.fromhex(clean)
                rid = kernel.get_resource_id(sid_bytes)
                if isinstance(rid, Error):
                    rid = kernel.load_resource(sid_bytes)
                if not isinstance(rid, Error):
                    if kernel.is_entity(rid):
                        return kernel.get_entity_proxy(rid)
                    elif hasattr(kernel, "get_script_proxy"):
                        r_data = kernel.get_resource(rid)
                        if isinstance(r_data, (dict, MappingProxyType)) and r_data.get("type") == 1:
                            return kernel.get_script_proxy(rid)
                    return kernel.get_resource(rid)
            except Exception:
                pass
            raise SyntaxError(f"Cannot resolve LittleBigEngine reference '{clean}'")

        module.__dict__["__lbe_resolve_ref__"] = __lbe_resolve_ref__

        for res_type, storage_id_hex in dependencies:
            if res_type != -1:
                var_name = f"_{res_type}_{storage_id_hex}"
                proxy = kernel.resolve_proxy(res_type, storage_id_hex)
                if isinstance(proxy, Error):
                    raise proxy
                module.__dict__[var_name] = proxy

        compiled = compile(transformed_code, filename, "exec")
        exec(compiled, module.__dict__)
        return dependencies


def extract_script_symbols(source: str, existing_symbols: dict[str, str] | None = None) -> dict[str, str]:
    """Extract top-level _fn_ functions and their human-readable display names from trailing comments.

    Parses top-level FunctionDef and AsyncFunctionDef whose names start with '_fn_'.
    Uses tokenize to extract the trailing comment '# <human_name>' on the exact line where
    the function definition header colon ':' occurs.
    Strips '#' and whitespace from the comment.
    If no trailing comment, preserves existing_symbols mapping if available, or defaults to the symbol name itself ('_fn_<id>').
    Returns mapping: {"_fn_<id>": "<human_display_name>"}.
    """
    if not source or not source.strip():
        return {}

    prep_source = source
    if "<|" in source:
        try:
            prep_source, _ = ReferencePreprocessor.preprocess(source)
        except Exception:
            prep_source = source

    try:
        tree = ast.parse(prep_source)
        tokens = list(tokenize.generate_tokens(io.StringIO(prep_source).readline))
    except (SyntaxError, tokenize.TokenError):
        return {}

    comments_by_line: dict[int, str] = {
        tok.start[0]: tok.string
        for tok in tokens
        if tok.type == tokenize.COMMENT
    }

    symbols: dict[str, str] = {}
    existing = existing_symbols or {}
    tok_idx = 0
    num_tokens = len(tokens)

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        is_fn_prefixed = node.name.startswith("_fn_") or node.name.startswith("fn_")
        has_export_decorator = False
        export_uuid: str | None = None
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and getattr(dec.func, "id", "") == "export" and dec.args:
                has_export_decorator = True
                if isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                    export_uuid = dec.args[0].value

        if not is_fn_prefixed and not has_export_decorator:
            continue

        while tok_idx < num_tokens:
            tok = tokens[tok_idx]
            if tok.type == tokenize.NAME and tok.string == node.name and tok.start[0] >= node.lineno:
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

        display_name = node.name
        if colon_line is not None and colon_line in comments_by_line:
            cleaned = comments_by_line[colon_line].strip().strip("#").strip()
            if cleaned:
                display_name = cleaned
        elif existing:
            clean_uuid = node.name.removeprefix("fn_").removeprefix("_fn_")
            display_name = existing.get(node.name) or existing.get(clean_uuid.lower()) or node.name

        symbols[node.name] = display_name
        if export_uuid:
            symbols[export_uuid.lower()] = display_name

    return symbols


_REF_DISPLAY_RE = re.compile(
    r'<lbe\.ref\(\s*["\'](?P<sid>[0-9a-fA-F]{32,64})["\'](?:\s*,\s*["\'](?P<alias>[^"\']*)["\'])?\s*\)>'
)


def project_source_to_display(
    code: str,
    symbols: dict[str, str] | None = None,
    kernel: Any = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Transform on-disk pure UUID source into human-readable display code for the editor.

    Replaces:
    - `def fn_<32hex>(` -> `def <display_name>(`
    - `<lbe.ref("<32hex>")>` -> `<display_name>`
    Returns (display_code, tokens).
    """
    syms = symbols or {}
    tokens: list[dict[str, Any]] = []

    def _replace_fn_def(m: re.Match) -> str:
        fn_sym = m.group("fn_sym")
        display = syms.get(fn_sym)
        clean_uuid = fn_sym[3:] if fn_sym.startswith("fn_") else (fn_sym[4:] if fn_sym.startswith("_fn_") else fn_sym)
        if not display:
            display = syms.get(clean_uuid.lower(), fn_sym)
        tokens.append({
            "type": "function_def",
            "name": display,
            "uuid": clean_uuid.lower(),
            "symbol": fn_sym,
        })
        return f"{m.group('prefix')}{display}("

    # Replace function definitions
    fn_def_re = re.compile(r'(?P<prefix>(?:def|async\s+def)\s+)(?P<fn_sym>(?:_fn_|fn_)[0-9a-fA-F]{32,64})\s*\(')
    out = fn_def_re.sub(_replace_fn_def, code)

    # Replace <lbe.ref("...")>
    def _replace_ref(m: re.Match) -> str:
        sid = m.group("sid").lower()
        alias = m.group("alias")
        display = alias
        if not display and kernel is not None:
            try:
                sid_bytes = bytes.fromhex(sid)
                if hasattr(kernel, "get_resource_id"):
                    rid = kernel.get_resource_id(sid_bytes)
                    if not isinstance(rid, Error) and hasattr(kernel, "get_resource"):
                        res = kernel.get_resource(rid)
                        if isinstance(res, (dict, MappingProxyType)) and res.get("name"):
                            display = res["name"]
            except Exception:
                pass
        if not display:
            display = syms.get(sid, f"Ref_{sid[:8]}")

        tokens.append({
            "type": "ref",
            "name": display,
            "uuid": sid,
            "raw": m.group(0),
        })
        return display

    out = _REF_DISPLAY_RE.sub(_replace_ref, out)
    return out, tokens


def project_display_to_source_with_symbols(
    display_code: str,
    symbols: dict[str, str] | None = None,
    kernel: Any = None,
) -> tuple[str, dict[str, str]]:
    """Transform human-readable display code back to persistent on-disk UUID source.

    Maintains existing stable UUIDs for known functions, allocates fresh 32-hex UUIDs
    for newly defined functions, updates the symbols dictionary, and maps entity references.
    Returns (disk_source_code, updated_symbols).
    """
    syms = dict(symbols) if symbols else {}
    inv: dict[str, str] = {}
    for sym_key, disp_name in syms.items():
        if disp_name and (sym_key.startswith("fn_") or sym_key.startswith("_fn_")):
            inv[disp_name] = sym_key

    # Discover newly defined functions via AST and allocate UUIDs
    try:
        tree = ast.parse(display_code)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name not in inv and not node.name.startswith(("fn_", "_fn_")):
                    new_uuid = uuid.uuid4().hex
                    sym_key = f"fn_{new_uuid}"
                    syms[sym_key] = node.name
                    syms[new_uuid] = node.name
                    inv[node.name] = sym_key
    except SyntaxError:
        pass

    out = display_code
    for disp_name, sym_key in inv.items():
        pat = re.compile(rf'(def|async\s+def)\s+{re.escape(disp_name)}\s*\(')
        out = pat.sub(rf'\1 {sym_key}(', out)

    # Map known entity references to <lbe.ref("sid", "name")>
    if kernel is not None and hasattr(kernel, "resources"):
        from collections.abc import Mapping
        entity_name_map: dict[str, str] = {}
        for rid, r in list(kernel.resources.items()):
            if isinstance(r, (dict, Mapping)) and hasattr(kernel, "is_entity") and kernel.is_entity(rid):
                ename = r.get("name")
                if ename and ename.isidentifier():
                    sid = kernel.get_storage_id(rid)
                    if hasattr(sid, "hex"):
                        entity_name_map[ename] = sid.hex().lower()

        for ename, esid in entity_name_map.items():
            # Match assignments like: target = Entity2 or target = Entity2\n
            ref_assign_pat = re.compile(rf'(=\s*){re.escape(ename)}(\s*(?:#.*)?$)')
            out = ref_assign_pat.sub(rf'\1<lbe.ref("{esid}", "{ename}")>\2', out)

    if symbols is not None:
        symbols.update(syms)

    return out, syms


def project_display_to_source(
    display_code: str,
    symbols: dict[str, str] | None = None,
    kernel: Any = None,
) -> str:
    """Transform human-readable display code back to persistent on-disk UUID source."""
    out, _ = project_display_to_source_with_symbols(display_code, symbols=symbols, kernel=kernel)
    return out

