"""Independent task acceptance remains separate from edit-preview validation."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from talven.backend import emit_c
from talven.edit_validation import snapshot_source, validate_edit
from talven.frontend import analyze


BASE = """struct Counter { value: i32 }
fn bump(c: &mut Counter, amount: i32) -> i32 {
    c.value = c.value + amount;
    return c.value;
}
fn exercise(c: &Counter, amount: i32) -> i32 {
    return bump(&mut c, amount);
}
"""
REPAIR = BASE.replace("fn exercise(c: &Counter", "fn exercise(c: &mut Counter")
WRONG_REPAIR = REPAIR.replace("return bump(&mut c, amount);", "return bump(&mut c, amount) + 1;")
DRIVER = """#include <stdint.h>
#include <limits.h>
#include <stdlib.h>
struct tv_s_Counter { int32_t tv_m_value; };
extern int32_t tv_f_exercise(struct tv_s_Counter *, int32_t);
_Noreturn void talven_trap(void) { abort(); }
int main(void) {
    const int32_t cases[][3] = {
        {0, 0, 0}, {2, 3, 5}, {-7, 4, -3}, {1000, -2, 998},
        {INT32_MAX, 0, INT32_MAX}, {INT32_MIN, 0, INT32_MIN}
    };
    for (unsigned i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        struct tv_s_Counter counter = {cases[i][0]};
        int32_t result = tv_f_exercise(&counter, cases[i][1]);
        if (result != cases[i][2] || counter.tv_m_value != cases[i][2]) return 1;
    }
    return 0;
}
"""


@unittest.skipUnless(shutil.which("cc"), "Native edit acceptance requires a C11 compiler named cc")
class NativeEditValidationTests(unittest.TestCase):
    def test_frontend_preview_does_not_replace_independent_task_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source, candidate = directory / "source.tal", directory / "candidate.tal"
            source.write_bytes(BASE.encode("utf-8"))
            snapshot = snapshot_source(source)
            self.assertTrue(snapshot["ok"], snapshot)
            driver = directory / "driver.c"
            driver.write_text(DRIVER, encoding="utf-8")
            for name, text, expected_exit in (("repair", REPAIR, 0), ("wrong-repair", WRONG_REPAIR, 1)):
                candidate.write_bytes(text.encode("utf-8"))
                preview = validate_edit(source, candidate, expected_source_hash=snapshot["source_hash"],
                                        expected_compiler_hash=snapshot["compiler_hash"])
                self.assertTrue(preview["ok"], preview)
                self.assertFalse(preview["base"]["ok"])
                self.assertTrue(preview["candidate"]["ok"])
                self.assertIsNone(preview["changes"])
                self.assertEqual("frontend-only", preview["validation"])
                self.assertEqual(BASE.encode("utf-8"), source.read_bytes())
                self.assertEqual(text.encode("utf-8"), candidate.read_bytes())
                generated = directory / f"{name}.c"
                generated.write_text(emit_c(analyze(candidate.read_text(encoding="utf-8")), freestanding=True),
                                     encoding="utf-8")
                for optimization in ("-O0", "-O2"):
                    with self.subTest(candidate=name, optimization=optimization):
                        executable = directory / f"{name}-{optimization[1:]}"
                        compiled = subprocess.run(
                            ["cc", "-std=c11", optimization, "-fno-lto", "-Wall", "-Wextra", "-Werror",
                             "-pedantic-errors", str(generated), str(driver), "-o", str(executable)],
                            capture_output=True, text=True, timeout=30,
                        )
                        self.assertEqual(0, compiled.returncode, compiled.stderr)
                        executed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=5)
                        self.assertEqual(expected_exit, executed.returncode, executed.stderr)


if __name__ == "__main__":
    unittest.main()
