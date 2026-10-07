"""Attached behavior with per-entity requirements and isolated execution."""
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
