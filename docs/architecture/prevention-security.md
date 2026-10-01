# Prevention and security architecture

This document owns the detailed Prevention contract. Global trust/authority semantics are canonical in [ARCHITECTURE.md](../ARCHITECTURE.md).

## Two different jobs

Maho Prevention deliberately separates **intent feedback** from **security enforcement**.

### Intent Guard

Intent Guard can parse a bounded set of deterministic interactive shell effects and provide early feedback.

It is not a security boundary.

Unknown syntax or an execution path Intent Guard does not understand must not be treated as safely inspected merely because it passed the parser.

### Mutation Boundary

The Mutation Boundary is the enforcement layer for accepted protected effects.

The current design uses BPF LSM hooks plus exact projected policy to enforce protected filesystem/device operations and explicitly registered protected-process signal operations. Enforcement is about actual kernel effects and identities, not command names.

A Python helper, shell indirection, renamed executable, or opaque binary does not gain permission merely because its command line looks different.

## Protected scope

Protected state is deliberately bounded.

Maho projects only accepted filesystem/device scopes and explicitly registered critical process identities. `/home` is not globally protected, and ordinary development workloads are not supposed to become protected merely because they run on MahoOS.

The boundary does **not** claim to prevent arbitrary root compromise, every possible kernel effect, firmware mutation, or signals to ordinary unregistered processes.

A broader scope requires architecture review and new evidence.

## Exact mutation authority

A protected mutation requires authority tied to the operation being performed.

Authority can bind:

- parent transaction/reason;
- boot identity where relevant;
- acting process start identity;
- executable identity;
- effect kind;
- operation/signal;
- exact target or target prefix;
- source/generation relationship where relevant;
- expiry.

Root or an executable name is never sufficient by itself.

High-level effects are projected only to the kernel operations they are intended to authorize. Write, metadata, create, unlink, rename, link, symlink, mount, device operations, and process-control signals remain separable scopes.

Missing, stale, wrong-process, wrong-executable, wrong-target, wrong-effect, or expired authority fails closed.

## Activation model

Loading enforcement is a transaction.

Hooks are attached while enforcement is inactive, required protected objects/policy are populated, and only then is enforcement enabled. A partial/failed load must not pretend to be active protection.

Pinned enforcement is independent of the evidence reader once active, while evidence collection may restart separately.

Whether Prevention is active on a particular machine is **runtime state**. Documentation, package presence, a historical VM campaign, or source support must not be used to claim live enforcement.

## Process control

Only explicitly registered critical process instances are protected.

A protected process identity includes enough information to prevent PID reuse or executable drift from inheriting authority. A restarted critical process must be registered again as its new process identity.

Signal 0 remains a permission probe. Real signals to protected targets require the accepted caller-to-target authority/signal scope.

Ordinary applications and development processes should retain normal Linux process-control behavior.

## Guardian relationship

Guardian consumes prevention evidence.

A denied mutation records what was attempted and that the protected mutation did not occur. One denial is not automatically a compromise verdict and does not automatically lower machine trust.

Repeated/correlated events may feed Guardian reasoning, but the evidence is not rewritten to fit an incident narrative.

Guardian also does not grant itself mutation authority merely because it observed a problem.

## Break glass

Break-glass is an exceptional, narrow authority path.

The accepted model requires:

- explicit interactive scope confirmation;
- fresh PolicyKit administrative authentication;
- one process/target/effect/operation scope;
- short expiry (bounded to minutes, not a persistent session);
- durable audit evidence.

Break-glass does not disable the whole boundary. There is no architectural permission for a permanent global off switch, hidden environment bypass, or generic `--force` that erases the authority model.

## Fail-closed semantics

For protected effects:

- no current authority → deny;
- stale authority → deny;
- wrong target/effect/process → deny;
- replayed/consumed authority → deny;
- unknown protected-state identity → do not infer permission.

For unprotected ordinary state, Prevention should not expand itself opportunistically. Fail-closed applies inside the accepted protected scope; it is not a license to freeze the whole machine.

## Security proof

Proof strength must match the claim.

Unit tests can validate policy logic. Integration tests can validate broker/kernel interfaces. A hostile disposable VM can validate the real enforcement boundary under bypass attempts. Physical claims require physical evidence.

Historical campaigns remain evidence of the source/scenario they tested. They never establish that the boundary is currently active or that newer source inherits the same certification automatically.
