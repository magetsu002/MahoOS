# Contributing to MahoOS

MahoOS accepts changes that make the system clearer, safer, more reliable, or more useful without creating a second owner for state that already has one.

Before editing, read:

1. [Architecture](docs/ARCHITECTURE.md)
2. [Components](docs/COMPONENTS.md)
3. this document

Use [Development](docs/DEVELOPMENT.md) for build and test commands.

## 1. Inspect before changing

Do not guess facts that the repository, runtime, or platform can answer directly.

Before substantial work:

- inspect the current branch, source revision, and working tree;
- preserve unrelated or unknown dirty work;
- find the existing component and mutation owner;
- inspect the current tests and contracts around that owner;
- distinguish source state from deployed/runtime state when runtime claims matter.

Never reset, clean, stash, overwrite, or delete work you do not understand.

## 2. Identify the owner

Use [Components](docs/COMPONENTS.md) to answer:

- What state is changing?
- Which component presents it?
- Which backend is authoritative?
- Who is allowed to mutate it?
- What would become a duplicate subsystem if added here?

If the answer is unclear, resolve ownership before implementation. Do not add a new database, daemon, registry, repair path, or authority simply because it is convenient.

## 3. Make the smallest coherent change

A good MahoOS change has one clear responsibility and closes its own safety boundary.

Keep unrelated cleanup out of the same change. Do not casually rewrite architecture while fixing a local defect. If a change requires a new authority, a new protected state, a new recovery class, or a changed trust invariant, open an architecture issue first.

## Contribution levels

### Level A — presentation and isolated behavior

Examples: documentation, visual presentation, local UI behavior, focused tests, and changes that do not create or alter system authority.

Architecture review is normally not required when ownership remains unchanged.

### Level B — platform integration

Examples: NetworkManager, BlueZ, KIO/Solid, PipeWire/WirePlumber, XDG portals, application associations, Secret Service, PolicyKit, packaging, or other system integration.

A Level B change must name the real backend and prove that Maho is integrating with it rather than creating a parallel owner.

### Level C — trust and mutation authority

Examples: Guardian trust semantics, updates, recovery, generations/GC, prevention, installer/boot, mutation authority, break-glass, firewall trust, and other fail-closed system paths.

Level C changes require architecture review before implementation. The design must identify the observation source, mutation owner, targets/effects, authority lifetime, stale/missing behavior, interruption behavior, recovery path, and required proof.

## Tests and evidence

Test the exact change, not merely a nearby happy path.

Evidence levels are distinct:

| Level | Meaning |
| --- | --- |
| **unit** | Pure or narrowly scoped behavior tested without integrating the real surrounding system. |
| **integration** | Multiple real components or interfaces exercised together in a controlled environment. |
| **VM** | The relevant system behavior exercised in a disposable virtual machine with the real boundary under test. |
| **physical** | The relevant behavior exercised on real hardware with the stated physical boundary. |

Never claim a stronger evidence level than was actually performed. A unit test does not prove a VM path. A VM result does not prove firmware or hardware behavior. Old certification does not prove current source or current runtime.

For security/reliability changes, negative evidence matters: stale, missing, replayed, interrupted, wrong-target, wrong-owner, and failed-verification cases should fail safely.

## Pull requests

A pull request should explain:

- the problem and bounded scope;
- the existing owner/authority inspected;
- why no parallel subsystem was introduced;
- architecture impact and contribution level;
- exact tests run and their evidence level;
- failure semantics;
- runtime/deployment verification when the claim depends on runtime state;
- known limitations.

Use the repository pull request template.

The completion model is:

```text
SOURCE → TEST → MERGE → DEPLOY → CONVERGE → VERIFY → ACCEPT
```

Stopping earlier is valid when that is the scope, but describe the state accurately. Source completion is not live completion.

## Architecture review boundary

Use the architecture issue template before coding when a proposal would:

- create or transfer mutation ownership;
- change trust or health semantics;
- add a new generation identity or recovery class;
- expand protected state or prevention enforcement;
- change installer/boot authority;
- replace an external platform authority with Maho-owned state;
- make a previously explicit destructive action automatic.

The canonical architecture lives in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Deep documents define the detailed contracts; secondary documents should link rather than restate them.
