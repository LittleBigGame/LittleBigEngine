"""Synchronous events and observable structural changes."""

from collections import deque
from dataclasses import dataclass
from typing import Any, Callable
from contextlib import contextmanager
from itertools import islice

ABSENT = object()


def snapshot(value, depth=0):
    """Bounded descriptions without calling arbitrary user-defined repr methods."""
    if value is ABSENT:
        return '<absent>'
    if type(value) is str:
        return repr(value[:180])
    if type(value) in (int, float, bool, type(None)):
        try:
            return repr(value)[:240]
        except ValueError:
            return '<int>'
    if type(value) in (tuple, list, dict, set, frozenset):
        if depth >= 2:
            return f'<{type(value).__name__} size={len(value)}>'
        if type(value) is dict:
            parts = [snapshot(k, depth+1)+': '+snapshot(v, depth+1)
                     for k, v in islice(value.items(), 6)]
        else:
            parts = [snapshot(v, depth+1) for v in islice(value, 6)]
        return (f'{type(value).__name__}['+', '.join(parts)+(', ...' if len(value)>6 else '')+']')[:240]
    from .core import Entity
    if isinstance(value, Entity):
        return f'<Entity {value.id}>'
    return f'<{type(value).__name__}>'


@dataclass(frozen=True)
class Change:
    sequence: int
    kind: str
    entity: Any
    key: str | None = None
    old: str | None = None
    new: str | None = None
    source: tuple | None = None


@dataclass(frozen=True)
class Diagnostic:
    source: str
    message: str
    traceback: str = ""


class Events:
    """Named events. Subscribe returns an idempotent unsubscribe function.

    Listeners added during dispatch run on the next emission. Listener failures
    are recorded, allowing the remaining listeners and structural work to finish.
    """

    def __init__(self):
        self._listeners: dict[str, list[Callable]] = {}
        self._observers = []
        self.errors: deque[Diagnostic] = deque(maxlen=100)

    def on(self, name: str, callback: Callable) -> Callable[[], None]:
        listeners = self._listeners.setdefault(name, [])
        listeners.append(callback)

        def unsubscribe():
            if callback in listeners:
                listeners.remove(callback)

        return unsubscribe

    def _observe(self, name, args, kwargs):
        for observer in tuple(self._observers):
            try:
                observer(name, args, kwargs)
            except Exception as error:
                self.errors.append(Diagnostic(name, str(error)))

    def emit(self, name: str, *args, **kwargs):
        callbacks = tuple(self._listeners.get(name, ()))
        self._observe(name, args, kwargs)
        for callback in callbacks:
            try:
                callback(*args, **kwargs)
            except Exception as error:
                self.errors.append(Diagnostic(name, str(error)))
                self._observe('event.error', (name, str(error)), {})

    def observe(self, callback):
        """Observe named emissions without changing their listener semantics."""
        self._observers.append(callback)
        def unsubscribe():
            if callback in self._observers:
                self._observers.remove(callback)
        return unsubscribe


class Changes:
    """Bounded recent history plus a live subscription stream."""

    def __init__(self, capacity: int = 4096):
        self.history: deque[Change] = deque(maxlen=capacity)
        self._events = Events()
        self.sequence = 0
        self.source = None

    @contextmanager
    def context(self, entity, system, phase):
        previous = self.source
        self.source = (entity.id, system, phase)
        try:
            yield
        finally:
            self.source = previous

    @property
    def errors(self):
        return self._events.errors

    def subscribe(self, callback):
        return self._events.on("change", callback)

    def publish(self, kind, entity, key=None, *, old=ABSENT, new=ABSENT):
        self.sequence += 1
        change = Change(self.sequence, kind, entity, key,
                        snapshot(old), snapshot(new), self.source)
        self.history.append(change)
        self._events.emit("change", change)
        return change
