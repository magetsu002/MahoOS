#!/usr/bin/env python3
"""L4 response adapter: evaluate authority and durably preserve evidence.

No recovery, shell, process, file-repair, boot, or containment executor exists
here. The only write is the bounded private evidence record.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping
from guardian_engine import evaluate_guardian
from guardian_handoff import build_evidence_record, handoff_summary, preserve_evidence

@dataclass(frozen=True)
class CatastrophicResponse:
    decision: dict[str,Any]
    evidence_preserved: bool
    evidence_path: str|None
    handoff: dict[str,Any]|None
    mutation_performed: bool=False
    def as_dict(self)->dict[str,Any]: return asdict(self)

def prepare_catastrophic_response(guardian_state:Mapping[str,Any], recovery_state:Mapping[str,Any], observation:Mapping[str,Any], evidence_path:Path)->CatastrophicResponse:
    decision=evaluate_guardian(guardian_state,recovery_state)
    catastrophic=decision.catastrophic
    if decision.severity.get("level")!=4 or not catastrophic.get("catastrophic"):
        return CatastrophicResponse(decision=decision.as_dict(),evidence_preserved=False,evidence_path=None,handoff=None)
    record=build_evidence_record(observation,catastrophic)
    preserve_evidence(evidence_path,record)
    return CatastrophicResponse(
        decision=decision.as_dict(), evidence_preserved=True, evidence_path=str(evidence_path),
        handoff=handoff_summary(catastrophic,str(evidence_path)), mutation_performed=False,
    )
