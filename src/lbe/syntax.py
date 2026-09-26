"""Python syntax tokenization and styling for code editing controls."""

import builtins
import keyword
import re

SYNTAX_THEME = {
    "keyword": (255, 123, 114),      # Coral red
    "builtin": (210, 168, 255),      # Light purple
    "literal": (121, 192, 255),      # Soft cyan (True, False, None)
    "string": (165, 214, 255),       # Soft blue
    "comment": (139, 148, 158),      # Muted grey
    "number": (255, 166, 87),        # Warm orange
    "definition": (220, 180, 255),   # Function/class definitions
    "decorator": (210, 168, 255),    # Decorators
    "operator": (255, 123, 114),     # Operators
    "punctuation": (180, 190, 205),  # Delimiters
    "default": (220, 224, 232),      # INK
}

KEYWORDS = set(keyword.kwlist)
BUILTINS = set(dir(builtins)) | {"self", "entity", "dt", "runtime"}
LITERALS = {"True", "False", "None"}

TOKEN_RE = re.compile(
    r'(?P<comment>#.*$)'
    r'|(?P<triple>[brufBRUF]*(?:"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'))'
    r'|(?P<unclosed_triple>[brufBRUF]*(?:"""|\'\'\'))'
    r'|(?P<string>[brufBRUF]*(?:\'(?:\\.|[^\'\\\n])*\'|"(?:\\.|[^"\\\n])*"))'
    r'|(?P<decorator>@[a-zA-Z_]\w*)'
    r'|(?P<number>\b(?:0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\b)'
    r'|(?P<ident>[a-zA-Z_]\w*)'
    r'|(?P<operator>==|!=|<=|>=|\+=|-=|\*=|/=|//=|%=|\*\*=|->|[+\-*/%&|^~<>=!])'
    r'|(?P<punct>[()[\]{},:;.])'
    r'|(?P<space>\s+)'
    r'|(?P<other>.)'
)


def highlight_python_lines(text, theme=SYNTAX_THEME):
    """Tokenize Python source text and return a list of styled spans per line.

    Each line's spans is a list of (text_chunk, color_tuple).
    """
    lines = text.split("\n")
    result = []
    in_triple = None  # None, '"""', or "'''"

    for line in lines:
        spans = []
        if not line:
            result.append(spans)
            continue

        idx = 0
        if in_triple:
            close_idx = line.find(in_triple)
            if close_idx == -1:
                result.append([(line, theme["string"])])
                continue
            else:
                end_quote = close_idx + len(in_triple)
                spans.append((line[:end_quote], theme["string"]))
                idx = end_quote
                in_triple = None

        prev_token_type = None
        for m in TOKEN_RE.finditer(line, idx):
            kind = m.lastgroup
            val = m.group(0)

            if kind == "comment":
                spans.append((val, theme["comment"]))
            elif kind == "triple":
                spans.append((val, theme["string"]))
            elif kind == "unclosed_triple":
                spans.append((line[m.start():], theme["string"]))
                in_triple = '"""' if '"""' in val else "'''"
                break
            elif kind == "string":
                spans.append((val, theme["string"]))
            elif kind == "decorator":
                spans.append((val, theme["decorator"]))
            elif kind == "number":
                spans.append((val, theme["number"]))
            elif kind == "ident":
                if prev_token_type in ("def", "class"):
                    spans.append((val, theme["definition"]))
                elif val in LITERALS:
                    spans.append((val, theme["literal"]))
                elif val in KEYWORDS:
                    spans.append((val, theme["keyword"]))
                    if val in ("def", "class"):
                        prev_token_type = val
                        continue
                elif val in BUILTINS:
                    spans.append((val, theme["builtin"]))
                else:
                    spans.append((val, theme["default"]))
            elif kind == "operator":
                spans.append((val, theme["operator"]))
            elif kind == "punct":
                spans.append((val, theme["punctuation"]))
            else:
                spans.append((val, theme["default"]))

            if kind not in ("space", "comment"):
                prev_token_type = kind

        # Merge adjacent spans with identical colors
        merged = []
        for chunk, color in spans:
            if merged and merged[-1][1] == color:
                merged[-1] = (merged[-1][0] + chunk, color)
            else:
                merged.append((chunk, color))

        result.append(merged)

    return result


def slice_spans(spans, start_col, max_cols):
    """Slice line spans to horizontal viewport window [start_col : start_col + max_cols]."""
    if not spans or max_cols <= 0:
        return []
    result = []
    current_col = 0
    for text, color in spans:
        span_len = len(text)
        span_end = current_col + span_len
        if span_end <= start_col:
            current_col = span_end
            continue
        if current_col >= start_col + max_cols:
            break
        take_start = max(0, start_col - current_col)
        take_end = min(span_len, start_col + max_cols - current_col)
        chunk = text[take_start:take_end]
        if chunk:
            result.append((chunk, color))
        current_col = span_end
    return result
