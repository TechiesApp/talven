# Supplied-block production cost fixture

This fixture measures the implemented experimental `m2-supplied-blocks-v1`
profile. The [measurement guide](../../docs/resource-costs.md) and
[proposal](../../docs/proposals/0044-supplied-block-production-costs.md) define the
receipt, target scope, and interpretation of production costs.

Run from the repository root with an already-built independent Rust producer:

~~~sh
python3 scripts/measure-resource-costs.py \
  --native experiments/native-compiler/target/release/talven-native \
  --out build/resource-costs-local \
  --environment-note 'local development host'
~~~

The output directory must be new. The runner retains original Talven source,
generated C, compiler identities, flags, binaries, stack evidence, acceptance
results, and timing batches. Capacities 1, 32, and 4096 are produced by replacing
each literal `storage(32)` in [workload.tal](workload.tal). This is a bounded
fixture, not a general allocator benchmark or evidence of live-agent benefit.

## Source workloads and fixed inputs

All entry points accept `(size: i32, alignment: i32, index: i32)` and return zero
on success, `-10` for invalid requests, `-20` for exhaustion, or `-30` for an
out-of-bounds byte operation. The hosted `main` returns zero.

| Driver workload | Function | Successful behavior per call |
| --- | --- | --- |
| 0 | `cycle` | Initialize one region, reserve, read a zero byte, release |
| 1 | `reuse` | Initialize one region, reserve, write and read 137, release, reserve again, read zero, release |
| 2 | `sequential` | Complete reserve/read-zero/release in each of two disjoint lexical regions |

Every timed batch cycles through these four rows in order:

| Row | Size | Alignment | Index |
| --- | --- | --- | --- |
| 0 | 1 | 1 | 0 |
| 1 | capacity | 16 | capacity - 1 |
| 2 | (capacity + 1) / 2 | 2 | size - 1 |
| 3 | capacity | 8 | 0 |

The division is integer division. These rows remain valid at capacity 1.
Untimed preflight calls every function with sizes 0 and -1, alignments 3 and 32,
size capacity + 1, negative and one-past-end byte indices, and all success rows.

## Independent acceptance and production timing

[driver.c](driver.c) has two build modes. Production uses only extern scalar
prototypes `tv_f_cycle`, `tv_f_reuse`, and `tv_f_sequential`; generated C is
compiled separately with its hosted entry renamed using
`-Dmain=tv_generated_main`. Compile the driver with `-DTEST_CAPACITY=N`, link the
generated object, then execute `DRIVER WORKLOAD ITERATIONS`. Workload is 0..2;
iterations are a positive multiple of four, at most 10,000,000.

After preflight, production uses one `CLOCK_MONOTONIC` start/end pair around the
complete batch, with `clock_getres` outside that interval. The timed loop
includes an indirect source-function call, row selection, and result/checksum
accumulation. All results must be zero, and the checksum must equal
`iterations / 4 * 10`; checks occur after the end timestamp. Success writes one
JSON object with exactly `workload`, `iterations`, `checksum`, `elapsed_ns`, and
`resolution_ns`, and leaves stderr empty. Batch time is not isolated intrinsic
latency.

The independent acceptance build uses `-DCOST_LEDGER
-DTV_REGION_SOURCE_TEST -DTEST_CAPACITY=N`, includes a sibling `generated.c`, and
executes without arguments. Success leaves stdout and stderr empty. It performs
no timing. The expected event order, region lifetime count, reserve/read/write/
release counts, backing bytes, zeroed bytes, bounds, and release tokens derive
from the fixed call inputs. A trusted callback initializes every backing byte
to a sentinel and compares the complete range against independent expected
bytes after every event. Reuse must erase the written byte; bytes beyond the
requested visible range must retain their sentinel. Each complete call must
leave no live owner. The runner requires this new fixture's ledger at O0 and O2
under ASan/UBSan independently of the broader source acceptance workload.

Production does not define either ledger macro or contain a callback dependency.
Generated symbols are internal experimental lowering details, not a supported
foreign ownership interface.

## Layout probe

[layout.c](layout.c) includes sibling `generated.c` with its hosted entry renamed.
It reports actual C11 `sizeof`, `_Alignof`, and explicit `offsetof` values for
`tv_region`, `tv_block`, `tv_allocation`, `tv_str`, and the emitted nominal
`tv_s_Allocation`, `tv_s_ByteRead`, and `tv_s_ByteWrite` structs. Each JSON entry
contains `size`, `alignment`, and `offsets`. These are target/toolchain results;
the probe does not predict descriptor padding, total stack use, or lifetime
overlap. Compiler stack evidence is recorded separately.
