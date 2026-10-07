#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

fail() {
    printf 'FAIL %s\n' "$1" >&2
    exit 1
}

pass() {
    printf 'PASS %s\n' "$1"
}

grep -q '^GNU GENERAL PUBLIC LICENSE$' "$ROOT/LICENSE" ||
    fail "Maho root GPL license changed unexpectedly"
pass "Maho root project license remains present"

doc="$ROOT/docs/GUARDIAN_TETRAGON_INTEGRATION.md"
grep -q 'Apache License 2.0' "$doc" ||
    fail "Tetragon root license boundary is undocumented"
grep -q 'GPL-2.0-only OR BSD-2-Clause' "$doc" ||
    fail "Tetragon BPF dual-license boundary is undocumented"
grep -q 'does not bundle or redistribute the Tetragon' "$doc" ||
    fail "current non-bundling boundary is undocumented"
pass "Tetragon license boundary is explicit"

for path in     "$ROOT/bin/tetragon"     "$ROOT/bin/tetra"     "$ROOT/bpf/tetragon"     "$ROOT/vendor/cilium/tetragon"     "$ROOT/third_party/tetragon"; do
    [ ! -e "$path" ] || fail "upstream Tetragon material was bundled at $path"
done
pass "no Tetragon executable/source tree is bundled in known integration paths"

if find "$ROOT/bpf" -maxdepth 1 -type f -iname '*tetragon*' -print -quit 2>/dev/null | grep -q .; then
    fail "Tetragon-derived BPF material appears in the Maho BPF tree"
fi
pass "Maho BPF tree contains no Tetragon-named source"

for policy in "$ROOT/config/guardian/tetragon-baseline.yaml"; do
    [ -r "$policy" ] || fail "missing Maho-owned Tetragon policy: $policy"
    if grep -Eq 'matchActions:|(^|[[:space:]])action:|Sigkill|Override|policy-mode:[[:space:]]*enforce|value:[[:space:]]*enforce' "$policy"; then
        fail "Maho baseline Tetragon policy contains an enforcement primitive"
    fi
done
pass "tracked baseline Tetragon policy is observation-only"

if grep -RIl --exclude='GUARDIAN_TETRAGON_INTEGRATION.md'     'Copyright Authors of Cilium'     "$ROOT/lib" "$ROOT/config/guardian" "$ROOT/bpf" 2>/dev/null | grep -q .; then
    fail "upstream Cilium-authored source appears copied into Maho integration code"
fi
pass "integration source has no copied Cilium copyright marker"

printf 'ALL GUARDIAN TETRAGON LICENSE BOUNDARY TESTS PASS\n'
