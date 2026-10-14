"""Comprehensive independent tests for ReferencePreprocessor and RuntimeBinder.

Derives tests from observable user requirements and kernel contracts:
1. Syntax Transformation & Line Preservation (<|0|hex|> -> _0_hex, 1:1 line numbers).
2. Comments & Strings Isolation (comments, quotes, raw strings, f-strings untransformed).
3. Syntax Error Cases (invalid hex length, unclosed bracket, non-hex chars, traceback line accuracy).
4. Dependency Extraction (accurate set of (res_type, storage_id_hex), ignoring strings/comments).
5. Runtime Execution & Proxy Binding (end-to-end script execution, mutation, dirty tracking, persistence).
"""

import time
import traceback
import pytest

from LBE import (
    EntityProxy,
    Error,
    Kernel,
    LBEReferenceSyntaxError,
    ReferencePreprocessor,
)


VALID_HEX_32 = "3f4a1234567890abcdef1234567890ab"
VALID_HEX_64 = "3f4a1234567890abcdef1234567890ab3f4a1234567890abcdef1234567890ab"


class TestSyntaxTransformationAndLinePreservation:
    """Verifies that reference syntax transforms into legal identifiers while maintaining exact lines."""

    def test_syntax_transformation_to_identifier(self):
        source = f"player = <|0|{VALID_HEX_32}|>"
        transformed, deps = ReferencePreprocessor.preprocess(source)

        expected_var = f"_0_{VALID_HEX_32.lower()}"
        assert transformed == f"player = {expected_var}"
        assert deps == {(0, VALID_HEX_32.lower())}

    def test_mixed_case_hex_normalized_to_lowercase(self):
        mixed_hex = "3F4A1234567890ABCDEF1234567890AB"
        source = f"target = <|0|{mixed_hex}|>"
        transformed, deps = ReferencePreprocessor.preprocess(source)

        expected_var = f"_0_{mixed_hex.lower()}"
        assert transformed == f"target = {expected_var}"
        assert deps == {(0, mixed_hex.lower())}

    def test_64_character_hex_support(self):
        source = f"asset = <|1|{VALID_HEX_64}|>"
        transformed, deps = ReferencePreprocessor.preprocess(source)

        expected_var = f"_1_{VALID_HEX_64.lower()}"
        assert transformed == f"asset = {expected_var}"
        assert deps == {(1, VALID_HEX_64.lower())}

    def test_exact_line_preservation_and_traceback_fidelity(self):
        source = (
            f"# Header comment\n"
            f"x = <|0|{VALID_HEX_32}|>\n"
            f"y = 10\n"
            f"z = 1 / 0\n"
            f"w = <|0|{VALID_HEX_32}|>\n"
        )
        transformed, deps = ReferencePreprocessor.preprocess(source, filename="faulty_script.py")

        # Line count must match 1:1
        assert transformed.count("\n") == source.count("\n")
        assert len(transformed.splitlines()) == len(source.splitlines())

        # When executed, traceback line number must match exactly
        with pytest.raises(ZeroDivisionError) as exc_info:
            exec(compile(transformed, "faulty_script.py", "exec"), {"_0_" + VALID_HEX_32: None})

        tb = traceback.extract_tb(exc_info.tb)
        faulty_frames = [f for f in tb if f.filename == "faulty_script.py"]
        assert len(faulty_frames) == 1
        assert faulty_frames[0].lineno == 4  # line 4 is 'z = 1 / 0'


class TestCommentsAndStringsIsolation:
    """Verifies that reference brackets inside comments and string literals are preserved untouched."""

    def test_reference_inside_comments_not_transformed(self):
        source = (
            f"# This is a comment with <|0|{VALID_HEX_32}|>\n"
            f"val = 42 # inline comment <|1|{VALID_HEX_32}|>\n"
        )
        transformed, deps = ReferencePreprocessor.preprocess(source)

        assert transformed == source
        assert deps == set()

    def test_reference_inside_single_and_double_quotes_not_transformed(self):
        source = (
            f'msg1 = "<|0|{VALID_HEX_32}|>"\n'
            f"msg2 = '<|0|{VALID_HEX_32}|>'\n"
        )
        transformed, deps = ReferencePreprocessor.preprocess(source)

        assert transformed == source
        assert deps == set()

    def test_reference_inside_triple_quotes_not_transformed(self):
        source = (
            f'doc1 = """\nMulti-line docstring with <|0|{VALID_HEX_32}|>\n"""\n'
            f"doc2 = '''\nSingle-quoted doc with <|0|{VALID_HEX_32}|>\n'''\n"
        )
        transformed, deps = ReferencePreprocessor.preprocess(source)

        assert transformed == source
        assert deps == set()

    def test_reference_inside_raw_and_f_strings_not_transformed(self):
        source = (
            f'raw_s = r"<|0|{VALID_HEX_32}|>"\n'
            f'f_s = f"<|0|{VALID_HEX_32}|>"\n'
            f"raw_single = r'<|0|{VALID_HEX_32}|>'\n"
            f"f_single = f'<|0|{VALID_HEX_32}|>'\n"
        )
        transformed, deps = ReferencePreprocessor.preprocess(source)

        assert transformed == source
        assert deps == set()

    def test_mixed_code_with_real_ref_and_commented_ref(self):
        source = (
            f"# Target: <|0|{VALID_HEX_32}|>\n"
            f"real_target = <|0|{VALID_HEX_32}|>\n"
            f'note = "Do not replace <|0|{VALID_HEX_32}|>"\n'
        )
        transformed, deps = ReferencePreprocessor.preprocess(source)

        expected = (
            f"# Target: <|0|{VALID_HEX_32}|>\n"
            f"real_target = _0_{VALID_HEX_32}\n"
            f'note = "Do not replace <|0|{VALID_HEX_32}|>"\n'
        )
        assert transformed == expected
        assert deps == {(0, VALID_HEX_32)}

    def test_redos_resistance_unclosed_quotes_with_backslashes(self):
        cases = [
            'x = "' + '\\' * 50,
            "x = '" + '\\' * 50,
            'x = """' + '\\' * 50,
            "x = '''" + '\\' * 50,
        ]
        for src in cases:
            start = time.perf_counter()
            ReferencePreprocessor.preprocess(src)
            duration = time.perf_counter() - start
            assert duration < 0.1, f"Regex evaluation took too long ({duration:.4f}s), possible catastrophic backtracking!"


class TestSyntaxErrorCases:
    """Verifies that invalid or malformed reference syntaxes raise LBEReferenceSyntaxError."""

    def test_invalid_hex_length_raises_syntax_error(self):
        # 10 chars instead of 32 or 64
        source = "<|0|0123456789|>"
        with pytest.raises(LBEReferenceSyntaxError) as exc_info:
            ReferencePreprocessor.preprocess(source, filename="test.py")
        assert "Invalid reference storage ID length" in str(exc_info.value)
        assert exc_info.value.lineno == 1

        # 30 chars
        source_30 = "<|0|" + "a" * 30 + "|>"
        with pytest.raises(LBEReferenceSyntaxError):
            ReferencePreprocessor.preprocess(source_30)

    def test_unclosed_bracket_raises_syntax_error(self):
        source = f"x = <|0|{VALID_HEX_32}\ny = 20"
        with pytest.raises(LBEReferenceSyntaxError) as exc_info:
            ReferencePreprocessor.preprocess(source, filename="unclosed.py")
        assert "Malformed" in str(exc_info.value)
        assert exc_info.value.lineno == 1

    def test_non_hex_characters_raise_syntax_error(self):
        # Contains 'z'
        bad_hex = "3f4a1234567890abcdef1234567890zz"
        source = f"x = <|0|{bad_hex}|>"
        with pytest.raises(LBEReferenceSyntaxError) as exc_info:
            ReferencePreprocessor.preprocess(source)
        assert "Malformed" in str(exc_info.value)

    def test_non_integer_resource_type_raises_syntax_error(self):
        source = f"x = <|Entity|{VALID_HEX_32}|>"
        with pytest.raises(LBEReferenceSyntaxError) as exc_info:
            ReferencePreprocessor.preprocess(source)
        assert "Malformed" in str(exc_info.value)


class TestDependencyExtraction:
    """Verifies precise extraction of engine resource dependencies from source code."""

    def test_multiple_unique_dependencies_extracted(self):
        hex1 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        hex2 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        source = (
            f"e1 = <|0|{hex1}|>\n"
            f"e2 = <|0|{hex2}|>\n"
            f"c1 = <|1|{hex1}|>\n"
        )
        _, deps = ReferencePreprocessor.preprocess(source)
        assert deps == {
            (0, hex1),
            (0, hex2),
            (1, hex1),
        }

    def test_duplicate_references_deduplicated_in_set(self):
        source = (
            f"e1 = <|0|{VALID_HEX_32}|>\n"
            f"e2 = <|0|{VALID_HEX_32}|>\n"
        )
        _, deps = ReferencePreprocessor.preprocess(source)
        assert len(deps) == 1
        assert deps == {(0, VALID_HEX_32.lower())}


class TestRuntimeExecutionAndProxyBinding:
    """Verifies Kernel script execution, dynamic proxy resolution, mutation, and persistence."""

    def test_execute_script_with_reference_and_mutation(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity_id = kernel.create_entity(name="Hero", components={"Health": {"current": 100, "max": 100}})
        assert not isinstance(entity_id, Error)
        storage_id = kernel.get_storage_id(entity_id)
        assert isinstance(storage_id, bytes)
        storage_id_hex = storage_id.hex()

        # Save to disk first so state is clean
        assert kernel.save_dirty_resources() is None
        assert not kernel.is_dirty(entity_id)

        # Execute script that references the entity via bracket syntax and mutates it
        script_source = (
            f"target = <|0|{storage_id_hex}|>\n"
            f"target.health.current -= 30\n"
            f"result = target.health.current\n"
        )

        env = kernel.execute_script(script_source, filename="hero_logic.py")

        # Verify execution environment
        assert env["result"] == 70
        assert isinstance(env["target"], EntityProxy)
        assert env["target"].id == entity_id

        # Verify Kernel state is marked dirty
        assert kernel.is_dirty(entity_id)

        # Save dirty resources
        assert kernel.save_dirty_resources() is None
        assert not kernel.is_dirty(entity_id)

        # Reload in a completely fresh Kernel session to confirm durability
        fresh_kernel = Kernel(tmp_path)
        loaded_id = fresh_kernel.load_entity(storage_id)
        assert not isinstance(loaded_id, Error)

        loaded_proxy = fresh_kernel.get_entity_proxy(loaded_id)
        assert loaded_proxy.health.current == 70
        assert loaded_proxy.health.max == 100

    def test_execute_script_with_extra_globals(self, tmp_path):
        kernel = Kernel(tmp_path)
        entity_id = kernel.create_entity(components={"Health": {"current": 50}})
        storage_id_hex = kernel.get_storage_id(entity_id).hex()

        script = (
            f"target = <|0|{storage_id_hex}|>\n"
            f"target.health.current += bonus_heal\n"
        )

        kernel.execute_script(script, extra_globals={"bonus_heal": 25})
        assert kernel.get_entity_proxy(entity_id).health.current == 75

    def test_execute_script_fails_cleanly_on_nonexistent_reference(self, tmp_path):
        kernel = Kernel(tmp_path)
        non_existent_hex = "00" * 16

        script = f"target = <|0|{non_existent_hex}|>\n"
        with pytest.raises(Error):
            kernel.execute_script(script)

    def test_resolve_proxy_type_mismatch_returns_error(self, tmp_path):
        kernel = Kernel(tmp_path)
        # Create a resource with type 1
        res_id = kernel.create_resource(resource_type=1, resource_data={"config": True})
        assert not isinstance(res_id, Error)
        storage_id_hex = kernel.get_storage_id(res_id).hex()

        # Resolving with matching type 1 succeeds
        res = kernel.resolve_proxy(1, storage_id_hex)
        assert not isinstance(res, Error)
        assert res["type"] == 1

        # Resolving with mismatched type 2 returns Error
        err = kernel.resolve_proxy(2, storage_id_hex)
        assert isinstance(err, Error)
        assert "mismatch" in str(err.message).lower()

        # Executing a script with mismatched type fails during module binding
        script = f"target = <|2|{storage_id_hex}|>\n"
        with pytest.raises(Error) as exc_info:
            kernel.execute_script(script)
        assert "mismatch" in str(exc_info.value.message).lower()
