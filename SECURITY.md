# Security Policy

MahoOS treats security, recovery, and mutation authority as architecture, not as a collection of ad-hoc privileged scripts.

For the security model, start with:

- [Architecture](docs/ARCHITECTURE.md)
- [Prevention and security](docs/architecture/prevention-security.md)
- [Installer and boot](docs/architecture/installer-boot.md)

## Supported release status

MahoOS is Pre-V1. There is not yet a stable public release support matrix. Security fixes and disclosure expectations may change before V1.

## Reporting a vulnerability

**PRE-PUBLIC-LAUNCH REQUIREMENT: a private vulnerability-reporting endpoint has not yet been configured.**

No email address or reporting URL is intentionally invented here. Before the repository is made public, maintainers must configure and document an approved private reporting mechanism.

Until that exists, do **not** place sensitive vulnerability details in a public issue, discussion, or pull request.

Non-sensitive architecture questions may use the architecture issue template, but a vulnerability report needs a private channel.

## What a useful report should contain

When the private reporting mechanism is available, include only what is necessary to reproduce and bound the problem:

- affected component and source revision;
- observed behavior and expected fail-safe behavior;
- reproduction steps;
- whether the issue requires local access, root, physical access, or a trusted signer;
- evidence level actually performed;
- logs or artifacts with secrets and personal paths removed;
- any known workaround that does not destroy evidence.

Do not submit credentials, private keys, recovery keys, personal data, or unrelated machine contents.

## Disclosure

MahoOS should preserve evidence, reproduce the issue in the smallest safe environment, fix the authoritative owner, and verify the failure mode before public disclosure. Historical certification must never be used to dismiss a current security report.
