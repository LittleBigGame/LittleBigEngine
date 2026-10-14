from __future__ import annotations

import copy
import functools
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .types import Error, RuntimeID, StorageID

if TYPE_CHECKING:
    from .kernel import Kernel


class ComponentProxy(dict):
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
        object.__setattr__(self, "_target", target)
        super().__init__(target)

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
        return val

    def __setitem__(self, key: Any, value: Any) -> None:
        target_val = value.to_dict() if isinstance(value, ComponentProxy) else value
        self._target[key] = target_val
        super().__setitem__(key, target_val)
        self._kernel.mark_dirty(self._entity_id)

    def __delitem__(self, key: Any) -> None:
        del self._target[key]
        super().__delitem__(key)
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
        had_key = key in self._target
        res = self._target.pop(key, *args)
        super().pop(key, *args)
        if had_key:
            self._kernel.mark_dirty(self._entity_id)
        return res

    def popitem(self) -> tuple[Any, Any]:
        res = self._target.popitem()
        super().pop(res[0], None)
        self._kernel.mark_dirty(self._entity_id)
        return res

    def clear(self) -> None:
        self._target.clear()
        super().clear()
        self._kernel.mark_dirty(self._entity_id)

    def setdefault(self, key: Any, default: Any = None) -> Any:
        if key not in self._target:
            self[key] = default
            return self[key]
        return self[key]

    def update(self, *args: Any, **kwargs: Any) -> None:
        self._target.update(*args, **kwargs)
        super().update(*args, **kwargs)
        self._kernel.mark_dirty(self._entity_id)

    def __ior__(self, other: Any) -> ComponentProxy:
        self.update(other)
        return self

    def __copy__(self) -> dict[str, Any]:
        return self.to_dict()

    def __deepcopy__(self, memo: Any) -> dict[str, Any]:
        return copy.deepcopy(self.to_dict(), memo)

    def to_dict(self) -> dict[str, Any]:
        result = {}
        for k, v in self._target.items():
            if isinstance(v, ComponentProxy):
                result[k] = v.to_dict()
            elif isinstance(v, dict):
                result[k] = copy.deepcopy(v)
            else:
                result[k] = v
        return result

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
        self._kernel = kernel
        self._entity_id = entity_id

    @property
    def id(self) -> RuntimeID:
        return self._entity_id

    @property
    def storage_id(self) -> StorageID | Error:
        return self._kernel.get_storage_id(self._entity_id)

    @property
    def name(self) -> str | None:
        res = self._kernel.get_resource(self._entity_id)
        if isinstance(res, dict):
            return res.get("name")
        return None

    @name.setter
    def name(self, val: str | None) -> None:
        res = self._kernel.get_resource(self._entity_id)
        if isinstance(res, dict):
            if val is None:
                res.pop("name", None)
            else:
                res["name"] = val
            self._kernel.mark_dirty(self._entity_id)

    @property
    def parent(self) -> EntityProxy | None:
        p_id = self._kernel.get_entity_parent(self._entity_id)
        if p_id is not None:
            return EntityProxy(self._kernel, p_id)
        return None

    @parent.setter
    def parent(self, new_parent: EntityProxy | RuntimeID | None) -> None:
        if new_parent is None:
            cur = self._kernel.get_entity_parent(self._entity_id)
            if cur is not None:
                self._kernel.remove_entity_child(cur, self._entity_id)
        else:
            p_id = new_parent.id if hasattr(new_parent, "id") else new_parent
            self._kernel.add_entity_child(p_id, self._entity_id)

    @property
    def children(self) -> list[EntityProxy]:
        child_ids = self._kernel.get_entity_children(self._entity_id)
        return [EntityProxy(self._kernel, cid) for cid in child_ids]

    @property
    def world(self) -> WorldProxy:
        return WorldProxy(self._kernel)

    def add_child(self, child: EntityProxy | RuntimeID) -> None | Error:
        child_id = child.id if hasattr(child, "id") else child
        return self._kernel.add_entity_child(self._entity_id, child_id)

    def remove_child(self, child: EntityProxy | RuntimeID) -> None | Error:
        child_id = child.id if hasattr(child, "id") else child
        return self._kernel.remove_entity_child(self._entity_id, child_id)

    def query_children(self, *component_names: str, recursive: bool = False) -> list[EntityProxy]:
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
        parent_id = self._entity_id if as_child else None
        res = self._kernel.spawn(template, parent_id=parent_id, name=name)
        if isinstance(res, Error):
            raise res
        return EntityProxy(self._kernel, res)

    def click(self, *args: Any, **kwargs: Any) -> Any | Error:
        """Trigger the on_click UI event for this entity."""
        return self._kernel.trigger_ui_event(self._entity_id, "on_click", *args, **kwargs)

    def trigger(self, event_name: str, *args: Any, **kwargs: Any) -> Any | Error:
        """Trigger an arbitrary UI event for this entity."""
        return self._kernel.trigger_ui_event(self._entity_id, event_name, *args, **kwargs)

    def _find_component_name(self, name: str) -> str | None:
        components = self._kernel.get_components(self._entity_id)
        if isinstance(components, Error) or not isinstance(components, dict):
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
        comp_name = self._find_component_name(name)
        if comp_name is not None:
            comp = self._kernel.get_component(self._entity_id, comp_name)
            if not isinstance(comp, Error):
                return comp
            raise AttributeError(f"Entity {self._entity_id} component error: {comp.message}")
        raise AttributeError(f"Entity {self._entity_id} has no component or attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        prop = getattr(type(self), name, None)
        if isinstance(prop, property):
            if prop.fset is None:
                raise AttributeError(f"can't set attribute '{name}'")
            prop.fset(self, value)
            return
        comp_name = self._find_component_name(name)
        target_name = comp_name if comp_name is not None else name
        err = self.set(target_name, value)
        if isinstance(err, Error):
            raise AttributeError(f"Failed to set component '{name}': {err.message}")

    def __delattr__(self, name: str) -> None:
        if name.startswith("_"):
            object.__delattr__(self, name)
            return
        prop = getattr(type(self), name, None)
        if isinstance(prop, property):
            raise AttributeError(f"can't delete attribute '{name}'")
        comp_name = self._find_component_name(name)
        target_name = comp_name if comp_name is not None else name
        err = self.remove(target_name)
        if isinstance(err, Error):
            raise AttributeError(f"Failed to remove component '{name}': {err.message}")

    def __getitem__(self, name: str) -> ComponentProxy:
        comp_name = self._find_component_name(name)
        if comp_name is None:
            raise KeyError(f"Component '{name}' not found on Entity {self._entity_id}")
        comp = self._kernel.get_component(self._entity_id, comp_name)
        if isinstance(comp, Error):
            raise KeyError(f"Component '{name}' error on Entity {self._entity_id}: {comp.message}")
        return comp

    def get(self, name: str, default: Any = None) -> Any:
        comp_name = self._find_component_name(name)
        if comp_name is None:
            return default
        comp = self._kernel.get_component(self._entity_id, comp_name)
        if isinstance(comp, Error):
            return default
        return comp

    def has(self, name: str) -> bool:
        return self._find_component_name(name) is not None

    def set(self, name: str, data: dict[str, Any]) -> None | Error:
        target_data = data.to_dict() if isinstance(data, ComponentProxy) else data
        return self._kernel.set_component(self._entity_id, name, target_data)

    def remove(self, name: str) -> dict | Error:
        comp_name = self._find_component_name(name)
        target_name = comp_name if comp_name is not None else name
        return self._kernel.remove_component(self._entity_id, target_name)

    def __contains__(self, name: str) -> bool:
        return self.has(name)

    def __setitem__(self, name: str, data: dict[str, Any]) -> None:
        err = self.set(name, data)
        if isinstance(err, Error):
            raise KeyError(f"Failed to set component '{name}': {err.message}")

    def __delitem__(self, name: str) -> None:
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
    def storage_id(self) -> StorageID | Error:
        return self._kernel.get_storage_id(self._script_id)

    @property
    def name(self) -> str | None:
        res = self._kernel.get_resource(self._script_id)
        if isinstance(res, dict):
            return res.get("name")
        return None

    @property
    def data(self) -> dict[str, Any] | None:
        res = self._kernel.get_resource(self._script_id)
        if isinstance(res, dict):
            return res.get("data")
        return None

    @property
    def type(self) -> int:
        res = self._kernel.get_resource(self._script_id)
        if isinstance(res, dict):
            return res.get("type", 1)
        return 1

    def __getitem__(self, key: str) -> Any:
        res = self._kernel.get_resource(self._script_id)
        if isinstance(res, dict) and key in res:
            return res[key]
        raise KeyError(f"Script resource has no key '{key}'")

    def __contains__(self, key: str) -> bool:
        res = self._kernel.get_resource(self._script_id)
        return isinstance(res, dict) and key in res

    def get(self, key: str, default: Any = None) -> Any:
        res = self._kernel.get_resource(self._script_id)
        if isinstance(res, dict):
            return res.get(key, default)
        return default

    @property
    def symbols(self) -> dict[str, str]:
        if self.data is not None:
            source_path = self.data.get("source_path", "")
            code = self.data.get("code", "")
            needs_extract = "symbols" not in self.data or not isinstance(self.data["symbols"], dict)
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
                return self.data["symbols"]

            if not code and not source_path:
                code = self.data.get("code", "")

            if code:
                from .preprocessor import extract_script_symbols
                syms = extract_script_symbols(code)
                self.data["symbols"] = syms
                return syms
            elif "symbols" in self.data and isinstance(self.data["symbols"], dict):
                return self.data["symbols"]
        return {}

    def bind(self, entity: Any) -> BoundScriptProxy:
        return BoundScriptProxy(self, entity)

    def __getattr__(self, name: str) -> Any:
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

