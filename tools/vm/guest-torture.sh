#!/usr/bin/env bash

source "/mnt/maho-src/tools/vm/torture-lib.sh"

TORTURE_ITERATIONS="$(cmdv maho.vm.torture_iterations || true)"
[[ "$TORTURE_ITERATIONS" =~ ^[0-9]+$ ]] || TORTURE_ITERATIONS=20

compile_kill_helper() {
  gcc -O2 -x c -o /var/tmp/maho-torture-kill - <<'C'
#include <signal.h>
#include <stdlib.h>
int main(int argc, char **argv) {
  if (argc != 2) return 2;
  long pid = strtol(argv[1], 0, 10);
  return pid > 1 && kill((pid_t)pid, SIGKILL) == 0 ? 0 : 1;
}
C
}

prepare_graphical_torture() {
  isolation
  torture_record_safety
  install_fresh
  install_graphical_authorities
  compile_kill_helper
  rm -rf "$HOME_VM/.cache/maho/files-release-build-"* 2>/dev/null || true
  systemctl daemon-reload
  if ! systemctl start sddm.service; then
    echo "FAIL  SDDM start failed before torture" >&2
    systemctl status sddm.service --no-pager || true
    journalctl -b --no-pager -u sddm.service | tail -160 || true
    return 1
  fi
  wait_graphical_session || return 1
  if ! wait_until 20 user_unit_active maho-guardian.service; then
    echo "FAIL  Guardian did not become active before torture" >&2
    u systemctl --user status maho-guardian.service --no-pager || true
    return 1
  fi
}

user_unit_active() {
  [ "$(u systemctl --user is-active "$1" 2>/dev/null || true)" = active ]
}

session_units_healthy() {
  local unit
  pgrep -u "$UID_VM" -x Hyprland >/dev/null || return 1
  for unit in maho-shell.service maho-dock.service maho-notify.service maho-awww-daemon.service maho-wallpaper.service maho-clipboard-history.service maho-guardian.service; do
    [ "$(u systemctl --user is-active "$unit" 2>/dev/null || true)" = active ] || return 1
  done
}

wallpaper_is_canonical() {
  graphical_user awww query -j 2>/dev/null | python3 - "$CANONICAL_WALLPAPER" <<'PY'
import json, os, sys
expected=os.path.realpath(sys.argv[1])
try: value=json.load(sys.stdin)
except Exception: raise SystemExit(1)
paths={os.path.realpath(row["displaying"]["image"]) for rows in value.values() for row in rows if row.get("displaying",{}).get("image")}
raise SystemExit(0 if paths == {expected} else 1)
PY
}

seed_canonical_wallpaper() {
  local current
  current="$(readlink -f "$HOME_VM/.local/share/maho/runtime/current")"
  CANONICAL_WALLPAPER="$HOME_VM/Pictures/Wallpapers/maho-torture-canonical.png"
  install -d -o "$UID_VM" -g "$UID_VM" "$HOME_VM/Pictures/Wallpapers"
  install -o "$UID_VM" -g "$UID_VM" -m 0644 "$current/config/quickshell/maho-shell/maho-guardian-rotor.png" "$CANONICAL_WALLPAPER"
  graphical_user awww img --transition-type none "$CANONICAL_WALLPAPER"
  wait_until 20 wallpaper_is_canonical
  wait_until 30 test -s "$HOME_VM/.local/state/maho/wallpaper/current.json"
  wait_until 60 test -s "$HOME_VM/.cache/maho/theme/active.json"
}

scenario_compositor_kill() {
  local directory="$1" iteration="$2" old new begin method
  old="$(pgrep -u "$UID_VM" -x Hyprland | head -1)"
  case $(((iteration - 1) % 4)) in
    0) method=kill;; 1) method=pkill;; 2) method=python;; 3) method=compiled;;
  esac
  begin="$(date +%s%N)"
  torture_kill_pid "$old" "$method" Hyprland
  wait_until 15 bash -c "! kill -0 $old 2>/dev/null"
  SCENARIO_DETECTION_MS=$((($(date +%s%N) - begin) / 1000000))
  wait_graphical_session
  new="$(pgrep -u "$UID_VM" -x Hyprland | head -1)"
  [ -n "$new" ] && [ "$new" != "$old" ]
  wait_until 45 session_units_healthy
  wait_until 45 wallpaper_is_canonical
  [ -s "$HOME_VM/.cache/maho/theme/active.json" ]
  wait_until 20 no_active_guardian_incidents
  SCENARIO_CONVERGENCE_MS=$((($(date +%s%N) - begin) / 1000000))
  SCENARIO_RECOVERY_MS="$SCENARIO_CONVERGENCE_MS"
  SCENARIO_ACTUAL=RECOVERED_AUTOMATICALLY
}

scenario_surface_kill() {
  local directory="$1" iteration="$2" unit old begin
  case "$iteration" in
    1) unit=maho-shell.service;;
    2) unit=maho-dock.service;;
    3) unit=maho-notify.service;;
    *) return 2;;
  esac
  old="$(unit_main_pid "$unit")"; begin="$(date +%s%N)"
  torture_kill_pid "$old" kill
  wait_until 15 unit_replaced "$unit" "$old"
  wait_until 20 no_active_guardian_incidents
  SCENARIO_CONVERGENCE_MS=$((($(date +%s%N) - begin) / 1000000))
  SCENARIO_DETECTION_MS="$SCENARIO_CONVERGENCE_MS"
  SCENARIO_RECOVERY_MS="$SCENARIO_CONVERGENCE_MS"
  SCENARIO_ACTUAL=RECOVERED_AUTOMATICALLY
}

scenario_all_surfaces() {
  local directory="$1" iteration="$2" unit begin old
  begin="$(date +%s%N)"
  for unit in maho-shell.service maho-dock.service maho-notify.service; do
    old="$(unit_main_pid "$unit")"
    printf '%s=%s\n' "$unit" "$old" >>"$directory/evidence/old-pids.txt"
    torture_kill_pid "$old" kill
  done
  wait_until 20 session_units_healthy
  wait_until 20 no_active_guardian_incidents
  SCENARIO_CONVERGENCE_MS=$((($(date +%s%N) - begin) / 1000000))
  SCENARIO_RECOVERY_MS="$SCENARIO_CONVERGENCE_MS"
  SCENARIO_ACTUAL=RECOVERED_AUTOMATICALLY
}

clipboard_workers_healthy() {
  local unit=maho-clipboard-history.service main cgroup count=0 pid args
  [ "$(u systemctl --user is-active "$unit" 2>/dev/null || true)" = active ] || return 1
  main="$(unit_main_pid "$unit")"
  cgroup="$(u systemctl --user show "$unit" -p ControlGroup --value)"
  [ -r "/sys/fs/cgroup${cgroup}/cgroup.procs" ] || return 1
  while read -r pid; do
    [ "$pid" = "$main" ] && continue
    args="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
    [[ "$args" == *wl-paste*--watch* ]] && count=$((count + 1))
  done <"/sys/fs/cgroup${cgroup}/cgroup.procs"
  [ "$count" -eq 2 ]
}

scenario_clipboard_worker_kill() {
  local directory="$1" iteration="$2" main worker begin
  main="$(unit_main_pid maho-clipboard-history.service)"
  worker="$(pgrep -P "$main" -x wl-paste | head -1)"
  [ -n "$worker" ]; begin="$(date +%s%N)"
  torture_kill_pid "$worker" kill
  wait_until 20 clipboard_workers_healthy
  ! kill -0 "$worker" 2>/dev/null
  wait_until 20 no_active_guardian_incidents
  SCENARIO_CONVERGENCE_MS=$((($(date +%s%N) - begin) / 1000000))
  SCENARIO_RECOVERY_MS="$SCENARIO_CONVERGENCE_MS"
  SCENARIO_ACTUAL=RECOVERED_AUTOMATICALLY
}

scenario_wallpaper_provider_race() {
  local directory="$1" iteration="$2" awww wallpaper begin
  awww="$(unit_main_pid maho-awww-daemon.service)"
  wallpaper="$(unit_main_pid maho-wallpaper.service)"
  begin="$(date +%s%N)"
  case "$iteration" in
    1) torture_kill_pid "$awww" kill; torture_kill_pid "$wallpaper" kill;;
    2) torture_kill_pid "$wallpaper" python; torture_kill_pid "$awww" kill;;
    *) torture_kill_pid "$awww" compiled; wait_until 10 unit_replaced maho-awww-daemon.service "$awww"; torture_kill_pid "$wallpaper" kill;;
  esac
  wait_until 30 session_units_healthy
  wait_until 45 wallpaper_is_canonical
  [ -s "$HOME_VM/.cache/maho/theme/active.json" ]
  wait_until 20 no_active_guardian_incidents
  SCENARIO_CONVERGENCE_MS=$((($(date +%s%N) - begin) / 1000000))
  SCENARIO_RECOVERY_MS="$SCENARIO_CONVERGENCE_MS"
  SCENARIO_ACTUAL=RECOVERED_AUTOMATICALLY
}

scenario_guardian_kill() {
  local directory="$1" iteration="$2" old begin
  old="$(unit_main_pid maho-guardian.service)"; begin="$(date +%s%N)"
  torture_kill_pid "$old" "$( [ $((iteration % 2)) -eq 0 ] && echo python || echo kill )"
  wait_until 20 unit_replaced maho-guardian.service "$old"
  wait_until 20 test -s "$HOME_VM/.local/state/maho/security/guardian/providers/guardian.watch.json"
  SCENARIO_CONVERGENCE_MS=$((($(date +%s%N) - begin) / 1000000))
  SCENARIO_RECOVERY_MS="$SCENARIO_CONVERGENCE_MS"
  SCENARIO_ACTUAL=RECOVERED_AUTOMATICALLY
}

scenario_stale_guardian_evidence() {
  local directory="$1" iteration="$2" heartbeat before after sequence
  heartbeat="$HOME_VM/.local/state/maho/security/guardian/providers/guardian.watch.json"
  wait_until 20 test -s "$heartbeat"
  before="$(sha256sum "$heartbeat" | awk '{print $1}')"
  sequence="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sequence"])' "$heartbeat")"
  torture_stop_user_unit maho-guardian.service
  sleep 3
  after="$(sha256sum "$heartbeat" | awk '{print $1}')"
  [ "$before" = "$after" ]
  u env PYTHONPATH="$SRC/lib" python3 - "$heartbeat" <<'PY'
import json, sys
from datetime import datetime, timezone
from guardian_evidence import EvidenceConfidence, EvidenceEnvelope, EvidenceFreshness, FreshnessPolicy, ProviderHealth
d=json.load(open(sys.argv[1]))
e=EvidenceEnvelope(provider_id=d["provider_id"],domain=d["domain"],schema_version=1,observed_at=d["last_success_at"],source=d["source"],freshness_policy=FreshnessPolicy(2),health=ProviderHealth(d["health"]),data=d.get("details",{}),confidence=EvidenceConfidence.HIGH,errors=tuple(d.get("errors",[])),authority_boundary=d["authority_boundary"])
assert e.freshness(now=datetime.now(timezone.utc)) is EvidenceFreshness.STALE
assert not e.decision_usable(now=datetime.now(timezone.utc))
PY
  u systemctl --user start maho-guardian.service
  wait_until 20 user_unit_active maho-guardian.service
  wait_until 20 bash -c "[ \$(python3 -c 'import json; print(json.load(open(\"$heartbeat\"))[\"sequence\"])') -gt $sequence ]"
  SCENARIO_ACTUAL=DETECTED_ONLY
}

scenario_journal_flood() {
  local directory="$1" iteration="$2" old flood begin
  begin="$(date +%s%N)"
  (
    for n in $(seq 1 2500); do
      u systemd-cat -t maho-torture-flood echo "benign observation $n" >/dev/null 2>&1 || exit
    done
  ) & flood=$!
  old="$(unit_main_pid maho-notify.service)"
  torture_kill_pid "$old" kill
  wait_until 20 unit_replaced maho-notify.service "$old"
  wait "$flood"
  wait_until 20 no_active_guardian_incidents
  SCENARIO_CONVERGENCE_MS=$((($(date +%s%N) - begin) / 1000000))
  SCENARIO_RECOVERY_MS="$SCENARIO_CONVERGENCE_MS"
  SCENARIO_ACTUAL=RECOVERED_AUTOMATICALLY
}

install_second_runtime() {
  local next=/var/tmp/maho-src-next
  rm -rf "$next"; cp -a "$SRC" "$next"
  python3 - "$next/share/maho/release.json" <<'PY'
import json, pathlib, sys
p=pathlib.Path(sys.argv[1]); d=json.loads(p.read_text()); d["source_revision"]="f"*40; p.write_text(json.dumps(d,sort_keys=True)+"\n")
PY
  printf '%s\n' 'torture second immutable release' >"$next/share/maho/torture-release"
  chown -R "$UID_VM:$UID_VM" "$next"
  u bash "$next/bin/maho-setup" install
  [ -L "$HOME_VM/.local/share/maho/runtime/previous" ]
}

scenario_runtime_corruption_recovery() {
  local directory="$1" iteration="$2" tool prepare corrupt recover campaign confirmation begin
  tool="$HOME_VM/.local/bin/maho-guardian-runtime-recovery-certify"
  begin="$(date +%s%N)"
  prepare="$(u "$tool" prepare)"; printf '%s\n' "$prepare" >"$directory/evidence/prepare.json"
  campaign="$(printf '%s' "$prepare" | python3 -c 'import json,sys; print(json.load(sys.stdin)["campaign_id"])')"
  confirmation="$(printf '%s' "$prepare" | python3 -c 'import json,sys; print(json.load(sys.stdin)["corruption_confirmation"])')"
  torture_destructive_gate
  corrupt="$(u "$tool" corrupt "$campaign" --confirm "$confirmation")"; printf '%s\n' "$corrupt" >"$directory/evidence/corrupt.json"
  SCENARIO_DETECTION_MS=$((($(date +%s%N) - begin) / 1000000))
  confirmation="$(printf '%s' "$corrupt" | python3 -c 'import json,sys; print(json.load(sys.stdin)["recovery_confirmation"])')"
  SCENARIO_MANUAL=true
  recover="$(u "$tool" recover "$campaign" --confirm "$confirmation")"; printf '%s\n' "$recover" >"$directory/evidence/recover.json"
  printf '%s' "$recover" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["phase"]=="VERIFIED" and d["receipt"]["verified"] is True and d["receipt"]["corrupted_generation_retained"] is True'
  u bash "$HOME_VM/.local/bin/maho-setup" status
  SCENARIO_CONVERGENCE_MS=$((($(date +%s%N) - begin) / 1000000))
  SCENARIO_RECOVERY_MS="$SCENARIO_CONVERGENCE_MS"
  SCENARIO_ACTUAL=RECOVERED_WITH_AUTHORITY
}

scenario_corrupt_recovery_prior() {
  local directory="$1" iteration="$2" runtime current previous target
  runtime="$HOME_VM/.local/share/maho/runtime"
  current="$(readlink -f "$runtime/current")"; previous="$(readlink -f "$runtime/previous")"
  target="$current/share/maho/runtime-source-revision"
  torture_destructive_gate
  chmod u+w "$target"; printf '%s\n' '# corrupt current too' >>"$target"; chmod a-w "$target"
  ! u env PYTHONPATH="$(readlink -f "$runtime/current")/lib" python3 "$SRC/lib/maho_runtime_release.py" "$current" --releases-root "$runtime/releases" >/dev/null 2>&1
  ! u env PYTHONPATH="$SRC/lib" python3 "$SRC/lib/maho_runtime_release.py" "$previous" --releases-root "$runtime/releases" >/dev/null 2>&1
  if u "$HOME_VM/.local/bin/maho-guardian-runtime-recovery-certify" prepare >"$directory/evidence/unsafe-prepare.json" 2>&1; then
    SCENARIO_REASON="Guardian offered recovery with corrupt current and prior"
    return 1
  fi
  SCENARIO_ACTUAL=DETECTED_ONLY
}

scenario_update_contracts() {
  local directory="$1" iteration="$2" test
  for test in state transaction staging preparation maintenance admission adversarial receipts native; do
    u env PYTHONPATH="$SRC/lib" python3 "$SRC/tests/test_maho_update_${test}.py"
  done
  SCENARIO_MANUAL=true
  SCENARIO_ACTUAL=RECOVERED_WITH_AUTHORITY
}

scenario_update_reboot_gap() {
  SCENARIO_REASON="persistent same-disk reboot interruption is not implemented by the V1 full-system harness"
  SCENARIO_ACTUAL=NOT_COVERED
}

scenario_enospc_atomicity() {
  local directory="$1" iteration="$2" mountpoint=/var/tmp/maho-torture-enospc state file
  mkdir -p "$mountpoint"; torture_mount_tmpfs "$mountpoint" 256k
  state="$mountpoint/state"; file="$state/guardian/providers/torture.storage.json"
  PYTHONPATH="$SRC/lib" python3 "$SRC/lib/guardian_provider_state.py" record --state-root "$state" --provider-id torture.storage --domain storage --source torture --authority-boundary disposable-vm --success --health healthy >/dev/null
  cp "$file" "$directory/evidence/before.json"
  if dd if=/dev/zero of="$mountpoint/fill" bs=64K status=none 2>/dev/null; then :; fi
  if PYTHONPATH="$SRC/lib" python3 "$SRC/lib/guardian_provider_state.py" record --state-root "$state" --provider-id torture.storage --domain storage --source torture --authority-boundary disposable-vm --success --health healthy >/dev/null 2>&1; then
    SCENARIO_REASON="durable publication unexpectedly succeeded under ENOSPC"; umount "$mountpoint"; return 1
  fi
  python3 -m json.tool "$file" >/dev/null
  rm -f "$mountpoint/fill"
  PYTHONPATH="$SRC/lib" python3 "$SRC/lib/guardian_provider_state.py" record --state-root "$state" --provider-id torture.storage --domain storage --source torture --authority-boundary disposable-vm --success --health healthy >/dev/null
  python3 -m json.tool "$file" >/dev/null
  umount "$mountpoint"
  SCENARIO_ACTUAL=RECOVERED_AUTOMATICALLY
}

scenario_readonly_atomicity() {
  local directory="$1" iteration="$2" mountpoint=/var/tmp/maho-torture-readonly state file
  mkdir -p "$mountpoint"; torture_mount_tmpfs "$mountpoint" 1m
  state="$mountpoint/state"; file="$state/guardian/providers/torture.readonly.json"
  PYTHONPATH="$SRC/lib" python3 "$SRC/lib/guardian_provider_state.py" record --state-root "$state" --provider-id torture.readonly --domain storage --source torture --authority-boundary disposable-vm --success --health healthy >/dev/null
  torture_destructive_gate; mount -o remount,ro "$mountpoint"
  if PYTHONPATH="$SRC/lib" python3 "$SRC/lib/guardian_provider_state.py" record --state-root "$state" --provider-id torture.readonly --domain storage --source torture --authority-boundary disposable-vm --success --health healthy >/dev/null 2>&1; then
    mount -o remount,rw "$mountpoint"; umount "$mountpoint"; SCENARIO_REASON="publication succeeded on read-only state"; return 1
  fi
  python3 -m json.tool "$file" >/dev/null
  mount -o remount,rw "$mountpoint"
  PYTHONPATH="$SRC/lib" python3 "$SRC/lib/guardian_provider_state.py" record --state-root "$state" --provider-id torture.readonly --domain storage --source torture --authority-boundary disposable-vm --success --health healthy >/dev/null
  umount "$mountpoint"
  SCENARIO_ACTUAL=RECOVERED_AUTOMATICALLY
}

scenario_compound_session_guardian() {
  local directory="$1" iteration="$2" guardian hypr begin
  guardian="$(unit_main_pid maho-guardian.service)"; hypr="$(pgrep -u "$UID_VM" -x Hyprland | head -1)"; begin="$(date +%s%N)"
  torture_kill_pid "$guardian" kill
  torture_kill_pid "$hypr" python
  wait_graphical_session
  wait_until 45 session_units_healthy
  wait_until 45 wallpaper_is_canonical
  wait_until 30 no_active_guardian_incidents
  SCENARIO_CONVERGENCE_MS=$((($(date +%s%N) - begin) / 1000000))
  SCENARIO_RECOVERY_MS="$SCENARIO_CONVERGENCE_MS"
  SCENARIO_ACTUAL=RECOVERED_AUTOMATICALLY
}

scenario_compound_session_dependencies() {
  local directory="$1" iteration="$2" hypr awww clipboard begin
  hypr="$(pgrep -u "$UID_VM" -x Hyprland | head -1)"; awww="$(unit_main_pid maho-awww-daemon.service)"; clipboard="$(unit_main_pid maho-clipboard-history.service)"; begin="$(date +%s%N)"
  torture_kill_pid "$hypr" kill
  torture_kill_pid "$awww" kill || true
  torture_kill_pid "$clipboard" kill || true
  wait_graphical_session
  wait_until 45 session_units_healthy
  wait_until 45 clipboard_workers_healthy
  wait_until 45 wallpaper_is_canonical
  wait_until 30 no_active_guardian_incidents
  SCENARIO_CONVERGENCE_MS=$((($(date +%s%N) - begin) / 1000000))
  SCENARIO_RECOVERY_MS="$SCENARIO_CONVERGENCE_MS"
  SCENARIO_ACTUAL=RECOVERED_AUTOMATICALLY
}

scenario_failure_storm() {
  local directory="$1" iteration="$2" n old begin
  begin="$(date +%s%N)"
  for n in $(seq 1 8); do
    old="$(unit_main_pid maho-notify.service)"
    torture_kill_pid "$old" kill
    wait_until 15 unit_replaced maho-notify.service "$old"
  done
  wait_until 30 no_active_guardian_incidents
  [ "$(u systemctl --user show maho-notify.service -p NRestarts --value)" -le 12 ]
  SCENARIO_CONVERGENCE_MS=$((($(date +%s%N) - begin) / 1000000))
  SCENARIO_RECOVERY_MS="$SCENARIO_CONVERGENCE_MS"
  SCENARIO_ACTUAL=RECOVERED_AUTOMATICALLY
}

torture_profile() {
  local profile="$1" iteration
  prepare_graphical_torture
  case "$profile" in
    torture-session)
      seed_canonical_wallpaper
      for iteration in $(seq 1 "$TORTURE_ITERATIONS"); do scenario_run session-compositor-kill RECOVERED_AUTOMATICALLY "$iteration" scenario_compositor_kill; done
      for iteration in 1 2 3; do scenario_run quickshell-surface-kill RECOVERED_AUTOMATICALLY "$iteration" scenario_surface_kill; done
      scenario_run quickshell-all-surfaces RECOVERED_AUTOMATICALLY 1 scenario_all_surfaces
      scenario_run clipboard-worker-kill RECOVERED_AUTOMATICALLY 1 scenario_clipboard_worker_kill
      for iteration in 1 2 3; do scenario_run wallpaper-provider-race RECOVERED_AUTOMATICALLY "$iteration" scenario_wallpaper_provider_race; done
      ;;
    torture-guardian)
      for iteration in $(seq 1 5); do scenario_run guardian-self-kill RECOVERED_AUTOMATICALLY "$iteration" scenario_guardian_kill; done
      scenario_run stale-guardian-evidence DETECTED_ONLY 1 scenario_stale_guardian_evidence
      scenario_run journal-flood-reconciliation RECOVERED_AUTOMATICALLY 1 scenario_journal_flood
      ;;
    torture-runtime)
      install_second_runtime
      scenario_run immutable-runtime-corruption RECOVERED_WITH_AUTHORITY 1 scenario_runtime_corruption_recovery
      scenario_run corrupt-recovery-prior DETECTED_ONLY 1 scenario_corrupt_recovery_prior
      ;;
    torture-update)
      scenario_run update-interruption-contracts RECOVERED_WITH_AUTHORITY 1 scenario_update_contracts
      scenario_run update-reboot-interruption NOT_COVERED 1 scenario_update_reboot_gap
      ;;
    torture-storage)
      scenario_run enospc-durable-publication RECOVERED_AUTOMATICALLY 1 scenario_enospc_atomicity
      scenario_run readonly-durable-publication RECOVERED_AUTOMATICALLY 1 scenario_readonly_atomicity
      ;;
    torture-compound)
      seed_canonical_wallpaper
      for iteration in $(seq 1 5); do scenario_run compound-session-guardian RECOVERED_AUTOMATICALLY "$iteration" scenario_compound_session_guardian; done
      scenario_run compound-session-wallpaper-clipboard RECOVERED_AUTOMATICALLY 1 scenario_compound_session_dependencies
      scenario_run bounded-ui-failure-storm RECOVERED_AUTOMATICALLY 1 scenario_failure_storm
      ;;
    *) return 2;;
  esac
  torture_profile_summary
  systemctl stop sddm.service
}
