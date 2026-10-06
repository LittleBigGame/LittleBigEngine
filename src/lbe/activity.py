"""Bounded, derived runtime activity observations for application tools."""

from collections import deque
from dataclasses import dataclass
from time import monotonic

from .events import snapshot
from .core import Entity


@dataclass(frozen=True)
class Record:
    sequence: int
    time: float
    kind: str
    target: str
    source: str
    detail: str
    editor: bool = False


class ActivityLog:
    """Observe changes, emissions and system entry points without owning state.

    All records are immutable strings, so destroyed entities are not retained.
    Calls to update/draw are opt-in to avoid flooding the bounded buffer.
    """
    def __init__(self, runtime, capacity=2000):
        self.records = deque(maxlen=capacity)
        self.sequence = 0
        self.paused = False
        self.frame_calls = False
        self.include_editor = False
        self.excluded = set()
        self._runtime = runtime
        self._start = monotonic()
        self._unsubscribe = [runtime.changes.subscribe(self._change), runtime.events.observe(self._event)]

    def write(self, kind, detail, *, target='', source=None, editor=False):
        if self.paused or (editor and not self.include_editor and not kind.endswith('error')):
            return
        self.sequence += 1
        self.records.append(Record(self.sequence, monotonic()-self._start, kind,
                                   str(target), str(source or self._source()), str(detail)[:1000], editor))

    def _source(self, source=None):
        source = source or self._runtime.changes.source
        if not source:
            return 'external'
        entity = self._runtime._entities.get(source[0])
        name = entity.components._values.get('name', '') if entity else ''
        label=source[1]
        registry=self._runtime.assets.registry
        if registry is not None:
            try:
                entry=registry.get(label)
                if entry:
                    label=entry['name']
            except (ValueError,TypeError):
                pass
        return f'{snapshot(name)}:{str(source[0])[:8]}.{label}.{source[2]}'

    @staticmethod
    def _target(entity):
        name = entity.components._values.get('name', '')
        return f'{snapshot(name)} ({entity.id})'

    def _change(self, change):
        entity = change.entity
        current = entity
        while current is not None:
            if current.id in self.excluded and not change.kind.endswith('error'):
                if change.kind == 'entity.destroy':
                    self.excluded.discard(entity.id)
                return
            current = current._parent
        editor = 'ui' in entity.tags._values or 'editor' in entity.tags._values
        detail = change.key or ''
        if change.kind == 'entity.create':
            detail = ('components: '+snapshot(dict(entity.components._values))
                      +'; tags: '+snapshot(set(entity.tags._values))
                      +'; parent: '+snapshot(entity._parent))
        if change.kind.startswith(('component.', 'relation.', 'tag.')) or change.kind == 'hierarchy.parent':
            old = 'unknown prior value' if change.kind == 'component.mutate' else change.old
            detail += f': {old} -> {change.new}'
        if change.kind in ('system.error','script.error'):
            collection = entity.scripts if change.kind == 'script.error' else entity.systems
            instance = collection._values.get(change.key)
            if instance and instance.errors:
                detail += ': '+instance.errors[-1].message
                if change.kind == 'script.error':
                    detail += '\n'+instance.errors[-1].traceback
            else:
                detail += ': '+str(change.new)
        self.write(change.kind, detail, target=self._target(entity), source=self._source(change.source), editor=editor)

    def _event(self, name, args, kwargs):
        if name == 'query.result' and not self.frame_calls:
            return
        if args and isinstance(args[0], Entity):
            current = args[0]
            while current is not None:
                if current.id in self.excluded:
                    return
                current = current._parent
        if name == 'system.call':
            entity, system, phase = args
            if phase in ('update', 'draw') and not self.frame_calls:
                return
            self.write(name, system+'.'+phase, target=self._target(entity), source=self._source(),
                       editor='ui' in entity.tags._values or 'editor' in entity.tags._values)
        else:
            source = self._runtime.changes.source
            owner = self._runtime._entities.get(source[0]) if source else None
            editor = bool(owner and ('ui' in owner.tags._values or 'editor' in owner.tags._values))
            target = self._target(args[0]) if args and isinstance(args[0], Entity) else ''
            self.write(name if name == 'event.error' else 'event.'+name,
                       snapshot(args)+' '+snapshot(kwargs), target=target, source=self._source(), editor=editor)
        if name == 'runtime.close':
            self.close()

    def clear(self):
        self.records.clear()

    def exclude(self, entity):
        """Exclude an observer's own entity subtree to avoid feedback."""
        self.excluded.add(entity.id)

    def close(self):
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()

    def view(self, *, include_editor=False, text=''):
        needle = text.casefold()
        return tuple(r for r in self.records if (include_editor or not r.editor or r.kind.endswith('error'))
                     and (not needle or needle in (r.kind+' '+r.target+' '+r.source+' '+r.detail).casefold()))
