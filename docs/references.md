# References and evidence

These primary sources support the security design discussion. They are guidance to evaluate, not evidence that this proposed language implements or complies with them.

## Security sources

| Source | Relevance |
| --- | --- |
| [CISA: Memory Safe Languages](https://www.cisa.gov/resources-tools/resources/memory-safe-languages-reducing-vulnerabilities-modern-software-development) | Memory-safety motivation; does not establish protection from every vulnerability class |
| [NIST SP 800-218: SSDF](https://csrc.nist.gov/pubs/sp/800/218/final) | Secure development lifecycle and vulnerability reduction |
| [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/) | Verifiable controls for web applications and services |
| [OWASP Top 10 for Agentic Applications for 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/) | Threat modeling for agents that use tools and carry out workflows |
| [The Update Framework specification](https://theupdateframework.github.io/specification/latest/) | Secure update metadata, key roles, rollback and freeze threats |
| [NIST SP 800-193](https://csrc.nist.gov/pubs/sp/800/193/final) | Firmware and platform protection, detection, and recovery |

The NIST SSDF final page, OWASP ASVS page, OWASP agentic guidance page, and TUF specification were checked on 2026-09-06. At that check, the cited SSDF final document was version 1.1 and ASVS identified 5.0.0 as its latest stable version. Recheck official publication status before adopting a later version; distinguish drafts from final publications.

## How to add evidence

- Prefer official specifications, vendor documentation, standards publications, or research papers.
- Link the specific page supporting a factual claim.
- Record the version, target, and check date when behavior can change.
- Label architecture proposals, observations, and measured results separately.
- Do not infer compliance, zero overhead, universal package compatibility, or unconditional security from the choice of an underlying technology.

Native compilation, memory rules, ecosystem adapters, cache interfaces, GPU backends, and performance targets in this repository are proposed project directions. They need prototype evidence before being presented as supported features.

