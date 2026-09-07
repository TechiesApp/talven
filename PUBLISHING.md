# Repository and publication

Talven's public repository is [TechiesApp/talven](https://github.com/TechiesApp/talven), with `main` as its default branch. The project owner created the repository, and its owner, public visibility, and empty initial state were verified on 7 September 2026 before the initial documentation was published.

## Initial scope

The initial content consists of design documentation and four Mermaid architecture diagrams: one overall system diagram, two agent and security flowcharts, and one CPU/GPU resource-lifetime sequence. The README links to the requirements, architecture, security model, and roadmap.

The original publication was a design baseline. M1a adds an experimental reference compiler, examples, tests, and editor/agent interfaces; M1b adds [canonical formatting and native CI](docs/formatting.md); M1c adds [call-scoped borrowing and mutation](docs/borrowing.md). See [the prototype guide](docs/prototype.md) for the language subset. The repository is licensed under [Apache-2.0](LICENSE). Documentation CI checks relative links, Mermaid diagrams, and DCO sign-off; native CI checks the declared Linux x86-64/ARM64 hosts. There is no production runtime release.

## Get the repository

~~~sh
git clone https://github.com/TechiesApp/talven.git
cd talven
~~~

For future changes, follow [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md). Keep implementation status explicit and verify relative links and diagrams when editing documentation. Preserve existing work and use ordinary commits and pull requests; do not force-push unrelated history.
