# Update artifact lifecycle — Level C review

Status: human-approved for source implementation and disposable VM certification
on 2026-10-09 in the active engineering session. Physical operations remain
subject to their separate approval boundaries.

## Problem and existing owners

The coordinator invalidates prepared transactions on repository database drift,
including drift with an equivalent package generation. Each replacement stages
another private archive set. Neither the coordinator nor staging publishes its
retired cache objects into the generation GC inventory. The generation-store
adapter does not infer update-cache deletion authority. Old bytes therefore
survive indefinitely. Preparation and maintenance polling also write
`last_success_at`, obscuring whether installation happened.

Maho Update remains the sole transaction and staging owner. Generation GC
remains the retirement executor. Guardian and Adaptive remain observation and
package-maintenance policy owners. No new daemon, general filesystem cleaner,
package execution authority, or recovery class is proposed.

## Observation and protection

Under the existing campaign exclusion lock, read exact transaction histories,
current/coordinator pointers, staging manifests, execution/activation/recovery
journals, generation references, certification receipts, and current unresolved
incident references. Missing, unreadable, corrupt or contradictory protection
evidence blocks retirement of every affected object. Directory age, a BLOCKED
label, a name prefix, or a non-current pointer never proves disposability.

Protect active and recoverable transactions; running/current roots; retained
previous roots, kernels and recovery snapshots; admission and activation
artifacts; key rollback material; unresolved incident material; receipts,
transaction histories, manifests and forensic logs. Historical M4B transactions
need a complete independently reviewed protection inventory before adoption.

## Retirement authority

Capacity accounting distinguishes retired file allocation from newly available
filesystem space. The archive receipt's `reclaimed_bytes` is the sum of
confirmed unlinked files' allocated bytes; snapshots or clones can retain those
extents. It does not establish physical capacity recovery. Guardian storage
observations and staging reserves continue to use fresh filesystem availability.
Retiring archives must never clear a low-space veto from the receipt alone.

The disposable-VM matrix includes a file-backed Btrfs filesystem with a retained
read-only snapshot: archive retirement commits, the snapshot content remains
intact, and available capacity does not increase. Snapshot retirement and cache
layout changes require their own owner-bound design and proof; this file-only
profile grants neither operation.

The coordinator durably publishes an exact retirement record only after proving
an unexecuted generation invalidated or superseded and proving no protected
reference to each disposable object. The record binds transaction, generation,
manifest digest, exact artifact digest and filesystem identity, source revision,
inventory digest, retirement reason and selected targets. Consumption holds the
same campaign lock and revalidates references and identities. Authority is
single-use and expires after five minutes; durable cleanup already started may
resume only its recorded objects after revalidating protections.

Initial physical targets are limited to independently verified regular package
archives and detached signatures inside `/var/cache/maho/update-auto/<txid>/staging`
and `/var/cache/maho/update-m4b/<txid>/staging`. Adoption of disposable discovery
database copies requires a separately enumerated exact file manifest. There is
no recursive directory deletion and no Btrfs snapshot deletion in this profile.

Use descriptor-relative traversal from root-owned non-writable cache ancestors,
`O_NOFOLLOW`, regular-file checks, inode/device/content checks and rejection of
mount crossings, hard links, special files and unexpected entries. Revalidate
each object immediately before unlink. A changed object remains protected.

## Durable phases and interruption

Fsync a prepared journal and its parent; commit authoritative retirement before
unlink; fsync each parent directory and record completed object identities;
publish an exact receipt with measured reclaimed allocation. Resume verifies
the same journal and remaining objects, rejects replay/substitution and never
recreates a reference to deleted bytes. Interrupted or failed cleanup retains
evidence and reports incomplete reclamation. Existing generic GC's directory
deletion path is not sufficient evidence for this narrower profile.

## Scheduling, budgets and vetoes

Retain one authoritative prepared generation while authority is unavailable;
observe discovery inputs without downloading another archive set. Changed
repository bytes remain an execution blocker: do not rebind an old plan to new
repositories merely because versions match. Compare the full coherent plan,
exact repository package digests/signatures and installed database before any
reuse. Relevant change retires the obsolete unexecuted objects before staging
their replacement. Do not enqueue replacements while retirement is unresolved.

Store distinct discovery/preparation/execution/verified-health timestamps.
Use WAITING_AUTHORITY for absent, invalid or out-of-scope authority,
WAITING_MAINTENANCE for fresh policy deferrals, WAITING_PREPARATION for recoverable
preparation blockers, and BLOCKED for unsafe/unknown errors. Bounded retry must
reobserve changed authority and safety evidence without duplicating transactions
or endlessly appending identical history events.

Run certified storage retirement before expensive staging and separately from
the package-maintenance gate. A reliability veto may permit only this certified
archive-retirement capability; security/recovery protection and missing evidence
still deny it. This exception never authorizes package installation. Bound
disposable storage to one prepared generation plus one replacement in progress;
enforce a 12 GiB archive budget and the canonical post-staging reserve
`max(20 GiB, 15% of the filesystem)`. If protected artifacts prevent compliance,
report the deficit and defer staging rather than remove recovery material.

## Guardian convergence and execution

Keep the existing fresh statvfs provider and Guardian reliability assessor.
Recovery must be recognized from newly observed usage below the configured
degradation threshold and current healthy required providers. Adaptive may
release its veto only through its existing fresh-evidence policy owner; preserve
unrelated incidents and security restrictions. No fabricated receipt or health.

Execution-profile work continues under architecture issue #145's source/VM
approval. New effects still require exact disposable-VM certification and
separate physical production authority. Boot trust, native boot updates,
activation and recovery retain their existing explicit authorization contracts.

## Required proof and approval boundary

Focused unit/integration tests: repeated denied cycles and bounded bytes/history;
equivalent and changed repositories; active/recovery/incident protection;
corrupt/missing references; expired/replayed authority; symlink/hardlink/path and
mount substitution; budget refusal; interruption before and after each durable
boundary; repeated resume; fresh versus stale reliability-veto release.

Disposable VM proof must exercise real artifact files, locks, fsync/restart and
low-disk behavior. Execute/activate/recover changed package-effect boundaries
only in disposable VMs, reusing accepted baselines and historical proof at its
exact scope. Local CI only. Physical acceptance requires measured reclamation,
protected-object verification and repeated naturally scheduled maintenance
cycles. A single cleanup or PREPARED state is not completion.

Requested architecture decision: approve this exact source implementation and
disposable VM certification design, or specify changes. This approval does not
authorize physical root-owned deployment/cleanup, package transactions,
firmware/key changes, root exchange, reboot, merging or production-profile
expansion. Those require their concrete reviewed artifacts and separate approval.
