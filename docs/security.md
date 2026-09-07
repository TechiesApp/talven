# Security design

Status: proposed requirements and controls. There is no security-certified compiler, runtime, or deployment in this repository.

## Security contract

Prevent unauthorized operations where enforcement is possible; authenticate code and data at appropriate boundaries; detect unauthorized changes and stale-state replay; contain compromise; and support recovery.

A language cannot unconditionally protect an application against a compromised kernel, firmware, driver, hardware platform, or signing authority. Every claim must state its trusted computing base and target assumptions.

Security must support the agent-first product goal. Smaller, trustworthy context and explicit capabilities should help agents reason about changes without granting them more authority.

## Threats and boundaries

| Threat | Proposed control | Boundary or limitation |
| --- | --- | --- |
| Memory corruption in safe code | Ownership, initialization, bounds, aliasing and concurrency rules | Compiler correctness, sound runtime and unsafe implementation |
| Malicious native dependency | Trusted review or a restricted process/suitable Wasm sandbox | An in-process typed wrapper cannot contain arbitrary native code |
| Prompt injection or malicious tool content | Treat external content as data; independently enforced tool and capability limits | Natural-language instructions alone are not an isolation mechanism |
| Agent modifies its own policy | Protected policy and checks outside its writable workspace | Agent must not hold release authority or production credentials |
| Dependency or update tampering | Verified integrity, provenance, signatures, trusted metadata, freshness and rollback checks | Keys and trust anchors must remain protected |
| Unauthorized file or database write | Least privilege, validated operations, correct authorization, transactional or atomic updates | Authorized code can still implement the wrong business rule |
| Network tampering or impersonation | Vetted authenticated transport, peer validation, authorization, applicable replay controls | Encryption does not replace endpoint or application security |
| Resource exhaustion | Explicit budgets, queue bounds, backpressure, time and size limits | Limits depend on the workload and execution environment |
| Privileged platform compromise | Platform integrity, isolation and recovery where supported | Secure boot alone does not stop every later runtime compromise |

Memory-safe languages reduce memory-related vulnerability exposure. They do not eliminate authorization errors or malicious behavior. See [CISA's memory-safe language guidance](https://www.cisa.gov/resources-tools/resources/memory-safe-languages-reducing-vulnerabilities-modern-software-development).

## Capabilities and effects

Safe modules should receive explicit capabilities for files, network destinations, secrets, process execution, and device resources. Do not provide unrestricted ambient access by default.

Capabilities should be narrow and passable through checked interfaces. Effects should identify externally visible operations, allocation, blocking, and unsafe boundaries where practical.

Compiler restrictions need runtime and OS support when code can escape the safe language. A process with the same unrestricted privileges is not automatically a sandbox.

The agent can propose a capability change. A protected build or execution policy must decide whether that change is allowed. Editing an AGENTS.md file, package manifest, or local policy file must not grant new authority by itself.

OWASP's [Agentic Applications guidance](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/) is a relevant source for agent threat modeling; the specific controls here are project proposals.

## Memory and concurrency

Define safe rules for ownership, borrowing, bounds, initialization, atomics, synchronization, and task lifetimes. Keep raw pointers, unchecked operations, FFI, and privileged device access explicit.

An unsafe implementation needs a documented contract and reviewable surface. Calling it through a safe-looking API is sound only if the implementation actually preserves that contract.

CPU and GPU buffer lifetimes must include outstanding work. Cancelling a host task must not free resources still used by a device. Host memory safety alone does not establish race-freedom inside arbitrary GPU kernels.

## Filesystem and stored data

Use capability-scoped file handles and carefully designed path APIs. Account for traversal, symlinks, and time-of-check/time-of-use races.

Use authorization and schema/business-rule validation before changes. Use atomic or transactional operations where consistency requires them. Include tenant and record scope in application access decisions.

Choose authenticated encryption, MACs, or signatures according to the trust model. A checksum that an attacker can replace alongside the data does not establish authenticity. Encryption without authentication is not an integrity guarantee.

Integrity does not establish freshness. Where rollback or replay matters, protect version state and recovery procedures as well as data. Backups and logs need access controls and integrity checks.

## Network and servers

Use vetted cryptographic libraries and protocols, verify peer identities, and separate authentication from authorization. Provide parameterized data-access APIs and safe input handling.

Use non-root service identities, restricted execution, bounded resources, secret management, patched OS components and drivers, and observability appropriate to the deployment.

Web-service controls should map to versioned requirements from [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/). ASVS is a web-application verification framework, not a blanket certification for embedded firmware or every program.

## Packages, builds, and updates

Record exact source/artifact hashes, adapter versions, toolchains, targets, and transitive dependencies. Restrict install and build scripts. Track a software inventory and relevant advisories.

Verify publisher identity and provenance where available, and define policy when they are absent. A valid signature establishes a relationship to a key; it does not prove code is benign.

Keep release-signing keys outside agent workspaces. Aim for reproducible builds and independently verified release artifacts. Security-sensitive checks must run through protected enforcement, not only a workflow file an agent can replace.

Use an established secure-update design rather than inventing a signature-only updater. [The Update Framework](https://theupdateframework.github.io/specification/latest/) addresses signed metadata, key roles, and attacks including rollback and freeze.

## Platform and hardware trust

Where the threat model requires it and hardware supports it, use verified boot, signed firmware, protected keys, rollback resistance, and recovery. Measured boot, attestation, or confidential computing may be relevant to particular deployments; none should be described as a universal remedy.

[NIST SP 800-193](https://csrc.nist.gov/pubs/sp/800/193/final) provides guidance on platform firmware protection, detection, and recovery.

A small board without secure key storage cannot provide the same guarantees as a platform with an appropriate hardware trust anchor. A requested deployment profile must report unsupported protections or reject the build/deployment.

## Security profiles and maintenance

Profiles should state requirements, trusted components, enabled checks, and platform prerequisites. They must not silently disable safety to meet footprint targets.

Keep guidance versioned and review updates deliberately. Pin build inputs, evaluate changes, and rerun relevant verification. Do not equate downloading the latest dependency with secure operation.

Use [NIST SSDF](https://csrc.nist.gov/pubs/sp/800/218/final) as a development-process reference. Plan compiler fuzzing, malformed-input tests, unsafe-code review, dependency monitoring, independent audits, and a vulnerability response process as implementation matures.

Before a runtime release, establish supported versions, a verified private reporting channel, patch ownership, and disclosure procedures. These operational arrangements are not yet established by this design repository.

