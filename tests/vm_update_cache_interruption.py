#!/usr/bin/env python3
"""Process-death cache provisioning reconciliation; disposable guest only."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"lib"))
if os.geteuid()!=0 or os.environ.get("MAHO_DISPOSABLE_VM_TEST")!="1":
    raise SystemExit("Explicit disposable guest scope required")
if not Path("/sys/class/dmi/id/product_name").read_text().startswith(("Standard PC","QEMU")):
    raise SystemExit("Refusing physical boundary")
import maho_update_cache_layout as layout
from maho_update_native import NativeBtrfsOps
from maho_update_campaign import _campaign_mutex
from maho_generation_gc import InventoryError

revision=subprocess.check_output(["git","-C",str(ROOT),"rev-parse","HEAD"],text=True).strip()
identity=NativeBtrfsOps("upd-20000101T000000Z-000000000009").root_identity()
results=[]
for index,phase in enumerate(("PREPARED","CREATED","UNIT_INSTALLED","MOUNTED")):
    # Fixture constants stay inside this guest; production constants have no
    # override interface. Each test owns a separate real subvolume and mount.
    cache=Path(f"/var/cache/maho/cache-proof-{index}")
    state=Path(f"/root/cache-install-proofs/{index}");state.mkdir(parents=True)
    unit=subprocess.check_output(["systemd-escape","--path","--suffix=mount",str(cache)],text=True).strip()
    with patch.multiple(layout,CACHE=cache,SUBVOLUME=f"@maho-cache-proof-{index}",
                        RECORD=state/"cache-layout.json",UNIT_NAME=unit,
                        UNIT_PATH=Path("/etc/systemd/system")/unit):
        plan=layout.installation_plan(revision,identity.filesystem_uuid)
        write=layout._atomic_json
        pid=os.fork()
        if pid==0:
            def interrupted(path,value,*args,**kwargs):
                write(path,value,*args,**kwargs)
                if path.name=="cache-installation.json" and value.get("phase")==phase:
                    os.kill(os.getpid(),signal.SIGKILL)
            with patch.object(layout,"_atomic_json",side_effect=interrupted),_campaign_mutex():
                layout.install_cache(plan,confirmation=plan["plan_sha256"],source_revision=revision)
            os._exit(99)
        _,status=os.waitpid(pid,0)
        assert os.WIFSIGNALED(status) and os.WTERMSIG(status)==signal.SIGKILL
        journal=json.loads((state/"cache-installation.json").read_text())
        assert journal["phase"]==phase
        with _campaign_mutex():
            record=layout.install_cache(plan,confirmation=plan["plan_sha256"],source_revision=revision)
        assert layout.observe_layout()==record
        try:
            with _campaign_mutex():
                layout.install_cache(plan,confirmation=plan["plan_sha256"],source_revision=revision)
        except InventoryError: pass
        else: raise AssertionError("completed installation was replayed")
        results.append({"interrupted_phase":phase,"signal":"SIGKILL","resume_phase":record["phase"],"replay_rejected":True})
print(json.dumps({"evidence_kind":"disposable-vm","source_revision":revision,"results":results}),flush=True)
