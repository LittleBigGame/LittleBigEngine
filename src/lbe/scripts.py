"""Attached behavior with per-entity requirements and isolated execution."""
from collections.abc import MutableMapping
import traceback
from .systems import SystemDefinition, SystemInstance
from .events import Diagnostic


def identity(entity, reference):
    from .assets import AssetRef
    from uuid import UUID
    if isinstance(reference,AssetRef):
        return reference.id
    if isinstance(reference,SystemDefinition):
        if reference.asset_id is not None:
            return reference.asset_id
        registry=entity.runtime.assets.registry
        return registry.get_id(reference.path) if registry is not None else None
    return UUID(str(reference))


class ScriptInstance(SystemInstance):
    def initialize(self):
        if not super().initialize():
            return False
        if not callable(self.namespace.get('run')):
            self._error('initialize',TypeError('Attached script must define run(dt) or run()'))
            return False
        return True

    def _error(self, phase, error):
        self.errors.append(Diagnostic(f'{self.name}.{phase}',str(error),traceback.format_exc()))
        self.running=False
        with self.entity.runtime.changes.context(self.entity,self.name,phase):
            self.entity._changed('script.error',self.name,new=str(error))

    def run(self,*args,**kwargs):
        try:
            self.entity._check()
            if not self.running:
                raise RuntimeError('Script attachment is stopped or failed')
            missing=[k for k in self.definition.components if not self.entity.items.has_value(k)]
            if missing:
                raise ValueError('Missing components: '+', '.join(missing))
            with self.entity.runtime.changes.context(self.entity,self.name,'run'):
                self.namespace['self'] = self.entity
                run_func = self.namespace['run']
                import inspect
                try:
                    sig = inspect.signature(run_func)
                    params = sig.parameters
                    param_count = len(params)
                except (ValueError, TypeError):
                    params = {}
                    param_count = None

                if param_count == 0:
                    return run_func()
                elif param_count == 1:
                    pname = list(params.keys())[0]
                    if pname in ("entity", "e", "ent", "target"):
                        return run_func(self.entity)
                    elif pname in ("dt", "delta") and args and isinstance(args[0], (int, float)):
                        return run_func(args[0])
                    elif args:
                        return run_func(args[0])
                    else:
                        return run_func(self.entity)
                elif param_count == 2:
                    pnames = list(params.keys())
                    dt = args[0] if (args and isinstance(args[0], (int, float))) else (args[1] if (len(args) > 1 and isinstance(args[1], (int, float))) else 0.0)
                    if pnames[0] in ("dt", "delta"):
                        return run_func(dt, self.entity)
                    else:
                        return run_func(self.entity, dt)
                else:
                    return run_func(self.entity, *args, **kwargs)
        except Exception as error:
            # A failed call does not disable the orchestrator or other entities.
            self.errors.append(Diagnostic(f'{self.name}.run',str(error),traceback.format_exc()))
            with self.entity.runtime.changes.context(self.entity,self.name,'run'):
                self.entity._changed('script.error',self.name,new=str(error))
            return None


class Scripts(MutableMapping):
    def __init__(self,entity):
        self._entity=entity
        from .items import NamedValues
        self._values=NamedValues(entity, ScriptInstance)

    def __getitem__(self,key):
        self._entity._check()
        return self._values[str(identity(self._entity,key))]

    def __iter__(self):
        self._entity._check()
        return iter(tuple(self._values))

    def __contains__(self,key):
        try:
            return str(identity(self._entity,key)) in self._values
        except (ValueError,TypeError):
            return False

    def __len__(self):
        self._entity._check()
        return len(self._values)

    def __setitem__(self,key,definition):
        if str(identity(self._entity,key)) != str(identity(self._entity,definition)):
            raise ValueError('Script key must match its asset UUID')
        self.attach(definition)

    def __delitem__(self,key):
        instance=self[key]
        del self._values[instance.name]
        instance.stop()
        self._entity._changed('script.detach',instance.name)

    def attach(self,reference, *, item_identity=None, activate=True):
        self._entity._check()
        if self._entity._destroying:
            raise RuntimeError('Cannot attach scripts during destruction')
        definition=reference if isinstance(reference,SystemDefinition) else self._entity.runtime.assets.resolve(reference)
        uid=identity(self._entity,definition)
        if uid is None:
            raise ValueError('Script must have a registered asset UUID')
        key=str(uid)
        if key in self._values:
            raise ValueError('Script is already attached')
        instance=ScriptInstance(self._entity,key,definition,identity=item_identity)
        self._values[key]=instance
        self._entity._changed('script.attach',key)
        if activate and instance.initialize() and self._entity.alive and self._values.get(key) is instance:
            instance.start()
        return instance

    def reload(self, key, definition):
        current=self[key]
        candidate=ScriptInstance(self._entity,current.name,definition,identity=current.id)
        if not candidate.initialize():
            current.errors.extend(candidate.errors)
            return current
        if not self._entity.alive or self._values.get(current.name) is not current:
            candidate.stop()
            return current
        current.stop()
        if not self._entity.alive or self._values.get(current.name) is not current:
            candidate.stop()
            return current
        self._values[current.name]=candidate
        candidate.start()
        self._entity._changed('script.reload',current.name)
        return candidate

    def relocate(self,key,path,*,new_name=None):
        current=self[key]
        current.definition=SystemDefinition(current.definition.source,str(path),current.definition.asset_id)
        current.namespace['__file__']=str(path)
        self._entity._changed('script.relocate',current.name)
        return current

    def run(self,reference,*args,**kwargs):
        try:
            return self[reference].run(*args,**kwargs)
        except Exception as error:
            self._entity._changed('script.error',str(reference),new=str(error))
            return None
