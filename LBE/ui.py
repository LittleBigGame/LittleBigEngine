"""Data-driven UI creation and event adapters.

These functions operate on the Kernel's authoritative state.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import copy
import inspect
import re

from .logger import logger
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

UI_SCHEMAS: dict[str, dict[str, Any]] = {
    "UIContainer": {
        "layout": "vertical",
        "gap": 4.0,
        "padding": 4.0,
        "columns": 2,
        "collapsible": False,
        "collapsed": False,
    },
    "UIButton": {
        "label": "",
        "width": 0.0,
        "height": 0.0,
        "on_click": "",
        "enabled": True,
    },
    "UISlider": {
        "label": "",
        "min": 0.0,
        "max": 1.0,
        "value": 0.0,
        "step": 0.01,
        "on_change": "",
    },
    "UITextInput": {
        "label": "",
        "text": "",
        "hint": "",
        "is_search": False,
        "on_change": "",
    },
    "UIText": {
        "content": "",
        "color": None,
        "bullet": False,
    },
    "UIPanel": {
        "title": "Panel",
        "width": 300.0,
        "height": 400.0,
        "minimized": False,
        "closable": True,
    },
}

UI_COMPONENT_NAMES: dict[str, str] = {
    "uicontainer": "UIContainer",
    "uibutton": "UIButton",
    "uislider": "UISlider",
    "uitextinput": "UITextInput",
    "uitext": "UIText",
    "uipanel": "UIPanel",
}

UI_COMPONENT_ALIASES: dict[str, str] = {
    **UI_COMPONENT_NAMES,
    "container": "UIContainer",
    "button": "UIButton",
    "slider": "UISlider",
    "textinput": "UITextInput",
    "text_input": "UITextInput",
    "text": "UIText",
    "panel": "UIPanel",
}

UI_EVENT_HANDLER_REGEX = re.compile(r"^<\|1\|(?P<sid>[0-9a-fA-F]+)\|>\.(?P<fn>[a-zA-Z_][a-zA-Z0-9_]*)$")


def _validate_handler_ref(canonical_name: str, field: str, ref: Any) -> Error | None:
    if ref is None:
        return None
    if not isinstance(ref, str):
        err = Error(
            message="Invalid UI component data",
            description=f"UI component '{canonical_name}' field '{field}' must be a string or None, got {type(ref).__name__} instead!",
            data={"component_name": canonical_name, "field": field, "value": ref},
            code=InvalidResourceDataError,
        )
        logger.trace(f"Validation failed: UI component '{canonical_name}' field '{field}' is not a string", channel="ui", error=err)
        return err
    if ref == "":
        return None
    ref_stripped = ref.strip()
    if ref_stripped == "":
        return None
    match = UI_EVENT_HANDLER_REGEX.match(ref_stripped)
    if not match:
        err = Error(
            message="Invalid UI event handler reference",
            description=f"UI component '{canonical_name}' field '{field}' reference '{ref}' is invalid. Must match '<|1|<storage_id_hex>|>.<function_name>'",
            data={"component_name": canonical_name, "field": field, "value": ref},
            code=InvalidResourceDataError,
        )
        logger.trace(f"Validation failed: UI component '{canonical_name}' field '{field}' invalid reference", channel="ui", error=err)
        return err
    sid = match.group("sid")
    if len(sid) not in (32, 64):
        err = Error(
            message="Invalid UI event handler reference",
            description=f"UI component '{canonical_name}' field '{field}' reference '{ref}' has invalid hex storage ID length ({len(sid)}). Must be 32 or 64 hex characters!",
            data={"component_name": canonical_name, "field": field, "value": ref},
            code=InvalidResourceDataError,
        )
        logger.trace(f"Validation failed: UI component '{canonical_name}' field '{field}' invalid hex length", channel="ui", error=err)
        return err
    return None


class ValidateUI:
    @staticmethod
    def validate_ui_component(component_name: str, component_data: Any) -> Error | None:
        """Validate known UI component types when present on an entity."""
        if not isinstance(component_name, str):
            return None

        canonical_name = UI_COMPONENT_ALIASES.get(component_name.lower())
        if canonical_name is None:
            return None

        # Exempt internal workstation panels from standard UIPanel validation:
        if canonical_name == "UIPanel" and isinstance(component_data, Mapping) and "panel_type" in component_data:
            return None

        if not isinstance(component_data, Mapping):
            err = Error(
                message="Invalid UI component data",
                description=f"UI component '{canonical_name}' data must be a dictionary, got {type(component_data).__name__} instead!",
                data={"component_name": component_name, "component_data": component_data},
                code=InvalidResourceDataError,
            )
            logger.trace("Validation failed: UI component data is not a dict", channel="ui", error=err)
            return err

        allowed_keys = set(UI_SCHEMAS[canonical_name].keys())
        for key in component_data:
            if key not in allowed_keys:
                err = Error(
                    message="Invalid UI component data",
                    description=f"UI component '{canonical_name}' contains unexpected key '{key}'!",
                    data={"component_name": canonical_name, "unexpected_key": key},
                    code=InvalidResourceDataError,
                )
                logger.trace(f"Validation failed: UI component '{canonical_name}' unexpected key '{key}'", channel="ui", error=err)
                return err

        if canonical_name == "UIContainer":
            if "layout" in component_data:
                layout = component_data["layout"]
                if not isinstance(layout, str) or layout not in ("vertical", "horizontal", "grid"):
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UIContainer 'layout' must be 'vertical', 'horizontal', or 'grid', got {layout!r}!",
                        data={"component_name": canonical_name, "field": "layout", "value": layout},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UIContainer invalid layout", channel="ui", error=err)
                    return err
            if "gap" in component_data:
                gap = component_data["gap"]
                if not isinstance(gap, (int, float)) or isinstance(gap, bool) or gap < 0:
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UIContainer 'gap' must be a non-negative number, got {gap!r}!",
                        data={"component_name": canonical_name, "field": "gap", "value": gap},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UIContainer invalid gap", channel="ui", error=err)
                    return err
            if "padding" in component_data:
                padding = component_data["padding"]
                if not isinstance(padding, (int, float)) or isinstance(padding, bool) or padding < 0:
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UIContainer 'padding' must be a non-negative number, got {padding!r}!",
                        data={"component_name": canonical_name, "field": "padding", "value": padding},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UIContainer invalid padding", channel="ui", error=err)
                    return err
            if "columns" in component_data:
                columns = component_data["columns"]
                if not isinstance(columns, int) or isinstance(columns, bool) or columns < 1:
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UIContainer 'columns' must be an integer >= 1, got {columns!r}!",
                        data={"component_name": canonical_name, "field": "columns", "value": columns},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UIContainer invalid columns", channel="ui", error=err)
                    return err
            if "collapsible" in component_data:
                collapsible = component_data["collapsible"]
                if not isinstance(collapsible, bool):
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UIContainer 'collapsible' must be a boolean, got {collapsible!r}!",
                        data={"component_name": canonical_name, "field": "collapsible", "value": collapsible},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UIContainer invalid collapsible", channel="ui", error=err)
                    return err
            if "collapsed" in component_data:
                collapsed = component_data["collapsed"]
                if not isinstance(collapsed, bool):
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UIContainer 'collapsed' must be a boolean, got {collapsed!r}!",
                        data={"component_name": canonical_name, "field": "collapsed", "value": collapsed},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UIContainer invalid collapsed", channel="ui", error=err)
                    return err

        elif canonical_name == "UIButton":
            if "label" in component_data:
                label = component_data["label"]
                if not isinstance(label, str):
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UIButton 'label' must be a string, got {type(label).__name__}!",
                        data={"component_name": canonical_name, "field": "label", "value": label},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UIButton invalid label", channel="ui", error=err)
                    return err
            if "width" in component_data:
                width = component_data["width"]
                if not isinstance(width, (int, float)) or isinstance(width, bool) or width < 0:
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UIButton 'width' must be a non-negative number, got {width!r}!",
                        data={"component_name": canonical_name, "field": "width", "value": width},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UIButton invalid width", channel="ui", error=err)
                    return err
            if "height" in component_data:
                height = component_data["height"]
                if not isinstance(height, (int, float)) or isinstance(height, bool) or height < 0:
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UIButton 'height' must be a non-negative number, got {height!r}!",
                        data={"component_name": canonical_name, "field": "height", "value": height},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UIButton invalid height", channel="ui", error=err)
                    return err
            if "on_click" in component_data:
                ref_err = _validate_handler_ref(canonical_name, "on_click", component_data["on_click"])
                if isinstance(ref_err, Error):
                    return ref_err
            if "enabled" in component_data:
                enabled = component_data["enabled"]
                if not isinstance(enabled, bool):
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UIButton 'enabled' must be a boolean, got {enabled!r}!",
                        data={"component_name": canonical_name, "field": "enabled", "value": enabled},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UIButton invalid enabled", channel="ui", error=err)
                    return err

        elif canonical_name == "UISlider":
            if "label" in component_data:
                label = component_data["label"]
                if not isinstance(label, str):
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UISlider 'label' must be a string, got {type(label).__name__}!",
                        data={"component_name": canonical_name, "field": "label", "value": label},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UISlider invalid label", channel="ui", error=err)
                    return err
            if "min" in component_data:
                min_val = component_data["min"]
                if not isinstance(min_val, (int, float)) or isinstance(min_val, bool):
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UISlider 'min' must be a number, got {min_val!r}!",
                        data={"component_name": canonical_name, "field": "min", "value": min_val},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UISlider invalid min", channel="ui", error=err)
                    return err
            if "max" in component_data:
                max_val = component_data["max"]
                if not isinstance(max_val, (int, float)) or isinstance(max_val, bool):
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UISlider 'max' must be a number, got {max_val!r}!",
                        data={"component_name": canonical_name, "field": "max", "value": max_val},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UISlider invalid max", channel="ui", error=err)
                    return err
            if "min" in component_data and "max" in component_data:
                min_val = component_data["min"]
                max_val = component_data["max"]
                if min_val > max_val:
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UISlider min ({min_val}) cannot be greater than max ({max_val})",
                        data={"component_name": canonical_name, "min": min_val, "max": max_val},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UISlider min > max", channel="ui", error=err)
                    return err
            if "value" in component_data:
                val = component_data["value"]
                if not isinstance(val, (int, float)) or isinstance(val, bool):
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UISlider 'value' must be a number, got {val!r}!",
                        data={"component_name": canonical_name, "field": "value", "value": val},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UISlider invalid value", channel="ui", error=err)
                    return err
                min_val = component_data.get("min", UI_SCHEMAS["UISlider"]["min"])
                max_val = component_data.get("max", UI_SCHEMAS["UISlider"]["max"])
                if isinstance(min_val, (int, float)) and not isinstance(min_val, bool) and isinstance(max_val, (int, float)) and not isinstance(max_val, bool):
                    if not (min_val <= val <= max_val):
                        err = Error(
                            message="Invalid UI component data",
                            description=f"UISlider value ({val}) is outside [min={min_val}, max={max_val}]",
                            data={"component_name": canonical_name, "field": "value", "value": val, "min": min_val, "max": max_val},
                            code=InvalidResourceDataError,
                        )
                        logger.trace("Validation failed: UISlider value out of bounds", channel="ui", error=err)
                        return err
            if "step" in component_data:
                step = component_data["step"]
                if not isinstance(step, (int, float)) or isinstance(step, bool) or step <= 0:
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UISlider 'step' must be a positive number, got {step!r}!",
                        data={"component_name": canonical_name, "field": "step", "value": step},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UISlider invalid step", channel="ui", error=err)
                    return err
            if "on_change" in component_data:
                ref_err = _validate_handler_ref(canonical_name, "on_change", component_data["on_change"])
                if isinstance(ref_err, Error):
                    return ref_err

        elif canonical_name == "UITextInput":
            if "label" in component_data:
                label = component_data["label"]
                if not isinstance(label, str):
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UITextInput 'label' must be a string, got {type(label).__name__}!",
                        data={"component_name": canonical_name, "field": "label", "value": label},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UITextInput invalid label", channel="ui", error=err)
                    return err
            if "text" in component_data:
                text = component_data["text"]
                if not isinstance(text, str):
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UITextInput 'text' must be a string, got {type(text).__name__}!",
                        data={"component_name": canonical_name, "field": "text", "value": text},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UITextInput invalid text", channel="ui", error=err)
                    return err
            if "hint" in component_data:
                hint = component_data["hint"]
                if not isinstance(hint, str):
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UITextInput 'hint' must be a string, got {type(hint).__name__}!",
                        data={"component_name": canonical_name, "field": "hint", "value": hint},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UITextInput invalid hint", channel="ui", error=err)
                    return err
            if "is_search" in component_data:
                is_search = component_data["is_search"]
                if not isinstance(is_search, bool):
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UITextInput 'is_search' must be a boolean, got {is_search!r}!",
                        data={"component_name": canonical_name, "field": "is_search", "value": is_search},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UITextInput invalid is_search", channel="ui", error=err)
                    return err
            if "on_change" in component_data:
                ref_err = _validate_handler_ref(canonical_name, "on_change", component_data["on_change"])
                if isinstance(ref_err, Error):
                    return ref_err

        elif canonical_name == "UIText":
            if "content" in component_data:
                content = component_data["content"]
                if not isinstance(content, str):
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UIText 'content' must be a string, got {type(content).__name__}!",
                        data={"component_name": canonical_name, "field": "content", "value": content},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UIText invalid content", channel="ui", error=err)
                    return err
            if "color" in component_data:
                color = component_data["color"]
                if color is not None:
                    if not isinstance(color, list):
                        err = Error(
                            message="Invalid UI component data",
                            description=f"UIText 'color' must be a list or None, got {type(color).__name__}!",
                            data={"component_name": canonical_name, "field": "color", "value": color},
                            code=InvalidResourceDataError,
                        )
                        logger.trace("Validation failed: UIText invalid color type", channel="ui", error=err)
                        return err
                    if len(color) not in (3, 4) or not all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in color):
                        err = Error(
                            message="Invalid UI component data",
                            description=f"UIText 'color' elements must be 3 or 4 numbers (RGB or RGBA), got {color!r}!",
                            data={"component_name": canonical_name, "field": "color", "value": color},
                            code=InvalidResourceDataError,
                        )
                        logger.trace("Validation failed: UIText invalid color elements", channel="ui", error=err)
                        return err
            if "bullet" in component_data:
                bullet = component_data["bullet"]
                if not isinstance(bullet, bool):
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UIText 'bullet' must be a boolean, got {bullet!r}!",
                        data={"component_name": canonical_name, "field": "bullet", "value": bullet},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UIText invalid bullet", channel="ui", error=err)
                    return err

        elif canonical_name == "UIPanel":
            if "title" in component_data:
                title = component_data["title"]
                if not isinstance(title, str):
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UIPanel 'title' must be a string, got {type(title).__name__}!",
                        data={"component_name": canonical_name, "field": "title", "value": title},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UIPanel invalid title", channel="ui", error=err)
                    return err
            if "width" in component_data:
                width = component_data["width"]
                if not isinstance(width, (int, float)) or isinstance(width, bool) or width < 50.0:
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UIPanel 'width' must be a number >= 50.0, got {width!r}!",
                        data={"component_name": canonical_name, "field": "width", "value": width},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UIPanel invalid width", channel="ui", error=err)
                    return err
            if "height" in component_data:
                height = component_data["height"]
                if not isinstance(height, (int, float)) or isinstance(height, bool) or height < 50.0:
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UIPanel 'height' must be a number >= 50.0, got {height!r}!",
                        data={"component_name": canonical_name, "field": "height", "value": height},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UIPanel invalid height", channel="ui", error=err)
                    return err
            if "minimized" in component_data:
                minimized = component_data["minimized"]
                if not isinstance(minimized, bool):
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UIPanel 'minimized' must be a boolean, got {minimized!r}!",
                        data={"component_name": canonical_name, "field": "minimized", "value": minimized},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UIPanel invalid minimized", channel="ui", error=err)
                    return err
            if "closable" in component_data:
                closable = component_data["closable"]
                if not isinstance(closable, bool):
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UIPanel 'closable' must be a boolean, got {closable!r}!",
                        data={"component_name": canonical_name, "field": "closable", "value": closable},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UIPanel invalid closable", channel="ui", error=err)
                    return err

        return None

    ui_component = validate_ui_component


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

    val_err = ValidateUI.validate_ui_component(canonical_type, props)
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
    bubble: bool = True,
    **kwargs: Any,
) -> Any | Error:
    """Trigger a UI event handler on an Entity with generation safety and optional event bubbling."""
    if hasattr(entity_id, "id"):
        entity_id = entity_id.id

    if not self.is_valid_runtime_id(entity_id):
        err = Error(
            message="Entity not found",
            description=f"Runtime ID {entity_id} is invalid or stale (referencing a deleted resource)!",
            data={"entity_id": entity_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to trigger UI event: entity not found or stale", channel="ui", error=err, entity_id=entity_id)
        return err

    resolved_id = self._resolve_handle(entity_id)
    if resolved_id not in self.resources:
        err = Error(
            message="Entity not found",
            description=f"RuntimeID {entity_id} was not found in memory!",
            data={"entity_id": entity_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to trigger UI event: entity not found", channel="ui", error=err, entity_id=entity_id)
        return err

    res = self.resources[resolved_id]
    if res.get("type") != Entity:
        err = Error(
            message="Resource is not an entity",
            description=f"RuntimeID {entity_id} has type {res.get('type')}, expected Entity ({Entity})!",
            data={"entity_id": entity_id, "type": res.get("type")},
            code=EntityTypeMismatchError,
        )
        logger.trace("Failed to trigger UI event: not an entity", channel="ui", error=err, entity_id=entity_id)
        return err

    curr_id: RuntimeID | None = entity_id
    target_keys = (event_name, f"on_{event_name}" if not event_name.startswith("on_") else event_name)
    visited: set[RuntimeID] = set()

    while curr_id is not None and curr_id not in visited:
        visited.add(curr_id)
        if not self.is_valid_runtime_id(curr_id):
            break

        curr_resolved = self._resolve_handle(curr_id)
        curr_res = self.resources.get(curr_resolved)
        if not curr_res or curr_res.get("type") != Entity:
            break

        components = curr_res.get("data", {}).get("components", {})
        handler_ref = None
        found_key = False
        if isinstance(components, dict):
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

        if found_key and handler_ref is not None:
            if isinstance(handler_ref, str) and not handler_ref.strip():
                pass
            else:
                if not isinstance(handler_ref, str):
                    err = Error(
                        message="Invalid UI event handler reference",
                        description=f"Handler attribute '{event_name}' must be a string, got {type(handler_ref).__name__} instead!",
                        data={"entity_id": curr_id, "event_name": event_name, "handler_ref": handler_ref},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Failed to trigger UI event: handler reference not a string", channel="ui", error=err, entity_id=curr_id)
                    return err

                match = UI_EVENT_HANDLER_REGEX.match(handler_ref.strip())
                if not match:
                    err = Error(
                        message="Invalid UI event handler reference",
                        description=f"Handler reference '{handler_ref}' does not match expected pattern '<|1|<storage_id>|>.<function_name>'",
                        data={"entity_id": curr_id, "event_name": event_name, "handler_ref": handler_ref},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Failed to trigger UI event: invalid reference format", channel="ui", error=err, entity_id=curr_id)
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
                        data={"entity_id": curr_id, "handler_ref": handler_ref, "error": str(ex)},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Failed to trigger UI event: function not found", channel="ui", error=err, entity_id=curr_id)
                    return err
                except Exception as ex:
                    err = Error(
                        message="UI event handler failed",
                        description=str(ex),
                        data={"entity_id": curr_id, "handler_ref": handler_ref, "error": str(ex)},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Failed to trigger UI event: error resolving function", channel="ui", error=err, entity_id=curr_id)
                    return err

                if not callable(func):
                    err = Error(
                        message="UI event handler failed",
                        description=f"Attribute '{fn_name}' on script proxy is not callable",
                        data={"entity_id": curr_id, "handler_ref": handler_ref},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Failed to trigger UI event: attribute not callable", channel="ui", error=err, entity_id=curr_id)
                    return err

                entity_proxy = self.get_entity_proxy(curr_id)
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
                        data={"entity_id": curr_id, "event_name": event_name, "error": str(ex)},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Failed to trigger UI event: execution raised exception", channel="ui", error=err, entity_id=curr_id)
                    return err

        if not bubble:
            break

        curr_id = self.get_entity_parent(curr_id)

    return None


