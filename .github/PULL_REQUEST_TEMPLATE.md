## Summary

Describe the problem and the smallest coherent change.

## Scope

- Contribution level: A / B / C
- Primary component/owner:
- Existing backend/authority inspected:
- Out of scope:

## Architecture checklist

- [ ] I identified the existing owner before editing.
- [ ] This change does not create a duplicate subsystem or truth database.
- [ ] MahoSystem/MahoShell responsibility remains correct.
- [ ] Existing Linux/platform authority is reused where one exists.
- [ ] New/changed protected behavior fails closed on missing/stale/wrong authority.
- [ ] Any Level C architecture change had architecture review before implementation, or this PR is architecture-only.

## Verification

Exact commands/tests run:

```text
# commands here
```

Evidence actually performed:

- [ ] unit
- [ ] integration
- [ ] VM
- [ ] physical
- [ ] not applicable (documentation/governance only)

Do not select a stronger evidence level than was actually performed.

## Runtime completion

- [ ] Runtime verification is not relevant to this change.
- [ ] Deployed/runtime state was verified after source changes.
- [ ] Source is complete but deployment/convergence/verification is intentionally still pending and is stated below.

Runtime evidence / reason not applicable:

## Failure and recovery semantics

What happens on missing evidence, interruption, failed verification, or partial mutation?

## Security and privacy

- [ ] No credentials, private keys, recovery secrets, personal data, private machine paths, or raw private logs are included.
- [ ] Destructive/reboot/firmware behavior is explicit.
- [ ] Security-sensitive claims match the evidence level performed.

## Completion chain

State the furthest completed stage:

`SOURCE → TEST → MERGE → DEPLOY → CONVERGE → VERIFY → ACCEPT`

## Limitations / follow-up

List unresolved limitations without presenting them as completed.
