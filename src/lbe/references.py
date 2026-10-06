"""Lexical persistent source references, kept out of strings and comments."""
import io
import re
import tokenize
from dataclasses import dataclass
from uuid import UUID


REFERENCE_PATTERN = re.compile(r"<\|(Entity|Component|System|Script|Relation|Tag|Asset):([0-9a-fA-F-]{36})\|>")


@dataclass(frozen=True)
class SourceReference:
    kind: str
    id: UUID
    start: int
    end: int
    symbol: str


def code_mask(source):
    """Equal-length lexical mask. References are not valid Python until lowered."""
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    mask = list(source)
    string_start = None
    string_depth = 0
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in (getattr(tokenize, "FSTRING_START", -1), getattr(tokenize, "TSTRING_START", -2)):
                if string_depth == 0:
                    string_start = offsets[token.start[0] - 1] + token.start[1]
                string_depth += 1
            elif token.type in (getattr(tokenize, "FSTRING_END", -1), getattr(tokenize, "TSTRING_END", -2)):
                string_depth -= 1
                if string_depth == 0:
                    end = offsets[token.end[0] - 1] + token.end[1]
                    mask[string_start:end] = ["\n" if c == "\n" else " " for c in source[string_start:end]]
            if token.type in (tokenize.STRING, tokenize.COMMENT):
                start = offsets[token.start[0] - 1] + token.start[1]
                end = offsets[token.end[0] - 1] + token.end[1]
                mask[start:end] = ["\n" if c == "\n" else " " for c in source[start:end]]
    except tokenize.TokenError as error:
        # An unfinished triple string in an editor is still not code.
        if "multi-line string" in str(error):
            row, column = error.args[1]
            start = offsets[row - 1] + column
            mask[start:] = ["\n" if c == "\n" else " " for c in source[start:]]
    except IndentationError:
        pass  # compile remains responsible for the actual syntax diagnostic
    return "".join(mask)


def source_references(source, *, strict=False, path="<system>"):
    mask = code_mask(source)
    prefix = "_lbe_ref_"
    while prefix in source:
        prefix = "_" + prefix
    references = []
    cursor = 0
    while True:
        start = mask.find("<|", cursor)
        if start == -1:
            break
        match = REFERENCE_PATTERN.match(mask, start)
        try:
            if match is None:
                raise ValueError("Expected <|Type:uuid|> persistent reference")
            identity = UUID(match.group(2))
        except ValueError as error:
            if strict:
                row = source.count("\n", 0, start) + 1
                column = start - source.rfind("\n", 0, start)
                raise SyntaxError(str(error), (path, row, column, source.splitlines()[row - 1])) from None
            cursor = start + 2
            continue
        references.append(SourceReference(match.group(1), identity, start, match.end(), f"{prefix}{len(references)}"))
        cursor = match.end()
    return tuple(references)


def lower_references(source, path="<system>"):
    references = source_references(source, strict=True, path=path)
    lowered = list(source)
    for reference in references:
        width = reference.end - reference.start
        lowered[reference.start:reference.end] = list(reference.symbol.ljust(width))
    return "".join(lowered), references


class LinkedReference:
    """Persistent binding that follows component edits and behavior reloads."""
    def __init__(self, linker, identity, expected):
        self.linker, self.id, self.expected = linker, identity, expected

    def resolve(self):
        return self.linker.resolve(self.id, self.expected)

    @property
    def value(self):
        return self.linker.component_value(self.id)

    def __getattr__(self, name):
        return getattr(self.resolve(), name)


def bind_reference(runtime, reference):
    from .core import Entity
    from .items import Component, InheritedComponent, Relation, Tag
    from .systems import SystemInstance
    from .scripts import ScriptInstance
    if reference.kind == "Asset":
        return runtime.assets.resolve(reference.id)
    expected = {"Entity": Entity, "Component": (Component, InheritedComponent),
                "Relation": Relation, "Tag": Tag, "System": SystemInstance,
                "Script": ScriptInstance}[reference.kind]
    runtime.linker.resolve(reference.id, expected)
    if reference.kind == "Entity":
        return runtime.resolve(reference.id)
    return LinkedReference(runtime.linker, reference.id, expected)


def reference_label(runtime, kind, identity):
    """Friendly editor label and validity, without altering persisted source."""
    from .core import Entity
    try:
        if kind == "Asset":
            registry = runtime.assets.registry
            entry = registry.get(identity) if registry else None
            if not entry:
                raise KeyError(identity)
            return f"Asset: {entry['name']}", True
        expected = source_references(f"<|{kind}:{identity}|>", strict=True)[0]
        bind_reference(runtime, expected)
        item = runtime.linker.resolve(identity)
        name = item.items.get_value("name", "Entity") if isinstance(item, Entity) else item.name
        return f"{kind}: {name}", True
    except (KeyError, ValueError, TypeError, FileNotFoundError):
        return f"Missing {kind}: {str(identity)[:8]}", False
