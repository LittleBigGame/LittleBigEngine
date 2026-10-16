"""The local resource store: the client's authority for its own drafts.

Layout on disk:

    <root>/resources/<id hex>.json   one document per resource (lbe.kernel.codec)
    <root>/blobs/<sha256 hex>        content-addressed binary content

Rules enforced here:
  * published resources can never be modified or deleted;
  * a resource can only be published together with everything it depends
    on, unless those dependencies are already published;
  * writes are atomic per file (write to a temporary file, then rename).

What this store does not do: reserve ids with a server, authenticate, or
talk to the network. Those belong to the server and sync layers.
"""

from __future__ import annotations

import copy
import hashlib
import os
from collections.abc import Iterable, Iterator
from dataclasses import replace
from pathlib import Path

from lbe.kernel import codec, wellknown
from lbe.kernel.errors import ImmutableResourceError, PublishError, ResourceNotFound, ValidationError
from lbe.kernel.graph import closure
from lbe.kernel.ids import ID_HEX_LENGTH, ResourceId
from lbe.kernel.resource import Resource, State
from lbe.kernel.types import validate_resource


class ResourceStore:
    """Persistent local storage for resources and blobs."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self._resources = self.root / "resources"
        self._blobs = self.root / "blobs"
        self._resources.mkdir(parents=True, exist_ok=True)
        self._blobs.mkdir(parents=True, exist_ok=True)
        for bootstrap in wellknown.bootstrap_resources():
            if not self.contains(bootstrap.id):
                self._write(bootstrap)

    # -- resources ---------------------------------------------------------

    def contains(self, resource_id: ResourceId) -> bool:
        return self._path(resource_id).is_file()

    def ids(self) -> Iterator[ResourceId]:
        for path in sorted(self._resources.glob("*.json")):
            if len(path.stem) == ID_HEX_LENGTH:
                yield ResourceId.parse(path.stem)

    def get(self, resource_id: ResourceId) -> Resource:
        path = self._path(resource_id)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise ResourceNotFound(f"no resource {resource_id}") from None
        resource = codec.loads(text)
        if resource.id != resource_id:
            raise ValidationError(f"file {path.name} contains resource {resource.id}")
        return resource

    def put(self, resource: Resource) -> None:
        """Save a draft. Fails if the id already names a published resource."""
        if resource.published:
            raise ImmutableResourceError("use publish() to publish; put() only saves drafts")
        if self.contains(resource.id) and self.get(resource.id).published:
            raise ImmutableResourceError(f"resource {resource.id} is published and cannot change")
        codec.encode_value(resource.data)  # reject unencodable data before touching disk
        self._write(replace(resource, data=copy.deepcopy(dict(resource.data))))

    def delete(self, resource_id: ResourceId) -> None:
        """Remove a draft. Published resources cannot be deleted; their ids are never reused."""
        if self.get(resource_id).published:
            raise ImmutableResourceError(f"resource {resource_id} is published and cannot be deleted")
        self._path(resource_id).unlink()

    def publish(self, ids: Iterable[ResourceId]) -> list[Resource]:
        """Publish a group of drafts atomically with respect to validation.

        Every member is validated, and every dependency of every member must
        be either already published or itself a member of the group. Blobs
        must be present. Only then are the records rewritten as published.
        Returns the published records.
        """
        group = {resource_id: self.get(resource_id) for resource_id in ids}
        unresolved: dict[ResourceId, list[ResourceId]] = {}
        for resource in group.values():
            if resource.published:
                continue
            validate_resource(self, resource)
            if resource.blob is not None and not self.has_blob(resource.blob):
                raise PublishError(f"resource {resource.id} names blob {resource.blob} which is missing")
            for dep_id in resource.dependencies():
                if dep_id in group:
                    continue
                dep = self.get(dep_id)  # raises ResourceNotFound
                if not dep.published:
                    unresolved.setdefault(resource.id, []).append(dep_id)
        if unresolved:
            raise PublishError(
                "cannot publish: dependencies are unpublished drafts outside the group",
                {k.hex: [d.hex for d in v] for k, v in unresolved.items()},
            )
        published = [replace(r, state=State.PUBLISHED) for r in group.values()]
        for resource in published:
            self._write(resource)
        return published

    def dependency_closure(self, roots: Iterable[ResourceId]) -> dict[ResourceId, Resource]:
        return closure(self, roots)

    # -- blobs -------------------------------------------------------------

    def put_blob(self, content: bytes) -> str:
        """Store binary content; returns its SHA-256 hex, which is its name."""
        digest = hashlib.sha256(content).hexdigest()
        path = self._blobs / digest
        if not path.exists():
            _atomic_write_bytes(path, content)
        return digest

    def has_blob(self, digest: str) -> bool:
        return (self._blobs / digest).is_file()

    def get_blob(self, digest: str) -> bytes:
        try:
            content = (self._blobs / digest).read_bytes()
        except FileNotFoundError:
            raise ResourceNotFound(f"no blob {digest}") from None
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValidationError(f"blob {digest} failed its integrity check")
        return content

    # -- internals ---------------------------------------------------------

    def _path(self, resource_id: ResourceId) -> Path:
        return self._resources / f"{resource_id.hex}.json"

    def _write(self, resource: Resource) -> None:
        _atomic_write_bytes(self._path(resource.id), codec.dumps(resource).encode("utf-8"))


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
