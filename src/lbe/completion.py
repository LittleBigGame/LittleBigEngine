"""Optional static Python completion, independent of editor controls and Core."""

from concurrent.futures import ThreadPoolExecutor
import io
import keyword
from pathlib import Path
import re
import tokenize

_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lbe-completion")

TYPE_MAP = {
    'int': 'int',
    'float': 'float',
    'str': 'str',
    'bool': 'bool',
    'tuple': 'tuple',
    'list': 'list',
    'dict': 'dict',
    'set': 'set',
}


def code_context(source, cursor):
    """Exclude comments and string contents, including incomplete strings."""
    prefix = source[:cursor]
    position = (prefix.count("\n") + 1, len(prefix.rsplit("\n", 1)[-1]))
    try:
        for token in tokenize.generate_tokens(io.StringIO(prefix).readline):
            if token.type in (tokenize.STRING, tokenize.COMMENT) and token.start < position <= token.end:
                return False
            if token.type == tokenize.ERRORTOKEN and token.string in ("'", '"'):
                return False
    except tokenize.TokenError as error:
        if "string" in str(error):
            return False
    return True


def build_prelude(context=()):
    """Generate static Python typing declarations modeling the live game environment."""
    prelude = (
        "from lbe import Entity as _Entity\n"
        "from lbe.core import Runtime as _Runtime\n"
        "from lbe.desktop import Graphics as _Graphics, Input as _Input\n"
        "from lbe.space import SpatialIndex as _Space\n"
        "from pathlib import Path as _Path\n"
        "from uuid import UUID as _UUID\n"
        "from lbe.systems import Assets as _Assets, Systems as _Systems\n\n"
        "from typing import Iterable as _Iterable\n\n"
    )

    if not isinstance(context, dict):
        components = sorted(set(context))
        prelude += "class _Owner(_Entity):\n    pass\n"
        for name in components:
            if name.isidentifier() and not keyword.iskeyword(name):
                prelude += f"    {name}: object\n"
        # Provide standard components on _Owner for self completion if not explicitly provided
        for name in ("name", "x", "y", "w", "h", "vx", "vy", "color"):
            if name not in components:
                prelude += f"    {name}: object\n"
        prelude += (
            "self: _Owner\n"
            "entity: _Owner\n"
            "query = self.query\n"
            "runtime = self.runtime\n"
            "systems = self.systems\n"
            "create = runtime.create\n"
            "resolve = runtime.resolve\n"
            "destroy = runtime.destroy\n"
            "events = runtime.events\n"
            "changes = runtime.changes\n"
            "assets = runtime.assets\n"
            "graphics: _Graphics\n"
            "input: _Input\n"
            "space: _Space\n"
            "project: _Path\n"
            "dt: float\n"
        )
        return prelude

    owner_info = context.get('owner', {})
    owner_comps = owner_info.get('components', {})
    all_comps = context.get('all_components', {})

    # Query results expose known project components for static suggestions.
    prelude += "class _GameEntity(_Entity):\n    pass\n"
    for name, type_name in sorted(all_comps.items()):
        if name.isidentifier() and not keyword.iskeyword(name):
            type_str = TYPE_MAP.get(type_name, 'object')
            prelude += f"    {name}: {type_str}\n"
    prelude += "\n"

    # The attached owner has its own component schema.
    prelude += "class _OwnerEntity(_Entity):\n    pass\n"
    for name, type_name in sorted(owner_comps.items()):
        if name.isidentifier() and not keyword.iskeyword(name):
            type_str = TYPE_MAP.get(type_name, 'object')
            prelude += f"    {name}: {type_str}\n"
    prelude += "self: _OwnerEntity\n"
    prelude += "entity: _OwnerEntity\n\n"

    # Runtime resolution yields an entity; known project components refine its static view.
    prelude += (
        "def resolve(name_or_uuid: str | _UUID) -> _GameEntity: pass\n"
        "def query(*components: str, tags=()) -> _Iterable[_GameEntity]: pass\n"
    )
    prelude += (
        "runtime: _Runtime\n"
        "systems: _Systems\n"
        "create = runtime.create\n"
        "destroy = runtime.destroy\n"
        "events = runtime.events\n"
        "changes = runtime.changes\n"
        "assets: _Assets\n"
        "asset = assets.resolve\n"
        "graphics: _Graphics\n"
        "input: _Input\n"
        "space: _Space\n"
        "project: _Path\n"
        "dt: float\n"
    )
    return prelude


def complete(source, cursor, path, context=()):
    """Return prefix and (name, kind) pairs using source/import inference.

    Context provides runtime entity, component, and game state from the running game.
    The synthetic declarations are analyzed only; neither they nor source execute.
    """
    import jedi

    if not code_context(source, cursor):
        return "", []
    prefix_match = re.search(r"[A-Za-z_]\w*$", source[:cursor])
    prefix = prefix_match.group() if prefix_match else ""
    prelude = build_prelude(context)
    from .references import lower_references
    try:
        source, references = lower_references(source, str(path))
        prelude += 'from lbe.references import LinkedReference as _LinkedReference\n'
        for reference in references:
            reference_type = '_Entity' if reference.kind == 'Entity' else '_LinkedReference'
            prelude += f'{reference.symbol}: {reference_type}\n'
    except SyntaxError:
        pass
    path = Path(path).resolve()
    project = jedi.Project(path.parent, added_sys_path=[str(Path(__file__).parent.parent)])
    script = jedi.Script(prelude + source, path=path, project=project)
    line = prelude.count("\n") + source[:cursor].count("\n") + 1
    column = len(source[:cursor].rsplit("\n", 1)[-1])
    try:
        raw_matches = script.complete(line, column)
        matches = [(c.name, c.type) for c in raw_matches
                   if c.name != prefix and (not c.name.startswith("_") or prefix.startswith("_"))]
        known_components = set()
        if isinstance(context, dict):
            known_components.update(context.get("all_components", {}).keys())
            known_components.update(context.get("owner", {}).get("components", {}).keys())
        elif hasattr(context, "__iter__"):
            known_components.update(context)
        if not known_components:
            known_components.update({"x", "y", "vx", "vy", "w", "h", "color", "name", "self", "query", "space", "dt"})
        if known_components:
            matches.sort(key=lambda m: (0 if m[0] in known_components else 1, m[0]))
    except Exception:
        matches = []
    return prefix, matches[:100]


def request_completion(source, cursor, path, context=()):
    """Serialize analysis off the render thread; callers discard stale results."""
    return _worker.submit(complete, source, cursor, path, context)


def hover_info(source, line, column, path, context=()):
    """Return hover inspection dict for symbol at 0-indexed (line, column).

    Returns None if no symbol or doc found, or a dict:
    {
        "name": str,
        "type": str,
        "description": str,
        "docstring": str,
        "line": int,
        "column": int,
    }
    """
    import jedi

    prelude = build_prelude(context)
    path = Path(path).resolve()
    project = jedi.Project(path.parent, added_sys_path=[str(Path(__file__).parent.parent)])
    script = jedi.Script(prelude + source, path=path, project=project)
    jedi_line = prelude.count("\n") + line + 1
    jedi_column = column
    try:
        definitions = script.help(jedi_line, jedi_column)
        if not definitions:
            definitions = script.infer(jedi_line, jedi_column)
        if not definitions:
            return None
        d = definitions[0]
        desc = getattr(d, "description", "") or f"{d.type} {d.name}"

        # Extract signatures from Jedi (via get_signatures or signatures attribute)
        sig_strs = []
        if hasattr(d, "get_signatures") and callable(d.get_signatures):
            try:
                sig_strs = [s.to_string() for s in d.get_signatures() if hasattr(s, "to_string")]
            except Exception:
                sig_strs = []
        elif hasattr(d, "signatures"):
            s_attr = getattr(d, "signatures")
            sig_list = s_attr() if callable(s_attr) else s_attr
            sig_strs = [s.to_string() for s in (sig_list or []) if hasattr(s, "to_string")]

        raw_doc = d.docstring(raw=True) or d.docstring() or ""

        # Extract docstring signatures and clean description body
        doc_lines = [l.strip() for l in raw_doc.splitlines()]
        doc_signatures = []
        doc_body = []
        past_sig = False
        for l in doc_lines:
            if not l:
                if doc_signatures:
                    past_sig = True
                continue
            if not past_sig and (l.startswith(f"{d.name}(") or " -> " in l):
                doc_signatures.append(l)
                continue
            past_sig = True
            doc_body.append(l)

        all_sigs = doc_signatures or sig_strs
        if all_sigs:
            desc = f"{d.type} {all_sigs[0]}"

        cleaned_doc = "\n".join(doc_body).strip()
        if not cleaned_doc and raw_doc:
            cleaned_doc = raw_doc.strip()

        return {
            "name": d.name,
            "type": d.type,
            "description": desc,
            "signatures": all_sigs,
            "docstring": cleaned_doc,
            "line": line,
            "column": column,
        }
    except Exception:
        return None


def request_hover(source, line, column, path, context=()):
    """Serialize hover analysis off the render thread."""
    return _worker.submit(hover_info, source, line, column, path, context)
