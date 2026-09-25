# Migrating OpenTome into Mangarr

## Why this is the right home, not a consolation prize

The licensing problem does not get worked around — **it disappears**. At 100% usable for a
free release every source is fine, and openBD's purpose limitation (*"book promotion and
introduction"*) is **actively satisfied** by a tool that helps people find and acquire
manga. Open Library's non-commercial requirement is met outright. The EU database-right
question shrinks to near-irrelevance for a free self-hosted tool.

It also supplies the integrator the standalone product never found. Mangarr already needs
exactly this data and currently ships a 421-volume artifact built from a hand-curated
16-series list.

| | Mangarr today | With OpenTome |
|---|---:|---:|
| Volumes | 421 | **130,476** (+2,385 specials) |
| Release lines | ~16 | **13,001** |
| Title aliases | 3 hand-written bridges | **35,184** |
| Markets | EN (+JP) | JP, EN, **FR**, DE |
| Upstream | manual Cloudflare-gated GCD download | fully automated, cache-backed |

## The mapping is near-direct

Mangarr's `series` table is already **one row per release line** — the same model OpenTome
converged on independently:

```
opentome.release_line  ->  series
opentome.volume        ->  volumes
opentome.work_title    ->  series_alias
opentome.composition   ->  volumes.composition
market                 ->  series.language
```

`language` already exists per series row, so **French and German need no schema change**.

## Two constraints come from the C#, not from SQLite

**`GcdSeries.GcdSeriesId` is `int`.** Series ids must therefore be stable integers. They
are hash-derived and recorded in an `id_map` table carried across rebuilds, so a re-export
reuses existing ids and only new lines get new ones. **Verified: 13,001 of 13,001 ids
identical after re-export.** Sequential numbering was rejected outright — it renumbers
everything after an insertion, which the ID contract forbids and which Mangarr's own
blueprint warns about (*"do not big-bang re-key existing series"*).

**`GcdVolume.VolumeNumber` is `int`.** Fractional (`7.5`) and label volumes (`SP`, `Ex3`,
`Side Story`, `Extra`) cannot be represented — 2,385 of them. They are **not dropped
silently**: they go to a `volumes_special` table today's C# ignores, a later version can
promote, and the count is written to `meta`. Changing that column to `TEXT` recovers them.

## A bug this caught

The first export produced `series_alias` rows from `work_title`, which holds **raw article
names** — *"Liste des chapitres de L'Attaque des Titans"*. That matches no folder anyone
has, and the French lookup returned **zero** results. Aliases now carry the cleaned work
title alongside the raw form. After the fix, `L'Attaque des Titans` resolves and returns 34
French volumes with dates and ISBNs.

Testing against the C#'s *actual* queries found this; a row-count check would not have.

## What the current export discards

Mangarr's schema has no column for `release_date_precision`, `release_date_type`,
confidence, provenance, or medium. **That is the most valuable part of OpenTome** — the
confidence layer is precisely what prevents the silent-wrong-match class of bug Mangarr has
historically suffered. The drop-in export is a first step to prove the pipeline end to end
with zero C# changes; extending the schema to carry precision and confidence is where the
real gain is.

## Known Mangarr defects this fixes

- `GOOGLE_BOOKS_API_KEY` unset and keyless quota now **zero** — the per-volume backfill is
  silently dead. OpenTome supplies dates directly.
- `SanitizeBackfillPages` keeps only 80–400pp, **rejecting German omnibus editions** at
  450–472pp.
- `overrides.json` manual pinning — 63 hand-entered Fairy Tail dates that never converged.

## Delivery needs no new plumbing

Mangarr already has the mechanism: a 24-hour `MetadataUpdateService` that fetches a
version manifest, downloads, verifies sha256, confirms the `meta.gcd_dump` key and reloads.
The export writes `gcd_dump = opentome-YYYY-MM-DD`. Three known defects in that updater
should be fixed first — the ordinal string version compare, `FindArtifact()` picking the
alphabetically-first `*.sqlite`, and the dead baked-in artifact path.

## Attribution ships in the artifact

BnF's Etalab licence and openBD's terms both require retained attribution. The `meta` table
carries a source list and a licence note. **Cover art is deliberately not included** — see
`docs/legal-position.md`; the artifact stores facts, and covers are fetched at display time
per user.

## Edition columns (2026-09-24, Preferred Edition v0)

Additive; a consumer reading named columns sees nothing change.

| Column / key | Meaning |
|---|---|
| `series.country` | the release line's market code verbatim (measured: `CN DE EN ES FR IT JP KR TW`) — never NULL |
| `series.local_name` | the line's title in its own language: a DE line (main or not) takes the DNB series title when it has one, else — main line only — the line's official title in its own language (FR/JP/…, cleaned of list-article prefixes: "Liste des … des X" / "Chronologie des … des X" → "Les X", "… du X" → "Le X"; disambiguators stripped); NULL for EN lines, for a non-main line with no DNB name, and — today, for lack of source data rather than by rule — for KR/CN/TW/IT/ES |
| `series_alias.language`, `series_alias.kind` | the alias's language (NULL for a line's own name and corrections) and kind (`line`, `official`, `alias`, `abbreviation`, `romanized`, `correction`); first insertion wins, the alias ORDER is unchanged |
| meta `markets` | JSON `{language: line count}` keyed by `series.language` codes (`ja`, `zh-TW`, …, not `country`), sorted keys |
| `id_redirect` | (pre-existing, `dnb-ingest`) a retired release-line id → the line in this artifact that replaced it (`entity='release_line'`); the edition picker resolves a retired id through it instead of a dedicated table: `SELECT new_tome_id FROM id_redirect WHERE old_tome_id=@t AND entity='release_line'`. A carried id with no successor (an excluded work; 55 today, see HANDOFF.md) has no row at all — a consumer must treat "no row" as gone, not as an error |

One work can have the same spelling in more than one of its titles (e.g. an English and a
French claim that read identically); the alias row they collapse to (first-insert-wins:
line name, then work titles in stored order, then corrections) keeps whichever language
was inserted first, alphabetically among ties — so a consumer must treat
`series_alias.language` as a hint, never an exclusion filter.

Measured on branch `preferred-edition-v0` (build/opentome.db; **not published**): FR
official titles on 1,254 of 1,255 FR main lines; all 1,459 DE lines carry a local name
(1,424 direct from a DNB `line_name` claim — main and non-main alike — plus 35 more on main
lines via the de official-title fallback), of which 1,080 differ from the work's primary
title; JP official titles are native script (3,749 of 5,188 main JP lines). `local_name` is
NULL today for every KR/CN/TW/IT/ES line (measured ko 0/66, zh 0/4, zh-TW 0/3, it 0/1, es
0/1) — no official-title claims exist yet for those languages, not a rule exclusion. No
`series_alias.kind='romanized'` rows exist yet — romaji arrives as `en`/`alias`. meta
`markets`: `{"de": 1459, "en": 3030, "es": 1, "fr": 1493, "it": 1, "ja": 6978, "ko": 66,
"zh": 4, "zh-TW": 3}`.
