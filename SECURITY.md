# Security Policy

MahoOS treats security, recovery, and mutation authority as architecture, not as a collection of ad-hoc privileged scripts.

For the security model, start with:

- [Architecture](docs/ARCHITECTURE.md)
- [Prevention and security](docs/architecture/prevention-security.md)
- [Installer and boot](docs/architecture/installer-boot.md)

## Supported release status

MahoOS is Pre-V1. There is not yet a stable public release support matrix. Security fixes and disclosure expectations may change before V1.

## Reporting a vulnerability

**PUBLIC-LAUNCH REQUIREMENT: a private vulnerability-reporting endpoint has not yet been activated.**

No email address or reporting URL is intentionally invented here. On GitHub.com, Private Vulnerability Reporting can only be enabled for a public repository, so it cannot be activated while this repository remains private.

If GitHub Private Vulnerability Reporting is the selected channel, treat repository publication and reporting setup as one controlled launch sequence:

1. make the repository public only after the other launch gates pass;
2. immediately enable Private Vulnerability Reporting;
3. verify that the public repository exposes the private **Report a vulnerability** flow;
4. update this section if any reporter-facing instruction changes.

Do not announce the public repository as ready for external security reports until that sequence is verified. If maintainers approve a different private contact before launch, document that real contact here instead.

Until a verified private channel exists, do **not** place sensitive vulnerability details in a public issue, discussion, or pull request.

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
