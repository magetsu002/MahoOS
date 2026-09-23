#!/usr/bin/env bash
# Shared fail-closed safety and evidence helpers for destructive guest profiles.

TORTURE_SCHEMA_VERSION=1
TORTURE_ROOT="$E/scenarios"
TORTURE_SAFETY="$E/safety.json"
SCENARIO_ACTUAL=""
SCENARIO_REASON=""
SCENARIO_DETECTION_MS="null"
SCENARIO_RECOVERY_MS="null"
SCENARIO_CONVERGENCE_MS="null"
SCENARIO_BLOCKED=false
SCENARIO_HOST_MUTATION=false
SCENARIO_MANUAL=false

torture_fail() {
  echo "FAIL  $*" >&2
  return 1
}

torture_assert_safety() {
  local root_fs home_fs source_fs source_opts evidence_fs evidence_opts vendor product allowed device target opts
  [ "$(cmdv maho.vm.torture || true)" = 1 ] || torture_fail "torture marker absent"
  root_fs="$(findmnt -n -o FSTYPE /)"
  home_fs="$(findmnt -n -o FSTYPE /home)"
  source_fs="$(findmnt -n -o FSTYPE /mnt/maho-src)"
  source_opts="$(findmnt -n -o OPTIONS /mnt/maho-src)"
  evidence_fs="$(findmnt -n -o FSTYPE /mnt/maho-evidence)"
  evidence_opts="$(findmnt -n -o OPTIONS /mnt/maho-evidence)"
  [ "$root_fs" = overlay ] || torture_fail "root is not disposable overlay"
  [ "$home_fs" = ext4 ] || torture_fail "home is not dedicated disposable ext4"
  [ "$source_fs" = 9p ] && [[ ",$source_opts," == *,ro,* ]] || torture_fail "source is not read-only 9p"
  [ "$evidence_fs" = 9p ] && [[ ",$evidence_opts," == *,rw,* ]] || torture_fail "evidence is not writable 9p"
  if touch /mnt/maho-src/.torture-write-probe 2>/dev/null; then
    rm -f /mnt/maho-src/.torture-write-probe
    torture_fail "source write probe succeeded"
  fi
  while read -r target opts; do
    if [[ ",$opts," == *,rw,* ]] && [ "$target" != /mnt/maho-evidence ]; then
      torture_fail "unexpected writable host share: $target"
    fi
  done < <(findmnt -rn -t 9p -o TARGET,OPTIONS)
  if findmnt -rn -t 9p -o TARGET,OPTIONS | awk '$1 ~ /maho\/lower$/ && $2 !~ /(^|,)ro(,|$)/ {exit 0} END {exit 1}'; then
    torture_fail "host root transport is writable"
  fi
  allowed="$(cmdv maho.vm.allowed_writable_block || true)"
  [ "$allowed" = vda ] || torture_fail "dedicated block allowlist missing"
  [ "$(findmnt -n -o SOURCE /home)" = /dev/vda ] || torture_fail "dedicated block is not mounted only as home"
  for device in /sys/class/block/*; do
    device="${device##*/}"
    case "$device" in loop*|ram*|zram*) continue;; esac
    if [ "$device" != "$allowed" ]; then
      [ "$(cat "/sys/class/block/$device/ro" 2>/dev/null || true)" = 1 ] || torture_fail "unexpected writable block device exposed: $device"
      grep -qi qemu "/sys/class/block/$device/device/model" 2>/dev/null || torture_fail "unexpected non-QEMU block device exposed: $device"
    fi
  done
  [[ "$(readlink -f /sys/class/block/vda/device 2>/dev/null || true)" == *virtio* ]] || torture_fail "writable disk is not virtio guest media"
  vendor="$(cat /sys/class/dmi/id/sys_vendor 2>/dev/null || true)"
  product="$(cat /sys/class/dmi/id/product_name 2>/dev/null || true)"
  [[ "$vendor $product" =~ QEMU|KVM|Standard.PC ]] || torture_fail "machine is not expected QEMU guest"
  for device in /sys/class/net/*; do
    [ "${device##*/}" = lo ] || torture_fail "non-loopback network interface exposed: ${device##*/}"
  done
  return 0
}

torture_record_safety() {
  torture_assert_safety
  python3 - "$TORTURE_SAFETY" "$REV" <<'PY'
import json, pathlib, subprocess, sys
def out(*argv):
    return subprocess.check_output(argv, text=True).strip()
payload = {
    "schema_version": 1,
    "source_revision": sys.argv[2],
    "torture_marker": True,
    "root_filesystem": out("findmnt", "-n", "-o", "FSTYPE", "/"),
    "home_filesystem": out("findmnt", "-n", "-o", "FSTYPE", "/home"),
    "home_source": out("findmnt", "-n", "-o", "SOURCE", "/home"),
    "source_options": out("findmnt", "-n", "-o", "OPTIONS", "/mnt/maho-src"),
    "evidence_options": out("findmnt", "-n", "-o", "OPTIONS", "/mnt/maho-evidence"),
    "network_interfaces": sorted(p.name for p in pathlib.Path("/sys/class/net").iterdir()),
    "block_devices": sorted(p.name for p in pathlib.Path("/sys/class/block").iterdir()),
    "boot_id": pathlib.Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
    "physical_host_block_device_exposed": False,
    "host_root_writable": False,
    "passed": True,
}
path = pathlib.Path(sys.argv[1]); path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
PY
}

torture_destructive_gate() {
  torture_assert_safety || {
    echo "ABORT  destructive action refused by VM safety predicate" >&2
    return 125
  }
}

torture_kill_pid() {
  local pid="$1" method="${2:-kill}" comm="${3:-}"
  torture_destructive_gate || return
  [[ "$pid" =~ ^[0-9]+$ ]] && [ "$pid" -gt 1 ] || return 2
  case "$method" in
    kill) kill -KILL "$pid" ;;
    pkill) [ -n "$comm" ] && [ "$(pgrep -x "$comm" | wc -l)" -eq 1 ] && pkill -KILL -x "$comm" ;;
    python) python3 - "$pid" <<'PY'
import os, signal, sys
os.kill(int(sys.argv[1]), signal.SIGKILL)
PY
      ;;
    compiled) /var/tmp/maho-torture-kill "$pid" ;;
    *) return 2 ;;
  esac
}

torture_stop_user_unit() {
  torture_destructive_gate || return
  u systemctl --user stop "$1"
}

torture_mount_tmpfs() {
  torture_destructive_gate || return
  mount -t tmpfs -o "size=$2,mode=0700" tmpfs "$1"
}

unit_main_pid() {
  u systemctl --user show "$1" -p MainPID --value
}

wait_until() {
  local timeout="$1"; shift
  local start=$SECONDS
  while ! "$@"; do
    [ $((SECONDS - start)) -lt "$timeout" ] || return 1
    sleep 0.1
  done
}

unit_replaced() {
  local unit="$1" old="$2" pid
  pid="$(unit_main_pid "$unit" 2>/dev/null || true)"
  [ "$(u systemctl --user is-active "$unit" 2>/dev/null || true)" = active ] &&
    [[ "$pid" =~ ^[0-9]+$ ]] && [ "$pid" -gt 1 ] && [ "$pid" != "$old" ] && ! kill -0 "$old" 2>/dev/null
}

no_active_guardian_incidents() {
  local active="$HOME_VM/.local/state/maho/security/guardian/active"
  [ ! -d "$active" ] || ! find "$active" -maxdepth 1 -type f -name '*.json' -print -quit | grep -q .
}

torture_capture_guardian() {
  local output="$1"
  python3 - "$output" "$HOME_VM/.local/state/maho/security" "$UID_VM" <<'PY'
import json, pathlib, subprocess, sys
out, root, uid = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3]
active = root / "guardian" / "active"
rows=[]
if active.is_dir():
    for p in sorted(active.glob("*.json")):
        try: rows.append(json.loads(p.read_text()))
        except Exception: rows.append({"path": str(p), "invalid": True})
def state(unit):
    r=subprocess.run(["runuser","-u","mahovm","--","env","HOME=/home/mahovm","XDG_RUNTIME_DIR=/run/user/1500","DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1500/bus","systemctl","--user","is-active",unit],capture_output=True,text=True)
    return r.stdout.strip() or "unknown"
payload={"guardian_unit":state("maho-guardian.service"),"active_incident_count":len(rows),"active_incidents":rows}
out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
PY
}

scenario_reset() {
  SCENARIO_ACTUAL=""
  SCENARIO_REASON=""
  SCENARIO_DETECTION_MS="null"
  SCENARIO_RECOVERY_MS="null"
  SCENARIO_CONVERGENCE_MS="null"
  SCENARIO_BLOCKED=false
  SCENARIO_HOST_MUTATION=false
  SCENARIO_MANUAL=false
}

scenario_run() {
  local name="$1" expected="$2" iteration="$3" function="$4"
  local directory="$TORTURE_ROOT/$name/iteration-$iteration" start_ns end_ns rc pass=false
  mkdir -p "$directory/evidence"
  scenario_reset
  torture_capture_guardian "$directory/guardian-before.json"
  start_ns="$(date +%s%N)"
  set +e
  "$function" "$directory" "$iteration" >"$directory/guest.log" 2>&1
  rc=$?
  set -e
  end_ns="$(date +%s%N)"
  torture_capture_guardian "$directory/guardian-after.json"
  journalctl --user -b --no-pager --since "@$((start_ns / 1000000000))" >"$directory/journal.log" 2>&1 || true
  u systemctl --user --no-pager --failed >"$directory/service-state.txt" 2>&1 || true
  [ -n "$SCENARIO_ACTUAL" ] || SCENARIO_ACTUAL=BUG
  if [ "$rc" -ne 0 ]; then
    SCENARIO_ACTUAL=BUG
    [ -n "$SCENARIO_REASON" ] || SCENARIO_REASON="scenario function exited $rc"
  fi
  if [ "$SCENARIO_ACTUAL" = "$expected" ] && [ "$rc" -eq 0 ]; then pass=true; fi
  python3 - "$directory/summary.json" "$REV" "$name" "$iteration" "$expected" "$SCENARIO_ACTUAL" "$start_ns" "$end_ns" "$SCENARIO_DETECTION_MS" "$SCENARIO_RECOVERY_MS" "$SCENARIO_CONVERGENCE_MS" "$SCENARIO_HOST_MUTATION" "$SCENARIO_BLOCKED" "$SCENARIO_MANUAL" "$pass" "$SCENARIO_REASON" <<'PY'
import json, pathlib, sys
(path,rev,name,iteration,expected,actual,start,end,detection,recovery,convergence,host,blocked,manual,passed,reason)=sys.argv[1:]
def number(value): return None if value == "null" else int(value)
before=json.loads((pathlib.Path(path).parent/"guardian-before.json").read_text())
after=json.loads((pathlib.Path(path).parent/"guardian-after.json").read_text())
payload={"schema_version":1,"source_revision":rev,"scenario":name,"iteration":int(iteration),"expected_outcome":expected,"actual_outcome":actual,"start_time_ns":int(start),"end_time_ns":int(end),"detection_latency_ms":number(detection),"recovery_latency_ms":number(recovery),"convergence_latency_ms":number(convergence),"guardian_before":before,"guardian_after":after,"incidents_before":before["active_incident_count"],"incidents_after":after["active_incident_count"],"host_mutation_performed":host=="true","protected_effect_blocked":blocked=="true","manual_intervention_required":manual=="true","pass":passed=="true","failure_reason":reason or None}
pathlib.Path(path).write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
PY
  if [ "$pass" = true ]; then
    echo "PASS  torture scenario=$name iteration=$iteration outcome=$SCENARIO_ACTUAL"
  else
    echo "FAIL  torture scenario=$name iteration=$iteration expected=$expected actual=$SCENARIO_ACTUAL reason=$SCENARIO_REASON" >&2
    return 1
  fi
}

torture_profile_summary() {
  python3 - "$E/summary.json" "$PROFILE" "$REV" "$START_NS" "$TORTURE_ROOT" <<'PY'
import json, pathlib, sys, time
path,profile,revision,start,root=sys.argv[1:]
rows=[]
for item in sorted(pathlib.Path(root).glob("*/iteration-*/summary.json")):
    rows.append(json.loads(item.read_text()))
passed=bool(rows) and all(row.get("pass") for row in rows)
counts={}
for row in rows: counts[row["actual_outcome"]]=counts.get(row["actual_outcome"],0)+1
payload={"schema_version":1,"profile":profile,"source_revision":revision,"status":"passed" if passed else "failed","exit_code":0 if passed else 1,"duration_seconds":round((time.time_ns()-int(start))/1e9,3),"scenario_count":len(rows),"outcomes":counts,"scenarios":rows}
pathlib.Path(path).write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
raise SystemExit(0 if passed else 1)
PY
}
