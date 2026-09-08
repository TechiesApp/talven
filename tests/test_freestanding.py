import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check-freestanding.py"
SPEC = importlib.util.spec_from_file_location("check_freestanding", SCRIPT)
freestanding = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(freestanding)


def readelf(machine="Advanced Micro Devices X86-64", *, elf_class="ELF64", data="2's complement, little endian",
            typ="EXEC (Executable file)", entry="401000", headers=None, dynamic="There is no dynamic section in this file."):
    headers = headers or """LOAD 0x000000 0x0000000000400000 0x0000000000400000 0x100 0x100 R E 0x1000
  LOAD 0x001000 0x0000000000401000 0x0000000000401000 0x20 0x20 RW 0x1000
  GNU_STACK 0x000000 0x0000000000000000 0x0000000000000000 0x0 0x0 RW 0x10"""
    return f"""ELF Header:
  Class:                             {elf_class}
  Data:                              {data}
  Type:                              {typ}
  Machine:                           {machine}
  Entry point address:               0x{entry}
Program Headers:
  Type Offset VirtAddr PhysAddr FileSiz MemSiz Flg Align
  {headers}
{dynamic}
"""


class InspectorTests(unittest.TestCase):
    def test_valid_x86_and_aarch64(self):
        for machine in ("Advanced Micro Devices X86-64", "AArch64"):
            with self.subTest(machine=machine):
                result = freestanding.parse_readelf(readelf(machine), machine, 0x401000)
                self.assertEqual(0x401000, result["entry"])

    def test_rejects_wrong_header_identity_and_entry(self):
        changes = [
            {"machine": "AArch64"}, {"elf_class": "ELF32"}, {"data": "2's complement, big endian"},
            {"typ": "DYN (Shared object file)"}, {"entry": "0"},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                freestanding.parse_readelf(readelf(**change), "Advanced Micro Devices X86-64", 0x401000)
        with self.assertRaisesRegex(ValueError, "does not match"):
            freestanding.parse_readelf(readelf(), "Advanced Micro Devices X86-64", 0x401001)

    def test_rejects_dynamic_headers_dependencies_and_unsafe_segments(self):
        bad = [
            (readelf(headers="INTERP 0x0 0x0 0x0 0x0 0x0 R 0x1\n  LOAD 0x0 0x400000 0x400000 0x1 0x1 R E 0x1000\n  GNU_STACK 0x0 0x0 0x0 0x0 0x0 RW 0x10"),
             "interpreter or dynamic program header"),
            (readelf(headers="DYNAMIC 0x0 0x0 0x0 0x0 0x0 RW 0x1\n  LOAD 0x0 0x400000 0x400000 0x1 0x1 R E 0x1000\n  GNU_STACK 0x0 0x0 0x0 0x0 0x0 RW 0x10"),
             "interpreter or dynamic program header"),
            (readelf(dynamic="Dynamic section contains 1 entry:\n 0x1 (NEEDED) Shared library: [libc.so.6]"),
             "dynamic section"),
            (readelf(headers="LOAD 0x0 0x400000 0x400000 0x1 0x1 WE 0x1000\n  GNU_STACK 0x0 0x0 0x0 0x0 0x0 RW 0x10"),
             "writable/executable LOAD"),
            (readelf(headers="LOAD 0x0 0x400000 0x400000 0x1 0x1 R E 0x1000\n  GNU_STACK 0x0 0x0 0x0 0x0 0x0 RWE 0x10"),
             "GNU_STACK is missing or executable"),
        ]
        for value, error in bad:
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                freestanding.parse_readelf(value, "Advanced Micro Devices X86-64")

    def test_rejects_truncated_program_header_rows(self):
        for headers in ("LOAD R E\n  GNU_STACK 0x0 0x0 0x0 0x0 0x0 RW 0x10",
                        "LOAD 0x0 0x0 0x0 0x1 0x1 R E 0x1000\n  GNU_STACK RW"):
            with self.subTest(headers=headers), self.assertRaisesRegex(ValueError, "malformed"):
                freestanding.parse_readelf(readelf(headers=headers), "Advanced Micro Devices X86-64")

    def test_rejects_duplicate_stack_headers_in_both_orders(self):
        safe = "GNU_STACK 0x0 0x0 0x0 0x0 0x0 RW 0x10"
        executable = "GNU_STACK 0x0 0x0 0x0 0x0 0x0 RWE 0x10"
        load = "LOAD 0x0 0x400000 0x400000 0x1 0x1 R E 0x1000"
        for stacks in ((safe, executable), (executable, safe)):
            headers = "\n  ".join((load, *stacks))
            with self.subTest(stacks=stacks), self.assertRaisesRegex(ValueError, "duplicate GNU_STACK"):
                freestanding.parse_readelf(readelf(headers=headers), "Advanced Micro Devices X86-64")

    def test_nm_parser_rejects_unexpected_and_malformed_symbols(self):
        self.assertEqual({"talven_trap"}, freestanding.parse_nm_undefined("                 U talven_trap\n"))
        self.assertEqual(set(), freestanding.parse_nm_undefined(""))
        self.assertNotEqual({"talven_trap"}, freestanding.parse_nm_undefined(" U memcpy\n"))
        for output in ("garbage\n", "0000 T defined_symbol\n", "U\n"):
            with self.subTest(output=output), self.assertRaises(ValueError):
                freestanding.parse_nm_undefined(output)

    def test_size_parser_is_strict(self):
        self.assertEqual({"text_bytes": 12, "data_bytes": 3, "bss_bytes": 4},
                         freestanding.parse_size("text data bss dec hex filename\n12 3 4 19 13 probe\n"))
        self.assertEqual(12, freestanding.parse_size(
            "text data bss dec hex filename\n12 3 4 19 13 path with spaces/probe\n")["text_bytes"])
        for output in ("", "text data bss dec hex filename\n", "text data bss dec hex filename\n12 x 4 16 10 p\n",
                       "text data bss dec hex filename\n12 3 4 20 14 p\n",
                       "text data bss dec hex filename\n12 3 4 19 14 p\n", "12 3 4 19 13 p\n"):
            with self.subTest(output=output), self.assertRaises(ValueError):
                freestanding.parse_size(output)


class CliBehaviorTests(unittest.TestCase):
    def test_preflight_rejects_empty_existing_unsupported_and_mismatch_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            with self.assertRaisesRegex(freestanding.ProbeError, "must not be empty"):
                freestanding.preflight("", None)
            existing = base / "existing"
            existing.mkdir()
            with self.assertRaisesRegex(freestanding.ProbeError, "already exists"):
                freestanding.preflight(str(existing), None)
            target = base / "new"
            with mock.patch.object(freestanding.platform, "system", return_value="Darwin"), \
                 mock.patch.object(freestanding.platform, "machine", return_value="arm64"):
                with self.assertRaisesRegex(freestanding.ProbeError, "requires native Linux"):
                    freestanding.preflight(str(target), None)
            self.assertFalse(target.exists())
            with mock.patch.object(freestanding.platform, "system", return_value="Linux"), \
                 mock.patch.object(freestanding.platform, "machine", return_value="x86_64"):
                with self.assertRaisesRegex(freestanding.ProbeError, "expected aarch64"):
                    freestanding.preflight(str(target), "aarch64")
            self.assertFalse(target.exists())

    def test_preflight_rejects_missing_tool_without_creating_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "new"
            with mock.patch.object(freestanding.platform, "system", return_value="Linux"), \
                 mock.patch.object(freestanding.platform, "machine", return_value="x86_64"), \
                 mock.patch.object(freestanding.shutil, "which", side_effect=lambda name: None if name == "nm" else f"/bin/{name}"):
                with self.assertRaisesRegex(freestanding.ProbeError, "nm"):
                    freestanding.preflight(str(target), None)
            self.assertFalse(target.exists())

    def test_timeout_records_command_evidence(self):
        report = {"commands": []}
        expired = subprocess.TimeoutExpired(["fake"], 5, output=b"partial", stderr=b"problem")
        with mock.patch.object(freestanding.subprocess, "run", side_effect=expired):
            with self.assertRaisesRegex(freestanding.ProbeError, "timed out"):
                freestanding.command(report, ["fake"], "execute", 5)
        self.assertTrue(report["commands"][0]["timed_out"])
        self.assertEqual("partial", report["commands"][0]["stdout"])

    def test_execution_boundary_preserves_expected_and_wrong_nonzero_exits(self):
        for returncode in (97, 1, -11):
            completed = subprocess.CompletedProcess(["probe"], returncode, "", "")
            report = {"commands": []}
            with self.subTest(returncode=returncode), \
                 mock.patch.object(freestanding.subprocess, "run", return_value=completed):
                result = freestanding.command(report, ["probe"], "execute", 5, allow_empty=True, check=False)
                self.assertEqual(returncode, result.returncode)
                self.assertEqual(returncode, report["commands"][0]["returncode"])

    def test_failure_after_creation_saves_partial_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "results"
            tools = {name: f"/fake/{name}" for name in freestanding.TOOLS}
            with mock.patch.object(freestanding, "preflight", return_value=(target, "aarch64", tools)), \
                 mock.patch.object(freestanding, "git_details", side_effect=freestanding.ProbeError("provenance", "controlled failure")):
                report = freestanding.run_probe(str(target))
            saved = json.loads((target / "report.json").read_text())
            self.assertFalse(report["passed"])
            self.assertEqual("provenance", saved["stage"])
            self.assertIn("controlled failure", saved["error"])


if __name__ == "__main__":
    unittest.main()
