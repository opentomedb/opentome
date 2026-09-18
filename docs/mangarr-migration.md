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
