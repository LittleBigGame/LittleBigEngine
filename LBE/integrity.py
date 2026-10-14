import re
from typing import Any

from .types import Error, InvalidResourceDataError, Entity
from .logger import logger


resource_data_requires = ("data", "type")
resource_data_may_have = ("name", "dependencies", "metadata", "children")

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
        logger.trace(f"Validation failed: UI component '{canonical_name}' field '{field}' is not a string", channel="integrity", error=err)
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
        logger.trace(f"Validation failed: UI component '{canonical_name}' field '{field}' invalid reference", channel="integrity", error=err)
        return err
    sid = match.group("sid")
    if len(sid) not in (32, 64):
        err = Error(
            message="Invalid UI event handler reference",
            description=f"UI component '{canonical_name}' field '{field}' reference '{ref}' has invalid hex storage ID length ({len(sid)}). Must be 32 or 64 hex characters!",
            data={"component_name": canonical_name, "field": field, "value": ref},
            code=InvalidResourceDataError,
        )
        logger.trace(f"Validation failed: UI component '{canonical_name}' field '{field}' invalid hex length", channel="integrity", error=err)
        return err
    return None


class Validate:
    @staticmethod
    def resource_data(resource_data: dict) -> Error | None:
        """Validate the resource data envelope and fields."""
        if not isinstance(resource_data, dict):
            err = Error(
                message="Invalid resource data",
                description=f"Resource data must be a dictionary, got {type(resource_data).__name__} instead!",
                data={"resource_data": resource_data},
                code=InvalidResourceDataError,
            )
            logger.trace("Validation failed: payload is not a dict", channel="integrity", error=err)
            return err

        # 1. Check required keys
        for resource_data_key in resource_data_requires:
            if resource_data_key not in resource_data:
                err = Error(
                    message="Invalid resource data",
                    description=f"Resource data must contain the key '{resource_data_key}', but it was not found!",
                    data={"resource_data": resource_data, "missing_key": resource_data_key},
                    code=InvalidResourceDataError,
                )
                logger.trace(f"Validation failed: missing required key '{resource_data_key}'", channel="integrity", error=err)
                return err

        # 2. Check for unknown/unexpected keys
        valid_keys = set(resource_data_requires) | set(resource_data_may_have)
        for key in resource_data:
            if key not in valid_keys:
                err = Error(
                    message="Invalid resource data",
                    description=f"Resource data contains unknown key '{key}'!",
                    data={"resource_data": resource_data, "unknown_key": key},
                    code=InvalidResourceDataError,
                )
                logger.trace(f"Validation failed: unexpected key '{key}'", channel="integrity", error=err)
                return err

        # 3. Validate 'type'
        res_type = resource_data.get("type")
        if not isinstance(res_type, int) or isinstance(res_type, bool):
            err = Error(
                message="Invalid resource data",
                description=f"Resource type must be an integer ResourceType, got {type(res_type).__name__} instead!",
                data={"resource_data": resource_data, "type": res_type},
                code=InvalidResourceDataError,
            )
            logger.trace("Validation failed: 'type' is not an integer", channel="integrity", error=err)
            return err

        # 4. Validate 'data'
        res_data = resource_data.get("data")
        if not isinstance(res_data, dict):
            err = Error(
                message="Invalid resource data",
                description=f"Resource 'data' must be a dictionary, got {type(res_data).__name__} instead!",
                data={"resource_data": resource_data, "data": res_data},
                code=InvalidResourceDataError,
            )
            logger.trace("Validation failed: 'data' is not a dictionary", channel="integrity", error=err)
            return err

        # 5. Validate optional 'name' if provided
        if "name" in resource_data:
            res_name = resource_data["name"]
            if not isinstance(res_name, str):
                err = Error(
                    message="Invalid resource data",
                    description=f"Resource 'name' must be a string, got {type(res_name).__name__} instead!",
                    data={"resource_data": resource_data, "name": res_name},
                    code=InvalidResourceDataError,
                )
                logger.trace("Validation failed: optional 'name' is not a string", channel="integrity", error=err)
                return err
            if len(res_name.strip()) == 0:
                err = Error(
                    message="Invalid resource data",
                    description="Resource 'name' cannot be empty or whitespace only!",
                    data={"resource_data": resource_data, "name": res_name},
                    code=InvalidResourceDataError,
                )
                logger.trace("Validation failed: optional 'name' is empty", channel="integrity", error=err)
                return err

        # 6. Validate optional 'dependencies' if provided
        if "dependencies" in resource_data:
            dependencies = resource_data["dependencies"]
            if not isinstance(dependencies, list):
                err = Error(
                    message="Invalid resource data",
                    description=f"Resource 'dependencies' must be a list, got {type(dependencies).__name__} instead!",
                    data={"resource_data": resource_data, "dependencies": dependencies},
                    code=InvalidResourceDataError,
                )
                logger.trace("Validation failed: 'dependencies' is not a list", channel="integrity", error=err)
                return err

        # 7. Validate optional 'metadata' if provided
        if "metadata" in resource_data:
            metadata = resource_data["metadata"]
            if not isinstance(metadata, dict):
                err = Error(
                    message="Invalid resource data",
                    description=f"Resource 'metadata' must be a dictionary, got {type(metadata).__name__} instead!",
                    data={"resource_data": resource_data, "metadata": metadata},
                    code=InvalidResourceDataError,
                )
                logger.trace("Validation failed: 'metadata' is not a dict", channel="integrity", error=err)
                return err

        # 8. Validate optional 'children' if provided
        if "children" in resource_data:
            children = resource_data["children"]
            if not isinstance(children, list):
                err = Error(
                    message="Invalid resource data",
                    description=f"Resource 'children' must be a list, got {type(children).__name__} instead!",
                    data={"resource_data": resource_data, "children": children},
                    code=InvalidResourceDataError,
                )
                logger.trace("Validation failed: 'children' is not a list", channel="integrity", error=err)
                return err

        # 9. Entity-specific data validation if res_type == Entity
        if res_type == Entity:
            allowed_entity_data_keys = {"components", "resources", "scripts", "parent", "children"}
            for key in res_data:
                if key not in allowed_entity_data_keys:
                    err = Error(
                        message="Invalid entity resource data",
                        description=f"Entity resource 'data' contains unexpected key '{key}'. Entities may only contain 'components', 'resources', 'scripts', 'parent', and 'children'!",
                        data={"resource_data": resource_data, "unexpected_key": key},
                        code=InvalidResourceDataError,
                    )
                    logger.trace(f"Validation failed: entity has unexpected key '{key}'", channel="integrity", error=err)
                    return err

            if "components" not in res_data:
                err = Error(
                    message="Invalid entity resource data",
                    description="Entity resource 'data' must contain a 'components' dictionary!",
                    data={"resource_data": resource_data},
                    code=InvalidResourceDataError,
                )
                logger.trace("Validation failed: entity missing 'components'", channel="integrity", error=err)
                return err

            components = res_data["components"]
            if not isinstance(components, dict):
                err = Error(
                    message="Invalid entity resource data",
                    description=f"Entity 'components' must be a dictionary, got {type(components).__name__} instead!",
                    data={"resource_data": resource_data, "components": components},
                    code=InvalidResourceDataError,
                )
                logger.trace("Validation failed: entity 'components' is not a dict", channel="integrity", error=err)
                return err

            for comp_name, comp_val in components.items():
                if not isinstance(comp_name, str):
                    err = Error(
                        message="Invalid entity resource data",
                        description=f"Component name must be a string, got {type(comp_name).__name__} instead!",
                        data={"component_name": comp_name},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: component name is not a string", channel="integrity", error=err)
                    return err
                if not isinstance(comp_val, dict):
                    err = Error(
                        message="Invalid entity resource data",
                        description=f"Component '{comp_name}' data must be a dictionary, got {type(comp_val).__name__} instead!",
                        data={"component_name": comp_name, "component_data": comp_val},
                        code=InvalidResourceDataError,
                    )
                    logger.trace(f"Validation failed: component '{comp_name}' data is not a dict", channel="integrity", error=err)
                    return err

                ui_err = Validate.ui_component(comp_name, comp_val)
                if isinstance(ui_err, Error):
                    return ui_err

            if "resources" in res_data:
                res_list = res_data["resources"]
                if not isinstance(res_list, list):
                    err = Error(
                        message="Invalid entity resource data",
                        description=f"Entity 'resources' must be a list, got {type(res_list).__name__} instead!",
                        data={"resource_data": resource_data, "resources": res_list},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: entity 'resources' is not a list", channel="integrity", error=err)
                    return err

            if "scripts" in res_data:
                scripts_list = res_data["scripts"]
                if not isinstance(scripts_list, list):
                    err = Error(
                        message="Invalid entity resource data",
                        description=f"Entity 'scripts' must be a list, got {type(scripts_list).__name__} instead!",
                        data={"resource_data": resource_data, "scripts": scripts_list},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: entity 'scripts' is not a list", channel="integrity", error=err)
                    return err
                for item in scripts_list:
                    if not isinstance(item, str):
                        err = Error(
                            message="Invalid entity resource data",
                            description=f"Entity 'scripts' elements must be strings, got {type(item).__name__} instead!",
                            data={"resource_data": resource_data, "scripts": scripts_list, "invalid_item": item},
                            code=InvalidResourceDataError,
                        )
                        logger.trace("Validation failed: entity 'scripts' element is not a string", channel="integrity", error=err)
                        return err

            if "parent" in res_data:
                parent_val = res_data["parent"]
                if parent_val is not None:
                    if not isinstance(parent_val, str):
                        err = Error(
                            message="Invalid entity resource data",
                            description=f"Entity 'parent' must be a hex string or None, got {type(parent_val).__name__} instead!",
                            data={"resource_data": resource_data, "parent": parent_val},
                            code=InvalidResourceDataError,
                        )
                        logger.trace("Validation failed: entity 'parent' is not a string or None", channel="integrity", error=err)
                        return err
                    try:
                        if len(parent_val) != 32 or len(bytes.fromhex(parent_val)) != 16:
                            raise ValueError()
                    except ValueError:
                        err = Error(
                            message="Invalid entity resource data",
                            description=f"Entity 'parent' must be a 32-character hex string, got '{parent_val}'!",
                            data={"resource_data": resource_data, "parent": parent_val},
                            code=InvalidResourceDataError,
                        )
                        logger.trace("Validation failed: entity 'parent' is not a valid 32-char hex string", channel="integrity", error=err)
                        return err

            if "children" in res_data:
                children_val = res_data["children"]
                if not isinstance(children_val, list):
                    err = Error(
                        message="Invalid entity resource data",
                        description=f"Entity 'children' must be a list, got {type(children_val).__name__} instead!",
                        data={"resource_data": resource_data, "children": children_val},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: entity 'children' is not a list", channel="integrity", error=err)
                    return err
                for child_item in children_val:
                    if not isinstance(child_item, str):
                        err = Error(
                            message="Invalid entity resource data",
                            description=f"Entity 'children' elements must be hex strings, got {type(child_item).__name__} instead!",
                            data={"resource_data": resource_data, "children": children_val, "invalid_item": child_item},
                            code=InvalidResourceDataError,
                        )
                        logger.trace("Validation failed: entity 'children' item is not a string", channel="integrity", error=err)
                        return err
                    try:
                        if len(child_item) != 32 or len(bytes.fromhex(child_item)) != 16:
                            raise ValueError()
                    except ValueError:
                        err = Error(
                            message="Invalid entity resource data",
                            description=f"Entity 'children' element must be a 32-character hex string, got '{child_item}'!",
                            data={"resource_data": resource_data, "children": children_val, "invalid_item": child_item},
                            code=InvalidResourceDataError,
                        )
                        logger.trace("Validation failed: entity 'children' item is not valid 32-char hex string", channel="integrity", error=err)
                        return err

        logger.trace("Resource passed schema integrity checks", channel="integrity")
        return None

    @staticmethod
    def ui_component(component_name: str, component_data: dict) -> Error | None:
        """Validate known UI component types when present on an entity."""
        if not isinstance(component_name, str):
            return None

        canonical_name = UI_COMPONENT_ALIASES.get(component_name.lower())
        if canonical_name is None:
            return None

        # Exempt internal workstation panels from standard UIPanel validation:
        if canonical_name == "UIPanel" and isinstance(component_data, dict) and "panel_type" in component_data:
            return None

        if not isinstance(component_data, dict):
            err = Error(
                message="Invalid UI component data",
                description=f"UI component '{canonical_name}' data must be a dictionary, got {type(component_data).__name__} instead!",
                data={"component_name": component_name, "component_data": component_data},
                code=InvalidResourceDataError,
            )
            logger.trace("Validation failed: UI component data is not a dict", channel="integrity", error=err)
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
                logger.trace(f"Validation failed: UI component '{canonical_name}' unexpected key '{key}'", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UIContainer invalid layout", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UIContainer invalid gap", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UIContainer invalid padding", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UIContainer invalid columns", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UIContainer invalid collapsible", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UIContainer invalid collapsed", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UIButton invalid label", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UIButton invalid width", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UIButton invalid height", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UIButton invalid enabled", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UISlider invalid label", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UISlider invalid min", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UISlider invalid max", channel="integrity", error=err)
                    return err
            if "min" in component_data and "max" in component_data:
                if component_data["min"] > component_data["max"]:
                    err = Error(
                        message="Invalid UI component data",
                        description=f"UISlider 'min' ({component_data['min']}) cannot be greater than 'max' ({component_data['max']})!",
                        data={"component_name": canonical_name, "min": component_data["min"], "max": component_data["max"]},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Validation failed: UISlider min > max", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UISlider invalid value", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UISlider invalid step", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UITextInput invalid label", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UITextInput invalid text", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UITextInput invalid hint", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UITextInput invalid is_search", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UIText invalid content", channel="integrity", error=err)
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
                        logger.trace("Validation failed: UIText invalid color type", channel="integrity", error=err)
                        return err
                    if len(color) not in (3, 4) or not all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in color):
                        err = Error(
                            message="Invalid UI component data",
                            description=f"UIText 'color' elements must be 3 or 4 numbers (RGB or RGBA), got {color!r}!",
                            data={"component_name": canonical_name, "field": "color", "value": color},
                            code=InvalidResourceDataError,
                        )
                        logger.trace("Validation failed: UIText invalid color elements", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UIText invalid bullet", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UIPanel invalid title", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UIPanel invalid width", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UIPanel invalid height", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UIPanel invalid minimized", channel="integrity", error=err)
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
                    logger.trace("Validation failed: UIPanel invalid closable", channel="integrity", error=err)
                    return err

        return None