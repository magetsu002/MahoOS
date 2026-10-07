# Guardian Tetragon integration boundary

Status: prototype integration foundation

Audited upstream release: **Cilium Tetragon v1.7.1**

## Why Tetragon is used

Guardian needs trustworthy low-level observations for process lifecycle, selected
filesystem mutation activity, selected network activity, and event-loss
accounting. Maho continues to own the event schema, evidence semantics,
causality, incidents, trust, policy, recovery, Prevention, containment, and UX.

Tetragon is an observation mechanism only.

## License boundary

The Tetragon repository root is licensed under **Apache License 2.0**.

Tetragon's `bpf/` directory states that, unless a file says otherwise, its
contents are dual-licensed under **GPL-2.0-only OR BSD-2-Clause**, at the
recipient's option.

Tetragon also builds with third-party Go dependencies carrying their own
licenses and notices.

This MahoOS integration therefore deliberately uses a process/API boundary:

```text
Tetragon executable
    |
    | JSON/event interface
    v
Maho-owned guardian_tetragon_sensor.py
    |
    v
Maho-owned GuardianEvent
```

The Maho adapter:

- does not copy Tetragon source
- does not copy Tetragon BPF source
- does not link against Tetragon libraries
- does not import Tetragon Go packages
- does not use Tetragon enforcement
- does not grant Tetragon Maho mutation authority

The current repository change **does not bundle or redistribute the Tetragon
binary**. For that reason Tetragon is not added to `THIRD_PARTY_NOTICES.md`,
which explicitly inventories material bundled directly in the MahoOS
repository rather than package-manager dependencies.

## Release packaging gate

Before a MahoOS ISO or package redistributes a Tetragon executable, the exact
artifact must receive a separate compliance review. At minimum that gate must:

1. pin the exact Tetragon source/release revision and artifact checksum;
2. preserve the Apache-2.0 license for Tetragon userspace;
3. preserve the applicable license notice for distributed BPF material,
   including the upstream BSD-2-Clause option where that option is selected;
4. inventory licenses/notices for third-party code actually present in the
   shipped executable/artifact;
5. install those notices in the MahoOS package's license/notice location;
6. record provenance in the release manifest/SBOM;
7. avoid implying endorsement by the Cilium/Tetragon trademarks.

Do not copy a release binary into the MahoOS repository or installer payload
until this gate is complete.

## Authority rule

A normalized Guardian sensor event always carries:

`authority_boundary = "observation-only"`

No event emitted by this adapter can authorize containment, recovery,
Prevention mutation, package changes, or any other privileged action.

Those actions continue to require their existing exact Maho authority paths.

## Privacy rule

The always-on adapter intentionally discards raw Tetragon command arguments and
working directories.

The first bounded event set retains only what Guardian needs to reconstruct
useful system behavior:

- stable process identity
- PID/UID
- executable path
- parent process identity
- process start time
- selected path-addressable file **write-access observations**
- selected TCP **connect-attempt** endpoint data
- provider event-loss accounting

Read-only file activity is excluded from the default normalization path.
Pathless pipe/FIFO writes are also excluded from the always-on ledger and are
reserved for a future high-fidelity IPC trace mode.

Future fields must be justified individually rather than copying the complete
Tetragon payload into the Guardian ledger.
