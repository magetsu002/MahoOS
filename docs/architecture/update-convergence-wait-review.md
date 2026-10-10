# Existing coordinator convergence — focused review

Maho Update retains transaction, campaign-lock and coordinator-state ownership.
This decision extends accepted stable waiting and reserve contracts; it creates
no mutation authority, generation identity, daemon or separate state store.

The coordinator records a versioned blocker/evidence fingerprint in its existing
atomic status document. It binds source, transaction, package/provenance,
repository identities, exact known plan effects, runtime identity and normalized
blocking prerequisites. Repeated observation timestamps and insignificant free
space variation do not constitute progress. Authority observations remain
non-authorizing: only the existing validator and execution owner admit work.

Before expensive staged-artifact preparation, freshly observe power, package
lock and canonical post-update reserve. A still-failed necessary prerequisite
settles waiting without hashing archives or appending transaction events. Before
repository refresh for prepared work, observe fresh adaptive/Guardian readiness;
a persistent veto avoids refresh and candidate preparation. Crossing a required
threshold resumes the existing complete validation, never bypasses it. Missing,
revoked or expired evidence continues to deny admission. Existing source drift
and repository invalidation, interrupted mutation, postboot and recovery paths
are unchanged. Waiting retains update debt and never writes installation success.

Capacity refusal stays WAITING_PREPARATION for existing consumers, with explicit
capacity-constrained outcome and required resumption condition. Known effect
scope mismatch is unsupported under the current certificate; unknown unstaged
effects remain unresolved. No blanket source rebinding or effect graduation.

Proof obligations: stable fingerprints across harmless observations, changed
source/transaction/repository/effect/authority/prerequisite detection; no archive
hashing, staging, repository refresh or journal append while a necessary gate is
closed; resource/Guardian recovery resumes full checks; revocation and stale
provider evidence deny; debt and installation timestamps preserved. Focused
local tests and disposable-VM regression only; production acceptance requires
exact immutable deployment and natural timer observations. Unchanged cache/GC
and Snapper concurrency proofs are reused only for unchanged boundaries.

Snapshot retirement remains disabled: the experimental owner patch does not
exclude old library clients or independently published incident/recovery claims.
Configured retention floors remain unconditional. No snapshot deletion, package
execution, root exchange, reboot, firmware changes or normal grant rebinding is
part of this decision.
