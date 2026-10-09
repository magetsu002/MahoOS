#!/usr/bin/env python3
"""Read-only Snapper protection classification for generation GC.

The installed backend has no read-only cleanup target enumerator, and L3
publication is not serialized with Update GC. No snapshot deletion authority
can be inferred from this diagnostic. Snapper stays the metadata/mutation owner.
"""
from __future__ import annotations
import re
from typing import Any, Mapping, Sequence
from maho_generation_gc import InventoryError, digest_payload

PROFILE = "snapper-owner-retention-awaiting-exclusion-certification-v1"


def protection_report(rows: Sequence[Mapping[str, Any]], *, uuid_by_number: Mapping[int, str],
                      referenced_uuids: Sequence[str], protected_numbers: Sequence[int] = (),
                      source_revision: str) -> dict[str, Any]:
    if re.fullmatch(r"[0-9a-f]{40}", source_revision) is None:
        raise InventoryError("snapshot report requires exact source identity")
    referenced, pinned = set(referenced_uuids), set(protected_numbers)
    seen, objects = set(), []
    for row in rows:
        fields = row.get("fields")
        if not isinstance(fields, Mapping) or re.fullmatch(r"[1-9][0-9]*", str(fields.get("num", ""))) is None:
            raise InventoryError("unknown Snapper metadata identity")
        number = int(fields["num"])
        if number in seen:
            raise InventoryError("duplicate Snapper snapshot number")
        seen.add(number)
        uuid = uuid_by_number.get(number)
        userdata = row.get("userdata")
        if not isinstance(userdata, list) or any(not isinstance(item, Mapping) or set(item) != {"key", "value"} for item in userdata):
            raise InventoryError("unknown Snapper recovery metadata")
        reasons = []
        if not isinstance(uuid, str) or re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", uuid) is None:
            reasons.append("snapshot_uuid_unresolved")
        if uuid in referenced or number in pinned:
            reasons.append("protected_generation_recovery_boot_or_incident_reference")
        if any(item["key"] == "important" and item["value"] != "no" for item in userdata):
            reasons.append("snapper_important_marker")
        if any(str(item["key"]).startswith("maho.") for item in userdata):
            reasons.append("maho_recovery_marker")
        cleanup, kind = fields.get("cleanup"), fields.get("type")
        if not ((cleanup == "timeline" and kind == "single") or (cleanup == "number" and kind in {"pre", "post"})):
            reasons.append("manual_or_unclassified_snapshot")
        # Labels identify the backend's retention lane, not its eligibility.
        objects.append({"number":number, "uuid":uuid, "type":kind, "cleanup":cleanup,
                        "metadata_sha256":row.get("sha256"), "protection_reasons":reasons,
                        "retirement_eligible":False})
    report = {"kind":"maho-snapper-retention-observation", "schema_version":1,
              "source_revision":source_revision, "profile":PROFILE,
              "execution_authorized":False, "plan":None, "objects":sorted(objects,key=lambda row:row["number"]),
              "blockers":["snapper_retention_eligibility_proof_unavailable",
                          "snapper_metadata_exclusion_uncertified",
                          "recovery_writer_exclusion_uncertified"]}
    report["observation_sha256"] = digest_payload(report)
    return report
