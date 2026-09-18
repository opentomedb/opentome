# Corrections

Hand-checked facts that the pipeline gets wrong, as data rather than as code.

This is the alternative to a community editing website. What a correction
actually needs is a value, a source, and a guarantee that the next rebuild keeps
it — none of which requires a server. So corrections are three JSON files in
this directory, and they arrive as **pull requests**.

Every correction is applied by `tier2/corrections.py`, which runs as a stage of
`tier0/rebuild_all.sh`, and every one is asserted by `export/test_artifact.py`,
so a correction that stops landing fails the build instead of disappearing
quietly.

## The rule

**A correction records what a source says, not what someone believes.** Each
entry carries `source_url` — the publisher page, library record or other primary
source that was actually checked — and `checked`, the date it was checked. A
correction with no source is a guess with better formatting, and guesses are
what the confidence layer exists to keep out of the catalogue.

Corrections are for facts the sources get wrong or do not carry. They are not a
place to work around a parser bug: if the pipeline mis-reads a source, fix the
parser and let every series benefit.

## Files

### `volumes.json` — per-field value corrections

```json
[
  {
    "volume": "v_5c7be0913a2d",
    "field": "release_date",
    "value": "2013-10-13",
    "precision": "day",
    "source_url": "https://kodansha.us/volume/vinland-saga-1/",
    "reason": "publisher page; Wikipedia had the reprint date",
    "checked": "2026-09-04"
  }
]
```

Required: `volume`, `field`, `value`, `source_url`, `checked`. Optional:
`precision` (for a date), `reason`.

`volume` is an OpenTome volume id (`v_…`, `volumes.tome_id` in the published
artifact) or an ISBN-13, which is resolved to the volume that carries it — key
on the id when the same ISBN is on more than one volume. Fields: `release_date`
(with optional `precision`), `isbn13`, `page_count`, `title`, `cover_url` (a
picked cover: stored as a `correction` claim, which the exporter prefers over
every ISBN lookup).

Each correction is written to the `override` table — where `tier2/resolve.py`
already ranks it above every source, so the confidence layer reports it as
`manual_override` — **and** onto the `volume` row, which is what the export
reads. Writing only the first would produce a correction that is visible in the
provenance and absent from the artifact.

### `aliases.json` — extra names for a release line

```json
[
  {
    "line": "rl_13affd6972b3",
    "alias": "Vinland Saga Deluxe",
    "source_url": "https://kodansha.us/series/vinland-saga/",
    "reason": "the name the publisher prints on the spine",
    "checked": "2026-09-04"
  }
]
```

Required: `line`, `alias`, `source_url`, `checked`.

`line` is an OpenTome release-line id (`series.tome_id` in the published
artifact). Aliases are added to that line only, never fanned out.

Folder-name bridges belong here — a library whose folder is misspelled
("Jujustu Kaisen") is a fact about that library, and recording it as a
correction keeps it out of the catalogue's own naming.

### `lines.json` — a whole edition the sources do not carry

For an edition that is on no source at all: the English *Mushoku Tensei: Roxy
Gets Serious* (Seven Seas, 12 volumes) is absent from the English Wikipedia
list, Open Library has never seen its ISBNs, and the publisher's site refuses
robots — so the pipeline cannot know it exists, and a person reading the
publisher's page can.

```json
[
  {
    "work": "w_179929c7bc15",
    "market": "EN",
    "medium": "manga",
    "name": "Mushoku Tensei: Roxy Gets Serious",
    "publisher": "Seven Seas Entertainment",
    "volumes": [
      {"number": "1", "isbn13": "978-1-64505-XXX-X", "release_date": "2020-10-06", "contains": [1]},
      {"number": "2", "isbn13": "978-1-64505-XXX-X", "release_date": "2021-02-09", "contains": [2]}
    ],
    "source_url": "https://sevenseasentertainment.com/series/mushoku-tensei-roxy-gets-serious/",
    "reason": "Seven Seas edition; not on the en list article, publisher blocks robots",
    "checked": "2026-09-04"
  }
]
```

Required: `work`, `market`, `medium`, `name`, `volumes`, `source_url`, `checked`.
Optional: `publisher`, `reason`.

`work` is the OpenTome work id (`series.tome_work_id` in the published artifact,
on every sibling line). `market` is one of `JP EN FR DE KR IT ES BR CN TW HK`.
Every volume needs a `number`; `contains` lists the original-market volume
numbers each volume collects — `[1]` for a straight translation, `[1, 2]` for a
2-in-1 — and is how the cross-market mapping and the status rule see the
edition. Per-volume fields: `isbn13`, `release_date`, `page_count`, `title`. An
ISBN whose registration group is another market's (a 978-4 on an English line)
is rejected: that is the single most common way a wrong row gets in.

The line receives exactly the id the pipeline would give the same edition, so
if a source later carries it the two meet instead of duplicating, and the
consumer's series id never changes.

## Checking before you open the pull request

Every key is resolved against the **published artifact**, not against a
database you would have to build. Download it, then:

```bash
curl -fsSLO https://github.com/itsnickspiro/mangarr-metadata/releases/download/metadata/manga-metadata.sqlite
python3 tier2/corrections.py --check corrections/ --artifact manga-metadata.sqlite
```

It exits 0 and prints `corrections check ok` when every file is well-formed
JSON, every entry has its required keys, every `field` and `market` is one the
pipeline accepts, and every id or ISBN resolves. Otherwise it names the file,
the index and the reason — `STALE CORRECTION` for a key that is not in the
artifact — and exits 1. It never writes anything.

Opening a pull request that touches these files runs the same check
automatically (`.github/workflows/corrections-check.yml`), plus the parser's
unit tests. A merged correction lands in the next build.

## Finding an id

Against the published artifact:

```bash
sqlite3 manga-metadata.sqlite "SELECT tome_id, tome_work_id, name, language, medium
  FROM series WHERE name LIKE 'Vinland%'"

sqlite3 manga-metadata.sqlite "SELECT v.tome_id, v.volume_number, v.isbn13, v.release_date
  FROM volumes v JOIN series s ON s.gcd_series_id = v.gcd_series_id
  WHERE s.tome_id = 'rl_13affd6972b3' ORDER BY v.volume_number"
```

Ids are a public contract — never reused, never re-keyed — so a correction keyed
on one keeps applying across rebuilds. An id that no longer exists is reported
by the check and by the loader as a stale correction rather than ignored.
