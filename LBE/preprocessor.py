from __future__ import annotations

import ast
import io
import re
import tokenize
import types
from typing import TYPE_CHECKING, Any

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
    r'|(?P<valid_ref><\|(?P<res_type>\d+)\|(?P<storage_id>[0-9a-fA-F]+)\|>)'
    r'|(?P<malformed><\|(?:.*?\|>|[^\r\n]*))'
)


class ReferencePreprocessor:
    """Preprocesses LittleBigEngine resource reference bracket syntax `<|type|storage_id|>`."""

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
            if match.group("malformed") is not None:
                raise _make_syntax_error(
                    f"Malformed LittleBigEngine reference syntax: {match.group(0)!r}",
                    source,
                    filename,
                    match.start(),
                )
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
        for res_type, storage_id_hex in dependencies:
            var_name = f"_{res_type}_{storage_id_hex}"
            proxy = kernel.resolve_proxy(res_type, storage_id_hex)
            if isinstance(proxy, Error):
                raise proxy
            module.__dict__[var_name] = proxy

        compiled = compile(transformed_code, filename, "exec")
        exec(compiled, module.__dict__)
        return dependencies


def extract_script_symbols(source: str) -> dict[str, str]:
    """Extract top-level _fn_ functions and their human-readable display names from trailing comments.

    Parses top-level FunctionDef and AsyncFunctionDef whose names start with '_fn_'.
    Uses tokenize to extract the trailing comment '# <human_name>' on the exact line where
    the function definition header colon ':' occurs.
    Strips '#' and whitespace from the comment.
    If no trailing comment, defaults to the symbol name itself ('_fn_<id>').
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
    tok_idx = 0
    num_tokens = len(tokens)

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("_fn_"):
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

        symbols[node.name] = display_name

    return symbols
