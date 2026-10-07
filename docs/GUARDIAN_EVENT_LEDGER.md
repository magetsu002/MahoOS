# Guardian event ledger

Guardian's event ledger is a bounded historical record of normalized
`GuardianEvent` observations.

It is **not** a trust database. Historical records cannot establish current
system health or current trust.

## Storage

The initial ledger uses SQLite through Python's standard-library `sqlite3`
module rather than a Maho-specific database engine.

Maho owns the schema. SQLite provides transactional storage, indexes, dedupe,
and crash-safe persistence.

The repository does not vendor SQLite source or binaries as part of this
change.

The database lives below the caller-provided state root at:

`guardian/events/ledger.sqlite3`

The directory is mode `0700`; the database is mode `0600`. WAL mode and
`synchronous=FULL` are used so batched event writes remain durable without
turning every observation into a custom file-format/fsync implementation.

## Stored fields

The indexed columns are deliberately bounded:

- event identity/type/time
- boot identity
- provider/source identity
- observation-only authority boundary
- stable process identity/PID/UID/binary/parent identity
- target kind
- normalized target JSON
- complete normalized GuardianEvent JSON

Raw Tetragon payloads are not stored.

## Retention

Retention is explicit rather than silently hard-coded into the storage layer.

The ledger supports:

- maximum event count
- prune-before timestamp

The product policy that chooses actual retention limits belongs above this
module.

## Query model

The first query surface supports:

- stable process identity
- event type
- boot identity
- provider identity
- inclusive time window
- bounded result count
- chronological or newest-first ordering

Future trace reconstruction should consume these normalized queries rather than
reopening raw sensor logs.

## Evidence rule

Duplicate `event_id` records are idempotent.

Observation-gap and sensor-reset events belong in the same ledger as ordinary
events so later analysis can tell when history is incomplete.

No ledger record grants mutation authority.
