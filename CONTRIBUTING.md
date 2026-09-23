# Contributing to Talven

Thank you for helping. Talven is early, so a well-placed contribution can shape the language. This guide covers setup, the checks to run, and how changes get merged.

The goal behind every change is the same: make coding by AI agents more reliable and economical, while keeping the language clear for humans, native, and safe.

## Ways to contribute

| If you want to… | Start here |
| --- | --- |
| Improve the compiler or tools | [Prototype guide](docs/prototype.md), then `talven/` |
| Extend the native compiler | [Native compiler prototype](experiments/native-compiler/README.md) |
| Build harder agent tasks or run evaluations | [Evaluation harness](experiments/README.md) |
| Propose a language feature or design change | [Design proposals](docs/proposals/README.md) |
| Fix or clarify documentation | [Documentation index](docs/README.md) |
| Ask a question or float an idea | GitHub Discussions |

## Set up

You need **Python 3.11+** and a **C11 compiler available as `cc`**. The reference compiler uses only the Python standard library, so there is nothing to install. The optional extras are:

- **Node 18+** for the documentation check.
- **Rust 1.96** through rustup, for the native compiler in `experiments/native-compiler/`.

~~~sh
git clone https://github.com/TechiesApp/talven.git && cd talven
python3 -m unittest discover -s tests     # should end with OK
~~~

## Find your way around

| Path | Contents |
| --- | --- |
| `talven/` | Reference compiler: `frontend.py` (lexer, parser, checker), `backend.py` (C11), `formatter.py`, `lsp.py`, `context.py`, `dev.py`, `edit_validation.py` |
| `tests/` | Unit, native, LSP, formatter, and evaluation tests |
| `examples/` | Runnable programs; `examples/invalid/` holds programs that must be rejected |
| `experiments/` | Agent-evaluation harness, corpora, adapters, results, and the Rust native compiler |
| `scripts/` | CI helpers: docs check, sanitizers, freestanding probe, benchmarks |
| `docs/` | Language reference, guides, design documents, proposals, and evidence records |

## Run the checks for your change

CI runs all of these on Linux x86-64 and ARM64. Run the ones that match your change before opening a pull request:

| You changed | Run |
| --- | --- |
| Anything in `talven/` or `experiments/` | `python3 -m unittest discover -s tests` |
| A `.tal` file | `python3 -m talven fmt FILE --check` |
| Borrowing or lowering | `python3 scripts/check-borrow-sanitizers.py` (Linux or a host with ASan/UBSan) |
| The Rust native compiler | `cargo fmt --check`, `cargo clippy -- -D warnings`, `cargo test`, then `python3 experiments/native-compiler/tests/differential.py` |
| Documentation | `node scripts/check-docs.mjs` (checks relative links and renders Mermaid diagrams) |

If a check is skipped or unsupported on your machine, say so in the pull request rather than reporting it as passed.

When you change a language rule:
- Add both acceptance and rejection tests, plus an execution test if lowering changes.
- Update the [language reference](docs/language-reference.md).
- If the rule is part of the scalar subset, keep the Rust port in step; the differential suite fails when the two compilers disagree.
- Keep diagnostics, compiler context, and editor behavior consistent, and version the profile or schema when compatibility changes.

## Open a pull request

1. Create a branch from `main`.
2. Sign off every commit with `git commit -s`. This certifies the [Developer Certificate of Origin](https://developercertificate.org/), and CI rejects unsigned commits.
3. Open a pull request and fill in the template. Explain what changed and why, and link the issue, proposal, or discussion.
4. All required checks must pass. A code owner must approve (see [CODEOWNERS](.github/CODEOWNERS)), and the branch must be up to date with `main`.

Keep pull requests focused, and avoid unrelated rewrites.

## Propose a design change

Substantial changes to language semantics, tooling contracts, or architecture go through the [design proposal process](docs/proposals/README.md). Copy the template, fill in every section, and open a pull request. The proposal names:
- the problem and the requirement IDs it affects;
- the proposed behavior, with examples;
- the alternatives you considered;
- the cost to agents and at runtime, and the security implications;
- how the claim will be evaluated.

Label illustrative syntax as a proposal; only what the [language reference](docs/language-reference.md) describes is implemented. [GOVERNANCE.md](GOVERNANCE.md) explains how proposals are decided.

## Report measurements honestly

Benchmarks and evaluations are only useful if they can be trusted:
- Record the inputs, the model and tokenizer versions, the host, the compiler settings, and the correctness criteria.
- Keep every sample, including failures.
- Never present a skipped check or a fixture run as a measurement.

[AGENTS.md](AGENTS.md) spells out these rules; they apply to human contributors too.

## Security, conduct, and licensing

- Report security concerns privately, as described in [SECURITY.md](SECURITY.md), not in public issues.
- Keep credentials, personal information, and private customer material out of the repository.
- All participation is subject to the [code of conduct](CODE_OF_CONDUCT.md).
- Talven is licensed under [Apache-2.0](LICENSE), and your contributions are licensed under the same terms. Third-party material under a different license needs review before it can be included.
