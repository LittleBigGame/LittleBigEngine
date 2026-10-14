from __future__ import annotations

import copy
import functools
from collections.abc import Mapping, MutableMapping, MutableSequence, Sequence
from types import MappingProxyType
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .types import Error, RuntimeID, StorageID

if TYPE_CHECKING:
    from .kernel import Kernel


class ReadOnlySequence(Sequence):
    """An immutable, deeply read-only view over a sequence (list/tuple)."""

    __slots__ = ("_data",)

    def __init__(self, data: Any) -> None:
        self._data = tuple(_unwrap(item) if isinstance(item, (ComponentProxy, TrackedList)) else item for item in data)

    def __getitem__(self, index: Any) -> Any:
        return self._data[index]

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return repr(list(self._data))

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, (str, bytes)):
            return False
        if isinstance(other, (Sequence, list, tuple)):
            return tuple(self) == tuple(other)
        return False


def _unwrap(val: Any) -> Any:
    if isinstance(val, ComponentProxy):
        return val.to_dict()
    if isinstance(val, TrackedList):
        return val.to_list()
    if isinstance(val, Mapping):
        return {k: _unwrap(v) for k, v in val.items()}
    if isinstance(val, (list, tuple, ReadOnlySequence, Sequence)) and not isinstance(val, (str, bytes)):
        return [_unwrap(v) for v in val]
    return val


def _check_component_target(kernel, entity_id, target):
    """Reject views detached by replacement, reload, deletion or transaction rollback."""
    if not hasattr(kernel, "is_valid_runtime_id"):
        return
    if not kernel.is_valid_runtime_id(entity_id):
        raise AttributeError("Component view belongs to a deleted entity")
    resource = kernel.resources.get(kernel._resolve_handle(entity_id), {})
    pending = [resource.get("data", {}).get("components", {})]
    seen = set()
    while pending:
        value = pending.pop()
        if value is target:
            return
        if id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    raise AttributeError("Component view is detached; retrieve the component again")


class TrackedList(MutableSequence):
    """Wraps a list and tracks in-place mutations back to the Kernel and entity."""

    def __init__(
        self,
        target: list[Any],
        kernel: Kernel | Any,
        entity_id: RuntimeID,
        component_name: str = "",
    ) -> None:
        self._data = target
        self._kernel = kernel
        self._entity_id = entity_id
        self._component_name = component_name

    @property
    def _target(self):
        _check_component_target(self._kernel, self._entity_id, self._data)
        return self._data

    def __getitem__(self, index: Any) -> Any:
        val = self._target[index]
        if isinstance(index, slice):
            return [_unwrap(v) for v in val]
        if isinstance(val, dict) and not isinstance(val, ComponentProxy):
            name = f"{self._component_name}[{index}]" if self._component_name else f"[{index}]"
            return ComponentProxy(self._kernel, self._entity_id, name, val)
        if isinstance(val, list) and not isinstance(val, TrackedList):
            name = f"{self._component_name}[{index}]" if self._component_name else f"[{index}]"
            return TrackedList(val, kernel=self._kernel, entity_id=self._entity_id, component_name=name)
        return val

    def __setitem__(self, index: Any, value: Any) -> None:
        if isinstance(index, slice):
            self._target[index] = [_unwrap(v) for v in value]
        else:
            self._target[index] = _unwrap(value)
        self._kernel.mark_dirty(self._entity_id)

    def __delitem__(self, index: Any) -> None:
        del self._target[index]
        self._kernel.mark_dirty(self._entity_id)

    def __len__(self) -> int:
        return len(self._target)

    def insert(self, index: int, value: Any) -> None:
        self._target.insert(index, _unwrap(value))
        self._kernel.mark_dirty(self._entity_id)

    def append(self, value: Any) -> None:
        self._target.append(_unwrap(value))
        self._kernel.mark_dirty(self._entity_id)

    def extend(self, values: Any) -> None:
        items = list(values)
        if items:
            self._target.extend(_unwrap(v) for v in items)
            self._kernel.mark_dirty(self._entity_id)

    def pop(self, index: int = -1) -> Any:
        res = self._target.pop(index)
        self._kernel.mark_dirty(self._entity_id)
        return res

    def remove(self, value: Any) -> None:
        self._target.remove(value)
        self._kernel.mark_dirty(self._entity_id)

    def clear(self) -> None:
        if self._target:
            self._target.clear()
            self._kernel.mark_dirty(self._entity_id)

    def reverse(self) -> None:
        self._target.reverse()
        self._kernel.mark_dirty(self._entity_id)

    def sort(self, *args: Any, **kwargs: Any) -> None:
        self._target.sort(*args, **kwargs)
        self._kernel.mark_dirty(self._entity_id)

    def __iter__(self):
        for i in range(len(self._target)):
            yield self[i]

    def __contains__(self, value: Any) -> bool:
        return value in self._target

    def to_list(self) -> list[Any]:
        return [_unwrap(v) for v in self._target]

    def __copy__(self) -> list[Any]:
        return self.to_list()

    def __deepcopy__(self, memo: Any) -> list[Any]:
        return copy.deepcopy(self.to_list(), memo)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, TrackedList):
            return self._target == other._target
        if isinstance(other, list):
            return self._target == other
        return False

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)

    def __repr__(self) -> str:
        return f"TrackedList({self._target!r})"


class ComponentProxy(MutableMapping):
    """Wraps a component dictionary and tracks mutations back to the Kernel and entity."""

    def __init__(
        self,
        kernel: Kernel | Any,
        entity_id: RuntimeID,
        component_name: str,
        target: dict[str, Any],
    ) -> None:
        object.__setattr__(self, "_kernel", kernel)
        object.__setattr__(self, "_entity_id", entity_id)
        object.__setattr__(self, "_component_name", component_name)
        object.__setattr__(self, "_data", target)

    @property
    def _target(self):
        _check_component_target(self._kernel, self._entity_id, self._data)
        return self._data

    @property
    def entity_id(self) -> RuntimeID:
        return self._entity_id

    @property
    def component_name(self) -> str:
        return self._component_name

    def __getitem__(self, key: Any) -> Any:
        val = self._target[key]
        if isinstance(val, dict) and not isinstance(val, ComponentProxy):
            return ComponentProxy(
                self._kernel,
                self._entity_id,
                f"{self._component_name}.{key}",
                val,
            )
        if isinstance(val, list) and not isinstance(val, TrackedList):
            return TrackedList(
                val,
                kernel=self._kernel,
                entity_id=self._entity_id,
                component_name=f"{self._component_name}.{key}",
            )
        return val

    def __setitem__(self, key: Any, value: Any) -> None:
        self._target[key] = _unwrap(value)
        self._kernel.mark_dirty(self._entity_id)

    def __delitem__(self, key: Any) -> None:
        del self._target[key]
        self._kernel.mark_dirty(self._entity_id)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
        if name in self._target:
            return self[name]
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            self[name] = value

    def __delattr__(self, name: str) -> None:
        if name.startswith("_"):
            object.__delattr__(self, name)
        elif name in self._target:
            del self[name]
        else:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def __contains__(self, key: Any) -> bool:
        return key in self._target

    def __len__(self) -> int:
        return len(self._target)

    def __iter__(self):
        return iter(self._target)

    def get(self, key: Any, default: Any = None) -> Any:
        if key in self._target:
            return self[key]
        return default

    def keys(self):
        return self._target.keys()

    def values(self):
        return [self[k] for k in self._target]

    def items(self):
        return [(k, self[k]) for k in self._target]

    def pop(self, key: Any, *args: Any) -> Any:
        if key in self._target:
            res = self._target.pop(key)
            self._kernel.mark_dirty(self._entity_id)
            return res
        if args:
            return args[0]
        raise KeyError(key)

    def popitem(self) -> tuple[Any, Any]:
        res = self._target.popitem()
        self._kernel.mark_dirty(self._entity_id)
        return res

    def clear(self) -> None:
        if self._target:
            self._target.clear()
            self._kernel.mark_dirty(self._entity_id)

    def setdefault(self, key: Any, default: Any = None) -> Any:
        if key not in self._target:
            self[key] = default
            return self[key]
        return self[key]

    def update(self, *args: Any, **kwargs: Any) -> None:
        other = dict(*args, **kwargs)
        if other:
            for k, v in other.items():
                self._target[k] = _unwrap(v)
            self._kernel.mark_dirty(self._entity_id)

    def __ior__(self, other: Any) -> ComponentProxy:
        self.update(other)
        return self

    def __copy__(self) -> dict[str, Any]:
        return self.to_dict()

    def __deepcopy__(self, memo: Any) -> dict[str, Any]:
        return copy.deepcopy(self.to_dict(), memo)

    def to_dict(self) -> dict[str, Any]:
        return {k: _unwrap(v) for k, v in self._target.items()}

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, ComponentProxy):
            return self._target == other._target
        if isinstance(other, dict):
            return self._target == other
        return False

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)

    def __repr__(self) -> str:
        return f"ComponentProxy({self._component_name!r}, {self._target!r})"


class WorldProxy:
    """Helper object exposing world-level entity queries to an EntityProxy."""

    def __init__(self, kernel: Kernel | Any) -> None:
        self._kernel = kernel

    def query(self, *components: str) -> list[EntityProxy]:
        return self._kernel.query_proxies(*components)

    def __repr__(self) -> str:
        return "<WorldProxy>"


class EntityProxy:
    """Wraps an entity RuntimeID and provides ergonomic, tracked component access."""

    def __init__(self, kernel: Kernel | Any, entity_id: RuntimeID) -> None:
        object.__setattr__(self, "_kernel", kernel)
        object.__setattr__(self, "_entity_id", entity_id)
        object.__setattr__(self, "kernel", kernel)
        object.__setattr__(self, "runtime_id", entity_id)

    @property
    def id(self) -> RuntimeID:
        return self._entity_id

    @property
    def is_alive(self) -> bool:
        return bool(self._kernel.is_entity(self._entity_id))

    def _ensure_alive(self) -> None:
        if not self.is_alive:
            raise AttributeError(f"Entity {self._entity_id} has been destroyed and is no longer valid.")

    @property
    def storage_id(self) -> StorageID | Error:
        self._ensure_alive()
        return self._kernel.get_storage_id(self._entity_id)

    @property
    def name(self) -> str | None:
        self._ensure_alive()
        res = self._kernel.get_resource(self._entity_id)
        if isinstance(res, (dict, MappingProxyType)):
            return res.get("name")
        return None

    @name.setter
    def name(self, val: str | None) -> None:
        self._ensure_alive()
        resolved_id = self._kernel._resolve_handle(self._entity_id) if hasattr(self._kernel, "_resolve_handle") else self._entity_id
        if resolved_id in self._kernel.resources:
            res = self._kernel.resources[resolved_id]
            if val is None:
                res.pop("name", None)
            else:
                res["name"] = val
            self._kernel.mark_dirty(self._entity_id)

    @property
    def parent(self) -> EntityProxy | None:
        self._ensure_alive()
        p_id = self._kernel.get_entity_parent(self._entity_id)
        if p_id is not None:
            return EntityProxy(self._kernel, p_id)
        return None

    @parent.setter
    def parent(self, new_parent: EntityProxy | RuntimeID | None) -> None:
        self._ensure_alive()
        if new_parent is None:
            cur = self._kernel.get_entity_parent(self._entity_id)
            if cur is not None:
                self._kernel.remove_entity_child(cur, self._entity_id)
        else:
            p_id = new_parent.id if hasattr(new_parent, "id") else new_parent
            self._kernel.add_entity_child(p_id, self._entity_id)

    @property
    def children(self) -> list[EntityProxy]:
        self._ensure_alive()
        child_ids = self._kernel.get_entity_children(self._entity_id)
        return [EntityProxy(self._kernel, cid) for cid in child_ids]

    @property
    def world(self) -> WorldProxy:
        self._ensure_alive()
        return WorldProxy(self._kernel)

    def add_child(self, child: EntityProxy | RuntimeID) -> None | Error:
        self._ensure_alive()
        child_id = child.id if hasattr(child, "id") else child
        return self._kernel.add_entity_child(self._entity_id, child_id)

    def remove_child(self, child: EntityProxy | RuntimeID) -> None | Error:
        self._ensure_alive()
        child_id = child.id if hasattr(child, "id") else child
        return self._kernel.remove_entity_child(self._entity_id, child_id)

    def query_children(self, *component_names: str, recursive: bool = False) -> list[EntityProxy]:
        self._ensure_alive()
        results: list[EntityProxy] = []
        visited: set[RuntimeID] = set()

        def _traverse(proxy: EntityProxy) -> None:
            for child in proxy.children:
                if child.id in visited:
                    continue
                visited.add(child.id)
                if all(child.has(c) for c in component_names):
                    results.append(child)
                if recursive:
                    _traverse(child)

        _traverse(self)
        return results

    def find_child(self, name: str, recursive: bool = False) -> EntityProxy | None:
        self._ensure_alive()
        visited: set[RuntimeID] = set()

        def _find(proxy: EntityProxy) -> EntityProxy | None:
            for child in proxy.children:
                if child.id in visited:
                    continue
                visited.add(child.id)
                if child.name == name:
                    return child
                if recursive:
                    found = _find(child)
                    if found is not None:
                        return found
            return None

        return _find(self)

    def spawn(self, template: Any, as_child: bool = False, name: str | None = None) -> EntityProxy:
        self._ensure_alive()
        parent_id = self._entity_id if as_child else None
        res = self._kernel.spawn(template, parent_id=parent_id, name=name)
        if isinstance(res, Error):
            raise res
        return EntityProxy(self._kernel, res)

    def click(self, *args: Any, **kwargs: Any) -> Any | Error:
        """Trigger the on_click UI event for this entity."""
        self._ensure_alive()
        return self._kernel.trigger_ui_event(self._entity_id, "on_click", *args, **kwargs)

    def trigger(self, event_name: str, *args: Any, **kwargs: Any) -> Any | Error:
        """Trigger an arbitrary UI event for this entity."""
        self._ensure_alive()
        return self._kernel.trigger_ui_event(self._entity_id, event_name, *args, **kwargs)

    def _find_component_name(self, name: str) -> str | None:
        components = self._kernel.get_components(self._entity_id)
        if isinstance(components, Error) or not isinstance(components, (dict, MappingProxyType)):
            return None
        if name in components:
            return name
        name_lower = name.lower()
        for key in components:
            if key.lower() == name_lower:
                return key
        return None

    def __getattr__(self, name: str) -> ComponentProxy:
        if name.startswith("_"):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
        self._ensure_alive()
        comp_name = self._find_component_name(name)
        if comp_name is not None:
            comp = self._kernel.get_component(self._entity_id, comp_name)
            if not isinstance(comp, Error):
                return comp
            raise AttributeError(f"Entity {self._entity_id} component error: {comp.message}")
        raise AttributeError(f"Entity {self._entity_id} has no component or attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_") or name in ("kernel", "runtime_id"):
            object.__setattr__(self, name, value)
            return
        prop = getattr(type(self), name, None)
        if isinstance(prop, property):
            if prop.fset is None:
                raise AttributeError(f"can't set attribute '{name}'")
            prop.fset(self, value)
            return
        self._ensure_alive()
        comp_name = self._find_component_name(name)
        target_name = comp_name if comp_name is not None else name
        err = self.set(target_name, value)
        if isinstance(err, Error):
            raise AttributeError(f"Failed to set component '{name}': {err.message}")

    def __delattr__(self, name: str) -> None:
        if name.startswith("_") or name in ("kernel", "runtime_id"):
            object.__delattr__(self, name)
            return
        prop = getattr(type(self), name, None)
        if isinstance(prop, property):
            raise AttributeError(f"can't delete attribute '{name}'")
        self._ensure_alive()
        comp_name = self._find_component_name(name)
        target_name = comp_name if comp_name is not None else name
        err = self.remove(target_name)
        if isinstance(err, Error):
            raise AttributeError(f"Failed to remove component '{name}': {err.message}")

    def __getitem__(self, name: str) -> ComponentProxy:
        if not self.is_alive:
            raise KeyError(f"Entity {self._entity_id} has been destroyed and is no longer valid.")
        comp_name = self._find_component_name(name)
        if comp_name is None:
            raise KeyError(f"Component '{name}' not found on Entity {self._entity_id}")
        comp = self._kernel.get_component(self._entity_id, comp_name)
        if isinstance(comp, Error):
            raise KeyError(f"Component '{name}' error on Entity {self._entity_id}: {comp.message}")
        return comp

    def get(self, name: str, default: Any = None) -> Any:
        if not self.is_alive:
            return default
        comp_name = self._find_component_name(name)
        if comp_name is None:
            return default
        comp = self._kernel.get_component(self._entity_id, comp_name)
        if isinstance(comp, Error):
            return default
        return comp

    def has(self, name: str) -> bool:
        if not self.is_alive:
            return False
        return self._find_component_name(name) is not None

    def set(self, name: str, data: dict[str, Any]) -> None | Error:
        if not self.is_alive:
            return Error(
                message="Resource not found",
                description=f"Runtime ID {self._entity_id} is invalid or stale (referencing a deleted resource)!",
                data={"entity_id": self._entity_id},
                code=RuntimeIDNotFoundOnMemoryError,
            )
        target_data = data.to_dict() if isinstance(data, ComponentProxy) else data
        return self._kernel.set_component(self._entity_id, name, target_data)

    def remove(self, name: str) -> dict | Error:
        if not self.is_alive:
            return Error(
                message="Resource not found",
                description=f"Runtime ID {self._entity_id} is invalid or stale (referencing a deleted resource)!",
                data={"entity_id": self._entity_id},
                code=RuntimeIDNotFoundOnMemoryError,
            )
        comp_name = self._find_component_name(name)
        target_name = comp_name if comp_name is not None else name
        return self._kernel.remove_component(self._entity_id, target_name)

    def __contains__(self, name: str) -> bool:
        return self.has(name)

    def __setitem__(self, name: str, data: dict[str, Any]) -> None:
        if not self.is_alive:
            raise KeyError(f"Entity {self._entity_id} has been destroyed and is no longer valid.")
        err = self.set(name, data)
        if isinstance(err, Error):
            raise KeyError(f"Failed to set component '{name}': {err.message}")

    def __delitem__(self, name: str) -> None:
        if not self.is_alive:
            raise KeyError(f"Entity {self._entity_id} has been destroyed and is no longer valid.")
        err = self.remove(name)
        if isinstance(err, Error):
            raise KeyError(f"Failed to remove component '{name}': {err.message}")

    def __repr__(self) -> str:
        return f"EntityProxy(id={self._entity_id})"


class BoundScriptProxy:
    """Wraps a ScriptProxy and an Entity, automatically binding the entity as the first parameter."""

    def __init__(self, script_proxy: ScriptProxy, entity: Any) -> None:
        self._script_proxy = script_proxy
        self._entity = entity

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._script_proxy, name)
        if callable(attr):
            return functools.partial(attr, self._entity)
        return attr

    def __repr__(self) -> str:
        return f"BoundScriptProxy(script={self._script_proxy!r}, entity={self._entity!r})"


class ScriptProxy:
    """Wraps a Script resource RuntimeID and provides cross-script function dispatch."""

    def __init__(self, kernel: Kernel | Any, script_id: RuntimeID) -> None:
        self._kernel = kernel
        self._script_id = script_id

    @property
    def id(self) -> RuntimeID:
        return self._script_id

    @property
    def is_alive(self) -> bool:
        return bool(self._kernel.is_valid_runtime_id(self._script_id))

    @property
    def storage_id(self) -> StorageID | Error:
        return self._kernel.get_storage_id(self._script_id)

    @property
    def name(self) -> str | None:
        res = self._kernel.get_resource(self._script_id)
        if isinstance(res, (dict, MappingProxyType)):
            return res.get("name")
        return None

    @property
    def data(self) -> dict[str, Any] | None:
        res = self._kernel.get_resource(self._script_id)
        if isinstance(res, (dict, MappingProxyType)):
            return res.get("data")
        return None

    @property
    def type(self) -> int:
        res = self._kernel.get_resource(self._script_id)
        if isinstance(res, (dict, MappingProxyType)):
            return res.get("type", 1)
        return 1

    def __getitem__(self, key: str) -> Any:
        res = self._kernel.get_resource(self._script_id)
        if isinstance(res, (dict, MappingProxyType)) and key in res:
            return res[key]
        raise KeyError(f"Script resource has no key '{key}'")

    def __contains__(self, key: str) -> bool:
        res = self._kernel.get_resource(self._script_id)
        return isinstance(res, (dict, MappingProxyType)) and key in res

    def get(self, key: str, default: Any = None) -> Any:
        res = self._kernel.get_resource(self._script_id)
        if isinstance(res, (dict, MappingProxyType)):
            return res.get(key, default)
        return default

    @property
    def symbols(self) -> dict[str, str]:
        if self.data is not None:
            source_path = self.data.get("source_path", "")
            code = self.data.get("code", "")
            needs_extract = "symbols" not in self.data or not isinstance(self.data["symbols"], (dict, MappingProxyType))
            if not code and source_path:
                try:
                    p = Path(source_path)
                    if not p.is_absolute() and hasattr(self._kernel, "folder_location"):
                        p = self._kernel.folder_location / p
                    if p.exists():
                        mtime = p.stat().st_mtime_ns
                        cached_mtime = getattr(self._kernel, "_script_mtime_cache", {}).get(self._script_id)
                        if needs_extract or cached_mtime is None or cached_mtime != mtime:
                            code = p.read_text(encoding="utf-8")
                            needs_extract = True
                            if cached_mtime is not None and cached_mtime != mtime:
                                if hasattr(self._kernel, "_script_module_cache"):
                                    self._kernel._script_module_cache.pop(self._script_id, None)
                                if hasattr(self._kernel, "_script_cache"):
                                    self._kernel._script_cache.pop(self._script_id, None)
                except Exception:
                    pass

            if not needs_extract:
                return dict(self.data["symbols"])

            if not code and not source_path:
                code = self.data.get("code", "")

            if code:
                from .preprocessor import extract_script_symbols
                syms = extract_script_symbols(code)
                resolved_id = self._kernel._resolve_handle(self._script_id) if hasattr(self._kernel, "_resolve_handle") else self._script_id
                if resolved_id in self._kernel.resources:
                    self._kernel.resources[resolved_id].setdefault("data", {})["symbols"] = syms
                return syms
            elif "symbols" in self.data and isinstance(self.data["symbols"], (dict, MappingProxyType)):
                return dict(self.data["symbols"])
        return {}

    def bind(self, entity: Any) -> BoundScriptProxy:
        return BoundScriptProxy(self, entity)

    def __getattr__(self, name: str) -> Any:
        if not self.is_alive:
            raise AttributeError(f"Script resource {self._script_id} has been destroyed and is no longer valid.")
        if name.startswith("_") and not name.startswith("_fn_"):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
        target_symbol = name
        if not name.startswith("_fn_"):
            symbols = self.symbols
            for fn_sym, display_name in symbols.items():
                if display_name == name:
                    target_symbol = fn_sym
                    break
        func = self._kernel.get_script_callable(self._script_id, target_symbol)
        if func is None or isinstance(func, Error):
            raise AttributeError(f"'{type(self).__name__}' object or script has no attribute or function '{name}'")
        return func

    def __repr__(self) -> str:
        return f"ScriptProxy(id={self._script_id}, name={self.name!r})"

