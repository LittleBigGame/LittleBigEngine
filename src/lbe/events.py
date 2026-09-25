"""Synchronous events and observable structural changes."""

from collections import deque
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Change:
    sequence: int
    kind: str
    entity: Any
    key: str | None = None


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
        self.errors: deque[Diagnostic] = deque(maxlen=100)

    def on(self, name: str, callback: Callable) -> Callable[[], None]:
        listeners = self._listeners.setdefault(name, [])
        listeners.append(callback)

        def unsubscribe():
            if callback in listeners:
                listeners.remove(callback)

        return unsubscribe

    def emit(self, name: str, *args, **kwargs):
        for callback in tuple(self._listeners.get(name, ())):
            try:
                callback(*args, **kwargs)
            except Exception as error:
                self.errors.append(Diagnostic(name, str(error)))


class Changes:
    """Bounded recent history plus a live subscription stream."""

    def __init__(self, capacity: int = 4096):
        self.history: deque[Change] = deque(maxlen=capacity)
        self._events = Events()
        self.sequence = 0

    @property
    def errors(self):
        return self._events.errors

    def subscribe(self, callback):
        return self._events.on("change", callback)

    def publish(self, kind, entity, key=None):
        self.sequence += 1
        change = Change(self.sequence, kind, entity, key)
        self.history.append(change)
        self._events.emit("change", change)
        return change
