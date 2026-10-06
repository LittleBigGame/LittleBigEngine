"""Shared script definitions and independent runtime attachments."""

from collections import deque
from collections.abc import MutableMapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import CodeType
import traceback

from .events import Diagnostic


@dataclass(frozen=True)
class SystemDefinition:
    source: str
    path: str = "<system>"
    asset_id: object = None
    components: tuple = field(init=False, default=())
    code: CodeType = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "code", compile(self.source, self.path, "exec"))
        import ast
        for statement in ast.parse(self.source).body:
            if isinstance(statement, ast.Assign) and any(isinstance(t,ast.Name) and t.id=='components' for t in statement.targets):
                requirements=ast.literal_eval(statement.value)
                if not isinstance(requirements,(tuple,list)) or not all(isinstance(k,str) and k for k in requirements):
                    raise ValueError('Script components must be a list/tuple of component names')
                object.__setattr__(self,'components',tuple(requirements))

    @classmethod
    def from_file(cls, path):
        path = Path(path).resolve()
        return cls(path.read_text(encoding="utf-8"), str(path))


class Assets:
    """Cache immutable compiled system sources and resolve persistent asset handles."""

    def __init__(self, registry=None):
        self._systems = {}
        self.registry = registry

    def system(self, path):
        path = Path(path).resolve()
        source = path.read_text(encoding="utf-8")
        previous = self._systems.get(path)
        if previous is None or previous.source != source:
            previous = SystemDefinition(source, str(path))
            self._systems[path] = previous
        return previous

    def invalidate(self, path):
        self._systems.pop(Path(path).resolve(), None)

    def resolve(self, key):
        """Resolve a path, UUID, or AssetRef to an asset object or resolved Path."""
        from uuid import UUID
        from .assets import AssetRef
        if isinstance(key, AssetRef):
            key = key.id
        if isinstance(key, (UUID, str)):
            uid = None
            if isinstance(key, UUID):
                uid = key
            elif isinstance(key, str) and len(key) == 36 and "-" in key:
                try:
                    uid = UUID(key)
                except ValueError:
                    uid = None
            if uid is not None and self.registry:
                p = self.registry.get_path(uid)
                if p is None:
                    raise KeyError(uid)
                if not p.exists():
                    raise FileNotFoundError(p)
                if p.suffix.lower() != '.py':
                    return p
                definition=self.system(p)
                if definition.asset_id != uid:
                    definition=replace(definition,asset_id=uid)
                    self._systems[p]=definition
                return definition
            if uid is not None:
                raise KeyError(uid)
        p = Path(key)
        if p.suffix.lower() == ".py" and p.exists():
            return self.system(p)
        return p

    def get(self, key, default=None):
        try:
            return self.resolve(key)
        except (KeyError, FileNotFoundError):
            return default

    def __getitem__(self, key):
        return self.resolve(key)

    def __contains__(self, key):
        try:
            return self.get(key) is not None
        except Exception:
            return False


class SystemInstance:
    def __init__(self, entity, name, definition, *, identity=None):
        from uuid import UUID, uuid4
        self.id = UUID(str(identity)) if identity is not None else uuid4()
        self.entity = entity
        self.name = name
        self.definition = definition
        self.namespace = {}
        self.errors: deque[Diagnostic] = deque(maxlen=100)
        self.running = False
        self._initialized = False
        self._started = False
        self._stopped = False
        self._subscriptions = []
        self._injected = {}

    @property
    def globals(self):
        """User-defined public globals, excluding injected services unless rebound."""
        res = {}
        for key, value in self.namespace.items():
            if key.startswith("_"):
                continue
            if key in self._injected and value is self._injected[key]:
                continue
            res[key] = value
        return res

    @property
    def lifecycle(self):
        return tuple(name for name in ("start", "update", "run", "draw", "stop")
                     if callable(self.namespace.get(name)))

    def _error(self, phase, error):
        self.errors.append(Diagnostic(
            f"{self.name}.{phase}", str(error), traceback.format_exc()
        ))
        self.running = False
        with self.entity.runtime.changes.context(self.entity, self.name, phase):
            self.entity._changed("system.error", self.name, new=str(error))

    def initialize(self):
        runtime = self.entity.runtime
        self.namespace = dict(runtime.services)
        self.namespace.update({
            "__name__": f"lbe_script_{self.entity.id.hex}_{self.name}",
            "__file__": self.definition.path,
            "self": self.entity,
            "entity": self.entity,
            "runtime": runtime,
            "system": self,
            "systems": self.entity.systems,
            "create": runtime.create,
            "resolve": runtime.resolve,
            "destroy": runtime.destroy,
            "query": self.entity.query,
            "events": runtime.events,
            "changes": runtime.changes,
            "assets": runtime.assets,
            "asset": runtime.assets.resolve,
        })
        self._injected = dict(self.namespace)
        try:
            with runtime.changes.context(self.entity, self.name, 'initialize'):
                runtime.events.emit('system.call', self.entity, self.name, 'initialize')
                exec(self.definition.code, self.namespace)
            for name in ("start", "update", "run", "draw", "stop"):
                value = self.namespace.get(name)
                if value is not None and not callable(value):
                    raise TypeError(f"{name} must be callable")
            self._initialized = True
            return True
        except Exception as error:
            self._error("initialize", error)
            self._unsubscribe()
            return False

    def start(self):
        if self._initialized and not self._stopped and not self._started:
            self._started = True
            self.running = True
            self.call("start")

    def _invoke(self, func, *args):
        if not callable(func):
            return
        import inspect
        try:
            sig = inspect.signature(func)
            params = sig.parameters
            param_count = len(params)
        except (ValueError, TypeError):
            param_count = None

        if param_count == 0:
            func()
        elif param_count == 1:
            pname = list(params.keys())[0] if param_count else None
            if pname == 'dt' and args:
                func(args[0])
            elif pname in ('self', 'entity') and args and not isinstance(args[0], (int, float)):
                func(args[0])
            elif pname in ('self', 'entity'):
                func(self.entity)
            elif args:
                func(args[0])
            else:
                func(self.entity)
        elif param_count == 2:
            func(self.entity, args[0] if args else 0.0)
        else:
            func(*args)

    def _invoke_target(self, func, target, dt):
        import inspect
        try:
            sig = inspect.signature(func)
            params = sig.parameters
            param_count = len(params)
        except (ValueError, TypeError):
            param_count = None

        if param_count == 0:
            func()
        elif param_count == 1:
            pname = list(params.keys())[0] if param_count else None
            if pname in ("entity", "e", "ent", "target"):
                func(target)
            else:
                func(dt)
        elif param_count == 2:
            pnames = list(params.keys())
            if pnames[0] in ("dt", "delta") and pnames[1] in ("entity", "self", "e"):
                func(dt, target)
            else:
                func(target, dt)
        else:
            try:
                func(dt)
            except TypeError:
                func(target)

    def call(self, phase, *args):
        try:
            dt = args[0] if args else 0.0
            if phase == "update":
                has_update = callable(self.namespace.get("update"))
                has_run = callable(self.namespace.get("run"))
                if not has_update and not has_run:
                    return

                with self.entity.runtime.changes.context(self.entity, self.name, phase):
                    self.entity.runtime.events.emit('system.call', self.entity, self.name, phase)

                    if has_update:
                        self.namespace["self"] = self.entity
                        self._invoke(self.namespace["update"], *args)

                    if has_run:
                        if self.definition.components:
                            if all(c in self.entity.components for c in self.definition.components):
                                targets = [self.entity]
                            else:
                                targets = list(self.entity.query(*self.definition.components, recursive=True))
                        else:
                            if not self.entity.children or ("root" not in self.entity.tags and self.entity.parent is not None):
                                targets = [self.entity]
                            else:
                                targets = list(self.entity.children)
                                if not targets:
                                    targets = [self.entity]

                        run_func = self.namespace["run"]
                        for target in targets:
                            self.namespace["self"] = target
                            self._invoke_target(run_func, target, dt)

                        self.namespace["self"] = self.entity
            else:
                callback = self.namespace.get(phase)
                if callback is None:
                    return
                with self.entity.runtime.changes.context(self.entity, self.name, phase):
                    self.entity.runtime.events.emit('system.call', self.entity, self.name, phase)
                    self.namespace["self"] = self.entity
                    self._invoke(callback, *args)
        except Exception as error:
            self._error(phase, error)

    def listen(self, name, callback):
        """Subscribe with automatic cleanup when this attachment stops."""
        def guarded(*args, **kwargs):
            if self.running:
                try:
                    with self.entity.runtime.changes.context(self.entity, self.name, f'event:{name}'):
                        if name != 'system.call':
                            self.entity.runtime.events.emit('system.call', self.entity, self.name, f'event:{name}')
                        callback(*args, **kwargs)
                except Exception as error:
                    self._error(f"event:{name}", error)

        unsubscribe = self.entity.runtime.events.on(name, guarded)
        self._subscriptions.append(unsubscribe)
        return unsubscribe

    def _unsubscribe(self):
        for unsubscribe in self._subscriptions:
            unsubscribe()
        self._subscriptions.clear()

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        self.running = False
        if self._initialized:
            self.call("stop")
        self._unsubscribe()


class Systems(MutableMapping):
    def __init__(self, entity):
        self._entity = entity
        from .items import NamedValues
        self._values = NamedValues(entity, SystemInstance)

    def __getitem__(self, name):
        self._entity._check()
        return self._values[name]

    def __iter__(self):
        self._entity._check()
        return iter(tuple(self._values))

    def __len__(self):
        self._entity._check()
        return len(self._values)

    def __setitem__(self, name, definition):
        self.attach(name, definition)

    def __delitem__(self, name):
        self._entity._check()
        instance = self._values.pop(name)
        instance.stop()
        self._entity._changed("system.detach", name)

    def attach(self, name, definition=None, *, identity=None):
        if definition is None:
            definition = self._entity.runtime.assets.resolve(name) if not isinstance(name,SystemDefinition) else name
            identity = definition.asset_id
            if identity is None and self._entity.runtime.assets.registry is not None:
                identity = self._entity.runtime.assets.registry.get_id(definition.path)
            if identity is None:
                raise ValueError('UUID attachment requires a registered system asset')
            name = str(identity)
        self._entity._check()
        if self._entity._destroying:
            raise RuntimeError("Cannot attach systems during entity destruction")
        if not isinstance(name, str) or not name:
            raise ValueError("System names must be nonempty strings")
        if name in self._values:
            raise ValueError(f"System {name!r} already attached; use reload")
        if not isinstance(definition, SystemDefinition):
            raise TypeError("Expected a SystemDefinition")
        instance = SystemInstance(self._entity, name, definition, identity=identity)
        self._values[name] = instance
        self._entity._changed("system.attach", name)
        if instance.initialize() and self._entity.alive and self._values.get(name) is instance:
            instance.start()
        return instance

    def reload(self, name, definition):
        """Compile first; syntax failures preserve the current attachment."""
        current = self[name]
        try:
            if isinstance(definition, str):
                definition = SystemDefinition(definition, current.definition.path)
            if not isinstance(definition, SystemDefinition):
                raise TypeError("Expected source text or a SystemDefinition")
        except Exception as error:
            current.errors.append(Diagnostic(f"{name}.compile", str(error), traceback.format_exc()))
            self._entity._changed("system.error", name)
            return current
        candidate = SystemInstance(self._entity, name, definition, identity=current.id)
        if not candidate.initialize():
            current.errors.extend(candidate.errors)
            return current
        if not self._entity.alive or self._values.get(name) is not current:
            candidate.stop()
            return current
        current.stop()
        if not self._entity.alive or self._values.get(name) is not current:
            candidate.stop()
            return current
        self._values[name] = candidate
        candidate.start()
        self._entity._changed("system.reload", name)
        return candidate

    def move(self, name, index):
        self._entity._check()
        if name not in self._values:
            raise KeyError(name)
        if not isinstance(index, int) or not 0 <= index < len(self._values):
            raise IndexError(index)
        items = list(self._values.items())
        pair = next(item for item in items if item[0] == name)
        items.remove(pair)
        items.insert(index, pair)
        self._values.reorder(items)
        self._entity._changed("system.reorder", name)

    def relocate(self, name, path, *, new_name=None):
        """Change source identity without restarting behavior or reordering attachments."""
        instance = self[name]
        new_name = new_name or name
        if new_name != name and new_name in self._values:
            raise ValueError(f"System {new_name!r} is already attached")
        definition = SystemDefinition(instance.definition.source, str(path), instance.definition.asset_id)
        self._entity.items._names.pop((SystemInstance, name))
        instance.name = new_name
        self._entity.items._names[SystemInstance, new_name] = instance.id
        instance.definition = definition
        instance.namespace["__file__"] = str(path)
        self._entity._changed("system.relocate", new_name)
        return instance
