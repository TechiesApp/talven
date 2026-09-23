"""Hard-corpus acceptance: reference solutions pass, starters and habit mistakes fail."""
from pathlib import Path
import shutil
import unittest

from experiments.hard_tasks import HARD_CORPUS, HARD_TASKS
from experiments.tasks import get_tasks
from experiments.verifier import verify

COUNTER = """struct Counter {
    value: i32
}

fn read(c: &Counter) -> i32 {
    return c.value;
}

fn add(c: &mut Counter, delta: i32) -> i32 {
    c.value = c.value + delta;
    return c.value;
}
"""
PAIR = """struct Pair {
    a: i32,
    b: i32
}

fn total(p: Pair) -> i32 {
    return p.a + p.b;
}
"""
MAIN = "fn main() -> i32 {\n    return 0;\n}\n"

SOLUTIONS = {
    "lcm-no-overflow": """fn gcd(a: i32, b: i32) -> i32 {
    if (b == 0) { return a; }
    return gcd(b, a % b);
}
fn lcm(a: i32, b: i32) -> i32 {
    if (a == 0 || b == 0) { return 0; }
    return a / gcd(a, b) * b;
}
""" + MAIN,
    "digit-sum": """fn digit_sum(n: i32) -> i32 {
    if (n == 0) { return 0; }
    let digit = n % 10;
    let rest = n / 10;
    if (digit < 0) { return -digit + digit_sum(rest); }
    return digit + digit_sum(rest);
}
""" + MAIN,
    "pow-mod": """fn pow_mod(base: i32, exp: i32, m: i32) -> i32 {
    if (exp == 0) { return 1 % m; }
    let half = pow_mod(base, exp / 2, m);
    let square = half * half % m;
    if (exp % 2 == 0) { return square; }
    return square * (base % m) % m;
}
""" + MAIN,
    "grade-bands": """fn band(score: i32) -> i32 {
    if (score < 0 || score > 100) { return -1; }
    if (score >= 90) { return 4; }
    if (score >= 80) { return 3; }
    if (score >= 70) { return 2; }
    if (score >= 60) { return 1; }
    return 0;
}
""" + MAIN,
    "recursive-reborrow": COUNTER + """fn bump_n(c: &mut Counter, times: i32, delta: i32) -> i32 {
    if (times == 0) { return read(&c); }
    add(&mut c, delta);
    return bump_n(&mut c, times - 1, delta);
}
""" + MAIN,
    "snapshot-before-move": PAIR + """fn weighted(p: Pair) -> i32 {
    let a = p.a;
    return total(p) * 10 + a;
}
""" + MAIN,
    "no-shadowing": """fn clamp(x: i32) -> i32 {
    if (x < -1000) { return -1000; }
    if (x > 1000) { return 1000; }
    return x;
}
fn normalize(x: i32) -> i32 {
    let tripled = clamp(x) * 3;
    if (tripled % 2 != 0) { return tripled + 1 - 7; }
    return tripled - 7;
}
""" + MAIN,
    "multi-error-repair": """struct Meter {
    level: i32
}
fn read(m: &Meter) -> i32 {
    return m.level;
}
fn raise(m: &mut Meter, amount: i32) -> i32 {
    m.level = m.level + amount;
    return m.level;
}
fn in_range(x: i32, low: i32, high: i32) -> bool { return low <= x && x <= high; }
fn classify(x: i32) -> i32 {
    if (x < 0) { return -1; }
    if (x == 0) { return 0; }
    return 1;
}
fn boost(m: &mut Meter, x: i32) -> i32 {
    let before = read(&m);
    raise(&mut m, classify(x) * 10);
    return read(&m) - before;
}
fn scaled(x: i32) -> i32 { return x * 2 + 3; }
fn sum3(a: i32, b: i32, c: i32) -> i32 { return a + b + c; }
fn settle(m: Meter) -> i32 {
    let level = m.level;
    let kept = m;
    return level + kept.level;
}
""" + MAIN,
}

# One natural mistake per task: habits from other languages or unchecked overflow.
MISTAKES = {
    "lcm-no-overflow": ("return a / gcd(a, b) * b;", "return a * b / gcd(a, b);"),
    "digit-sum": ("if (n == 0) { return 0; }", "if (n == 0) { return 0; }\n    if (n < 0) { return digit_sum(-n); }"),
    "pow-mod": ("return square * (base % m) % m;", "return square * base % m;"),
    "grade-bands": ("if (score >= 80) { return 3; }", "else if (score >= 80) { return 3; }"),
    "recursive-reborrow": ("add(&mut c, delta);", "add(c, delta);"),
    "snapshot-before-move": ("let a = p.a;\n    return total(p) * 10 + a;", "return total(p) * 10 + p.a;"),
    "no-shadowing": ("let tripled = clamp(x) * 3;", "let x = clamp(x) * 3;\n    let tripled = x;"),
    "multi-error-repair": ("return low <= x && x <= high;", "return low <= x <= high;"),
}


@unittest.skipUnless(shutil.which("cc"), "Native acceptance requires a C11 compiler named cc")
class HardCorpusTests(unittest.TestCase):
    def test_corpus_is_registered_with_existing_sources(self):
        self.assertIs(HARD_TASKS, get_tasks(HARD_CORPUS))
        self.assertEqual(set(SOLUTIONS), set(HARD_TASKS))
        for spec in HARD_TASKS.values():
            self.assertTrue(Path(spec["source"]).is_file(), spec["source"])

    def test_reference_solutions_pass(self):
        for task, source in SOLUTIONS.items():
            with self.subTest(task=task):
                result = verify(task, source)
                self.assertEqual("passed", result["status"], result["feedback"])

    def test_starters_do_not_pass(self):
        for task, spec in HARD_TASKS.items():
            with self.subTest(task=task):
                result = verify(task, Path(spec["source"]).read_text(encoding="utf-8"))
                self.assertEqual("failed", result["status"], result["feedback"])

    def test_habit_mistakes_are_rejected(self):
        for task, (correct, mistake) in MISTAKES.items():
            with self.subTest(task=task):
                self.assertIn(correct, SOLUTIONS[task])
                result = verify(task, SOLUTIONS[task].replace(correct, mistake, 1))
                self.assertNotEqual("passed", result["status"])

    def test_one_call_cannot_replace_repeated_add_calls(self):
        cheat = SOLUTIONS["recursive-reborrow"].replace(
            "if (times == 0) { return read(&c); }\n    add(&mut c, delta);\n    return bump_n(&mut c, times - 1, delta);",
            "add(&mut c, times * delta);\n    return read(&c);")
        self.assertNotEqual(cheat, SOLUTIONS["recursive-reborrow"])
        self.assertEqual("failed", verify("recursive-reborrow", cheat)["status"])


if __name__ == "__main__":
    unittest.main()
