"""Asset registry, stable UUID handles, and asset reference primitives."""

from dataclasses import dataclass
import os
import ast
from functools import lru_cache
from pathlib import Path
import uuid
from uuid import UUID

ASSET_EXTENSIONS = {
    ".py": "system",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".bmp": "image",
    ".gif": "image",
    ".wav": "audio",
    ".ogg": "audio",
    ".mp3": "audio",
    ".json": "data",
    ".txt": "text",
}

ASSET_ICONS = {
    "system": "⚡",
    "script": "⚡",
    "image": "🖼️",
    "audio": "🔊",
    "data": "📄",
    "text": "📝",
    "folder": "📁",
    "asset": "📦",
}


@lru_cache(maxsize=512)
def _source_functions(path, modified, size):
    """Inspect declarations without executing source; stat keys invalidate edits."""
    try:
        from .references import lower_references
        body = ast.parse(lower_references(Path(path).read_text(encoding="utf-8-sig"), path)[0]).body
    except (OSError, SyntaxError, UnicodeError):
        return None
    return frozenset(node.name for node in body if isinstance(node, ast.FunctionDef))


def source_functions(path):
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return None
    return _source_functions(str(path.resolve()), stat.st_mtime_ns, stat.st_size)


def asset_icon(path, asset_type=None):
    """Code badges identify available entry points, including mixed capabilities."""
    path = Path(path)
    if path.suffix.lower() != '.py':
        return ASSET_ICONS.get(asset_type or ASSET_EXTENSIONS.get(path.suffix.lower()), '📦')
    functions = source_functions(path)
    if functions is None:
        return '{?}'
    marks = ''.join(symbol for name, symbol in (('run', '▶'), ('update', '↻'), ('draw', '◇')) if name in functions)
    return '{' + ('*' if marks == '▶↻◇' else marks or '·') + '}'


@dataclass(frozen=True)
class AssetRef:
    """A first-class reference to a project asset by its persistent UUID."""
    id: UUID
    type: str = "asset"
    name: str = ""

    def __post_init__(self):
        if isinstance(self.id, str):
            object.__setattr__(self, "id", UUID(self.id))

    def __str__(self):
        return f"AssetRef({self.name or self.id})"

    def __repr__(self):
        return f"AssetRef(id={self.id!r}, type={self.type!r}, name={self.name!r})"


class AssetRegistry:
    """Persistent UUID mappings. Paths are canonical and entry snapshots are read-only to callers."""

    def __init__(self, project_dir=None):
        self.project_dir = Path(project_dir).resolve() if project_dir else None
        self._entries = {}
        self._path_to_id = {}
        self.revision = 0

    def _relative(self, path):
        path = Path(path)
        if self.project_dir is not None:
            absolute = path.resolve() if path.is_absolute() else (self.project_dir / path).resolve()
            if not absolute.is_relative_to(self.project_dir):
                raise ValueError("Asset path must be inside the project")
            path = absolute.relative_to(self.project_dir)
        if path.is_absolute() or ".." in path.parts or str(path) in ("", "."):
            raise ValueError("Expected a project-relative asset path")
        return path.as_posix()

    @staticmethod
    def _key(path):
        return os.path.normcase(path).replace("\\", "/")

    def clear(self):
        self._entries.clear()
        self._path_to_id.clear()
        self.revision += 1

    @staticmethod
    def infer_type(path):
        path=Path(path)
        if path.suffix.lower()=='.py' and 'run' in (source_functions(path) or ()):
            return 'script'
        return ASSET_EXTENSIONS.get(path.suffix.lower(), "asset")

    def icon(self, asset_id):
        entry = self.get(asset_id)
        if entry is None:
            return '📦'
        path = self.project_dir / entry['path'] if self.project_dir else entry['path']
        return asset_icon(path, entry['type'])

    def entries(self):
        return tuple((uid, dict(entry)) for uid, entry in self._entries.items())

    def register(self, path, asset_type=None, asset_id=None, name=None):
        relative = self._relative(path)
        key = self._key(relative)
        existing = self._path_to_id.get(key)
        uid = UUID(str(asset_id)) if asset_id is not None else existing or uuid.uuid5(uuid.NAMESPACE_URL, f"lbe://{key}")
        if uid in self._entries and self._key(self._entries[uid]["path"]) != key:
            if asset_id is not None:
                raise ValueError(f"Asset identity {uid} already belongs to another path")
            # A renamed asset retains its UUID. Recreating its former path is a
            # new asset, even though the deterministic path UUID is still owned.
            uid = uuid.uuid4()
            while uid in self._entries:
                uid = uuid.uuid4()
        previous = self._entries.get(existing, {})
        entry = {"path": relative, "type": asset_type or previous.get("type", self.infer_type(self.project_dir / relative if self.project_dir else relative)),
                 "name": name or previous.get("name", Path(relative).name)}
        if existing is not None and existing != uid:
            self._entries.pop(existing)
        changed = self._entries.get(uid) != entry or existing != uid
        self._entries[uid] = entry
        self._path_to_id[key] = uid
        self.revision += bool(changed)
        return uid

    def rename(self, asset_id, new_path):
        uid = UUID(str(asset_id))
        if uid not in self._entries:
            return False
        relative = self._relative(new_path)
        collision = self._path_to_id.get(self._key(relative))
        if collision is not None and collision != uid:
            raise ValueError(f"Asset destination already registered: {relative}")
        previous = self._entries[uid]
        self._path_to_id.pop(self._key(previous["path"]))
        self._entries[uid] = dict(previous, path=relative, name=Path(relative).name, type=self.infer_type(self.project_dir / relative if self.project_dir else relative))
        self._path_to_id[self._key(relative)] = uid
        self.revision += 1
        return True

    def relocate(self, old_path, new_path):
        """Rename a file or directory subtree as one validated registry update."""
        old, new = Path(self._relative(old_path)), Path(self._relative(new_path))
        entries = self.to_dict()
        for uid, entry in entries.items():
            path = Path(entry["path"])
            if path == old or path.is_relative_to(old):
                destination = new / path.relative_to(old) if path != old else new
                entries[uid] = dict(entry, path=destination.as_posix(), name=destination.name)
        candidate = AssetRegistry(self.project_dir)
        candidate.from_dict(entries)
        self.from_dict(candidate.to_dict())

    def unregister(self, asset_id):
        entry = self._entries.pop(UUID(str(asset_id)), None)
        if entry is None:
            return False
        self._path_to_id.pop(self._key(entry["path"]))
        self.revision += 1
        return True

    def get(self, asset_id):
        entry = self._entries.get(UUID(str(asset_id)))
        return dict(entry) if entry is not None else None

    def get_id(self, path):
        return self._path_to_id.get(self._key(self._relative(path)))

    def get_ref(self, path_or_id):
        try:
            uid = UUID(str(path_or_id))
        except ValueError:
            uid = self.get_id(path_or_id)
        entry = self._entries.get(uid)
        return AssetRef(uid, entry["type"], entry["name"]) if entry else None

    def get_path(self, asset_id):
        entry = self._entries.get(UUID(str(asset_id)))
        return (self.project_dir / entry["path"]).resolve() if entry and self.project_dir else None

    def scan(self, project_dir=None):
        directory = Path(project_dir).resolve() if project_dir else self.project_dir
        if directory is None or not directory.exists():
            return
        self.project_dir = directory
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "venv", ".venv")]
            for name in files:
                if not name.startswith(".") and name != "project.json" and not name.endswith(".tmp"):
                    self.register(Path(root) / name)

    def to_dict(self):
        return {str(uid): dict(entry) for uid, entry in self._entries.items()}

    def from_dict(self, data):
        if not isinstance(data, dict):
            raise ValueError("Asset registry must be an object")
        candidate = AssetRegistry(self.project_dir)
        for identity, entry in data.items():
            if not isinstance(entry, dict):
                raise ValueError("Asset entry must be an object")
            path = candidate._relative(entry["path"])
            if candidate._key(path) in candidate._path_to_id:
                raise ValueError(f"Duplicate asset path: {path}")
            candidate.register(path, asset_id=identity, asset_type=entry.get("type"), name=entry.get("name"))
        self._entries = candidate._entries
        self._path_to_id = candidate._path_to_id
        self.revision += 1
