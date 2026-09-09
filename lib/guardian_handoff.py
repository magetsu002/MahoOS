#!/usr/bin/env python3
"""Bounded evidence preservation and L4 handoff records for Guardian."""
from __future__ import annotations
import json, os, tempfile
from pathlib import Path
from typing import Any, Mapping

MAX_ITEMS=32
MAX_PROCESS_ROWS=24
MAX_BYTES=262144
_ALLOWED_TOP={
 "incident_identity","boot_id","timestamps","guardian_version","guardian_source_revision",
 "runtime_identity","kernel_identity","root_filesystem_identity","recovery_generation_evidence",
 "active_high_severity_signals","privilege_evidence","integrity_evidence","persistence_evidence",
 "network_evidence","process_metadata",
}

def _bounded(value: Any, depth: int=0) -> Any:
    if depth>5: return "[bounded]"
    if isinstance(value, Mapping):
        out={}
        for k,v in list(value.items())[:MAX_ITEMS]:
            if isinstance(k,str) and not any(x in k.lower() for x in ("password","token","cookie","private_key","secret")):
                out[k]=_bounded(v,depth+1)
        return out
    if isinstance(value,list): return [_bounded(v,depth+1) for v in value[:MAX_ITEMS]]
    if isinstance(value,str): return value[:4096]
    if isinstance(value,(int,float,bool)) or value is None: return value
    return str(value)[:1024]

def build_evidence_record(observation: Mapping[str,Any], authority_decision: Mapping[str,Any]) -> dict[str,Any]:
    record={"version":1,"kind":"guardian-catastrophic-evidence"}
    for key in _ALLOWED_TOP:
        if key in observation:
            record[key]=_bounded(observation[key])
    if isinstance(record.get("process_metadata"),list):
        record["process_metadata"]=record["process_metadata"][:MAX_PROCESS_ROWS]
    record["authority_decision"]=_bounded(authority_decision)
    return record

def preserve_evidence(path: Path, record: Mapping[str,Any]) -> Path:
    data=(json.dumps(record,sort_keys=True,indent=2)+"\n").encode()
    if len(data)>MAX_BYTES:
        raise ValueError("catastrophic evidence record exceeds bounded storage contract")
    path.parent.mkdir(parents=True,exist_ok=True)
    os.chmod(path.parent,0o700)
    fd,tmp_name=tempfile.mkstemp(prefix=f".{path.name}.",dir=str(path.parent))
    tmp=Path(tmp_name)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"wb") as h:
            h.write(data); h.flush(); os.fsync(h.fileno())
        os.replace(tmp,path)
    finally:
        try: tmp.unlink()
        except FileNotFoundError: pass
    return path

def handoff_summary(decision: Mapping[str,Any], evidence_path: str|None=None) -> dict[str,Any]:
    return {
      "severity":4,"label":"catastrophic",
      "automatic_recovery_allowed":False,"automatic_host_mutation_allowed":False,
      "trusted_boundaries":list(decision.get("trusted_boundaries") or []),
      "untrusted_boundaries":list(decision.get("untrusted_boundaries") or []),
      "catastrophic_reasons":list(decision.get("catastrophic_reasons") or []),
      "safe_actions":list(decision.get("safe_actions") or []),
      "unsafe_actions":list(decision.get("unsafe_actions") or []),
      "evidence_preservation_required":True,
      "evidence_path":evidence_path,
      "recovery_handoff":list(decision.get("recovery_handoff") or []),
      "host_mutation_performed":False,
    }
