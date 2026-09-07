# Repository and publication

Talven's public repository is [TechiesApp/talven](https://github.com/TechiesApp/talven), with `main` as its default branch. The project owner created the repository, and its owner, public visibility, and empty initial state were verified on 7 September 2026 before the initial documentation was published.

## Initial scope

The initial content consists of design documentation and four Mermaid architecture diagrams: one overall system diagram, two agent and security flowcharts, and one CPU/GPU resource-lifetime sequence. The README links to the requirements, architecture, security model, and roadmap.

This is a design-stage project. No working compiler, executable, dependency installation, or runtime release is included. The repository is licensed under [Apache-2.0](LICENSE). A CI workflow checks relative links, renders Mermaid diagrams, and verifies DCO sign-off on pull requests.

## Get the repository

~~~sh
git clone https://github.com/TechiesApp/talven.git
cd talven
~~~

For future changes, follow [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md). Keep implementation status explicit and verify relative links and diagrams when editing documentation. Preserve existing work and use ordinary commits and pull requests; do not force-push unrelated history.
