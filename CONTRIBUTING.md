# Contributing to the design

This repository currently contains a language proposal. Design work should preserve the primary objective: reliable, economical coding by LLM agents while retaining human clarity, native control, and strong safety.

Start with the [requirements](docs/requirements.md), [decision register](docs/decisions.md), and [roadmap](docs/roadmap.md).

## Proposals

Substantial design changes go through the [design proposal process](docs/proposals/README.md): copy the template, fill every section, and open a pull request. Ideas that are not ready for a proposal can start in GitHub Discussions. Decisions are made as described in [GOVERNANCE.md](GOVERNANCE.md).

Describe the problem and the requirement IDs it affects. Include the proposed semantics or behavior, examples, alternatives, agent-context implications, runtime and memory costs, security boundaries, target constraints, and a concrete way to evaluate the claim.

Label illustrative syntax and hypothetical APIs. Do not present them as working compiler behavior.

Prefer primary references for factual technical claims. Distinguish a draft standard from finalized guidance and a prototype measurement from a released guarantee.

## Documentation changes

Keep the README navigation and relative links correct. Update the relevant decision status and requirement mapping when a proposal changes.

Run `node scripts/check-docs.mjs` before opening a pull request. It verifies every relative link and renders every Mermaid diagram; the same check runs in CI. Simple prose edits need this check and a consistency read rather than tests that merely restate the text. Implementation changes will need checks appropriate to their actual risk and behavior.

## Public contributions

Keep private credentials, personal information, unpublished customer material, and sensitive deployment data out of public files and discussions.

## License and sign-off

Talven is licensed under the [Apache License, Version 2.0](LICENSE). By contributing you agree that your contribution is licensed under the same terms.

Every commit must carry a `Signed-off-by` trailer certifying the [Developer Certificate of Origin](https://developercertificate.org/). Use `git commit -s`; CI rejects pull requests with unsigned commits. Do not submit code or text you do not have the right to license under Apache-2.0.

Third-party material with a different license needs an explicit review before it is redistributed from this repository.

Report security concerns privately as described in [SECURITY.md](SECURITY.md). Before runtime releases, a supported-version policy and named response ownership must be established; no such operational process exists yet.

All participation is subject to the [code of conduct](CODE_OF_CONDUCT.md).

