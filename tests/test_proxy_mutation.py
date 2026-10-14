"""Comprehensive independent tests for ComponentProxy and EntityProxy mutation and persistence.

Derives tests from observable user requirements and kernel contracts:
1. ComponentProxy dot and dict mutations mark entities dirty and persist.
2. Non-mutating reads do not mark entities dirty.
3. EntityProxy case-insensitivity, dict/dot access, membership, addition, removal.
4. Error contracts (missing components, non-entities, stale handles).
5. End-to-end multi-kernel persistence roundtrip.
6. Planned tests for unimplemented engine features.
"""

import copy

import pytest

from LBE import (
    ComponentProxy,
    EntityProxy,
    Error,
    Kernel,
    ScriptProxy,
    extract_script_symbols,
)
from LBE.types import (
    ComponentNotFoundOnEntityError,
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

    @pytest.mark.skip(reason="Planned test: Transactional rollback on failed dependency graph loading")
    def test_planned_failed_dependency_load_transactional_cleanup(self):
        # When loading a tree of dependent resources, a failure in a child node must roll back
        # any partially loaded parent nodes from kernel.resources.
        pass

    @pytest.mark.skip(reason="Planned test: Generation-safe RuntimeID recycling prevents stale handles")
    def test_planned_runtime_id_recycle_generation_safety(self):
        # Destroying an entity and creating a new one reusing the slot must invalidate
        # stale EntityProxy instances via generation counters.
        pass

    @pytest.mark.skip(reason="Planned test: Hot reload rollback preserves stable system state on syntax error")
    def test_planned_hot_reload_rollback_on_syntax_error(self):
        # A live system update that fails compilation must roll back to the previously active
        # implementation without engine corruption.
        pass