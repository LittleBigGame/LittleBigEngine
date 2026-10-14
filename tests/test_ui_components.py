"""Tests for Stage 2: Engine-Native UI Components & Function Event Binding.

Derives tests from observable user requirements and kernel contracts:
1. Schema validation (Validate.ui_component, Validate.resource_data, Kernel.set_component).
2. UI Entity creation and hierarchy (Kernel.create_ui_entity with defaults, props merging, and parenting).
3. Event dispatch and function binding (trigger_ui_event, proxy.click, proxy.trigger).
4. End-to-end disk persistence roundtrip of mutated UI hierarchy.
5. Planned future features (event bubbling, handle generation safety, transactional rollback).
"""

import pytest

from LBE import (
    Entity,
    Error,
    Kernel,
    UI_SCHEMAS,
    Validate,
)
from LBE.types import (
    EntityTypeMismatchError,
    InvalidResourceDataError,
    RuntimeIDNotFoundOnMemoryError,
)


class TestUIComponentSchemaValidation:
    """Tests schema integrity rules for all engine-native UI component definitions."""

    def test_valid_schemas_for_all_ui_component_types(self):
        for canonical_name, default_props in UI_SCHEMAS.items():
            err = Validate.ui_component(canonical_name, default_props)
            assert err is None, f"Default schema for {canonical_name} failed validation: {err}"

    def test_unknown_and_non_ui_components_pass_silently(self):
        assert Validate.ui_component("Transform", {"x": 10, "y": 20}) is None
        assert Validate.ui_component("Health", {"current": 100, "max": 100}) is None
        assert Validate.ui_component("CustomComponent", {"custom": "data"}) is None
        assert Validate.ui_component(12345, {"data": "ignored"}) is None

    def test_case_insensitive_component_name_validation(self):
        btn_props = {"label": "Submit", "width": 100.0, "height": 30.0, "on_click": "", "enabled": True}
        assert Validate.ui_component("uibutton", btn_props) is None
        assert Validate.ui_component("UIButton", btn_props) is None
        assert Validate.ui_component("UIBUTTON", btn_props) is None
        assert Validate.ui_component("UiBuTtOn", btn_props) is None

        container_props = {"layout": "vertical", "gap": 2.0, "padding": 2.0, "columns": 1, "collapsible": False, "collapsed": False}
        assert Validate.ui_component("uicontainer", container_props) is None
        assert Validate.ui_component("UIContainer", container_props) is None
        assert Validate.ui_component("UICONTAINER", container_props) is None

    def test_unexpected_keys_rejected(self):
        err = Validate.ui_component("UIButton", {"label": "Submit", "unknown_field": "not_allowed"})
        assert isinstance(err, Error)
        assert err.code == InvalidResourceDataError
        assert "unexpected key" in err.description

        err2 = Validate.ui_component("UIContainer", {"layout": "vertical", "extra_padding": 10})
        assert isinstance(err2, Error)
        assert err2.code == InvalidResourceDataError

    def test_non_dict_component_data_rejected(self):
        err = Validate.ui_component("UIButton", "not_a_dict")
        assert isinstance(err, Error)
        assert err.code == InvalidResourceDataError
        assert "must be a dictionary" in err.description

        err2 = Validate.ui_component("UISlider", [1, 2, 3])
        assert isinstance(err2, Error)
        assert err2.code == InvalidResourceDataError

    def test_uicontainer_invalid_layout_rejected(self):
        for layout in ["diagonal", "horizontal_layout", 123, None, ""]:
            err = Validate.ui_component("UIContainer", {"layout": layout})
            assert isinstance(err, Error), f"Expected error for layout={layout!r}"
            assert err.code == InvalidResourceDataError

        for valid_layout in ["vertical", "horizontal", "grid"]:
            assert Validate.ui_component("UIContainer", {"layout": valid_layout}) is None

    def test_uicontainer_negative_gap_and_padding_rejected(self):
        assert isinstance(Validate.ui_component("UIContainer", {"gap": -1.0}), Error)
        assert isinstance(Validate.ui_component("UIContainer", {"gap": -0.001}), Error)
        assert isinstance(Validate.ui_component("UIContainer", {"gap": "4px"}), Error)
        assert isinstance(Validate.ui_component("UIContainer", {"gap": True}), Error)

        assert isinstance(Validate.ui_component("UIContainer", {"padding": -1.0}), Error)
        assert isinstance(Validate.ui_component("UIContainer", {"padding": "10px"}), Error)
        assert isinstance(Validate.ui_component("UIContainer", {"padding": False}), Error)

        assert Validate.ui_component("UIContainer", {"gap": 0.0, "padding": 0}) is None
        assert Validate.ui_component("UIContainer", {"gap": 10, "padding": 12.5}) is None

    def test_uicontainer_invalid_columns_rejected(self):
        for invalid_col in [0, -1, -10, 1.5, True, False, "2", None]:
            err = Validate.ui_component("UIContainer", {"columns": invalid_col})
            assert isinstance(err, Error), f"Expected error for columns={invalid_col!r}"
            assert err.code == InvalidResourceDataError

        assert Validate.ui_component("UIContainer", {"columns": 1}) is None
        assert Validate.ui_component("UIContainer", {"columns": 4}) is None

    def test_uicontainer_non_boolean_flags_rejected(self):
        for val in [1, 0, "true", "false", None, [], {}]:
            assert isinstance(Validate.ui_component("UIContainer", {"collapsible": val}), Error)
            assert isinstance(Validate.ui_component("UIContainer", {"collapsed": val}), Error)

        assert Validate.ui_component("UIContainer", {"collapsible": True, "collapsed": False}) is None

    def test_uibutton_invalid_fields_rejected(self):
        assert isinstance(Validate.ui_component("UIButton", {"label": 123}), Error)
        assert isinstance(Validate.ui_component("UIButton", {"label": None}), Error)

        assert isinstance(Validate.ui_component("UIButton", {"width": -5.0}), Error)
        assert isinstance(Validate.ui_component("UIButton", {"width": True}), Error)
        assert isinstance(Validate.ui_component("UIButton", {"width": "auto"}), Error)

        assert isinstance(Validate.ui_component("UIButton", {"height": -1.0}), Error)
        assert isinstance(Validate.ui_component("UIButton", {"height": False}), Error)
        assert isinstance(Validate.ui_component("UIButton", {"height": "auto"}), Error)

        assert isinstance(Validate.ui_component("UIButton", {"enabled": 1}), Error)
        assert isinstance(Validate.ui_component("UIButton", {"enabled": "yes"}), Error)
        assert isinstance(Validate.ui_component("UIButton", {"enabled": None}), Error)

        assert Validate.ui_component("UIButton", {"label": "OK", "width": 0.0, "height": 0.0, "enabled": True}) is None

    def test_uibutton_handler_reference_validation(self):
        valid_sid = "0123456789abcdef0123456789abcdef"
        assert Validate.ui_component("UIButton", {"on_click": ""}) is None
        assert Validate.ui_component("UIButton", {"on_click": None}) is None
        assert Validate.ui_component("UIButton", {"on_click": "   "}) is None
        assert Validate.ui_component("UIButton", {"on_click": f"<|1|{valid_sid}|>.on_click"}) is None
        assert Validate.ui_component("UIButton", {"on_click": f"<|1|{valid_sid}|>._fn_action_1"}) is None

        # Non-string
        assert isinstance(Validate.ui_component("UIButton", {"on_click": 12345}), Error)
        assert isinstance(Validate.ui_component("UIButton", {"on_click": {"ref": "click"}}), Error)

        # Malformed references
        assert isinstance(Validate.ui_component("UIButton", {"on_click": "on_click"}), Error)
        assert isinstance(Validate.ui_component("UIButton", {"on_click": f"<|0|{valid_sid}|>.on_click"}), Error)  # Type 0 instead of 1
        assert isinstance(Validate.ui_component("UIButton", {"on_click": f"<|1|{valid_sid}|>"}), Error)  # Missing function
        assert isinstance(Validate.ui_component("UIButton", {"on_click": f"<|1|{valid_sid}|>."}), Error)
        assert isinstance(Validate.ui_component("UIButton", {"on_click": f"<|1|{valid_sid}|>.fn."}), Error)
        assert isinstance(Validate.ui_component("UIButton", {"on_click": "<|1|123|>.on_click"}), Error)  # Odd length hex
        assert isinstance(Validate.ui_component("UIButton", {"on_click": "<|1|xyz012|>.on_click"}), Error)  # Non-hex characters

    def test_uislider_invalid_fields_rejected(self):
        assert isinstance(Validate.ui_component("UISlider", {"label": 123}), Error)
        assert isinstance(Validate.ui_component("UISlider", {"min": "0"}), Error)
        assert isinstance(Validate.ui_component("UISlider", {"min": True}), Error)
        assert isinstance(Validate.ui_component("UISlider", {"max": "10"}), Error)
        assert isinstance(Validate.ui_component("UISlider", {"max": False}), Error)

        # min > max
        assert isinstance(Validate.ui_component("UISlider", {"min": 10.0, "max": 5.0}), Error)

        # value
        assert isinstance(Validate.ui_component("UISlider", {"value": "0.5"}), Error)
        assert isinstance(Validate.ui_component("UISlider", {"value": True}), Error)

        # step
        assert isinstance(Validate.ui_component("UISlider", {"step": 0.0}), Error)
        assert isinstance(Validate.ui_component("UISlider", {"step": -0.01}), Error)
        assert isinstance(Validate.ui_component("UISlider", {"step": True}), Error)
        assert isinstance(Validate.ui_component("UISlider", {"step": "0.1"}), Error)

        # on_change ref
        assert isinstance(Validate.ui_component("UISlider", {"on_change": "invalid_ref"}), Error)

        assert Validate.ui_component("UISlider", {"min": 0.0, "max": 100.0, "value": 50.0, "step": 1.0}) is None

    def test_uitextinput_invalid_fields_rejected(self):
        assert isinstance(Validate.ui_component("UITextInput", {"label": 123}), Error)
        assert isinstance(Validate.ui_component("UITextInput", {"text": 456}), Error)
        assert isinstance(Validate.ui_component("UITextInput", {"hint": None}), Error)
        assert isinstance(Validate.ui_component("UITextInput", {"is_search": 1}), Error)
        assert isinstance(Validate.ui_component("UITextInput", {"is_search": "true"}), Error)
        assert isinstance(Validate.ui_component("UITextInput", {"on_change": "bad_ref"}), Error)

        assert Validate.ui_component("UITextInput", {"label": "Search", "text": "", "hint": "Type here...", "is_search": True}) is None

    def test_uitext_invalid_fields_rejected(self):
        assert isinstance(Validate.ui_component("UIText", {"content": 123}), Error)
        assert isinstance(Validate.ui_component("UIText", {"bullet": 1}), Error)
        assert isinstance(Validate.ui_component("UIText", {"bullet": "no"}), Error)

        # color validation
        assert isinstance(Validate.ui_component("UIText", {"color": "#ffffff"}), Error)
        assert isinstance(Validate.ui_component("UIText", {"color": 12345}), Error)
        assert isinstance(Validate.ui_component("UIText", {"color": [1.0, 0.0]}), Error)  # length 2
        assert isinstance(Validate.ui_component("UIText", {"color": [1, 2, 3, 4, 5]}), Error)  # length 5
        assert isinstance(Validate.ui_component("UIText", {"color": ["1", "0", "0"]}), Error)  # non-numeric
        assert isinstance(Validate.ui_component("UIText", {"color": [True, 0.0, 0.0]}), Error)  # bool element

        assert Validate.ui_component("UIText", {"color": None}) is None
        assert Validate.ui_component("UIText", {"color": [1.0, 0.5, 0.2]}) is None
        assert Validate.ui_component("UIText", {"color": [0, 128, 255, 255]}) is None

    def test_uipanel_valid_properties_and_boundaries(self):
        # Default schema passes
        assert Validate.ui_component("UIPanel", UI_SCHEMAS["UIPanel"]) is None

        # Fully populated valid definition
        valid_props = {
            "title": "Debug Window",
            "width": 350.0,
            "height": 450.0,
            "minimized": False,
            "closable": True,
        }
        assert Validate.ui_component("UIPanel", valid_props) is None

        # Boundary checks: width and height exactly at minimum 50.0
        assert Validate.ui_component("UIPanel", {"width": 50.0, "height": 50.0}) is None
        assert Validate.ui_component("UIPanel", {"width": 50, "height": 50}) is None
        assert Validate.ui_component("UIPanel", {"width": 5000.0, "height": 3000.0}) is None

        # Optional fields omitting title or flags
        assert Validate.ui_component("UIPanel", {"width": 120.0}) is None
        assert Validate.ui_component("UIPanel", {"minimized": True}) is None
        assert Validate.ui_component("UIPanel", {}) is None

        # Case-insensitive canonical name and aliases
        assert Validate.ui_component("uipanel", valid_props) is None
        assert Validate.ui_component("UIPANEL", valid_props) is None
        assert Validate.ui_component("panel", valid_props) is None
        assert Validate.ui_component("PANEL", valid_props) is None

    def test_uipanel_invalid_fields_rejected(self):
        # Non-string title
        for bad_title in [123, None, True, False, ["Title"], {"t": "w"}]:
            err = Validate.ui_component("UIPanel", {"title": bad_title})
            assert isinstance(err, Error)
            assert err.code == InvalidResourceDataError
            assert "must be a string" in err.description

        # Width boundary & type failures (< 50.0, non-numeric, boolean)
        for bad_width in [49.99, 49.0, 0.0, -10.0, -0.001, "300", True, False, None, []]:
            err = Validate.ui_component("UIPanel", {"width": bad_width})
            assert isinstance(err, Error), f"Expected error for width={bad_width!r}"
            assert err.code == InvalidResourceDataError
            assert "must be a number >= 50.0" in err.description

        # Height boundary & type failures (< 50.0, non-numeric, boolean)
        for bad_height in [49.99, 49.0, 0.0, -10.0, -0.001, "400", True, False, None, []]:
            err = Validate.ui_component("UIPanel", {"height": bad_height})
            assert isinstance(err, Error), f"Expected error for height={bad_height!r}"
            assert err.code == InvalidResourceDataError
            assert "must be a number >= 50.0" in err.description

        # Non-boolean minimized
        for bad_min in ["false", 0, 1, 100, None, [], {}]:
            err = Validate.ui_component("UIPanel", {"minimized": bad_min})
            assert isinstance(err, Error)
            assert err.code == InvalidResourceDataError
            assert "must be a boolean" in err.description

        # Non-boolean closable
        for bad_close in ["true", 0, 1, -1, None, [], {}]:
            err = Validate.ui_component("UIPanel", {"closable": bad_close})
            assert isinstance(err, Error)
            assert err.code == InvalidResourceDataError
            assert "must be a boolean" in err.description

        # Unexpected fields
        for unknown_key in ["resizable", "collapsed", "on_close", "dockable"]:
            err = Validate.ui_component("UIPanel", {unknown_key: True})
            assert isinstance(err, Error)
            assert err.code == InvalidResourceDataError
            assert "unexpected key" in err.description

        # Alias "panel" validates against UIPanel schema
        err_alias = Validate.ui_component("panel", {"width": 10.0})
        assert isinstance(err_alias, Error)
        assert err_alias.code == InvalidResourceDataError

        # Internal workstation panels are exempted from UIPanel schema
        assert Validate.ui_component("panel", {"panel_type": "scene_view", "width": 10.0}) is None
        assert Validate.ui_component("UIPanel", {"panel_type": "console", "resizable": True}) is None

    def test_wiring_in_validate_resource_data(self):
        payload_bad = {
            "type": Entity,
            "data": {
                "components": {
                    "UIButton": {"width": -50.0}
                }
            }
        }
        err = Validate.resource_data(payload_bad)
        assert isinstance(err, Error)
        assert err.code == InvalidResourceDataError

        payload_bad_panel = {
            "type": Entity,
            "data": {
                "components": {
                    "UIPanel": {"width": 30.0}
                }
            }
        }
        err_panel = Validate.resource_data(payload_bad_panel)
        assert isinstance(err_panel, Error)
        assert err_panel.code == InvalidResourceDataError

        payload_good = {
            "type": Entity,
            "data": {
                "components": {
                    "UIButton": {"label": "OK", "width": 50.0},
                    "UIPanel": {"title": "Tools", "width": 250.0, "height": 180.0},
                }
            }
        }
        assert Validate.resource_data(payload_good) is None

    def test_wiring_in_kernel_set_component(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity_id = kernel.create_entity(name="TestEntity")
        assert not isinstance(entity_id, Error)

        # Negative: invalid UI component rejected
        err = kernel.set_component(entity_id, "UIButton", {"width": -20.0})
        assert isinstance(err, Error)
        assert err.code == InvalidResourceDataError

        # Negative: invalid UIPanel rejected
        err_panel = kernel.set_component(entity_id, "UIPanel", {"width": 20.0})
        assert isinstance(err_panel, Error)
        assert err_panel.code == InvalidResourceDataError

        # Positive: valid UI component accepted
        assert kernel.set_component(entity_id, "UIButton", {"label": "Start", "width": 80.0}) is None
        comp = kernel.get_component(entity_id, "UIButton")
        assert comp["label"] == "Start"
        assert comp["width"] == 80.0

        # Positive: valid UIPanel accepted
        assert kernel.set_component(entity_id, "UIPanel", {"title": "Tools", "width": 250.0, "height": 150.0}) is None
        panel_comp = kernel.get_component(entity_id, "UIPanel")
        assert panel_comp["title"] == "Tools"
        assert panel_comp["width"] == 250.0
        assert panel_comp["height"] == 150.0

        # Via EntityProxy
        proxy = kernel.get_entity_proxy(entity_id)
        proxy_err = proxy.set("UISlider", {"min": 50.0, "max": 10.0})
        assert isinstance(proxy_err, Error)
        assert proxy_err.code == InvalidResourceDataError

        proxy_panel_err = proxy.set("UIPanel", {"height": 30.0})
        assert isinstance(proxy_panel_err, Error)
        assert proxy_panel_err.code == InvalidResourceDataError


class TestUIEntityCreationAndHierarchy:
    """Tests Kernel.create_ui_entity defaults, prop merging, and scene hierarchy wiring."""

    def test_create_ui_entity_defaults_for_all_types(self, tmp_path):
        kernel = Kernel(tmp_path)
        for canonical_name in UI_SCHEMAS:
            eid = kernel.create_ui_entity(name=f"Default_{canonical_name}", component_type=canonical_name)
            assert not isinstance(eid, Error), f"Failed to create {canonical_name}: {eid}"

            proxy = kernel.get_entity_proxy(eid)
            comp = proxy.get(canonical_name)
            assert comp is not None

            # Verify every default key from schema is populated
            for k, expected_v in UI_SCHEMAS[canonical_name].items():
                assert comp[k] == expected_v, f"Mismatch in {canonical_name}.{k}: {comp[k]} != {expected_v}"

    def test_create_ui_entity_all_aliases(self, tmp_path):
        kernel = Kernel(tmp_path)
        alias_tests = [
            ("container", "UIContainer"),
            ("button", "UIButton"),
            ("slider", "UISlider"),
            ("textinput", "UITextInput"),
            ("text_input", "UITextInput"),
            ("text", "UIText"),
            ("panel", "UIPanel"),
            ("uipanel", "UIPanel"),
            ("UIContainer", "UIContainer"),
            ("UIButton", "UIButton"),
            ("UISlider", "UISlider"),
            ("UITextInput", "UITextInput"),
            ("UIText", "UIText"),
            ("UIPanel", "UIPanel"),
        ]
        for alias, canonical_name in alias_tests:
            eid = kernel.create_ui_entity(name=f"Alias_{alias}", component_type=alias)
            assert not isinstance(eid, Error), f"Failed to create with alias {alias}: {eid}"
            proxy = kernel.get_entity_proxy(eid)
            assert proxy.has(canonical_name)

    def test_create_ui_entity_component_props_merging(self, tmp_path):
        kernel = Kernel(tmp_path)
        props = {"label": "CustomBtn", "width": 120.0}
        eid = kernel.create_ui_entity(name="MergedBtn", component_type="button", component_props=props)
        assert not isinstance(eid, Error)

        proxy = kernel.get_entity_proxy(eid)
        btn = proxy.uibutton
        assert btn.label == "CustomBtn"
        assert btn.width == 120.0
        # Defaults retained for unmentioned props
        assert btn.height == 0.0
        assert btn.on_click == ""
        assert btn.enabled is True

    def test_create_ui_entity_negative_cases(self, tmp_path):
        kernel = Kernel(tmp_path)

        # Non-string component_type
        assert isinstance(kernel.create_ui_entity("Bad", component_type=123), Error)

        # Unknown component type
        assert isinstance(kernel.create_ui_entity("Bad", component_type="checkbox"), Error)

        # Non-dict props
        assert isinstance(kernel.create_ui_entity("Bad", component_type="button", component_props="not_a_dict"), Error)

        # Invalid props failing validation
        assert isinstance(kernel.create_ui_entity("Bad", component_type="button", component_props={"width": -100}), Error)

    def test_create_ui_entity_hierarchy_wiring_with_runtime_id(self, tmp_path):
        kernel = Kernel(tmp_path)
        parent_id = kernel.create_ui_entity(name="RootContainer", component_type="container")
        assert not isinstance(parent_id, Error)

        child_id = kernel.create_ui_entity(name="ChildButton", component_type="button", parent_id=parent_id)
        assert not isinstance(child_id, Error)

        # Hierarchy verified via kernel queries
        assert kernel.get_entity_children(parent_id) == [child_id]
        assert kernel.get_entity_parent(child_id) == parent_id

        # Hierarchy verified via proxies
        parent_proxy = kernel.get_entity_proxy(parent_id)
        child_proxy = kernel.get_entity_proxy(child_id)
        assert len(parent_proxy.children) == 1
        assert parent_proxy.children[0].id == child_id
        assert child_proxy.parent.id == parent_id

    def test_create_ui_entity_hierarchy_wiring_with_entity_proxy(self, tmp_path):
        kernel = Kernel(tmp_path)
        parent_id = kernel.create_ui_entity(name="RootContainer", component_type="container")
        parent_proxy = kernel.get_entity_proxy(parent_id)

        # Pass EntityProxy as parent_id
        child_id = kernel.create_ui_entity(name="ChildSlider", component_type="slider", parent_id=parent_proxy)
        assert not isinstance(child_id, Error)

        child_proxy = kernel.get_entity_proxy(child_id)
        assert child_proxy.parent.id == parent_proxy.id
        assert any(c.id == child_id for c in parent_proxy.children)

    def test_create_ui_entity_nested_tree_hierarchy(self, tmp_path):
        kernel = Kernel(tmp_path)
        root_id = kernel.create_ui_entity("Root", "container", {"layout": "vertical"})
        root = kernel.get_entity_proxy(root_id)

        panel_id = kernel.create_ui_entity("Panel", "container", {"layout": "horizontal"}, parent_id=root)
        panel = kernel.get_entity_proxy(panel_id)

        btn_id = kernel.create_ui_entity("Btn", "button", {"label": "InsidePanel"}, parent_id=panel)
        btn = kernel.get_entity_proxy(btn_id)

        assert len(root.children) == 1
        assert root.children[0].id == panel_id
        assert len(panel.children) == 1
        assert panel.children[0].id == btn_id
        assert btn.parent.id == panel_id
        assert btn.parent.parent.id == root_id


class TestUIEventDispatchAndFunctionBinding:
    """Tests trigger_ui_event, proxy.click, proxy.trigger, and script invocation bindings."""

    def test_button_click_triggers_symbol_id_handler(self, tmp_path):
        kernel = Kernel(tmp_path)
        script_code = (
            'def _fn_on_btn_click(entity): # click_action\n'
            '    entity.uibutton.label = "Clicked!"\n'
            '    entity.stats.clicks += 1\n'
        )
        script_id = kernel.create_script_resource(name="ButtonEvents", code=script_code)
        assert not isinstance(script_id, Error)
        sid_hex = kernel.get_storage_id(script_id).hex()

        btn_id = kernel.create_ui_entity(
            name="TestBtn",
            component_type="button",
            component_props={
                "label": "Click Me",
                "on_click": f"<|1|{sid_hex}|>._fn_on_btn_click",
            },
        )
        assert not isinstance(btn_id, Error)
        kernel.set_component(btn_id, "Stats", {"clicks": 0})

        # Trigger via kernel.trigger_ui_event
        res = kernel.trigger_ui_event(btn_id, "on_click")
        assert not isinstance(res, Error)

        btn_proxy = kernel.get_entity_proxy(btn_id)
        assert btn_proxy.uibutton.label == "Clicked!"
        assert btn_proxy.stats.clicks == 1
        assert kernel.is_dirty(btn_id)

    def test_button_click_triggers_display_name_alias_handler(self, tmp_path):
        kernel = Kernel(tmp_path)
        script_code = (
            'def _fn_on_btn_press(entity): # submit_form\n'
            '    entity.uibutton.label = "Submitted"\n'
        )
        script_id = kernel.create_script_resource(name="FormEvents", code=script_code)
        sid_hex = kernel.get_storage_id(script_id).hex()

        btn_id = kernel.create_ui_entity(
            name="SubmitBtn",
            component_type="button",
            component_props={
                "label": "Submit",
                "on_click": f"<|1|{sid_hex}|>.submit_form",
            },
        )
        btn_proxy = kernel.get_entity_proxy(btn_id)

        # Trigger via proxy.click()
        res = btn_proxy.click()
        assert not isinstance(res, Error)
        assert btn_proxy.uibutton.label == "Submitted"

    def test_slider_change_triggers_handler_with_new_value(self, tmp_path):
        kernel = Kernel(tmp_path)
        script_code = (
            'def _fn_on_slider_change(entity, new_val): # update_slider\n'
            '    entity.uislider.value = new_val\n'
            '    entity.stats.last_changed = new_val\n'
        )
        script_id = kernel.create_script_resource(name="SliderEvents", code=script_code)
        sid_hex = kernel.get_storage_id(script_id).hex()

        slider_id = kernel.create_ui_entity(
            name="VolumeSlider",
            component_type="slider",
            component_props={
                "label": "Volume",
                "min": 0.0,
                "max": 1.0,
                "value": 0.2,
                "on_change": f"<|1|{sid_hex}|>._fn_on_slider_change",
            },
        )
        kernel.set_component(slider_id, "Stats", {"last_changed": 0.2})
        slider_proxy = kernel.get_entity_proxy(slider_id)

        # Trigger with 'on_change'
        res1 = slider_proxy.trigger("on_change", 0.8)
        assert not isinstance(res1, Error)
        assert slider_proxy.uislider.value == 0.8
        assert slider_proxy.stats.last_changed == 0.8

        # Trigger with 'change' (alias resolution)
        res2 = slider_proxy.trigger("change", 0.95)
        assert not isinstance(res2, Error)
        assert slider_proxy.uislider.value == 0.95
        assert slider_proxy.stats.last_changed == 0.95

    def test_handler_mutating_entity_marks_dirty(self, tmp_path):
        kernel = Kernel(tmp_path)
        script_code = (
            'def _fn_mutate_btn(entity):\n'
            '    entity.uibutton.label = "Mutated"\n'
        )
        script_id = kernel.create_script_resource(name="Mutator", code=script_code)
        sid_hex = kernel.get_storage_id(script_id).hex()

        btn_id = kernel.create_ui_entity(
            name="Btn",
            component_type="button",
            component_props={"label": "Old", "on_click": f"<|1|{sid_hex}|>._fn_mutate_btn"},
        )
        kernel.save_dirty_resources()
        assert not kernel.is_dirty(btn_id)

        btn_proxy = kernel.get_entity_proxy(btn_id)
        btn_proxy.click()
        assert kernel.is_dirty(btn_id)
        assert btn_proxy.uibutton.label == "Mutated"

    def test_handler_zero_arguments_execution(self, tmp_path):
        kernel = Kernel(tmp_path)
        script_code = (
            'def _fn_global_ping():\n'
            '    return "pong"\n'
        )
        script_id = kernel.create_script_resource(name="PingLib", code=script_code)
        sid_hex = kernel.get_storage_id(script_id).hex()

        btn_id = kernel.create_ui_entity(
            name="PingBtn",
            component_type="button",
            component_props={"on_click": f"<|1|{sid_hex}|>._fn_global_ping"},
        )
        btn_proxy = kernel.get_entity_proxy(btn_id)
        result = btn_proxy.click()
        assert result == "pong"

    def test_handler_extra_positional_arguments_fallback(self, tmp_path):
        kernel = Kernel(tmp_path)
        script_code = (
            'def _fn_standalone_calc(val):\n'
            '    return val * 10\n'
        )
        script_id = kernel.create_script_resource(name="CalcLib", code=script_code)
        sid_hex = kernel.get_storage_id(script_id).hex()

        btn_id = kernel.create_ui_entity(
            name="CalcBtn",
            component_type="button",
            component_props={"on_click": f"<|1|{sid_hex}|>._fn_standalone_calc"},
        )
        btn_proxy = kernel.get_entity_proxy(btn_id)
        # Calling click(5) invokes fallback func(5)
        result = btn_proxy.click(5)
        assert result == 50

    def test_handler_varargs_and_kwargs(self, tmp_path):
        kernel = Kernel(tmp_path)
        script_code = (
            'def _fn_vararg_handler(entity, *args, **kwargs):\n'
            '    return (entity.name, args, kwargs)\n'
        )
        script_id = kernel.create_script_resource(name="VarargLib", code=script_code)
        sid_hex = kernel.get_storage_id(script_id).hex()

        btn_id = kernel.create_ui_entity(
            name="VarargBtn",
            component_type="button",
            component_props={"on_click": f"<|1|{sid_hex}|>._fn_vararg_handler"},
        )
        btn_proxy = kernel.get_entity_proxy(btn_id)
        res = btn_proxy.click(1, 2, mode="turbo", flag=True)
        assert res == ("VarargBtn", (1, 2), {"mode": "turbo", "flag": True})

    def test_empty_or_none_handler_returns_none_cleanly(self, tmp_path):
        kernel = Kernel(tmp_path)
        btn_id = kernel.create_ui_entity("BtnEmpty", "button", {"on_click": ""})
        btn_proxy = kernel.get_entity_proxy(btn_id)
        assert btn_proxy.click() is None

        # None handler
        btn2_id = kernel.create_ui_entity("BtnNone", "button")
        btn2_proxy = kernel.get_entity_proxy(btn2_id)
        btn2_proxy.uibutton.on_click = None
        assert btn2_proxy.click() is None

    def test_unregistered_event_name_returns_none_cleanly(self, tmp_path):
        kernel = Kernel(tmp_path)
        btn_id = kernel.create_ui_entity("Btn", "button")
        btn_proxy = kernel.get_entity_proxy(btn_id)
        # Entity has no 'on_hover' or 'hover' attribute
        assert btn_proxy.trigger("hover") is None
        assert btn_proxy.trigger("on_hover") is None

    def test_trigger_nonexistent_entity_returns_error(self, tmp_path):
        kernel = Kernel(tmp_path)
        err = kernel.trigger_ui_event(999999, "on_click")
        assert isinstance(err, Error)
        assert err.code == RuntimeIDNotFoundOnMemoryError

    def test_trigger_non_entity_resource_returns_error(self, tmp_path):
        kernel = Kernel(tmp_path)
        script_id = kernel.create_script_resource(name="Script", code="x = 1")
        err = kernel.trigger_ui_event(script_id, "on_click")
        assert isinstance(err, Error)
        assert err.code == EntityTypeMismatchError

    def test_trigger_nonexistent_script_storage_id_returns_error(self, tmp_path):
        kernel = Kernel(tmp_path)
        btn_id = kernel.create_ui_entity(
            "Btn",
            "button",
            {"on_click": "<|1|ffffffffffffffffffffffffffffffff|>.on_click"},
        )
        btn_proxy = kernel.get_entity_proxy(btn_id)
        err = btn_proxy.click()
        assert isinstance(err, Error)

    def test_trigger_nonexistent_function_on_script_returns_error(self, tmp_path):
        kernel = Kernel(tmp_path)
        script_id = kernel.create_script_resource(name="EmptyScript", code="val = 42")
        sid_hex = kernel.get_storage_id(script_id).hex()

        btn_id = kernel.create_ui_entity(
            "Btn",
            "button",
            {"on_click": f"<|1|{sid_hex}|>.no_such_function"},
        )
        btn_proxy = kernel.get_entity_proxy(btn_id)
        err = btn_proxy.click()
        assert isinstance(err, Error)
        assert err.code == InvalidResourceDataError
        assert "not found on script proxy" in err.description

    def test_trigger_syntax_error_script_returns_error(self, tmp_path):
        kernel = Kernel(tmp_path)
        script_id = kernel.create_script_resource(name="BrokenScript", code="def broken_syntax :")
        sid_hex = kernel.get_storage_id(script_id).hex()

        btn_id = kernel.create_ui_entity(
            "Btn",
            "button",
            {"on_click": f"<|1|{sid_hex}|>.broken_syntax"},
        )
        btn_proxy = kernel.get_entity_proxy(btn_id)
        err = btn_proxy.click()
        assert isinstance(err, Error)
        assert err.code == InvalidResourceDataError

    def test_trigger_non_callable_attribute_returns_error(self, tmp_path):
        kernel = Kernel(tmp_path)
        script_id = kernel.create_script_resource(name="VarScript", code="PI = 3.14159")
        sid_hex = kernel.get_storage_id(script_id).hex()

        btn_id = kernel.create_ui_entity(
            "Btn",
            "button",
            {"on_click": f"<|1|{sid_hex}|>.PI"},
        )
        btn_proxy = kernel.get_entity_proxy(btn_id)
        err = btn_proxy.click()
        assert isinstance(err, Error)
        assert "not found on script proxy" in err.description or "is not callable" in err.description

    def test_trigger_exception_inside_handler_returns_error_cleanly(self, tmp_path):
        kernel = Kernel(tmp_path)
        script_code = (
            'def _fn_div_zero(entity):\n'
            '    return 1 / 0\n'
        )
        script_id = kernel.create_script_resource(name="CrashScript", code=script_code)
        sid_hex = kernel.get_storage_id(script_id).hex()

        btn_id = kernel.create_ui_entity(
            'CrashBtn',
            'button',
            {'on_click': f'<|1|{sid_hex}|>._fn_div_zero'},
        )
        btn_proxy = kernel.get_entity_proxy(btn_id)
        err = btn_proxy.click()
        assert isinstance(err, Error)
        assert err.code == InvalidResourceDataError
        assert "division by zero" in err.description


class TestUIEndToEndPersistenceRoundtrip:
    """Tests complete disk roundtrip persistence of UI entity tree, mutations, and scripts."""

    def test_ui_hierarchy_mutation_and_disk_reload(self, tmp_path):
        kernel1 = Kernel(tmp_path)

        # 1. Define event handler script
        handler_code = (
            'def _fn_on_submit(entity): # submit\n'
            '    entity.uibutton.label = "Submitted"\n'
            '    entity.state.submitted = True\n'
            '\n'
            'def _fn_on_volume_change(entity, new_val): # volume\n'
            '    entity.uislider.value = new_val\n'
        )
        script_id = kernel1.create_script_resource(name="UIHandlers", code=handler_code)
        assert not isinstance(script_id, Error)
        sid_hex = kernel1.get_storage_id(script_id).hex()

        # 2. Build UI Hierarchy: RootContainer -> (SubmitBtn, VolumeSlider)
        root_id = kernel1.create_ui_entity(
            name="SettingsPanel",
            component_type="container",
            component_props={"layout": "vertical", "gap": 8.0, "padding": 12.0},
        )
        root_proxy = kernel1.get_entity_proxy(root_id)
        root_sid = root_proxy.storage_id

        btn_id = kernel1.create_ui_entity(
            name="SubmitBtn",
            component_type="button",
            component_props={
                "label": "Submit",
                "width": 100.0,
                "height": 30.0,
                "on_click": f"<|1|{sid_hex}|>._fn_on_submit",
            },
            parent_id=root_proxy,
        )
        kernel1.set_component(btn_id, "State", {"submitted": False})
        btn_proxy = kernel1.get_entity_proxy(btn_id)
        btn_sid = btn_proxy.storage_id

        slider_id = kernel1.create_ui_entity(
            name="VolumeSlider",
            component_type="slider",
            component_props={
                "label": "Volume",
                "min": 0.0,
                "max": 100.0,
                "value": 25.0,
                "step": 1.0,
                "on_change": f"<|1|{sid_hex}|>._fn_on_volume_change",
            },
            parent_id=root_proxy,
        )
        slider_proxy = kernel1.get_entity_proxy(slider_id)
        slider_sid = slider_proxy.storage_id

        # 3. Trigger events to mutate state in memory
        btn_proxy.click()
        assert btn_proxy.uibutton.label == "Submitted"
        assert btn_proxy.state.submitted is True

        slider_proxy.trigger("on_change", 75.0)
        assert slider_proxy.uislider.value == 75.0

        # 4. Save dirty resources to disk
        save_err = kernel1.save_dirty_resources()
        assert save_err is None

        # 5. Reload in fresh Kernel session
        kernel2 = Kernel(tmp_path)
        loaded_root_id = kernel2.load_entity(root_sid)
        assert not isinstance(loaded_root_id, Error)

        loaded_root = kernel2.get_entity_proxy(loaded_root_id)
        assert loaded_root.name == "SettingsPanel"
        assert loaded_root.uicontainer.layout == "vertical"
        assert loaded_root.uicontainer.gap == 8.0
        assert loaded_root.uicontainer.padding == 12.0
        assert len(loaded_root.children) == 2

        # Verify child button
        loaded_btn = next((c for c in loaded_root.children if c.name == "SubmitBtn"), None)
        assert loaded_btn is not None
        assert loaded_btn.storage_id == btn_sid
        assert loaded_btn.uibutton.label == "Submitted"
        assert loaded_btn.uibutton.width == 100.0
        assert loaded_btn.uibutton.height == 30.0
        assert loaded_btn.uibutton.on_click == f"<|1|{sid_hex}|>._fn_on_submit"
        assert loaded_btn.state.submitted is True
        assert loaded_btn.parent.id == loaded_root.id

        # Verify child slider
        loaded_slider = next((c for c in loaded_root.children if c.name == "VolumeSlider"), None)
        assert loaded_slider is not None
        assert loaded_slider.storage_id == slider_sid
        assert loaded_slider.uislider.label == "Volume"
        assert loaded_slider.uislider.value == 75.0
        assert loaded_slider.uislider.min == 0.0
        assert loaded_slider.uislider.max == 100.0
        assert loaded_slider.uislider.step == 1.0
        assert loaded_slider.parent.id == loaded_root.id


class TestPlannedUIFeatures:
    """Specifies forward-looking test contracts for planned engine capabilities."""

    @pytest.mark.skip(reason="Planned test: UI event bubbling / propagation up the hierarchy tree")
    def test_planned_ui_event_bubbling_up_hierarchy(self):
        # When a UI event is triggered on a child entity that does not handle it,
        # it should bubble up to parent containers until handled or reaching the root.
        pass

    @pytest.mark.skip(reason="Planned test: Generation-safe RuntimeID recycling in UI event dispatcher")
    def test_planned_generation_safe_ui_handle_invalidation(self):
        # Destroying a UI entity and recycling its RuntimeID slot must prevent stale
        # UI proxies or event listeners from dispatching events to the recycled entity.
        pass

    def test_planned_ui_subtree_spawning_transactional_rollback(self, tmp_path):
        # If an error occurs midway through instantiating a complex UI template subtree,
        # all already-created entities in that subtree should be cleanly rolled back.
        kernel = Kernel(tmp_path)
        existing_id = kernel.create_entity(name="ExistingRoot")
        assert not isinstance(existing_id, Error)

        initial_resources = dict(kernel.resources)
        initial_runtime_ids = dict(kernel.resource_runtime_ids)

        with pytest.raises(RuntimeError, match="Midway UI creation failure"):
            with kernel.transaction():
                panel_id = kernel.create_ui_entity("SettingsPanel", "container")
                assert not isinstance(panel_id, Error)
                btn_id = kernel.create_ui_entity("SubmitBtn", "button", parent_id=panel_id)
                assert not isinstance(btn_id, Error)
                raise RuntimeError("Midway UI creation failure")

        assert kernel.resources == initial_resources
        assert kernel.resource_runtime_ids == initial_runtime_ids
        assert kernel.is_valid_runtime_id(existing_id)
        assert len(kernel.resources) == 1


