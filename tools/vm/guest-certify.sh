#!/usr/bin/env bash
set -euo pipefail
E=/mnt/maho-evidence
SRC=/var/tmp/maho-src
U=mahovm
UID_VM=1500
HOME_VM=/home/$U
RUN_VM=/run/user/$UID_VM
STATUS=failed
START_NS="$(date +%s%N)"

cmdv() {
  local k="$1" x
  for x in $(cat /proc/cmdline); do
    case "$x" in "$k"=*) printf '%s\n' "${x#*=}"; return 0;; esac
  done
  return 1
}
PROFILE="$(cmdv maho.vm.profile || true)"; [ -n "$PROFILE" ] || PROFILE=smoke
REV="$(cmdv maho.vm.source_revision || true)"
TORTURE_STAGE="$(cmdv maho.vm.torture_stage || true)"
[[ "$REV" =~ ^[0-9a-f]{40}$ ]] || REV=0000000000000000000000000000000000000000
mkdir -p "$E"
if [ -n "$TORTURE_STAGE" ]; then
  exec > >(tee "$E/guest-stage${TORTURE_STAGE}.log") 2>&1
else
  exec > >(tee "$E/guest.log") 2>&1
fi

finish() {
  rc=$?; trap - EXIT
  if [[ "$PROFILE" == torture-* ]] && [ -r "$E/summary.json" ]; then
    exit "$rc"
  fi
  python3 - "$E/summary.json" "$PROFILE" "$REV" "$STATUS" "$rc" "$START_NS" <<'PY'
import json,pathlib,sys,time
p,profile,rev,status,rc,start=sys.argv[1:]
pathlib.Path(p).write_text(json.dumps({"schema_version":1,"profile":profile,
"source_revision":rev,"status":status if int(rc)==0 else "failed",
"exit_code":int(rc),"duration_seconds":round((time.time_ns()-int(start))/1e9,3)},
sort_keys=True,indent=2)+"\n")
PY
  exit "$rc"
}
trap finish EXIT

eq() { [ "$1" = "$2" ] || { echo "FAIL  $3 expected=$1 actual=$2" >&2; return 1; }; echo "PASS  $3"; }
need() { [ -e "$1" ] || { echo "FAIL  missing $1" >&2; return 1; }; echo "PASS  file $1"; }

isolation() {
  r="$(findmnt -n -o FSTYPE /)"; h="$(findmnt -n -o FSTYPE /home)"; s="$(findmnt -n -o FSTYPE /mnt/maho-src)"
  eq overlay "$r" "disposable root"
  if [ "$(cmdv maho.vm.diskhome || true)" = "1" ]; then
    eq ext4 "$h" "isolated disk-backed home"
  else
    eq tmpfs "$h" "isolated home"
  fi
  eq 9p "$s" "read-only source transport"
  ! touch /mnt/maho-src/.vm-write-probe 2>/dev/null || { rm -f /mnt/maho-src/.vm-write-probe; return 1; }
  printf 'root=%s\nhome=%s\nsource=%s\nboot_id=%s\n' "$r" "$h" "$s" "$(cat /proc/sys/kernel/random/boot_id)" >"$E/isolation.env"
}

prepare_source() {
  rm -rf "$SRC"; mkdir -p "$SRC"; cp -a /mnt/maho-src/. "$SRC/"; rm -rf "$SRC/.git"
  mkdir -p "$SRC/share/maho"
  python3 - "$SRC/share/maho/release.json" "$REV" <<'PY'
import json,pathlib,sys
pathlib.Path(sys.argv[1]).write_text(json.dumps({"schema_version":1,"source_revision":sys.argv[2],
"certification_source":"maho-vm-overlay"},sort_keys=True)+"\n")
PY
}

create_user() {
  getent passwd "$U" >/dev/null || useradd -m -u "$UID_VM" -s /bin/bash "$U"
  install -d -o "$UID_VM" -g "$UID_VM" -m 0700 "$HOME_VM"
  systemctl start systemd-logind.service
  loginctl enable-linger "$U"
  systemctl start "user@$UID_VM.service"
  for _ in $(seq 1 100); do [ -S "$RUN_VM/bus" ] && break; sleep .05; done
  [ -S "$RUN_VM/bus" ] || { echo "FAIL  user bus unavailable" >&2; return 1; }
}

u() {
  runuser -u "$U" -- env HOME="$HOME_VM" USER="$U" LOGNAME="$U" XDG_RUNTIME_DIR="$RUN_VM" \
  DBUS_SESSION_BUS_ADDRESS="unix:path=$RUN_VM/bus" PYTHONPYCACHEPREFIX="$HOME_VM/.cache/maho/vm-python" \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/bin "$@"
}

install_fresh() {
  prepare_source; create_user
  u bash "$SRC/bin/maho-setup" preflight
  u bash "$SRC/bin/maho-setup" install
  u bash "$SRC/bin/maho-setup" status
  cur="$(readlink -f "$HOME_VM/.local/share/maho/runtime/current")"
  need "$cur/manifest.json"; need "$cur/share/maho/runtime-source-revision"
  eq "$REV" "$(tr -d '\n' <"$cur/share/maho/runtime-source-revision")" "runtime provenance"
  need "$HOME_VM/.local/bin/maho-session"; need "$HOME_VM/.local/bin/maho-power"
  need "$HOME_VM/.config/systemd/user/maho-shell.service"
  ! grep -RIl '/home/magetsu' "$HOME_VM/.local/bin" "$HOME_VM/.config/systemd/user" 2>/dev/null | grep -q .
}

update_tests() {
  for t in state transaction staging preparation maintenance admission adversarial receipts native cli; do
    echo "RUN update-$t"; u env PYTHONPATH="$SRC/lib" python3 "$SRC/tests/test_maho_update_${t}.py"
  done
  u bash "$SRC/tests/setup-live-migration-contracts.sh"
}

fresh_profile() {
  isolation; install_fresh
  u systemctl --user --failed --no-legend --no-pager >"$E/user-failed.txt"
  [ ! -s "$E/user-failed.txt" ] || { cat "$E/user-failed.txt"; return 1; }
}

update_profile() {
  isolation; install_fresh
  a="$(readlink -f "$HOME_VM/.local/share/maho/runtime/current")"
  u bash "$SRC/bin/maho-setup" install
  b="$(readlink -f "$HOME_VM/.local/share/maho/runtime/current")"
  eq "$a" "$b" "idempotent reinstall"
  update_tests
}

autonomy_convergence_profile() {
  isolation
  install_fresh
  local campaign_repo=/var/tmp/maho-autonomy-campaign
  git clone --no-checkout "$E/source.bundle" "$campaign_repo"
  git -C "$campaign_repo" checkout --detach "$REV"
  bash "$campaign_repo/bin/maho-update-campaign-install" install \
    --repo "$campaign_repo" --revision "$REV"

  local unit
  for unit in \
    maho-update-coordinator.service \
    maho-update-coordinator.timer \
    maho-update-activate-on-reboot.service; do
    cmp "$SRC/config/systemd/system/$unit" "/usr/lib/systemd/system/$unit"
    echo "PASS  installed exact $unit"
  done
  systemctl is-enabled --quiet maho-update-coordinator.timer
  systemctl is-active --quiet maho-update-coordinator.timer
  systemctl is-enabled --quiet maho-update-activate-on-reboot.service
  systemctl is-active --quiet maho-update-activate-on-reboot.service
  echo "PASS  automatic coordinator and explicit-reboot sentinel are enabled and active"

  local deadline=$((SECONDS + 150))
  while [ ! -r /var/lib/maho/update/coordinator.json ] && [ "$SECONDS" -lt "$deadline" ]; do
    sleep 1
  done
  [ -r /var/lib/maho/update/coordinator.json ] || {
    systemctl status maho-update-coordinator.timer maho-update-coordinator.service --no-pager || true
    return 1
  }
  while [ "$SECONDS" -lt "$deadline" ]; do
    case "$(systemctl show -p ActiveState --value maho-update-coordinator.service)" in
      inactive|failed) break ;;
      *) sleep 1 ;;
    esac
  done
  case "$(systemctl show -p ActiveState --value maho-update-coordinator.service)" in
    inactive|failed) ;;
    *) systemctl status maho-update-coordinator.service --no-pager || true; return 1 ;;
  esac
  cp /var/lib/maho/update/coordinator.json "$E/coordinator.json"
  systemctl status maho-update-coordinator.timer maho-update-coordinator.service \
    --no-pager >"$E/systemd-status.txt" || true
  python3 - "$E/coordinator.json" "$REV" <<'PY_AUTONOMY'
import json
import pathlib
import sys

state = json.loads(pathlib.Path(sys.argv[1]).read_text())
revision = sys.argv[2]
assert state["source_revision"] == revision, state
assert state["phase"] == "BLOCKED", state
assert state["blockers"], state
assert state["live_root_mutation_started"] is False, state
assert state["reboot_performed"] is False, state
print("PASS  timer initiated coordination and unavailable prerequisites failed closed")
PY_AUTONOMY
}

adversarial_profile() {
  isolation; install_fresh
  u env PYTHONPATH="$SRC/lib" python3 "$SRC/tests/test_adaptive_adversarial.py"
  u env PYTHONPATH="$SRC/lib" python3 "$SRC/tests/test_guardian_g4_adversarial.py"
  u env PYTHONPATH="$SRC/lib" python3 "$SRC/tests/test_maho_update_adversarial.py"
  bash "$SRC/tests/firewall-certification-contracts.sh"
  bash "$SRC/tests/firewall-policy-netns.sh"
  bash "$SRC/tests/firewall-transaction-netns.sh"
  cur="$(readlink -f "$HOME_VM/.local/share/maho/runtime/current")"
  cp -p "$cur/bin/maho-power" /tmp/maho-power.verified
  printf '\n# vm-corruption\n' >>"$cur/bin/maho-power"
  ! u bash "$SRC/bin/maho-setup" status >/dev/null 2>&1 || { echo "FAIL  corrupt runtime accepted"; return 1; }
  ! u bash "$SRC/bin/maho-setup" install >/dev/null 2>&1 || { echo "FAIL  corrupt immutable release was overwritten"; return 1; }
  cat /tmp/maho-power.verified >"$cur/bin/maho-power"; chmod a-w "$cur/bin/maho-power"
  u bash "$SRC/bin/maho-setup" status
  ! ip -brief link | grep -Ev '^[[:space:]]*lo[[:space:]]' | grep -q . || { echo "FAIL  external NIC present"; return 1; }
}

seed_hypr_fixture() {
  local rel
  install -d -o "$UID_VM" -g "$UID_VM" "$HOME_VM/.config/hypr/maho/core" \
    "$HOME_VM/.config/hypr/maho/appearance" "$HOME_VM/.config/hypr/maho/theme"
  install -o "$UID_VM" -g "$UID_VM" -m 0644 "$SRC/config/hypr/hyprland.lua" "$HOME_VM/.config/hypr/hyprland.lua"
  for rel in \
    maho/core/binds.lua maho/core/input.lua maho/core/windowing.lua \
    maho/appearance/animations.lua maho/appearance/decorations.lua \
    maho/theme/fallback.lua maho/theme/palette.lua; do
    install -o "$UID_VM" -g "$UID_VM" -m 0644 "$SRC/config/hypr/$rel" "$HOME_VM/.config/hypr/$rel"
  done
  echo "PASS  seeded canonical pre-installer Hyprland fixture"
}

install_graphical_authorities() {
  local cur
  cur="$(readlink -f "$HOME_VM/.local/share/maho/runtime/current")"
  MAHO_ROOT="$cur" MAHO_PLATFORM_STATE_ROOT=/run/maho-platform "$cur/bin/maho-platform-install" install
  MAHO_ROOT="$cur" MAHO_PLATFORM_STATE_ROOT=/run/maho-platform "$cur/bin/maho-platform-install" status
  MAHO_SDDM_USER="$U" bash "$cur/bin/maho-lock-sddm-install" install
  bash "$cur/bin/maho-lock-sddm-install" status
  seed_hypr_fixture

  install -d -m 0755 /etc/sddm.conf.d
  cat >/etc/sddm.conf.d/99-maho-vm-autologin.conf <<EOF
[Autologin]
User=$U
Session=maho
Relogin=true
EOF
}

wait_graphical_session() {
  local i shell dock notify target
  for i in $(seq 1 400); do
    if pgrep -u "$UID_VM" -x Hyprland >/dev/null 2>&1; then
      target="$(u systemctl --user is-active maho-hyprland-session.target 2>/dev/null || true)"
      shell="$(u systemctl --user is-active maho-shell.service 2>/dev/null || true)"
      dock="$(u systemctl --user is-active maho-dock.service 2>/dev/null || true)"
      notify="$(u systemctl --user is-active maho-notify.service 2>/dev/null || true)"
      if [ "$target:$shell:$dock:$notify" = "active:active:active:active" ]; then
        return 0
      fi
    fi
    sleep 0.1
  done
  echo "FAIL  graphical Maho session did not converge" >&2
  systemctl status sddm.service --no-pager || true
  u systemctl --user --failed --no-pager || true
  journalctl -b --no-pager -u sddm.service | tail -120 || true
  return 1
}

graphical_user() {
  local line
  local -a vars=()
  while IFS= read -r line; do
    case "$line" in
      WAYLAND_DISPLAY=*|HYPRLAND_INSTANCE_SIGNATURE=*|DISPLAY=*|XDG_CURRENT_DESKTOP=*|XDG_SESSION_DESKTOP=*|XDG_SESSION_TYPE=*)
        vars+=("$line")
        ;;
    esac
  done < <(u systemctl --user show-environment)
  u env "${vars[@]}" "$@"
}

record_session() {
  local label="$1" hypr sid
  hypr="$(pgrep -u "$UID_VM" -x Hyprland | head -1)"
  sid="$(loginctl list-sessions --no-legend | awk -v uid="$UID_VM" '$2==uid {print $1; exit}')"
  {
    echo "label=$label"
    echo "hyprland_pid=$hypr"
    echo "session_id=$sid"
    [ -n "$sid" ] && loginctl show-session "$sid" -p Active -p Class -p Type -p Service -p Desktop
  } >>"$E/session-cycles.txt"
}

session_profile() {
  isolation
  install_fresh
  install_graphical_authorities
  rm -rf "$HOME_VM/.cache/maho/files-release-build-"* 2>/dev/null || true
  systemctl daemon-reload
  systemctl start sddm.service
  wait_graphical_session
  record_session initial

  local cycle old new
  for cycle in $(seq 1 10); do
    old="$(pgrep -u "$UID_VM" -x Hyprland | head -1)"
    graphical_user "$HOME_VM/.local/bin/maho-power" action logout
    for _ in $(seq 1 400); do
      new="$(pgrep -u "$UID_VM" -x Hyprland | head -1 || true)"
      [ -n "$new" ] && [ "$new" != "$old" ] && break
      sleep 0.1
    done
    [ -n "$new" ] && [ "$new" != "$old" ] || { echo "FAIL  logout cycle $cycle did not replace Hyprland"; return 1; }
    wait_graphical_session
    record_session "cycle-$cycle"
  done

  u systemctl --user --failed --no-legend --no-pager >"$E/user-failed-after-cycles.txt"
  [ ! -s "$E/user-failed-after-cycles.txt" ] || { cat "$E/user-failed-after-cycles.txt"; return 1; }
  echo "PASS  ten SDDM logout/relogin cycles"
  systemctl stop sddm.service
}

performance_profile() {
  local short="${PROFILE#performance-}" cur
  isolation
  install_fresh
  install_graphical_authorities
  rm -rf "$HOME_VM/.cache/maho/files-release-build-"* 2>/dev/null || true
  systemctl daemon-reload
  systemctl start sddm.service
  wait_graphical_session
  record_session "performance-parent"

  cur="$(readlink -f "$HOME_VM/.local/share/maho/runtime/current")"
  local guest_evidence="$HOME_VM/.local/state/maho/certification/vm-memory-$short"
  rm -rf "$guest_evidence" "$E/memory-$short"
  install -d -o "$UID_VM" -g "$UID_VM" "$(dirname "$guest_evidence")"
  graphical_user "$HOME_VM/.local/bin/maho-memory-certify" run "$short" \
    --evidence "$guest_evidence" --timeout 300
  mkdir -p "$E/memory-$short"
  cp -R --no-preserve=ownership "$guest_evidence/." "$E/memory-$short/"
  cat >"$E/performance-authority.json" <<EOF
{"schema_version":1,"pressure_recovery_authority":"vm","gpu_rendered_idle_pss_authority":"physical-hardware","virtual_display":"bochs-display","note":"Software-rendered Qt PSS in this VM is intentionally not used as the physical idle-memory verdict."}
EOF

  python3 - "$E/memory-$short/summary.json" "$short" <<'PY'
import json, pathlib, sys
p=pathlib.Path(sys.argv[1]); profile=sys.argv[2]
d=json.loads(p.read_text())
assert d.get("profile")==profile, d
assert d.get("pass") is True, d
conds=d.get("pass_conditions") or {}
assert conds and all(conds.values()), conds
print("PASS  low-memory profile", profile,
      "idle_pss_mib=", d.get("idle_pss_mib"),
      "peak_memory_mib=", d.get("peak_memory_mib"),
      "recovery_memory_mib=", d.get("recovery_memory_mib"))
PY

  u systemctl --user --failed --no-legend --no-pager >"$E/user-failed-after-performance.txt"
  [ ! -s "$E/user-failed-after-performance.txt" ] || { cat "$E/user-failed-after-performance.txt"; return 1; }
  systemctl stop sddm.service
}
case "$PROFILE" in
  smoke) isolation;;
  fresh-user) fresh_profile;;
  update-freeze) update_profile;;
  autonomy-convergence) autonomy_convergence_profile;;
  resilience) adversarial_profile;;
  session) session_profile;;
  performance-4g|performance-8g) performance_profile;;
  torture-session|torture-guardian|torture-runtime|torture-runtime-executor|torture-runtime-executor-after|torture-runtime-guardian-verifying|torture-postconditions|torture-network|torture-update|torture-update-compound|torture-storage|torture-final-contracts|torture-compound|torture-root-destruction)
    source "/mnt/maho-src/tools/vm/guest-torture.sh"
    torture_profile "$PROFILE"
    ;;
  torture-reboot-awaiting|torture-reboot-recovering|torture-reboot-verifying)
    source "/mnt/maho-src/tools/vm/guest-torture.sh"
    torture_reboot_profile "$PROFILE" "$TORTURE_STAGE"
    ;;
  torture-reboot-update-phases)
    source "/mnt/maho-src/tools/vm/guest-torture.sh"
    torture_update_reboot_profile "$TORTURE_STAGE"
    ;;
  *) echo "FAIL  unknown profile $PROFILE" >&2; exit 2;;
esac
STATUS=passed
echo "ALL MAHO VM PROFILE CHECKS PASS profile=$PROFILE"
