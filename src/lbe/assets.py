"""Asset registry, stable UUID handles, and asset reference primitives."""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Dict, Optional, Tuple, Union
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
    "image": "🖼️",
    "audio": "🔊",
    "data": "📄",
    "text": "📝",
    "folder": "📁",
    "asset": "📦",
}


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
    """Manages persistent UUID-to-path mappings for all project resources."""

    def __init__(self, project_dir: Optional[Union[str, Path]] = None):
        self.project_dir = Path(project_dir).resolve() if project_dir else None
        # UUID -> dict(path=relative_path_str, type=str, name=str)
        self._entries: Dict[UUID, dict] = {}
        # normalized relative path str -> UUID
        self._path_to_id: Dict[str, UUID] = {}

    def clear(self):
        self._entries.clear()
        self._path_to_id.clear()

    @staticmethod
    def infer_type(path: Union[str, Path]) -> str:
        ext = Path(path).suffix.lower()
        return ASSET_EXTENSIONS.get(ext, "asset")

    def register(self, path: Union[str, Path], asset_type: Optional[str] = None,
                 asset_id: Optional[Union[str, UUID]] = None, name: Optional[str] = None) -> UUID:
        """Register a project asset with a persistent UUID."""
        path_obj = Path(path)
        if self.project_dir and path_obj.is_absolute():
            try:
                rel_path = str(path_obj.resolve().relative_to(self.project_dir)).replace("\\", "/")
            except ValueError:
                try:
                    rel_path = str(path_obj.relative_to(self.project_dir)).replace("\\", "/")
                except ValueError:
                    rel_path = path_obj.name
        else:
            rel_path = str(path_obj).replace("\\", "/")

        norm_rel = rel_path.lower()
        if norm_rel in self._path_to_id:
            existing_id = self._path_to_id[norm_rel]
            if asset_id is not None and UUID(str(asset_id)) != existing_id:
                # Update ID if explicitly requested
                self._entries.pop(existing_id, None)
                existing_id = UUID(str(asset_id))
                self._path_to_id[norm_rel] = existing_id
            entry = self._entries[existing_id]
            entry["path"] = rel_path
            if asset_type:
                entry["type"] = asset_type
            if name:
                entry["name"] = name
            return existing_id

        if asset_id is None:
            # Deterministic namespace UUID so re-scanning without project.json doesn't churn
            asset_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"lbe://{norm_rel}")
        else:
            asset_uuid = UUID(str(asset_id)) if isinstance(asset_id, str) else asset_id

        resolved_type = asset_type or self.infer_type(path_obj)
        display_name = name or path_obj.name

        self._entries[asset_uuid] = {
            "path": rel_path,
            "type": resolved_type,
            "name": display_name,
        }
        self._path_to_id[norm_rel] = asset_uuid
        return asset_uuid

    def rename(self, asset_id: Union[str, UUID], new_path: Union[str, Path]) -> bool:
        """Update the file path for an asset without modifying its UUID."""
        uid = UUID(str(asset_id)) if isinstance(asset_id, str) else asset_id
        entry = self._entries.get(uid)
        if entry is None:
            return False

        old_norm = entry["path"].lower()
        self._path_to_id.pop(old_norm, None)

        path_obj = Path(new_path)
        if self.project_dir and path_obj.is_absolute():
            try:
                rel_path = str(path_obj.resolve().relative_to(self.project_dir)).replace("\\", "/")
            except ValueError:
                try:
                    rel_path = str(path_obj.relative_to(self.project_dir)).replace("\\", "/")
                except ValueError:
                    rel_path = path_obj.name
        else:
            rel_path = str(path_obj).replace("\\", "/")

        entry["path"] = rel_path
        entry["name"] = path_obj.name
        entry["type"] = self.infer_type(path_obj)
        self._path_to_id[rel_path.lower()] = uid
        return True

    def unregister(self, asset_id: Union[str, UUID]) -> bool:
        uid = UUID(str(asset_id)) if isinstance(asset_id, str) else asset_id
        entry = self._entries.pop(uid, None)
        if entry:
            self._path_to_id.pop(entry["path"].lower(), None)
            return True
        return False

    def get(self, asset_id: Union[str, UUID]) -> Optional[dict]:
        uid = UUID(str(asset_id)) if isinstance(asset_id, str) else asset_id
        return self._entries.get(uid)

    def get_id(self, path: Union[str, Path]) -> Optional[UUID]:
        path_obj = Path(path)
        if self.project_dir and path_obj.is_absolute():
            try:
                rel_path = str(path_obj.resolve().relative_to(self.project_dir)).replace("\\", "/")
            except ValueError:
                try:
                    rel_path = str(path_obj.relative_to(self.project_dir)).replace("\\", "/")
                except ValueError:
                    rel_path = path_obj.name
        else:
            rel_path = str(path_obj).replace("\\", "/")
        return self._path_to_id.get(rel_path.lower())

    def get_ref(self, path_or_id: Union[str, Path, UUID]) -> Optional[AssetRef]:
        if isinstance(path_or_id, UUID) or (isinstance(path_or_id, str) and len(path_or_id) == 36 and "-" in path_or_id):
            try:
                uid = UUID(str(path_or_id))
                entry = self._entries.get(uid)
                if entry:
                    return AssetRef(id=uid, type=entry.get("type", "asset"), name=entry.get("name", entry["path"]))
            except ValueError:
                pass
        uid = self.get_id(path_or_id)
        if uid:
            entry = self._entries[uid]
            return AssetRef(id=uid, type=entry.get("type", "asset"), name=entry.get("name", entry["path"]))
        return None

    def get_path(self, asset_id: Union[str, UUID]) -> Optional[Path]:
        uid = UUID(str(asset_id)) if isinstance(asset_id, str) else asset_id
        entry = self._entries.get(uid)
        if entry and self.project_dir:
            return (self.project_dir / entry["path"]).resolve()
        return None

    def scan(self, project_dir: Optional[Union[str, Path]] = None):
        """Discover files in the project directory and register them."""
        pdir = Path(project_dir).resolve() if project_dir else self.project_dir
        if not pdir or not pdir.exists():
            return
        self.project_dir = pdir
        for root, dirs, files in os.walk(pdir):
            # Skip hidden folders and virtual environments
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "venv", ".venv")]
            for file in files:
                if file.startswith("."):
                    continue
                file_path = Path(root) / file
                rel = file_path.relative_to(pdir)
                rel_str = str(rel).replace("\\", "/")
                # Register if not already known
                if rel_str.lower() not in self._path_to_id:
                    self.register(rel_str)
                else:
                    # Update name/path
                    uid = self._path_to_id[rel_str.lower()]
                    self._entries[uid]["path"] = rel_str
                    self._entries[uid]["name"] = file_path.name

    def to_dict(self) -> dict:
        return {str(uid): dict(entry) for uid, entry in self._entries.items()}

    def from_dict(self, data: dict):
        self.clear()
        if not isinstance(data, dict):
            return
        for uid_str, entry in data.items():
            try:
                uid = UUID(uid_str)
                path = str(entry.get("path", ""))
                atype = str(entry.get("type", self.infer_type(path)))
                name = str(entry.get("name", Path(path).name))
                self._entries[uid] = {"path": path, "type": atype, "name": name}
                self._path_to_id[path.lower()] = uid
            except Exception:
                continue
