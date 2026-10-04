"""Independent acceptance must reject type-valid but incorrect cost sources."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from talven.backend import emit_c
from talven.resources import analyze_resources

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "experiments/resource-costs"


class ResourceCostFixtureTests(unittest.TestCase):
    def execute(self, source, *, ledger):
        compiler = shutil.which("cc")
        self.assertIsNotNone(compiler, "resource cost acceptance requires a C11 compiler")
        # Analysis succeeds even for the intentionally wrong mutation below.
        generated = emit_c(analyze_resources(source))
        with tempfile.TemporaryDirectory(prefix="talven-cost-oracle-") as temporary:
            directory = Path(temporary)
            (directory / "generated.c").write_text(generated)
            (directory / "driver.c").write_bytes((FIXTURES / "driver.c").read_bytes())
            flags = ["-std=c11", "-O2", "-fno-lto", "-Wall", "-Wextra", "-Werror",
                     "-pedantic-errors", "-DTEST_CAPACITY=32"]
            if ledger:
                command = [compiler, *flags, "-DCOST_LEDGER", "-DTV_REGION_SOURCE_TEST",
                           str(directory / "driver.c"), "-o", str(directory / "program")]
            else:
                result = subprocess.run([compiler, *flags, "-Dmain=tv_generated_main", "-c",
                                         str(directory / "generated.c"), "-o", str(directory / "generated.o")],
                                        capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                command = [compiler, *flags, str(directory / "driver.c"), str(directory / "generated.o"),
                           "-o", str(directory / "program")]
            result = subprocess.run(command, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            argv = [str(directory / "program")] if ledger else [str(directory / "program"), "0", "10000"]
            return subprocess.run(argv, capture_output=True, timeout=30)

    def test_independent_ledgers_accept_correct_source(self):
        result = self.execute((FIXTURES / "workload.tal").read_text(), ledger=True)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))

    def test_type_valid_wrong_zero_value_rejected_in_both_builds(self):
        source = (FIXTURES / "workload.tal").read_text()
        self.assertIn("return byte;", source)
        source = source.replace("return byte;", "return byte + 1;")
        for ledger in (True, False):
            with self.subTest(ledger=ledger):
                result = self.execute(source, ledger=ledger)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"resource-costs:", result.stderr)

    def test_type_valid_wrong_failure_value_rejected(self):
        source = (FIXTURES / "workload.tal").read_text().replace("return -10;", "return 0;")
        result = self.execute(source, ledger=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"resource-costs:", result.stderr)

    def test_ledger_rejects_missing_work_even_when_scalar_oracle_passes(self):
        source = (FIXTURES / "workload.tal").read_text()
        start = source.index("                match (read_byte(&block, index)) {")
        end = source.index("\n            }\n            Allocation::InvalidRequest", start)
        # Keep every scheduled return correct, but remove the required byte read.
        replacement = """                release(block);
                if (index < 0 || index >= size) {
                    return -30;
                }
                return 0;"""
        source = source[:start] + replacement + source[end:]
        production = self.execute(source, ledger=False)
        self.assertEqual(production.returncode, 0, production.stderr.decode())
        ledger = self.execute(source, ledger=True)
        self.assertNotEqual(ledger.returncode, 0)
        self.assertIn(b"resource-costs:", ledger.stderr)
