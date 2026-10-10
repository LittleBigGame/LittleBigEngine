"""Derived, inspectable attribution of system queries and structural writes."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Effect:
    owner: object
    system: str
    asset: object
    queried: frozenset
    changed: frozenset


class SystemEffects:
    """Observe the latest update plus subsequent draw/event activity per attachment.

    UUIDs are retained instead of entities. Attachments and registry paths remain
    authoritative; this service is only a view of observed execution.
    """
    def __init__(self, runtime):
        self.runtime = runtime
        self._observations = {}
        self._unsubscribe = (runtime.changes.subscribe(self._change), runtime.events.observe(self._event))

    def _bucket(self, source):
        if source is None:
            return None
        return self._observations.setdefault(source[:2], (set(),set()))

    def _event(self, name, args, kwargs):
        if name == 'system.call':
            entity,system,phase = args
            if phase == 'update':
                self._observations[(entity.id,system)] = (set(),set())
        elif name == 'query.result':
            bucket = self._bucket(self.runtime.changes.source)
            if bucket is not None:
                bucket[0].update(e.id for e in args[0])
        elif name == 'runtime.close':
            self.close()

    def _change(self, change):
        identity = change.entity.id
        if change.kind == 'entity.destroy':
            for key,bucket in tuple(self._observations.items()):
                if key[0] == identity:
                    del self._observations[key]
                else:
                    bucket[0].discard(identity)
                    bucket[1].discard(identity)
            return
        if change.kind in ('system.detach','script.detach'):
            self._observations.pop((identity,change.key), None)
            return
        if change.kind.startswith(('component.','tag.','relation.')) or change.kind == 'hierarchy.parent':
            bucket = self._bucket(change.source)
            if bucket is not None:
                bucket[1].add(identity)

    def records(self):
        records = []
        registry = self.runtime.assets.registry
        for (identity,name),(queried,changed) in tuple(self._observations.items()):
            owner = self.runtime._entities.get(identity)
            if owner is None or (not owner.items.has_behaviour(name, kind='system') and not owner.items.has_behaviour(name, kind='script')):
                continue
            instance = owner.items.get_behaviour(name, kind='system') or owner.items.get_behaviour(name, kind='script')
            path = instance.definition.path
            try:
                asset = registry.get_id(path) if registry is not None and path else None
            except ValueError:
                asset = None  # Inline/external definitions have no project asset identity.
            records.append(Effect(identity,name,asset,frozenset(queried),frozenset(changed)))
        return tuple(records)

    def affecting(self, entity):
        return tuple(r for r in self.records() if entity.id in r.queried or entity.id in r.changed)

    def for_asset(self, identity):
        return tuple(r for r in self.records() if r.asset == identity)

    def close(self):
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe = ()
        self._observations.clear()
