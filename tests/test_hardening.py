"""Regression coverage for the remaining robustness and readability phases."""

import copy
import os
from pathlib import Path

import pytest

from LBE import Error, Kernel
from LBE.logger import INFO, TRACE, Logger
from editor import EditorSession
from editor.pills import rename_script_function_display_name


def test_failed_reload_retains_working_module_and_recovers(tmp_path):
    kernel = Kernel(tmp_path)
    script = kernel.create_script_resource(code="def _fn_value(): return 7")
    previous = kernel.get_script_module(script)
    data = copy.deepcopy(kernel.resources[script]["data"])
    data["code"] = "def broken(:"
    assert kernel.mutate_resource(script, data) is None
    assert kernel.get_script_module(script) is previous
    assert kernel.get_script_module(script)["_fn_value"]() == 7
    assert script in kernel.get_diagnostics()["script_reload_errors"]
    data["code"] = "def _fn_value(): return 9"
    assert kernel.mutate_resource(script, data) is None
    assert kernel.get_script_module(script)["_fn_value"]() == 9
    assert kernel.get_diagnostics()["script_reload_errors"] == {}


def test_failed_activation_rolls_back_kernel_side_effects(tmp_path):
    kernel = Kernel(tmp_path)
    entity = kernel.create_entity(components={"Health": {"value": 10}})
    script = kernel.create_script_resource(code="value = 1")
    previous = kernel.get_script_module(script)
    data = copy.deepcopy(kernel.resources[script]["data"])
    data["code"] = f"kernel.get_entity_proxy({entity}).health.value = 0\nraise RuntimeError('bad activation')"
    kernel.mutate_resource(script, data)
    assert kernel.get_script_module(script) is previous
    assert kernel.get_component(entity, "Health")["value"] == 10


def test_missing_external_source_preserves_previous_module(tmp_path):
    source = tmp_path / "logic.py"
    source.write_text("value = 42", encoding="utf-8")
    kernel = Kernel(tmp_path)
    script = kernel.create_script_resource(source_path="logic.py")
    previous = kernel.get_script_module(script)
    source.unlink()
    assert kernel.get_script_module(script) is previous
    assert script in kernel.get_diagnostics()["script_reload_errors"]


def test_external_function_rename_preserves_source_mode(tmp_path):
    source = tmp_path / "logic.py"
    source.write_text("def _fn_value(): # OldName\n    return 4\n", encoding="utf-8")
    kernel = Kernel(tmp_path)
    script = kernel.create_script_resource(source_path="logic.py")
    sid = kernel.get_storage_id(script).hex()
    assert rename_script_function_display_name(kernel, sid, "_fn_value", "NewName") is None
    assert kernel.resources[script]["data"]["code"] == ""
    assert "NewName" in source.read_text(encoding="utf-8")
    assert kernel.get_script_module(script)["_fn_value"]() == 4


def test_aborted_transaction_handles_never_address_later_entities(tmp_path):
    kernel = Kernel(tmp_path)
    with pytest.raises(RuntimeError):
        with kernel.transaction():
            aborted = kernel.create_entity()
            raise RuntimeError("abort")
    replacement = kernel.create_entity()
    assert replacement != aborted
    assert not kernel.is_valid_runtime_id(aborted)


def test_detached_component_views_fail_instead_of_losing_writes(tmp_path):
    kernel = Kernel(tmp_path)
    entity = kernel.create_entity(components={"Stats": {"values": [1]}})
    old_view = kernel.get_component(entity, "Stats")
    old_list = old_view["values"]
    assert kernel.set_component(entity, "Stats", {"values": [2]}) is None
    with pytest.raises(AttributeError, match="detached"):
        old_list.append(3)
    with pytest.raises(AttributeError, match="detached"):
        old_view["value"] = 4
    assert kernel.get_component(entity, "Stats")["values"] == [2]


def test_editor_listener_failure_is_reported_and_other_listeners_continue(tmp_path):
    session = EditorSession(Kernel(tmp_path))
    delivered = []

    def fail():
        raise ValueError("Broken panel")

    session.subscribe_state_changed(fail)
    session.subscribe_state_changed(lambda: delivered.append(True))
    session.refresh()
    assert delivered == [True]
    assert session.errors[-1].description == "Broken panel"


def test_editor_exposes_save_failures(tmp_path, monkeypatch):
    session = EditorSession(Kernel(tmp_path))
    error = Error("Save failed", "Disk is full", {}, 9)
    monkeypatch.setattr(session.kernel, "save_dirty_resources", lambda: [error])
    assert session.save_dirty_resources() == [error]
    assert session.errors[-1] is error


def test_logger_filters_before_allocating_and_bounds_history(capsys):
    log = Logger(min_level=INFO, max_records=2)
    assert log.trace("filtered") is None
    assert log.records == []
    for index in range(3):
        log.info(str(index))
    assert [record.message for record in log.records] == ["1", "2"]
    assert "filtered" not in capsys.readouterr().out
    assert not log.is_enabled(TRACE)


def test_batch_save_rolls_back_earlier_files_when_later_publish_fails(tmp_path, monkeypatch):
    kernel = Kernel(tmp_path)
    first = kernel.create_entity(components={"Health": {"value": 1}})
    second = kernel.create_entity(components={"Health": {"value": 2}})
    assert kernel.save_dirty_resources() is None
    originals = {path: path.read_bytes() for path in tmp_path.glob("*.json")}
    kernel.set_component(first, "Health", {"value": 100})
    kernel.set_component(second, "Health", {"value": 200})
    real_replace = os.replace
    published = []

    def fail_second(source, target):
        if Path(target).parent == tmp_path and Path(source).parent.name.startswith(".lbe-save-"):
            published.append(target)
            if len(published) == 2:
                raise OSError("Injected second publish failure")
        return real_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_second)
    assert isinstance(kernel.save_dirty_resources(), list)
    assert {path: path.read_bytes() for path in tmp_path.glob("*.json")} == originals
    assert kernel.dirty_runtime_ids == {first, second}
    assert not list(tmp_path.glob(".lbe-save-*"))
