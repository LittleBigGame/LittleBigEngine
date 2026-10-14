from collections.abc import Mapping
import re
from typing import Any

from .types import Error, InvalidResourceDataError, Entity
from .logger import logger


resource_data_requires = ("data", "type")
resource_data_may_have = ("name", "dependencies", "metadata", "children")

from .ui import (
    UI_SCHEMAS,
    UI_COMPONENT_NAMES,
    UI_COMPONENT_ALIASES,
    UI_EVENT_HANDLER_REGEX,
    ValidateUI,
    _validate_handler_ref,
)


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
    def ui_component(component_name: str, component_data: Any) -> Error | None:
        """Validate known UI component types when present on an entity."""
        return ValidateUI.validate_ui_component(component_name, component_data)