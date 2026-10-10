# Snapper owner exclusion — Level C review

Scope: source and disposable-VM investigation under the human's Finish Permanent Storage mission. The existing file-only grant gains no snapshot effects. No production snapshot authority until every proof below passes.

## Problem and existing owner

Snapper owns metadata and snapshot mutation. Its daemon config lock excludes other clients' deletion but not SetSnapshot, SetSnapshotReadOnly, configuration changes or a second lock holder. Direct `--no-dbus` library access also bypasses daemon client locks. Update's lock cannot exclude these owners. Maho L3 currently creates important-marked targets/backups, but generic recovery discovery can select an ordinary coherent snapshot; its reference publication is not excluded by Update GC.

## Reviewed investigation

Keep Snapper as the owner. Test a version-pinned backend patch that makes config locks exclusive and checks them for metadata/configuration/topology writes under the existing server mutex. Acquire a kernel advisory exclusive lock on the descriptor for the authoritative snapshot information directory for each loaded library owner. Directory inode identity makes aliases share the boundary; no configurable lock-file path. The library lock is acquired before ACL changes or metadata initialization and retained by the Snapper object. Holding a daemon client config lock keeps that object loaded. Direct-library users then cannot mutate the same snapshot collection concurrently. No separate daemon or privileged Maho snapshot cleaner.

This alone is not retirement certification. A future exact executor must retain the same persistent daemon connection, bind its unique bus owner and backend payload, hold Update/recovery publication exclusion, reobserve exact filesystem/subvolume UUIDs, metadata/read-only/mounted/default/next-boot state, incident and generation references and retention policy, then delete only an individually journalled bounded owner-approved object. Recovery/incident claims must pin metadata or acquire an owner-tracked mount before publishing an external reference. Every existing writer must be proven to obey that protocol; unresolved writers block execution. Configured count/calendar floors are unconditional and unchanged. No pressure exception.

## Failure, lifetime and recovery

Unknown owner, changed backend/daemon identity, failed lock, corrupt/stale state, identity drift or missing writer proof denies snapshot mutation. A dead process releases kernel/client locks; a restarted owner does not inherit authority. Exact deletion needs fsynced PREPARED/retired journals, fresh checks on resume, independent owner-removal proof and actual available-capacity measurement. Never count an ambiguous interruption as reclaimed capacity. Important/manual/Maho/current/previous/recovery/incident objects remain protected. No direct Btrfs deletion or writable conversion fallback. Existing retained known-good roots remain the recovery route.

## Required proof

Real Snapper/Btrfs VM: two independent persistent clients; metadata, read-only, config and competing-lock denial; promotion before acquisition must survive; direct-library alias access refused during ownership; owner exit/SIGKILL/restart releases exclusion without preserving mutation authority. Use fixed own test config/subvolume and no production objects. Full certification additionally requires every recovery/reference writer, exact UUID/metadata/retention decisions, expiry/replay, deletion interruption/resume, retained roots and actual capacity gain. Partial backend exclusion proof never enables automatic snapshot retirement.
