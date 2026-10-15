from collections.abc import MutableMapping
import importlib


from LBE import Error, Kernel


def test_entity_roundtrip_and_id_mapping(tmp_path):
    kernel = Kernel(tmp_path)
    entity = kernel.create_entity(name="Player", components={"Health": {"current": 100}})
    assert not isinstance(entity, Error)
    persistent_id = kernel.get_storage_id(entity)
    assert isinstance(persistent_id, bytes)
    assert len(persistent_id) == 16  # CURRENT format, not a policy endorsement
    assert kernel.get_resource_id(persistent_id) == entity

    assert kernel.set_component(entity, "Health", {"current": 85}) is None
    assert kernel.is_dirty(entity)
    assert kernel.save_dirty_resources() is None
    assert not kernel.is_dirty(entity)

    reloaded = Kernel(tmp_path)
    loaded = reloaded.load_entity(persistent_id)
    assert not isinstance(loaded, Error)
    assert reloaded.get_component(loaded, "Health") == {"current": 85}


def test_direct_component_edit_should_be_persisted_or_prevented(tmp_path):
    kernel = Kernel(tmp_path)
    entity = kernel.create_entity(components={"Health": {"current": 100}})
    assert isinstance(entity, int)
    assert kernel.save_dirty_resources() is None

    component = kernel.get_component(entity, "Health")
    assert isinstance(component, MutableMapping)
    assert not isinstance(component, dict)
    component["current"] = 55
    assert kernel.is_dirty(entity)


def test_queue_module_should_import():
    importlib.import_module("LBE.Queue")
