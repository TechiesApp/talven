"""Run bounded source-edit experiments and retain auditable artifacts."""

from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import time

from talven import VERSION, PROFILE
from talven.context import compiler_hash, context
from talven.frontend import CompileError, analyze
from . import CORPUS_VERSION, SCHEMA
from .metrics import aggregate, summarize_trial
from .process import run_process
from .protocol import candidate_source, digest, encode, parse_response, read_config, strict_json
from .tasks import TASKS


ROOT = Path(__file__).resolve().parents[1]
GUIDES = ("docs/prototype.md", "docs/borrowing.md")


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encode(value), encoding="utf-8")
    temporary.replace(path)


def pinned_files():
    files = {ROOT / name for name in GUIDES}
    files.update(ROOT / task["source"] for task in TASKS.values())
    for package in ("talven", "experiments"):
        files.update((ROOT / package).rglob("*.py"))
    return {str(path.relative_to(ROOT)): path.read_bytes() for path in sorted(files)}


def assert_unchanged(hashes, adapter=None):
    current = {name: digest(data) for name, data in pinned_files().items()}
    if current != hashes:
        raise ValueError("Pinned compiler, harness, guide, or task inputs changed; stop and start a new run")
    if adapter:
        for name, expected in adapter["artifact_hashes"].items():
            if digest(Path(name).read_bytes()) != expected:
                raise ValueError("Pinned adapter artifact changed during the run")


def environment(cc):
    def probe(argv):
        result = run_process(argv, cwd=ROOT, timeout=10)
        if result["error"] or result["returncode"] != 0:
            raise ValueError(f"Cannot record environment: {argv}: {result['error'] or result['stderr']}")
        return result["stdout"].strip()
    executable = shutil.which(cc)
    if executable is None:
        raise ValueError(f"Native C compiler not found: {cc}")
    executable = str(Path(executable).resolve())
    return {
        "repository_revision": probe(["git", "rev-parse", "HEAD"]),
        "repository_dirty": bool(probe(["git", "status", "--porcelain"])),
        "system": platform.system(), "release": platform.release(), "machine": platform.machine(),
        "processor": platform.processor() or None, "logical_cpus": os.cpu_count(),
        "python": platform.python_version(), "python_implementation": platform.python_implementation(),
        "compiler_version": VERSION, "language_profile": PROFILE, "compiler_hash": compiler_hash(),
        "cc": executable, "cc_sha256": digest(Path(executable).read_bytes()),
        "cc_version": probe([executable, "--version"]), "cc_target": probe([executable, "-dumpmachine"]),
        "c_flags": ["-std=c11", "-O2"],
    }


def compiler_context(source, budget):
    try:
        return context(analyze(source), max_bytes=budget)
    except CompileError as error:
        if error.code == "E0502":
            raise ValueError("Compiler context exceeds the configured byte budget") from error
        diagnostic = encode({"schema": "talven.diagnostics.v1", "ok": False,
                             "diagnostics": [error.diagnostic(source)]})
        if len(diagnostic.encode("utf-8")) > budget:
            raise ValueError("Compiler diagnostic exceeds the configured context byte budget")
        return diagnostic


def verify_candidate(task_id, candidate, env, timeout, native_timeout):
    command = [sys.executable, "-m", "experiments.verifier", "--task", task_id,
               "--source", str(candidate), "--cc", env["cc"], "--timeout", str(native_timeout)]
    process = run_process(command, cwd=ROOT, timeout=timeout)
    if process["error"]:
        return {"status": "error", "feedback": "Verifier process failed: " + process["error"], "process": process}
    try:
        result = strict_json(process["stdout"])
        if not isinstance(result, dict) or result.get("status") not in ("passed", "failed", "error"):
            raise ValueError("Invalid verifier result")
        # Verifier exit codes may reflect rejection, but never accept a crashed process.
        if result["status"] == "passed" and process["returncode"] != 0:
            raise ValueError("Verifier reported success with a failing process exit")
    except ValueError as error:
        return {"status": "error", "feedback": str(error), "process": process}
    return {**result, "process": process}


def trial_id(task, mode, repetition):
    return f"{task}-{mode}-{repetition:03d}"


def run_trial(task_id, mode, repetition, run_dir, config, env, inputs, hashes, limits, checkpoint):
    identifier = trial_id(task_id, mode, repetition)
    directory = run_dir / identifier
    directory.mkdir()
    source = inputs[TASKS[task_id]["source"]].decode("utf-8")
    started = time.monotonic()
    result = {"id": identifier, "task": task_id, "context_mode": mode, "repetition": repetition,
              "status": "error", "attempts": [], "elapsed_seconds": 0.0}
    system = ("You are editing a Talven M1c program. Follow the task and the pinned guides. "
              "Independent tests are controlled by the runner. Return a JSON object with an edits "
              "object containing exactly one key, task.tal, whose value is the complete replacement "
              "source. Do not request tools or edit any other file.\n\n" +
              "\n\n".join(f"--- {name} ---\n{inputs[name].decode('utf-8')}" for name in GUIDES))
    messages = [{"role": "system", "content": system}]
    feedback = None

    def save():
        result["elapsed_seconds"] = time.monotonic() - started
        result["metrics"] = summarize_trial(result["attempts"], config["kind"])
        write_json(directory / "trial.json", result)
        checkpoint(result)

    for attempt_index in range(limits["max_repairs"] + 1):
        remaining = limits["task_timeout"] - (time.monotonic() - started)
        if remaining <= 0:
            result.update(status="error", error="task_timeout")
            break
        try:
            assert_unchanged(hashes, config)
            payload = {"instruction": TASKS[task_id]["instruction"], "source": source, "feedback": feedback}
            if mode == "compiler":
                payload["compiler_context"] = compiler_context(source, limits["context_bytes"])
            messages.append({"role": "user", "content": encode(payload)})
        except (ValueError, OSError, UnicodeError) as error:
            result.update(status="error", error=str(error))
            break
        attempt_dir = directory / f"attempt-{attempt_index:03d}"
        attempt_dir.mkdir()
        request = {"schema": "talven.eval.request.v1", "corpus_version": CORPUS_VERSION,
                   "task_id": task_id, "context_mode": mode, "repetition": repetition,
                   "attempt": attempt_index, "allowed_files": ["task.tal"],
                   "model": {key: config[key] for key in ("provider", "model", "tokenizer", "settings")},
                   "messages": messages}
        request_bytes = encode(request).encode("utf-8")
        (attempt_dir / "request.json").write_bytes(request_bytes)
        attempt = {"index": attempt_index, "request_sha256": digest(request_bytes), "usage": None,
                   "status": "error", "verification": None}
        result["attempts"].append(attempt)
        save()  # Preserve the in-flight attempt before invoking a possibly billable adapter.
        with tempfile.TemporaryDirectory(prefix="talven-adapter-") as isolated:
            process = run_process(config["command"], cwd=isolated,
                                  timeout=min(remaining, limits["adapter_timeout"]), stdin=request_bytes)
        attempt["adapter_process"] = process
        (attempt_dir / "response.txt").write_text(process["stdout"], encoding="utf-8")
        attempt["response_sha256"] = digest(process["stdout"].encode("utf-8"))
        try:
            assert_unchanged(hashes, config)
            # A failing adapter can still return a valid billing receipt. Keep
            # that observed usage even though no candidate will be accepted.
            response, usage = parse_response(process["stdout"])
            attempt["usage"] = usage
            if process["error"] or process["returncode"] != 0:
                raise ValueError(f"Adapter failed: {process['error'] or process['returncode']}")
        except (ValueError, OSError) as error:
            attempt["error"] = str(error)
            result.update(status="error", error=str(error))
            save()
            break
        messages.append({"role": "assistant", "content": encode({"edits": response.get("edits")})})
        try:
            candidate = candidate_source(response)
        except ValueError as error:
            attempt.update(status="failed", error=str(error))
            feedback = str(error)
            result["status"] = "failed"
            save()
            continue
        source = candidate
        candidate_path = attempt_dir / "task.tal"
        candidate_path.write_text(source, encoding="utf-8")
        attempt["source_sha256"] = digest(source.encode("utf-8"))
        remaining = limits["task_timeout"] - (time.monotonic() - started)
        if remaining <= 0:
            verification = {"status": "error", "feedback": "Task time budget exhausted before verification"}
        else:
            verification = verify_candidate(task_id, candidate_path, env,
                                            min(remaining, limits["verification_timeout"]), limits["native_timeout"])
        attempt["verification"] = verification
        attempt["status"] = verification["status"]
        write_json(attempt_dir / "verification.json", verification)
        result["status"] = verification["status"]
        feedback = verification.get("feedback", "Independent acceptance failed")
        save()
        if result["status"] != "failed":
            break
    save()
    return result


def make_report(run, costs=None):
    costs = costs or {}
    known_ids = {t["id"] for t in run["trials"]}
    if not isinstance(costs, dict) or costs.keys() - known_ids:
        raise ValueError("Verification cost receipts must be keyed by existing trial IDs")
    trials = [{**trial, "metrics": summarize_trial(trial["attempts"], run["measurement_kind"], costs.get(trial["id"]))}
              for trial in run["trials"]]
    report = {"schema": "talven.eval.report.v1", "measurement_kind": run["measurement_kind"],
            "cost_scope": "model + adapter tools + measured verification; excludes human labor",
            "run_complete": run["complete"], "planned_trials": run["planned_trials"],
            "summary": aggregate(trials),
            "by_context": {mode: aggregate([t for t in trials if t["context_mode"] == mode])
                           for mode in sorted({t["context_mode"] for t in trials})},
            "trials": [{key: t[key] for key in ("id", "status", "metrics", "elapsed_seconds")} for t in trials],
            "verification_cost_receipts": costs}
    # An interrupted suite must not masquerade as a smaller successful one.
    if not run["complete"]:
        for summary in [report["summary"], *report["by_context"].values()]:
            summary["correctness_rate"] = None
            summary["total_task_cost_usd"] = None
            summary["cost_per_correct_task_usd"] = None
    return report


def run_experiment(adapter_path, output, tasks, modes, repetitions, cc, limits):
    config = read_config(adapter_path)
    env = environment(cc)
    inputs = pinned_files()
    hashes = {name: digest(data) for name, data in inputs.items()}
    run_dir = Path(output).resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "adapter-config.json").write_bytes(Path(adapter_path).read_bytes())
    adapter_dir = run_dir / "adapter-artifacts"
    adapter_dir.mkdir()
    for name, expected in config["artifact_hashes"].items():
        data = Path(name).read_bytes()
        if digest(data) != expected:
            raise ValueError("Adapter changed before artifact capture")
        (adapter_dir / expected).write_bytes(data)
    for name, data in inputs.items():
        destination = run_dir / "inputs" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    run = {"schema": SCHEMA, "corpus_version": CORPUS_VERSION, "measurement_kind": config["kind"],
           "started_at": datetime.now(timezone.utc).isoformat(), "complete": False,
           "planned_trials": len(tasks) * len(modes) * repetitions,
           "environment": env, "adapter": config, "input_hashes": hashes,
           "limits": limits, "task_order": tasks, "context_order": modes, "repetitions": repetitions,
           "tool_permissions": "source replacement only; no model tools; trusted adapter command",
           "trials": []}

    def checkpoint(trial=None):
        if trial is not None:
            for index, existing in enumerate(run["trials"]):
                if existing["id"] == trial["id"]:
                    run["trials"][index] = trial
                    break
            else:
                run["trials"].append(trial)
        report = make_report(run)
        run["summary"] = report["summary"]
        write_json(run_dir / "run.json", run)
        write_json(run_dir / "report.json", report)

    checkpoint()
    for repetition in range(1, repetitions + 1):
        for task in tasks:
            for mode in modes:
                run_trial(task, mode, repetition, run_dir, config, env, inputs, hashes, limits, checkpoint)
                assert_unchanged(hashes, config)
    run["complete"] = True
    checkpoint()
    return run


def load_run(directory):
    run = strict_json((Path(directory) / "run.json").read_text(encoding="utf-8"))
    if not isinstance(run, dict) or run.get("schema") != SCHEMA or run.get("corpus_version") != CORPUS_VERSION:
        raise ValueError("Unsupported evaluation run schema or corpus")
    return run


def reverify(directory, cc=None):
    directory = Path(directory).resolve()
    run = load_run(directory)
    assert_unchanged(run["input_hashes"])
    # Archived metadata is untrusted data, never authority to select a program.
    env = environment(cc or "cc")
    limits = run["limits"]
    for name in ("verification_timeout", "native_timeout"):
        value = limits[name]
        if type(value) not in (int, float) or not 0 < value <= 86400:
            raise ValueError("Invalid archived verification timeout")
    results = []
    for trial in run["trials"]:
        task, mode, repetition = trial["task"], trial["context_mode"], trial["repetition"]
        if task not in TASKS or mode not in ("source", "compiler") or type(repetition) is not int or not 1 <= repetition <= 100:
            raise ValueError("Invalid trial identity")
        if trial["id"] != trial_id(task, mode, repetition):
            raise ValueError("Trial ID does not match its inputs")
        attempts = trial["attempts"]
        last = attempts[-1] if attempts else {}
        if "source_sha256" not in last:
            results.append({"id": trial["id"], "status": "error", "feedback": "No final candidate to reverify"})
            continue
        index = last["index"]
        if type(index) is not int or not 0 <= index <= 20:
            raise ValueError("Invalid attempt index")
        candidate = (directory / trial["id"] / f"attempt-{index:03d}" / "task.tal").resolve()
        if not candidate.is_relative_to(directory) or candidate.stat().st_size > 256 * 1024 or digest(candidate.read_bytes()) != last["source_sha256"]:
            raise ValueError("Candidate artifact changed or escaped the run directory")
        result = verify_candidate(task, candidate, env, run["limits"]["verification_timeout"], run["limits"]["native_timeout"])
        results.append({"id": trial["id"], **result})
    return {"schema": "talven.eval.reverification.v1", "environment": env, "trials": results,
            "note": "Fresh correctness checks only; no new model usage or billing measurements"}
