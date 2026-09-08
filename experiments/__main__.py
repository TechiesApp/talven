"""python3 -m experiments: run, report, and independently reverify."""

import argparse
import math
from pathlib import Path
import sys

from . import CORPUS_VERSION
from .protocol import encode, strict_json
from .runner import load_run, make_report, reverify, run_experiment
from .tasks import CORPORA, get_tasks


def bounded_int(low, high):
    def parse(text):
        value = int(text)
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(f"Expected {low} through {high}")
        return value
    return parse


def positive_seconds(text):
    value = float(text)
    if not math.isfinite(value) or not 0 < value <= 86400:
        raise argparse.ArgumentTypeError("Expected positive finite seconds up to 86400")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description="Reproducible Talven source-edit agent evaluation")
    commands = parser.add_subparsers(dest="command", required=True)
    tasks = commands.add_parser("tasks", help="Print the versioned public corpus")
    tasks.add_argument("--corpus", choices=CORPORA, default=CORPUS_VERSION)
    run = commands.add_parser("run", help="Run a trusted adapter; creates a new artifact directory")
    run.add_argument("--adapter", required=True, type=Path)
    run.add_argument("--out", required=True, type=Path)
    run.add_argument("--corpus", choices=CORPORA, default=CORPUS_VERSION)
    run.add_argument("--task", action="append", help="Task ID from the selected corpus; may be repeated")
    run.add_argument("--context", choices=("source", "compiler", "both"), default="both")
    run.add_argument("--repetitions", type=bounded_int(1, 100), default=1)
    run.add_argument("--max-repairs", type=bounded_int(0, 20), default=2)
    run.add_argument("--context-bytes", type=bounded_int(1, 1048576), default=16384)
    run.add_argument("--adapter-timeout", type=positive_seconds, default=60)
    run.add_argument("--native-timeout", type=positive_seconds, default=5)
    run.add_argument("--verification-timeout", type=positive_seconds, default=60)
    run.add_argument("--task-timeout", type=positive_seconds, default=300)
    run.add_argument("--cc", default="cc")
    report = commands.add_parser("report", help="Recompute accounting, optionally adding measured cost receipts")
    report.add_argument("directory", type=Path)
    report.add_argument("--verification-costs", type=Path)
    report.add_argument("--out", type=Path)
    check = commands.add_parser("reverify", help="Recheck final candidates using matching trusted compiler/harness inputs")
    check.add_argument("directory", type=Path)
    check.add_argument("--cc")
    check.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "tasks":
            value = get_tasks(args.corpus)
        elif args.command == "run":
            tasks = args.task or list(get_tasks(args.corpus))
            if len(set(tasks)) != len(tasks):
                raise ValueError("Duplicate task selection; use --repetitions instead")
            modes = ["source", "compiler"] if args.context == "both" else [args.context]
            limits = {key: getattr(args, key) for key in ("max_repairs", "context_bytes", "adapter_timeout",
                      "native_timeout", "verification_timeout", "task_timeout")}
            value = run_experiment(args.adapter, args.out, tasks, modes, args.repetitions, args.cc, limits,
                                   corpus_version=args.corpus)
            print(encode({"output": str(args.out.resolve()), **make_report(value)}), end="")
            return 2 if value["summary"]["error_tasks"] else 1 if value["summary"]["failed_tasks"] else 0
        elif args.command == "report":
            costs = strict_json(args.verification_costs.read_text(encoding="utf-8")) if args.verification_costs else None
            value = make_report(load_run(args.directory), costs)
        else:
            if args.out.exists():
                raise ValueError("Refusing to overwrite an existing reverification artifact")
            value = reverify(args.directory, args.cc)
        if getattr(args, "out", None):
            with args.out.open("x", encoding="utf-8") as file:
                file.write(encode(value))
        print(encode(value), end="")
        if args.command == "reverify":
            return 0 if value["trials"] and all(t["status"] == "passed" for t in value["trials"]) else 1
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"evaluation error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
