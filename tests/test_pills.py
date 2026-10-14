"""Comprehensive verification tests for Visual Pill Tokens in Inspector & Tooling (editor/).

Derives tests from observable user requirements and editor contracts:
1. Reference String Parsing & Pill Data Construction (parse_reference_pill):
   - Durable function references: <|1|<sid>|>._fn_<id>
   - Display name references: <|1|<sid>|>.<display_name>
   - Entity references: <|0|<sid>|>
   - Non-reference strings, invalid syntax, odd hex lengths
   - Graceful fallback when target script is not in memory
   - Uppercase/lowercase hex normalization
2. Function Pill Scanning (get_available_function_pills):
   - Accurately enumerates all _fn_* functions across all loaded scripts
   - Empty list when no scripts or no _fn_* functions exist
   - Ignores non-script resources
3. Display Name Renaming (rename_script_function_display_name):
   - Refactors trailing comment (# <human_name>) without modifying _fn_<id> symbol
   - Inline code string and external source_path file handling
   - AST validation and symbol ID preservation
   - Callers using _fn_<id> continue executing uninterrupted without breaking
   - Negative tests: invalid name, invalid hex, missing script, missing symbol, syntax error
4. Inspector Panel & Storage Panel UI Integration:
   - Headless DPG context verification
   - Visual pill badge rendered for reference strings
   - Pill details and rename modal interaction
   - Function Picker ("⚡ Pick") updates field value and triggers component mutation
   - StoragePanel exposes "⚡ Functions" button and modal for Script resources
5. Planned Tests for Unimplemented Features:
   - Future UID-based function rename call-site refactoring
   - Hot reload rollback on syntax error
   - Stale handle safety when referenced script is destroyed
   - Transactional rollback on failed dependency graph loading
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
import dearpygui.dearpygui as dpg
import pytest

from editor import (
    EditorApp,
    PillData,
    get_available_function_pills,
    get_pill_theme,
    parse_reference_pill,
    rename_script_function_display_name,
)
from LBE import Error, Kernel, Script, extract_script_symbols
from LBE.types import InvalidResourceDataError, RuntimeIDNotFoundOnMemoryError


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
# 1. Public API & PillData Construction
# =============================================================================

class TestPillsPublicApi:
    """Verify editor package exports and PillData presentation models."""

    def test_editor_package_exports_pill_symbols(self) -> None:
        import editor
        assert hasattr(editor, "PillData")
        assert hasattr(editor, "parse_reference_pill")
        assert hasattr(editor, "get_available_function_pills")
        assert hasattr(editor, "rename_script_function_display_name")
        assert hasattr(editor, "get_pill_theme")

    def test_pill_data_display_label_formatting(self) -> None:
        # Case 1: Script with human display name
        p1 = PillData(
            res_type=Script,
            storage_id_hex="a" * 32,
            res_name="CombatScript",
            fn_symbol="_fn_attack",
            fn_display_name="Execute Attack",
            raw_ref="<|1|" + "a" * 32 + "|>._fn_attack",
        )
        assert p1.display_label == "[CombatScript :: Execute Attack]"

        # Case 2: Script with only symbol ID (no human comment)
        p2 = PillData(
            res_type=Script,
            storage_id_hex="b" * 32,
            res_name="LogicScript",
            fn_symbol="_fn_calc",
            fn_display_name=None,
            raw_ref="<|1|" + "b" * 32 + "|>._fn_calc",
        )
        assert p2.display_label == "[LogicScript :: _fn_calc]"

        # Case 3: Script with neither display name nor symbol ID (fallback to storage_id prefix)
        p3 = PillData(
            res_type=Script,
            storage_id_hex="1234567890abcdef1234567890abcdef",
            res_name="RawScript",
            fn_symbol=None,
            fn_display_name=None,
            raw_ref="<|1|1234567890abcdef1234567890abcdef|>",
        )
        assert p3.display_label == "[RawScript :: 12345678]"

        # Case 4: Resource without storage ID
        p4 = PillData(
            res_type=0,
            storage_id_hex="",
            res_name="EmptySIDEntity",
            fn_symbol=None,
            fn_display_name=None,
            raw_ref="",
        )
        assert p4.display_label == "[EmptySIDEntity]"

    def test_pill_data_display_label_entity_without_fn_symbol(self) -> None:
        # Entity reference without a function should only display entity name
        p = PillData(
            res_type=0,
            storage_id_hex="c" * 32,
            res_name="Root Entity",
            fn_symbol=None,
            fn_display_name=None,
            raw_ref="<|0|" + "c" * 32 + "|>",
        )
        assert p.display_label == "[Root Entity]"
        assert "::" not in p.display_label


# =============================================================================
# 2. Reference String Parsing (parse_reference_pill)
# =============================================================================

class TestReferenceStringParsing:
    """Verification of parse_reference_pill contract against various inputs."""

    def test_parse_durable_function_reference_loaded_script(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        code = '''
def _fn_jump(self, dt): # Player Jump
    self.transform.y += 10
'''
        s_rid = kernel.create_script_resource(name="PlayerMovement", code=code)
        assert not isinstance(s_rid, Error)
        sid_hex = kernel.get_storage_id(s_rid).hex().lower()

        ref_str = f"<|1|{sid_hex}|>._fn_jump"
        pill = parse_reference_pill(ref_str, kernel)

        assert pill is not None
        assert pill.res_type == Script
        assert pill.storage_id_hex == sid_hex
        assert pill.res_name == "PlayerMovement"
        assert pill.fn_symbol == "_fn_jump"
        assert pill.fn_display_name == "Player Jump"
        assert pill.raw_ref == ref_str
        assert pill.display_label == "[PlayerMovement :: Player Jump]"

    def test_parse_display_name_reference_loaded_script(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        code = '''
def _fn_fire(self, dt): # primary_weapon_fire
    pass
'''
        s_rid = kernel.create_script_resource(name="WeaponSystem", code=code)
        assert not isinstance(s_rid, Error)
        sid_hex = kernel.get_storage_id(s_rid).hex().lower()

        # Display name reference: <|1|<sid>|>.<display_name>
        ref_str = f"<|1|{sid_hex}|>.primary_weapon_fire"
        pill = parse_reference_pill(ref_str, kernel)

        assert pill is not None
        assert pill.res_type == Script
        assert pill.storage_id_hex == sid_hex
        assert pill.res_name == "WeaponSystem"
        assert pill.fn_symbol == "_fn_fire"
        assert pill.fn_display_name == "primary_weapon_fire"
        assert pill.display_label == "[WeaponSystem :: primary_weapon_fire]"

    def test_parse_entity_reference(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        e_rid = kernel.create_entity(name="MainCamera", components={"Transform": {"x": 0, "y": 0}})
        assert not isinstance(e_rid, Error)
        e_sid = kernel.get_storage_id(e_rid).hex().lower()

        ref_str = f"<|0|{e_sid}|>"
        pill = parse_reference_pill(ref_str, kernel)

        assert pill is not None
        assert pill.res_type == 0
        assert pill.storage_id_hex == e_sid
        assert pill.res_name == "MainCamera"
        assert pill.fn_symbol is None
        assert pill.fn_display_name is None

    def test_parse_entity_reference_display_label(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        e_rid = kernel.create_entity(name="MainCamera", components={"Transform": {"x": 0, "y": 0}})
        assert not isinstance(e_rid, Error)
        e_sid = kernel.get_storage_id(e_rid).hex().lower()

        ref_str = f"<|0|{e_sid}|>"
        pill = parse_reference_pill(ref_str, kernel)
        assert pill is not None
        assert pill.display_label == "[MainCamera]"

    def test_parse_non_reference_strings_return_none(self) -> None:
        assert parse_reference_pill("", None) is None
        assert parse_reference_pill("regular text without brackets", None) is None
        assert parse_reference_pill("12345", None) is None
        assert parse_reference_pill(None, None) is None  # type: ignore[arg-type]
        assert parse_reference_pill(42, None) is None  # type: ignore[arg-type]
        assert parse_reference_pill({}, None) is None  # type: ignore[arg-type]

    def test_parse_invalid_syntax_returns_none(self) -> None:
        assert parse_reference_pill("<||>", None) is None
        assert parse_reference_pill("<|1||>", None) is None
        assert parse_reference_pill("<|not_a_type|" + "a" * 32 + "|>", None) is None
        assert parse_reference_pill("<|1|" + "a" * 31 + "|>", None) is None  # shorter than 32 hex chars
        assert parse_reference_pill("<|1|" + "a" * 65 + "|>", None) is None  # longer than 64 hex chars
        assert parse_reference_pill("<|1|" + "g" * 32 + "|>", None) is None  # invalid non-hex characters
        assert parse_reference_pill("<|1|" + "a" * 32 + "|>.123bad", None) is None  # fn name starts with digit
        assert parse_reference_pill("<|1|" + "a" * 32 + "|>.fn.extra", None) is None  # multiple dots

    def test_parse_rejects_odd_hex_length(self) -> None:
        odd_hex_ref = "<|1|" + "a" * 33 + "|>"
        # 33 hex characters is an odd length; hex bytes require an even length
        assert parse_reference_pill(odd_hex_ref, None) is None

    def test_parse_graceful_fallback_when_target_script_not_in_memory(self) -> None:
        unloaded_sid = "deadbeef" * 4  # 32 hex chars

        # 1. Durable reference to unloaded script
        p1 = parse_reference_pill(f"<|1|{unloaded_sid}|>._fn_action", None)
        assert p1 is not None
        assert p1.res_type == 1
        assert p1.storage_id_hex == unloaded_sid
        assert p1.res_name == f"Script_{unloaded_sid[:8]}"
        assert p1.fn_symbol == "_fn_action"
        assert p1.fn_display_name == "_fn_action"

        # 2. Display name reference to unloaded script
        p2 = parse_reference_pill(f"<|1|{unloaded_sid}|>.custom_handler", None)
        assert p2 is not None
        assert p2.res_type == 1
        assert p2.fn_symbol is None
        assert p2.fn_display_name == "custom_handler"

        # 3. Entity reference to unloaded entity
        p3 = parse_reference_pill(f"<|0|{unloaded_sid}|>", None)
        assert p3 is not None
        assert p3.res_type == 0
        assert p3.res_name == f"Resource_{unloaded_sid[:8]}"
        assert p3.fn_symbol is None

    def test_parse_hex_casing_normalization(self) -> None:
        upper_sid = ("A1B2C3D4" * 4)
        ref = f"<|1|{upper_sid}|>._fn_test"
        pill = parse_reference_pill(ref, None)
        assert pill is not None
        assert pill.storage_id_hex == upper_sid.lower()


# =============================================================================
# 3. Function Pill Scanning (get_available_function_pills)
# =============================================================================

class TestFunctionPillScanning:
    """Verification of get_available_function_pills across kernel resources."""

    def test_scan_empty_kernel_returns_empty_list(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        assert get_available_function_pills(kernel) == []
        assert get_available_function_pills(None) == []

    def test_scan_script_without_fn_symbols_returns_empty_list(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        code = '''
def update(self, dt):
    pass

def custom_helper():
    pass
'''
        kernel.create_script_resource(name="PlainScript", code=code)
        assert get_available_function_pills(kernel) == []

    def test_scan_multiple_scripts_and_functions(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)

        code_a = '''
def _fn_strike(self, dt): # Strike Action
    pass

def _fn_dash(self, dt): # Dash Action
    pass
'''
        s_a = kernel.create_script_resource(name="CombatActions", code=code_a)
        assert not isinstance(s_a, Error)
        sid_a = kernel.get_storage_id(s_a).hex().lower()

        code_b = '''
def _fn_heal(self, dt): # Heal Spell
    pass

def _fn_raw(self, dt):
    pass
'''
        s_b = kernel.create_script_resource(name="MagicActions", code=code_b)
        assert not isinstance(s_b, Error)
        sid_b = kernel.get_storage_id(s_b).hex().lower()

        pills = get_available_function_pills(kernel)
        assert len(pills) == 4

        # Group by script
        pills_a = [p for p in pills if p.storage_id_hex == sid_a]
        pills_b = [p for p in pills if p.storage_id_hex == sid_b]

        assert len(pills_a) == 2
        assert {p.fn_symbol for p in pills_a} == {"_fn_strike", "_fn_dash"}
        assert {p.fn_display_name for p in pills_a} == {"Strike Action", "Dash Action"}

        assert len(pills_b) == 2
        assert {p.fn_symbol for p in pills_b} == {"_fn_heal", "_fn_raw"}
        # _fn_raw has no comment, defaults to _fn_raw
        assert {p.fn_display_name for p in pills_b} == {"Heal Spell", "_fn_raw"}

    def test_scan_ignores_entities_and_non_script_resources(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        # Create entities with components
        kernel.create_entity(name="E1", components={"Comp": {"val": 10}})
        kernel.create_entity(name="E2", components={"Comp": {"val": 20}})
        assert get_available_function_pills(kernel) == []


# =============================================================================
# 4. Display Name Renaming (rename_script_function_display_name)
# =============================================================================

class TestDisplayNameRenaming:
    """Verification of rename_script_function_display_name refactoring."""

    def test_rename_inline_code_script(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        code = '''
def _fn_attack(self, dt): # Quick Slash
    self.stats.power += 5
'''
        s_rid = kernel.create_script_resource(name="MeleeScript", code=code)
        assert not isinstance(s_rid, Error)
        sid_hex = kernel.get_storage_id(s_rid).hex().lower()

        err = rename_script_function_display_name(kernel, sid_hex, "_fn_attack", "Mighty Slash")
        assert err is None

        # Verify in memory code
        updated_code = kernel.resources[s_rid]["data"]["code"]
        assert "# Mighty Slash" in updated_code
        assert "def _fn_attack(self, dt):" in updated_code

        # Verify AST parse and symbols
        tree = ast.parse(updated_code)
        fn_nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_fn_attack"]
        assert len(fn_nodes) == 1

        updated_symbols = kernel.resources[s_rid]["data"]["symbols"]
        assert updated_symbols["_fn_attack"] == "Mighty Slash"

    def test_rename_external_source_path_script(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        script_file = tmp_path / "ranged_combat.py"
        script_file.write_text('''
def _fn_shoot(self, dt): # Shoot Arrow
    self.stats.ammo -= 1
''', encoding="utf-8")

        s_rid = kernel.create_script_resource(name="RangedScript", source_path=str(script_file))
        assert not isinstance(s_rid, Error)
        sid_hex = kernel.get_storage_id(s_rid).hex().lower()

        err = rename_script_function_display_name(kernel, sid_hex, "_fn_shoot", "Sniper Shot")
        assert err is None

        # Verify disk file updated
        file_content = script_file.read_text(encoding="utf-8")
        assert "# Sniper Shot" in file_content
        assert "def _fn_shoot(self, dt):" in file_content

        # Verify memory payload
        assert kernel.resources[s_rid]["data"]["symbols"]["_fn_shoot"] == "Sniper Shot"
        assert kernel.is_dirty(s_rid)

    def test_rename_adds_comment_when_none_existed(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        code = '''
def _fn_block(self, dt):
    self.stats.guard = True
'''
        s_rid = kernel.create_script_resource(name="DefendScript", code=code)
        assert not isinstance(s_rid, Error)
        sid_hex = kernel.get_storage_id(s_rid).hex().lower()

        err = rename_script_function_display_name(kernel, sid_hex, "_fn_block", "Iron Guard")
        assert err is None

        updated_code = kernel.resources[s_rid]["data"]["code"]
        assert "# Iron Guard" in updated_code
        assert kernel.resources[s_rid]["data"]["symbols"]["_fn_block"] == "Iron Guard"

    def test_rename_preserves_callable_execution_uninterrupted(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        code = '''
def _fn_buff(self, dt): # Old Buff
    self.stats.mana += 20
'''
        s_rid = kernel.create_script_resource(name="BuffScript", code=code)
        assert not isinstance(s_rid, Error)
        sid_hex = kernel.get_storage_id(s_rid).hex().lower()

        # Entity attaching script
        e_rid = kernel.create_entity(name="Wizard", components={"stats": {"mana": 50}})
        assert not isinstance(e_rid, Error)
        attach_err = kernel.attach_script(e_rid, s_rid)
        assert not isinstance(attach_err, Error)

        # Rename display name
        err = rename_script_function_display_name(kernel, sid_hex, "_fn_buff", "Arcane Surge")
        assert err is None

        # Callers referencing _fn_buff continue executing uninterrupted
        proxy = kernel.get_script_proxy(s_rid)
        assert not isinstance(proxy, Error)
        entity_proxy = kernel.get_entity_proxy(e_rid)
        assert not isinstance(entity_proxy, Error)

        # Call via symbol identifier
        proxy._fn_buff(entity_proxy, 0.016)
        assert entity_proxy.stats.mana == 70

        # Call via bound proxy
        bound = proxy.bind(entity_proxy)
        bound._fn_buff(0.016)
        assert entity_proxy.stats.mana == 90

    def test_rename_negative_cases(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        code = '''
def _fn_run(self, dt): # Run Fast
    pass
'''
        s_rid = kernel.create_script_resource(name="SpeedScript", code=code)
        assert not isinstance(s_rid, Error)
        sid_hex = kernel.get_storage_id(s_rid).hex().lower()

        e_rid = kernel.create_entity(name="Ent", components={"Data": {}})
        assert not isinstance(e_rid, Error)
        e_sid = kernel.get_storage_id(e_rid).hex().lower()

        # 1. Empty display name
        err1 = rename_script_function_display_name(kernel, sid_hex, "_fn_run", "")
        assert isinstance(err1, Error)
        assert err1.code == InvalidResourceDataError

        # 2. Whitespace-only or hash-only
        err2 = rename_script_function_display_name(kernel, sid_hex, "_fn_run", "   # #   ")
        assert isinstance(err2, Error)
        assert err2.code == InvalidResourceDataError

        # 3. Invalid hex storage ID
        err3 = rename_script_function_display_name(kernel, "not_a_valid_hex", "_fn_run", "New Name")
        assert isinstance(err3, Error)
        assert err3.code == InvalidResourceDataError

        # 4. Non-existent script storage ID
        err4 = rename_script_function_display_name(kernel, "0" * 32, "_fn_run", "New Name")
        assert isinstance(err4, Error)
        assert err4.code == RuntimeIDNotFoundOnMemoryError

        # 5. Target resource is an entity, not a script
        err5 = rename_script_function_display_name(kernel, e_sid, "_fn_run", "New Name")
        assert isinstance(err5, Error)
        assert err5.code == InvalidResourceDataError

        # 6. Non-existent symbol ID in script
        err6 = rename_script_function_display_name(kernel, sid_hex, "_fn_missing", "New Name")
        assert isinstance(err6, Error)
        assert err6.code == InvalidResourceDataError

    def test_rename_function_with_bracket_reference_in_parameter_defaults(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        code = '''
def _fn_jump(entity, target=<|0|11223344556677881122334455667788|>): # old_jump
    pass
'''
        s_rid = kernel.create_script_resource(name="JumpScript", code=code)
        assert not isinstance(s_rid, Error)
        sid_hex = kernel.get_storage_id(s_rid).hex().lower()

        err = rename_script_function_display_name(kernel, sid_hex, "_fn_jump", "new_jump")
        assert err is None

        updated_code = kernel.resources[s_rid]["data"]["code"]
        assert "def _fn_jump(entity, target=<|0|11223344556677881122334455667788|>): # new_jump" in updated_code
        assert "): # new_jump" in updated_code
        new_symbols = extract_script_symbols(updated_code)
        assert new_symbols == {"_fn_jump": "new_jump"}

    def test_rename_function_with_multiple_bracket_references_in_parameter_defaults(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        code = '''
def _fn_cast(caster, target=<|0|11223344556677881122334455667788|>, spell=<|1|aabbccddeeff00112233445566778899|>): # old_cast
    pass
'''
        s_rid = kernel.create_script_resource(name="SpellScript", code=code)
        assert not isinstance(s_rid, Error)
        sid_hex = kernel.get_storage_id(s_rid).hex().lower()

        err = rename_script_function_display_name(kernel, sid_hex, "_fn_cast", "new_cast")
        assert err is None

        updated_code = kernel.resources[s_rid]["data"]["code"]
        assert "def _fn_cast(caster, target=<|0|11223344556677881122334455667788|>, spell=<|1|aabbccddeeff00112233445566778899|>): # new_cast" in updated_code
        assert "): # new_cast" in updated_code
        new_symbols = extract_script_symbols(updated_code)
        assert new_symbols == {"_fn_cast": "new_cast"}

    def test_rename_function_rejects_newlines_in_display_name(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        code = '''
def _fn_act(self): # Action
    pass
'''
        s_rid = kernel.create_script_resource(name="ActionScript", code=code)
        assert not isinstance(s_rid, Error)
        sid_hex = kernel.get_storage_id(s_rid).hex().lower()

        err_nl = rename_script_function_display_name(kernel, sid_hex, "_fn_act", "jump\nattack")
        assert isinstance(err_nl, Error)
        assert err_nl.code == InvalidResourceDataError
        assert "newline" in err_nl.description.lower()

        err_cr = rename_script_function_display_name(kernel, sid_hex, "_fn_act", "jump\rattack")
        assert isinstance(err_cr, Error)
        assert err_cr.code == InvalidResourceDataError

        err_crlf = rename_script_function_display_name(kernel, sid_hex, "_fn_act", "jump\r\nattack")
        assert isinstance(err_crlf, Error)
        assert err_crlf.code == InvalidResourceDataError

        assert "# Action" in kernel.resources[s_rid]["data"]["code"]

    def test_rename_function_returns_error_on_preexisting_syntax_or_tokenize_error(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        # Case 1: unclosed parenthesis e.g. def _fn_broken(
        broken_code1 = "def _fn_broken(\n"
        s_rid1 = kernel.create_script_resource(name="BrokenScript1", code=broken_code1)
        assert not isinstance(s_rid1, Error)
        sid_hex1 = kernel.get_storage_id(s_rid1).hex().lower()

        err1 = rename_script_function_display_name(kernel, sid_hex1, "_fn_broken", "Fixed")
        assert isinstance(err1, Error)
        assert err1.code == InvalidResourceDataError

        # Case 2: syntax error with missing closing paren in header
        broken_code2 = "def _fn_broken(self:\n    pass\n"
        s_rid2 = kernel.create_script_resource(name="BrokenScript2", code=broken_code2)
        assert not isinstance(s_rid2, Error)
        sid_hex2 = kernel.get_storage_id(s_rid2).hex().lower()

        err2 = rename_script_function_display_name(kernel, sid_hex2, "_fn_broken", "Fixed")
        assert isinstance(err2, Error)
        assert err2.code == InvalidResourceDataError



# =============================================================================
# 5. Inspector Panel & Storage Panel UI Integration
# =============================================================================

class TestPillUIIntegration:
    """Headless Dear PyGui UI integration tests for pills and tool modals."""

    def test_inspector_renders_visual_pill_badge_for_reference_string(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        script_code = '''
def _fn_jump(self, dt): # Player Jump Handler
    pass
'''
        s_rid = kernel.create_script_resource(name="JumpScript", code=script_code)
        assert not isinstance(s_rid, Error)
        s_sid = kernel.get_storage_id(s_rid).hex().lower()

        ref_str = f"<|1|{s_sid}|>._fn_jump"
        e_rid = kernel.create_entity(name="Hero", components={"Actions": {"jump_action": ref_str}})
        assert not isinstance(e_rid, Error)

        app = EditorApp(kernel=kernel, auto_build=True)
        try:
            app.start_non_blocking(render_frame=True)
            app.session.select_entity(e_rid)
            app.start_non_blocking(render_frame=True)

            assert app.inspector_panel is not None
            buttons = find_buttons(app.inspector_panel.content_tag)
            badge_matches = [
                (btn, lbl) for btn, lbl in buttons
                if "JumpScript" in lbl and "Player Jump Handler" in lbl
            ]
            assert len(badge_matches) == 1
            _, badge_label = badge_matches[0]
            assert "JumpScript" in badge_label
            assert "Player Jump Handler" in badge_label
        finally:
            app.destroy()

    def test_inspector_detail_and_rename_modal(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        script_code = '''
def _fn_fire(self, dt): # Fire Missile
    pass
'''
        s_rid = kernel.create_script_resource(name="WeaponScript", code=script_code)
        assert not isinstance(s_rid, Error)
        s_sid = kernel.get_storage_id(s_rid).hex().lower()

        ref_str = f"<|1|{s_sid}|>._fn_fire"
        e_rid = kernel.create_entity(name="Turret", components={"Weapon": {"on_fire": ref_str}})
        assert not isinstance(e_rid, Error)

        app = EditorApp(kernel=kernel, auto_build=True)
        try:
            app.start_non_blocking(render_frame=True)
            app.session.select_entity(e_rid)
            app.start_non_blocking(render_frame=True)

            inspector = app.inspector_panel
            assert inspector is not None

            pill = parse_reference_pill(ref_str, kernel)
            assert pill is not None
            inspector._open_pill_info_modal(0, None, pill)

            modal_tag = "window_pill_info_modal"
            assert dpg.does_item_exist(modal_tag)
            rename_input = f"{modal_tag}_rename_input"
            assert dpg.does_item_exist(rename_input)

            dpg.set_value(rename_input, "Launch Super Rocket")
            inspector._on_rename_display_name_submit(0, None, (pill, rename_input, modal_tag))

            assert not dpg.does_item_exist(modal_tag)
            assert kernel.resources[s_rid]["data"]["symbols"]["_fn_fire"] == "Launch Super Rocket"

            buttons = find_buttons(inspector.content_tag)
            assert any("Launch Super Rocket" in lbl for _, lbl in buttons)
        finally:
            app.destroy()

    def test_inspector_function_picker_updates_field_and_component(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        script_code = '''
def _fn_click(self, dt): # On Button Click
    pass
'''
        s_rid = kernel.create_script_resource(name="ButtonLogic", code=script_code)
        assert not isinstance(s_rid, Error)
        s_sid = kernel.get_storage_id(s_rid).hex().lower()

        e_rid = kernel.create_entity(name="MenuButton", components={"UI": {"on_click": ""}})
        assert not isinstance(e_rid, Error)
        kernel.save_dirty_resources()
        assert not kernel.is_dirty(e_rid)

        app = EditorApp(kernel=kernel, auto_build=True)
        try:
            app.start_non_blocking(render_frame=True)
            app.session.select_entity(e_rid)
            app.start_non_blocking(render_frame=True)

            inspector = app.inspector_panel
            assert inspector is not None

            input_tag = f"{inspector.tag}_hnd_inp_{e_rid}_UI_on_click"
            assert dpg.does_item_exist(input_tag)

            # Open function picker
            inspector._open_function_picker(0, None, (e_rid, "UI", ["on_click"], input_tag))
            assert dpg.does_item_exist("window_function_picker")

            pills = get_available_function_pills(kernel)
            assert len(pills) == 1
            chosen_pill = pills[0]

            inspector._on_picker_select_pill(
                0,
                None,
                (chosen_pill, e_rid, "UI", ["on_click"], input_tag, "window_function_picker"),
            )

            assert not dpg.does_item_exist("window_function_picker")

            comp = app.session.get_components(e_rid)
            expected_ref = f"<|1|{s_sid}|>._fn_click"
            assert comp["UI"]["on_click"] == expected_ref
            assert app.session.is_dirty(e_rid)

            buttons = find_buttons(inspector.content_tag)
            assert any("ButtonLogic" in lbl and "On Button Click" in lbl for _, lbl in buttons)
        finally:
            app.destroy()

    def test_storage_panel_functions_button_and_modal(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        script_code = '''
def _fn_alpha(self, dt): # Alpha Task
    pass

def _fn_beta(self, dt): # Beta Task
    pass
'''
        s_rid = kernel.create_script_resource(name="TasksScript", code=script_code)
        assert not isinstance(s_rid, Error)
        s_sid = kernel.get_storage_id(s_rid).hex().lower()

        app = EditorApp(kernel=kernel, auto_build=True)
        try:
            app.start_non_blocking(render_frame=True)
            storage = app.storage_panel
            assert storage is not None

            fn_buttons = find_buttons(storage.table_tag, text_match="Functions")
            assert len(fn_buttons) >= 1

            # Open script functions modal
            storage._open_script_functions_modal(0, None, (s_rid, "TasksScript", s_sid))
            modal_tag = f"window_script_functions_{s_rid}"
            assert dpg.does_item_exist(modal_tag)

            modal_buttons = find_buttons(modal_tag)
            copy_buttons = [b for b, lbl in modal_buttons if "Copy Ref" in lbl]
            rename_buttons = [b for b, lbl in modal_buttons if "Rename" in lbl]
            assert len(copy_buttons) == 2
            assert len(rename_buttons) == 2

            # Test opening rename dialog
            pill = PillData(
                res_type=Script,
                storage_id_hex=s_sid,
                res_name="TasksScript",
                fn_symbol="_fn_alpha",
                fn_display_name="Alpha Task",
                raw_ref=f"<|1|{s_sid}|>._fn_alpha",
            )
            storage._open_rename_dialog(0, None, (pill, modal_tag, s_sid))
            dialog_tag = f"dialog_rename_{pill.fn_symbol}"
            assert dpg.does_item_exist(dialog_tag)

            input_tag = f"{dialog_tag}_input"
            assert dpg.does_item_exist(input_tag)
            dpg.set_value(input_tag, "Super Alpha Task")

            storage._on_apply_function_rename(
                0,
                None,
                (pill, input_tag, dialog_tag, modal_tag, s_sid),
            )

            assert not dpg.does_item_exist(dialog_tag)
            assert kernel.resources[s_rid]["data"]["symbols"]["_fn_alpha"] == "Super Alpha Task"
        finally:
            app.destroy()

    def test_entity_pill_modal_title_and_label(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        e_rid = kernel.create_entity(name="RootNode")
        assert not isinstance(e_rid, Error)
        e_sid = kernel.get_storage_id(e_rid).hex().lower()

        pill = parse_reference_pill(f"<|0|{e_sid}|>", kernel)
        assert pill is not None
        assert pill.display_label == "[RootNode]"
        assert "::" not in pill.display_label

        app = EditorApp(kernel=kernel, auto_build=True)
        try:
            app.start_non_blocking(render_frame=True)
            assert app.inspector_panel is not None
            app.inspector_panel._open_pill_info_modal(0, None, pill)

            modal_tag = "window_pill_info_modal"
            assert dpg.does_item_exist(modal_tag)
            cfg = dpg.get_item_configuration(modal_tag)
            assert cfg.get("label") == "Entity Reference Details"
        finally:
            app.destroy()


# =============================================================================
# 6. Planned Tests for Unimplemented Features
# =============================================================================

class TestPlannedPillCapabilities:
    """Planned tests for future capabilities not yet implemented in the prototype."""

    @pytest.mark.skip(
        reason="Planned test: Preprocessor or editor automatic call-site refactoring when a function symbol UID is renamed"
    )
    def test_planned_automatic_call_site_refactoring_on_symbol_rename(self) -> None:
        """Future: Renaming an internal symbol UID should automatically update call-sites in dependent scripts."""
        pass

    @pytest.mark.skip(
        reason="Planned test: Failed hot reload rollback preserves prior bytecode when live reloaded script contains syntax error"
    )
    def test_planned_hot_reload_rollback_on_syntax_error(self) -> None:
        """Future: If updated script source fails syntax check, previous valid bytecode remains active in memory."""
        pass

    def test_planned_stale_handle_safety_when_referenced_script_destroyed(self, tmp_path: Path) -> None:
        """Deleting a script resource safely invalidates proxies without crashing callers."""
        kernel = Kernel(tmp_path)
        script_code = "def _fn_calculate():\n    return 42\n"
        s1 = kernel.create_script_resource("MathUtils", code=script_code)
        assert not isinstance(s1, Error)

        proxy1 = kernel.get_script_proxy(s1)
        assert not isinstance(proxy1, Error)
        assert proxy1.is_alive
        assert proxy1._fn_calculate() == 42

        # Delete the script resource
        res = kernel.delete_resource(s1)
        assert res is True
        assert not kernel.is_valid_runtime_id(s1)
        assert not proxy1.is_alive

        # Calling functions or properties on stale proxy raises cleanly
        with pytest.raises(AttributeError):
            _ = proxy1._fn_calculate

        get_res = kernel.get_resource(s1)
        assert isinstance(get_res, Error)
        assert get_res.code == RuntimeIDNotFoundOnMemoryError

        # Create a new script resource that recycles the slot
        new_code = "def _fn_other():\n    return 100\n"
        s2 = kernel.create_script_resource("OtherUtils", code=new_code)
        assert not isinstance(s2, Error)
        assert s2 != s1

        slot1, gen1 = kernel._unpack_handle(s1)
        slot2, gen2 = kernel._unpack_handle(s2)
        assert slot1 == slot2
        assert gen2 > gen1

        # Old proxy remains dead and cannot access the recycled slot
        assert not proxy1.is_alive
        with pytest.raises(AttributeError):
            _ = proxy1._fn_calculate

        proxy2 = kernel.get_script_proxy(s2)
        assert not isinstance(proxy2, Error)
        assert proxy2.is_alive
        assert proxy2._fn_other() == 100

    test_planned_stale_handle_safety_when_script_destroyed = test_planned_stale_handle_safety_when_referenced_script_destroyed

    @pytest.mark.skip(
        reason="Planned test: Transactional rollback cleans up loaded parents if a nested script resource fails load validation"
    )
    def test_planned_transactional_rollback_on_failed_script_load(self) -> None:
        """Future: If a script dependency fails disk validation, partially registered parents are rolled back."""
        pass
