# Guardian trace reconstruction

Guardian traces are bounded reconstructions over the normalized historical
event ledger.

They answer a different question from incidents:

> What did this process lineage do around this exact event?

A trace is not automatically a threat or incident.

## Anchor

Every trace starts from an exact `GuardianEvent.event_id`.

The default reconstruction window is 30 seconds before and after the anchor.
The query is restricted to the same boot identity.

## Process scope

When the anchor belongs to a process, Guardian includes:

- the seed process;
- its ancestor chain visible in the selected window;
- descendants of the seed process;
- file write-access observations for those process instances;
- network connect-attempt observations for those process instances.

Guardian deliberately does **not** pull sibling processes merely because they
share a parent. That would turn a focused trace into unrelated session noise.

## Causality

Trace graphs reuse Guardian's existing `PROVEN / CORRELATED / UNKNOWN`
causality model.

The current Tetragon-backed projector can prove:

- exact stable parent -> child process identity;
- exact process -> path write-access observation;
- exact process -> TCP connect-attempt observation.

It does **not** claim that a write-access hook proves a successful file content
mutation, or that a `tcp_connect` entry observation proves a successfully
established session.

## Coverage

Current trace coverage has only two states:

- `incomplete` — the window contains an observation-gap or sensor-reset event;
- `unknown` — no such gap is recorded, but end-to-end historical continuity is
  not independently proven.

There is intentionally no `complete` state yet.

Absence of a recorded gap is not proof that no gap occurred.

A future coverage-interval evidence type may add a proven-complete state once
the sensor can bind explicit start/end coverage receipts to the trace window.

## Bounded queries

The window query is capped. If it reaches the configured cap, the trace is
marked `truncated=true`.

A truncated trace must not be presented as a full reconstruction.
