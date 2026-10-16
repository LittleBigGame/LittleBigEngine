"""256-bit cryptographically random identifiers.

A ResourceId identifies exactly one resource, forever. A TypeId is the
ResourceId of a type-definition resource; it is the same kind of value and
compares equal to it. Runtime handles (lbe.kernel.runtime.Handle) are the
separate, ephemeral, process-local identifiers and are never persisted.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import NewType

ID_BYTES = 32
ID_HEX_LENGTH = ID_BYTES * 2


@dataclass(frozen=True, slots=True)
class ResourceId:
    """A 256-bit identifier. Immutable, hashable and totally ordered by bytes."""

    raw: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.raw, bytes) or len(self.raw) != ID_BYTES:
            raise ValueError(f"ResourceId must be exactly {ID_BYTES} bytes")

    @classmethod
    def generate(cls) -> ResourceId:
        """Return a fresh identifier from the operating system's CSPRNG."""
        return cls(secrets.token_bytes(ID_BYTES))

    @classmethod
    def parse(cls, text: str) -> ResourceId:
        """Parse the canonical 64-character lowercase hex form (uppercase accepted)."""
        if not isinstance(text, str) or len(text) != ID_HEX_LENGTH:
            raise ValueError(f"ResourceId text must be {ID_HEX_LENGTH} hex characters")
        try:
            return cls(bytes.fromhex(text))
        except ValueError as exc:
            raise ValueError("ResourceId text must be hexadecimal") from exc

    @property
    def hex(self) -> str:
        return self.raw.hex()

    def __str__(self) -> str:
        return self.hex

    def __repr__(self) -> str:
        return f"ResourceId({self.hex!r})"

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ResourceId):
            return NotImplemented
        return self.raw < other.raw


# A TypeId is the ResourceId of a type-definition resource. The distinction is
# documentation for readers and type checkers; at runtime the values are equal.
TypeId = NewType("TypeId", ResourceId)
