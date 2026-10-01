# Machine and AI contributor contract

This file is the compact public contract for automated contributors. It is not a project-management handoff.

Read these first:

1. [Architecture](docs/ARCHITECTURE.md)
2. [Components](docs/COMPONENTS.md)
3. [Contributing](CONTRIBUTING.md)

## Rules

- Inspect current reality before substantial changes. Do not guess inspectable facts.
- Preserve unrelated or unknown dirty work. Never reset, clean, stash, overwrite, or delete it without explicit authority.
- Find the existing owner before adding state or mutation. Do not invent parallel subsystems.
- Keep observers read-only unless the architecture explicitly assigns mutation ownership.
- Treat root privilege as privilege, not as Maho authority.
- Treat stale, missing, and unknown evidence as unresolved, never healthy.
- Do not use historical proof as evidence of current source or runtime trust.
- Test the exact change and state the real evidence level: unit, integration, VM, or physical.
- Do not claim source work as deployed/live completion.
- Do not hide reboot, shutdown, firmware, key-enrollment, or destructive disk behavior.
- Do not enable automatic AUR installation.
- Keep permanent architecture free of temporary branch heads, active blockers, agent assignments, process IDs, and local-machine paths.
- If a proposed change transfers authority or alters trust/recovery semantics, stop implementation and use the architecture review path in [CONTRIBUTING.md](CONTRIBUTING.md).

The engineering completion chain is defined in [Architecture](docs/ARCHITECTURE.md) and the evidence rules are defined in [Contributing](CONTRIBUTING.md).
