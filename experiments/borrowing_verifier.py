"""Reviewer-owned acceptance for the bounded borrowing corpus.

Public task text, starter programs, and scripted repairs are not acceptance
oracles. This module fixes the protected contracts and computes native expected
values independently. A second native build records calls to the preserved
helpers, including pointee identity, amounts, order, and sensitivity to their
return values. This is finite public acceptance, not a proof of equivalence or
a foreign ABI guarantee.
"""

from talven.backend import signature
from talven.frontend import lex


TASK_IDS = {"borrow-overlap", "borrow-permission", "borrow-reborrow", "borrow-order"}
HELPERS = {
    "read": "fn read(c: &Counter) -> i32 { return c.value; }",
    "add": """fn add(c: &mut Counter, delta: i32) -> i32 {
        c.value = c.value + delta;
        return c.value;
    }""",
    "with_before": """fn with_before(c: &mut Counter, before: i32, delta: i32) -> i32 {
        let after = add(&mut c, delta);
        return before * 100 + after;
    }""",
}


def _tokens(source):
    return [(token.kind, token.text) for token in lex(source)]


def _expressions(expr):
    yield expr
    for child in expr.args:
        yield from _expressions(child)
    for _, child in expr.fields:
        yield from _expressions(child)


def structure(task, analysis):
    record = analysis.records.get("Counter")
    if (set(analysis.records) != {"Counter"} or record is None or
            [(n.text, t.text) for n, t in record.fields] != [("value", "i32")]):
        return False, "preserve exactly struct Counter { value: i32 }"
    helpers = {"read", "add", "with_before"} if task == "borrow-overlap" else {"read", "add"}
    if set(analysis.functions) != helpers | {"exercise", "main"}:
        return False, "preserve the existing function set; do not add or remove helpers"
    for name in sorted(helpers):
        fn = analysis.functions[name]
        if _tokens(analysis.source[fn.span.start:fn.span.end]) != _tokens(HELPERS[name]):
            return False, f"preserve {name}'s signature and body; only comments/layout may change"
    expected, final = {"borrow-permission": (8, 8), "borrow-order": (50811, 11)}.get(task, (508, 8))
    main = f"""fn main() -> i32 {{
        let mut counter = Counter {{ value: 5 }};
        let result = exercise(&mut counter, 3);
        if (result != {expected}) {{ return 1; }}
        if (read(&counter) != {final}) {{ return 2; }}
        return 0;
    }}"""
    fn = analysis.functions["main"]
    if _tokens(analysis.source[fn.span.start:fn.span.end]) != _tokens(main):
        return False, "preserve main's example and both executable checks, using a let mut counter owner"
    exercise = analysis.functions["exercise"]
    if (exercise.result.text != "i32" or
            [(n.text, t.text) for n, t in exercise.params] != [("c", "&mut Counter"), ("delta", "i32")]):
        return False, "require fn exercise(c: &mut Counter, delta: i32) -> i32"
    body = exercise.body
    if (not body or body[-1].kind != "return" or
            any(s.kind not in {"let", "expr"} for s in body[:-1]) or
            any(s.kind == "expr" and s.expr.kind != "call" for s in body[:-1]) or
            any(e.kind == "record" for s in body for e in _expressions(s.expr))):
        return False, "exercise requires straight-line bindings/call statements and a final return; no record construction or assignment"
    return True, "protected helpers/main and bounded exercise contract preserved"


def instrument(analysis, generated):
    """Wrap emitted helper definitions, leaving Talven call sites unchanged.

    Exact backend signatures identify definitions only. Prototypes and calls
    continue to use tv_f_* and therefore enter the observing wrappers. Original
    helper bodies remain present under private verifier names. The wrappers
    retain their mutations and add independent offsets only to returned values.
    """
    names = [name for name in HELPERS if name in analysis.functions]
    for name in names:
        header = signature(analysis.functions[name]) + " {"
        if generated.count(header) != 1:
            raise ValueError("Cannot identify emitted borrowing helper definition")
        renamed = header.replace(f"tv_f_{name}(", f"tv_eval_original_{name}(", 1)
        generated = generated.replace(header, renamed, 1)
    generated += """
static const struct tv_s_Counter *tv_eval_owner;
static int32_t tv_eval_delta, tv_eval_before;
static int32_t tv_eval_offsets[4];
static char tv_eval_trace[16];
static unsigned tv_eval_count, tv_eval_reads, tv_eval_adds;
static int tv_eval_bad;
static void tv_eval_observe(char event, const struct tv_s_Counter *owner) {
    if (owner != tv_eval_owner) { tv_eval_bad = 1; }
    if (tv_eval_count < sizeof(tv_eval_trace)) { tv_eval_trace[tv_eval_count++] = event; }
    else { tv_eval_bad = 1; }
}
int32_t tv_f_read(const struct tv_s_Counter *c) {
    tv_eval_observe('R', c);
    int32_t value = tv_eval_original_read(c);
    unsigned index = tv_eval_reads++;
    if (index >= 2) { tv_eval_bad = 1; return value; }
    return tv_add(value, tv_eval_offsets[index]);
}
int32_t tv_f_add(struct tv_s_Counter *c, int32_t delta) {
    tv_eval_observe('A', c);
    if (delta != tv_eval_delta) { tv_eval_bad = 1; }
    int32_t value = tv_eval_original_add(c, delta);
    unsigned index = tv_eval_adds++;
    if (index >= 2) { tv_eval_bad = 1; return value; }
    return tv_add(value, tv_eval_offsets[2 + index]);
}
"""
    if "with_before" in names:
        generated += """
int32_t tv_f_with_before(struct tv_s_Counter *c, int32_t before, int32_t delta) {
    tv_eval_observe('W', c);
    if (before != tv_eval_before + tv_eval_offsets[0] || delta != tv_eval_delta) { tv_eval_bad = 1; }
    return tv_eval_original_with_before(c, before, delta);
}
"""
    return generated


def harness(task, *, trace=False):
    expected = {"borrow-permission": "after", "borrow-order": "before*10000 + after*100 + final"}.get(
        task, "before*100 + after")
    increments = 2 if task == "borrow-order" else 1
    sequence = {"borrow-overlap": "RWA", "borrow-permission": "AR", "borrow-reborrow": "RAR",
                "borrow-order": "RAA"}[task]
    reset = """tv_eval_owner = &counter; tv_eval_before = before; tv_eval_delta = delta;
               tv_eval_count = 0; tv_eval_reads = 0; tv_eval_adds = 0; tv_eval_bad = 0;
               for (unsigned k = 0; k < 4; ++k) { tv_eval_offsets[k] = offsets[probe][k]; }""" if trace else ""
    # Probe each input twice. Independent signed add offsets distinguish
    # retaining both call results from rebuilding the first from the second.
    probes = """    const int32_t offsets[][4] = {{17,-19,11,-13}, {-7,23,-5,29}};
    for (unsigned probe = 0; probe < sizeof(offsets)/sizeof(offsets[0]); ++probe) {
""" if trace else ""
    end_probes = "    }\n" if trace else ""
    if trace:
        expected = {
            "borrow-overlap": "(before + tv_eval_offsets[0])*100 + (after + tv_eval_offsets[2])",
            "borrow-permission": "after + tv_eval_offsets[0]",
            "borrow-reborrow": "(before + tv_eval_offsets[0])*100 + (after + tv_eval_offsets[1])",
            "borrow-order": "(before + tv_eval_offsets[0])*10000 + (after + tv_eval_offsets[2])*100 + (final + tv_eval_offsets[3])",
        }[task]
    observed = f"""
        const char wanted[] = "{sequence}";
        if (tv_eval_bad || tv_eval_count != sizeof(wanted)-1) {{
            puts("helper count, pointee, snapshot, or delta mismatch"); return 1;
        }}
        for (unsigned j = 0; j < sizeof(wanted)-1; ++j) {{
            if (tv_eval_trace[j] != wanted[j]) {{ puts("helper order mismatch"); return 1; }}
        }}""" if trace else ""
    main_check = "" if trace else 'if (tv_f_main() != 0) { puts("main checks failed"); return 1; }'
    return f"""int main(void) {{
    {main_check}
    const int32_t values[][2] = {{
        {{5,3}}, {{0,0}}, {{0,4}}, {{7,0}}, {{-5,3}},
        {{5,-3}}, {{-7,-2}}, {{12,5}}, {{-2,7}}, {{3,-5}}
    }};
{probes}    for (unsigned i = 0; i < sizeof(values)/sizeof(values[0]); ++i) {{
        int32_t before = values[i][0], delta = values[i][1];
        int32_t after = before + delta, final = before + {increments}*delta;
        struct tv_s_Counter counter = {{.tv_m_value=before}};
        {reset}
        int32_t result = tv_f_exercise(&counter, delta);
        if (result != {expected} || counter.tv_m_value != final) {{
            puts("exercise result or original record mutation mismatch"); return 1;
        }}
        {observed}
    }}
{end_probes}    puts("borrowing checks passed"); return 0;
}}
"""
