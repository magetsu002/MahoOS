#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
CERT="$ROOT/tools/maho-vm-certify"
TORTURE="$ROOT/tools/maho-vm-torture"
GUEST="$ROOT/tools/vm/guest-torture.sh"
GCERT="$ROOT/tools/vm/guest-certify.sh"
VESKTOP="$ROOT/tests/vesktop-session-reliability.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }
req() {
  local file="$1" text="$2" message="$3"
  grep -Fq -- "$text" "$file" || fail "$message"
}

req "$CERT" 'torture-final-contracts' 'VM launcher does not admit final contracts profile'
req "$TORTURE" 'torture-final-contracts' 'full campaign omits final contracts profile'
req "$GCERT" 'torture-final-contracts' 'guest dispatcher omits final contracts profile'
req "$GCERT" 'PYTHONPYCACHEPREFIX="$HOME_VM/.cache/maho/vm-python"' 'VM user commands can write Python cache into the read-only source tree'
req "$CERT" 'mount_tag=wallpaper_picker' 'final VM does not mount exact live picker release'
req "$CERT" 'maho.vm.wallpaper_picker_revision=' 'picker revision is not bound into VM authority'
req "$CERT" 'maho.vm.wallpaper_picker_sha256=' 'picker tree digest is not bound into VM authority'
req "$GUEST" 'maho.vm.wallpaper_picker_sha256' 'guest does not verify bound picker tree digest'

for row in   'final-runtime-admission PREVENTED'   'final-runtime-interruption RECOVERED_AUTOMATICALLY'   'final-runtime-authority RECOVERED_WITH_AUTHORITY'   'final-persistence-authority PREVENTED'   'final-firewall-fail-closed DETECTED_ONLY'   'final-vesktop-recovery RECOVERED_AUTOMATICALLY'   'final-generation-gc RECOVERED_WITH_AUTHORITY'   'final-desktop-contracts DETECTED_ONLY'   'final-wallpaper-picker-reopen RECOVERED_AUTOMATICALLY'
do
  req "$GUEST" "scenario_run $row" "missing classified final-contract scenario: $row"
done

req "$GUEST" 'test_maho_runtime_deployment.py' 'runtime deployment contracts absent'
req "$GUEST" 'test_maho_persistence_transition.py' 'persistence contracts absent'
req "$GUEST" 'test_maho_firewall_receipt.py' 'firewall receipt contracts absent'
req "$GUEST" 'vesktop-session-reliability.sh' 'Vesktop reliability contracts absent'
req "$VESKTOP" 'rev-parse --is-inside-work-tree' 'Vesktop reliability contract requires Git metadata removed by VM isolation'
req "$GUEST" 'test_generation_gc.py' 'GC contracts absent'
req "$GUEST" 'maho-files-ux-closure-contracts.sh' 'Files closure contracts absent'
req "$GUEST" 'test_maho_system_tui.py' 'TUI contracts absent'
req "$GUEST" 'maho-link-contracts.sh' 'Edge/Link contracts absent'
req "$GUEST" 'open_picker.sh' 'real wallpaper picker launcher absent from final VM profile'
req "$GUEST" 'QT_QUICK_BACKEND=software' 'virtual-display picker launch is not pinned to the software renderer'
req "$GUEST" '"wallpaper-picker" in str(r.get("title","")).lower()' 'picker surface detector rejects the real Quickshell window title'
echo 'ALL FINAL VM CONTRACT WIRING PASS'
