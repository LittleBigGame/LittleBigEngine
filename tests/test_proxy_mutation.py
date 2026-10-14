"""Comprehensive independent tests for ComponentProxy and EntityProxy mutation and persistence.

Derives tests from observable user requirements and kernel contracts:
1. ComponentProxy dot and dict mutations mark entities dirty and persist.
2. Non-mutating reads do not mark entities dirty.
3. EntityProxy case-insensitivity, dict/dot access, membership, addition, removal.
4. Error contracts (missing components, non-entities, stale handles).
5. End-to-end multi-kernel persistence roundtrip.
6. Planned tests for unimplemented engine features.
"""

from collections.abc import MutableMapping, MutableSequence
import copy
import json
from types import MappingProxyType

import pytest

from LBE import (
    ComponentProxy,
    EntityProxy,
    Error,
    Kernel,
    ReadOnlySequence,
    ScriptProxy,
    TrackedList,
    extract_script_symbols,
)
from LBE.proxy import _unwrap
from LBE.types import (
    EntityTypeMismatchError,
    RuntimeIDNotFoundOnMemoryError,
)


class TestComponentProxyMutations:
    """Tests for ComponentProxy dictionary and dot-attribute mutations."""

    def test_dict_setitem_marks_dirty_and_persists(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(components={"Health": {"current": 100}})
        assert not isinstance(entity, Error)
        kernel.save_dirty_resources()
        assert not kernel.is_dirty(entity)

        comp = kernel.get_component(entity, "Health")
        assert isinstance(comp, ComponentProxy)
        comp["current"] = 55

        assert kernel.is_dirty(entity)
        assert comp["current"] == 55
        assert kernel.save_dirty_resources() is None
        assert not kernel.is_dirty(entity)

    def test_dot_setattr_marks_dirty_and_persists(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(components={"Health": {"current": 100}})
        assert not isinstance(entity, Error)
        kernel.save_dirty_resources()
        assert not kernel.is_dirty(entity)

        comp = kernel.get_component(entity, "Health")
        assert isinstance(comp, ComponentProxy)
        comp.current = 42

        assert kernel.is_dirty(entity)
        assert comp.current == 42
        assert comp["current"] == 42
        assert kernel.save_dirty_resources() is None
        assert not kernel.is_dirty(entity)

    def test_dict_mutation_methods_mark_dirty(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(components={"Stats": {"str": 10, "dex": 12, "int": 14}})
        assert not isinstance(entity, Error)
        kernel.save_dirty_resources()

        comp = kernel.get_component(entity, "Stats")

        # del item
        del comp["int"]
        assert kernel.is_dirty(entity)
        assert "int" not in comp
        kernel.save_dirty_resources()

        # pop
        val = comp.pop("dex")
        assert val == 12
        assert kernel.is_dirty(entity)
        assert "dex" not in comp
        kernel.save_dirty_resources()

        # update
        comp.update({"vit": 16, "agi": 18})
        assert kernel.is_dirty(entity)
        assert comp.vit == 16
        assert comp.agi == 18
        kernel.save_dirty_resources()

        # setdefault on new key marks dirty
        res = comp.setdefault("luck", 7)
        assert res == 7
        assert kernel.is_dirty(entity)
        assert comp.luck == 7
        kernel.save_dirty_resources()

        # setdefault on existing key does NOT mark dirty
        res = comp.setdefault("luck", 99)
        assert res == 7
        assert not kernel.is_dirty(entity)

        # delattr marks dirty
        del comp.luck
        assert kernel.is_dirty(entity)
        assert "luck" not in comp
        kernel.save_dirty_resources()

        # popitem marks dirty
        comp.popitem()
        assert kernel.is_dirty(entity)
        kernel.save_dirty_resources()

        # clear marks dirty
        comp.clear()
        assert kernel.is_dirty(entity)
        assert len(comp) == 0

    def test_reads_do_not_mark_dirty(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(components={"Health": {"current": 100, "max": 100}})
        assert not isinstance(entity, Error)
        kernel.save_dirty_resources()
        assert not kernel.is_dirty(entity)

        comp = kernel.get_component(entity, "Health")
        assert not kernel.is_dirty(entity)

        # Dot and dict reads
        _ = comp.current
        _ = comp["current"]
        _ = comp.get("current")
        _ = comp.get("missing", 0)
        _ = "current" in comp
        _ = len(comp)
        _ = list(comp.keys())
        _ = list(comp.values())
        _ = list(comp.items())
        _ = comp.to_dict()
        _ = repr(comp)

        assert not kernel.is_dirty(entity), "Pure read operations must not mark entity dirty"

    def test_component_proxy_ior_operator(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(components={"Health": {"current": 100}})
        assert not isinstance(entity, Error)
        kernel.save_dirty_resources()
        comp = kernel.get_component(entity, "Health")

        comp |= {"max": 120, "shield": 10}
        assert kernel.is_dirty(entity)
        assert comp.max == 120
        assert comp.shield == 10
        assert comp["max"] == 120
        assert isinstance(comp, ComponentProxy)

    def test_component_proxy_pop_missing_does_not_mark_dirty(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(components={"Health": {"current": 100}})
        assert not isinstance(entity, Error)
        kernel.save_dirty_resources()
        assert not kernel.is_dirty(entity)
        comp = kernel.get_component(entity, "Health")

        val = comp.pop("nonexistent", "fallback")
        assert val == "fallback"
        assert not kernel.is_dirty(entity), "Popping a missing key with default must not mark entity dirty"

    def test_component_proxy_copy_and_deepcopy(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(components={"Health": {"current": 100, "tags": ["alive", "player"]}})
        assert not isinstance(entity, Error)
        kernel.save_dirty_resources()
        comp = kernel.get_component(entity, "Health")

        shallow = copy.copy(comp)
        assert isinstance(shallow, dict)
        assert not isinstance(shallow, ComponentProxy)
        assert shallow == {"current": 100, "tags": ["alive", "player"]}
        assert not hasattr(shallow, "_kernel")

        deep = copy.deepcopy(comp)
        assert isinstance(deep, dict)
        assert not isinstance(deep, ComponentProxy)
        assert deep == {"current": 100, "tags": ["alive", "player"]}
        assert not hasattr(deep, "_kernel")

        # Mutating copied dicts must NOT mark entity dirty
        shallow["current"] = 50
        assert not kernel.is_dirty(entity)
        deep["tags"].append("mutated")
        assert not kernel.is_dirty(entity)

    def test_component_proxy_errors_and_boundaries(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(components={"Health": {"current": 100}})
        comp = kernel.get_component(entity, "Health")

        with pytest.raises(KeyError):
            _ = comp["nonexistent"]

        with pytest.raises(AttributeError):
            _ = comp.nonexistent

        with pytest.raises(KeyError):
            del comp["nonexistent"]

        with pytest.raises(AttributeError):
            del comp.nonexistent

        with pytest.raises(AttributeError):
            _ = comp._private_attr

        # Setting private attribute should not mutate component dictionary
        comp._local_temp = "test"
        assert "_local_temp" not in comp
        assert comp._local_temp == "test"

        # Equality comparison
        assert comp == {"current": 100}
        assert comp != {"current": 50}
        assert comp != "not a dict"


class TestEntityProxyOperations:
    """Tests for EntityProxy ergonomics, case-normalization and dictionary semantics."""

    def test_dot_access_and_case_normalization(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity_id = kernel.create_entity(name="Player", components={"Health": {"current": 100}})
        proxy = kernel.get_entity_proxy(entity_id)
        assert isinstance(proxy, EntityProxy)

        # Dot access with exact, lower, upper case
        assert proxy.Health.current == 100
        assert proxy.health.current == 100
        assert proxy.HEALTH.current == 100

        # Dict access with exact, lower, upper case
        assert proxy["Health"]["current"] == 100
        assert proxy["health"]["current"] == 100
        assert proxy["HEALTH"]["current"] == 100

    def test_dict_and_get_semantics(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity_id = kernel.create_entity(components={"Health": {"current": 100}})
        proxy = kernel.get_entity_proxy(entity_id)

        assert proxy.get("Health") is not None
        assert proxy.get("health") is not None
        assert proxy.get("NonExistent") is None
        assert proxy.get("NonExistent", "fallback") == "fallback"

        with pytest.raises(KeyError):
            _ = proxy["NonExistent"]

    def test_membership_and_has(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity_id = kernel.create_entity(components={"Health": {"current": 100}})
        proxy = kernel.get_entity_proxy(entity_id)

        assert proxy.has("Health") is True
        assert proxy.has("health") is True
        assert proxy.has("HEALTH") is True
        assert proxy.has("Mana") is False

        assert "Health" in proxy
        assert "health" in proxy
        assert "Mana" not in proxy

    def test_set_and_remove_component(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity_id = kernel.create_entity(components={"Health": {"current": 100}})
        proxy = kernel.get_entity_proxy(entity_id)
        kernel.save_dirty_resources()

        # Set new component via method
        res = proxy.set("Mana", {"current": 50, "max": 50})
        assert res is None
        assert kernel.is_dirty(entity_id)
        assert proxy.has("Mana")
        assert proxy.mana.current == 50
        kernel.save_dirty_resources()

        # Set component via dict assignment
        proxy["Armor"] = {"current": 25}
        assert kernel.is_dirty(entity_id)
        assert proxy.has("armor")
        assert proxy.armor.current == 25
        kernel.save_dirty_resources()

        # Remove component via method
        removed = proxy.remove("mana")
        assert isinstance(removed, dict)
        assert removed["current"] == 50
        assert not proxy.has("Mana")
        assert kernel.is_dirty(entity_id)
        kernel.save_dirty_resources()

        # Remove component via del item
        del proxy["armor"]
        assert not proxy.has("Armor")
        assert kernel.is_dirty(entity_id)

        # Deleting non-existent component raises KeyError
        with pytest.raises(KeyError):
            del proxy["nonexistent"]

    def test_entity_proxy_dot_setattr_and_delattr(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity_id = kernel.create_entity(components={"Health": {"current": 100}})
        proxy = kernel.get_entity_proxy(entity_id)
        kernel.save_dirty_resources()
        assert not kernel.is_dirty(entity_id)

        # Set existing component via dot attribute (case-insensitive resolution)
        proxy.health = {"current": 80}
        assert kernel.is_dirty(entity_id)
        assert proxy.health.current == 80
        kernel.save_dirty_resources()

        # Add new component via dot attribute
        proxy.Mana = {"current": 50}
        assert kernel.is_dirty(entity_id)
        assert proxy.has("Mana")
        assert proxy.mana.current == 50
        kernel.save_dirty_resources()

        # Del component via dot attribute
        del proxy.mana
        assert kernel.is_dirty(entity_id)
        assert not proxy.has("Mana")
        kernel.save_dirty_resources()

        # Del non-existent component via dot attribute raises AttributeError
        with pytest.raises(AttributeError):
            del proxy.nonexistent

        # Property protection: attempting to set or delete read-only properties raises AttributeError
        with pytest.raises(AttributeError):
            proxy.id = 12345
        with pytest.raises(AttributeError):
            del proxy.id
        with pytest.raises(AttributeError):
            proxy.storage_id = b"123"
        with pytest.raises(AttributeError):
            del proxy.storage_id

    def test_set_using_component_proxy(self, tmp_path):
        kernel = Kernel(tmp_path)
        e1 = kernel.create_entity(components={"Stats": {"str": 15}})
        e2 = kernel.create_entity()
        p1 = kernel.get_entity_proxy(e1)
        p2 = kernel.get_entity_proxy(e2)

        # Set component using p1's ComponentProxy directly
        p2.set("Stats", p1.stats)
        assert p2.has("Stats")
        assert p2.stats.str == 15

    def test_id_and_storage_id_properties(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity_id = kernel.create_entity(name="Hero")
        proxy = kernel.get_entity_proxy(entity_id)

        assert proxy.id == entity_id
        assert proxy.storage_id == kernel.get_storage_id(entity_id)
        assert isinstance(proxy.storage_id, bytes)
        assert len(proxy.storage_id) == 16
        assert repr(proxy) == f"EntityProxy(id={entity_id})"

    def test_missing_component_raises_attribute_error(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity_id = kernel.create_entity()
        proxy = kernel.get_entity_proxy(entity_id)

        with pytest.raises(AttributeError) as exc_info:
            _ = proxy.inventory
        assert "inventory" in str(exc_info.value)

        with pytest.raises(AttributeError):
            _ = proxy._private_field

    def test_invalid_entity_id_returns_error(self, tmp_path):
        kernel = Kernel(tmp_path)
        err = kernel.get_entity_proxy(999999)
        assert isinstance(err, Error)
        assert err.code == RuntimeIDNotFoundOnMemoryError

        # Resource that is not an entity
        generic_res = kernel.create_resource(resource_type=99, resource_data={"config": 1})
        err2 = kernel.get_entity_proxy(generic_res)
        assert isinstance(err2, Error)
        assert err2.code == EntityTypeMismatchError


class TestEndToEndPersistenceRoundtrip:
    """Tests complete persistence across distinct Kernel lifecycles."""

    def test_in_place_arithmetic_mutation_and_reload(self, tmp_path):
        kernel1 = Kernel(tmp_path)
        entity_id = kernel1.create_entity(name="Hero", components={"Health": {"current": 100, "max": 100}})
        assert not isinstance(entity_id, Error)
        proxy1 = kernel1.get_entity_proxy(entity_id)
        storage_id = proxy1.storage_id
        kernel1.save_dirty_resources()

        # In-place arithmetic via dot proxy: proxy.health.current -= 25
        proxy1.health.current -= 25
        assert proxy1.health.current == 75
        assert kernel1.is_dirty(entity_id)

        assert kernel1.save_dirty_resources() is None
        assert not kernel1.is_dirty(entity_id)

        # Fresh kernel simulating next session / restart
        kernel2 = Kernel(tmp_path)
        loaded_id = kernel2.load_entity(storage_id)
        assert not isinstance(loaded_id, Error)

        # Direct kernel component check
        comp = kernel2.get_component(loaded_id, "Health")
        assert isinstance(comp, ComponentProxy)
        assert comp["current"] == 75

        # Proxy check in new session
        proxy2 = kernel2.get_entity_proxy(loaded_id)
        assert proxy2.health.current == 75
        assert proxy2.health.max == 100

    def test_entity_proxy_set_and_remove_persistence(self, tmp_path):
        kernel1 = Kernel(tmp_path)
        entity_id = kernel1.create_entity(name="Hero", components={"Health": {"current": 100}})
        proxy1 = kernel1.get_entity_proxy(entity_id)
        storage_id = proxy1.storage_id

        # Add component via EntityProxy
        proxy1.set("Shield", {"current": 50})
        kernel1.save_dirty_resources()

        # Reload in second kernel
        kernel2 = Kernel(tmp_path)
        loaded_id = kernel2.load_entity(storage_id)
        proxy2 = kernel2.get_entity_proxy(loaded_id)
        assert proxy2.has("Shield")
        assert proxy2.shield.current == 50

        # Remove component in second kernel
        proxy2.remove("Health")
        kernel2.save_dirty_resources()

        # Reload in third kernel
        kernel3 = Kernel(tmp_path)
        loaded_id3 = kernel3.load_entity(storage_id)
        proxy3 = kernel3.get_entity_proxy(loaded_id3)
        assert not proxy3.has("Health")
        assert proxy3.has("Shield")
        assert proxy3.shield.current == 50


class TestPlannedEngineFeatures:
    """Planned tests for approved architectural milestones not yet implemented."""

    def test_planned_uid_based_function_reference_rename(self, tmp_path):
        """Proves that a script defining a stable symbol ID (_fn_<uid>) survives

        human display name refactoring/renaming, cross-script references continue
        to work, the new alias works, and the old alias raises AttributeError.
        """
        kernel = Kernel(tmp_path)

        # 1. Script defines def _fn_f8e12a(entity, amount): # chug_potion
        code_v1 = (
            "def _fn_f8e12a(entity, amount): # chug_potion\n"
            "    entity.health.current += amount\n"
        )
        s_id = kernel.create_script_resource(name="PotionScript", code=code_v1)
        assert not isinstance(s_id, Error)
        s_sid_hex = kernel.get_storage_id(s_id).hex()

        e_id = kernel.create_entity(name="Hero", components={"Health": {"current": 100}})
        e_proxy = kernel.get_entity_proxy(e_id)

        script = kernel.get_script_proxy(s_id)
        assert isinstance(script, ScriptProxy)

        # Initial invocation via human display name
        script.chug_potion(e_proxy, 15)
        assert e_proxy.health.current == 115

        # 2. Caller invokes via symbol ID script._fn_f8e12a(...)
        script._fn_f8e12a(e_proxy, 20)
        assert e_proxy.health.current == 135

        # Also set up a cross-script caller invoking via symbol ID
        caller_code = (
            f"potion_lib = <|1|{s_sid_hex}|>\n\n"
            "def update(dt):\n"
            "    potion_lib._fn_f8e12a(self, 10 * dt)\n"
        )
        caller_id = kernel.create_script_resource(name="CallerScript", code=caller_code)
        assert not isinstance(caller_id, Error)
        kernel.attach_script(e_id, caller_id)

        errors = kernel.tick(dt=1.0)
        assert errors is None
        assert e_proxy.health.current == 145

        # 3. Refactor / rename human display name in comment:
        # def _fn_f8e12a(entity, amount): # drink_healing_elixir
        code_v2 = (
            "def _fn_f8e12a(entity, amount): # drink_healing_elixir\n"
            "    entity.health.current += amount\n"
        )
        kernel.mutate_resource(
            s_id,
            {
                "name": "PotionScript",
                "code": code_v2,
                "requires": [],
                "symbols": extract_script_symbols(code_v2),
            },
        )

        # 4. Calling script._fn_f8e12a(...) and cross-script references STILL SUCCEED without breaking!
        script._fn_f8e12a(e_proxy, 25)
        assert e_proxy.health.current == 170

        errors = kernel.tick(dt=1.0)
        assert errors is None
        assert e_proxy.health.current == 180

        # 5. The new human name alias is also callable: script.drink_healing_elixir(...)
        script.drink_healing_elixir(e_proxy, 10)
        assert e_proxy.health.current == 190

        # 6. The old human name alias script.chug_potion(...) raises AttributeError
        with pytest.raises(AttributeError):
            script.chug_potion(e_proxy, 10)

        # Also verify BoundScriptProxy behavior
        bound = script.bind(e_proxy)
        bound._fn_f8e12a(5)
        assert e_proxy.health.current == 195
        bound.drink_healing_elixir(5)
        assert e_proxy.health.current == 200
        with pytest.raises(AttributeError):
            bound.chug_potion(5)

    def test_planned_failed_dependency_load_transactional_cleanup(self, tmp_path):
        # When loading a tree of dependent resources, a failure in a child node must roll back
        # any partially loaded parent nodes from kernel.resources.
        k1 = Kernel(tmp_path)
        parent_id = k1.create_entity(name="Parent")
        assert not isinstance(parent_id, Error)
        child_id = k1.create_entity(name="Child", parent_id=parent_id)
        assert not isinstance(child_id, Error)
        parent_sid = k1.get_storage_id(parent_id)
        child_sid = k1.get_storage_id(child_id)
        assert not isinstance(parent_sid, Error)
        assert not isinstance(child_sid, Error)
        assert k1.save_dirty_resources() is None

        # Corrupt child JSON on disk
        child_file = tmp_path / f"{child_sid.hex()}.json"
        child_file.write_text("{corrupt json payload", encoding="utf-8")

        k2 = Kernel(tmp_path)
        res = k2.load_resource(parent_sid, is_fatal=True)
        assert isinstance(res, Error)
        # Parent must be rolled back and not present in kernel.resources
        assert k2.resources == {}
        assert parent_sid not in k2.resource_runtime_ids

    def test_planned_runtime_id_recycle_generation_safety(self, tmp_path):
        kernel = Kernel(tmp_path)
        a_id = kernel.create_entity(name="EntityA", components={"Transform": {"x": 10.0, "y": 20.0}})
        assert not isinstance(a_id, Error)
        proxy_a = kernel.get_entity_proxy(a_id)
        assert not isinstance(proxy_a, Error)
        assert proxy_a.is_alive
        assert proxy_a.name == "EntityA"
        assert proxy_a.Transform["x"] == 10.0

        # Delete Entity A
        res = kernel.delete_resource(a_id)
        assert res is True
        assert not kernel.is_entity(a_id)
        assert not kernel.is_valid_runtime_id(a_id)
        assert not proxy_a.is_alive

        # Create Entity B (which reuses the freed slot)
        b_id = kernel.create_entity(name="EntityB", components={"Transform": {"x": 99.0, "y": 99.0}})
        assert not isinstance(b_id, Error)
        proxy_b = kernel.get_entity_proxy(b_id)
        assert not isinstance(proxy_b, Error)
        assert proxy_b.is_alive
        assert proxy_b.name == "EntityB"

        # Assert Entity B has a different handle than Entity A
        assert b_id != a_id
        slot_a, gen_a = kernel._unpack_handle(a_id)
        slot_b, gen_b = kernel._unpack_handle(b_id)
        assert slot_a == slot_b
        assert gen_b > gen_a

        # Assert accessing proxy for Entity A raises or fails cleanly, and does NOT mutate or read Entity B
        assert not proxy_a.is_alive
        with pytest.raises(AttributeError):
            _ = proxy_a.name
        with pytest.raises(AttributeError):
            _ = proxy_a.Transform
        with pytest.raises(AttributeError):
            proxy_a.Transform = {"x": 0.0, "y": 0.0}
        with pytest.raises(KeyError):
            _ = proxy_a["Transform"]

        # Verify Entity B was not mutated by attempts to access or modify proxy_a
        assert proxy_b.name == "EntityB"
        assert proxy_b.Transform["x"] == 99.0

    @pytest.mark.skip(reason="Planned test: Hot reload rollback preserves stable system state on syntax error")
    def test_planned_hot_reload_rollback_on_syntax_error(self):
        # A live system update that fails compilation must roll back to the previously active
        # implementation without engine corruption.
        pass


class TestPhase3SingleControlledMutationAndReadOnlyViews:
    """Comprehensive test suite for Phase 3 mutation contracts and read-only views."""

    def test_component_proxy_is_not_dict_subclass(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(components={"Health": {"current": 100, "max": 100}})
        assert not isinstance(entity, Error)

        comp = kernel.get_component(entity, "Health")
        assert isinstance(comp, MutableMapping)
        assert not isinstance(comp, dict)
        assert not issubclass(ComponentProxy, dict)
        assert issubclass(ComponentProxy, MutableMapping)

        # Single store verification: wrap only _target
        assert hasattr(comp, "_target")
        assert comp._target == {"current": 100, "max": 100}
        assert not hasattr(super(ComponentProxy, comp), "__getitem__") or type(comp).__bases__ == (MutableMapping,)

    def test_component_proxy_mapping_methods(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(components={"Stats": {"atk": 10, "def": 5}})
        assert not isinstance(entity, Error)
        kernel.save_dirty_resources()
        assert not kernel.is_dirty(entity)

        comp = kernel.get_component(entity, "Stats")
        assert len(comp) == 2
        assert "atk" in comp
        assert "speed" not in comp
        assert list(comp.keys()) == ["atk", "def"]
        assert list(comp.values()) == [10, 5]
        assert list(comp.items()) == [("atk", 10), ("def", 5)]
        assert comp.get("atk") == 10
        assert comp.get("missing", 99) == 99
        assert comp.to_dict() == {"atk": 10, "def": 5}
        assert not kernel.is_dirty(entity)

        # Mutate via __setitem__
        comp["atk"] = 25
        assert kernel.is_dirty(entity)
        assert comp["atk"] == 25
        assert comp._target["atk"] == 25
        kernel.save_dirty_resources()

        # Mutate via __delitem__
        del comp["def"]
        assert kernel.is_dirty(entity)
        assert "def" not in comp
        assert "def" not in comp._target

    def test_tracked_list_mutations_mark_dirty_and_persist(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(components={"Inventory": {"items": ["sword", "shield"]}})
        assert not isinstance(entity, Error)
        kernel.save_dirty_resources()
        assert not kernel.is_dirty(entity)

        comp = kernel.get_component(entity, "Inventory")
        items = comp["items"]
        assert isinstance(items, TrackedList)
        assert isinstance(items, MutableSequence)
        assert not isinstance(items, list)
        assert not kernel.is_dirty(entity)

        # append
        items.append("potion")
        assert kernel.is_dirty(entity)
        assert items[-1] == "potion"
        assert comp._target["items"] == ["sword", "shield", "potion"]
        kernel.save_dirty_resources()

        # extend
        items.extend(["bow", "arrow"])
        assert kernel.is_dirty(entity)
        assert len(items) == 5
        kernel.save_dirty_resources()

        # insert
        items.insert(0, "ring")
        assert kernel.is_dirty(entity)
        assert items[0] == "ring"
        kernel.save_dirty_resources()

        # pop
        popped = items.pop(0)
        assert popped == "ring"
        assert kernel.is_dirty(entity)
        kernel.save_dirty_resources()

        # remove
        items.remove("shield")
        assert kernel.is_dirty(entity)
        assert "shield" not in items
        kernel.save_dirty_resources()

        # __setitem__
        items[0] = "greatsword"
        assert kernel.is_dirty(entity)
        assert items[0] == "greatsword"
        kernel.save_dirty_resources()

        # reverse & sort
        items.reverse()
        assert kernel.is_dirty(entity)
        kernel.save_dirty_resources()
        items.sort()
        assert kernel.is_dirty(entity)
        kernel.save_dirty_resources()

        # __delitem__
        del items[0]
        assert kernel.is_dirty(entity)
        kernel.save_dirty_resources()

        # clear
        items.clear()
        assert kernel.is_dirty(entity)
        assert len(items) == 0
        kernel.save_dirty_resources()

    def test_tracked_list_and_proxy_recursive_unwrap(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(
            components={
                "Party": {
                    "members": [{"name": "Alice", "hp": 100}, {"name": "Bob", "hp": 80}],
                    "tags": ["heroes", "active"],
                }
            }
        )
        assert not isinstance(entity, Error)
        kernel.save_dirty_resources()

        comp = kernel.get_component(entity, "Party")
        assert isinstance(comp["members"], TrackedList)
        assert isinstance(comp["members"][0], ComponentProxy)
        assert isinstance(comp["tags"], TrackedList)

        # Mutate nested member through proxy
        comp["members"][0].hp = 95
        assert kernel.is_dirty(entity)
        kernel.save_dirty_resources()

        # to_dict recursively unwraps everything into plain dicts and lists
        plain = comp.to_dict()
        assert type(plain) is dict
        assert type(plain["members"]) is list
        assert type(plain["members"][0]) is dict
        assert type(plain["tags"]) is list
        assert plain == {
            "members": [{"name": "Alice", "hp": 95}, {"name": "Bob", "hp": 80}],
            "tags": ["heroes", "active"],
        }

        # Reload kernel and verify persisted primitives
        k2 = Kernel(tmp_path)
        loaded = k2.load_entity(kernel.get_storage_id(entity))
        assert not isinstance(loaded, Error)
        comp2 = k2.get_component(loaded, "Party")
        assert comp2.to_dict() == plain

    def test_get_components_returns_immutable_mapping_proxy(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(components={"Transform": {"x": 10.0, "y": 20.0}})
        assert not isinstance(entity, Error)

        comps = kernel.get_components(entity)
        assert isinstance(comps, MappingProxyType)
        assert isinstance(comps["Transform"], MappingProxyType)
        assert comps["Transform"]["x"] == 10.0

        # Direct assignment on components container raises TypeError
        with pytest.raises(TypeError):
            comps["Transform"] = {}

        # Direct assignment on component dictionary raises TypeError
        with pytest.raises(TypeError):
            comps["Transform"]["x"] = 99.0

        # Stale/invalid handle returns Error
        err = kernel.get_components(999999)
        assert isinstance(err, Error)
        assert err.code == RuntimeIDNotFoundOnMemoryError

    def test_get_resource_returns_immutable_mapping_proxy(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(name="TestEntity", components={"Pos": {"x": 1.0}})
        assert not isinstance(entity, Error)

        res = kernel.get_resource(entity)
        assert isinstance(res, MappingProxyType)
        assert res["name"] == "TestEntity"

        # Direct assignment on resource dictionary raises TypeError
        with pytest.raises(TypeError):
            res["name"] = "HackedName"

        with pytest.raises(TypeError):
            res["data"] = {}

        # Stale/invalid handle returns Error
        err = kernel.get_resource(999999)
        assert isinstance(err, Error)
        assert err.code == RuntimeIDNotFoundOnMemoryError

    def test_kernel_mutate_component_merges_and_marks_dirty(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(components={"Transform": {"x": 10.0, "y": 20.0, "z": 0.0}})
        assert not isinstance(entity, Error)
        kernel.save_dirty_resources()
        assert not kernel.is_dirty(entity)

        # Mutate component with new partial data
        err = kernel.mutate_component(entity, "Transform", {"x": 99.0, "z": 5.0})
        assert err is None
        assert kernel.is_dirty(entity)

        # Confirm merged state preserves unspecified key 'y'
        comps = kernel.get_components(entity)
        assert comps["Transform"]["x"] == 99.0
        assert comps["Transform"]["y"] == 20.0
        assert comps["Transform"]["z"] == 5.0

        # Mutate non-existent component creates it
        err2 = kernel.mutate_component(entity, "Armor", {"defense": 30})
        assert err2 is None
        comps2 = kernel.get_components(entity)
        assert comps2["Armor"]["defense"] == 30

        # Invalid handle returns Error
        err3 = kernel.mutate_component(999999, "Transform", {"x": 1.0})
        assert isinstance(err3, Error)
        assert err3.code == RuntimeIDNotFoundOnMemoryError

        # Invalid component data returns Error
        err4 = kernel.mutate_component(entity, "Transform", "not-a-dict")
        assert isinstance(err4, Error)

    def test_kernel_set_component_clears_script_cache(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(components={"Transform": {"x": 0.0}})
        assert not isinstance(entity, Error)
        resolved_id = kernel._resolve_handle(entity)

        # Populate a dummy script cache entry for resolved_id
        kernel._script_cache[resolved_id] = ("code", None, set())
        assert resolved_id in kernel._script_cache

        # set_component invalidates the script cache
        kernel.set_component(entity, "Transform", {"x": 10.0})
        assert resolved_id not in kernel._script_cache

        # mutate_component also invalidates the script cache
        kernel._script_cache[resolved_id] = ("code2", None, set())
        assert resolved_id in kernel._script_cache
        kernel.mutate_component(entity, "Transform", {"x": 20.0})
        assert resolved_id not in kernel._script_cache

    def test_entity_proxy_controlled_mutation_paths(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(name="Hero", components={"Health": {"current": 100}})
        assert not isinstance(entity, Error)
        kernel.save_dirty_resources()

        proxy = kernel.get_entity_proxy(entity)
        assert isinstance(proxy, EntityProxy)

        # Mutate via proxy dot/dict component access
        proxy.Health.current = 80
        assert kernel.is_dirty(entity)
        assert proxy.Health["current"] == 80
        kernel.save_dirty_resources()

        # Mutate name property
        proxy.name = "Champion"
        assert kernel.is_dirty(entity)
        assert proxy.name == "Champion"
        assert kernel.get_resource(entity)["name"] == "Champion"
        kernel.save_dirty_resources()

        # Add component via proxy.set
        err = proxy.set("Mana", {"current": 50})
        assert err is None
        assert kernel.is_dirty(entity)
        assert proxy.Mana.current == 50
        kernel.save_dirty_resources()

        # Remove component via proxy.remove
        removed = proxy.remove("Mana")
        assert removed == {"current": 50}
        assert kernel.is_dirty(entity)
        assert not proxy.has("Mana")


class TestPhase3NegativeAndEdgeCaseRemediations:
    """Rigorous verification tests for Phase 3 review feedback."""

    def test_mapping_proxy_json_serialization_requires_unwrap(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(name="Hero", components={"Transform": {"x": 1.0, "y": 2.0}})
        assert not isinstance(entity, Error)

        res = kernel.get_resource(entity)
        assert isinstance(res, MappingProxyType)

        # Standard json.dumps on raw mappingproxy raises TypeError
        with pytest.raises(TypeError):
            json.dumps(res)

        # Unwrapping via _unwrap produces serializable pure primitives
        unwrapped = _unwrap(res)
        serialized = json.dumps(unwrapped)
        assert isinstance(serialized, str)
        assert "Hero" in serialized

    def test_read_only_view_deep_list_immutability(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(
            components={"Inventory": {"items": ["sword", "shield"]}}
        )
        assert not isinstance(entity, Error)
        kernel.save_dirty_resources()
        assert not kernel.is_dirty(entity)

        comps = kernel.get_components(entity)
        items = comps["Inventory"]["items"]
        assert isinstance(items, ReadOnlySequence)
        assert items == ["sword", "shield"]
        assert ["sword", "shield"] == items

        # In-place list mutations are strictly blocked
        with pytest.raises(AttributeError):
            items.append("helmet")

        with pytest.raises(TypeError):
            items[0] = "axe"

        # Entity remains clean
        assert not kernel.is_dirty(entity)

    def test_unpacked_slot_id_vs_packed_handle_resolution(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(name="Actor", components={"Pos": {"x": 5.0}})
        assert not isinstance(entity, Error)
        slot, gen = kernel._unpack_handle(entity)

        # Accessing via bare slot index resolves to active packed handle
        res_by_slot = kernel.get_resource(slot)
        assert not isinstance(res_by_slot, Error)
        assert res_by_slot["name"] == "Actor"

        comps_by_slot = kernel.get_components(slot)
        assert not isinstance(comps_by_slot, Error)
        assert comps_by_slot["Pos"]["x"] == 5.0

        # Unallocated or invalid slot index returns clean Error
        err = kernel.get_resource(999999)
        assert isinstance(err, Error)
        assert err.code == RuntimeIDNotFoundOnMemoryError

    def test_get_resource_deep_data_immutability(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(name="Actor", components={"Pos": {"x": 5.0}})
        assert not isinstance(entity, Error)

        res = kernel.get_resource(entity)
        assert isinstance(res["data"], MappingProxyType)
        assert isinstance(res["data"]["components"], MappingProxyType)

        with pytest.raises(TypeError):
            res["data"]["components"] = {}

        with pytest.raises(TypeError):
            res["data"]["components"]["Pos"] = {}

    def test_readonly_sequence_string_bytes_inequality(self):
        seq = ReadOnlySequence(["a", "b"])
        assert not (seq == "ab")
        assert not ("ab" == seq)

        seq_bytes = ReadOnlySequence([65, 66])
        assert not (seq_bytes == b"AB")
        assert not (b"AB" == seq_bytes)

    def test_get_entity_resources_is_readonly(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(name="Actor")
        assert not isinstance(entity, Error)

        kernel.add_entity_resource(entity, "0123456789abcdef0123456789abcdef")
        resources = kernel.get_entity_resources(entity)
        assert isinstance(resources, ReadOnlySequence)
        assert len(resources) == 1

        with pytest.raises(AttributeError):
            resources.append("illegal")

    def test_component_proxy_mutation_invalidates_script_cache(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity = kernel.create_entity(components={"Health": {"current": 100}})
        assert not isinstance(entity, Error)
        resolved_id = kernel._resolve_handle(entity)

        # Seed script cache
        kernel._script_cache[resolved_id] = ("cached_code", None, set())
        assert resolved_id in kernel._script_cache

        # Mutate via ComponentProxy
        comp = kernel.get_component(entity, "Health")
        comp.current = 50

        # Cache was invalidated via mark_dirty
        assert resolved_id not in kernel._script_cache
