#!/usr/bin/env python3
"""Deterministic conflict resolver for adaptive proposals."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from maho_adaptive_proposal import AdaptationProposal, Effect, DISRUPTION_ORDER
from maho_adaptive_situation import SituationSnapshot, UNKNOWN

MIN_CONFIDENCE = 0.60


@dataclass(frozen=True)
class FieldResolution:
    effect: str
    value: str | None
    status: str
    winning_proposal_ids: tuple[str, ...]
    considered_proposal_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class ResolvedPosture:
    schema_version: int
    situation_snapshot_id: str
    effective_posture: tuple[tuple[str, str], ...]
    fields: tuple[FieldResolution, ...]
    rejected: tuple[tuple[str, str], ...]
    review_required: tuple[tuple[str, str, str], ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _source_freshness(snapshot: SituationSnapshot, source: str) -> str:
    prefix = source.split(".", 1)[0]
    mapping = {
        "battery": snapshot.power.freshness,
        "power": snapshot.power.freshness,
        "thermal": snapshot.thermal.freshness,
        "gaming": snapshot.workload.freshness,
        "workload": snapshot.workload.freshness,
        "compile": snapshot.workload.freshness,
        "render": snapshot.workload.freshness,
        "media": snapshot.workload.freshness,
        "network": snapshot.network.freshness,
        "maintenance": snapshot.maintenance.freshness,
        "guardian": snapshot.guardian.freshness,
        "reliability": snapshot.guardian.freshness,
        "intent": snapshot.user_intent.freshness,
        "notification": snapshot.user_intent.freshness,
    }
    return mapping.get(prefix, "fresh")


def _specificity(proposal: AdaptationProposal) -> int:
    return len(proposal.source_policy.split(".")) + len(proposal.supporting_evidence)


def _rank(proposal: AdaptationProposal) -> tuple[int, int, float, int]:
    # Higher priority/confidence/specificity wins. At equal authority, prefer
    # the less disruptive proposal instead of escalating gratuitously.
    return (
        proposal.priority,
        -DISRUPTION_ORDER[proposal.disruption_class],
        proposal.confidence,
        _specificity(proposal),
    )


def _current(snapshot: SituationSnapshot) -> dict[str, str]:
    return dict(snapshot.adaptive_posture.effective_posture)


def _eligible(snapshot: SituationSnapshot, proposals: Iterable[AdaptationProposal]) -> tuple[list[AdaptationProposal], list[tuple[str, str]]]:
    accepted: list[AdaptationProposal] = []
    rejected: list[tuple[str, str]] = []
    for proposal in sorted(proposals, key=lambda item: item.proposal_id):
        if proposal.situation_snapshot_id != snapshot.snapshot_id:
            rejected.append((proposal.proposal_id, "snapshot-mismatch"))
            continue
        if proposal.confidence < MIN_CONFIDENCE:
            rejected.append((proposal.proposal_id, "low-confidence"))
            continue
        freshness = _source_freshness(snapshot, proposal.source_policy)
        if freshness != "fresh":
            rejected.append((proposal.proposal_id, f"evidence-{freshness}"))
            continue
        accepted.append(proposal)
    return accepted, rejected


def _best_group(candidates: list[tuple[AdaptationProposal, Effect]]) -> tuple[list[tuple[AdaptationProposal, Effect]], tuple[int, int, float, int]]:
    ranked = sorted(candidates, key=lambda pair: (_rank(pair[0]), pair[0].proposal_id), reverse=True)
    best_rank = _rank(ranked[0][0])
    return [pair for pair in ranked if _rank(pair[0]) == best_rank], best_rank


def resolve_posture(snapshot: SituationSnapshot, proposals: Iterable[AdaptationProposal]) -> ResolvedPosture:
    accepted, rejected = _eligible(snapshot, proposals)
    current = _current(snapshot)
    requested: dict[str, list[tuple[AdaptationProposal, Effect]]] = {}
    prohibited: dict[str, list[tuple[AdaptationProposal, Effect]]] = {}
    review: list[tuple[str, str, str]] = []

    for proposal in accepted:
        target = requested if proposal.disruption_class in {"A", "B"} else None
        for effect in proposal.requested_effects:
            if target is None:
                review.append((proposal.proposal_id, effect.key, effect.value))
            else:
                target.setdefault(effect.key, []).append((proposal, effect))
        for effect in proposal.prohibited_effects:
            prohibited.setdefault(effect.key, []).append((proposal, effect))

    fields: list[FieldResolution] = []
    effective = dict(current)
    all_effects = sorted(set(requested) | set(current))

    for key in all_effects:
        candidates = requested.get(key, [])
        considered = tuple(sorted({proposal.proposal_id for proposal, _ in candidates}))
        if not candidates:
            fields.append(FieldResolution(key, current.get(key), "preserved", (), considered, "no eligible proposal; preserve current behavior"))
            continue

        best, best_rank = _best_group(candidates)
        values = {effect.value for _, effect in best}
        if len(values) > 1:
            existing = current.get(key)
            if existing in values:
                winners = tuple(sorted(p.proposal_id for p, e in best if e.value == existing))
                fields.append(FieldResolution(key, existing, "preserved", winners, considered, "equal authority conflict; existing lease posture breaks tie without creating a new adaptation"))
                effective[key] = existing
            else:
                effective.pop(key, None)
                fields.append(FieldResolution(key, current.get(key), "ambiguous", (), considered, "equal authority proposals conflict; no new adaptation is created"))
                if key in current:
                    effective[key] = current[key]
            continue

        value = next(iter(values))
        winners = [(p, e) for p, e in candidates if e.value == value and _rank(p) == best_rank]

        vetoes = [(p, e) for p, e in prohibited.get(key, []) if e.value == value]
        if vetoes:
            veto_best, veto_rank = _best_group(vetoes)
            if veto_rank > best_rank:
                fields.append(FieldResolution(key, current.get(key), "preserved", tuple(sorted(p.proposal_id for p, _ in veto_best)), considered, "higher-authority prohibition blocks requested effect"))
                if key not in current:
                    effective.pop(key, None)
                continue
            if veto_rank == best_rank:
                fields.append(FieldResolution(key, current.get(key), "ambiguous", (), considered, "equal-authority request/prohibition conflict; preserve current behavior"))
                if key not in current:
                    effective.pop(key, None)
                continue

        effective[key] = value
        fields.append(FieldResolution(
            key,
            value,
            "resolved",
            tuple(sorted(p.proposal_id for p, _ in winners)),
            considered,
            "highest coherent authority wins; compatible equal-value proposals retain joint provenance",
        ))

    return ResolvedPosture(
        1,
        snapshot.snapshot_id,
        tuple(sorted(effective.items())),
        tuple(fields),
        tuple(sorted(rejected)),
        tuple(sorted(review)),
    )
