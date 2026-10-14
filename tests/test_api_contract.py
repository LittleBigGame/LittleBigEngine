"""Lock a few observable prototype interfaces until an approved migration."""

import inspect

from LBE import Kernel


def test_current_kernel_entrypoints_exist():
    for method in (
        "create_resource", "load_resource", "save_resource", "get_resource_id",
        "get_storage_id", "create_entity", "load_entity", "get_component",
        "set_component", "remove_component", "save_dirty_resources",
    ):
        assert callable(getattr(Kernel, method))


def test_kernel_constructor_has_storage_directory():
    parameters = inspect.signature(Kernel).parameters
    assert "folder_location" in parameters
