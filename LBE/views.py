"""Deep read-only projections of authoritative resource data."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any
from .proxy import ReadOnlySequence


def _make_readonly_view(obj: Any) -> Any:
    if isinstance(obj, Mapping):
        return MappingProxyType({k: _make_readonly_view(v) for k, v in obj.items()})
    if isinstance(obj, (list, tuple, ReadOnlySequence)):
        return ReadOnlySequence([_make_readonly_view(v) for v in obj])
    return obj

