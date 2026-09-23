from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from talven.backend import emit_c
from talven.formatter import format_source
from talven.frontend import analyze

REFERENCE = Path("docs/language-reference.md")


class LanguageReferenceTests(unittest.TestCase):
    def example(self):
        blocks = re.findall(r"~~~text\n(.*?)~~~", REFERENCE.read_text(encoding="utf-8"), re.S)
        self.assertEqual(1, len(blocks))
        return blocks[0]

    def test_example_is_canonical_and_checks(self):
        source = self.example()
        self.assertEqual(source, format_source(source))
        emit_c(analyze(source), console=True)

    @unittest.skipUnless(shutil.which("cc"), "Native execution requires a C11 compiler named cc")
    def test_example_prints_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            cfile, executable = directory / "reference.c", directory / "reference"
            cfile.write_text(emit_c(analyze(self.example()), console=True))
            subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic-errors",
                            str(cfile), "-o", str(executable)], check=True, capture_output=True, timeout=30)
            result = subprocess.run([str(executable)], capture_output=True, timeout=5)
            self.assertEqual((0, b"ok\n", b""), (result.returncode, result.stdout, result.stderr))

    def test_every_documented_diagnostic_code_is_emitted_by_the_compiler(self):
        documented = set(re.findall(r"E0\d{3}", REFERENCE.read_text(encoding="utf-8")))
        emitted = set()
        for path in Path("talven").glob("*.py"):
            emitted.update(re.findall(r'"(E0\d{3})"', path.read_text(encoding="utf-8")))
        self.assertLessEqual(documented, emitted)
