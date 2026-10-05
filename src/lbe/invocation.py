"""Bind supported script signatures before executing each callback exactly once."""

import inspect

ENTITY_NAMES = {'self', 'entity', 'e', 'ent', 'target'}
TIME_NAMES = {'dt', 'delta'}


def invoke(callback, entity, args=(), kwargs=None):
    kwargs = dict(kwargs or {})
    args = tuple(args)
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        return callback(*args, **kwargs)
    parameters = tuple(signature.parameters.values())
    positional = tuple(p for p in parameters if p.kind in (
        inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD))
    for parameter in parameters:
        if parameter.kind == inspect.Parameter.KEYWORD_ONLY:
            if parameter.name in ENTITY_NAMES:
                kwargs.setdefault(parameter.name, entity)
            elif parameter.name in TIME_NAMES and args:
                kwargs.setdefault(parameter.name, args[0])
    if positional and positional[0].name in ENTITY_NAMES:
        candidates = [(entity, *args), args]
    elif len(positional) > 1 and positional[0].name in TIME_NAMES and positional[1].name in ENTITY_NAMES:
        candidates = [(args[0] if args else 0.0, entity, *args[1:]), args]
    else:
        candidates = [args, (), (entity, *args)]
    for candidate in candidates:
        try:
            signature.bind(*candidate, **kwargs)
        except TypeError:
            continue
        return callback(*candidate, **kwargs)
    # Preserve the useful binding error without executing an incompatible call.
    signature.bind(*candidates[0], **kwargs)
