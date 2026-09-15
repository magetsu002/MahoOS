#!/usr/bin/env python3
"""Expose deterministic causal relationships on the canonical Guardian status."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from guardian_causal_projection import load_active_security_incidents, project_security_causality
from guardian_live_state import render_status


def enrich_status(payload: Mapping[str, Any], security_root: Path) -> dict[str, Any]:
    result = dict(payload)
    incidents, errors = load_active_security_incidents(security_root)
    graph = project_security_causality(incidents)
    result["causality"] = graph.as_dict()
    existing = result.get("errors")
    merged = list(existing) if isinstance(existing, list) else []
    merged.extend(f"causal_incident_malformed:{name}" for name in errors)
    result["errors"] = sorted(set(str(item) for item in merged))
    return result


def render_enriched_status(payload: Mapping[str, Any]) -> str:
    base = render_status(payload)
    causal = payload.get("causality") if isinstance(payload.get("causality"), Mapping) else {}
    counts = causal.get("counts") if isinstance(causal.get("counts"), Mapping) else {}
    edges = causal.get("edges") if isinstance(causal.get("edges"), list) else []
    lines = [
        base,
        "",
        "Causal relationships",
        f"  proven={int(counts.get('proven', 0))} correlated={int(counts.get('correlated', 0))} unknown={int(counts.get('unknown', 0))}",
    ]
    for edge in edges[:8]:
        if not isinstance(edge, Mapping):
            continue
        lines.append(
            f"  {edge.get('strength', 'unknown'):<10} {edge.get('source')} -> {edge.get('target')}  {edge.get('relation')}"
        )
    return "\n".join(lines)
