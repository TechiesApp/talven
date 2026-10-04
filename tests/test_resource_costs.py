"""Receipt gates reject plausible but incomplete or misleading cost evidence."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("resource_cost_measurement", ROOT / "scripts/measure-resource-costs.py")
costs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(costs)


class ResourceCostReceiptTests(unittest.TestCase):
    def test_original_source_reference_cli_and_native_receipt_shapes(self):
        process = subprocess.run([sys.executable, "-B", "-m", "talven", "check",
                                  str(ROOT / "experiments/resource-costs/workload.tal"), "--resources", "--json"],
                                 cwd=ROOT, capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, b"")
        self.assertEqual(costs.validate_check(process.stdout)["language_profile"], costs.PROFILE)
        native = {"schema": "talven.diagnostics.v1", "ok": True, "diagnostics": [], "profile": costs.PROFILE}
        costs.validate_check(json.dumps(native).encode(), native=True)
        with self.assertRaises(costs.base.MeasurementError):
            costs.validate_check(process.stdout, native=True)
        with self.assertRaises(costs.base.MeasurementError):
            costs.validate_check(json.dumps({**native, "ok": 1}).encode(), native=True)

    def receipt(self, **updates):
        value = {"workload": 1, "iterations": 100, "checksum": 250,
                 "elapsed_ns": 10000, "resolution_ns": 100}
        value.update(updates)
        return json.dumps(value).encode()

    def test_timing_requires_correct_batch_and_adequate_clock(self):
        self.assertEqual(costs.validate_timing(self.receipt(), 1, 100)["checksum"], 250)
        for updates in ({"checksum": 249}, {"workload": 0}, {"iterations": 104},
                        {"elapsed_ns": 9999}, {"resolution_ns": 0}, {"elapsed_ns": -1},
                        {"elapsed_ns": True}, {"iterations": 100.0}, {"resolution_ns": "100"}):
            with self.subTest(updates=updates), self.assertRaises(costs.base.MeasurementError):
                costs.validate_timing(self.receipt(**updates), 1, 100)

    def test_timing_rejects_extra_duplicate_and_trailing_json(self):
        for output in (self.receipt() + b"{}", self.receipt(extra=0),
                       self.receipt().replace(b'"workload": 1', b'"workload": 1, "workload": 1'),
                       self.receipt().replace(b"10000", b"NaN")):
            with self.subTest(output=output), self.assertRaises(costs.base.MeasurementError):
                costs.validate_timing(output, 1, 100)

    def test_iteration_bounds_exclude_bools_and_incomplete_schedule(self):
        for number in (4, 10000, 10000000):
            costs.validate_iterations(number)
        for number in (True, 0, 3, 5, 10000004, 4.0):
            with self.subTest(number=number), self.assertRaises(costs.base.MeasurementError):
                costs.validate_iterations(number)

    def test_actual_gcc_and_clang_stack_record_labels(self):
        for records in (b"/tmp/generated.c:321:9:tv_f_cycle\t128\tstatic\n"
                        b"/tmp/generated.c:385:9:tv_f_reuse\t256\tstatic\n"
                        b"/tmp/generated.c:461:9:tv_f_sequential\t512\tstatic\n",
                        b"generated.c:321:tv_f_cycle\t128\tstatic\n"
                        b"generated.c:385:tv_f_reuse\t256\tstatic\n"
                        b"generated.c:461:tv_f_sequential\t512\tstatic\n"):
            self.assertEqual(costs.parse_stack_usage(records),
                             {"tv_f_cycle": 128, "tv_f_reuse": 256, "tv_f_sequential": 512})

    def test_stack_reports_cannot_hide_dynamic_or_missing_functions(self):
        good = b"file.c:1:tv_f_cycle\t32\tstatic\nfile.c:2:tv_f_reuse\t32\tstatic\nfile.c:3:tv_f_sequential\t64\tstatic\n"
        for output in (good.replace(b"static", b"dynamic", 1),
                       good.replace(b"static", b"dynamic,bounded", 1),
                       good.replace(b"\t32\t", b"\t-32\t", 1),
                       good + b"file.c:4:helper\t16\tdynamic\n",
                       good + good.splitlines(keepends=True)[0], good.splitlines(keepends=True)[0],
                       good + b"badrecord\n", b""):
            with self.subTest(output=output), self.assertRaises(costs.base.MeasurementError):
                costs.parse_stack_usage(output)
        self.assertEqual(costs.parse_stack_usage(good + b"file.c:5:helper.constprop.0\t16\tstatic\n")["tv_f_cycle"], 32)

    def samples(self):
        return [{"phase": "measured", "verified": True, "capacity": capacity,
                 "optimization": optimization, "shape": shape, "repetition": 1,
                 "batch": {"iterations": 100, "elapsed_ns": 10000, "resolution_ns": 1}}
                for capacity in costs.CAPACITIES for optimization in costs.OPTIMIZATIONS for shape in costs.SHAPES]

    def test_summary_excludes_warmup_and_requires_every_verified_shape(self):
        samples = self.samples()
        warmup = {**samples[0], "phase": "warmup", "batch": {"iterations": 100, "elapsed_ns": 999999, "resolution_ns": 1}}
        summary = costs.summarize([*samples, warmup], 1)
        self.assertEqual(len(summary), 18)
        self.assertEqual(summary[0]["median_batch_ns"], 10000)
        self.assertEqual(summary[0]["median_ns_per_workload_iteration"], 100)
        for bad in (samples[:-1], [*samples, samples[0]], [{**samples[0], "verified": False}, *samples[1:]],
                    [{**samples[0], "repetition": 2}, *samples[1:]]):
            with self.subTest(bad=bad), self.assertRaises(costs.base.MeasurementError):
                costs.summarize(bad, 1)

    def test_semantic_zeroing_accounts_for_rows_and_reuse(self):
        cycle = costs.semantic_counts(32, "cycle", 4)["batch"]
        reuse = costs.semantic_counts(32, "reuse", 4)["batch"]
        sequential = costs.semantic_counts(32, "sequential", 4)["batch"]
        self.assertEqual(cycle["initialized_visible_bytes"], 81)
        self.assertEqual(reuse["initialized_visible_bytes"], 162)
        self.assertEqual(sequential["initialized_visible_bytes"], 162)
        self.assertEqual(reuse["writes"], 4)
        self.assertEqual(cycle["writes"], 0)
        self.assertEqual(sequential["calls"], 4)
        self.assertEqual(sequential["region_initializations"], 8)

    def test_production_dependencies_are_fixed_and_do_not_allow_test_hooks(self):
        self.assertEqual(costs.production_symbols(b"                 U _abort\n                 U _memset\n"), ["abort", "memset"])
        self.assertEqual(costs.production_symbols(b"_abort\n_memset\n___stack_chk_fail\n"),
                         ["abort", "memset", "stack_chk_fail"])
        for output in (b" U _tv_region_source_event\n", b" U malloc\n", b"malformed\n"):
            with self.assertRaises(costs.base.MeasurementError):
                costs.production_symbols(output)

    def test_native_section_reports_keep_platform_formats_without_summing(self):
        darwin_object = b"Segment : 40\n\tSection (__TEXT, __text): 8\n\tSection (__LD, __compact_unwind): 32\n\ttotal 40\ntotal 40\n"
        darwin_program = (b"Segment __PAGEZERO: 4294967296 (zero fill)\nSegment __TEXT: 16384\n"
                          b"\tSection __text: 7064\n\tSection __stubs: 108\n\ttotal 7501\n"
                          b"Segment __DATA_CONST: 16384\n\tSection __const: 24\n\tSection __got: 88\n"
                          b"\ttotal 112\nSegment __LINKEDIT: 16384\ntotal 4295016448\n")
        linux = b"generated.o  :\nsection           size   addr\n.text              512      0\n.note.GNU-stack      0      0\nTotal              512\n"
        self.assertEqual(costs.validate_size(darwin_object, "Darwin"), darwin_object.decode().strip())
        costs.validate_size(darwin_program, "Darwin")
        costs.validate_size(linux, "Linux")
        for data, system in ((darwin_object, "Linux"), (linux, "Darwin"),
                             (b"Segment : 40\ntotal 40\n", "Darwin"), (b"Total 512\n", "Linux")):
            with self.subTest(data=data, system=system), self.assertRaises(costs.base.MeasurementError):
                costs.validate_size(data, system)

    def test_layout_shape_and_offsets_reject_impossible_target_claims(self):
        layout = {name: {"size": 64, "alignment": 8, "offsets": {field: 0 for field in fields}}
                  for name, fields in costs.LAYOUT_FIELDS.items()}
        costs.validate_layout(json.dumps(layout).encode())
        for record in ({"size": True}, {"alignment": 3}, {"size": 65},
                       {"offsets": {"storage": 64}}):
            bad = {**layout, "tv_region": {**layout["tv_region"], **record}}
            with self.subTest(record=record), self.assertRaises(costs.base.MeasurementError):
                costs.validate_layout(json.dumps(bad).encode())
        with self.assertRaises(costs.base.MeasurementError):
            costs.validate_layout(json.dumps({**layout, "invented": {}}).encode())

    def test_native_identity_and_input_bytes_must_stay_stable(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "input"
            path.write_bytes(b"original")
            identity = costs.base.fingerprint(path)
            info = {"compiler_hash": "abc"}
            with patch.object(costs.native_checker, "verify_build_sources"):
                costs.verify_native(info, path, identity, info)
                with self.assertRaises(costs.base.MeasurementError):
                    costs.verify_native({"compiler_hash": "changed"}, path, identity, info)
                path.write_bytes(b"changed")
                with self.assertRaises(costs.base.MeasurementError):
                    costs.verify_native(info, path, identity, info)
            with self.assertRaises(costs.base.MeasurementError):
                costs.verify_inputs([path], {path: b"original"}, [path])
            with self.assertRaises(costs.base.MeasurementError):
                costs.verify_inputs([path], {path: b"changed"}, [])

    def test_fixed_native_manifest_rejects_stale_or_extra_embedded_sources(self):
        native_root = ROOT / "experiments/native-compiler"
        info = {"compiler_hash": "test-identity", "settings": {"CARGO_ENCODED_RUSTFLAGS": ""},
                "source_files": {name: (native_root / name).read_text() for name in costs.source_gate.NATIVE_SOURCES}}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "native"
            path.write_bytes(b"test binary identity")
            identity = costs.base.fingerprint(path)
            costs.verify_native(info, path, identity)
            stale = {**info, "source_files": {**info["source_files"], "src/resources.rs": "stale"}}
            extra = {**info, "source_files": {**info["source_files"], "../../private": "untrusted path"}}
            for label, changed in (("stale", stale), ("extra", extra)):
                with self.subTest(case=label), self.assertRaises(costs.base.MeasurementError):
                    costs.verify_native(changed, path, identity)

    def test_artifact_use_requires_the_original_build_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            executable = out / "program"
            executable.write_bytes(b"compiled first build")
            record = costs.archive_artifact(executable, out)
            costs.verify_file(record, out)
            executable.write_bytes(b"replacement build")
            with self.assertRaises(costs.base.MeasurementError):
                costs.verify_file(record, out)


if __name__ == "__main__":
    unittest.main()
