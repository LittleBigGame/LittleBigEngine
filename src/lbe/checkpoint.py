"""In-memory recovery for engine state during trusted script activation.

External resources and opaque user objects are not transactional. Mutable native
containers and LBE-owned state are restored in place so existing handles survive.
"""

from collections import deque
from types import SimpleNamespace


class RuntimeCheckpoint:
    def __init__(self, runtime):
        from .core import Entity
        self.runtime = runtime
        self.entities = runtime.entities
        self._records = []
        seen = set()
        pending = [runtime]
        while pending:
            value = pending.pop()
            kind = type(value)
            if kind not in (dict, list, set, deque, tuple, SimpleNamespace) and not (
                isinstance(value, Entity) or kind.__module__.startswith('lbe.')
            ):
                continue
            if id(value) in seen:
                continue
            seen.add(id(value))
            if kind is dict:
                state = dict(value)
                self._records.append((value, 'dict', state))
                pending.extend(v for k, v in state.items() if k != '__builtins__')
            elif kind in (list, deque, set):
                state = tuple(value)
                self._records.append((value, kind.__name__, state))
                pending.extend(state)
            elif kind is tuple:
                pending.extend(value)
            elif isinstance(value, Entity):
                state = {key: object.__getattribute__(value, key) for key in Entity.__slots__}
                self._records.append((value, 'entity', state))
                pending.extend(state.values())
            else:
                # Frozen definitions and records are immutable; native graphics,
                # files, futures and imported modules deliberately stay opaque.
                params = getattr(kind, '__dataclass_params__', None)
                if params is not None and params.frozen:
                    continue
                state = getattr(value, '__dict__', None)
                if state is not None:
                    pending.append(state)

    def restore(self):
        original = set(self.entities)
        for entity in self.runtime.entities:
            if entity not in original:
                for instance in (*entity.systems.values(), *entity.scripts.values()):
                    instance.running = False
                object.__setattr__(entity, '_alive', False)
                object.__setattr__(entity, '_parent', None)
        for value, kind, state in self._records:
            if kind == 'entity':
                for key, item in state.items():
                    object.__setattr__(value, key, item)
            else:
                value.clear()
                if kind in ('dict', 'set'):
                    value.update(state)
                else:
                    value.extend(state)
