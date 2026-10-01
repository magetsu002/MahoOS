> **HISTORICAL EVIDENCE**
>
> This document records point-in-time certification or design history.
> It is not current project status and does not override current source or canonical architecture documentation.

# M4B physical certification — 2026-09-24

This record certifies the first real Maho boot-critical update transaction. It
does not claim that MahoOS is globally bug-free.

- Physical proof source: `6b0dda9c515a97358e40e519c9ee10b85aecc567`
- Update transaction: `upd-20260924T185307Z-8c9c00b0dbc9`
- Package generation: `pkg-2edc0ea7f4abd9bf66decdd4b6f0687057e30d477daf9d89428085a63092d624`
- Candidate/live root UUID: `6c1473c2-60fa-984d-a49b-11c7458d57be`
- Previous root UUID: `a7a682fe-1f34-5d4e-b912-1f9720b7aebb`
- Recovery generation: `g3-623c64a36c689d4d23c82130`
- Admission graph: `art-7edca989dd7f81ae96e1255185518f76fbefb3a8077bb799c7f06ecfdec94a54`
- Frozen Admission evidence: `art-170d5715ac3894794ec9a6f036f263f41db1bf227fc74ee249a9b5bfd7eb2ce2`
- Activation authority: `art-a232e0f81a6951421b9179e59a1e043eeb8bf5b4b3002affc98cf22bd2533cf1`
- Normal boot ID used for postboot proof: `b9d87b9c-dded-48b9-bf21-c9e4f85ebec9`

The offline candidate installed the complete 125-package solver transaction.
The verified live matrix included Primary `linux-cachyos` and headers
`7.2.5-1`, fallback `linux-cachyos-lts` and headers `6.18.50-1`,
`nvidia-580xx-dkms 580.178.04-1`, and `intel-ucode 20260812-1`.

Native Admission inspected 185,430 effects once. All security-boundary effects
were declared; 204 undeclared effects were ordinary generated files. Explicit
review approval and activation reused candidate/base UUID-bound immutable
evidence and completed without a second or third full-root scan.

Postboot verification proved a normal Primary boot, exact candidate `/@`, the
expected running Primary kernel, exact package and boot-artifact identities,
preserved `/home`, verified immutable Maho runtime, intact M3B recovery,
the exact previous-root backup, and delayed previous-root immutability until
the candidate was proven live. The transaction reached `HEALTHY`.

The generation publisher added by the certification change accepts only this
durable `HEALTHY` transaction/campaign/receipt relationship, re-observes the
live machine, and creates the first `SystemGeneration` and `KernelGeneration`
with no manufactured historical parent.
