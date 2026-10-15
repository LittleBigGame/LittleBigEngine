"""Script compilation, activation and runtime invocation.

These functions operate on the Kernel's authoritative state.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable
import copy

from .logger import logger
from .proxy import ScriptProxy
from .types import (
    StorageID,
    RuntimeID,
    Error,
    RuntimeIDNotFoundOnMemoryError,
    InvalidResourceDataError,
    EntityTypeMismatchError,
    MissingComponentRequirementError,
    BrokenReferenceError,
    Entity,
    Script,
)


def export(uuid_or_name: str | Callable | None = None) -> Any:
    """Decorator to mark a function as an exported LBE function with an associated UUID."""
    if callable(uuid_or_name):
        fn = uuid_or_name
        setattr(fn, "_lbe_export_uuid", getattr(fn, "__name__", ""))
        return fn

    def decorator(fn: Callable) -> Callable:
        uuid_str = uuid_or_name if uuid_or_name is not None else getattr(fn, "__name__", "")
        setattr(fn, "_lbe_export_uuid", str(uuid_str))
        return fn

    return decorator


def _clean_hex_uuid(val: Any) -> str | None:
    if not isinstance(val, (str, bytes)):
        return None
    if isinstance(val, bytes):
        val = val.hex()
    s = str(val).replace("-", "").strip().lower()
    if s.startswith("fn_"):
        s = s[3:]
    elif s.startswith("_fn_"):
        s = s[4:]
    if len(s) in (32, 64):
        try:
            bytes.fromhex(s)
            return s
        except ValueError:
            return None
    return None


def resolve_reference(self, storage_id_hex: str) -> Any | Error:
    """Resolve a universal 128-bit persistent StorageID (hex string) into a callable, proxy, or resource."""
    clean = _clean_hex_uuid(storage_id_hex) or str(storage_id_hex).replace("-", "").strip().lower()

    if hasattr(self, "resolve_function_export"):
        res = self.resolve_function_export(clean)
        if not isinstance(res, Error):
            return res[0]

    try:
        sid = bytes.fromhex(clean)
    except ValueError as ex:
        err = Error(
            message="Invalid storage ID hex",
            description=f"Failed to parse storage ID hex '{storage_id_hex}': {ex}",
            data={"storage_id_hex": storage_id_hex, "error": str(ex)},
            code=InvalidResourceDataError,
        )
        logger.trace("Failed to resolve reference: invalid hex", channel="storage", error=err)
        return err

    rid = self.get_resource_id(sid)
    if isinstance(rid, Error):
        rid = self.load_resource(sid)
        if isinstance(rid, Error):
            return rid

    if self.is_entity(rid):
        return self.get_entity_proxy(rid)

    res = self.get_resource(rid)
    if isinstance(res, Error):
        return res

    if isinstance(res, (dict, MappingProxyType)) and res.get("type") == Script:
        return self.get_script_proxy(rid)

    return res


def resolve_proxy(self, resource_type: int, storage_id_hex: str) -> Any | Error:
    """Resolve a resource by type and hex StorageID into a proxy or loaded resource."""
    try:
        storage_id = bytes.fromhex(storage_id_hex)
    except ValueError as ex:
        err = Error(
            message="Invalid storage ID hex",
            description=f"Failed to parse storage ID hex '{storage_id_hex}': {ex}",
            data={"storage_id_hex": storage_id_hex, "error": str(ex)},
            code=InvalidResourceDataError,
        )
        logger.trace("Failed to resolve proxy: invalid hex", channel="storage", error=err)
        return err

    runtime_id = self.get_resource_id(storage_id)
    if isinstance(runtime_id, Error):
        runtime_id = self.load_resource(storage_id)
        if isinstance(runtime_id, Error):
            return runtime_id

    if resource_type == Entity or resource_type == 0:
        return self.get_entity_proxy(runtime_id)

    if resource_type == Script or resource_type == 1:
        return self.get_script_proxy(runtime_id)

    res = self.get_resource(runtime_id)
    if isinstance(res, Error):
        return res

    actual_type = res.get("type") if isinstance(res, (dict, MappingProxyType)) else None
    if actual_type != resource_type:
        err = Error(
            message="Resource type mismatch",
            description=f"Resource {runtime_id} has type {actual_type}, expected {resource_type}!",
            data={"runtime_id": runtime_id, "actual_type": actual_type, "expected_type": resource_type},
            code=InvalidResourceDataError,
        )
        logger.trace("Failed to resolve proxy: type mismatch", channel="resources", error=err)
        return err
    return res


def execute_script(
    self,
    source: str,
    filename: str = "<lbe_script>",
    extra_globals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a script with preprocessed reference binding and optional extra globals."""
    import types
    from .preprocessor import RuntimeBinder

    module = types.ModuleType(filename)
    module.__dict__["__builtins__"] = __builtins__
    module.__dict__["export"] = export
    if extra_globals:
        module.__dict__.update(extra_globals)
    RuntimeBinder.bind_module(module, source, self, filename=filename)
    return module.__dict__


def _resolve_script_id(self, script_id: RuntimeID | StorageID | str) -> tuple[StorageID, str, RuntimeID] | Error:
    if isinstance(script_id, int):
        runtime_id = script_id
        sid = self.get_storage_id(runtime_id)
        if isinstance(sid, Error):
            return sid
        return sid, sid.hex(), runtime_id
    elif isinstance(script_id, bytes):
        sid = script_id
        runtime_id = self.get_resource_id(sid)
        if isinstance(runtime_id, Error):
            runtime_id = self.load_resource(sid)
            if isinstance(runtime_id, Error):
                return runtime_id
        return sid, sid.hex(), runtime_id
    elif isinstance(script_id, str):
        try:
            sid = bytes.fromhex(script_id)
        except ValueError as ex:
            return Error(
                message="Invalid script storage ID",
                description=f"Cannot parse hex string '{script_id}': {ex}",
                data={"script_id": script_id, "error": str(ex)},
                code=InvalidResourceDataError,
            )
        runtime_id = self.get_resource_id(sid)
        if isinstance(runtime_id, Error):
            runtime_id = self.load_resource(sid)
            if isinstance(runtime_id, Error):
                return runtime_id
        return sid, sid.hex(), runtime_id
    return Error(
        message="Invalid script ID type",
        description=f"Expected RuntimeID, StorageID, or hex str, got {type(script_id).__name__}!",
        data={"script_id": script_id},
        code=InvalidResourceDataError,
    )


def create_script_resource(
    self,
    name: str = "Script",
    source_path: str = "",
    code: str = "",
    requires: list[str] | None = None,
    storage_id: StorageID | None = None,
    immediate_save: bool = False,
) -> RuntimeID | Error:
    """Create a new Script resource."""
    from .preprocessor import extract_script_symbols

    symbols = {}
    if code:
        symbols = extract_script_symbols(code)
    elif source_path:
        try:
            s_file = Path(source_path)
            if not s_file.is_absolute():
                s_file = self.folder_location / s_file
            if s_file.exists():
                symbols = extract_script_symbols(s_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    script_data = {
        "name": name,
        "source_path": source_path,
        "code": code,
        "requires": list(requires) if requires is not None else [],
        "symbols": symbols,
    }
    return self.create_resource(
        resource_type=Script,
        resource_data=script_data,
        name=name,
        storage_id=storage_id,
        immediate_save=immediate_save,
    )


def get_script_proxy(self, script_id: RuntimeID) -> ScriptProxy | Error:
    """Get a ScriptProxy for a script resource in memory."""
    if not self.is_valid_runtime_id(script_id):
        err = Error(
            message="Resource not found",
            description=f"Runtime ID {script_id} is invalid or stale (referencing a deleted resource)!",
            data={"script_id": script_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to get script proxy: invalid or stale", channel="resources", error=err, entity_id=script_id)
        return err

    resolved_id = self._resolve_handle(script_id)
    if resolved_id not in self.resources:
        err = Error(
            message="Resource not found",
            description=f"RuntimeID {script_id} was not found in memory!",
            data={"script_id": script_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to get script proxy: resource not found", channel="resources", error=err, entity_id=script_id)
        return err

    res = self.resources[resolved_id]
    if res.get("type") != Script:
        err = Error(
            message="Resource is not a script",
            description=f"RuntimeID {script_id} has type {res.get('type')}, expected Script ({Script})!",
            data={"script_id": script_id, "type": res.get("type")},
            code=InvalidResourceDataError,
        )
        logger.trace("Failed to get script proxy: not a script", channel="resources", error=err, entity_id=script_id)
        return err

    return ScriptProxy(self, resolved_id)


def _scan_module_exports(self, script_id: RuntimeID, namespace: dict[str, Any]) -> None:
    if not hasattr(self, "function_exports"):
        self.function_exports = {}
    sid = self.get_storage_id(script_id)
    if isinstance(sid, Error):
        return

    exports_map = namespace.get("__exports__")
    if isinstance(exports_map, dict):
        for exp_k, exp_v in exports_map.items():
            clean_k = _clean_hex_uuid(exp_k)
            fn_sym = exp_v if isinstance(exp_v, str) else getattr(exp_v, "__name__", "")
            if clean_k and fn_sym:
                self.function_exports[clean_k] = (sid, fn_sym)

    for func_name, obj in namespace.items():
        if callable(obj):
            export_uuid = getattr(obj, "_lbe_export_uuid", None)
            if export_uuid is not None:
                clean_uuid = _clean_hex_uuid(export_uuid)
                if clean_uuid:
                    self.function_exports[clean_uuid] = (sid, func_name)
                else:
                    raw = str(export_uuid).strip().lower()
                    if raw:
                        self.function_exports[raw] = (sid, func_name)
            else:
                clean_name = _clean_hex_uuid(func_name)
                if clean_name:
                    self.function_exports[clean_name] = (sid, func_name)


def resolve_function_export(self, fn_uuid_hex: str | bytes) -> tuple[Callable, RuntimeID] | Error:
    """Resolve an exported function UUID into (callable, script_runtime_id)."""
    if not hasattr(self, "function_exports"):
        self.function_exports = {}

    if isinstance(fn_uuid_hex, bytes):
        key = fn_uuid_hex.hex().lower()
    else:
        clean = _clean_hex_uuid(fn_uuid_hex)
        key = clean if clean is not None else str(fn_uuid_hex).strip().lower()

    if key not in self.function_exports:
        for rid, res in list(self.resources.items()):
            if isinstance(res, (dict, MappingProxyType)) and res.get("type") == Script:
                mod = self.get_script_module(rid)
                if not isinstance(mod, Error):
                    _scan_module_exports(self, rid, mod)
                if key in self.function_exports:
                    break

    if key not in self.function_exports:
        return Error(
            message=f"Exported function UUID '{fn_uuid_hex}' not found",
            description=f"Exported function UUID '{fn_uuid_hex}' not found",
            data={"fn_uuid_hex": fn_uuid_hex},
            code=BrokenReferenceError,
        )

    script_sid, _ = self.function_exports[key]
    mod = self.get_script_module(script_sid)
    if isinstance(mod, Error):
        return mod

    # Re-read function_exports after get_script_module in case the module was recompiled/renamed
    script_sid, fn_name = self.function_exports.get(key, (script_sid, ""))

    func = mod.get(fn_name) if isinstance(mod, dict) else getattr(mod, fn_name, None)
    if not callable(func):
        return Error(
            message="Exported function not callable",
            description=f"Exported function '{fn_name}' in script is not callable or not found",
            data={"fn_uuid_hex": fn_uuid_hex, "script_sid": script_sid, "fn_name": fn_name},
            code=BrokenReferenceError,
        )

    script_rid = self.get_resource_id(script_sid)
    if isinstance(script_rid, Error):
        return script_rid

    return func, script_rid


def get_script_module(self, script_id: RuntimeID | StorageID | str) -> dict[str, Any] | Error:
    """Prevent recursive activation of mutually dependent script modules."""
    resolved = self._resolve_script_id(script_id)
    if isinstance(resolved, Error):
        return resolved
    _sid, _sid_hex, runtime_id = resolved
    if runtime_id in self._scripts_activating:
        return Error("Script module compilation error", "Cyclic top-level script activation",
                     {"script_id": runtime_id}, InvalidResourceDataError)
    self._scripts_activating.add(runtime_id)
    try:
        return _activate_script_module(self, runtime_id)
    finally:
        self._scripts_activating.discard(runtime_id)


def _activate_script_module(self, script_id: RuntimeID) -> dict[str, Any] | Error:
    """Activate validated source, retaining the last working module on reload failure."""
    if not self.is_valid_runtime_id(script_id):
        return Error("Resource not found", "Script handle is invalid or stale", {"script_id": script_id},
                     RuntimeIDNotFoundOnMemoryError)
    script_id = self._resolve_handle(script_id)
    resource = self.resources[script_id]
    if resource.get("type") != Script:
        return Error("Resource is not a script", "Expected a Script resource", {"script_id": script_id},
                     InvalidResourceDataError)

    data = resource.get("data", {})
    code = data.get("code", "")
    source_path = data.get("source_path", "")
    file_mtime = None
    snapshot = None
    fingerprint = (source_path, code, file_mtime)

    def reject(error):
        if snapshot is not None:
            self._restore_loaded_state(snapshot)
        self._script_reload_errors[script_id] = error
        self._script_failed_sources[script_id] = fingerprint
        logger.error("Script activation rejected; previous module retained", channel="scripts",
                     error=error, entity_id=script_id)
        return self._last_good_script_modules.get(script_id, error)

    if not code and source_path:
        path = Path(source_path)
        if not path.is_absolute():
            path = self.folder_location / path
        try:
            file_mtime = path.stat().st_mtime_ns
            cached = self._script_module_cache.get(script_id)
            if cached is not None and self._script_mtime_cache.get(script_id) == file_mtime:
                self._script_reload_errors.pop(script_id, None)
                self._script_failed_sources.pop(script_id, None)
                _scan_module_exports(self, script_id, cached[1])
                return cached[1]
            code = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as ex:
            return reject(Error("Failed to read script file", str(ex),
                                {"script_id": script_id, "source_path": str(path)}, InvalidResourceDataError))
    else:
        cached = self._script_module_cache.get(script_id)
        if cached is not None and cached[0] == code:
            self._script_reload_errors.pop(script_id, None)
            self._script_failed_sources.pop(script_id, None)
            _scan_module_exports(self, script_id, cached[1])
            return cached[1]

    fingerprint = (source_path, code, file_mtime)
    if self._script_failed_sources.get(script_id) == fingerprint:
        return self._last_good_script_modules.get(script_id, self._script_reload_errors[script_id])

    from .preprocessor import ReferencePreprocessor, extract_script_symbols
    filename = source_path or f"<script_{script_id}>"
    try:
        transformed_code, dependencies = ReferencePreprocessor.preprocess(code, filename=filename)
        code_object = compile(transformed_code, filename, "exec")
        symbols = extract_script_symbols(code)
    except Exception as ex:
        error = ex if isinstance(ex, Error) else Error(
            "Script module compilation error", str(ex), {"script_id": script_id, "filename": filename},
            InvalidResourceDataError)
        return reject(error)

    snapshot = self._snapshot_loaded_state()
    namespace = {"__builtins__": __builtins__, "kernel": self, "export": export}
    try:
        for resource_type, storage_id_hex in dependencies:
            proxy = self.resolve_proxy(resource_type, storage_id_hex)
            if isinstance(proxy, Error):
                return reject(proxy)
            namespace[f"_{resource_type}_{storage_id_hex}"] = proxy
        exec(code_object, namespace)
    except (Exception, SystemExit) as ex:
        error = ex if isinstance(ex, Error) else Error(
            "Script module compilation error", str(ex), {"script_id": script_id, "filename": filename},
            InvalidResourceDataError)
        return reject(error)

    self._script_cache[script_id] = (code, code_object, dependencies)
    self._script_module_cache[script_id] = (code, namespace)
    self._last_good_script_modules[script_id] = namespace
    self._script_reload_errors.pop(script_id, None)
    self._script_failed_sources.pop(script_id, None)
    if file_mtime is not None:
        self._script_mtime_cache[script_id] = file_mtime
    self._method_sig_cache = {key: value for key, value in self._method_sig_cache.items() if key[0] != script_id}
    if data.get("symbols") != symbols:
        self.resources[script_id]["data"]["symbols"] = symbols
        self.mark_dirty(script_id)
    _scan_module_exports(self, script_id, namespace)
    return namespace


def get_script_callable(self, script_id: RuntimeID, func_name: str) -> Callable | None | Error:
    """Retrieve a callable function from a script resource by function name."""
    mod_globals = self.get_script_module(script_id)
    if isinstance(mod_globals, Error):
        return mod_globals
    func = mod_globals.get(func_name)
    if callable(func):
        return func
    return None


def update_script_source(self, script_id: RuntimeID, source: str) -> None | Error:
    """Replace inline or external source after syntax validation, without executing it."""
    proxy = self.get_script_proxy(script_id)
    if isinstance(proxy, Error):
        return proxy
    script_id = self._resolve_handle(script_id)
    from .preprocessor import ReferencePreprocessor, extract_script_symbols
    try:
        transformed, _ = ReferencePreprocessor.preprocess(source)
        compile(transformed, "<script_edit>", "exec")
        symbols = extract_script_symbols(source)
    except Exception as ex:
        return Error("Invalid script source", str(ex), {"script_id": script_id}, InvalidResourceDataError)

    data = copy.deepcopy(self.resources[script_id]["data"])
    source_path = data.get("source_path", "")
    external = bool(source_path and not data.get("code"))
    data["code"] = "" if external else source
    data["symbols"] = symbols
    temp_path = None
    try:
        with self.transaction():
            result = self.mutate_resource(script_id, data)
            if isinstance(result, Error):
                raise result
            if external:
                path = Path(source_path)
                if not path.is_absolute():
                    path = self.folder_location / path
                temp_path = path.with_name(path.name + ".lbe.tmp")
                temp_path.write_text(source, encoding="utf-8")
                temp_path.replace(path)
    except (Error, OSError, UnicodeError) as ex:
        return ex if isinstance(ex, Error) else Error(
            "Failed to write script source", str(ex), {"script_id": script_id}, InvalidResourceDataError)
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError as ex:
                logger.warn("Could not remove script temporary file", channel="scripts", data={"error": str(ex)})
    return None


def attach_script(self, entity_id: RuntimeID, script_id: RuntimeID | StorageID | str) -> None | Error:
    """Attach a script resource to an Entity, storing its canonical StorageID hex."""
    if entity_id not in self.resources:
        err = Error(
            message="Entity not found",
            description=f"RuntimeID {entity_id} was not found in memory!",
            data={"entity_id": entity_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to attach script: entity not found", channel="entities", error=err, entity_id=entity_id)
        return err

    res = self.resources[entity_id]
    if res.get("type") != Entity:
        err = Error(
            message="Resource is not an entity",
            description=f"RuntimeID {entity_id} has type {res.get('type')}, expected Entity ({Entity})!",
            data={"entity_id": entity_id, "type": res.get("type")},
            code=EntityTypeMismatchError,
        )
        logger.trace("Failed to attach script: not an entity", channel="entities", error=err, entity_id=entity_id)
        return err

    resolved = self._resolve_script_id(script_id)
    if isinstance(resolved, Error):
        return resolved
    _, sid_hex, script_rid = resolved

    script_res = self.resources.get(script_rid)
    if not script_res or script_res.get("type") != Script:
        err = Error(
            message="Resource is not a script",
            description=f"Resource {script_rid} has type {script_res.get('type') if script_res else None}, expected Script ({Script})!",
            data={"script_id": script_id, "resolved_id": script_rid},
            code=InvalidResourceDataError,
        )
        logger.trace("Failed to attach script: target is not a script", channel="entities", error=err, entity_id=entity_id)
        return err

    scripts = res.setdefault("data", {}).setdefault("scripts", [])
    if sid_hex not in scripts:
        before = copy.deepcopy(scripts)
        scripts.append(sid_hex)
        self.dirty_runtime_ids.add(entity_id)
        logger.trace(
            f"Attached script '{sid_hex[:8]}...' to Entity {entity_id}",
            channel="entities",
            entity_id=entity_id,
            action="attach_script",
            before=before,
            after=copy.deepcopy(scripts),
            data={"script_storage_id": sid_hex},
        )
    return None


def detach_script(self, entity_id: RuntimeID, script_id: RuntimeID | StorageID | str) -> None | Error:
    """Detach a script from an Entity."""
    if entity_id not in self.resources:
        err = Error(
            message="Entity not found",
            description=f"RuntimeID {entity_id} was not found in memory!",
            data={"entity_id": entity_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to detach script: entity not found", channel="entities", error=err, entity_id=entity_id)
        return err

    res = self.resources[entity_id]
    if res.get("type") != Entity:
        err = Error(
            message="Resource is not an entity",
            description=f"RuntimeID {entity_id} has type {res.get('type')}, expected Entity ({Entity})!",
            data={"entity_id": entity_id, "type": res.get("type")},
            code=EntityTypeMismatchError,
        )
        logger.trace("Failed to detach script: not an entity", channel="entities", error=err, entity_id=entity_id)
        return err

    resolved = self._resolve_script_id(script_id)
    if isinstance(resolved, Error):
        sid_hex = script_id if isinstance(script_id, str) else None
        if not sid_hex:
            return resolved
    else:
        _, sid_hex, _ = resolved

    scripts = res.get("data", {}).get("scripts", [])
    if sid_hex in scripts:
        before = copy.deepcopy(scripts)
        scripts.remove(sid_hex)
        self.dirty_runtime_ids.add(entity_id)
        logger.trace(
            f"Detached script '{sid_hex[:8]}...' from Entity {entity_id}",
            channel="entities",
            entity_id=entity_id,
            action="detach_script",
            before=before,
            after=copy.deepcopy(scripts),
            data={"script_storage_id": sid_hex},
        )
    return None


def get_entity_scripts(self, entity_id: RuntimeID) -> list[RuntimeID]:
    """Get RuntimeIDs of all scripts attached to an Entity."""
    if entity_id not in self.resources:
        return []

    res = self.resources[entity_id]
    if res.get("type") != Entity:
        return []

    script_hexes = res.get("data", {}).get("scripts", [])
    runtime_ids: list[RuntimeID] = []
    for sid_hex in script_hexes:
        try:
            sid = bytes.fromhex(sid_hex)
        except (ValueError, TypeError):
            continue
        rid = self.get_resource_id(sid)
        if isinstance(rid, Error):
            rid = self.load_resource(sid)
            if isinstance(rid, Error):
                continue
        runtime_ids.append(rid)
    return runtime_ids


def run_entity_scripts(
    self,
    entity_id: RuntimeID,
    dt: float = 0.0,
    method_name: str = "update",
) -> None | Error:
    """Execute all scripts attached to an Entity with self context."""
    if entity_id not in self.resources:
        err = Error(
            message="Entity not found",
            description=f"RuntimeID {entity_id} was not found in memory!",
            data={"entity_id": entity_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to run entity scripts: entity not found", channel="entities", error=err, entity_id=entity_id)
        return err

    res = self.resources[entity_id]
    if res.get("type") != Entity:
        err = Error(
            message="Resource is not an entity",
            description=f"RuntimeID {entity_id} has type {res.get('type')}, expected Entity ({Entity})!",
            data={"entity_id": entity_id, "type": res.get("type")},
            code=EntityTypeMismatchError,
        )
        logger.trace("Failed to run entity scripts: not an entity", channel="entities", error=err, entity_id=entity_id)
        return err

    entity_proxy = self.get_entity_proxy(entity_id)
    if isinstance(entity_proxy, Error):
        return entity_proxy

    script_rids = self.get_entity_scripts(entity_id)
    for s_rid in script_rids:
        s_res = self.get_resource(s_rid)
        if isinstance(s_res, Error) or not isinstance(s_res, (dict, MappingProxyType)):
            continue

        s_data = s_res.get("data", {})
        requires = s_data.get("requires", [])
        for req_comp in requires:
            if not entity_proxy.has(req_comp):
                err = Error(
                    message="Missing component requirement",
                    description=f"Entity {entity_id} missing required component '{req_comp}' for script '{s_res.get('name', s_rid)}'!",
                    data={"entity_id": entity_id, "required_component": req_comp, "script_id": s_rid},
                    code=MissingComponentRequirementError,
                )
                logger.trace(f"Script run failed: missing component requirement '{req_comp}'", channel="entities", error=err, entity_id=entity_id)
                return err

        mod_globals = self.get_script_module(s_rid)
        if isinstance(mod_globals, Error):
            return mod_globals

        func = mod_globals.get(method_name)
        if callable(func):
            sig_key = (s_rid, method_name)
            if sig_key not in self._method_sig_cache:
                try:
                    import inspect
                    sig = inspect.signature(func)
                    params = list(sig.parameters.values())
                    param_count = len(params)
                    first_param_name = params[0].name if params else ""
                    self._method_sig_cache[sig_key] = (param_count, first_param_name)
                except Exception:
                    self._method_sig_cache[sig_key] = (1, "dt")
            param_count, first_param_name = self._method_sig_cache[sig_key]

            mod_globals["self"] = entity_proxy
            mod_globals["dt"] = dt

            try:
                if param_count >= 2:
                    func(entity_proxy, dt)
                elif param_count == 1:
                    if first_param_name in ("self", "entity", "target", "e", "proxy"):
                        func(entity_proxy)
                    else:
                        func(dt)
                else:
                    func()
            except (Exception, SystemExit) as ex:
                err = Error(
                    message="Script method execution error",
                    description=f"Script '{s_res.get('name', s_rid)}' method '{method_name}' raised an error: {ex}",
                    data={"entity_id": entity_id, "script_id": s_rid, "method": method_name, "error": str(ex)},
                    code=InvalidResourceDataError,
                )
                logger.trace(f"Script method '{method_name}' failed", channel="entities", error=err, entity_id=entity_id)
                return err
    return None


def tick(self, dt: float = 0.0) -> None | list[Error]:
    """Iterate over all active entities with attached scripts and run update(dt)."""
    errors: list[Error] = []
    for entity_id in list(self.resources.keys()):
        if self.is_entity(entity_id):
            scripts = self.resources[entity_id].get("data", {}).get("scripts", [])
            if scripts:
                err = self.run_entity_scripts(entity_id, dt=dt, method_name="update")
                if isinstance(err, Error):
                    errors.append(err)
    return errors if errors else None

