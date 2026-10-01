"""Execute the borrowing corpus with ASan/UBSan on a supported native host.

Separate from the portable unit suite: sanitizer runtimes need OS facilities
that restricted or traced development environments may not provide. CI requires
this check to pass; a missing tool, runtime failure, or timeout is a failure.
"""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from talven.backend import emit_c
from talven.frontend import analyze


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", type=Path, help="Already-built native compiler to validate instead of the reference")
    args = parser.parse_args()
    if not shutil.which("cc"):
        raise SystemExit("Sanitizer conformance requires cc")
    sources = [ROOT / "examples/borrowing.tal",
               ROOT / "tests/fixtures/borrowing-order.tal",
               ROOT / "tests/fixtures/borrowing-reborrow.tal"]
    executions = 0
    with tempfile.TemporaryDirectory() as temporary:
        cfile, binary = Path(temporary) / "program.c", Path(temporary) / "program"
        for source in sources:
            generated = emit_c(analyze(source.read_text(encoding="utf-8"))).encode("utf-8")
            if args.native:
                result = subprocess.run([str(args.native.resolve()), "emit-c", str(source)],
                                        capture_output=True, check=True, timeout=30)
                if result.stdout != generated:
                    raise SystemExit(f"{source.relative_to(ROOT)}: native C differs from reference")
                generated = result.stdout
            cfile.write_bytes(generated)
            for optimization in ("-O0", "-O2"):
                subprocess.run(["cc", "-std=c11", optimization, "-g", "-Wall", "-Wextra", "-Werror",
                                "-pedantic-errors", "-fsanitize=address,undefined",
                                "-fsanitize-address-use-after-scope", "-fno-sanitize-recover=all",
                                "-fno-omit-frame-pointer", str(cfile), "-o", str(binary)], check=True, timeout=30)
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                if result.returncode != 0 or result.stderr:
                    raise SystemExit(f"{source.relative_to(ROOT)} {optimization}: exit {result.returncode}\n{result.stderr}")
                executions += 1
    print(json.dumps({"borrow_sanitizer_executions": executions, "passed": True,
                      "compiler": "native" if args.native else "reference",
                      "sanitizers": ["address", "undefined"], "optimizations": ["-O0", "-O2"]}, sort_keys=True))


if __name__ == "__main__":
    main()
