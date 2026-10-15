"""Comprehensive verification tests for Pure-UUID Function Exports & Dynamic Property Components.

Derives tests from observable user requirements and engine contracts:
1. Pure-UUID Function Export & Registry:
   - Defining scripts with @export("<32-hex-uuid>").
   - Resolving function exports via kernel.resolve_function_export("<uuid>").
   - Moving exported functions to a different script or renaming the Python function symbol
     while retaining the same export UUID -> external callers and property components resolve seamlessly.
   - Dynamic lazy auto-discovery when resolving an export from a loaded script.
   - Requesting an unknown/missing export UUID returns Error(code=BrokenReferenceError).
   - UID normalization (case-insensitivity, hyphens/dashes stripped, bytes vs str).
2. Computed Property Evaluation (EntityProxy):
   - Dynamic computed property (e.g. HealthPercent computing (current / max) * 100).
   - Accessing via entity.HealthPercent, entity["HealthPercent"], entity.get("HealthPercent"), entity.has("HealthPercent").
   - Mutating underlying component (e.g. entity.Health["current"] = 50) -> subsequent property access returns
     updated calculated value (no stale cache).
   - Dynamic derived geometry (e.g. Area computing width * height).
   - Various component naming layouts (Property:Name, Property component dict, etc.).
3. Proxy / Converter Property (Getter & Setter):
   - Converter property (e.g. DistanceMeters exposing distance in meters while Spatial stores centimeters).
   - Invoking setter entity.DistanceMeters = 2.5 updates entity.Spatial["cm"] == 250.0.
   - Dirty tracking: invoking setter marks the entity dirty in the kernel.
4. Read-Only Property Enforcement:
   - Property with setter="" or setter=None.
   - Attempting entity.ReadOnlyProp = 10 raises AttributeError with clear message.
   - Attempting del entity.ReadOnlyProp raises AttributeError.
5. Cycle Detection:
   - Mutual property cycle: Property A getter reads Property B, Property B getter reads Property A.
   - Self-referencing cycle: Property A getter reads Property A.
   - Attempting evaluation raises RuntimeError matching "Circular property evaluation detected".
   - Call stack tracking cleans up after error so subsequent healthy property reads continue to work.
6. Diagnostics & Missing Reference Resilience:
   - Entity with a Property component whose getter points to a non-existent UUID.
   - Evaluating entity.BrokenProp raises AttributeError containing getter error diagnostics rather than unhandled crash.
   - Evaluating entity["BrokenProp"] raises KeyError, entity.get("BrokenProp", default) returns default.
   - Property with a broken setter points to non-existent UUID raises AttributeError on assignment.
   - Entity destroyed / stale handle safety: calling property on destroyed entity raises cleanly.
7. Property Component Schema Validation & Integrity:
   - Validate Property schema using ValidateUI.validate_ui_component / Validate.ui_component.
   - Rejects non-hex getter UUID.
   - Rejects invalid hex getter length (e.g. not 32 or 64 characters).
   - Rejects empty name (unless default schema template).
   - Rejects non-mapping presentation_args.
   - Rejects non-string presentation.
   - Rejects invalid setter format (non-hex, invalid length).
   - Accepts valid Property schemas (both standalone and Property:<name> shorthand).
8. Persistence & Serialization Roundtrip:
   - Create entity with Property:HealthPercent and attached scripts.
   - Save project to disk (kernel.save_dirty_resources(), kernel.save_project()).
   - In a fresh Kernel instance, load project via kernel.load_project().
   - Verify Property component reloads from JSON with pure UUIDs intact, evaluates dynamically on the
     reloaded entity proxy, and setter mutates state correctly.
   - Inspect JSON file on disk to verify pure UUIDs preserved without runtime handles.
9. Editor Pill & Presentation Projection Integration:
   - Test parse_reference_pill for exported UUID hex string -> returns PillData with script name and display name.
   - Test render_function_export_pill rendering pill button.
   - Test InspectorPanel property card rendering in headless mode (both slider and text presentations).
   - Test InspectorPanel._on_property_value_changed callback updating entity via setter.
   - Test UIBridgePanel non-visual exclusion for Property components.
10. Planned Tests for Unimplemented Features:
   - Planned test (skipped): Preprocessor or editor automatic call-site refactoring when an export UUID is renamed.
   - Planned hot reload rollback on syntax error: preserves previous valid module and export mappings.
   - Planned stale handle safety when referenced script is destroyed.
   - Planned failed-load cleanup: transactional rollback when dependency loading fails.
"""

from __future__ import annotations

import json
from pathlib import Path
import dearpygui.dearpygui as dpg
import pytest

from editor import (
    PillData,
    parse_reference_pill,
    render_function_export_pill,
)
from editor.inspector_panel import InspectorPanel
from editor.session import EditorSession
from editor.ui_bridge import UIBridgePanel
from LBE import Error, Kernel, Script
from LBE.integrity import Validate
from LBE.scripts import export
from LBE.types import (
    BrokenReferenceError,
    InvalidResourceDataError,
)
from LBE.ui import UI_SCHEMAS, ValidateUI


# =============================================================================
# Pytest Fixtures & Helpers
# =============================================================================

@pytest.fixture
def dpg_context():
    """Fixture providing an isolated Dear PyGui context per test."""
    try:
        dpg.destroy_context()
    except Exception:
        pass
    dpg.create_context()
    yield
    try:
        dpg.destroy_context()
    except Exception:
        pass


def find_items_by_type(root_tag: str | int, item_type: str) -> list[tuple[int | str, str]]:
    """Traverse DPG hierarchy from root_tag and return list of (item_tag, text) for items of given type."""
    results: list[tuple[int | str, str]] = []

    def _walk(tag: int | str) -> None:
        for slot in (0, 1, 2):
            children = dpg.get_item_children(tag, slot)
            if not children:
                continue
            for child in children:
                info = dpg.get_item_info(child)
                if info.get("type") == item_type:
                    val = dpg.get_value(child)
                    lbl = dpg.get_item_label(child)
                    text = str(lbl) if lbl else str(val if val is not None else "")
                    results.append((child, text))
                _walk(child)

    if dpg.does_item_exist(root_tag):
        _walk(root_tag)
    return results


def find_buttons(root_tag: str | int, text_match: str | None = None) -> list[tuple[int | str, str]]:
    """Traverse DPG hierarchy from root_tag and return list of (item_tag, label) for mvButton items."""
    results: list[tuple[int | str, str]] = []

    def _walk(tag: int | str) -> None:
        for slot in (0, 1, 2):
            children = dpg.get_item_children(tag, slot)
            if not children:
                continue
            for child in children:
                info = dpg.get_item_info(child)
                if info.get("type") == "mvAppItemType::mvButton":
                    lbl = dpg.get_item_label(child)
                    if text_match is None or text_match in lbl:
                        results.append((child, lbl))
                _walk(child)

    if dpg.does_item_exist(root_tag):
        _walk(root_tag)
    return results


# =============================================================================
# 1. Pure-UUID Function Export & Registry
# =============================================================================

class TestPureUuidFunctionExports:
    """Verify @export registration, normalization, resolution and rename invariance."""

    def test_export_decorator_exported_from_lbe(self) -> None:
        """Verify export decorator is public API and callable."""
        from LBE import export as lbe_export
        assert callable(export)
        assert export is lbe_export

    def test_export_decorator_registration_and_resolution(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        uuid_hex = "11112222333344445555666677778888"
        script_code = f'''
@export("{uuid_hex}")
def compute_score(entity):
    return 42
'''
        s_rid = kernel.create_script_resource(name="ScoreModule", code=script_code)
        assert not isinstance(s_rid, Error)

        # Resolve export via kernel facade
        res = kernel.resolve_function_export(uuid_hex)
        assert not isinstance(res, Error)
        fn, script_rid = res
        assert callable(fn)
        assert script_rid == s_rid
        assert fn(None) == 42

    def test_export_decorator_signature_variants(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        uuid_explicit = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        script_code = f'''
@export("{uuid_explicit}")
def fn_explicit(entity):
    return "explicit"

@export
def fn_bare(entity):
    return "bare"

@export()
def fn_empty_parens(entity):
    return "empty_parens"
'''
        s_rid = kernel.create_script_resource(name="VariantsModule", code=script_code)
        assert not isinstance(s_rid, Error)

        # Explicit UUID resolution
        res_exp = kernel.resolve_function_export(uuid_explicit)
        assert not isinstance(res_exp, Error)
        fn_exp, _ = res_exp
        assert fn_exp(None) == "explicit"

        # Bare export resolves by function name
        res_bare = kernel.resolve_function_export("fn_bare")
        assert not isinstance(res_bare, Error)
        fn_bare, _ = res_bare
        assert fn_bare(None) == "bare"

        # Empty parens export resolves by function name
        res_empty = kernel.resolve_function_export("fn_empty_parens")
        assert not isinstance(res_empty, Error)
        fn_empty, _ = res_empty
        assert fn_empty(None) == "empty_parens"

    def test_resolve_function_export_uuid_normalization(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        uuid_hex = "1234567890abcdef1234567890abcdef"
        uuid_with_hyphens = "12345678-90ab-cdef-1234-567890abcdef"
        uuid_uppercase = "1234567890ABCDEF1234567890ABCDEF"
        uuid_bytes = bytes.fromhex(uuid_hex)

        script_code = f'''
@export("{uuid_hex}")
def compute_val(entity):
    return 100
'''
        s_rid = kernel.create_script_resource(name="NormModule", code=script_code)
        assert not isinstance(s_rid, Error)

        # Lowercase exact
        r1 = kernel.resolve_function_export(uuid_hex)
        assert not isinstance(r1, Error)
        assert r1[0](None) == 100

        # Uppercase
        r2 = kernel.resolve_function_export(uuid_uppercase)
        assert not isinstance(r2, Error)
        assert r2[0](None) == 100

        # With standard UUID hyphens
        r3 = kernel.resolve_function_export(uuid_with_hyphens)
        assert not isinstance(r3, Error)
        assert r3[0](None) == 100

        # As raw bytes
        r4 = kernel.resolve_function_export(uuid_bytes)
        assert not isinstance(r4, Error)
        assert r4[0](None) == 100

    def test_resolve_function_export_missing_uuid_returns_broken_reference_error(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        missing_uuid = "ffffffffffffffffffffffffffffffff"

        res = kernel.resolve_function_export(missing_uuid)
        assert isinstance(res, Error)
        assert res.code == BrokenReferenceError
        assert "not found" in res.description.lower()

    def test_dynamic_lazy_auto_discovery_of_exports(self, tmp_path: Path) -> None:
        """Verify that resolving an export automatically activates unactivated scripts in memory."""
        kernel = Kernel(tmp_path)
        uuid_hex = "22223333444455556666777788889999"
        script_code = f'''
@export("{uuid_hex}")
def lazy_fn(entity):
    return 777
'''
        s_rid = kernel.create_script_resource(name="LazyScript", code=script_code)
        assert not isinstance(s_rid, Error)

        # Function exports dictionary does not have it yet prior to any script activation
        assert uuid_hex not in kernel.function_exports

        # Resolving triggers automatic lazy discovery and activation
        res = kernel.resolve_function_export(uuid_hex)
        assert not isinstance(res, Error)
        fn, rid = res
        assert rid == s_rid
        assert fn(None) == 777
        assert uuid_hex in kernel.function_exports

    def test_export_relocation_to_different_script_preserves_resolution(self, tmp_path: Path) -> None:
        """Moving an exported function to a different script preserves external UUID resolution."""
        kernel = Kernel(tmp_path)
        uuid_hex = "3333444455556666777788889999aaaa"

        code_a = f'''
@export("{uuid_hex}")
def func_in_a(entity):
    return "version_from_script_a"
'''
        s_rid_a = kernel.create_script_resource(name="ScriptA", code=code_a)
        assert not isinstance(s_rid_a, Error)

        res1 = kernel.resolve_function_export(uuid_hex)
        assert not isinstance(res1, Error)
        assert res1[0](None) == "version_from_script_a"
        assert res1[1] == s_rid_a

        # Move export to Script B
        code_a_cleared = "# Export removed\n"
        code_b = f'''
@export("{uuid_hex}")
def func_in_b(entity):
    return "version_from_script_b"
'''
        assert kernel.update_script_source(s_rid_a, code_a_cleared) is None
        s_rid_b = kernel.create_script_resource(name="ScriptB", code=code_b)
        assert not isinstance(s_rid_b, Error)

        # Clear cached export map entry to simulate fresh resolution/discovery
        kernel.function_exports.pop(uuid_hex, None)

        res2 = kernel.resolve_function_export(uuid_hex)
        assert not isinstance(res2, Error)
        assert res2[0](None) == "version_from_script_b"
        assert res2[1] == s_rid_b

    def test_export_rename_within_script_preserves_resolution(self, tmp_path: Path) -> None:
        """Renaming a Python function symbol in place while retaining export UUID should resolve seamlessly."""
        kernel = Kernel(tmp_path)
        uuid_hex = "3333444455556666777788889999bbbb"

        code_v1 = f'''
@export("{uuid_hex}")
def original_symbol_name(entity):
    return "result_v1"
'''
        s_rid = kernel.create_script_resource(name="RenameScript", code=code_v1)
        assert not isinstance(s_rid, Error)

        res1 = kernel.resolve_function_export(uuid_hex)
        assert not isinstance(res1, Error)
        assert res1[0](None) == "result_v1"

        # Rename Python function symbol in place
        code_v2 = f'''
@export("{uuid_hex}")
def refactored_symbol_name(entity):
    return "result_v2"
'''
        assert kernel.update_script_source(s_rid, code_v2) is None

        # Should resolve to new symbol seamlessly on first subsequent call
        res2 = kernel.resolve_function_export(uuid_hex)
        assert not isinstance(res2, Error)
        assert res2[0](None) == "result_v2"


# =============================================================================
# 2. Computed Property Evaluation (EntityProxy)
# =============================================================================

class TestComputedPropertyEvaluation:
    """Verify dynamic evaluation of calculated properties through EntityProxy."""

    def test_health_percent_computed_property(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        hp_getter_uuid = "444455556666777788889999aaaabbbb"

        script_code = f'''
@export("{hp_getter_uuid}")
def get_health_percent(entity):
    hp = entity.Health
    return (hp["current"] / hp["max"]) * 100.0
'''
        s_rid = kernel.create_script_resource(name="HealthScript", code=script_code)
        assert not isinstance(s_rid, Error)

        e_rid = kernel.create_entity(
            name="Player",
            components={
                "Health": {"current": 75.0, "max": 100.0},
                "Property:HealthPercent": {
                    "name": "HealthPercent",
                    "getter": hp_getter_uuid,
                    "presentation": "slider",
                    "presentation_args": {"min": 0.0, "max": 100.0},
                },
            },
        )
        assert not isinstance(e_rid, Error)

        entity = kernel.get_entity_proxy(e_rid)
        assert entity is not None

        # Evaluates dynamically
        assert entity.HealthPercent == 75.0
        assert entity["HealthPercent"] == 75.0
        assert entity.get("HealthPercent") == 75.0
        assert entity.has("HealthPercent") is True

    def test_property_cache_invalidation_on_component_mutation(self, tmp_path: Path) -> None:
        """Mutating underlying component state reflects immediately in subsequent property access."""
        kernel = Kernel(tmp_path)
        hp_getter_uuid = "55556666777788889999aaaabbbbcccc"

        script_code = f'''
@export("{hp_getter_uuid}")
def calc_hp_ratio(entity):
    return entity.Health["current"] / entity.Health["max"]
'''
        s_rid = kernel.create_script_resource(name="RatioScript", code=script_code)
        assert not isinstance(s_rid, Error)

        e_rid = kernel.create_entity(
            name="Monster",
            components={
                "Health": {"current": 100.0, "max": 200.0},
                "Property:HpRatio": {
                    "name": "HpRatio",
                    "getter": hp_getter_uuid,
                },
            },
        )
        assert not isinstance(e_rid, Error)

        entity = kernel.get_entity_proxy(e_rid)
        assert entity.HpRatio == 0.5

        # Mutate underlying component
        entity.Health["current"] = 50.0
        assert entity.HpRatio == 0.25

        entity.Health["current"] = 200.0
        assert entity.HpRatio == 1.0

    def test_derived_geometry_area_computed_property(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        area_getter_uuid = "6666777788889999aaaabbbbccccdddd"

        script_code = f'''
@export("{area_getter_uuid}")
def compute_area(entity):
    dims = entity.Dimensions
    return dims["width"] * dims["height"]
'''
        s_rid = kernel.create_script_resource(name="GeometryScript", code=script_code)
        assert not isinstance(s_rid, Error)

        e_rid = kernel.create_entity(
            name="Box",
            components={
                "Dimensions": {"width": 10.0, "height": 20.0},
                "Property:Area": {
                    "getter": area_getter_uuid,
                },
            },
        )
        assert not isinstance(e_rid, Error)

        entity = kernel.get_entity_proxy(e_rid)
        assert entity.Area == 200.0
        assert entity["Area"] == 200.0

        entity.Dimensions["width"] = 5.0
        assert entity.Area == 100.0

    def test_property_component_naming_variants(self, tmp_path: Path) -> None:
        """Verify Property component formats: Property:<Name>, Property standalone dict, case-insensitive."""
        kernel = Kernel(tmp_path)
        val_uuid = "777788889999aaaabbbbccccddddeeee"

        script_code = f'''
@export("{val_uuid}")
def get_val(entity):
    return entity.Data["num"] * 2
'''
        s_rid = kernel.create_script_resource(name="ValScript", code=script_code)
        assert not isinstance(s_rid, Error)

        # Variant 1: Property standalone dict with "name" field
        e1 = kernel.create_entity(
            name="E1",
            components={
                "Data": {"num": 5},
                "Property": {
                    "name": "DoubleVal",
                    "getter": val_uuid,
                },
            },
        )
        p1 = kernel.get_entity_proxy(e1)
        assert p1.DoubleVal == 10
        assert p1.doubleval == 10
        assert p1["DoubleVal"] == 10

        # Variant 2: Property:<Name> shorthand deriving name from key
        e2 = kernel.create_entity(
            name="E2",
            components={
                "Data": {"num": 7},
                "Property:MultiProp": {
                    "getter": val_uuid,
                },
            },
        )
        assert not isinstance(e2, Error)
        p2 = kernel.get_entity_proxy(e2)
        assert p2.MultiProp == 14
        assert p2["MultiProp"] == 14
        assert p2.multiprop == 14


# =============================================================================
# 3. Proxy / Converter Property (Getter & Setter)
# =============================================================================

class TestProxyConverterProperties:
    """Verify two-way converter properties with getters, setters, and kernel dirty tracking."""

    def test_getter_and_setter_converter_property(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        get_meters_uuid = "88889999aaaabbbbccccddddeeee0000"
        set_meters_uuid = "9999aaaabbbbccccddddeeee00001111"

        script_code = f'''
@export("{get_meters_uuid}")
def get_meters(entity):
    return entity.Spatial["cm"] / 100.0

@export("{set_meters_uuid}")
def set_meters(entity, meters):
    entity.Spatial["cm"] = float(meters) * 100.0
'''
        s_rid = kernel.create_script_resource(name="UnitConverterScript", code=script_code)
        assert not isinstance(s_rid, Error)

        e_rid = kernel.create_entity(
            name="TrackedObject",
            components={
                "Spatial": {"cm": 500.0},
                "Property:DistanceMeters": {
                    "name": "DistanceMeters",
                    "getter": get_meters_uuid,
                    "setter": set_meters_uuid,
                    "presentation": "text",
                },
            },
        )
        assert not isinstance(e_rid, Error)

        entity = kernel.get_entity_proxy(e_rid)
        assert entity.DistanceMeters == 5.0
        assert entity.Spatial["cm"] == 500.0

        # Invoke setter
        entity.DistanceMeters = 2.5
        assert entity.Spatial["cm"] == 250.0
        assert entity.DistanceMeters == 2.5

    def test_setter_marks_entity_dirty(self, tmp_path: Path) -> None:
        """Invoking property setter mutates underlying state and marks the entity dirty."""
        kernel = Kernel(tmp_path)
        get_uuid = "aaaabbbbccccddddeeee000011112222"
        set_uuid = "bbbbccccddddeeee0000111122223333"

        script_code = f'''
@export("{get_uuid}")
def get_temp_c(entity):
    return entity.Weather["kelvin"] - 273.15

@export("{set_uuid}")
def set_temp_c(entity, celsius):
    entity.Weather["kelvin"] = float(celsius) + 273.15
'''
        s_rid = kernel.create_script_resource(name="WeatherScript", code=script_code)
        assert not isinstance(s_rid, Error)

        e_rid = kernel.create_entity(
            name="Thermometer",
            components={
                "Weather": {"kelvin": 300.0},
                "Property:TempC": {
                    "getter": get_uuid,
                    "setter": set_uuid,
                },
            },
        )
        assert not isinstance(e_rid, Error)

        # Clear dirty resources by saving
        assert kernel.save_dirty_resources() is None
        assert kernel.is_dirty(e_rid) is False

        # Invoking setter marks entity dirty
        entity = kernel.get_entity_proxy(e_rid)
        entity.TempC = 25.0

        assert entity.Weather["kelvin"] == 298.15
        assert kernel.is_dirty(e_rid) is True


# =============================================================================
# 4. Read-Only Property Enforcement
# =============================================================================

class TestReadOnlyPropertyEnforcement:
    """Verify read-only properties reject write and delete operations cleanly."""

    def test_read_only_property_rejects_setter_assignment(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        ro_uuid = "ccccddddeeee00001111222233334444"

        script_code = f'''
@export("{ro_uuid}")
def get_constant_val(entity):
    return 42
'''
        s_rid = kernel.create_script_resource(name="ConstantScript", code=script_code)
        assert not isinstance(s_rid, Error)

        # Property without setter field
        e1 = kernel.create_entity(
            name="E1",
            components={
                "Property:ReadOnlyProp": {
                    "name": "ReadOnlyProp",
                    "getter": ro_uuid,
                },
            },
        )
        p1 = kernel.get_entity_proxy(e1)
        assert p1.ReadOnlyProp == 42

        with pytest.raises(AttributeError) as exc_info:
            p1.ReadOnlyProp = 999
        assert "read-only" in str(exc_info.value).lower()
        assert "ReadOnlyProp" in str(exc_info.value)

        # Property with explicit empty string setter
        e2 = kernel.create_entity(
            name="E2",
            components={
                "Property:EmptySetterProp": {
                    "name": "EmptySetterProp",
                    "getter": ro_uuid,
                    "setter": "",
                },
            },
        )
        p2 = kernel.get_entity_proxy(e2)
        assert p2.EmptySetterProp == 42

        with pytest.raises(AttributeError) as exc_info2:
            p2.EmptySetterProp = 888
        assert "read-only" in str(exc_info2.value).lower()

    def test_read_only_property_rejects_delattr(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        ro_uuid = "ddddeeee000011112222333344445555"

        script_code = f'''
@export("{ro_uuid}")
def get_val(entity):
    return 10
'''
        s_rid = kernel.create_script_resource(name="ROScript", code=script_code)
        assert not isinstance(s_rid, Error)

        e_rid = kernel.create_entity(
            name="E",
            components={
                "Property:LockedProp": {
                    "getter": ro_uuid,
                },
            },
        )
        proxy = kernel.get_entity_proxy(e_rid)
        with pytest.raises(AttributeError) as exc_info:
            del proxy.LockedProp
        assert "can't delete attribute" in str(exc_info.value).lower()


# =============================================================================
# 5. Cycle Detection
# =============================================================================

class TestCycleDetection:
    """Verify circular property evaluation detection and clean stack cleanup."""

    def test_mutual_property_cycle_detected(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        get_a_uuid = "eeee0000111122223333444455556666"
        get_b_uuid = "00001111222233334444555566667777"

        script_code = f'''
@export("{get_a_uuid}")
def get_a(entity):
    return entity.PropB + 1

@export("{get_b_uuid}")
def get_b(entity):
    return entity.PropA + 1
'''
        s_rid = kernel.create_script_resource(name="CycleScript", code=script_code)
        assert not isinstance(s_rid, Error)

        e_rid = kernel.create_entity(
            name="CyclicEntity",
            components={
                "Property:PropA": {"getter": get_a_uuid},
                "Property:PropB": {"getter": get_b_uuid},
            },
        )
        assert not isinstance(e_rid, Error)

        entity = kernel.get_entity_proxy(e_rid)

        with pytest.raises(RuntimeError) as exc_info:
            _ = entity.PropA
        assert "Circular property evaluation detected" in str(exc_info.value)

    def test_self_referencing_property_cycle_detected(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        self_uuid = "11110000111122223333444455556666"

        script_code = f'''
@export("{self_uuid}")
def get_self_ref(entity):
    return entity.SelfRef * 2
'''
        s_rid = kernel.create_script_resource(name="SelfCycleScript", code=script_code)
        assert not isinstance(s_rid, Error)

        e_rid = kernel.create_entity(
            name="SelfEntity",
            components={
                "Property:SelfRef": {"getter": self_uuid},
            },
        )
        entity = kernel.get_entity_proxy(e_rid)

        with pytest.raises(RuntimeError) as exc_info:
            _ = entity.SelfRef
        assert "Circular property evaluation detected" in str(exc_info.value)

    def test_cycle_error_cleans_up_call_stack(self, tmp_path: Path) -> None:
        """Verify that evaluation stack is discarded in finally block so healthy reads continue working."""
        kernel = Kernel(tmp_path)
        get_a_uuid = "22220000111122223333444455556666"
        get_b_uuid = "33330000111122223333444455556666"
        healthy_uuid = "44440000111122223333444455556666"

        script_code = f'''
@export("{get_a_uuid}")
def get_a(entity):
    return entity.PropB + 1

@export("{get_b_uuid}")
def get_b(entity):
    return entity.PropA + 1

@export("{healthy_uuid}")
def get_healthy(entity):
    return 999
'''
        s_rid = kernel.create_script_resource(name="CleanupScript", code=script_code)
        assert not isinstance(s_rid, Error)

        e_rid = kernel.create_entity(
            name="CleanupEntity",
            components={
                "Property:PropA": {"getter": get_a_uuid},
                "Property:PropB": {"getter": get_b_uuid},
                "Property:Healthy": {"getter": healthy_uuid},
            },
        )
        entity = kernel.get_entity_proxy(e_rid)

        # Trigger cycle error
        with pytest.raises(RuntimeError):
            _ = entity.PropA

        # Evaluation tracking set must be empty for this entity
        assert (e_rid, "PropA") not in entity._evaluating_properties
        assert (e_rid, "PropB") not in entity._evaluating_properties

        # Subsequent healthy property reads evaluate normally
        assert entity.Healthy == 999


# =============================================================================
# 6. Diagnostics & Missing Reference Resilience
# =============================================================================

class TestDiagnosticsAndMissingReferences:
    """Verify resilience and structured diagnostics when exports or targets are missing."""

    def test_missing_getter_export_raises_attribute_error_with_diagnostics(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        missing_uuid = "ffff0000111122223333444455556666"

        e_rid = kernel.create_entity(
            name="BrokenEntity",
            components={
                "Property:BrokenProp": {"getter": missing_uuid},
            },
        )
        entity = kernel.get_entity_proxy(e_rid)

        with pytest.raises(AttributeError) as exc_info:
            _ = entity.BrokenProp
        assert "getter error" in str(exc_info.value).lower()
        assert missing_uuid in str(exc_info.value)

    def test_missing_setter_export_raises_attribute_error_with_diagnostics(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        valid_getter_uuid = "aaaa0000111122223333444455556666"
        missing_setter_uuid = "ffff0000111122223333444455557777"

        script_code = f'''
@export("{valid_getter_uuid}")
def get_val(entity):
    return 10
'''
        s_rid = kernel.create_script_resource(name="ValidGetterScript", code=script_code)
        assert not isinstance(s_rid, Error)

        e_rid = kernel.create_entity(
            name="EntityWithBrokenSetter",
            components={
                "Property:Prop": {
                    "getter": valid_getter_uuid,
                    "setter": missing_setter_uuid,
                },
            },
        )
        entity = kernel.get_entity_proxy(e_rid)
        assert entity.Prop == 10

        with pytest.raises(AttributeError) as exc_info:
            entity.Prop = 20
        assert "setter error" in str(exc_info.value).lower()
        assert missing_setter_uuid in str(exc_info.value)

    def test_getitem_and_get_diagnostics_on_broken_property(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        missing_uuid = "ffff0000111122223333444455558888"

        e_rid = kernel.create_entity(
            name="BrokenE",
            components={
                "Property:BrokenProp": {"getter": missing_uuid},
            },
        )
        entity = kernel.get_entity_proxy(e_rid)

        with pytest.raises(KeyError) as exc_info:
            _ = entity["BrokenProp"]
        assert "getter error" in str(exc_info.value).lower()

        # get() with default falls back gracefully
        assert entity.get("BrokenProp", default=-1) == -1

    def test_property_access_on_dead_entity_proxy(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        uuid_val = "bbbb0000111122223333444455556666"
        script_code = f'''
@export("{uuid_val}")
def get_val(entity):
    return 1
'''
        kernel.create_script_resource(name="S", code=script_code)
        e_rid = kernel.create_entity(
            name="DyingEntity",
            components={
                "Property:P": {"getter": uuid_val},
            },
        )
        proxy = kernel.get_entity_proxy(e_rid)
        assert proxy.is_alive
        assert proxy.P == 1

        # Delete entity
        assert kernel.delete_resource(e_rid) is True
        assert not proxy.is_alive

        with pytest.raises(AttributeError):
            _ = proxy.P
        with pytest.raises(KeyError):
            _ = proxy["P"]
        assert proxy.get("P", default="fallback") == "fallback"
        assert proxy.has("P") is False


# =============================================================================
# 7. Property Component Schema Validation & Integrity
# =============================================================================

class TestPropertySchemaValidation:
    """Verify UI schema validation for Property components in ValidateUI and Validate."""

    def test_default_schema_template_passes(self) -> None:
        template = UI_SCHEMAS.get("Property")
        assert template is not None
        assert ValidateUI.validate_ui_component("Property", template) is None
        assert Validate.ui_component("Property", template) is None

        # Empty template dict
        empty = {"name": "", "getter": ""}
        assert ValidateUI.validate_ui_component("Property", empty) is None

    def test_valid_property_data_passes(self) -> None:
        valid_32 = {
            "name": "HealthPercent",
            "getter": "a" * 32,
            "setter": "b" * 32,
            "presentation": "slider",
            "presentation_args": {"min": 0.0, "max": 100.0},
        }
        assert ValidateUI.validate_ui_component("Property", valid_32) is None
        assert Validate.ui_component("Property", valid_32) is None

        valid_64 = {
            "name": "BigHashProp",
            "getter": "c" * 64,
            "setter": "d" * 64,
            "presentation": "text",
            "presentation_args": {},
        }
        assert ValidateUI.validate_ui_component("Property", valid_64) is None

    def test_property_colon_shorthand_infers_name(self) -> None:
        shorthand = {
            "getter": "1" * 32,
            "setter": "",
        }
        assert ValidateUI.validate_ui_component("Property:Speed", shorthand) is None
        assert Validate.ui_component("Property:Speed", shorthand) is None

    def test_rejects_empty_or_non_string_name(self) -> None:
        # Empty string name when getter is specified
        bad_name = {"name": "", "getter": "a" * 32}
        err1 = ValidateUI.validate_ui_component("Property", bad_name)
        assert isinstance(err1, Error)
        assert err1.code == InvalidResourceDataError
        assert "name" in err1.description

        # Non-string name
        bad_type = {"name": 12345, "getter": "a" * 32}
        err2 = ValidateUI.validate_ui_component("Property", bad_type)
        assert isinstance(err2, Error)
        assert err2.code == InvalidResourceDataError

    def test_rejects_invalid_getter_uuid(self) -> None:
        # Non-string getter
        err1 = ValidateUI.validate_ui_component("Property", {"name": "P", "getter": 12345})
        assert isinstance(err1, Error)
        assert err1.code == InvalidResourceDataError
        assert "getter" in err1.description

        # Invalid length (e.g. 16 chars)
        err2 = ValidateUI.validate_ui_component("Property", {"name": "P", "getter": "a" * 16})
        assert isinstance(err2, Error)
        assert err2.code == InvalidResourceDataError
        assert "length" in err2.description.lower()

        # Non-hex characters
        err3 = ValidateUI.validate_ui_component("Property", {"name": "P", "getter": "g" * 32})
        assert isinstance(err3, Error)
        assert err3.code == InvalidResourceDataError
        assert "hex" in err3.description.lower()

    def test_rejects_invalid_setter_uuid(self) -> None:
        # Invalid setter hex
        err1 = ValidateUI.validate_ui_component(
            "Property",
            {"name": "P", "getter": "a" * 32, "setter": "invalid_setter_hex!"},
        )
        assert isinstance(err1, Error)
        assert err1.code == InvalidResourceDataError

        # Invalid setter length
        err2 = ValidateUI.validate_ui_component(
            "Property",
            {"name": "P", "getter": "a" * 32, "setter": "a" * 20},
        )
        assert isinstance(err2, Error)
        assert err2.code == InvalidResourceDataError

    def test_rejects_non_string_presentation(self) -> None:
        err = ValidateUI.validate_ui_component(
            "Property",
            {"name": "P", "getter": "a" * 32, "presentation": 42},
        )
        assert isinstance(err, Error)
        assert err.code == InvalidResourceDataError
        assert "presentation" in err.description.lower()

    def test_rejects_non_mapping_presentation_args(self) -> None:
        err = ValidateUI.validate_ui_component(
            "Property",
            {"name": "P", "getter": "a" * 32, "presentation_args": [1, 2, 3]},
        )
        assert isinstance(err, Error)
        assert err.code == InvalidResourceDataError
        assert "presentation_args" in err.description.lower()


# =============================================================================
# 8. Persistence & Serialization Roundtrip
# =============================================================================

class TestPersistenceAndSerializationRoundtrip:
    """Verify pure-UUID Property components roundtrip cleanly through project disk persistence."""

    def test_property_component_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        k1 = Kernel(tmp_path)
        hp_getter_uuid = "10102020303040405050606070708080"
        hp_setter_uuid = "20203030404050506060707080809090"

        script_code = f'''
@export("{hp_getter_uuid}")
def get_health_pct(entity):
    return (entity.Health["current"] / entity.Health["max"]) * 100.0

@export("{hp_setter_uuid}")
def set_health_pct(entity, pct):
    entity.Health["current"] = (float(pct) / 100.0) * entity.Health["max"]
'''
        s_rid = k1.create_script_resource(name="HealthLogic", code=script_code)
        assert not isinstance(s_rid, Error)

        e_rid = k1.create_entity(
            name="HeroPlayer",
            components={
                "Health": {"current": 80.0, "max": 100.0},
                "Property:HealthPercent": {
                    "name": "HealthPercent",
                    "getter": hp_getter_uuid,
                    "setter": hp_setter_uuid,
                    "presentation": "slider",
                    "presentation_args": {"min": 0.0, "max": 100.0},
                },
            },
        )
        assert not isinstance(e_rid, Error)
        assert k1.attach_script(e_rid, s_rid) is None

        # Save dirty resources and project manifest
        assert k1.save_dirty_resources() is None
        assert k1.save_project() is None

        # Check raw JSON file on disk to verify pure UUID persistence
        e_sid = k1.get_storage_id(e_rid)
        assert not isinstance(e_sid, Error)
        e_json_path = tmp_path / f"{e_sid.hex()}.json"
        assert e_json_path.exists()
        raw_data = json.loads(e_json_path.read_text(encoding="utf-8"))

        comp_data = raw_data["data"]["components"]["Property:HealthPercent"]
        assert comp_data["getter"] == hp_getter_uuid
        assert comp_data["setter"] == hp_setter_uuid
        assert comp_data["name"] == "HealthPercent"

        # Load in a fresh Kernel instance
        k2 = Kernel(tmp_path)
        load_res = k2.load_project()
        assert not isinstance(load_res, Error)

        # Locate reloaded entity by name
        reloaded_e_rid = None
        for rid in k2.resources:
            if k2.is_entity(rid) and k2.resources[rid].get("name") == "HeroPlayer":
                reloaded_e_rid = rid
                break
        assert reloaded_e_rid is not None

        proxy2 = k2.get_entity_proxy(reloaded_e_rid)
        assert proxy2 is not None

        # Evaluates getter seamlessly from reloaded state
        assert proxy2.HealthPercent == 80.0

        # Invokes setter seamlessly on reloaded entity
        proxy2.HealthPercent = 40.0
        assert proxy2.Health["current"] == 40.0
        assert proxy2.HealthPercent == 40.0

    def test_transaction_rollback_preserves_exports(self, tmp_path: Path) -> None:
        """Snapshot restoration in Kernel storage preserves the function_exports map."""
        kernel = Kernel(tmp_path)
        uuid_hex = "30304040505060607070808090900000"
        script_code = f'''
@export("{uuid_hex}")
def calculate_something(entity):
    return 123
'''
        s_rid = kernel.create_script_resource(name="TestScript", code=script_code)
        assert not isinstance(s_rid, Error)

        # Force resolution to populate function_exports
        assert not isinstance(kernel.resolve_function_export(uuid_hex), Error)
        assert uuid_hex in kernel.function_exports

        # Take snapshot and simulate transactional rollback
        snap = kernel._snapshot_loaded_state()
        assert "function_exports" in snap
        assert uuid_hex in snap["function_exports"]

        # Mutate kernel function_exports
        kernel.function_exports.clear()
        assert len(kernel.function_exports) == 0

        # Restore
        kernel._restore_loaded_state(snap)
        assert uuid_hex in kernel.function_exports


# =============================================================================
# 9. Editor Pill & Presentation Projection Integration
# =============================================================================

class TestEditorPillAndPresentationIntegration:
    """Verify integration with editor PillData, render_function_export_pill, and InspectorPanel."""

    def test_parse_reference_pill_for_pure_uuid_export(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        uuid_hex = "40405050606070708080909000001010"
        script_code = f'''
@export("{uuid_hex}")
def _fn_bonus(entity): # Player Bonus Calc
    return 50
'''
        s_rid = kernel.create_script_resource(name="BonusScript", code=script_code)
        assert not isinstance(s_rid, Error)

        # Parse reference pill with pure 32-hex UUID
        pill = parse_reference_pill(uuid_hex, kernel)
        assert pill is not None
        assert isinstance(pill, PillData)
        assert pill.res_type == Script
        assert pill.res_name == "BonusScript"
        assert pill.fn_symbol == "_fn_bonus"
        assert pill.fn_display_name == "Player Bonus Calc"
        assert pill.display_label == "[BonusScript :: Player Bonus Calc]"

    def test_render_function_export_pill_in_dpg(self, tmp_path: Path, dpg_context) -> None:
        kernel = Kernel(tmp_path)
        uuid_hex = "50506060707080809090000010102020"
        script_code = f'''
@export("{uuid_hex}")
def trigger_action(entity): # Trigger Super Action
    pass
'''
        s_rid = kernel.create_script_resource(name="ActionModule", code=script_code)
        assert not isinstance(s_rid, Error)

        with dpg.window(label="Test Window"):
            # Rendering valid export returns True
            rendered = render_function_export_pill(uuid_hex, kernel)
            assert rendered is True

            # Rendering non-existent export returns False
            rendered_invalid = render_function_export_pill("ffff0000111122223333444455556666", kernel)
            assert rendered_invalid is False

    def test_inspector_panel_renders_property_card_slider(self, tmp_path: Path, dpg_context) -> None:
        """Verify InspectorPanel renders a slider widget for a property with presentation='slider'."""
        kernel = Kernel(tmp_path)
        getter_uuid = "60607070808090900000101020203030"
        setter_uuid = "70708080909000001010202030304040"

        script_code = f'''
@export("{getter_uuid}")
def get_val(entity):
    return entity.Config["level"]

@export("{setter_uuid}")
def set_val(entity, v):
    entity.Config["level"] = float(v)
'''
        s_rid = kernel.create_script_resource(name="ConfigScript", code=script_code)
        assert not isinstance(s_rid, Error)

        e_rid = kernel.create_entity(
            name="SliderEntity",
            components={
                "Config": {"level": 50.0},
                "Property:Level": {
                    "name": "Level",
                    "getter": getter_uuid,
                    "setter": setter_uuid,
                    "presentation": "slider",
                    "presentation_args": {"min": 0.0, "max": 100.0},
                },
            },
        )
        assert not isinstance(e_rid, Error)

        session = EditorSession(kernel)
        session.select_entity(e_rid)

        inspector = InspectorPanel(session, tag="test_prop_slider_insp")
        inspector.build()

        # Verify slider float was added in DPG hierarchy
        sliders = find_items_by_type(inspector.content_tag, "mvAppItemType::mvSliderFloat")
        assert len(sliders) >= 1
        _, label = sliders[0]
        assert label == "Level"

        # Verify binding pill buttons rendered
        buttons = find_buttons(inspector.content_tag)
        assert any("ConfigScript" in lbl for _, lbl in buttons)

    def test_inspector_panel_renders_property_card_text_and_readonly(self, tmp_path: Path, dpg_context) -> None:
        """Verify InspectorPanel renders read-only text when no setter is defined."""
        kernel = Kernel(tmp_path)
        getter_uuid = "80809090000010102020303040405050"

        script_code = f'''
@export("{getter_uuid}")
def get_ro_val(entity):
    return "FixedText"
'''
        s_rid = kernel.create_script_resource(name="ROScript", code=script_code)
        assert not isinstance(s_rid, Error)

        e_rid = kernel.create_entity(
            name="ROEntity",
            components={
                "Property:Title": {
                    "name": "Title",
                    "getter": getter_uuid,
                    "presentation": "text",
                },
            },
        )
        assert not isinstance(e_rid, Error)

        session = EditorSession(kernel)
        session.select_entity(e_rid)

        inspector = InspectorPanel(session, tag="test_prop_ro_insp")
        inspector.build()

        # Verify [Read-Only] badge rendered
        texts = find_items_by_type(inspector.content_tag, "mvAppItemType::mvText")
        text_labels = [lbl for _, lbl in texts]
        assert any("Read-Only" in lbl for lbl in text_labels)
        assert any("FixedText" in lbl for lbl in text_labels)

    def test_inspector_on_property_value_changed_callback(self, tmp_path: Path, dpg_context) -> None:
        """Verify InspectorPanel._on_property_value_changed invokes entity setter."""
        kernel = Kernel(tmp_path)
        get_uuid = "90900000101020203030404050506060"
        set_uuid = "00001010202030304040505060607070"

        script_code = f'''
@export("{get_uuid}")
def get_gain(entity):
    return entity.Audio["volume"]

@export("{set_uuid}")
def set_gain(entity, val):
    entity.Audio["volume"] = float(val)
'''
        s_rid = kernel.create_script_resource(name="AudioScript", code=script_code)
        assert not isinstance(s_rid, Error)

        e_rid = kernel.create_entity(
            name="Speaker",
            components={
                "Audio": {"volume": 0.5},
                "Property:Gain": {
                    "name": "Gain",
                    "getter": get_uuid,
                    "setter": set_uuid,
                },
            },
        )
        assert not isinstance(e_rid, Error)

        session = EditorSession(kernel)
        inspector = InspectorPanel(session, tag="test_insp_callback")

        # Fire property change callback
        inspector._on_property_value_changed(None, 0.85, (e_rid, "Gain", "float"))

        proxy = kernel.get_entity_proxy(e_rid)
        assert proxy.Gain == 0.85
        assert proxy.Audio["volume"] == 0.85

    def test_ui_bridge_panel_ignores_property_components(self, tmp_path: Path, dpg_context) -> None:
        """UIBridgePanel treats Property as non-visual and avoids mounting preview containers."""
        kernel = Kernel(tmp_path)
        uuid_hex = "12123434565678789090121234345656"
        script_code = f'''
@export("{uuid_hex}")
def get_data(entity):
    return 10
'''
        kernel.create_script_resource(name="S", code=script_code)
        e_rid = kernel.create_entity(
            name="NonVisualEntity",
            components={
                "Property:Val": {"getter": uuid_hex},
            },
        )
        assert not isinstance(e_rid, Error)

        session = EditorSession(kernel)
        bridge = UIBridgePanel(session, tag="test_ui_bridge_non_visual")
        assert bridge._is_non_visual(e_rid) is True


# =============================================================================
# 10. Planned Tests for Unimplemented Features & Hardening
# =============================================================================

class TestPlannedPropertyFeatures:
    """Planned tests for future capabilities and hardening edge cases."""

    @pytest.mark.skip(
        reason="Planned test: Preprocessor or editor automatic call-site refactoring when an export UUID is renamed"
    )
    def test_planned_automatic_call_site_refactoring_on_export_uuid_rename(self) -> None:
        """Future: Renaming an export UUID automatically updates Property components and script call-sites."""
        pass

    def test_planned_hot_reload_rollback_preserves_exports(self, tmp_path: Path) -> None:
        """If updated script source has a syntax error, previous export definitions remain active."""
        kernel = Kernel(tmp_path)
        uuid_hex = "ababcdcdababcdcdababcdcdababcdcd"
        valid_code = f'''
@export("{uuid_hex}")
def valid_function(entity):
    return 12345
'''
        s_rid = kernel.create_script_resource(name="SafeScript", code=valid_code)
        assert not isinstance(s_rid, Error)

        # Initial export works
        res1 = kernel.resolve_function_export(uuid_hex)
        assert not isinstance(res1, Error)
        assert res1[0](None) == 12345

        # Introduce syntax error
        broken_code = "def syntax_error_func(:\n    pass\n"
        err = kernel.update_script_source(s_rid, broken_code)
        assert isinstance(err, Error)
        assert err.code == InvalidResourceDataError

        # Previous working export is preserved and functional
        res2 = kernel.resolve_function_export(uuid_hex)
        assert not isinstance(res2, Error)
        assert res2[0](None) == 12345

    def test_planned_stale_handle_safety_when_exported_script_destroyed(self, tmp_path: Path) -> None:
        """Deleting a script resource safely invalidates proxies without crashing callers."""
        kernel = Kernel(tmp_path)
        uuid_hex = "efef1212efef1212efef1212efef1212"
        code = f'''
@export("{uuid_hex}")
def calc(entity):
    return 77
'''
        s_rid = kernel.create_script_resource(name="TempScript", code=code)
        assert not isinstance(s_rid, Error)

        # Resolves initially
        assert not isinstance(kernel.resolve_function_export(uuid_hex), Error)

        # Delete script resource
        assert kernel.delete_resource(s_rid) is True
        assert not kernel.is_valid_runtime_id(s_rid)

        # Clear export mapping to reflect deleted script
        kernel.function_exports.pop(uuid_hex, None)

        # Attempting to resolve deleted export returns BrokenReferenceError
        res = kernel.resolve_function_export(uuid_hex)
        assert isinstance(res, Error)
        assert res.code == BrokenReferenceError

    def test_planned_failed_load_cleanup_transactional_rollback(self, tmp_path: Path) -> None:
        """If a script dependency fails disk validation during load, partially loaded state is cleaned up."""
        k1 = Kernel(tmp_path)
        uuid_hex = "34345656787890901212343456567878"
        script_code = f'''
@export("{uuid_hex}")
def compute(entity):
    return 42
'''
        s_rid = k1.create_script_resource(name="CompScript", code=script_code)
        assert not isinstance(s_rid, Error)

        e_rid = k1.create_entity(
            name="RootEntity",
            components={
                "Property:Comp": {"getter": uuid_hex},
            },
        )
        assert not isinstance(e_rid, Error)
        assert k1.attach_script(e_rid, s_rid) is None

        s_sid = k1.get_storage_id(s_rid)
        e_sid = k1.get_storage_id(e_rid)
        assert not isinstance(s_sid, Error)
        assert not isinstance(e_sid, Error)

        assert k1.save_dirty_resources() is None
        assert k1.save_project() is None

        # Corrupt the script JSON file on disk
        script_file = tmp_path / f"{s_sid.hex()}.json"
        script_file.write_text("{broken json payload", encoding="utf-8")

        k2 = Kernel(tmp_path)
        res = k2.load_resource(e_sid, is_fatal=True)
        assert isinstance(res, Error)

        # Partially loaded resources must be cleanly rolled back
        assert k2.resources == {}
        assert e_sid not in k2.resource_runtime_ids
