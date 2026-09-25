# MahoOS V1 generation retention and garbage collection

Maho retains the current `SystemGeneration` and the two newest previous
eligible `SystemGeneration` identities. Retention is an identity graph, not a
directory-age policy. Every kernel, package set, root, boot artifact, runtime,
manifest, and evidence object referenced by a retained or otherwise protected
identity remains protected.

Additional hard protections cover the running kernel and current root, active
candidate/update/recovery transactions, the current and last independently
verified recovery routes, unresolved-incident evidence, required key-rotation
rollback material, and retained audit evidence. Missing references, corrupt
metadata, stale plans, or changed object content fail closed.

Storage pressure uses this order: abandoned failed candidates, expired staging
state, disposable package cache, then the oldest superseded generation. If the
configured safe reserve still cannot be restored, update mutation remains
blocked. The only-recovery route is never exchanged for free space.

The GC transaction durably records an exact source-inventory digest and exact
object content identities. It atomically commits the target inventory before
deleting bytes. Interruption can therefore leave unreferenced bytes to be
removed on resume, but cannot leave authoritative metadata pointing at deleted
content. Receipts bind the plan, source and target inventories, removed
identities, reclaimed bytes, and reserve outcome.

`maho-generation-gc status` is unprivileged and read-only. Installations that
predate a durable GC inventory are adapted from verified generation-store
manifests with mutation disabled. A bounded root deployment may perform the
single-use `initialize` operation to publish that exact discovered inventory;
it refuses to replace an existing inventory. `apply` and `resume` require root,
a durable inventory, and (for apply) the exact `GC:<plan-sha256>` confirmation
token.
