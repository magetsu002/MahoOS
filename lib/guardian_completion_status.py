#!/usr/bin/env python3
"""Final read-only enrichments for the canonical Guardian status surface."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from guardian_causal_status import enrich_status as enrich_causality
from guardian_causal_status import render_enriched_status as render_causality
from guardian_reliability import load_live_reliability


def enrich_status(payload: Mapping[str, Any], security_root: Path) -> dict[str, Any]:
    result = enrich_causality(payload, security_root)
    reliability, freshness = load_live_reliability(security_root)
    result["reliability"] = reliability
    existing = result.get("evidence_freshness")
    merged = dict(existing) if isinstance(existing, Mapping) else {}
    merged.update(freshness)
    result["evidence_freshness"] = merged
    return result


def render_status(payload: Mapping[str, Any]) -> str:
    base = render_causality(payload)
    reliability = payload.get("reliability") if isinstance(payload.get("reliability"), Mapping) else {}
    counts = reliability.get("counts") if isinstance(reliability.get("counts"), Mapping) else {}
    findings = reliability.get("findings") if isinstance(reliability.get("findings"), list) else []
    lines = [
        base,
        "",
        "Reliability",
        f"  state={reliability.get('state', 'unknown')} healthy={int(counts.get('healthy', 0))} degraded={int(counts.get('degraded', 0))} unknown={int(counts.get('unknown', 0))}",
    ]
    for finding in findings:
        if not isinstance(finding, Mapping) or finding.get("state") == "healthy":
            continue
        lines.append(
            f"  {finding.get('state', 'unknown'):<9} {finding.get('subject')}  {finding.get('reason')}"
        )
    return "\n".join(lines)
