"""Tests for <lbe.ref("uid")> preprocessing, pure-UUID exports, and Code Editor panel."""

from __future__ import annotations

from pathlib import Path
import dearpygui.dearpygui as dpg
import pytest

from editor.app import EditorApp
from editor.code_editor_panel import CodeEditorPanel
from editor.inspector_panel import InspectorPanel
from editor.pills import (
    get_code_token_pill_theme,
    render_code_token_pill,
)
from editor.session import EditorSession
from LBE import (
    BrokenReferenceError,
    Entity,
    Error,
    Kernel,
    LBEReferenceSyntaxError,
    ReferencePreprocessor,
    RuntimeBinder,
    Script,
    project_display_to_source,
    project_source_to_display,
)


@pytest.fixture
def dpg_context():
    """Isolated Dear PyGui context per test."""
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


class TestLbeRefPreprocessingSyntax:
    """Verification of <lbe.ref("uid")> syntax preprocessing and execution without eval."""

    def test_lbe_ref_preprocessing_transform(self) -> None:
        source = 'target = <lbe.ref("2e4b8702e1e9514338d026d79d39f704")>\nresult = target.x'
        transformed, deps = ReferencePreprocessor.preprocess(source)

        assert '__lbe_resolve_ref__("2e4b8702e1e9514338d026d79d39f704")' in transformed
        assert (-1, "2e4b8702e1e9514338d026d79d39f704") in deps
        assert "<lbe.ref" not in transformed

    def test_lbe_ref_with_alias_preprocessing(self) -> None:
        source = 'target = <lbe.ref("2e4b8702e1e9514338d026d79d39f704", "Player")>'
        transformed, deps = ReferencePreprocessor.preprocess(source)

        assert '__lbe_resolve_ref__("2e4b8702e1e9514338d026d79d39f704")' in transformed
        assert (-1, "2e4b8702e1e9514338d026d79d39f704") in deps

    def test_lbe_ref_malformed_syntax_rejection(self) -> None:
        with pytest.raises(LBEReferenceSyntaxError) as exc_info:
            ReferencePreprocessor.preprocess('target = <lbe.ref("invalid")>')
        assert "Malformed LittleBigEngine reference syntax" in str(exc_info.value)

        with pytest.raises(LBEReferenceSyntaxError) as exc_info_len:
            ReferencePreprocessor.preprocess('target = <lbe.ref("1234")>')
        assert "Invalid reference storage ID length" in str(exc_info_len.value)

        with pytest.raises(LBEReferenceSyntaxError) as exc_info2:
            ReferencePreprocessor.preprocess('target = <lbe.ref(bad_syntax>')
        assert "Malformed LittleBigEngine reference syntax" in str(exc_info2.value)

    def test_lbe_ref_runtime_execution_resolves_entity(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        # Create an entity
        e_rid = kernel.create_entity(name="HeroEntity")
        assert not isinstance(e_rid, Error)
        kernel.set_component(e_rid, "Transform", {"x": 42.0, "y": 99.0})
        e_sid = kernel.get_storage_id(e_rid)
        assert not isinstance(e_sid, Error)
        sid_hex = e_sid.hex()

        # Run script with <lbe.ref(...)>
        code = f'''
hero = <lbe.ref("{sid_hex}")>
hero_x = hero.Transform.x
'''
        result_ns = kernel.execute_script(code)
        assert "hero" in result_ns
        assert result_ns["hero_x"] == 42.0

    def test_lbe_ref_runtime_execution_resolves_function_export(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        func_uuid = "a1000000000000000000000000000099"
        # Create script with function
        script_code = f'''
def fn_{func_uuid}(val):
    return val * 10
'''
        s_rid = kernel.create_script_resource(name="MathScript", code=script_code)
        assert not isinstance(s_rid, Error)

        # Call script with <lbe.ref(...)>
        caller_code = f'''
fn = <lbe.ref("{func_uuid}")>
res = fn(5)
'''
        result_ns = kernel.execute_script(caller_code)
        assert result_ns["res"] == 50


class TestPureUuidFunctionExportsAndProjection:
    """Verification of pure UUID function definitions on disk and bidirectional display projection."""

    def test_fn_uuid_definition_auto_registers_in_kernel(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        func_uuid = "bb000000000000000000000000000001"
        code = f'''
def fn_{func_uuid}(x, y):
    return x + y
'''
        s_rid = kernel.create_script_resource(name="AddScript", code=code)
        assert not isinstance(s_rid, Error)

        # Resolve function export
        res = kernel.resolve_function_export(func_uuid)
        assert not isinstance(res, Error)
        fn_callable, script_id = res
        assert fn_callable(10, 25) == 35

    def test_project_source_to_display_and_back(self, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        func_uuid = "cc000000000000000000000000000002"
        entity_uuid = "ee000000000000000000000000000003"

        disk_code = f'''def fn_{func_uuid}(player):
    target = <lbe.ref("{entity_uuid}", "Entity2")>
    return target
'''
        symbols = {f"fn_{func_uuid}": "update_player"}

        # Project disk -> display
        display_code, tokens = project_source_to_display(disk_code, symbols=symbols, kernel=kernel)
        assert "def update_player(player):" in display_code
        assert "target = Entity2" in display_code
        assert f"fn_{func_uuid}" not in display_code
        assert "<lbe.ref" not in display_code

        # Check extracted tokens
        assert any(t["name"] == "update_player" and t["uuid"] == func_uuid for t in tokens)
        assert any(t["name"] == "Entity2" and t["uuid"] == entity_uuid for t in tokens)

        # Project display -> disk
        restored_disk = project_display_to_source(display_code, symbols=symbols, kernel=kernel)
        assert f"def fn_{func_uuid}(player):" in restored_disk


class TestCodeTokenPillHoverBoxWidget:
    """Verification of the interactive code token widget in Dear PyGui."""

    def test_code_token_pill_theme_creation(self, dpg_context) -> None:
        theme = get_code_token_pill_theme()
        assert dpg.does_item_exist(theme)
        assert dpg.get_item_type(theme) == "mvAppItemType::mvTheme"

    def test_render_code_token_pill_headless(self, dpg_context) -> None:
        with dpg.window(label="TestWindow"):
            btn = render_code_token_pill(
                display_name="update_player",
                uuid_hex="a1000000000000000000000000000001",
                token_type="function",
            )
            assert dpg.does_item_exist(btn)
            assert dpg.get_item_label(btn) == "update_player"

            # Verify tooltip was attached
            children = dpg.get_item_children(btn, 3)  # slot 3 is tooltip/handlers
            assert len(children) > 0


class TestCodeEditorPanelIntegration:
    """Verification of CodeEditorPanel lifecycle, script switching, and drop targets."""

    def test_code_editor_panel_builds_and_lists_scripts(self, dpg_context, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        s_rid = kernel.create_script_resource(
            name="PlatformerLogic",
            code="def fn_a10000000000000000000000000000001(x):\n    return x + 1\n",
        )
        assert not isinstance(s_rid, Error)

        session = EditorSession(kernel)
        panel = CodeEditorPanel(session)
        panel.build()

        assert dpg.does_item_exist("window_code_editor")
        assert panel.current_script_id == s_rid
        assert "fn_a10000000000000000000000000000001" in panel.current_disk_code

    def test_code_editor_mode_switching(self, dpg_context, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        s_rid = kernel.create_script_resource(
            name="Logic",
            code="def fn_a10000000000000000000000000000001(x):\n    return x\n",
        )
        session = EditorSession(kernel)
        panel = CodeEditorPanel(session)
        panel.build()

        # Switch mode to Source Code
        panel._on_mode_changed(None, "Source Code")
        assert panel.active_mode == "Source Code"
        assert dpg.does_item_exist(f"{panel.tag}_input")

        # Switch back to Interactive
        panel._on_mode_changed(None, "Code View (Interactive)")
        assert panel.active_mode == "Code View (Interactive)"

    def test_editor_app_hosts_code_editor_panel(self, dpg_context, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        app = EditorApp(kernel=kernel, folder_location=tmp_path)
        assert app.code_editor_panel is not None
        assert dpg.does_item_exist("window_code_editor")
        assert app.session.active_code_editor is app.code_editor_panel

    def test_inspector_property_slot_drop_target(self, dpg_context, tmp_path: Path) -> None:
        kernel = Kernel(tmp_path)
        e_rid = kernel.create_entity(name="TestHero")
        assert not isinstance(e_rid, Error)
        kernel.set_component(e_rid, "Property:Health", {
            "name": "Health",
            "getter": "a1000000000000000000000000000001",
            "setter": "",
        })

        session = EditorSession(kernel)
        session.select_entity(e_rid)

        inspector = InspectorPanel(session)
        inspector.build()

        # Simulate dropping a token onto the setter slot
        new_setter_uuid = "a1000000000000000000000000000002"
        inspector._on_drop_property_slot(
            sender=0,
            app_data={"type": "LBE_REF", "uuid": new_setter_uuid, "name": "health_set"},
            user_data=(e_rid, "Property:Health", "setter"),
        )

        # Verify component was updated with the dropped setter UUID!
        comps = kernel.get_components(e_rid)
        assert comps["Property:Health"]["setter"] == new_setter_uuid
