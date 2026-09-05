#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/dist}"
SOURCE_REVISION="${MAHO_SOURCE_REVISION:-$(git -C "$ROOT" rev-parse HEAD)}"
if [ -n "${MAHO_VERSION:-}" ]; then
  PKGVER="$MAHO_VERSION"
else
  COUNT="$(git -C "$ROOT" rev-list --count "$SOURCE_REVISION")"
  SHORT="$(git -C "$ROOT" rev-parse --short=12 "$SOURCE_REVISION")"
  PKGVER="0.0.0.r${COUNT}.g${SHORT}"
fi

case "$PKGVER" in
  *[!A-Za-z0-9._+]*)
    echo "build-arch-package: invalid Arch pkgver: $PKGVER" >&2
    exit 2
    ;;
esac

for command in git tar zstd sha256sum python makepkg; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "build-arch-package: missing required command: $command" >&2
    exit 1
  }
done

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
WORK="$TMP/work"
mkdir -p "$WORK" "$OUT"

ARCHIVE="$WORK/maho-os-${PKGVER}.tar.zst"
git -C "$ROOT" archive --format=tar --prefix="maho-os-${PKGVER}/" "$SOURCE_REVISION" \
  | zstd -q -T0 -19 -o "$ARCHIVE"
SOURCE_SHA256="$(sha256sum "$ARCHIVE" | awk '{print $1}')"

python - "$WORK/release.json" "$PKGVER" "$SOURCE_REVISION" "$SOURCE_SHA256" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
path.write_text(json.dumps({
    "format_version": 1,
    "version": sys.argv[2],
    "source_revision": sys.argv[3],
    "source_archive_sha256": sys.argv[4],
}, indent=2, sort_keys=True) + "\n")
PY
RELEASE_SHA256="$(sha256sum "$WORK/release.json" | awk '{print $1}')"

python - "$ROOT/packaging/arch/PKGBUILD.in" "$WORK/PKGBUILD" "$PKGVER" "$SOURCE_SHA256" "$RELEASE_SHA256" <<'PY'
import pathlib
import sys

source = pathlib.Path(sys.argv[1]).read_text()
source = source.replace("@PKGVER@", sys.argv[3])
source = source.replace("@SOURCE_SHA256@", sys.argv[4])
source = source.replace("@RELEASE_SHA256@", sys.argv[5])
pathlib.Path(sys.argv[2]).write_text(source)
PY

(
  cd "$WORK"
  makepkg --clean --cleanbuild --force --nodeps --noconfirm
)

find "$WORK" -maxdepth 1 -type f -name 'maho-os-*.pkg.tar.*' -exec cp -f -- {} "$OUT/" \;
cp -f -- "$WORK/release.json" "$OUT/release.json"
(
  cd "$OUT"
  sha256sum maho-os-*.pkg.tar.* release.json > SHA256SUMS
)

printf 'PASS  package version      %s\n' "$PKGVER"
printf 'PASS  source revision      %s\n' "$SOURCE_REVISION"
printf 'PASS  source archive       %s\n' "$SOURCE_SHA256"
printf 'PASS  output directory     %s\n' "$OUT"
