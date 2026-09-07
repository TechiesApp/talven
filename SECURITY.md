# Security policy

Talven contains an experimental reference compiler alongside its design documentation. There is no supported production software version or runtime release yet, and no mature vulnerability response process is claimed. See the [prototype limits](docs/prototype.md) for the implemented subset and the [security design](docs/security.md) for the broader proposed threat model and controls. The prototype is not a sandbox for hostile code.

## Reporting a concern

If you find a security-relevant problem in this repository, such as leaked credentials, malicious content, or a design flaw with security consequences, report it privately rather than in a public issue:

- Use GitHub private vulnerability reporting on this repository, or
- Email **hello@techiesapp.io** with "Talven security" in the subject.

You should receive an acknowledgement within seven days. Please do not disclose the report publicly until the maintainers have responded.

## Before an implementation release

The following must exist before any runtime release, as required by [docs/security.md](docs/security.md) and the [roadmap](docs/roadmap.md):

- A supported-versions statement.
- A verified private reporting channel with named patch ownership.
- A disclosure procedure and advisory format.
- Protected build, signing, and release enforcement that an agent workspace cannot rewrite.

This file will be updated when those arrangements are in place.
