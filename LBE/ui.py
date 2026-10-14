"""Data-driven UI creation and event adapters.

These functions operate on the Kernel's authoritative state.
"""

from __future__ import annotations

from typing import Any
import copy
import inspect

from .logger import logger
from .integrity import Validate, UI_SCHEMAS, UI_COMPONENT_ALIASES, UI_EVENT_HANDLER_REGEX
from .types import (
    StorageID,
    RuntimeID,
    Error,
    RuntimeIDNotFoundOnMemoryError,
    InvalidResourceDataError,
    EntityTypeMismatchError,
    Entity,
    Script,
)

def create_ui_entity(
    self,
    name: str,
    component_type: str,
    component_props: dict | None = None,
    parent_id: RuntimeID | None = None,
    storage_id: StorageID | None = None,
    immediate_save: bool = False,
) -> RuntimeID | Error:
    """Create an entity with the specified UI component pre-populated with default values merged with component_props."""
    if not isinstance(component_type, str):
        err = Error(
            message="Invalid UI component type",
            description=f"UI component type must be a string, got {type(component_type).__name__} instead!",
            data={"component_type": component_type},
            code=InvalidResourceDataError,
        )
        logger.trace("Failed to create UI entity: invalid component type type", channel="ui", error=err)
        return err

    canonical_type = UI_COMPONENT_ALIASES.get(component_type.lower())
    if canonical_type is None:
        err = Error(
            message="Invalid UI component type",
            description=f"Unknown UI component type '{component_type}'",
            data={"component_type": component_type},
            code=InvalidResourceDataError,
        )
        logger.trace("Failed to create UI entity: unknown component type", channel="ui", error=err)
        return err

    props = copy.deepcopy(UI_SCHEMAS[canonical_type])
    if component_props is not None:
        if not isinstance(component_props, dict):
            err = Error(
                message="Invalid UI component props",
                description=f"Component props must be a dictionary, got {type(component_props).__name__} instead!",
                data={"component_props": component_props},
                code=InvalidResourceDataError,
            )
            logger.trace("Failed to create UI entity: invalid props", channel="ui", error=err)
            return err
        props.update(component_props)

    val_err = Validate.ui_component(canonical_type, props)
    if isinstance(val_err, Error):
        return val_err

    return self.create_entity(
        components={canonical_type: props},
        name=name,
        parent_id=parent_id,
        storage_id=storage_id,
        immediate_save=immediate_save,
    )


def trigger_ui_event(
    self,
    entity_id: RuntimeID | Any,
    event_name: str = "on_click",
    *args: Any,
    **kwargs: Any,
) -> Any | Error:
    """Trigger a UI event handler on an Entity."""
    if hasattr(entity_id, "id"):
        entity_id = entity_id.id
    if entity_id not in self.resources:
        err = Error(
            message="Entity not found",
            description=f"RuntimeID {entity_id} was not found in memory!",
            data={"entity_id": entity_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to trigger UI event: entity not found", channel="ui", error=err, entity_id=entity_id)
        return err

    res = self.resources[entity_id]
    if res.get("type") != Entity:
        err = Error(
            message="Resource is not an entity",
            description=f"RuntimeID {entity_id} has type {res.get('type')}, expected Entity ({Entity})!",
            data={"entity_id": entity_id, "type": res.get("type")},
            code=EntityTypeMismatchError,
        )
        logger.trace("Failed to trigger UI event: not an entity", channel="ui", error=err, entity_id=entity_id)
        return err

    components = res.get("data", {}).get("components", {})
    if not isinstance(components, dict):
        return None

    handler_ref = None
    target_keys = (event_name, f"on_{event_name}" if not event_name.startswith("on_") else event_name)
    found_key = False
    for comp in components.values():
        if isinstance(comp, dict):
            for k in target_keys:
                if k in comp:
                    found_key = True
                    val = comp[k]
                    if val:
                        handler_ref = val
                        break
                    elif handler_ref is None:
                        handler_ref = val
            if handler_ref and isinstance(handler_ref, str) and handler_ref.strip():
                break

    if not found_key or handler_ref is None:
        return None

    if isinstance(handler_ref, str) and not handler_ref.strip():
        return None

    if not isinstance(handler_ref, str):
        err = Error(
            message="Invalid UI event handler reference",
            description=f"Handler attribute '{event_name}' must be a string, got {type(handler_ref).__name__} instead!",
            data={"entity_id": entity_id, "event_name": event_name, "handler_ref": handler_ref},
            code=InvalidResourceDataError,
        )
        logger.trace("Failed to trigger UI event: handler reference not a string", channel="ui", error=err, entity_id=entity_id)
        return err

    match = UI_EVENT_HANDLER_REGEX.match(handler_ref.strip())
    if not match:
        err = Error(
            message="Invalid UI event handler reference",
            description=f"Handler reference '{handler_ref}' does not match expected pattern '<|1|<storage_id>|>.<function_name>'",
            data={"entity_id": entity_id, "event_name": event_name, "handler_ref": handler_ref},
            code=InvalidResourceDataError,
        )
        logger.trace("Failed to trigger UI event: invalid reference format", channel="ui", error=err, entity_id=entity_id)
        return err

    sid_hex = match.group("sid")
    fn_name = match.group("fn")

    script_proxy = self.resolve_proxy(Script, sid_hex)
    if isinstance(script_proxy, Error):
        return script_proxy

    try:
        func = getattr(script_proxy, fn_name)
    except AttributeError as ex:
        err = Error(
            message="UI event handler failed",
            description=f"Function '{fn_name}' not found on script proxy: {ex}",
            data={"entity_id": entity_id, "handler_ref": handler_ref, "error": str(ex)},
            code=InvalidResourceDataError,
        )
        logger.trace("Failed to trigger UI event: function not found", channel="ui", error=err, entity_id=entity_id)
        return err
    except Exception as ex:
        err = Error(
            message="UI event handler failed",
            description=str(ex),
            data={"entity_id": entity_id, "handler_ref": handler_ref, "error": str(ex)},
            code=InvalidResourceDataError,
        )
        logger.trace("Failed to trigger UI event: error resolving function", channel="ui", error=err, entity_id=entity_id)
        return err

    if not callable(func):
        err = Error(
            message="UI event handler failed",
            description=f"Attribute '{fn_name}' on script proxy is not callable",
            data={"entity_id": entity_id, "handler_ref": handler_ref},
            code=InvalidResourceDataError,
        )
        logger.trace("Failed to trigger UI event: attribute not callable", channel="ui", error=err, entity_id=entity_id)
        return err

    entity_proxy = self.get_entity_proxy(entity_id)
    if isinstance(entity_proxy, Error):
        return entity_proxy

    pass_entity = True
    try:
        sig = inspect.signature(func)
        params = list(sig.parameters.values())
        if len(params) == 0:
            pass_entity = False
        else:
            has_pos = any(
                p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                for p in params
            )
            if not has_pos:
                pass_entity = False
    except (ValueError, TypeError):
        pass_entity = True

    try:
        if pass_entity:
            try:
                return func(entity_proxy, *args, **kwargs)
            except TypeError as ex:
                if ex.__traceback__ and ex.__traceback__.tb_next is None:
                    return func(*args, **kwargs)
                raise
        else:
            return func(*args, **kwargs)
    except Exception as ex:
        err = Error(
            message="UI event handler failed",
            description=str(ex),
            data={"entity_id": entity_id, "event_name": event_name, "error": str(ex)},
            code=InvalidResourceDataError,
        )
        logger.trace("Failed to trigger UI event: execution raised exception", channel="ui", error=err, entity_id=entity_id)
        return err

