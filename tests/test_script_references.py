"""Tests for Stage 1: Stable Function Identity and Cross-Script References.

Derives tests from observable user requirements and kernel contracts:
1. Function rename invariance with `<|1|storage_id|>._fn_<id>` in script code.
2. Syntax error handling in referenced scripts (returns Error cleanly without crashing).
3. Non-existent function symbol access raises AttributeError.
4. Cyclic reference protection and graceful resolution between mutually referencing scripts.
"""

from pathlib import Path

import pytest

from LBE import (
    BoundScriptProxy,
    Error,
    Kernel,
    ScriptProxy,
    extract_script_symbols,
)
from LBE.types import (
    InvalidResourceDataError,
)


class TestScriptReferenceRenameInvariance:
    """Verifies that symbol IDs (_fn_<id>) provide stable identity across human display name refactoring."""

    def test_cross_script_invocation_via_symbol_id_survives_display_name_rename(self, tmp_path):
        kernel = Kernel(tmp_path)

        # Provider script defines stable symbol _fn_calc_mul with initial display name
        code_v1 = (
            "def _fn_calc_mul(factor, val): # multiply\n"
            "    return factor * val\n"
        )
        lib_id = kernel.create_script_resource(name="MathLib", code=code_v1)
        assert not isinstance(lib_id, Error)
        lib_hex = kernel.get_storage_id(lib_id).hex()

        # Consumer script references provider via bracket syntax and durable symbol ID
        consumer_code = (
            f"math = <|1|{lib_hex}|>\n\n"
            "def update(dt):\n"
            "    self.stats.value = math._fn_calc_mul(2, self.stats.value)\n"
        )
        consumer_id = kernel.create_script_resource(name="ConsumerScript", code=consumer_code)
        assert not isinstance(consumer_id, Error)

        entity_id = kernel.create_entity(name="Worker", components={"Stats": {"value": 5}})
        kernel.attach_script(entity_id, consumer_id)

        # Initial execution
        errors = kernel.tick(dt=1.0)
        assert errors is None
        proxy = kernel.get_entity_proxy(entity_id)
        assert proxy.stats.value == 10

        # Refactor/rename human display name in comment: # multiply -> # compute_product
        code_v2 = (
            "def _fn_calc_mul(factor, val): # compute_product\n"
            "    return factor * val\n"
        )
        kernel.mutate_resource(
            lib_id,
            {
                "name": "MathLib",
                "code": code_v2,
                "requires": [],
                "symbols": extract_script_symbols(code_v2),
            },
        )

        # Consumer script continues ticking without breaking!
        errors = kernel.tick(dt=1.0)
        assert errors is None
        assert proxy.stats.value == 20

        # Direct proxy invocation via durable symbol ID succeeds
        lib_proxy = kernel.get_script_proxy(lib_id)
        assert lib_proxy._fn_calc_mul(3, 10) == 30

        # Direct proxy invocation via new display name succeeds
        assert lib_proxy.compute_product(3, 10) == 30

        # Direct proxy invocation via old display name raises AttributeError
        with pytest.raises(AttributeError):
            lib_proxy.multiply(3, 10)

    def test_cross_script_invocation_via_display_name_breaks_upon_rename(self, tmp_path):
        """Negative contrast test: calling via display name directly in script breaks when renamed,

        demonstrating why durable symbol IDs (_fn_<id>) are required for robust references.
        """
        kernel = Kernel(tmp_path)

        code_v1 = (
            "def _fn_boost(val): # quick_boost\n"
            "    return val + 10\n"
        )
        lib_id = kernel.create_script_resource(name="BoostLib", code=code_v1)
        lib_hex = kernel.get_storage_id(lib_id).hex()

        # Consumer calls via ephemeral display name rather than durable symbol ID
        consumer_code = (
            f"boost_lib = <|1|{lib_hex}|>\n\n"
            "def update(dt):\n"
            "    self.stats.value = boost_lib.quick_boost(self.stats.value)\n"
        )
        consumer_id = kernel.create_script_resource(name="FragileConsumer", code=consumer_code)
        entity_id = kernel.create_entity(name="Unit", components={"Stats": {"value": 5}})
        kernel.attach_script(entity_id, consumer_id)

        # Ticking works before rename
        errors = kernel.tick(dt=1.0)
        assert errors is None
        assert kernel.get_entity_proxy(entity_id).stats.value == 15

        # Refactor display name: quick_boost -> mega_boost
        code_v2 = (
            "def _fn_boost(val): # mega_boost\n"
            "    return val + 10\n"
        )
        kernel.mutate_resource(
            lib_id,
            {
                "name": "BoostLib",
                "code": code_v2,
                "requires": [],
                "symbols": extract_script_symbols(code_v2),
            },
        )

        # Ticking now produces an execution error because old display name quick_boost no longer exists
        errors = kernel.tick(dt=1.0)
        assert isinstance(errors, list)
        assert len(errors) == 1
        assert "quick_boost" in str(errors[0].description) or "quick_boost" in str(errors[0].message)


class TestScriptReferenceSyntaxErrorHandling:
    """Verifies that syntax and compilation errors in referenced scripts are handled cleanly."""

    def test_syntax_error_in_inline_script_returns_error_cleanly(self, tmp_path):
        kernel = Kernel(tmp_path)

        # Create script resource containing invalid Python syntax
        broken_code = "def invalid_syntax(x: return x +"
        s_id = kernel.create_script_resource(name="BrokenScript", code=broken_code)
        assert not isinstance(s_id, Error)

        # get_script_module returns Error without crashing
        mod = kernel.get_script_module(s_id)
        assert isinstance(mod, Error)
        assert mod.code == InvalidResourceDataError
        assert "compilation error" in mod.message.lower()

        # get_script_callable returns Error without crashing
        fn = kernel.get_script_callable(s_id, "_fn_anything")
        assert isinstance(fn, Error)
        assert fn.code == InvalidResourceDataError

        # ScriptProxy attribute access cleanly raises AttributeError
        proxy = kernel.get_script_proxy(s_id)
        assert isinstance(proxy, ScriptProxy)
        with pytest.raises(AttributeError):
            proxy._fn_anything()

    def test_syntax_error_in_source_path_script_returns_error_cleanly(self, tmp_path):
        kernel = Kernel(tmp_path)

        script_file = tmp_path / "broken_file.py"
        script_file.write_text("class 123 InvalidClass:\n    pass\n", encoding="utf-8")

        s_id = kernel.create_script_resource(name="BrokenFileScript", source_path=str(script_file))
        assert not isinstance(s_id, Error)

        mod = kernel.get_script_module(s_id)
        assert isinstance(mod, Error)
        assert mod.code == InvalidResourceDataError

        fn = kernel.get_script_callable(s_id, "_fn_any")
        assert isinstance(fn, Error)

    def test_tick_aggregates_error_when_entity_script_references_syntax_error_script(self, tmp_path):
        kernel = Kernel(tmp_path)

        broken_id = kernel.create_script_resource(name="BrokenLib", code="def broken(:\n    pass")
        broken_hex = kernel.get_storage_id(broken_id).hex()

        caller_code = (
            f"broken = <|1|{broken_hex}|>\n\n"
            "def update(dt):\n"
            "    broken.some_call()\n"
        )
        caller_id = kernel.create_script_resource(name="Caller", code=caller_code)

        e_faulty = kernel.create_entity(name="FaultyEntity")
        kernel.attach_script(e_faulty, caller_id)

        # Unrelated healthy entity
        healthy_code = "def update(dt): self.health.current += 1\n"
        healthy_id = kernel.create_script_resource(name="Healthy", code=healthy_code)
        e_healthy = kernel.create_entity(name="HealthyEntity", components={"Health": {"current": 50}})
        kernel.attach_script(e_healthy, healthy_id)

        # Tick catches faulty script error in returned error list; healthy entity still updates
        errors = kernel.tick(dt=1.0)
        assert isinstance(errors, list)
        assert len(errors) == 1
        assert kernel.get_entity_proxy(e_healthy).health.current == 51

    def test_syntax_error_in_attached_entity_script_does_not_crash_kernel(self, tmp_path):
        kernel = Kernel(tmp_path)

        broken_id = kernel.create_script_resource(name="SyntaxErrorScript", code="def update(:\n    pass")
        e_id = kernel.create_entity(name="BrokenEntity")
        kernel.attach_script(e_id, broken_id)

        errors = kernel.tick(dt=1.0)
        assert isinstance(errors, list)
        assert len(errors) == 1
        assert "compilation error" in errors[0].message.lower()


class TestNonExistentFunctionSymbolAccess:
    """Verifies that non-existent symbols, non-callables, and invalid prefixes raise AttributeError."""

    def test_nonexistent_symbol_id_on_script_proxy_raises_attribute_error(self, tmp_path):
        kernel = Kernel(tmp_path)
        code = "def _fn_exists(x): return x\n"
        s_id = kernel.create_script_resource(name="Utils", code=code)
        proxy = kernel.get_script_proxy(s_id)

        with pytest.raises(AttributeError) as exc_info:
            proxy._fn_missing_symbol()
        assert "no attribute or function '_fn_missing_symbol'" in str(exc_info.value)

    def test_nonexistent_display_name_on_script_proxy_raises_attribute_error(self, tmp_path):
        kernel = Kernel(tmp_path)
        code = "def _fn_exists(x): # run_exists\n    return x\n"
        s_id = kernel.create_script_resource(name="Utils", code=code)
        proxy = kernel.get_script_proxy(s_id)

        with pytest.raises(AttributeError) as exc_info:
            proxy.missing_display_name()
        assert "no attribute or function 'missing_display_name'" in str(exc_info.value)

    def test_private_symbol_not_starting_with_fn_raises_attribute_error(self, tmp_path):
        kernel = Kernel(tmp_path)
        code = "_private_var = 10\ndef _private_func(): pass\n"
        s_id = kernel.create_script_resource(name="Utils", code=code)
        proxy = kernel.get_script_proxy(s_id)

        with pytest.raises(AttributeError) as exc_info:
            proxy._private_func()
        assert "has no attribute '_private_func'" in str(exc_info.value)

    def test_non_callable_attribute_raises_attribute_error(self, tmp_path):
        kernel = Kernel(tmp_path)
        code = "CONST_VALUE = 42\ndef _fn_valid(): pass\n"
        s_id = kernel.create_script_resource(name="Config", code=code)
        proxy = kernel.get_script_proxy(s_id)

        # get_script_callable returns None for non-callables
        assert kernel.get_script_callable(s_id, "CONST_VALUE") is None

        # proxy attribute access raises AttributeError
        with pytest.raises(AttributeError):
            proxy.CONST_VALUE()

    def test_bound_script_proxy_nonexistent_symbol_raises_attribute_error(self, tmp_path):
        kernel = Kernel(tmp_path)
        code = "def _fn_act(self): pass\n"
        s_id = kernel.create_script_resource(name="Actions", code=code)
        proxy = kernel.get_script_proxy(s_id)
        e_id = kernel.create_entity(name="Hero")
        e_proxy = kernel.get_entity_proxy(e_id)

        bound = proxy.bind(e_proxy)
        assert isinstance(bound, BoundScriptProxy)

        with pytest.raises(AttributeError):
            bound.nonexistent_function()

        with pytest.raises(AttributeError):
            bound._fn_nonexistent()


class TestScriptCyclicReferences:
    """Verifies that circular and mutual references between scripts resolve gracefully without deadlocking."""

    def test_mutual_script_function_cross_references_resolve_gracefully(self, tmp_path):
        kernel = Kernel(tmp_path)

        # Pre-allocate script resources to obtain stable storage IDs
        s_a = kernel.create_script_resource(name="PingScript", code="# placeholder")
        s_b = kernel.create_script_resource(name="PongScript", code="# placeholder")
        hex_a = kernel.get_storage_id(s_a).hex()
        hex_b = kernel.get_storage_id(s_b).hex()

        code_a = (
            f"pong_lib = <|1|{hex_b}|>\n\n"
            "def _fn_ping(n): # ping\n"
            "    if n <= 0:\n"
            "        return 'ping_end'\n"
            "    return pong_lib._fn_pong(n - 1)\n"
        )
        code_b = (
            f"ping_lib = <|1|{hex_a}|>\n\n"
            "def _fn_pong(n): # pong\n"
            "    if n <= 0:\n"
            "        return 'pong_end'\n"
            "    return ping_lib._fn_ping(n - 1)\n"
        )

        kernel.mutate_resource(
            s_a,
            {"name": "PingScript", "code": code_a, "requires": [], "symbols": extract_script_symbols(code_a)},
        )
        kernel.mutate_resource(
            s_b,
            {"name": "PongScript", "code": code_b, "requires": [], "symbols": extract_script_symbols(code_b)},
        )

        proxy_a = kernel.get_script_proxy(s_a)
        proxy_b = kernel.get_script_proxy(s_b)

        # Cross-call from A -> B -> A -> B -> pong_end
        assert proxy_a._fn_ping(3) == "pong_end"

        # Cross-call from A -> B -> A -> B -> A -> ping_end
        assert proxy_a._fn_ping(4) == "ping_end"

        # Mutual calls via human display names also resolve gracefully
        assert proxy_a.ping(1) == "pong_end"
        assert proxy_b.pong(2) == "pong_end"

    def test_mutual_script_bound_proxies_interact_between_two_entities(self, tmp_path):
        kernel = Kernel(tmp_path)

        s_atk = kernel.create_script_resource(name="AttackerScript", code="# placeholder")
        s_def = kernel.create_script_resource(name="DefenderScript", code="# placeholder")
        hex_atk = kernel.get_storage_id(s_atk).hex()
        hex_def = kernel.get_storage_id(s_def).hex()

        code_atk = (
            f"def_lib = <|1|{hex_def}|>\n\n"
            "def _fn_strike(self, opponent): # strike\n"
            "    bound_def = def_lib.bind(opponent)\n"
            "    reduced_dmg = bound_def.absorb(self.combat.attack)\n"
            "    opponent.combat.hp -= reduced_dmg\n"
        )
        code_def = (
            f"atk_lib = <|1|{hex_atk}|>\n\n"
            "def _fn_absorb(self, incoming_dmg): # absorb\n"
            "    defense = self.combat.defense\n"
            "    return max(0, incoming_dmg - defense)\n"
        )

        kernel.mutate_resource(
            s_atk,
            {"name": "AttackerScript", "code": code_atk, "requires": [], "symbols": extract_script_symbols(code_atk)},
        )
        kernel.mutate_resource(
            s_def,
            {"name": "DefenderScript", "code": code_def, "requires": [], "symbols": extract_script_symbols(code_def)},
        )

        e_hero = kernel.create_entity(name="Hero", components={"Combat": {"attack": 25, "defense": 5, "hp": 100}})
        e_boss = kernel.create_entity(name="Boss", components={"Combat": {"attack": 15, "defense": 10, "hp": 100}})

        hero_proxy = kernel.get_entity_proxy(e_hero)
        boss_proxy = kernel.get_entity_proxy(e_boss)

        atk_proxy = kernel.get_script_proxy(s_atk)
        bound_hero_atk = atk_proxy.bind(hero_proxy)

        # Hero strikes boss: dmg = 25 - 10 = 15 -> Boss HP = 85
        bound_hero_atk.strike(boss_proxy)
        assert boss_proxy.combat.hp == 85

    def test_three_way_cyclic_references_resolve_and_execute(self, tmp_path):
        kernel = Kernel(tmp_path)

        s1 = kernel.create_script_resource(name="S1", code="#")
        s2 = kernel.create_script_resource(name="S2", code="#")
        s3 = kernel.create_script_resource(name="S3", code="#")
        h1 = kernel.get_storage_id(s1).hex()
        h2 = kernel.get_storage_id(s2).hex()
        h3 = kernel.get_storage_id(s3).hex()

        c1 = f"mod2 = <|1|{h2}|>\ndef _fn_f1(x): # f1\n  return mod2._fn_f2(x + 1)\n"
        c2 = f"mod3 = <|1|{h3}|>\ndef _fn_f2(x): # f2\n  return mod3._fn_f3(x * 2)\n"
        c3 = f"mod1 = <|1|{h1}|>\ndef _fn_f3(x): # f3\n  return x - 5\n"

        kernel.mutate_resource(s1, {"name": "S1", "code": c1, "requires": [], "symbols": extract_script_symbols(c1)})
        kernel.mutate_resource(s2, {"name": "S2", "code": c2, "requires": [], "symbols": extract_script_symbols(c2)})
        kernel.mutate_resource(s3, {"name": "S3", "code": c3, "requires": [], "symbols": extract_script_symbols(c3)})

        p1 = kernel.get_script_proxy(s1)
        # f1(3) -> f2(4) -> f3(8) -> 8 - 5 = 3
        assert p1._fn_f1(3) == 3

    def test_top_level_circular_import_execution_handled_safely(self, tmp_path):
        """Top-level circular invocation triggers RecursionError during module exec,

        which kernel.get_script_module catches and returns as an Error cleanly without crashing.
        """
        kernel = Kernel(tmp_path)

        s_a = kernel.create_script_resource(name="TopA", code="#")
        s_b = kernel.create_script_resource(name="TopB", code="#")
        hex_a = kernel.get_storage_id(s_a).hex()
        hex_b = kernel.get_storage_id(s_b).hex()

        code_a = f"b_lib = <|1|{hex_b}|>\nval = b_lib.calc()\n"
        code_b = f"a_lib = <|1|{hex_a}|>\ndef calc(): return a_lib.calc()\nval = a_lib.calc()\n"

        kernel.mutate_resource(s_a, {"name": "TopA", "code": code_a, "requires": [], "symbols": {}})
        kernel.mutate_resource(s_b, {"name": "TopB", "code": code_b, "requires": [], "symbols": {}})

        err = kernel.get_script_module(s_a)
        assert isinstance(err, Error)
        assert err.code == InvalidResourceDataError
        assert "compilation error" in err.message.lower()


class TestStage1Remediations:
    """Verifies all 5 architectural remediations implemented for Stage 1."""

    def test_source_path_mtime_caching_and_live_reload(self, tmp_path, monkeypatch):
        """Finding 1 & 2: Avoids disk I/O when mtime is unchanged, and reloads code and symbols when mtime changes."""
        import os

        kernel = Kernel(tmp_path)
        script_file = tmp_path / "behavior.py"
        script_file.write_text(
            "def _fn_step(e, dt): # do_step\n"
            "    e.stats.speed += 5 * dt\n"
            "def update(self, dt):\n"
            "    _fn_step(self, dt)\n",
            encoding="utf-8",
        )

        s_id = kernel.create_script_resource(name="Behavior", source_path=str(script_file))
        assert not isinstance(s_id, Error)

        e_id = kernel.create_entity(name="Hero", components={"Stats": {"speed": 10}})
        kernel.attach_script(e_id, s_id)

        # Initial tick populates mtime and module caches
        errors = kernel.tick(dt=1.0)
        assert errors is None
        proxy = kernel.get_entity_proxy(e_id)
        assert proxy.stats.speed == 15
        assert s_id in kernel._script_mtime_cache
        assert s_id in kernel._script_module_cache

        # Subsequent tick uses cache without reading disk
        read_count = 0
        orig_read_text = Path.read_text

        def mock_read_text(path_self, *args, **kwargs):
            nonlocal read_count
            read_count += 1
            return orig_read_text(path_self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", mock_read_text)

        errors2 = kernel.tick(dt=1.0)
        assert errors2 is None
        assert proxy.stats.speed == 20
        # read_text was not called because mtime was unchanged!
        assert read_count == 0

        # Now external file is modified on disk with new mtime
        monkeypatch.undo()
        current_stat = script_file.stat()
        new_mtime = current_stat.st_mtime_ns + 2_000_000_000
        script_file.write_text(
            "def _fn_step(e, dt): # do_boost\n"
            "    e.stats.speed += 20 * dt\n"
            "def update(self, dt):\n"
            "    _fn_step(self, dt)\n",
            encoding="utf-8",
        )
        os.utime(script_file, ns=(new_mtime, new_mtime))

        # Proxy symbols automatically refresh to new display name
        s_proxy = kernel.get_script_proxy(s_id)
        assert "do_boost" in s_proxy.symbols.values()
        assert "do_step" not in s_proxy.symbols.values()

        # Tick runs the updated code
        errors3 = kernel.tick(dt=1.0)
        assert errors3 is None
        assert proxy.stats.speed == 40  # 20 + 20

    def test_bound_script_proxy_non_callable_attributes(self, tmp_path):
        """Finding 3: BoundScriptProxy allows accessing non-callable attributes without TypeError."""
        kernel = Kernel(tmp_path)
        code = (
            "def _fn_act(self): # act\n"
            "    return self.name\n"
        )
        s_id = kernel.create_script_resource(name="HeroSkill", code=code)
        proxy = kernel.get_script_proxy(s_id)

        e_id = kernel.create_entity(name="Warrior")
        e_proxy = kernel.get_entity_proxy(e_id)

        bound = proxy.bind(e_proxy)
        assert isinstance(bound, BoundScriptProxy)

        # Accessing non-callables must NOT raise TypeError
        assert bound.name == "HeroSkill"
        assert bound.id == s_id
        assert bound.storage_id == proxy.storage_id
        assert bound.type == 1
        assert isinstance(bound.symbols, dict)
        assert "act" in bound.symbols.values()

        # Calling function properly binds entity
        assert bound.act() == "Warrior"
        assert bound._fn_act() == "Warrior"

        # Nonexistent attribute raises AttributeError
        with pytest.raises(AttributeError):
            _ = bound.nonexistent_attribute

    def test_method_sig_cache_eviction_on_mutate_and_reload(self, tmp_path):
        """Finding 4: _method_sig_cache is keyed by (s_rid, method_name) and evicted on mutation/reload."""
        kernel = Kernel(tmp_path)
        code_v1 = "def update(e, dt): e.stats.score += 1\n"
        s_id = kernel.create_script_resource(name="Scorer", code=code_v1)
        kernel.get_storage_id(s_id)
        kernel.save_dirty_resources()

        e_id = kernel.create_entity(name="Player", components={"Stats": {"score": 0}})
        kernel.attach_script(e_id, s_id)

        kernel.tick(dt=1.0)
        assert (s_id, "update") in kernel._method_sig_cache
        assert kernel._method_sig_cache[((s_id, "update"))][0] == 2

        # Mutate resource: cache entry for s_id must be evicted
        code_v2 = "def update(dt): self.stats.score += 5\n"
        kernel.mutate_resource(
            s_id,
            {"name": "Scorer", "code": code_v2, "requires": [], "symbols": {}},
        )
        assert (s_id, "update") not in kernel._method_sig_cache

        # Tick with new signature re-populates cache with updated signature
        kernel.tick(dt=1.0)
        assert (s_id, "update") in kernel._method_sig_cache
        assert kernel._method_sig_cache[(s_id, "update")][0] == 1

        # Reload resource from disk: cache entry must be evicted
        assert kernel.reload_resource(s_id) is None
        assert (s_id, "update") not in kernel._method_sig_cache

    def test_script_proxy_symbols_fallback_when_absent(self, tmp_path):
        """Finding 2: ScriptProxy.symbols falls back to code extraction when 'symbols' key is absent."""
        kernel = Kernel(tmp_path)
        code = "def _fn_strike(): # slash\n    pass\n"
        s_id = kernel.create_script_resource(name="Skill", code=code)

        # Manually remove symbols key from in-memory resource data
        kernel.resources[s_id]["data"].pop("symbols", None)

        proxy = kernel.get_script_proxy(s_id)
        assert proxy.symbols == {"_fn_strike": "slash"}
        # And updates in-memory dictionary
        assert proxy.data["symbols"] == {"_fn_strike": "slash"}

    def test_run_entity_scripts_delegates_to_module_with_globals_context(self, tmp_path):
        """Finding 5: run_entity_scripts delegates to get_script_module and supports signature styles."""
        kernel = Kernel(tmp_path)

        # Script using self and dt from module globals directly
        code_globals = """
def update():
    self.stats.val += dt * 10
"""
        s_id = kernel.create_script_resource(name="GlobalsScript", code=code_globals)
        e_id = kernel.create_entity(components={"Stats": {"val": 0}})
        kernel.attach_script(e_id, s_id)

        kernel.tick(dt=2.0)
        proxy = kernel.get_entity_proxy(e_id)
        assert proxy.stats.val == 20

