#!/usr/bin/env bash
set -euo pipefail

CACHE_ROOT="${MAHO_GUARDIAN_BAKEOFF_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/maho/guardian-sensor-bakeoff}"
TETRAGON_VERSION="1.7.1"
TRACEE_VERSION="0.24.1"
FALCO_LIBS_VERSION="0.26.0"

TETRAGON_SHA256="2f36a7bbb2b3d77a011383a01c8f804fe7761d934a76ff2fdf99ebad6f3e89ae"
TRACEE_SHA256="8cc56bd8c8dd3efadb0441c84849592affc48a71d3afbe7751a9e2014ef9ec85"

mkdir -p "$CACHE_ROOT/downloads" "$CACHE_ROOT/candidates"

download() {
    local url="$1" output="$2"
    if [[ ! -f "$output" ]]; then
        curl --fail --location --retry 3 --output "$output.part" "$url"
        mv "$output.part" "$output"
    fi
}

verify() {
    local expected="$1" path="$2" actual
    actual="$(sha256sum "$path" | cut -d' ' -f1)"
    [[ "$actual" == "$expected" ]] || {
        printf 'checksum mismatch: %s\n' "$path" >&2
        return 1
    }
}
tetragon_archive="$CACHE_ROOT/downloads/tetragon-v${TETRAGON_VERSION}-amd64.tar.gz"
tracee_archive="$CACHE_ROOT/downloads/tracee-x86_64.v${TRACEE_VERSION}.tar.gz"

download     "https://github.com/cilium/tetragon/releases/download/v${TETRAGON_VERSION}/tetragon-v${TETRAGON_VERSION}-amd64.tar.gz"     "$tetragon_archive"
verify "$TETRAGON_SHA256" "$tetragon_archive"

download     "https://github.com/aquasecurity/tracee/releases/download/v${TRACEE_VERSION}/tracee-x86_64.v${TRACEE_VERSION}.tar.gz"     "$tracee_archive"
verify "$TRACEE_SHA256" "$tracee_archive"

tetragon_dir="$CACHE_ROOT/candidates/tetragon-${TETRAGON_VERSION}"
tracee_dir="$CACHE_ROOT/candidates/tracee-${TRACEE_VERSION}"
falco_dir="$CACHE_ROOT/candidates/falco-libs-${FALCO_LIBS_VERSION}"

if [[ ! -d "$tetragon_dir" ]]; then
    mkdir -p "$tetragon_dir"
    tar -xzf "$tetragon_archive" -C "$tetragon_dir" --strip-components=1
fi

if [[ ! -d "$tracee_dir" ]]; then
    mkdir -p "$tracee_dir"
    tar -xzf "$tracee_archive" -C "$tracee_dir"
fi
if [[ ! -d "$falco_dir/.git" ]]; then
    rm -rf "$falco_dir"
    git clone --depth 1 --branch "$FALCO_LIBS_VERSION"         https://github.com/falcosecurity/libs.git "$falco_dir"
fi

tetragon_bin="$tetragon_dir/usr/local/bin/tetragon"
tracee_bin="$tracee_dir/dist/tracee-static"

[[ -x "$tetragon_bin" ]] || { echo "missing Tetragon binary" >&2; exit 1; }
[[ -x "$tracee_bin" ]] || { echo "missing Tracee binary" >&2; exit 1; }

cat <<EOF
Guardian sensor candidates staged without installation.

cache:       $CACHE_ROOT
tetragon:    $tetragon_bin
tetragon-bpf:$tetragon_dir/usr/local/lib/tetragon/bpf
tracee:      $tracee_bin
falco-libs:  $falco_dir

No privileged sensor was started and no system files were changed.
EOF
