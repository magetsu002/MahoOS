# Exact Snapper pressure exception — Level C review

Status: withdrawn. The current human mission prohibits weakening snapshot count floors. No source implementation or executable pressure exception is authorized. The following text is retained only as the historical proposal.

Backend diagnostic result: Snapper permits important/recovery metadata promotion
by a second client while the first holds its configuration lock. The required
exclusion proof has failed; this proposal grants no executable snapshot plan.
A reviewed backend integration that closes that race is needed before a
snapshot retirement capability can be certified, even for an exact exception.

## Concrete problem

The root Snapper backend permits the existing desktop account to read its
configuration. It currently retains fixed counts (`NUMBER_LIMIT=20`; hourly,
daily, monthly and yearly timeline limits of 10), has no qgroup, and does not
shrink those fixed floors for disk pressure. Its scheduled cleanup already
succeeds. The installed cleanup interface does not expose a read-only list of
the exact objects it would remove under a proposed policy.

Read-only inspection found the already-retired archive files in eleven
ordinary snapshots: 735, 736, 737, 738, 739, 740, 741, 742, 743, 744 and 745.
736/737 are one complete pre/post pair; the others are timeline snapshots.
They carry no important/Maho userdata markers. Snapshot 746 was taken after
the file cleanup and contains none of those reviewed retired files. These are
observations, not deletion authority or a guarantee of unique freed space.

## Proposed bounded exception

Add an **operator-approved, one-time** exact Snapper retirement plan for
ordinary snapshots proven to retain already-retired Update files. It may
override the configured count floors only for its individually reviewed
targets. Preserve the settings themselves and all remaining ordinary snapshots;
do not enable automatic pressure thinning or make a general cleanup call.

Generation GC owns the plan/journal and Maho protection decision. Snapper remains
the only snapshot deletion backend. The plan must include a precise retained
set, independently reobserved filesystem/subvolume UUIDs, backend config and
metadata hashes, retired archive receipt linkage, complete protection graph,
running/default/next-boot identity, exact pre/post relationships and source/
certificate bindings. A human-readable physical review must enumerate every
target and retained recovery object. Limit the plan to sixteen snapshots.

Important, Maho-marked, manual/unclassified, running/default/next-boot,
generation/recovery/incident-protected snapshots remain unconditionally outside
the exception. Neither an absent UUID reference nor a timeline label proves
eligibility. Preserve unresolved evidence and all logs/receipts. An unknown
required protection writer or unfinished recovery blocks execution.

## Authority, failure and proof

Require separate explicit physical approval of the exact plan. Bind a five-minute
single-use authority to the source/payload, VM certificate, target UUIDs and
protection/configuration evidence. An exact plan may resume only its durably
retired targets after fresh protection checks. It grants no recurring snapshot
capability, policy configuration change, new cache migration or package authority.

Use the Snapper backend's persistent client/configuration lock plus the Update
and recovery-owner exclusion boundary. Prove the actual lock semantics for
snapshot deletion and metadata promotion before implementing the executor.
Snapshot numbers are not sufficient identity. If promotion/reference writers
cannot be safely excluded, keep this feature read-only; explicit review is not
a substitute for the missing exclusion proof. Never fall back to direct Btrfs
deletion, writable conversion or recursive removal.

Fsync PREPARED and retirement records before the exact owner call; independently
verify removal, backend completion, retained-object identities and actual
filesystem availability. Report interrupted/ambiguous outcomes honestly, retaining
evidence. Snapper/Limine may remove the deleted snapshots' boot-menu entries
through their existing integration; enumerate that effect in the physical review.
Do not remove retained kernels, change firmware, activate a root or reboot.

Disposable VM proof must cover actual Snapper locks, important/manual/Maho pins,
new metadata/reference publication, source/UUID/pair drift, expiry/replay,
interruption and exact resume, backend synchronization, retained boot/recovery
objects, and real capacity gain for obsolete cache copies. No fabricated
Guardian recovery. Reuse the already tested isolated-cache boundary.

Requested decision: approve this additional source implementation and disposable
VM certification only. Physical deletion/installation and any additional
PolicyKit request still need their own concrete review and approval. This does
not authorize a recurring Snapper retention policy change.
