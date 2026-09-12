#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
INSTALLER="$ROOT/bin/maho-l3-campaign-install"
WRAPPER="$ROOT/bin/maho-l3-campaign"

pass() { printf 'PASS %s\n' "$1"; }
fail() { printf 'FAIL %s\n' "$1" >&2; exit 1; }

bash -n "$INSTALLER" "$WRAPPER"
pass "campaign shell entrypoints parse"

set +e
wrapper_output="$(bash "$WRAPPER" --help 2>&1)"
wrapper_rc=$?
set -e
(( wrapper_rc != 0 )) || fail "source-tree wrapper unexpectedly executed"
grep -Fq 'refusing non-root-owned campaign payload' <<<"$wrapper_output" \
  || fail "source-tree wrapper refusal is missing"
pass "source-tree wrapper cannot become privileged authority"

REV="$(git -C "$ROOT" rev-parse HEAD)"
set +e
install_output="$(bash "$INSTALLER" install --repo "$ROOT" --revision "$REV" 2>&1)"
install_rc=$?
set -e
if (( EUID != 0 )); then
  (( install_rc != 0 )) || fail "non-root installer unexpectedly succeeded"
  grep -Fq 'root privileges are required' <<<"$install_output" \
    || fail "installer did not fail at root boundary"
fi
pass "installer has explicit root boundary"

[ -e "$ROOT/.git" ] || fail "test repository does not expose Git worktree metadata"
resolved_root="$(git -c safe.directory="$ROOT" -C "$ROOT" rev-parse --show-toplevel)"
[ "$(readlink -f -- "$resolved_root")" = "$(readlink -f -- "$ROOT")" ] \
  || fail "linked worktree top-level identity is not exact"
if grep -Fq '[ -d "$SOURCE_REPO/.git" ]' "$INSTALLER"; then
  fail "installer still assumes .git must be a directory"
fi
grep -Fq 'rev-parse --show-toplevel' "$INSTALLER" \
  || fail "installer does not validate linked worktree roots through Git"
pass "installer accepts linked-worktree Git metadata without weakening root identity"

grep -Fq 'git_cmd show "$rev:$file"' "$INSTALLER" \
  || fail "installer does not install exact committed blobs"
grep -Fq 'git_cmd cat-file -e "$EXPECTED_REV:$file"' "$INSTALLER" \
  || fail "installer does not preflight every committed payload file"
if grep -Fq '"$ROOT/$file"' "$INSTALLER"; then
  fail "installer still copies live worktree files"
fi
pass "installer trusts exact Git objects instead of worktree bytes"

grep -Fq '[[ "$EXPECTED_REV" =~ ^[0-9a-f]{40}$ ]]' "$INSTALLER" \
  || fail "installer does not require a full revision"
grep -Fq '"$dest/SOURCE_REVISION"' "$INSTALLER" \
  || fail "installed source revision is not verified"
grep -Fq 'find "$dest" -perm /022' "$INSTALLER" \
  || fail "installed payload writability is not audited"
grep -Fq '! -user root -o ! -group root' "$INSTALLER" \
  || fail "installed payload ownership is not audited"
pass "installed payload identity and permissions are verified"

if grep -En '(^|[[:space:];|&])(reboot|shutdown|poweroff|efibootmgr)([[:space:];|&]|$)' \
    "$INSTALLER" "$WRAPPER" >/dev/null; then
  fail "campaign bootstrap contains a reboot or firmware mutation command"
fi
pass "campaign bootstrap cannot reboot or edit firmware"

grep -Fq 'unset PYTHONPATH PYTHONHOME' "$WRAPPER" \
  || fail "wrapper inherits Python injection variables"
grep -Fq 'exec /usr/bin/python "$ROOT/lib/maho_system_restore_campaign.py"' "$WRAPPER" \
  || fail "wrapper does not execute installed campaign controller"
pass "wrapper executes only the installed Python authority"

echo 'ALL L3 CAMPAIGN INSTALL CONTRACTS PASS'
