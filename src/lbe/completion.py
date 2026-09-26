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
        "from uuid import UUID as _UUID\n\n"
    )

    if not isinstance(context, dict):
        components = sorted(set(context))
        prelude += "class _Owner(_Entity):\n    pass\n"
        for name in components:
            if name.isidentifier() and not keyword.iskeyword(name):
                prelude += f"    {name}: object\n"
        prelude += (
            "entity: _Owner\n"
            "query = entity.query\n"
            "runtime = entity.runtime\n"
            "systems = entity.systems\n"
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
    entities_info = context.get('entities', {})
    all_comps = context.get('all_components', {})

    # 1. _GameEntity representing query child results with all known game components
    prelude += "class _GameEntity(_Entity):\n    pass\n"
    for name, type_name in sorted(all_comps.items()):
        if name.isidentifier() and not keyword.iskeyword(name):
            type_str = TYPE_MAP.get(type_name, 'object')
            prelude += f"    {name}: {type_str}\n"
    prelude += "\n"

    # 2. Specific classes for each named live game entity
    entity_class_names = {}
    for ent_name, ent_data in sorted(entities_info.items()):
        if ent_name.isidentifier() and not keyword.iskeyword(ent_name):
            cls_name = f"_Entity_{ent_name}"
            entity_class_names[ent_name] = cls_name
            prelude += f"class {cls_name}(_Entity):\n    pass\n"
            for c_name, c_type in sorted(ent_data.get('components', {}).items()):
                if c_name.isidentifier() and not keyword.iskeyword(c_name):
                    type_str = TYPE_MAP.get(c_type, 'object')
                    prelude += f"    {c_name}: {type_str}\n"
            prelude += "\n"

    # 3. Direct entity symbols and entities namespace container
    namespace_fields = []
    for ent_name, cls_name in entity_class_names.items():
        prelude += f"{ent_name}: {cls_name}\n"
        lower_name = ent_name.lower()
        if lower_name != ent_name and lower_name.isidentifier() and not keyword.iskeyword(lower_name):
            prelude += f"{lower_name}: {cls_name}\n"
        namespace_fields.append((ent_name, cls_name))
        if lower_name != ent_name and lower_name.isidentifier() and not keyword.iskeyword(lower_name):
            namespace_fields.append((lower_name, cls_name))

    prelude += "class _EntitiesNamespace:\n    pass\n"
    for f_name, cls_name in namespace_fields:
        prelude += f"    {f_name}: {cls_name}\n"
    prelude += "entities: _EntitiesNamespace\n\n"

    # 4. _OwnerEntity representing the owner/attached entity
    prelude += "class _OwnerEntity(_Entity):\n    pass\n"
    for name, type_name in sorted(owner_comps.items()):
        if name.isidentifier() and not keyword.iskeyword(name):
            type_str = TYPE_MAP.get(type_name, 'object')
            prelude += f"    {name}: {type_str}\n"
    prelude += "entity: _OwnerEntity\n\n"

    # 5. Injected services, functions, and standard update dt
    prelude += (
        "def query(*components: str) -> list[_GameEntity]: pass\n"
        "def resolve(name_or_uuid: str) -> _Entity: pass\n"
        "def create(parent: _Entity = None, tags: tuple = (), **components) -> _Entity: pass\n"
        "def destroy(entity: _Entity) -> None: pass\n"
        "runtime: _Runtime\n"
        "systems: dict\n"
        "events: object\n"
        "changes: object\n"
        "assets: object\n"
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
        if known_components:
            matches.sort(key=lambda m: (0 if m[0] in known_components else 1, m[0]))
    except Exception:
        matches = []
    return prefix, matches[:6]


def request_completion(source, cursor, path, context=()):
    """Serialize analysis off the render thread; callers discard stale results."""
    return _worker.submit(complete, source, cursor, path, context)
