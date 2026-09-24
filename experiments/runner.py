"""Run bounded source-edit experiments and retain auditable artifacts."""

from datetime import datetime, timezone
from decimal import Decimal
import os
import random
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import time

from talven import VERSION, PROFILE
from talven.context import agent_context, agent_diagnostics, compiler_hash
from talven.frontend import check_source
from . import CORPUS_VERSION, SCHEMA, SUPPORTED_SCHEMAS
from .metrics import aggregate, money, paired_comparison, summarize_trial
from .process import ADAPTER_ENVIRONMENT, TOOL_ENVIRONMENT, environment_subset, run_process
from .protocol import candidate_source, digest, encode, parse_response, read_config, strict_json
from .tasks import get_tasks


ROOT = Path(__file__).resolve().parents[1]
GUIDES = ("docs/language-reference.md",)


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encode(value), encoding="utf-8")
    temporary.replace(path)


def pinned_files(corpus_version=CORPUS_VERSION):
    tasks = get_tasks(corpus_version)
    files = {ROOT / name for name in GUIDES}
    files.update(ROOT / task["source"] for task in tasks.values())
    for package in ("talven", "experiments"):
        files.update((ROOT / package).rglob("*.py"))
    return {str(path.relative_to(ROOT)): path.read_bytes() for path in sorted(files)}


def assert_unchanged(hashes, adapter=None, corpus_version=CORPUS_VERSION):
    current = {name: digest(data) for name, data in pinned_files(corpus_version).items()}
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
    """Compact compiler facts for the prompt: program facts, or every recovered error."""
    analysis, errors = check_source(source)
    text = agent_diagnostics(source, errors) if errors else agent_context(analysis)
    if len(text.encode("utf-8")) > budget:
        raise ValueError("Compiler context exceeds the configured byte budget")
    return text


def verify_candidate(task_id, candidate, env, timeout, native_timeout):
    command = [sys.executable, "-m", "experiments.verifier", "--task", task_id,
               "--source", str(candidate), "--cc", env["cc"], "--timeout", str(native_timeout)]
    process = run_process(command, cwd=ROOT, timeout=timeout, env=environment_subset(TOOL_ENVIRONMENT))
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


def repair_feedback(verification, mode):
    """Feedback for the next attempt.

    Source-only trials learn that the language checks rejected a candidate,
    but never receive compiler diagnostic text; that is the compiler condition.
    """
    rejected = any(check.get("name") == "frontend" and not check.get("passed")
                   for check in verification.get("checks") or [])
    if mode == "source" and rejected:
        return "The candidate was rejected by the language checks before native acceptance."
    return verification.get("feedback") or "Independent acceptance failed"


class BudgetExhausted(Exception):
    """A live run stops before a call that could exceed its spend cap."""


class Budget:
    """Spend guard for live runs.

    Before each call, the recorded spend plus the most expensive call so far
    must stay within the cap. A call without a known cost stops the run,
    because the cap can no longer be enforced.
    """

    def __init__(self, cap_usd):
        self.cap = money(cap_usd)
        self.spent = Decimal(0)
        self.largest = Decimal(0)
        self.calls = 0
        self.stopped = None

    def before_call(self):
        if self.stopped is None and self.spent + self.largest > self.cap:
            self.stopped = "spend_cap"
        if self.stopped is not None:
            raise BudgetExhausted(self.stopped)

    def after_call(self, usage):
        self.calls += 1
        cost = None if usage is None else usage.get("model_cost_usd")
        if cost is None:
            self.stopped = "unknown_call_cost"
            return
        amount = money(cost) + money(usage.get("tool_cost_usd") or "0")
        self.spent += amount
        self.largest = max(self.largest, amount)

    def record(self):
        return {"cap_usd": str(self.cap), "spent_usd": str(self.spent), "largest_call_usd": str(self.largest),
                "calls": self.calls, "stopped": self.stopped}


def run_trial(task_id, mode, repetition, run_dir, config, env, inputs, hashes, limits, checkpoint,
              corpus_version=CORPUS_VERSION, budget=None):
    tasks = get_tasks(corpus_version)
    if task_id not in tasks:
        raise ValueError(f"Task {task_id!r} is not in corpus {corpus_version!r}")
    if budget is not None:
        budget.before_call()  # A trial that cannot start leaves no record.
    identifier = trial_id(task_id, mode, repetition)
    directory = run_dir / identifier
    directory.mkdir()
    source = inputs[tasks[task_id]["source"]].decode("utf-8")
    started = time.monotonic()
    result = {"id": identifier, "task": task_id, "context_mode": mode, "repetition": repetition,
              "status": "error", "attempts": [], "elapsed_seconds": 0.0}
    system = (f"You are editing a Talven program in language profile {PROFILE}. Follow the task and the "
              "pinned language reference. "
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
            assert_unchanged(hashes, config, corpus_version)
            payload = {"instruction": tasks[task_id]["instruction"], "source": source, "feedback": feedback}
            if mode == "compiler":
                payload["compiler_context"] = compiler_context(source, limits["context_bytes"])
            messages.append({"role": "user", "content": encode(payload)})
        except (ValueError, OSError, UnicodeError) as error:
            result.update(status="error", error=str(error))
            break
        if budget is not None:
            try:
                budget.before_call()
            except BudgetExhausted as stop:
                result.update(status="error", error=f"budget_stop: {stop}")
                save()
                raise
        attempt_dir = directory / f"attempt-{attempt_index:03d}"
        attempt_dir.mkdir()
        request = {"schema": "talven.eval.request.v1", "corpus_version": corpus_version,
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
                                  timeout=min(remaining, limits["adapter_timeout"]), stdin=request_bytes,
                                  env=environment_subset(ADAPTER_ENVIRONMENT))
        attempt["adapter_process"] = process
        (attempt_dir / "response.txt").write_text(process["stdout"], encoding="utf-8")
        attempt["response_sha256"] = digest(process["stdout"].encode("utf-8"))
        try:
            assert_unchanged(hashes, config, corpus_version)
            # A failing adapter can still return a valid billing receipt. Keep
            # that observed usage even though no candidate will be accepted.
            response, usage = parse_response(process["stdout"])
            attempt["usage"] = usage
            if budget is not None:
                budget.after_call(usage)
            if process["error"] or process["returncode"] != 0:
                raise ValueError(f"Adapter failed: {process['error'] or process['returncode']}")
        except (ValueError, OSError) as error:
            if budget is not None and attempt["usage"] is None:
                budget.after_call(None)
            attempt["error"] = str(error)
            result.update(status="error", error=str(error))
            save()
            break
        # Replay the model's own text when the adapter reports it, so repairs
        # see what was actually written rather than a re-encoding.
        metadata = response.get("provider_metadata") or {}
        text = metadata.get("candidate_text")
        messages.append({"role": "assistant", "content": text if isinstance(text, str) and text
                         else encode({"edits": response.get("edits")})})
        if isinstance(metadata.get("model_failure"), str):
            attempt["model_failure"] = metadata["model_failure"]
        try:
            candidate = candidate_source(response)
        except ValueError as error:
            attempt.update(status="failed", error=str(error))
            feedback = (f"The response ended with stop reason {attempt['model_failure']} before a complete edit."
                        if "model_failure" in attempt else str(error))
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
        feedback = repair_feedback(verification, mode)
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
    report = {"schema": "talven.eval.report.v1", "corpus_version": run.get("corpus_version", CORPUS_VERSION),
            "measurement_kind": run["measurement_kind"],
            "cost_scope": "model + adapter tools + measured verification; excludes human labor",
            "run_complete": run["complete"], "planned_trials": run["planned_trials"],
            "summary": aggregate(trials),
            "by_context": {mode: aggregate([t for t in trials if t["context_mode"] == mode])
                           for mode in sorted({t["context_mode"] for t in trials})},
            "paired": (paired_comparison(trials)
                       if {t["context_mode"] for t in trials} == {"source", "compiler"} and run["complete"] else None),
            "trials": [{key: t[key] for key in ("id", "status", "metrics", "elapsed_seconds")} for t in trials],
            "verification_cost_receipts": costs}
    # An interrupted suite must not masquerade as a smaller successful one.
    if not run["complete"]:
        for summary in [report["summary"], *report["by_context"].values()]:
            summary["correctness_rate"] = None
            summary["correctness_rate_excluding_errors"] = None
            summary["correctness_interval_95_excluding_errors"] = None
            summary["total_task_cost_usd"] = None
            summary["cost_per_correct_task_usd"] = None
    return report


def trial_plan(tasks, modes, repetitions, seed):
    """Every (repetition, task, mode) once; seeded shuffling interleaves
    conditions so time-varying provider behavior is not confounded with them."""
    plan = [(repetition, task, mode) for repetition in range(1, repetitions + 1)
            for task in tasks for mode in modes]
    if seed is not None:
        random.Random(seed).shuffle(plan)
    return plan


def run_experiment(adapter_path, output, tasks, modes, repetitions, cc, limits,
                   corpus_version=CORPUS_VERSION, seed=None, max_cost_usd=None, allow_dirty=False):
    corpus = get_tasks(corpus_version)
    for task in tasks:
        if task not in corpus:
            raise ValueError(f"Task {task!r} is not in corpus {corpus_version!r}")
    if len(set(tasks)) != len(tasks):
        raise ValueError("Duplicate task selection; use --repetitions instead")
    config = read_config(adapter_path)
    env = environment(cc)
    if config["kind"] == "live":
        if max_cost_usd is None:
            raise ValueError("Live runs require --max-cost-usd")
        if env["repository_dirty"] and not allow_dirty:
            raise ValueError("Live runs require a clean working tree; commit or pass --allow-dirty")
    budget = Budget(max_cost_usd) if max_cost_usd is not None else None
    plan = trial_plan(tasks, modes, repetitions, seed)
    inputs = pinned_files(corpus_version)
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
    run = {"schema": SCHEMA, "corpus_version": corpus_version, "measurement_kind": config["kind"],
           "started_at": datetime.now(timezone.utc).isoformat(), "complete": False,
           "planned_trials": len(tasks) * len(modes) * repetitions,
           "environment": env, "adapter": config, "input_hashes": hashes,
           "limits": limits, "task_order": tasks, "context_order": modes, "repetitions": repetitions,
           "order_seed": seed, "trial_order": [trial_id(task, mode, rep) for rep, task, mode in plan],
           "budget": budget.record() if budget else None,
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
        if budget is not None:
            run["budget"] = budget.record()
        report = make_report(run)
        run["summary"] = report["summary"]
        write_json(run_dir / "run.json", run)
        write_json(run_dir / "report.json", report)

    checkpoint()
    try:
        for repetition, task, mode in plan:
            run_trial(task, mode, repetition, run_dir, config, env, inputs, hashes, limits, checkpoint,
                      corpus_version, budget)
            assert_unchanged(hashes, config, corpus_version)
    except BudgetExhausted:
        checkpoint()  # An interrupted run stays incomplete; its rates are withheld.
        return run
    run["complete"] = True
    checkpoint()
    return run


def load_run(directory):
    run = strict_json((Path(directory) / "run.json").read_text(encoding="utf-8"))
    if not isinstance(run, dict) or run.get("schema") not in SUPPORTED_SCHEMAS:
        raise ValueError("Unsupported evaluation run schema or corpus")
    get_tasks(run.get("corpus_version"))
    return run


def reverify(directory, cc=None):
    directory = Path(directory).resolve()
    run = load_run(directory)
    corpus_version = run["corpus_version"]
    tasks = get_tasks(corpus_version)
    for task in run.get("task_order", []):
        if task not in tasks:
            raise ValueError(f"Archived task {task!r} is not in corpus {corpus_version!r}")
    for trial in run["trials"]:
        task, mode, repetition = trial["task"], trial["context_mode"], trial["repetition"]
        if task not in tasks or mode not in ("source", "compiler") or type(repetition) is not int or not 1 <= repetition <= 100:
            raise ValueError(f"Invalid trial identity for corpus {corpus_version!r}")
        if trial["id"] != trial_id(task, mode, repetition):
            raise ValueError("Trial ID does not match its inputs")
    assert_unchanged(run["input_hashes"], corpus_version=corpus_version)
    # Archived metadata is untrusted data, never authority to select a program.
    env = environment(cc or "cc")
    limits = run["limits"]
    for name in ("verification_timeout", "native_timeout"):
        value = limits[name]
        if type(value) not in (int, float) or not 0 < value <= 86400:
            raise ValueError("Invalid archived verification timeout")
    results = []
    for trial in run["trials"]:
        task = trial["task"]
        attempts = trial["attempts"]
        last = attempts[-1] if attempts else {}
        if "source_sha256" not in last:
            results.append({"id": trial["id"], "status": "error", "reverifiable": False,
                            "feedback": "No final candidate to reverify"})
            continue
        index = last["index"]
        if type(index) is not int or not 0 <= index <= 20:
            raise ValueError("Invalid attempt index")
        candidate = (directory / trial["id"] / f"attempt-{index:03d}" / "task.tal").resolve()
        if not candidate.is_relative_to(directory) or candidate.stat().st_size > 256 * 1024 or digest(candidate.read_bytes()) != last["source_sha256"]:
            raise ValueError("Candidate artifact changed or escaped the run directory")
        result = verify_candidate(task, candidate, env, run["limits"]["verification_timeout"], run["limits"]["native_timeout"])
        results.append({"id": trial["id"], **result})
    # Compare fresh verdicts with the archive: drift, not failure, is the signal.
    archived = {trial["id"]: trial["status"] for trial in run["trials"]}
    for result in results:
        result["archived_status"] = archived[result["id"]]
        if result.get("reverifiable", True):
            result["matches_archive"] = result["status"] == result["archived_status"]
        else:
            # Without a candidate there is nothing to recheck; a recorded pass would be inconsistent.
            result["matches_archive"] = result["archived_status"] != "passed"
    archived_cc = run.get("environment", {}).get("cc_sha256")
    return {"schema": "talven.eval.reverification.v2", "corpus_version": corpus_version,
            "environment": env, "trials": results,
            "matches_archive": all(result["matches_archive"] for result in results),
            "toolchain_matches_archive": archived_cc is not None and archived_cc == env.get("cc_sha256"),
            "note": "Fresh correctness checks only; no new model usage or billing measurements"}
