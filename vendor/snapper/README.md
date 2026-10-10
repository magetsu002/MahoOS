# Snapper owner-exclusion experiment

Applies only to upstream tag v0.13.2, commit `43475845a712bc2327cec2ed641063df406705de`. Snapper remains the metadata/mutation owner. Review: [owner exclusion](../../docs/architecture/snapper-owner-exclusion-review.md), architecture issue #147.

The patch makes daemon configuration locks exclusive and checks metadata, read-only, creation and configuration writes under the same mutex. A descriptor lock on the real snapshot information directory excludes direct-library owners and configuration aliases. Process exit releases descriptor ownership; daemon/client restart never preserves deletion authority.

The descriptor registry is private library state and preserves the public Snapper object layout and ABI. A production package still requires verified daemon/library/CLI integration and exclusion of older direct-library implementations. It is a disposable-VM experiment, not a production package, and is absent from the campaign installation payload. Existing production Snapper and snapshot authority are unchanged.

The patch is insufficient by itself for retirement: external recovery/incident publication, exact target identity, retention-floor decisions, durable deletion journals, and actual capacity proof still need certification. Do not enable snapshot GC using a lock test or this patch alone. No count-floor override, general cleanup call or direct Btrfs deletion is implemented.

The final real-Btrfs VM test covers two independent clients, direct-library access through a bind-mounted collection alias, compatibility of the unchanged distro CLI with the patched library, daemon SIGKILL/restart and protected-object survival. A bounded own pre/post pair above an unchanged 20-object count floor released about 32 MiB of actual available capacity. Its new-object minimum-age fixture is test-only; production policy is untouched. This proves backend exclusion and fixture capacity, not production snapshot eligibility or crash-safe autonomous retirement.

The remaining authority gap is concrete: generic Maho recovery preparation can publish an ordinary coherent snapshot reference without an owner pin, and incident publication lacks the same exclusion. A daemon lock cannot serialize those external JSON writes. The production backend package and every writer must be integrated and independently verified before any snapshot executor is enabled. No old pressure exception is permitted.
