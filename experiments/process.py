"""Bounded trusted subprocesses. This is resource hygiene, not an OS sandbox."""

import base64
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


def run_process(argv, *, cwd, timeout, stdin=b"", max_bytes=4 * 1024 * 1024, start_new_session=True):
    started = time.monotonic()
    result = {"argv": list(argv), "returncode": None, "stdout": "", "stderr": "", "error": None}
    with tempfile.TemporaryDirectory(prefix="talven-process-") as temporary:
        base = Path(temporary)
        (base / "stdin").write_bytes(stdin)
        with (base / "stdin").open("rb") as incoming, (base / "stdout").open("w+b") as output, (base / "stderr").open("w+b") as errors:
            try:
                process = subprocess.Popen(argv, stdin=incoming, stdout=output, stderr=errors,
                                           cwd=cwd, start_new_session=start_new_session and os.name == "posix")
            except OSError as error:
                result["error"] = f"launch: {error}"
            else:
                try:
                    while True:
                        excessive = any(os.fstat(stream.fileno()).st_size > max_bytes for stream in (output, errors))
                        expired = time.monotonic() - started >= timeout
                        if excessive or expired:
                            result["error"] = "output_limit" if excessive else "timeout"
                        if result["error"] or process.poll() is not None:
                            break
                        time.sleep(0.01)
                finally:
                    # Cancellation must not leave potentially billable adapters
                    # or native verification running beyond their timeout.
                    try:
                        if start_new_session and os.name == "posix":
                            os.killpg(process.pid, signal.SIGKILL)
                        elif process.poll() is None:
                            process.kill()
                    except ProcessLookupError:
                        pass
                    except PermissionError:
                        # Some hosts restrict group signaling even for our
                        # own child. Reap the child and disclose the limit.
                        result["cleanup_warning"] = "Host denied process-group cleanup"
                        if process.poll() is None:
                            process.kill()
                    process.wait()
                    result["returncode"] = process.returncode
                for name, stream in (("stdout", output), ("stderr", errors)):
                    stream.seek(0)
                    data = stream.read(max_bytes)
                    result[name + "_sha256"] = hashlib.sha256(data).hexdigest()
                    try:
                        result[name] = data.decode("utf-8")
                    except UnicodeError:
                        result["error"] = result["error"] or "invalid_utf8"
                        result[name] = data.decode("utf-8", errors="replace")
                        result[name + "_base64"] = base64.b64encode(data).decode("ascii")
    result["elapsed_seconds"] = time.monotonic() - started
    return result
