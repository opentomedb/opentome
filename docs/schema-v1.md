# Schema v1 — design notes

Every table traces to an empirical finding in `step0-findings.md`,
`smoke-test-library16.md` or `tier1-crossverify.md`. Nothing here is speculative.

## The four decisions that matter

### 1. IDs are a public contract
Opaque, prefixed (`w_`, `rl_`, `v_`, `ch_`), never reused, never re-keyed. Merges write
`id_redirect`; retired ids resolve forever and never 404. **This is the commercial moat** —
IMDb and TheTVDB are defensible because of their identifiers, not their bytes. Once
Mangarr or Kavita stores one, churn breaks every consumer simultaneously.

Ids are *derived* from a stable natural key by hash so loads are idempotent, but they are
stored opaquely and never parsed. Verified: re-running the loader against a populated DB
produced 116 volumes before and after.

### 2. `release_line` is the unit of volume numbering
Independence is **forced by the data**, not chosen: Re:Zero *Chapter 3* vol 1 and
*Chapter 4* vol 1 are both volume 1. Merging lines corrupts numbering — the only large
errors in cross-verification were flattened franchises (SAO "v6" was actually
*Progressive 3 (light novel)*).

`medium` is open-ended TEXT, not an enum. Solo Leveling in the reference library is
already manhwa, so a fixed manga/light-novel pair is under-general on day one. Consumer
preference ("I only want manga") shapes **queries**, never storage.

### 3. Dates carry three qualifiers
`release_date` + `_precision` + `_type`. Finding: 49 of 50 cross-source disagreements
were exact multiples of seven days, 45 in the same direction — two sources answering
different questions (publication vs retail on-sale), not one being wrong. A bare date
silently mixes them.

### 4. `claim` / `resolution` split — provenance per field
`claim` stores **every** source's assertion; `resolution` records which won, with a
confidence and a basis. Disagreement is preserved rather than discarded, because the
disagreement *is* the confidence signal.

Commercially this is the load-bearing table. `licence` per claim drives the
`clean_claim` view — the subset filtered to unencumbered provenance. Google Books and
MangaDex forbid database-building outright, so anything sourced from them can never
enter a paid product. **Per-field provenance is cheap now and unrecoverable later.**

## One primitive, three problems

`composition` expresses all of these with one relation:

- an omnibus contains volumes `[1,2,3]`
- a French volume contains Japanese volumes `[1,2]`
- any volume contains chapters `[1..7]`

## Verified end-to-end

Loaded Chainsaw Man (en) and Attack on Titan (fr) — 4 release lines, 116 volumes,
228 claims:

**Retracted:** the *Commercially clean claims* row in this table was later found to be
circular (the `licence` labels it counted were assigned without reading the sources'
terms) — see `docs/legal-position.md`; the verified position is in `LICENSE-DATA.md`.

| Check | Result |
|---|---|
| Consumer filter (`medium=manga`, by market) | ✅ |
| Cross-market join JP↔FR, day precision both sides | ✅ vol 1 JP `2010-03-17` → FR `2013-06-26` |
| Chapter composition | ✅ `[1–7]`, `[8–16]`, `[17–25]` contiguous |
| Idempotent reload | ✅ 116 → 116 |
| **Commercially clean claims** | **✅ 100%** (136 `facts_only`, 92 `open`, 0 restricted) |

*(Written before the retraction above — kept as the record of the smoke test's reasoning.)* That last row was a direct consequence of dropping Google Books: with Wikipedia used as a
**citation index** rather than a data source — every date attributed to the publisher URL
the article itself cites — 40% of claims resolve to `publisher` provenance and *nothing*
is restricted.

## Language support is data, not code

`DIALECTS` in `tier0/wikipedia_volumes.py` maps per-wiki template and field names:

| | en | fr |
|---|---|---|
| template | `{{Graphic novel list}}` | `{{TomeBD}}` |
| volume | `VolumeNumber` | `volume` |
| JP date / ISBN | `RelDate` / `ISBN` | `sortie_1` / `isbn_1` |
| local date / ISBN | `LicensedRelDate` / `LicensedISBN` | `sortie_2` / `isbn_2` |
| chapters | `ChapterListCol*` | `chapitre` |

German is **not** a dialect — de.wikipedia uses wikitables (9 tables, 138 rows,
`{{DatumZelle}}`), so it needs a separate table extractor.

## Correction to an earlier assumption

The plan predicted French would diverge structurally from Japanese volume splits. For
Attack on Titan it does **not** — French tracks Japanese 1:1. The divergent market for
this title is **German**, whose Carlsen omnibus editions run 450–472pp against ~190pp
elsewhere. Cross-market divergence is real, but it is per-title and per-market, not a
property of French.

## 2026-09-21 — volume titles, per-line status, orig_series_id

`volumes.title` is the Wikipedia row title (number-only titles, e.g. "Volume 3", are
dropped rather than exported as if they said something).

`series.status` is now per LINE, not per work, for a licensed market: `completed` |
`ongoing` | `stalled` | `NULL`. The rule lives in `export/line_status.py` — a line is
`stalled` when it is at least two volumes behind its origin-market counterpart and
nothing has shipped in 24 months while the origin kept going. A line that is NOT the
work's main line (an arc, a side story) and has reached its origin's top volume, with
neither market shipping for 24 months, is `completed` even while the work itself is
`ongoing` — a finished arc of a running series. A main line in the same position keeps
the work's status (a hiatus is still `ongoing`). Origin-market and omnibus lines take the
work's own status as before; `release_line.status` in the pipeline DB is not consulted
for a licensed line with a resolved origin (it is the column a future corrections-only
`cancelled` would use).

`series.orig_series_id` is the origin counterpart line's id for a licensed line — the
same-work, same-medium line the status rule and a cross-market join compare against.

A consumer that maps `status` to its own enum must treat `stalled` as neither
`completed` nor `ongoing`. Mangarr's `MapGcdStatus` does not recognize it yet and falls
back to AniList, which is safe but loses the signal.

## 2026-09-24 — display_anilist_id / display_anilist_via (display only)

Two additive `series` columns (Mangarr selects named columns, so an older Mangarr never
sees them):

- `display_anilist_id INTEGER` — an AniList id to take a **cover / synopsis** from, for an
  English line the resolver left with `anilist_id` NULL. It is **never a binding**: set only
  where `anilist_id IS NULL`, never copied into `anilist_id`, never a source of aliases. A
  consumer must not present it as the line's AniList id (the site links only `anilist_id`).
- `display_anilist_via TEXT` — how it was found:
  - `parent`: the line's name cut at its first ` (`, `: `, ` - ` or ` / ` key-equals the name
    of a **bound** English line of the **same work** (`tome_work_id`, any medium) — that
    line's `anilist_id` (`Re:Zero (Truth of Zero)` → the bound `Re:Zero`). Never across works,
    never when the same-work bound lines of that name carry different ids.
  - `medium`: a `novel` / `light_novel` line whose own (`format: NOVEL`) AniList page has no
    title-equal candidate at all, but whose manga-family page for the same name gives the
    resolver's `pick()` a candidate — AniList lists the adaptation, not the novel (Otherside
    Picnic, Bungo Stray Dogs).

Both columns are NULL or both set. `export/test_artifact.py` asserts: display ids only on
English lines with a NULL `anilist_id`; `via` in {`parent`, `medium`}; `medium` only on novel
mediums; every `parent` id is the unambiguous `anilist_id` of its same-work parent line.
Written by `export/resolve_anilist.py --display` in stage 8a, after `corrections/anilist.json`'s
pins and before `--covers-only`, which fills `build/anilist-covers.json` for display ids too.
