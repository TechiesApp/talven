"""Reviewer-owned acceptance for the hard corpus.

Expected values are computed independently in the C harness with 64-bit
arithmetic, over inputs chosen to include the edges each task names: products
that overflow while the answer fits, the most negative i32, exponents near
2**31, and range boundaries. A candidate that traps, crashes, or runs past the
native timeout fails. Protected helpers must stay token-identical. This is
finite public acceptance, not a proof of equivalence.
"""

from talven.backend import signature
from talven.frontend import lex

from .hard_tasks import HARD_TASKS

TASK_IDS = set(HARD_TASKS)

_PROTECTED = {
    "read-counter": "fn read(c: &Counter) -> i32 { return c.value; }",
    "add-counter": "fn add(c: &mut Counter, delta: i32) -> i32 { c.value = c.value + delta; return c.value; }",
    "total": "fn total(p: Pair) -> i32 { return p.a + p.b; }",
    "read-meter": "fn read(m: &Meter) -> i32 { return m.level; }",
    "raise": "fn raise(m: &mut Meter, amount: i32) -> i32 { m.level = m.level + amount; return m.level; }",
}

_CONTRACTS = {
    "lcm-no-overflow": {"gcd": ([("a", "i32"), ("b", "i32")], "i32"), "lcm": ([("a", "i32"), ("b", "i32")], "i32")},
    "digit-sum": {"digit_sum": ([("n", "i32")], "i32")},
    "pow-mod": {"pow_mod": ([("base", "i32"), ("exp", "i32"), ("m", "i32")], "i32")},
    "grade-bands": {"band": ([("score", "i32")], "i32")},
    "recursive-reborrow": {"bump_n": ([("c", "&mut Counter"), ("times", "i32"), ("delta", "i32")], "i32")},
    "snapshot-before-move": {"weighted": ([("p", "Pair")], "i32")},
    "no-shadowing": {"normalize": ([("x", "i32")], "i32")},
    "multi-error-repair": {
        "in_range": ([("x", "i32"), ("low", "i32"), ("high", "i32")], "bool"),
        "classify": ([("x", "i32")], "i32"),
        "boost": ([("m", "&mut Meter"), ("x", "i32")], "i32"),
        "scaled": ([("x", "i32")], "i32"),
        "sum3": ([("a", "i32"), ("b", "i32"), ("c", "i32")], "i32"),
        "settle": ([("m", "Meter")], "i32"),
    },
}

_RECORDS = {
    "recursive-reborrow": ("Counter", [("value", "i32")], {"read": "read-counter", "add": "add-counter"}),
    "snapshot-before-move": ("Pair", [("a", "i32"), ("b", "i32")], {"total": "total"}),
    "multi-error-repair": ("Meter", [("level", "i32")], {"read": "read-meter", "raise": "raise"}),
}


def _tokens(source):
    return [(token.kind, token.text) for token in lex(source)]


def _expressions(expr):
    yield expr
    for child in expr.args:
        yield from _expressions(child)
    for _, child in expr.fields:
        yield from _expressions(child)


def _statements(body):
    for statement in body:
        yield statement
        yield from _statements(statement.then)
        yield from _statements(statement.otherwise)


def _calls(fn):
    for statement in _statements(fn.body):
        for root in (statement.expr, statement.target):
            if root is not None:
                yield from (expr for expr in _expressions(root) if expr.kind == "call")


def structure(task, analysis):
    for name, (params, result) in _CONTRACTS[task].items():
        fn = analysis.functions.get(name)
        if fn is None or fn.result.text != result or [(n.text, t.text) for n, t in fn.params] != params:
            rendered = ", ".join(f"{n}: {t}" for n, t in params)
            return False, f"require fn {name}({rendered}) -> {result}"
    if task in _RECORDS:
        record_name, fields, helpers = _RECORDS[task]
        record = analysis.records.get(record_name)
        if record is None or [(n.text, t.text) for n, t in record.fields] != fields:
            return False, f"preserve struct {record_name} exactly"
        for name, key in helpers.items():
            fn = analysis.functions.get(name)
            if fn is None or _tokens(analysis.source[fn.span.start:fn.span.end]) != _tokens(_PROTECTED[key]):
                return False, f"preserve {name}'s signature and body; only comments and layout may change"
    if task == "recursive-reborrow":
        fn = analysis.functions["bump_n"]
        if any(statement.kind == "assign" for statement in _statements(fn.body)):
            return False, "bump_n must change the counter through add, not by assigning its field"
        if not any(call.value == "add" for call in _calls(fn)):
            return False, "bump_n must call add"
    if task == "snapshot-before-move":
        fn = analysis.functions["weighted"]
        if not any(call.value == "total" and len(call.args) == 1 and call.args[0].kind == "name"
                   and call.args[0].value == "p" for call in _calls(fn)):
            return False, "weighted must call total(p)"
    return True, "required contracts and protected helpers are present"


def prepare(task, analysis, generated):
    """Count add calls in recursive-reborrow; other tasks are unchanged."""
    if task != "recursive-reborrow":
        return generated
    header = signature(analysis.functions["add"]) + " {"
    if generated.count(header) != 1:
        raise ValueError("Cannot identify the emitted add definition")
    generated = generated.replace(header, header.replace("tv_f_add(", "tv_eval_original_add(", 1), 1)
    return generated + """
static unsigned tv_eval_adds;
static int32_t tv_eval_delta;
static int tv_eval_bad;
int32_t tv_f_add(struct tv_s_Counter *c, int32_t delta) {
    tv_eval_adds++;
    if (delta != tv_eval_delta) { tv_eval_bad = 1; }
    return tv_eval_original_add(c, delta);
}
"""


_REFERENCES = r"""
static int64_t ref_gcd(int64_t a, int64_t b) { while (b) { int64_t t = a % b; a = b; b = t; } return a; }
static int64_t ref_digits(int64_t n) { if (n < 0) { n = -n; } int64_t s = 0; while (n) { s += n % 10; n /= 10; } return s; }
static int64_t ref_pow(int64_t b, int64_t e, int64_t m) {
    int64_t r = 1 % m; b %= m;
    while (e) { if (e & 1) { r = r * b % m; } b = b * b % m; e >>= 1; }
    return r;
}
static int64_t ref_band(int64_t s) {
    if (s < 0 || s > 100) { return -1; }
    return s >= 90 ? 4 : s >= 80 ? 3 : s >= 70 ? 2 : s >= 60 ? 1 : 0;
}
static int64_t ref_normalize(int64_t x) {
    if (x < -1000) { x = -1000; } if (x > 1000) { x = 1000; }
    x *= 3; if (x % 2 != 0) { x += 1; }
    return x - 7;
}
static int64_t ref_classify(int64_t x) { return x < 0 ? -1 : x == 0 ? 0 : 1; }
#define FAIL(message) do { puts(message); return 1; } while (0)
"""

_CHECKS = {
    "lcm-no-overflow": r"""
    const int64_t pairs[][2] = {{0,0},{0,5},{5,0},{4,6},{21,6},{17,13},{65536,196608},{1000000,1500000},
        {2147483646,2},{46340,46341},{2147483647,1},{1,2147483647},{1134903170,1836311903},{2147483647,2147483647}};
    for (unsigned i = 0; i < sizeof(pairs) / sizeof(pairs[0]); ++i) {
        int64_t a = pairs[i][0], b = pairs[i][1], g = ref_gcd(a, b);
        if (tv_f_gcd((int32_t)a, (int32_t)b) != g) FAIL("gcd mismatch");
        int64_t l = (a == 0 || b == 0) ? 0 : a / g * b;
        if (l <= INT32_MAX && tv_f_lcm((int32_t)a, (int32_t)b) != l) FAIL("lcm mismatch");
    }""",
    "digit-sum": r"""
    const int64_t values[] = {0, 7, -7, 10, 12345, -12345, 1000000000, 2147483647, -2147483647, -2147483648LL};
    for (unsigned i = 0; i < sizeof(values) / sizeof(values[0]); ++i) {
        if (tv_f_digit_sum((int32_t)values[i]) != ref_digits(values[i])) FAIL("digit_sum mismatch");
    }""",
    "pow-mod": r"""
    const int64_t cases[][3] = {{2,10,1000},{0,0,7},{5,0,1},{0,5,3},{7,1,46340},{46339,2,46340},
        {2147483647,2147483647,46337},{3,2147483647,46340},{2,2147483646,46339},{123456789,1000000,40000},
        {10,2147483647,1},{2147483647,0,46340}};
    for (unsigned i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        int64_t b = cases[i][0], e = cases[i][1], m = cases[i][2];
        if (tv_f_pow_mod((int32_t)b, (int32_t)e, (int32_t)m) != ref_pow(b, e, m)) FAIL("pow_mod mismatch");
    }""",
    "grade-bands": r"""
    const int64_t values[] = {-2147483648LL, -1, 0, 1, 59, 60, 69, 70, 79, 80, 89, 90, 99, 100, 101, 2147483647};
    for (unsigned i = 0; i < sizeof(values) / sizeof(values[0]); ++i) {
        if (tv_f_band((int32_t)values[i]) != ref_band(values[i])) FAIL("band mismatch");
    }""",
    "recursive-reborrow": r"""
    const int32_t starts[] = {5, -3, 0};
    const int32_t times[] = {0, 1, 3, 50};
    const int32_t deltas[] = {-4, 0, 7};
    for (unsigned s = 0; s < 3; ++s) for (unsigned t = 0; t < 4; ++t) for (unsigned d = 0; d < 3; ++d) {
        struct tv_s_Counter counter = {.tv_m_value = starts[s]};
        tv_eval_adds = 0; tv_eval_bad = 0; tv_eval_delta = deltas[d];
        int32_t expected = starts[s] + times[t] * deltas[d];
        int32_t result = tv_f_bump_n(&counter, times[t], deltas[d]);
        if (result != expected || counter.tv_m_value != expected) FAIL("bump_n result or counter mismatch");
        if (tv_eval_adds != (unsigned)times[t] || tv_eval_bad) FAIL("bump_n must call add once per step with delta");
    }""",
    "snapshot-before-move": r"""
    const int32_t pairs[][2] = {{2,3},{0,0},{-5,9},{100,-7},{-40,-60},{12345,678}};
    for (unsigned i = 0; i < sizeof(pairs) / sizeof(pairs[0]); ++i) {
        struct tv_s_Pair p = {.tv_m_a = pairs[i][0], .tv_m_b = pairs[i][1]};
        if (tv_f_weighted(p) != (pairs[i][0] + pairs[i][1]) * 10 + pairs[i][0]) FAIL("weighted mismatch");
    }""",
    "no-shadowing": r"""
    const int64_t values[] = {-2147483648LL, -5000, -1001, -1000, -999, -2, -1, 0, 1, 2, 333, 999, 1000, 1001, 5000,
        2147483647};
    for (unsigned i = 0; i < sizeof(values) / sizeof(values[0]); ++i) {
        if (tv_f_normalize((int32_t)values[i]) != ref_normalize(values[i])) FAIL("normalize mismatch");
    }""",
    "multi-error-repair": r"""
    const int32_t ranges[][3] = {{5,1,10},{1,1,10},{10,1,10},{0,1,10},{11,1,10},{-5,-10,-1},{3,3,3},{4,5,1}};
    for (unsigned i = 0; i < sizeof(ranges) / sizeof(ranges[0]); ++i) {
        int32_t x = ranges[i][0], lo = ranges[i][1], hi = ranges[i][2];
        if (tv_f_in_range(x, lo, hi) != (lo <= x && x <= hi)) FAIL("in_range mismatch");
    }
    const int32_t xs[] = {-2147483647, -9, -1, 0, 1, 9, 2147483647};
    for (unsigned i = 0; i < sizeof(xs) / sizeof(xs[0]); ++i) {
        if (tv_f_classify(xs[i]) != ref_classify(xs[i])) FAIL("classify mismatch");
        struct tv_s_Meter meter = {.tv_m_level = 5};
        int32_t change = (int32_t)(ref_classify(xs[i]) * 10);
        if (tv_f_boost(&meter, xs[i]) != change || meter.tv_m_level != 5 + change) FAIL("boost mismatch");
    }
    const int32_t small[] = {-1000, -3, 0, 4, 1000};
    for (unsigned i = 0; i < 5; ++i) {
        if (tv_f_scaled(small[i]) != small[i] * 2 + 3) FAIL("scaled mismatch");
        if (tv_f_sum3(small[i], 7, -2) != small[i] + 5) FAIL("sum3 mismatch");
        struct tv_s_Meter meter = {.tv_m_level = small[i]};
        if (tv_f_settle(meter) != small[i] * 2) FAIL("settle mismatch");
    }""",
}


def harness(task):
    return (_REFERENCES + "int main(void) {\n" + _CHECKS[task] +
            '\n    puts("native checks passed");\n    return 0;\n}\n')
