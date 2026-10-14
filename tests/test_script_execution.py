"""Comprehensive independent tests for Stage 3: Script Resources, Attachment, Execution with self, and Nested Component Proxies.

Derives tests from observable user requirements and kernel contracts:
1. Recursive Nested Component Mutation:
   - Nested dot and dict mutations mark the parent entity dirty.
   - Durability: Saved and reloaded across separate Kernel lifecycles.
2. Script Resource Lifecycle & Attachment:
   - Creation of Script resources with metadata/requirements.
   - Attachment and detachment to Entities; persistent storage via canonical StorageID hex.
3. Component Requirements Validation:
   - Scripts with requires=["..."] fail with MissingComponentRequirementError when requirements are unmet.
   - Adding missing components allows subsequent execution to succeed.
4. Script Execution & `self` Context via tick():
   - Script update(dt) and update(self, dt) methods mutate self.<component>.<field>.
   - Changes dirty the entity and persist on save and reload.
5. Combined Reference Preprocessor in Script:
   - Entity script uses <|0|hex|> bracket syntax to manipulate another entity during tick().
   - Multi-entity dirty tracking and durability verification.
"""

import pytest

from LBE import (
    EntityProxy,
    Error,
    Kernel,
    Script,
    ScriptProxy,
    BoundScriptProxy,
    Validate,
)
from LBE.types import (
    Entity,
    InvalidResourceDataError,
    MissingComponentRequirementError,
    RuntimeIDNotFoundOnMemoryError,
)


class TestRecursiveNestedComponentMutation:
    """Tests for deeply nested dictionary mutation tracking via ComponentProxy."""

    def test_recursive_nested_mutation_and_persistence(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity_id = kernel.create_entity(
            name="Player",
            components={
                "Stats": {
                    "movement": {"speed": 10},
                    "combat": {"power": 50},
                }
            },
        )
        assert not isinstance(entity_id, Error)
        storage_id = kernel.get_storage_id(entity_id)
        assert kernel.save_dirty_resources() is None
        assert not kernel.is_dirty(entity_id)

        proxy = kernel.get_entity_proxy(entity_id)
        assert isinstance(proxy, EntityProxy)

        # Mutate via nested dot access: proxy.stats.movement.speed += 5
        proxy.stats.movement.speed += 5
        assert kernel.is_dirty(entity_id)
        assert proxy.stats.movement.speed == 15

        # Mutate via nested dict access: proxy["stats"]["combat"]["power"] -= 10
        proxy["stats"]["combat"]["power"] -= 10
        assert proxy["stats"]["combat"]["power"] == 40

        # Save dirty resources
        assert kernel.save_dirty_resources() is None
        assert not kernel.is_dirty(entity_id)

        # Reload in a brand new Kernel session
        fresh_kernel = Kernel(tmp_path)
        loaded_id = fresh_kernel.load_entity(storage_id)
        assert not isinstance(loaded_id, Error)

        fresh_proxy = fresh_kernel.get_entity_proxy(loaded_id)
        assert fresh_proxy.stats.movement.speed == 15
        assert fresh_proxy["stats"]["combat"]["power"] == 40

    def test_nested_dict_deletion_and_addition_marks_dirty(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity_id = kernel.create_entity(
            components={
                "Config": {
                    "audio": {"volume": 80, "mute": False},
                }
            }
        )
        kernel.save_dirty_resources()
        proxy = kernel.get_entity_proxy(entity_id)

        # Add nested key
        proxy.config.audio.channel = "stereo"
        assert kernel.is_dirty(entity_id)
        assert proxy.config.audio.channel == "stereo"
        kernel.save_dirty_resources()

        # Delete nested key
        del proxy.config.audio.mute
        assert kernel.is_dirty(entity_id)
        assert "mute" not in proxy.config.audio
        kernel.save_dirty_resources()

        # Reload to confirm durability of additions/deletions
        fresh = Kernel(tmp_path)
        loaded = fresh.load_entity(kernel.get_storage_id(entity_id))
        fresh_proxy = fresh.get_entity_proxy(loaded)
        assert fresh_proxy.config.audio.channel == "stereo"
        assert "mute" not in fresh_proxy.config.audio


class TestScriptResourceLifecycleAndAttachment:
    """Tests for creating, attaching, persisting, and detaching Script resources."""

    def test_create_and_attach_script(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity_id = kernel.create_entity(name="Actor", components={"Transform": {"x": 0, "y": 0}})
        assert not isinstance(entity_id, Error)

        # Create script resource
        script_id = kernel.create_script_resource(
            name="MoveScript",
            code="def update(dt): pass",
            requires=["Transform"],
        )
        assert not isinstance(script_id, Error)
        script_res = kernel.get_resource(script_id)
        assert script_res["type"] == Script
        assert script_res["data"]["requires"] == ["Transform"]

        kernel.save_dirty_resources()
        assert not kernel.is_dirty(entity_id)

        # Attach script to entity
        err = kernel.attach_script(entity_id, script_id)
        assert err is None
        assert kernel.is_dirty(entity_id)

        # Query scripts attached to entity
        scripts = kernel.get_entity_scripts(entity_id)
        assert scripts == [script_id]

    def test_script_attachment_persists_across_sessions(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity_id = kernel.create_entity(name="Actor", components={"Transform": {"x": 0, "y": 0}})
        entity_sid = kernel.get_storage_id(entity_id)

        script_id = kernel.create_script_resource(
            name="ActorAI",
            code="def update(dt): pass",
            requires=["Transform"],
        )
        script_sid = kernel.get_storage_id(script_id)

        kernel.attach_script(entity_id, script_id)
        assert kernel.save_dirty_resources() is None

        # Fresh kernel session
        fresh = Kernel(tmp_path)
        loaded_script = fresh.load_resource(script_sid)
        assert not isinstance(loaded_script, Error)
        loaded_entity = fresh.load_entity(entity_sid)
        assert not isinstance(loaded_entity, Error)

        scripts = fresh.get_entity_scripts(loaded_entity)
        assert len(scripts) == 1
        assert scripts[0] == loaded_script

    def test_detach_script_marks_dirty_and_persists(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity_id = kernel.create_entity(name="Actor")
        script_id = kernel.create_script_resource(name="TempScript", code="pass")
        kernel.attach_script(entity_id, script_id)
        kernel.save_dirty_resources()
        assert not kernel.is_dirty(entity_id)

        # Detach
        err = kernel.detach_script(entity_id, script_id)
        assert err is None
        assert kernel.is_dirty(entity_id)
        assert kernel.get_entity_scripts(entity_id) == []

        # Save and reload
        kernel.save_dirty_resources()
        fresh = Kernel(tmp_path)
        loaded = fresh.load_entity(kernel.get_storage_id(entity_id))
        assert fresh.get_entity_scripts(loaded) == []

    def test_corrupt_script_list_handled_safely(self, tmp_path):
        kernel = Kernel(tmp_path)
        # Test integrity check catches non-string script elements
        bad_envelope = {
            "type": Entity,
            "data": {
                "components": {},
                "scripts": [123],
            },
        }
        err = Validate.resource_data(bad_envelope)
        assert isinstance(err, Error)
        assert err.code == InvalidResourceDataError
        assert "must be strings" in err.description

        # Test kernel.get_entity_scripts handles corrupt entries safely in memory
        entity_id = kernel.create_entity(name="TestActor")
        kernel.resources[entity_id]["data"]["scripts"] = [123, "invalid_hex", None]
        # Must not raise TypeError or crash
        scripts = kernel.get_entity_scripts(entity_id)
        assert scripts == []

        # Running scripts on entity with corrupt script list handles gracefully
        res = kernel.run_entity_scripts(entity_id, dt=1.0)
        assert res is None


class TestComponentRequirementsValidation:
    """Tests that missing required components halt script execution with informative errors."""

    def test_missing_component_requirement_returns_error(self, tmp_path):
        kernel = Kernel(tmp_path)
        # Entity has no Transform component
        entity_id = kernel.create_entity(name="Camera", components={"CameraData": {"fov": 60}})
        script_id = kernel.create_script_resource(
            name="FollowPlayer",
            code="def update(dt): pass",
            requires=["Transform"],
        )
        kernel.attach_script(entity_id, script_id)

        # Attempting to run entity scripts must fail with MissingComponentRequirementError
        err = kernel.run_entity_scripts(entity_id, dt=0.016)
        assert isinstance(err, Error)
        assert err.code == MissingComponentRequirementError
        assert "Transform" in err.message or "Transform" in str(err.description)

    def test_satisfying_component_requirement_enables_execution(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity_id = kernel.create_entity(name="Player", components={})
        script_id = kernel.create_script_resource(
            name="HealthRegen",
            code="""
def update(dt):
    self.health.current += 1
""",
            requires=["Health"],
        )
        kernel.attach_script(entity_id, script_id)

        # Fails when missing
        err = kernel.run_entity_scripts(entity_id, dt=1.0)
        assert isinstance(err, Error)
        assert err.code == MissingComponentRequirementError

        # Add the required component
        proxy = kernel.get_entity_proxy(entity_id)
        proxy.set("Health", {"current": 50})

        # Now execution succeeds
        err2 = kernel.run_entity_scripts(entity_id, dt=1.0)
        assert err2 is None
        assert proxy.health.current == 51


class TestScriptExecutionAndSelfContextViaTick:
    """Tests execution of scripts with self context through kernel.tick()."""

    def test_update_dt_decrements_health_and_persists(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity_id = kernel.create_entity(
            name="Hero",
            components={"Health": {"current": 100, "max": 100}},
        )
        storage_id = kernel.get_storage_id(entity_id)

        script_code = """
def update(dt):
    self.health.current -= 10 * dt
"""
        script_id = kernel.create_script_resource(name="Poison", code=script_code)
        kernel.attach_script(entity_id, script_id)
        kernel.save_dirty_resources()
        assert not kernel.is_dirty(entity_id)

        # Run tick with dt=2.0 -> damage = 20
        tick_errors = kernel.tick(dt=2.0)
        assert tick_errors is None

        proxy = kernel.get_entity_proxy(entity_id)
        assert proxy.health.current == 80
        assert kernel.is_dirty(entity_id)

        # Save and reload in a new kernel
        kernel.save_dirty_resources()
        fresh = Kernel(tmp_path)
        loaded_id = fresh.load_entity(storage_id)
        fresh_proxy = fresh.get_entity_proxy(loaded_id)
        assert fresh_proxy.health.current == 80

    def test_update_with_explicit_self_parameter(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity_id = kernel.create_entity(
            name="Bot",
            components={"Energy": {"current": 50}},
        )
        script_code = """
def update(self, dt):
    self.energy.current += 5 * dt
"""
        script_id = kernel.create_script_resource(name="Recharge", code=script_code)
        kernel.attach_script(entity_id, script_id)

        kernel.tick(dt=2.0)
        proxy = kernel.get_entity_proxy(entity_id)
        assert proxy.energy.current == 60

    def test_tick_aggregates_script_errors_without_crashing(self, tmp_path):
        kernel = Kernel(tmp_path)
        e1 = kernel.create_entity(name="GoodEntity", components={"Health": {"current": 100}})
        e2 = kernel.create_entity(name="FaultyEntity", components={"Health": {"current": 100}})

        s_good = kernel.create_script_resource(
            name="GoodScript",
            code="def update(dt): self.health.current += 1",
        )
        s_bad = kernel.create_script_resource(
            name="BadScript",
            code="def update(dt): 1 / 0",
        )

        kernel.attach_script(e1, s_good)
        kernel.attach_script(e2, s_bad)

        errors = kernel.tick(dt=1.0)
        assert isinstance(errors, list)
        assert len(errors) == 1
        assert "ZeroDivisionError" in str(errors[0].description) or "error" in str(errors[0].message).lower()

        # The good entity's script still ran successfully
        assert kernel.get_entity_proxy(e1).health.current == 101

    def test_update_signatures_support_various_parameter_names(self, tmp_path):
        kernel = Kernel(tmp_path)
        # Test (entity, dt)
        e1 = kernel.create_entity(components={"Health": {"current": 100}})
        s1 = kernel.create_script_resource(
            name="S1",
            code="def update(entity, dt): entity.health.current += 10 * dt",
        )
        kernel.attach_script(e1, s1)

        # Test (target, dt)
        e2 = kernel.create_entity(components={"Health": {"current": 100}})
        s2 = kernel.create_script_resource(
            name="S2",
            code="def update(target, dt): target.health.current += 5 * dt",
        )
        kernel.attach_script(e2, s2)

        # Test (dt) using self in scope
        e3 = kernel.create_entity(components={"Health": {"current": 100}})
        s3 = kernel.create_script_resource(
            name="S3",
            code="def update(dt): self.health.current += 2 * dt",
        )
        kernel.attach_script(e3, s3)

        # Test () zero-argument function using self in scope
        e4 = kernel.create_entity(components={"Health": {"current": 100}})
        s4 = kernel.create_script_resource(
            name="S4",
            code="def update(): self.health.current += 1",
        )
        kernel.attach_script(e4, s4)

        # Test single argument entity proxy (e) without dt
        e5 = kernel.create_entity(components={"Health": {"current": 100}})
        s5 = kernel.create_script_resource(
            name="S5",
            code="def update(e): e.health.current += 7",
        )
        kernel.attach_script(e5, s5)

        kernel.tick(dt=2.0)

        assert kernel.get_entity_proxy(e1).health.current == 120  # + 10*2
        assert kernel.get_entity_proxy(e2).health.current == 110  # + 5*2
        assert kernel.get_entity_proxy(e3).health.current == 104  # + 2*2
        assert kernel.get_entity_proxy(e4).health.current == 101  # + 1
        assert kernel.get_entity_proxy(e5).health.current == 107  # + 7

    def test_script_caching_eliminates_recompilation(self, tmp_path):
        kernel = Kernel(tmp_path)
        script_id = kernel.create_script_resource(
            name="SharedAI",
            code="def update(dt): self.stats.score += 10",
        )

        entities = []
        for i in range(5):
            e = kernel.create_entity(name=f"Bot_{i}", components={"Stats": {"score": 0}})
            kernel.attach_script(e, script_id)
            entities.append(e)

        # Verify cache is empty before tick
        assert script_id not in kernel._script_cache

        # First tick populates script cache
        kernel.tick(dt=1.0)

        assert script_id in kernel._script_cache
        cached_code, cached_code_obj, cached_deps = kernel._script_cache[script_id]
        assert cached_code == "def update(dt): self.stats.score += 10"

        # Verify all 5 entities updated
        for e in entities:
            assert kernel.get_entity_proxy(e).stats.score == 10

        # Second tick reuses the exact same compiled code object
        kernel.tick(dt=1.0)
        assert kernel._script_cache[script_id][1] is cached_code_obj

        for e in entities:
            assert kernel.get_entity_proxy(e).stats.score == 20


class TestCombinedReferencePreprocessorInScript:
    """Tests scripts combining bracket references (<|0|hex|>) with self context."""

    def test_script_interacts_with_another_entity_via_bracket_reference(self, tmp_path):
        kernel = Kernel(tmp_path)
        target_id = kernel.create_entity(
            name="EnemyTarget",
            components={"Health": {"current": 100}},
        )
        target_sid_hex = kernel.get_storage_id(target_id).hex()

        attacker_id = kernel.create_entity(
            name="Attacker",
            components={"Stats": {"power": 25}},
        )

        # Attacker script references the target via bracket syntax
        script_code = f"""
target = <|0|{target_sid_hex}|>

def update(dt):
    damage = self.stats.power * dt
    target.health.current -= damage
"""
        script_id = kernel.create_script_resource(name="AttackScript", code=script_code)
        kernel.attach_script(attacker_id, script_id)
        kernel.save_dirty_resources()
        assert not kernel.is_dirty(target_id)
        assert not kernel.is_dirty(attacker_id)

        # Tick 2 seconds -> damage = 25 * 2 = 50
        errors = kernel.tick(dt=2.0)
        assert errors is None

        # Both entities should be properly updated and marked dirty
        target_proxy = kernel.get_entity_proxy(target_id)
        assert target_proxy.health.current == 50
        assert kernel.is_dirty(target_id)

        # Save and reload in new session to verify multi-entity persistence
        kernel.save_dirty_resources()
        fresh = Kernel(tmp_path)
        loaded_target = fresh.load_entity(kernel.get_storage_id(target_id))
        assert fresh.get_entity_proxy(loaded_target).health.current == 50


class TestScriptProxyAndCrossScriptReferences:
    """Tests for ScriptProxy, BoundScriptProxy, get_script_module caching, and cross-script references."""

    def test_create_script_resource_extracts_symbols_from_code(self, tmp_path):
        kernel = Kernel(tmp_path)
        code = (
            "def _fn_alpha(e, x): # do_alpha\n"
            "    e.stats.power += x\n\n"
            "def _fn_beta(e): # do_beta\n"
            "    pass\n\n"
            "def normal_func():\n"
            "    pass\n"
        )
        s_id = kernel.create_script_resource(name="MathScript", code=code)
        assert not isinstance(s_id, Error)
        res = kernel.get_resource(s_id)
        assert res["data"]["symbols"] == {
            "_fn_alpha": "do_alpha",
            "_fn_beta": "do_beta",
        }

    def test_create_script_resource_extracts_symbols_from_source_path(self, tmp_path):
        kernel = Kernel(tmp_path)
        script_file = tmp_path / "combat.py"
        script_file.write_text(
            "def _fn_slash(target, dmg): # slash_attack\n    target.health.current -= dmg\n",
            encoding="utf-8",
        )
        s_id = kernel.create_script_resource(name="Combat", source_path="combat.py")
        assert not isinstance(s_id, Error)
        res = kernel.get_resource(s_id)
        assert res["data"]["symbols"] == {"_fn_slash": "slash_attack"}

    def test_get_script_proxy_validations(self, tmp_path):
        kernel = Kernel(tmp_path)
        # Nonexistent ID
        err = kernel.get_script_proxy(999)
        assert isinstance(err, Error)
        assert err.code == RuntimeIDNotFoundOnMemoryError

        # Type mismatch (Entity instead of Script)
        e_id = kernel.create_entity(name="Hero")
        err2 = kernel.get_script_proxy(e_id)
        assert isinstance(err2, Error)
        assert err2.code == InvalidResourceDataError

        # Valid script
        s_id = kernel.create_script_resource(name="ValidScript", code="x = 1")
        proxy = kernel.get_script_proxy(s_id)
        assert isinstance(proxy, ScriptProxy)
        assert proxy.id == s_id
        assert proxy.name == "ValidScript"
        assert proxy.type == Script
        assert proxy["type"] == Script

    def test_get_script_module_and_caching(self, tmp_path):
        kernel = Kernel(tmp_path)
        code = "def _fn_get_value(): return 42"
        s_id = kernel.create_script_resource(name="ValueScript", code=code)

        # Initial compilation
        mod_globals = kernel.get_script_module(s_id)
        assert not isinstance(mod_globals, Error)
        assert "_fn_get_value" in mod_globals
        assert s_id in kernel._script_module_cache

        # Cache hit returns same dictionary
        cached = kernel.get_script_module(s_id)
        assert cached is mod_globals

        # Cache invalidated on mutation
        kernel.mutate_resource(s_id, {"name": "ValueScript", "code": "def _fn_get_value(): return 99", "requires": [], "symbols": {}})
        assert s_id not in kernel._script_module_cache
        new_globals = kernel.get_script_module(s_id)
        assert not isinstance(new_globals, Error)
        assert new_globals["_fn_get_value"]() == 99

    def test_get_script_callable(self, tmp_path):
        kernel = Kernel(tmp_path)
        code = "def _fn_add(a, b): return a + b\nvalue = 100\n"
        s_id = kernel.create_script_resource(name="Calc", code=code)

        fn = kernel.get_script_callable(s_id, "_fn_add")
        assert callable(fn)
        assert fn(10, 20) == 30

        # Non-callable attribute returns None
        assert kernel.get_script_callable(s_id, "value") is None
        # Non-existent attribute returns None
        assert kernel.get_script_callable(s_id, "nonexistent") is None
        # Invalid script ID returns Error
        assert isinstance(kernel.get_script_callable(999, "_fn_add"), Error)

    def test_script_proxy_dispatch_and_symbol_resolution(self, tmp_path):
        kernel = Kernel(tmp_path)
        code = (
            "def _fn_inflict(target, amount): # take_damage\n"
            "    target.health.current -= amount\n\n"
            "def _fn_heal(target, amount): # restore_health\n"
            "    target.health.current += amount\n"
        )
        s_id = kernel.create_script_resource(name="HealthUtils", code=code)
        proxy = kernel.get_script_proxy(s_id)
        assert isinstance(proxy, ScriptProxy)

        e_id = kernel.create_entity(name="Hero", components={"Health": {"current": 100}})
        e_proxy = kernel.get_entity_proxy(e_id)

        # Call via display name
        proxy.take_damage(e_proxy, 25)
        assert e_proxy.health.current == 75

        # Call via exact symbol
        proxy._fn_heal(e_proxy, 10)
        assert e_proxy.health.current == 85

        # Nonexistent symbol raises AttributeError
        with pytest.raises(AttributeError):
            proxy.nonexistent_function()

        # Private symbol without _fn_ raises AttributeError
        with pytest.raises(AttributeError):
            proxy._private_func

    def test_bound_script_proxy(self, tmp_path):
        kernel = Kernel(tmp_path)
        code = (
            "def _fn_hit(self, dmg): # apply_hit\n"
            "    self.stats.hp -= dmg\n"
        )
        s_id = kernel.create_script_resource(name="Combat", code=code)
        proxy = kernel.get_script_proxy(s_id)

        e_id = kernel.create_entity(name="Target", components={"Stats": {"hp": 100}})
        e_proxy = kernel.get_entity_proxy(e_id)

        bound = proxy.bind(e_proxy)
        assert isinstance(bound, BoundScriptProxy)

        # Method call automatically binds e_proxy as first argument
        bound.apply_hit(30)
        assert e_proxy.stats.hp == 70

    def test_cross_script_bracket_reference_execution(self, tmp_path):
        kernel = Kernel(tmp_path)

        # Library script with damage function
        lib_code = (
            "def _fn_damage(target, amount): # apply_damage\n"
            "    target.health.current -= amount\n"
        )
        lib_id = kernel.create_script_resource(name="DamageLib", code=lib_code)
        lib_sid_hex = kernel.get_storage_id(lib_id).hex()

        # Entity script referencing the library script via <|1|hex|>
        caller_code = (
            f"lib = <|1|{lib_sid_hex}|>\n\n"
            "def update(dt):\n"
            "    lib.apply_damage(self, 15 * dt)\n"
        )
        caller_id = kernel.create_script_resource(name="CallerScript", code=caller_code)

        entity_id = kernel.create_entity(
            name="TargetEntity",
            components={"Health": {"current": 100}},
        )
        kernel.attach_script(entity_id, caller_id)

        # Tick 2 seconds -> damage = 30
        errors = kernel.tick(dt=2.0)
        assert errors is None

        proxy = kernel.get_entity_proxy(entity_id)
        assert proxy.health.current == 70

    def test_cross_script_bound_proxy_via_bracket_reference(self, tmp_path):
        kernel = Kernel(tmp_path)

        lib_code = (
            "def _fn_buff(entity, amt): # apply_buff\n"
            "    entity.stats.atk += amt\n"
        )
        lib_id = kernel.create_script_resource(name="BuffLib", code=lib_code)
        lib_sid_hex = kernel.get_storage_id(lib_id).hex()

        entity_code = (
            f"buff_sys = <|1|{lib_sid_hex}|>\n\n"
            "def update(dt):\n"
            "    b = buff_sys.bind(self)\n"
            "    b.apply_buff(5)\n"
        )
        e_script_id = kernel.create_script_resource(name="EntityScript", code=entity_code)
        e_id = kernel.create_entity(name="Player", components={"Stats": {"atk": 10}})
        kernel.attach_script(e_id, e_script_id)

        errors = kernel.tick(dt=1.0)
        assert errors is None
        assert kernel.get_entity_proxy(e_id).stats.atk == 15
