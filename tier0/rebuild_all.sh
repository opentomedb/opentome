#!/bin/bash
# Full rebuild pipeline, in dependency order. Every stage is cache-backed, so a
# complete re-run costs minutes rather than hours and zero additional network.
#
#   0. unit tests      parser / collapse / resolve -- a rebuild on a broken
#                      parser is worse than no rebuild
#   1. work identity   langlinks -> cross-language work classes  (MUST precede build)
#   2. corpus en+fr    Wikipedia volume-list templates
#   3. corpus de       wikitables, discovered via langlinks
#   3b. official titles main-article + redirect names (the titles folders use)
#   3c. main articles  status / first / last / publishers / people / genres from the main
#   3d. relations      sequel / spin-off / adaptation from titles and shared main articles
#                      article's infobox (one request per work, cached)
#   3e. dnb            the German market from the Deutsche Nationalbibliothek (CC0): print
#                      manga / light novels of Japanese origin, ISBN-merged into the German
#                      Wikipedia lines, linked to works by title + author (high/medium ship,
#                      low/ambiguous -> build/dnb-review.tsv). ~340 SRU requests at >= 3 s
#                      on a cold cache (~22 min), zero on a warm one (tier0/build_dnb.py)
#   4b. covers         ISBN-keyed cover URLs from the cached openBD /
#                      Open Library responses -- zero requests
#   4. enrichment      openBD (JP) / Open Library (EN, FR) / BnF (FR)
#   5. clean           date_type, Jan-1 precision, malformed ISBNs
#   5b. corrections    hand-checked values (corrections/), applied after clean
#                      so clean cannot undo them and before resolve so the
#                      confidence layer reports them as manual_override
#   6. resolve         claims -> values + confidence
#   7. audit           report remaining defects -- EXITS NON-ZERO on any defect
#   8. export          Mangarr-shaped artifact (+ curated aliases, + id carry)
#   8a. anilist ids   series.anilist_id for English lines (export/resolve_anilist.py, cached), then
#                      corrections/anilist.json's hand-checked ids over the resolver's pick, then
#                      the DISPLAY-ONLY fallback (display_anilist_id -- never a binding) for lines
#                      still NULL, then build/anilist-covers.json for the final ids (pinned and
#                      display ids included)
#   8c. contract       export/test_artifact.py on the new artifact, plus the German (DNB)
#                      rules that need the catalogue's provenance (cc0, dates, linker fixture)
#   8d. measure gate   replay Mangarr's series pick over the committed library snapshot
#                      (export/fixtures/library.json) -- EXITS NON-ZERO on a coverage
#                      failure (an owned volume the picked line lacks); then the German
#                      floors (lines, volumes, date / page coverage, link rate, same ids on
#                      reload); log in build/measure.log
#
# The catalogue is built into a FRESH database and renamed over the old one at
# the end. Building on top of the existing file skipped every article already
# marked done, so a parser fix changed nothing and the run still printed
# REBUILD COMPLETE -- the exact silent-success failure this pipeline exists to
# avoid. Set KEEP_DB=1 to resume an interrupted first build instead.
set -euo pipefail
# NEVER suppress stderr in this pipeline. An earlier run redirected enrichment
# output to /dev/null; the scripts failed on relative paths, wrote zero claims,
# and the pipeline reported success. auto-acceptable silently fell 24% -> 3.5%
# and nothing surfaced it except a later audit. Failures must be loud.
cd "$(dirname "$0")/.."
mkdir -p build
FINAL="${1:-$PWD/build/opentome.db}"
if [ "${KEEP_DB:-0}" = "1" ]; then
  DB="$FINAL"
else
  DB="$FINAL.building"
  rm -f "$DB"
fi
ART="$PWD/build/manga-metadata.sqlite"
# Two different "previous" artifacts, never confused:
#   ID_CARRY      -- the last OpenTome export; its integer series ids are a
#                    consumer-facing contract and are carried forward. Automatic.
#   PREV_ARTIFACT -- a HAND-CURATED artifact whose aliases are worth keeping
#                    (the library's own folder-name bridges). Explicit only:
#                    merging a previous OpenTome export's aliases re-imports
#                    whatever alias fan-out that export had.
ID_CARRY=""
if [ -f "$ART" ]; then ID_CARRY="$ART"; fi
PREV="${PREV_ARTIFACT:-}"

echo "== 0. unit tests ==";        python3 tier0/test_parser.py >/dev/null && echo "   parser ok"
                                   python3 tier2/test_resolve.py >/dev/null && echo "   resolve ok"
                                   python3 export/test_resolve_anilist.py >/dev/null && echo "   anilist ok"
                                   python3 export/test_measure_fixture.py >/dev/null && echo "   measure ok"
                                   python3 export/test_line_status.py >/dev/null && echo "   line_status ok"
                                   python3 export/test_to_mangarr.py >/dev/null && echo "   to_mangarr ok"
                                   python3 tier0/test_dnb.py >/dev/null && echo "   dnb ok"
echo "== 1. work identity ==";     python3 tier0/work_identity.py
echo "== 2. corpus en+fr ==";      python3 tier0/build_corpus.py "$DB"
echo "== 3. corpus de ==";         python3 tier0/build_corpus_de.py "$DB"
echo "== 3b. official titles ==";  python3 tier0/main_titles.py "$DB"
echo "== 3c. main articles ==";     python3 tier0/main_articles.py "$DB"
echo "== 3d. relations ==";         python3 tier0/relations.py "$DB"
echo "== 3e. dnb (German market) =="; python3 tier0/build_dnb.py "$DB" "$ID_CARRY"
echo "== 4. enrichment ==";        python3 tier1/enrich.py "$DB"
                                   # `both` already runs EN Open Library, FR Open Library
                                   # AND BnF. A second `olfr` line re-queried every French
                                   # ISBN that had no record the first time -- 292 needless
                                   # batches against a source we are asked to be polite to,
                                   # for 4 records and 0 claims (rebuild2.log).
                                   python3 tier1/enrich_more.py "$DB" both
echo "== 4b. covers ==";           python3 tier1/covers.py "$DB"
echo "== 5. clean ==";             python3 tier2/clean.py "$DB"
echo "== 5b. corrections ==";      python3 tier2/corrections.py "$DB"
echo "== 6. resolve ==";           python3 tier2/resolve.py "$DB"
echo "== 7. audit ==";             python3 tier2/audit.py "$DB"
if [ "$DB" != "$FINAL" ]; then
  mv -f "$DB" "$FINAL"
  echo "   catalogue -> $FINAL"
fi
echo "== 8. export ==";            python3 export/to_mangarr.py "$FINAL" "$ART.new" "$ID_CARRY"
echo "== 8a. anilist ids ==";      python3 export/resolve_anilist.py "$ART.new"
                                   python3 tier2/corrections.py --anilist "$ART.new"
                                   python3 export/resolve_anilist.py "$ART.new" --display
                                   python3 export/resolve_anilist.py "$ART.new" --covers-only
# Carry curated aliases forward from the previous artifact. Measured: this is
# what takes the export from matching FEWER of the live library's series than
# the artifact it replaces (31/41) to more (38/41).
if [ -n "$PREV" ] && [ -f "$PREV" ]; then
  echo "== 8b. merge curated aliases =="
  python3 export/merge_aliases.py "$ART.new" "$PREV"
fi
echo "== 8c. artifact contract tests =="
python3 export/test_artifact.py "$ART.new" "$FINAL"
# 8d measures the NEW artifact before it replaces the old one, like 8c: a failed
# gate leaves the last good artifact in place.
echo "== 8d. measure gate =="
python3 export/measure_library.py "$ART.new" export/fixtures/library.json --catalogue="$FINAL" | tee build/measure.log
mv -f "$ART.new" "$ART"
echo "   artifact -> $ART"

# Explicit terminal marker. `set -e` aborts on failure, but a caller that pipes
# this to `tail` sees the pipeline's exit code, not the script's -- a stage
# crashed once and the run still reported success. If you do not see the line
# below, the rebuild did NOT complete, whatever the exit code says.
echo
echo "REBUILD COMPLETE -- all stages finished"
