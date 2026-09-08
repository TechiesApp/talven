"""Scripted offline adapter. No model calls, token counts, or billing evidence.

Create its portable local config with:
python3 tests/fixtures/eval_adapter.py --write-config build/eval-fixture.json
"""

import argparse
import json
from pathlib import Path
import sys


SOLUTIONS = {
    "move-scalar": """struct Item { value: i32 }
fn main() -> i32 {
    let original = Item { value: 7 };
    let saved = original.value;
    let transferred = original;
    return saved;
}
""",
    "strict-type": """fn main() -> i32 {
    let count: i32 = 1;
    return count;
}
""",
    "rename-field": """struct Vec2 { horizontal: i32, y: i32 }
fn dot(a: Vec2, b: Vec2) -> i32 {
    return a.horizontal * b.horizontal + a.y * b.y;
}
fn main() -> i32 {
    let left = Vec2 { horizontal: 2, y: 3 };
    let right = Vec2 { horizontal: 4, y: 5 };
    if (dot(left, right) == 23) { return 0; } else { return 1; }
}
""",
    "squared-length": """struct Vec2 { x: i32, y: i32 }
fn dot(a: Vec2, b: Vec2) -> i32 { return a.x * b.x + a.y * b.y; }
fn squared_length(value: Vec2) -> i32 { return value.x * value.x + value.y * value.y; }
fn main() -> i32 {
    let left = Vec2 { x: 2, y: 3 };
    let right = Vec2 { x: 4, y: 5 };
    if (dot(left, right) != 23) { return 1; }
    let value = Vec2 { x: 3, y: 4 };
    if (squared_length(value) == 25) { return 0; } else { return 1; }
}
""",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-config", type=Path)
    args = parser.parse_args()
    if args.write_config:
        script = str(Path(__file__).resolve())
        config = {"schema": "talven.eval.adapter.v1", "kind": "fixture", "provider": "none",
                  "model": "scripted-repair-fixture-v1", "tokenizer": "none", "settings": {},
                  "command": [sys.executable, script], "artifacts": [script]}
        args.write_config.parent.mkdir(parents=True, exist_ok=True)
        with args.write_config.open("x", encoding="utf-8") as output:
            json.dump(config, output, indent=2)
            output.write("\n")
        return
    request = json.load(sys.stdin)
    # First attempt returns the original bug; the repair uses a hand-written
    # solution. This measures runner behavior, never agent effectiveness.
    source = (json.loads(request["messages"][-1]["content"])["source"] if request["attempt"] == 0
              else SOLUTIONS[request["task_id"]])
    print(json.dumps({"schema": "talven.eval.response.v1", "edits": {"task.tal": source}, "usage": None,
                      "provider_metadata": {"fixture": True}}))


if __name__ == "__main__":
    main()
