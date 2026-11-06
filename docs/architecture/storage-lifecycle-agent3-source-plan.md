# Agent 3 — storage lifecycle retirement gate (source-stage plan)

> **Not production authorization.** This plan records the source-side state of
> the Agent 3 lane. The live daily-driver has not been measured from this
> execution environment. No historical figures are asserted to be current.

## Fixed ordering and boundaries

The approved deployment order remains: (1) one bounded PolicyKit grant per AI
mission, (2) bounded storage lifecycle and four logical recovery roles, (3)
autonomous verified updates, (4) Signed Boot, Windows boot reliability and TPM2
LUKS unlock. Storage retirement must not outrun Agent 2 recovery admission or
Agent 4 update transaction release. Agent 0 coordinates production activation.

Four logical recovery roles are `verified_known_good`, `previous_working`,
`pre_update`, and `emergency`. One physical snapshot may satisfy several
roles. A fifth or later physical snapshot can remain for a boot entry, active
update, unfinished incident, key rollback, archive dependency, or an unproven
historical migration head.

## Ownership map and safe disposition

| Class | Owning authority | Source-side disposition |
| --- | --- | --- |
| Generation-store manifests and immutable blobs | Existing `maho-generation-gc` | Bounded one-batch maintenance with exact inventory and content identity; old GC cannot delete directories or Btrfs subvolumes |
| Snapper root snapshots, manual/important labels | Snapper root config; recovery admission comes from Agent 2 | Read-only classification only until certified label-release and retirement transitions |
| Limine snapshot entries / EFI history | Limine/boot publication owner | Retain until exact boot references are retired and Signed Boot invariants remain intact |
| Migration recovery heads | Original migration/recovery owner (to establish on host) | Hold pending exact head identity, descendants and recovery-reference reconciliation |
| Update staging and unfinished transactions | Agent 4 Maho Update | Never delete from Agent 3 based on age alone; require positive released-transaction evidence |
| Completed archives and detached signatures | Producing archive/recovery owner (to establish on host) | Retain paired archive/signature and any referenced recovery head until a producer retirement receipt |
| Package caches | Pacman or isolated update-cache owner | Retire only unpinned exact artifact identities through the owning interface |
| Guardian incidents, rotation rollback, user data | Guardian / credential owner / user | Hard hold; never trade away these identities for free space |

The new `lib/maho_storage_lifecycle.py` deliberately emits no retirement
authority. It explains discovered snapshots and which external proofs are
missing. Descriptions, `important=yes`, and historical `maho.known_good=yes`
are not trust certificates.

## Source implementation implemented in this lane

- `maho-generation-gc plan --maintenance --output PATH` produces one
  deterministic no-pressure maintenance batch. It caps a batch at 16 objects
  and 1 GiB of estimated logical object sizes. An indivisible dependency
  closure exceeding either cap is skipped, not partially deleted.
- The existing GC executor verifies the submitted plan against a canonical
  pressure or bounded-maintenance plan and still requires root plus an exact
  `GC:<plan_sha256>` confirmation at the privileged boundary.
- It refuses directory/subvolume deletion and rechecks remaining content
  before each unlink, including resumed batches.
- Reported logical reclaim estimates are explicitly *not* physical Btrfs
  reclaimed bytes. Current system capacity and journal receipts must be
  separately measured and correlated.
- No timer or automatic production activation has been installed. That
  depends on a certified source/runtime authority and Agent 0 approval.

## Exact physical discovery required before any cleanup

Record the command, exit status, wall clock and Btrfs filesystem UUID for each
observation. Obtain read-only evidence from the relevant owners:

```bash
findmnt -no SOURCE,FSTYPE,UUID,FSROOT /
btrfs filesystem usage -b /
btrfs device usage -b /
snapper -c root --jsonout list --disable-used-space
snapper -c root --jsonout get-config
maho-generation-gc status
findmnt -no SOURCE,FSTYPE,UUID,FSROOT /boot
```

Inspect all mounted relevant Btrfs volumes, the Limine snapshot manifest
(`/boot/<machine-id>/limine_history/snapshots.json`, if applicable),
migration head catalogues, signed boot publication, update/campaign journals,
Guardian incidents, active recovery transactions, generation inventories,
Pacman cache, isolated staging cache and all archive/signature producer
directories. Count physically present items *per owner*, never only the
generation-store catalog.

For a proposed Snapper deletion, bind at least filesystem UUID, Snapper config,
numeric snapshot ID, observed subvolume UUID, current role bindings, paired
pre/post metadata, live Limine references, exact update/recovery/incident pins,
and Agent 2 certified expiry-bound retirement authority. On every execution
attempt re-observe the identities and dependencies, and use **Snapper's deletion
owner**, not a direct Btrfs subvolume deletion. Important/manual label release
is its own certified transition. Do not use age or marker text as admission.

A crash-recoverable Snapper retirement executor needs a durable per-batch
journal, bounded individual operations, postcondition reconciliation and
idempotent replay after exact identity rechecks. It must be built against the
verified Agent 2 interface; the current GC journal is not that interface.

## Capacity budgets and convergence acceptance

Preserve the **4 GiB** staging target, **8 GiB** recovery target and
**12 GiB** storage warning threshold. These are policy targets, not
permission to delete necessary recovery artifacts. The install/update safe
reserve is a separate authority and must also remain satisfied.

For each owner, record before/after item counts and hashes. For the actual
Btrfs filesystem, save `btrfs filesystem usage -b /` before/after; synchronize
pending Btrfs operations and only then report the observed used/free deltas.
Do **not** sum snapshot sizes or GC receipt logical sizes as an exact physical
reclaim claim; CoW sharing makes those estimates non-additive.

Required admission evidence before Agent 0 activates cleanup:

1. Agent 2's fresh, independently verified current/last recovery and role
   bindings, plus exact retirement certificates.
2. Agent 4's positive proof that candidate, staging and archive objects are
   not used by a live or recoverable update transaction.
3. Snapshot/Limine/EFI, Guardian, migration-head, package and key-rollback
   reference inventories all complete and fresh.
4. Identity-change, stale-reference, interrupted-journal, active-transaction,
   wrong-generation, pin, and untrusted-recovery adversarial tests pass.
5. On a disposable Btrfs VM, repeated maintenance genuinely converges
   without deleting the last usable recovery state; interruption and
   postboot recovery are exercised.
6. Agent 0 records the exact host before/after Btrfs bytes and per-owner
   retained items, then decides deployment.

Historical counts (40–41 Snapper snapshots, 64 migration heads, ~1,410
archive/signature files) are **unverified at this source stage**. Exact current
counts, production reclaimed bytes, all protected-item reasons, and physical
convergence remain pending live discovery.
