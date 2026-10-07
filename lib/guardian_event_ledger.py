#!/usr/bin/env python3
"""Private, transactional storage for normalized GuardianEvent records.

SQLite is used as the storage mechanism; Guardian owns the schema and event
semantics. The ledger is historical evidence only and never establishes
current trust merely because an old record exists.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Iterable, Iterator, Sequence

from guardian_evidence import parse_timestamp
from guardian_event import GuardianEvent, GuardianEventKind, parse_guardian_event

SCHEMA_VERSION = 1


def ledger_path(state_root: Path) -> Path:
    return state_root / "guardian" / "events" / "ledger.sqlite3"


def _observed_us(value: str) -> int:
    observed = parse_timestamp(value)
    if observed is None:
        raise ValueError("Guardian event timestamp is missing")
    return int(observed.timestamp() * 1_000_000)


class GuardianEventLedger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)

        self._db = sqlite3.connect(str(self.path), timeout=5.0)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA busy_timeout = 5000")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute("PRAGMA synchronous = FULL")
        self._db.execute("PRAGMA temp_store = MEMORY")
        self._initialize()
        os.chmod(self.path, 0o600)

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "GuardianEventLedger":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _initialize(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                observed_us INTEGER NOT NULL,
                boot_id TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                source TEXT NOT NULL,
                source_event_type TEXT NOT NULL,
                source_record_digest TEXT NOT NULL,
                authority_boundary TEXT NOT NULL CHECK(authority_boundary = 'observation-only'),
                process_id TEXT,
                pid INTEGER,
                uid INTEGER,
                binary TEXT,
                parent_process_id TEXT,
                target_kind TEXT,
                target_json TEXT NOT NULL,
                event_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS events_observed_idx
                ON events(observed_us, sequence);
            CREATE INDEX IF NOT EXISTS events_process_idx
                ON events(process_id, observed_us, sequence);
            CREATE INDEX IF NOT EXISTS events_type_idx
                ON events(event_type, observed_us, sequence);
            CREATE INDEX IF NOT EXISTS events_boot_idx
                ON events(boot_id, observed_us, sequence);
            CREATE INDEX IF NOT EXISTS events_provider_idx
                ON events(provider_id, observed_us, sequence);
            """
        )
        row = self._db.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            self._db.execute(
                "INSERT INTO metadata(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._db.commit()
        elif row["value"] != str(SCHEMA_VERSION):
            raise ValueError(
                f"unsupported Guardian ledger schema: {row['value']}"
            )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            self._db.rollback()
            raise
        else:
            self._db.commit()

    @staticmethod
    def _row(event: GuardianEvent) -> tuple:
        payload = event.as_dict()
        process = event.process
        return (
            event.event_id,
            event.event_type.value,
            event.observed_at,
            _observed_us(event.observed_at),
            event.boot_id,
            event.provider_id,
            event.source,
            event.source_event_type,
            event.source_record_digest,
            event.authority_boundary,
            process.process_id if process else None,
            process.pid if process else None,
            process.uid if process else None,
            process.binary if process else None,
            process.parent_process_id if process else None,
            event.target_kind,
            json.dumps(dict(event.target), sort_keys=True, separators=(",", ":")),
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )

    def append(self, events: Iterable[GuardianEvent]) -> int:
        rows = [self._row(event) for event in events]
        if not rows:
            return 0

        before = self._db.total_changes
        with self._transaction():
            self._db.executemany(
                """
                INSERT OR IGNORE INTO events(
                    event_id, event_type, observed_at, observed_us, boot_id,
                    provider_id, source, source_event_type,
                    source_record_digest, authority_boundary, process_id, pid,
                    uid, binary, parent_process_id, target_kind, target_json,
                    event_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                rows,
            )
        return self._db.total_changes - before

    def get(self, event_id: str) -> GuardianEvent | None:
        row = self._db.execute(
            "SELECT event_json FROM events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["event_json"])
        return parse_guardian_event(payload)

    def query(
        self,
        *,
        process_id: str | None = None,
        event_types: Sequence[GuardianEventKind] = (),
        boot_id: str | None = None,
        provider_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 500,
        newest_first: bool = False,
    ) -> tuple[GuardianEvent, ...]:
        if limit < 1 or limit > 10000:
            raise ValueError("Guardian ledger query limit must be 1..10000")

        where: list[str] = []
        args: list[object] = []

        if process_id is not None:
            where.append("process_id = ?")
            args.append(process_id)
        if boot_id is not None:
            where.append("boot_id = ?")
            args.append(boot_id)
        if provider_id is not None:
            where.append("provider_id = ?")
            args.append(provider_id)
        if event_types:
            values = [kind.value for kind in event_types]
            where.append("event_type IN (" + ",".join("?" for _ in values) + ")")
            args.extend(values)
        if since is not None:
            where.append("observed_us >= ?")
            args.append(_observed_us(since))
        if until is not None:
            where.append("observed_us <= ?")
            args.append(_observed_us(until))

        clause = " WHERE " + " AND ".join(where) if where else ""
        order = "DESC" if newest_first else "ASC"
        args.append(limit)
        rows = self._db.execute(
            f"""
            SELECT event_json
            FROM events
            {clause}
            ORDER BY observed_us {order}, sequence {order}
            LIMIT ?
            """,
            tuple(args),
        ).fetchall()

        return tuple(parse_guardian_event(json.loads(row["event_json"])) for row in rows)

    def prune(
        self,
        *,
        max_events: int | None = None,
        before: str | None = None,
    ) -> int:
        if max_events is not None and max_events < 1:
            raise ValueError("max_events must be positive")
        cutoff_us = _observed_us(before) if before is not None else None

        before_changes = self._db.total_changes
        with self._transaction():
            if cutoff_us is not None:
                self._db.execute(
                    "DELETE FROM events WHERE observed_us < ?",
                    (cutoff_us,),
                )

            if max_events is not None:
                cutoff = self._db.execute(
                    """
                    SELECT sequence
                    FROM events
                    ORDER BY observed_us DESC, sequence DESC
                    LIMIT 1 OFFSET ?
                    """,
                    (max_events - 1,),
                ).fetchone()
                if cutoff is not None:
                    self._db.execute(
                        """
                        DELETE FROM events
                        WHERE (observed_us, sequence) < (
                            SELECT observed_us, sequence
                            FROM events
                            WHERE sequence = ?
                        )
                        """,
                        (cutoff["sequence"],),
                    )

        return self._db.total_changes - before_changes

    def stats(self) -> dict[str, object]:
        row = self._db.execute(
            """
            SELECT
                COUNT(*) AS event_count,
                MIN(observed_at) AS earliest_observed_at,
                MAX(observed_at) AS latest_observed_at,
                COUNT(DISTINCT boot_id) AS boot_count,
                COUNT(DISTINCT process_id) AS process_count
            FROM events
            """
        ).fetchone()
        self._db.execute("PRAGMA wal_checkpoint(PASSIVE)")
        wal = Path(str(self.path) + "-wal")
        return {
            "schema_version": SCHEMA_VERSION,
            "event_count": row["event_count"],
            "earliest_observed_at": row["earliest_observed_at"],
            "latest_observed_at": row["latest_observed_at"],
            "boot_count": row["boot_count"],
            "process_count": row["process_count"],
            "database_bytes": self.path.stat().st_size if self.path.exists() else 0,
            "wal_bytes": wal.stat().st_size if wal.exists() else 0,
        }
