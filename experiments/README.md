# Agent evaluation protocol for M1a

Status: task definitions; no comparative model runs or token savings have been measured.

Use the same repository revision, prototype guide, task instructions, and verification criteria for each agent. Start each task in an isolated checkout. Give the agent the M1a grammar and the relevant compiler context, with an initial context-output budget of 16384 bytes. Keep the compiler and verification commands outside the agent's edit set for the experiment.

| Task | Starting point | Requested change | Independent acceptance |
| --- | --- | --- | --- |
| Preserve a scalar across a move | `examples/invalid/moved.tal` | Return the original scalar value after transferring the record; preserve a real record move | `check` passes; inspect that the move remains; native exit status is 7 |
| Repair a strict type error | `examples/invalid/type.tal` | Return integer 1 through the `count` binding | `check` passes; native exit status is 1; return type remains i32 |
| Change a record contract | `examples/vectors.tal` | Rename Vec2 field `x` to `horizontal` at declaration and every use | `check` passes; verify the old field is absent; native example exits zero |
| Extend a calculation | `examples/vectors.tal` | Add `squared_length(value: Vec2) -> i32` and make main verify that (3,4) has squared length 25 | `check` passes; reviewer-controlled C/native test exercises the new function on multiple vectors |

For the last task, generate a freestanding C translation unit and link a reviewer-controlled harness against `tv_f_squared_length`. This emitted symbol spelling is a prototype testing interface, not a stable foreign ABI.

Record provider, exact model/version, tokenizer, prompts, tool permissions, compiler/context hashes, source revision, target, tool invocations, actual input/output tokens, repair attempts, wall time, and acceptance results. Report provider cache metrics separately if available. Do not estimate subscription usage from API price or infer tokens from UTF-8 bytes.

First compare the same agent using source-only context versus compiler context. Language-to-language comparisons with Rust/C/TypeScript require equivalent tasks and independently validated baselines; this change does not supply or claim those results.

Agents may edit only task source files. The protected verifier must check the edit scope and task-specific acceptance, not just accept a successful compiler exit. A malicious edit can replace a test with an unconditional success. Repository instructions document that rule; an external runner must enforce it.
