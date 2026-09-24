"""Reviewer-owned acceptance for the large-program corpus.

Every declaration other than pipeline must be token-identical to the
generated starter, and pipeline must call each stage. The C harness simulates
the stages independently with 64-bit arithmetic and checks both the returned
value and the account's final balance over a grid of inputs.
"""

from talven.frontend import lex, parse

from .large_tasks import INPUTS, LARGE_TASKS, SOURCES, STAGES

TASK_IDS = set(LARGE_TASKS)


def _tokens(text):
    return [(token.kind, token.text) for token in lex(text) if token.kind != "eof"]


def _declarations(source):
    program = parse(source)
    items = {}
    for item in [*program.records, *program.functions]:
        items[item.name.text] = _tokens(source[item.span.start:item.span.end])
    return items


def _calls(expr, found):
    if expr.kind == "call":
        found.add(expr.value)
    for child in expr.args:
        _calls(child, found)
    for _, child in expr.fields:
        _calls(child, found)


def _statement_calls(statements, found):
    for statement in statements:
        for root in (statement.expr, statement.target):
            if root is not None:
                _calls(root, found)
        _statement_calls(statement.then, found)
        _statement_calls(statement.otherwise, found)


def structure(task, analysis):
    expected = _declarations(SOURCES[task])
    actual = _declarations(analysis.source)
    if set(actual) != set(expected):
        return False, "keep exactly the starter's struct and functions; add or remove nothing"
    for name, tokens in expected.items():
        if name != "pipeline" and actual[name] != tokens:
            return False, f"{name} must stay unchanged; only pipeline may be edited"
    fn = analysis.functions["pipeline"]
    if fn.signature() != "fn pipeline(a: &mut Account, v: i32) -> i32":
        return False, "keep fn pipeline(a: &mut Account, v: i32) -> i32"
    called = set()
    _statement_calls(fn.body, called)
    missing = [name for name, _, _ in STAGES[task] if name not in called]
    if missing:
        return False, f"pipeline must call every stage; missing {', '.join(missing)}"
    return True, "starter declarations preserved and every stage called"


def harness(task):
    steps = []
    for _, form, k in STAGES[task]:
        if form == "mut":
            steps.append(f"balance += running * {k}; running = balance;")
        elif form == "read":
            steps.append(f"running = balance - running * {k};")
        elif form == "consume":
            steps.append(f"running = balance + tier * {k} - running;")
        else:
            steps.append(f"running = running * {k} - 1;")
    rows = ", ".join("{%d, %d, %d, %d}" % row for row in INPUTS)
    return f"""int main(void) {{
    const int64_t inputs[][4] = {{{rows}}};
    for (unsigned i = 0; i < sizeof(inputs) / sizeof(inputs[0]); ++i) {{
        int64_t balance = inputs[i][0], tier = inputs[i][2], running = inputs[i][3];
        {" ".join(steps)}
        struct tv_s_Account account = {{.tv_m_balance = (int32_t)inputs[i][0], .tv_m_limit = (int32_t)inputs[i][1],
                                        .tv_m_tier = (int32_t)inputs[i][2]}};
        int32_t result = tv_f_pipeline(&account, (int32_t)inputs[i][3]);
        if (result != running) {{ puts("pipeline returned the wrong running value"); return 1; }}
        if (account.tv_m_balance != balance || account.tv_m_limit != inputs[i][1] || account.tv_m_tier != tier) {{
            puts("pipeline left the account in the wrong state"); return 1;
        }}
    }}
    puts("native checks passed");
    return 0;
}}
"""
