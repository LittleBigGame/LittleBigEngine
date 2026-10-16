"""The LBE kernel: the minimal foundation every other product is built on.

The kernel depends on the Python standard library only. It knows nothing
about games, rendering, audio, editors or networking.

Public surface (Phase 2, universal resource kernel):
    ResourceId, TypeId, Ref          identity and references
    Resource, State                   immutable resource records
    ResourceStore                     local persistent storage (drafts + published)
    closure, strongly_connected_groups   cycle-safe graph operations
    validate_resource                 type and requirement validation
    Runtime, Handle                   compact handles and mutable instances
    wellknown                         the bootstrap types the kernel must know
"""

from lbe.kernel import wellknown
from lbe.kernel.errors import (
    ImmutableResourceError,
    KernelError,
    PublishError,
    ResourceNotFound,
    ValidationError,
)
from lbe.kernel.graph import closure, missing_dependencies, strongly_connected_groups
from lbe.kernel.ids import ResourceId, TypeId
from lbe.kernel.resource import Ref, Resource, State
from lbe.kernel.runtime import Handle, Runtime
from lbe.kernel.store import ResourceStore
from lbe.kernel.types import validate_resource

__all__ = [
    "Handle",
    "ImmutableResourceError",
    "KernelError",
    "PublishError",
    "Ref",
    "Resource",
    "ResourceId",
    "ResourceNotFound",
    "ResourceStore",
    "Runtime",
    "State",
    "TypeId",
    "ValidationError",
    "closure",
    "missing_dependencies",
    "strongly_connected_groups",
    "validate_resource",
    "wellknown",
]
