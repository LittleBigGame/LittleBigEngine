"""Kernel exception hierarchy. Every kernel error derives from KernelError."""

from __future__ import annotations


class KernelError(Exception):
    """Base class for all kernel errors."""


class ResourceNotFound(KernelError, LookupError):
    """A resource or blob was requested by identity but is not in the store."""


class ImmutableResourceError(KernelError):
    """An attempt was made to modify or delete a published resource."""


class ValidationError(KernelError, ValueError):
    """A resource, its data or its encoding violates a kernel rule."""


class PublishError(KernelError):
    """A resource group cannot be published because its dependencies are unresolved."""

    def __init__(self, message: str, unresolved: dict | None = None) -> None:
        super().__init__(message)
        self.unresolved = unresolved or {}
