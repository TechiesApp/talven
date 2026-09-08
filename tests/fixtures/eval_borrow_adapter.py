"""Offline borrowing fixture: unchanged first attempt, hand-written repair next.

This script has no provider dependency and reports no token or cost measurements.
"""

import argparse
import json
from pathlib import Path
import sys


PREFIX = """struct Counter { value: i32 }
fn read(c: &Counter) -> i32 { return c.value; }
fn add(c: &mut Counter, delta: i32) -> i32 {
    c.value = c.value + delta;
    return c.value;
}
"""
BODIES = {
    "borrow-overlap": """fn with_before(c: &mut Counter, before: i32, delta: i32) -> i32 {
    let after = add(&mut c, delta);
    return before * 100 + after;
}
fn exercise(c: &mut Counter, delta: i32) -> i32 {
    let snapshot = read(&c);
    return with_before(&mut c, snapshot, delta);
}
""",
    "borrow-permission": """fn exercise(c: &mut Counter, delta: i32) -> i32 {
    add(&mut c, delta);
    return read(&c);
}
""",
    "borrow-reborrow": """fn exercise(c: &mut Counter, delta: i32) -> i32 {
    let before = read(&c);
    add(&mut c, delta);
    return before * 100 + read(&c);
}
""",
    "borrow-order": """fn exercise(c: &mut Counter, delta: i32) -> i32 {
    let before = read(&c);
    let after = add(&mut c, delta);
    let second = add(&mut c, delta);
    return before * 10000 + after * 100 + second;
}
""",
}
SOLUTIONS = {}
for task, body in BODIES.items():
    expected = {"borrow-permission": 8, "borrow-order": 50811}.get(task, 508)
    final = 11 if task == "borrow-order" else 8
    SOLUTIONS[task] = PREFIX + body + f"""fn main() -> i32 {{
    let mut counter = Counter {{ value: 5 }};
    let result = exercise(&mut counter, 3);
    if (result != {expected}) {{ return 1; }}
    if (read(&counter) != {final}) {{ return 2; }}
    return 0;
}}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-config", type=Path)
    args = parser.parse_args()
    if args.write_config:
        script = str(Path(__file__).resolve())
        config = {"schema": "talven.eval.adapter.v1", "kind": "fixture", "provider": "none",
                  "model": "scripted-borrow-repair-fixture-v1", "tokenizer": "none", "settings": {},
                  "command": [sys.executable, script], "artifacts": [script]}
        args.write_config.parent.mkdir(parents=True, exist_ok=True)
        with args.write_config.open("x", encoding="utf-8") as output:
            json.dump(config, output, indent=2)
            output.write("\n")
        return
    request = json.load(sys.stdin)
    if request["corpus_version"] != "m1c-borrowing-tasks-v1":
        raise ValueError("This fixture supports only m1c-borrowing-tasks-v1")
    source = (json.loads(request["messages"][-1]["content"])["source"] if request["attempt"] == 0
              else SOLUTIONS[request["task_id"]])
    print(json.dumps({"schema": "talven.eval.response.v1", "edits": {"task.tal": source}, "usage": None,
                      "provider_metadata": {"fixture": True}}))


if __name__ == "__main__":
    main()
