#!/bin/bash
# Publish the artifact + version manifest to the GitHub release Mangarr's
# in-app updater already polls. NEVER runs as part of a rebuild: publishing is
# public distribution, which needs an explicit go-ahead every time.
#
#   bash export/publish.sh            # dry run: print the manifest, change nothing
#   PUBLISH=1 bash export/publish.sh  # upload
#   PUBLISH=1 ROLLBACK_TO=opentome-YYYY-MM-DD bash export/publish.sh
#                                     # re-point the alias at an earlier build (below)
#
# Every published build gets its own release, tagged with the artifact's
# version label (opentome-YYYY-MM-DD): the artifact, version.json and the
# AniList report -- one release per build; a re-run replaces its assets. The
# alias tag (`metadata`, TAG) is what Mangarr polls; it is re-pointed by
# uploading the same artifact + manifest to it with --clobber.
# ROLLBACK_TO downloads an earlier build's two files and uploads them to the
# alias the same way -- every install downgrades on its next check, because the
# updater compares the date label in version.json. Nothing else is touched.
#
# Mangarr's MetadataUpdateService fetches version.json from the release, compares
# `gcd_dump` against the artifact it already has (IsNewer parses the date out of
# either label), downloads `artifact_url`, verifies sha256, checks the file opens
# as SQLite carrying that same `gcd_dump`, then swaps it in atomically.
#
# Auth: `gh` reads GH_TOKEN on its own (CI passes the fine-grained PAT that way);
# without it the logged-in `gh` on the workstation is used.
set -euo pipefail
cd "$(dirname "$0")/.."

REPO="${REPO:-DrAwesome441/mangarr-metadata}"
TAG="${TAG:-metadata}"
ART="${1:-build/manga-metadata.sqlite}"

need_gh() {
  command -v gh >/dev/null || { echo "gh CLI not installed" >&2; exit 1; }
  if [ -z "${GH_TOKEN:-}" ]; then
    gh auth status >/dev/null 2>&1 || { echo "gh is not authenticated and GH_TOKEN is unset" >&2; exit 1; }
  fi
}

if [ -n "${ROLLBACK_TO:-}" ]; then
  case "$ROLLBACK_TO" in
    opentome-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;;
    *) echo "refusing: ROLLBACK_TO is '$ROLLBACK_TO', expected opentome-YYYY-MM-DD (a per-build release tag)." >&2
       exit 1 ;;
  esac
  echo "repo        $REPO  (tag $TAG)"
  echo "rollback    $TAG -> release $ROLLBACK_TO (its manga-metadata.sqlite + version.json)"
  if [ "${PUBLISH:-0}" != "1" ]; then
    echo
    echo "DRY RUN. Nothing was uploaded. This re-points the PUBLIC alias every Mangarr polls:"
    echo "  - get Nick's explicit go-ahead"
    echo "  - then: PUBLISH=1 ROLLBACK_TO=$ROLLBACK_TO bash export/publish.sh"
    exit 0
  fi
  need_gh
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  gh release download "$ROLLBACK_TO" --repo "$REPO" --pattern manga-metadata.sqlite --pattern version.json --dir "$TMP"
  [ -f "$TMP/manga-metadata.sqlite" ] && [ -f "$TMP/version.json" ] \
    || { echo "release $ROLLBACK_TO does not carry both manga-metadata.sqlite and version.json" >&2; exit 1; }
  # artifact first, manifest second -- same reason as below
  gh release upload "$TAG" "$TMP/manga-metadata.sqlite" --repo "$REPO" --clobber
  gh release upload "$TAG" "$TMP/version.json" --repo "$REPO" --clobber
  echo
  echo "ROLLED BACK $TAG -> $ROLLBACK_TO ($REPO)"
  echo "Mangarr picks it up within 24h, or immediately via Settings -> Metadata Source -> Check Now."
  exit 0
fi
[ -f "$ART" ] || { echo "no artifact at $ART -- run tier0/rebuild_all.sh first" >&2; exit 1; }

q() { sqlite3 "$ART" "SELECT value FROM meta WHERE key='$1'"; }

VERSION="$(q gcd_dump)"
case "$VERSION" in
  opentome-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;;
  *) echo "refusing: meta.gcd_dump is '$VERSION', expected opentome-YYYY-MM-DD." >&2
     echo "The updater parses the date out of this label to decide what is newer." >&2
     exit 1 ;;
esac

# CLEAN ROOM. An artifact whose aliases were merged from the GCD-derived
# artifact is a derivative of CC BY-SA data and cannot be published. The pure
# build matches the live library exactly as well (40/41, docs/cleanup-v2.md),
# so this costs nothing.
PROV="$(q alias_provenance)"
if [ "$PROV" != "opentome" ]; then
  echo "refusing: meta.alias_provenance is '${PROV:-(absent)}', expected 'opentome'." >&2
  echo "Either aliases were merged from another artifact, or this predates the" >&2
  echo "stamp. Rebuild with PREV_ARTIFACT unset and publish that build." >&2
  exit 1
fi

SHA="$(shasum -a 256 "$ART" | cut -d' ' -f1)"
SIZE="$(wc -c < "$ART" | tr -d ' ')"
URL="https://github.com/$REPO/releases/download/$TAG/manga-metadata.sqlite"

cat > build/version.json <<JSON
{
  "gcd_dump": "$VERSION",
  "sha256": "$SHA",
  "size": $SIZE,
  "artifact_url": "$URL"
}
JSON

echo "repo        $REPO  (tag $TAG)"
echo "release     $VERSION  (one release per build; a re-run replaces its assets; $TAG is re-pointed at it)"
echo "artifact    $ART"
echo "version     $VERSION"
echo "sha256      $SHA"
echo "size        $SIZE bytes"
echo "series      $(sqlite3 "$ART" 'SELECT COUNT(*) FROM series')"
echo "volumes     $(sqlite3 "$ART" 'SELECT COUNT(*) FROM volumes')"
echo "licence     $(q licence)"
echo
echo "manifest -> build/version.json"

# A build whose DNB refresh degraded (tier0/build_dnb.py: DNB failed and some German result
# sets kept last week's page set) is built and gated, but never published -- only a clean
# refresh, or an offline rebuild of a complete cache, may replace the live artifact. Checked
# before the dry-run exit so the manifest step says so, but only a real publish stops on it
# (the weekly build must not fail over a DNB outage).
DEGRADED="$(q dnb_degraded)"
if [ -n "$DEGRADED" ]; then
  echo
  echo "DNB DEGRADED: $DEGRADED" >&2
  if [ "${PUBLISH:-0}" = "1" ]; then
    echo "refusing: meta.dnb_degraded is set -- rebuild once DNB answers, then publish that build." >&2
    exit 1
  fi
fi

# Ids are a public contract: a build that did not carry them from the last published artifact
# (meta.carried_from absent) re-issued every integer and redirected nothing. Only a deliberate
# cold start (OPENTOME_COLD_START=1 at build and here) may publish one. Same shape as above: the
# dry run says so, a real publish refuses.
CARRIED="$(q carried_from)"
if [ -z "$CARRIED" ]; then
  echo
  echo "NO ID CARRY: meta.carried_from is absent" >&2
  if [ "${PUBLISH:-0}" = "1" ] && [ "${OPENTOME_COLD_START:-0}" != "1" ]; then
    echo "refusing: this build did not carry ids from the published artifact (set OPENTOME_COLD_START=1 only for a deliberate cold start)." >&2
    exit 1
  fi
else
  echo "carried     $CARRIED"
fi

if [ "${PUBLISH:-0}" != "1" ]; then
  echo
  echo "DRY RUN. Nothing was uploaded. This publishes a dataset PUBLICLY:"
  echo "  - re-read docs/legal-position.md (free/non-commercial; attribution ships in meta)"
  echo "  - get Nick's explicit go-ahead"
  echo "  - then: PUBLISH=1 bash export/publish.sh"
  exit 0
fi

need_gh

# (a) The per-build release. A re-run for the same version must not fail: if
# the tag exists the assets are replaced, the release is not recreated.
ASSETS=("$ART" build/version.json)
[ -f build/anilist-resolve-report.tsv ] && ASSETS+=(build/anilist-resolve-report.tsv)
if gh release view "$VERSION" --repo "$REPO" >/dev/null 2>&1; then
  gh release upload "$VERSION" "${ASSETS[@]}" --repo "$REPO" --clobber
else
  gh release create "$VERSION" --repo "$REPO" --title "OpenTome $VERSION" \
    --notes "$(printf 'OpenTome %s: %s series, %s volumes.\n\nLicence: %s' \
               "$VERSION" "$(sqlite3 "$ART" 'SELECT COUNT(*) FROM series')" \
               "$(sqlite3 "$ART" 'SELECT COUNT(*) FROM volumes')" "$(q licence)")" \
    "${ASSETS[@]}"
fi

# (b) Re-point the alias. The alias release is created once and never deleted.
gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1 \
  || gh release create "$TAG" --repo "$REPO" --title "Metadata artifact" \
       --notes "Rolling release. version.json is the manifest Mangarr's updater polls."

# Upload the artifact FIRST: the manifest is the signal that a new version
# exists, so a client that polls between the two uploads must never see a
# manifest pointing at bytes that are not there yet.
gh release upload "$TAG" "$ART" --repo "$REPO" --clobber
gh release upload "$TAG" build/version.json --repo "$REPO" --clobber

echo
echo "PUBLISHED $VERSION -> $REPO (release $VERSION; alias $TAG re-pointed)"
echo "Mangarr picks it up within 24h, or immediately via Settings -> Metadata Source -> Check Now."
