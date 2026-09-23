## Summary

<!-- What changes and why. Link the issue, proposal, or discussion. -->

## Type of change

- [ ] Documentation fix (links, wording, consistency; no change to a recorded position)
- [ ] Design proposal (new or updated file under `docs/proposals/`)
- [ ] Change to requirements, architecture, or a recorded decision
- [ ] Compiler, tooling, or evaluation code
- [ ] Repository tooling or process

## Checklist

- [ ] Illustrative syntax and hypothetical APIs are labeled as proposals, not implemented behavior
- [ ] Relative links resolve and Mermaid diagrams render (`node scripts/check-docs.mjs`)
- [ ] The [decision register](https://github.com/TechiesApp/talven/blob/main/docs/decisions.md) and requirement mapping are updated if a position changed
- [ ] Code changes: `python3 -m unittest discover -s tests` passes, changed `.tal` files pass `talven fmt --check`, and new rules have acceptance and rejection tests
- [ ] The [documentation index](https://github.com/TechiesApp/talven/blob/main/docs/README.md) is updated if a document was added, renamed, or removed
- [ ] No credentials, personal information, or private material is included
- [ ] Commits are signed off (`git commit -s`) to certify the [Developer Certificate of Origin](https://developercertificate.org/)
