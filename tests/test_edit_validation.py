import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from talven import PROFILE
from talven.context import compiler_hash, encode, source_hash
from talven.edit_validation import snapshot_source, validate_edit
from talven.frontend import analyze as frontend_analyze


VALID = "fn main() -> i32 { return 0; }\n"


class EditValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.tal"
        self.candidate = self.root / "candidate.tal"
        self.source.write_bytes(VALID.encode())
        self.candidate.write_bytes(VALID.encode())

    def tearDown(self):
        self.temporary.cleanup()

    def test_snapshot_is_deterministic_and_source_echo_is_opt_in(self):
        receipt = snapshot_source(self.source)
        self.assertTrue(receipt["ok"])
        self.assertEqual("talven.edit-snapshot.v1", receipt["schema"])
        self.assertEqual("not-run", receipt["validation"])
        self.assertEqual(source_hash(VALID), receipt["source_hash"])
        self.assertEqual(compiler_hash(), receipt["compiler_hash"])
        self.assertEqual(PROFILE, receipt["profile"])
        self.assertEqual(len(VALID.encode()), receipt["source_bytes"])
        self.assertNotIn("untrusted_source_text", receipt)
        self.assertEqual(encode(receipt), encode(snapshot_source(self.source)))
        self.assertEqual(VALID, snapshot_source(self.source, include_source=True)["untrusted_source_text"])

    def test_snapshot_accepts_invalid_syntax_and_preserves_crlf_hash(self):
        raw = b"fn broken(\r\n"
        self.source.write_bytes(raw)
        receipt = snapshot_source(self.source, include_source=True)
        self.assertTrue(receipt["ok"])
        self.assertEqual(source_hash(raw.decode()), receipt["source_hash"])
        self.assertEqual(raw.decode(), receipt["untrusted_source_text"])

    def test_successful_noop_and_contract_call_changes(self):
        source = ("struct P { x: i32 }\n"
                  "fn read(p: &P) -> i32 { return p.x; }\n"
                  "fn f(p: P) -> i32 { return p.x; }\n")
        candidate = ("struct P { x: i32, y: bool }\n"
                     "fn read(p: &P) -> i32 { return p.x; }\n"
                     "fn f(p: &P) -> i32 { return read(&p); }\n")
        self.source.write_text(source, encoding="utf-8")
        self.candidate.write_text(candidate, encoding="utf-8")
        receipt = validate_edit(self.source, self.candidate,
                                expected_source_hash=source_hash(source),
                                expected_compiler_hash=compiler_hash())
        self.assertTrue(receipt["ok"])
        self.assertTrue(receipt["candidate_changed"])
        self.assertEqual(["f", "P"], [item["name"] for item in receipt["changes"]["contracts_changed"]])
        self.assertEqual([{"name": "f", "before": [], "after": ["read"]}], receipt["changes"]["calls_changed"])
        self.assertNotIn("calls", receipt["changes"]["contracts_changed"][1]["before"])

    def test_invalid_base_can_be_repaired_but_invalid_candidate_blocks(self):
        self.source.write_text("fn main() -> i32 { return false; }", encoding="utf-8")
        expected = source_hash(self.source.read_text())
        repaired = validate_edit(self.source, self.candidate, expected_source_hash=expected,
                                 expected_compiler_hash=compiler_hash())
        self.assertTrue(repaired["ok"])
        self.assertFalse(repaired["base"]["ok"])
        self.assertIsNone(repaired["changes"])
        self.candidate.write_text("fn main() -> i32 { return false; }", encoding="utf-8")
        failed = validate_edit(self.source, self.candidate, expected_source_hash=expected,
                               expected_compiler_hash=compiler_hash())
        self.assertFalse(failed["ok"])
        self.assertEqual("E0201", failed["candidate"]["diagnostics"][0]["code"])
        self.assertEqual([], failed["diagnostics"])

    def test_guards_precede_candidate_read_and_analysis(self):
        missing = self.root / "missing.tal"
        stale_compiler = validate_edit(self.source, missing, expected_source_hash=source_hash(VALID),
                                       expected_compiler_hash="0" * 64)
        self.assertEqual("E0702", stale_compiler["diagnostics"][0]["code"])
        with patch("talven.edit_validation.analyze") as analyze:
            stale_source = validate_edit(self.source, missing, expected_source_hash="1" * 64,
                                         expected_compiler_hash=compiler_hash())
        self.assertEqual("E0501", stale_source["diagnostics"][0]["code"])
        analyze.assert_not_called()

    def test_request_input_and_output_limits_are_controlled(self):
        for kwargs in ({"expected_source_hash": "BAD", "expected_compiler_hash": "0" * 64},
                       {"expected_source_hash": source_hash(VALID), "expected_compiler_hash": compiler_hash(), "max_bytes": True}):
            receipt = validate_edit(self.source, self.candidate, **kwargs)
            self.assertFalse(receipt["ok"])
            self.assertEqual("E0701", receipt["diagnostics"][0]["code"])
            self.assertEqual("request", receipt["diagnostics"][0]["input"])
        full = snapshot_source(self.source, max_bytes=1024 * 1024)
        boundary = len(encode(full).encode("utf-8"))
        self.assertTrue(snapshot_source(self.source, max_bytes=boundary)["ok"])
        too_small = snapshot_source(self.source, max_bytes=boundary - 1)
        self.assertEqual("E0703", too_small["diagnostics"][0]["code"])
        self.assertNotIn("untrusted_source_text", too_small)

    def test_invalid_utf8_and_oversize_are_tagged(self):
        self.source.write_bytes(b"\xff")
        bad = snapshot_source(self.source)
        self.assertEqual(("E0901", "source"), (bad["diagnostics"][0]["code"], bad["diagnostics"][0]["input"]))
        self.source.write_bytes(b" " * (256 * 1024 + 1))
        large = snapshot_source(self.source)
        self.assertEqual("E0005", large["diagnostics"][0]["code"])

    def test_body_and_layout_only_edits_have_no_declared_changes(self):
        self.candidate.write_text("// retained\nfn main()->i32{return 0 + 0;}", encoding="utf-8")
        receipt = validate_edit(self.source, self.candidate,
                                expected_source_hash=source_hash(VALID),
                                expected_compiler_hash=compiler_hash())
        self.assertTrue(receipt["ok"])
        self.assertEqual({"added": [], "removed": [], "contracts_changed": [], "calls_changed": []},
                         receipt["changes"])

    def test_same_file_preview_preserves_content_and_writer_metadata(self):
        before_data = self.source.read_bytes()
        before = self.source.stat()
        receipt = validate_edit(self.source, self.source,
                                expected_source_hash=source_hash(VALID),
                                expected_compiler_hash=compiler_hash())
        after = self.source.stat()
        self.assertTrue(receipt["ok"])
        self.assertFalse(receipt["candidate_changed"])
        self.assertEqual(before_data, self.source.read_bytes())
        self.assertEqual((before.st_ino, before.st_mode, before.st_mtime_ns),
                         (after.st_ino, after.st_mode, after.st_mtime_ns))

    def test_kind_changes_are_removal_and_addition(self):
        self.source.write_text("struct Item { value: i32 }", encoding="utf-8")
        self.candidate.write_text("fn Item() -> i32 { return 0; }", encoding="utf-8")
        receipt = validate_edit(self.source, self.candidate,
                                expected_source_hash=source_hash(self.source.read_text()),
                                expected_compiler_hash=compiler_hash())
        self.assertTrue(receipt["ok"])
        self.assertEqual("function", receipt["changes"]["added"][0]["kind"])
        self.assertEqual("record", receipt["changes"]["removed"][0]["kind"])
        self.assertEqual([], receipt["changes"]["contracts_changed"])

    def test_candidate_diagnostic_uses_candidate_utf16_positions(self):
        candidate = "// 😀\nfn main() -> i32 { return false; }"
        self.candidate.write_text(candidate, encoding="utf-8")
        receipt = validate_edit(self.source, self.candidate,
                                expected_source_hash=source_hash(VALID),
                                expected_compiler_hash=compiler_hash())
        diagnostic = receipt["candidate"]["diagnostics"][0]
        self.assertEqual({"line": 1, "character": 26}, diagnostic["range"]["start"])

    def test_observed_candidate_and_compiler_changes_fail_without_writing(self):
        changed = "fn main() -> i32 { return 1; }\n"
        calls = 0

        def mutate_during_analysis(text):
            nonlocal calls
            calls += 1
            result = frontend_analyze(text)
            if calls == 2:
                self.candidate.write_text(changed, encoding="utf-8")
            return result

        with patch("talven.edit_validation.analyze", side_effect=mutate_during_analysis):
            receipt = validate_edit(self.source, self.candidate,
                                    expected_source_hash=source_hash(VALID),
                                    expected_compiler_hash=compiler_hash())
        self.assertEqual("E0501", receipt["diagnostics"][0]["code"])
        self.assertEqual(changed, self.candidate.read_text())
        identity = "a" * 64
        with patch("talven.edit_validation.compiler_hash", side_effect=[identity, "b" * 64]):
            receipt = validate_edit(self.source, self.source, expected_source_hash=source_hash(VALID),
                                    expected_compiler_hash=identity)
        self.assertEqual("E0702", receipt["diagnostics"][0]["code"])


if __name__ == "__main__":
    unittest.main()
