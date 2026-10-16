"""The bootstrap types the kernel must know by identity.

Type definitions are themselves resources, so the kernel needs a few fixed
identities to get started. These constants were generated once with a
CSPRNG and must never change: every store, server and client agrees on them.

Only these types are built into the kernel. Everything else (scripts,
images, scenes, physics bodies...) is defined by ordinary type-definition
resources created by the community.
"""

from __future__ import annotations

from lbe.kernel.ids import ResourceId, TypeId
from lbe.kernel.resource import Resource, State

#: The type of type definitions. It is self-typed: its own type is itself.
TYPE_DEFINITION = TypeId(
    ResourceId.parse("cab3aa0709d11c9db762162f1a3e37979dd9b4839cc33771bc348f43cc32f823")
)

#: An entity: an ordered composition of component resources, at most one per type.
ENTITY = TypeId(
    ResourceId.parse("254c4e1ac49f6ad8de02461c2e9de5fafac3046a7e3539da4c9dc90948593ebd")
)

#: Arbitrary binary content (images, audio, wasm bytes...) with a media type.
BLOB = TypeId(
    ResourceId.parse("4ba2e284b0b93c00fff7e8aa67ff7609febef4efb7049fdf8d2d0146e052a107")
)

#: Field kinds a type definition may declare for its typed data.
FIELD_KINDS = frozenset({"int", "float", "bool", "string", "ref"})


def bootstrap_resources() -> list[Resource]:
    """The published, kernel-validated records for the bootstrap types.

    Their data is intentionally minimal: the kernel validates these three
    types with code (see lbe.kernel.types), not with a field schema.
    """
    return [
        Resource(
            id=TYPE_DEFINITION,
            type_id=TYPE_DEFINITION,
            label="TypeDefinition",
            data={"kernel": "type-definition"},
            state=State.PUBLISHED,
        ),
        Resource(
            id=ENTITY,
            type_id=TYPE_DEFINITION,
            label="Entity",
            data={"kernel": "entity"},
            state=State.PUBLISHED,
        ),
        Resource(
            id=BLOB,
            type_id=TYPE_DEFINITION,
            label="Blob",
            data={"kernel": "blob"},
            state=State.PUBLISHED,
        ),
    ]
