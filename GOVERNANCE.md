# Governance

Status: initial governance for a design-stage project. It is intentionally simple and will be revised when there are implementation contributors and a released toolchain.

## Roles

**Project owner.** Techies App Technologies Sdn Bhd (TechiesApp, [techies.app](https://techies.app)), acting through the repository administrators, owns the project name, repository, and final decision authority during the design stage.

**Maintainers.** People with write access who review proposals and pull requests. The initial maintainer set is the project owner. Maintainers are added by the project owner and listed in this file when the set grows beyond one.

**Contributors.** Anyone who opens a proposal, issue, or pull request under the [contributing guide](CONTRIBUTING.md) and [code of conduct](CODE_OF_CONDUCT.md).

## How decisions are made

1. Anyone may open a design proposal under [docs/proposals](docs/proposals/README.md) or start a design discussion in GitHub Discussions.
2. Maintainers review the proposal against the [requirements](docs/requirements.md) and the [decision register](docs/decisions.md). Review is public and asynchronous.
3. A proposal is accepted, rejected, or deferred by maintainer consensus. When maintainers disagree, the project owner decides and records the reason.
4. Every accepted or rejected proposal adds or updates a row in the decision register. Merging a proposal document is a decision about direction, not evidence that anything is implemented.

Small documentation fixes, link corrections, and clarifications that do not change a recorded position need only an ordinary pull request review.

## What this governance does not cover

Release authority, signing keys, security response, and protected build policy are not established yet. The [security design](docs/security.md) requires those to live outside any agent-writable workspace before a runtime release.

## Changing this document

Changes to governance follow the proposal process above and require project owner approval.
