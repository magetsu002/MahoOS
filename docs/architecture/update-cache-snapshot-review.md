# Update cache isolation and snapshot retention — Level C review

Status: human-approved for source implementation and disposable VM certification
on 2026-10-09 in the active engineering session. Physical operations remain
subject to separate exact review and approval.

## Problem and observations

File retirement is working, but is not physical capacity recovery when other
Btrfs roots retain the same extents. The physical diagnostic identified root
Snapper timeline/package snapshots, the running root, and a protected previous
root as holders of sampled archives. The staging directories are ordinary
directories inside the root subvolume. Snapper cleanup already runs; its success
does not establish that protected/shared allocation has become free.

Unreferenced snapshots can still be explicitly important recovery objects.
Absence from the sampled Maho UUID references alone never grants deletion.

## Existing owners and proposed boundary

Maho Update remains owner of transaction/staging state. Generation GC remains
the retirement planner/journal owner. Snapper remains the sole backend for its
snapshot metadata and deletion. NativeBtrfsOps remains the native filesystem
integration boundary. Guardian continues measuring actual available capacity.
No new daemon, updater, general cleaner, generation identity or recovery class.

There are two independently gated changes:

1. Isolate **new** staging in a dedicated Btrfs cache subvolume mounted at the
   fixed path `/var/cache/maho/update-artifacts`, with `auto` and `m4b` transaction
   roots below it. The top-level subvolume is `@maho-update-artifacts` on the
   independently identified root filesystem. Provisioning belongs to the exact
   Update installation operation, not a read-only observer or an implicit
   coordinator repair. An exact mount unit provides persistence across reboot
   and existing candidate/previous-root activation. A verified mount and
   filesystem/subvolume UUID record are required before selecting these roots.
   Missing/wrong mounts defer expensive staging; no ordinary-directory fallback.
   Existing cache paths remain readable and protected in place. There is no
   automatic migration, recursive copying/deletion, manifest rewriting, or
   invalidation of recovery data to force a new layout. Budgets include both
   legacy and isolated roots. Candidate preparation must preserve the mount
   integration and verify that staged archives are outside its snapshot.
2. Add a separate exact Snapper retirement profile. The existing file profile
   does not gain snapshot authority. Planning first observes the complete root
   Snapper configuration/list/metadata, subvolume UUIDs, mount/default root,
   Limine boot manifest, Maho generation/recovery/transaction references and
   fresh Guardian incident evidence. Preserve every important or Maho-marked
   snapshot, unclassified/manual snapshot, mounted/default/next-boot root,
   current and required previous generations, recovery route and incident
   reference. Initially consider only backend-labelled ordinary timeline
   snapshots and complete unimportant pre/post pairs. Their independent
   eligibility must include the configured retention floors and Maho protection
   graph; age, low disk, naming or missing references alone is insufficient.
   If the installed policy offers no safe eligible objects, return that blocker.
   Do not silently lower retention floors or enable quota/configuration changes.

## Scope, lifetime and attribution

Cache provisioning is an explicit single-use installation plan bound to source,
root filesystem UUID, expected empty target, subvolume identity, mount unit and
payload hashes. It may create only this cache and its mount integration; never
replace an existing unknown subvolume, mount, directory or configuration.

Snapshot retirement requires a distinct source/payload/VM-certificate-bound
grant. A five-minute single-use plan enumerates exact root config, snapshot
number, UUID, read-only state, metadata digest, protected-inventory digest and
reason. No numeric ranges, wildcard targets, direct Btrfs snapshot-deletion
fallback, writable conversion or general Snapper cleanup command. Mutation
uses only Snapper's exact snapshot deletion operation, including backend sync.
Bound each maintenance batch to at most sixteen snapshots and its complete
pre/post pairs; any quota/retention-policy uncertainty blocks the plan.

The file and snapshot capability grants remain separate. Installing source
never rebinds an old grant automatically. A Guardian reliability veto may allow
only the independently certified retirement effects; other security/recovery
protections remain hard vetoes. This is not package or activation authority.

## Missing evidence, concurrency, interruption and recovery

Unreadable, corrupt, contradictory, stale or incomplete protection/configuration
evidence blocks mutation. Fail closed on snapshot number reuse, changed UUID,
unexpected mount crossing, symlink, owner/mode drift, broken pair or replay.

Hold the existing Update exclusion lock and coordinate with the recovery owner
and Snapper backend's configuration serialization. Every protection writer must
participate in the same exclusion boundary before automatic deletion is enabled.
If this cannot be demonstrated, the snapshot feature remains read-only and
uncertified. Reobserve eligibility/protections and exact backend identity before
each operation; a new recovery/incident reference cancels remaining deletion.

Fsync a PREPARED journal, durably publish exact retirement, execute one bounded
backend operation, then record independently observed removal and measured
filesystem availability. Resume only the recorded targets under freshly
validated protections. An absent object without sufficient backend/journal
evidence remains ambiguous, never silently counted as physical recovery.
Interrupted creation/mount provisioning is reconciled by exact UUID/hash
identity; preserve unknown state and defer. Never delete a recovery snapshot as
the rollback for a cache-installation failure.

Deleting a proven disposable snapshot is irreversible and must be exposed as
such in the separate physical review. Existing eligible recovery roots remain
the recovery path. Capacity is measured after backend completion; receipts do
not promise a minimum capacity gain when other protected roots share extents.

## Required proof and acceptance

Focused tests: exact layout/mount identity, unsafe target substitution, legacy
protection and aggregate budgets; retention floors, important/manual/Maho pins,
pair integrity, running/default/boot roots, stale/unknown references, expiry,
replay, concurrent recovery publication and changed identity; crash/resume at
durable boundaries and honest shared-allocation accounting.

Disposable VM tests use real Btrfs and Snapper. Prove that root/candidate
snapshots exclude isolated staged payload, while protected root snapshots and
legacy archives remain intact; retiring an isolated archive really increases
available space. Prove exact owner deletion releases unprotected shared
allocation and preserves all protected snapshots. Prove mount persistence,
candidate activation and recovery attachment without changing existing boot
authority. Reuse historical certification only for unchanged boundaries.

Automatic snapshot retirement stays disabled unless all protection writers and
the real backend exclusion contract pass. A read-only proposal or source test
never counts as certified physical mutation. Physical acceptance needs the
exact reviewed plan, protected-object verification, measured recovered capacity
and fresh Guardian convergence across repeated scheduled cycles.

## Requested decision

Approve source implementation and disposable VM certification of this design.
Any unresolved exclusion or recovery proof leaves the corresponding capability
disabled, with an explicit blocker. This approval grants no physical cache
provisioning, snapshot deletion, additional PolicyKit prompt, package operation,
root exchange, reboot, firmware change, merge or expanded production authority.
Those require separate concrete review and approval, including an explicit
exception to the already-consumed physical privilege-request limit.

## Backend references

- [Btrfs subvolume documentation](https://btrfs.readthedocs.io/en/latest/btrfs-subvolume.html):
  root snapshots exclude nested/mounted subvolume content, and shared roots may
  retain allocation after deletion.
- [Snapper manual](https://snapper.io/manpages/snapper.html) and the installed
  Snapper 0.13.2 manual: deletion operates through its owner; `--sync` waits for
  the Btrfs backend's removal work. Retention policy remains an eligibility input.
