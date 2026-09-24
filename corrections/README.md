# Corrections

Hand-checked facts that the pipeline gets wrong, as data rather than as code.

This is the alternative to a community editing website. What a correction
actually needs is a value, a source, and a guarantee that the next rebuild keeps
it — none of which requires a server. So corrections are five JSON files in
this directory (`volumes.json`, `aliases.json`, `lines.json`, `excluded.json`,
`anilist.json`), and they arrive as **pull requests**.

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

### `aliases.json` — curated removal (`"remove": true`, same file)

For a specific alias the export's own fan-out generated that is actually a
volume or story-arc title, not a name anyone uses for the whole line: My Hero
Academia's alias list includes the bare fragment "My Hero" (a head-split of
the alternate title "My Hero: Ultra Impact"), which is ambiguous and belongs
to no reader's folder name.

```json
[
  {
    "line": "rl_82d4b3ac7f3f",
    "alias": "My Hero",
    "remove": true,
    "source_url": "https://en.wikipedia.org/wiki/List_of_My_Hero_Academia_chapters",
    "reason": "a head-split fragment, too generic to stand alone as a series name",
    "checked": "2026-09-23"
  }
]
```

Required: same as an addition (`line`, `alias`, `source_url`, `checked`), plus
`remove: true`. This is a curated, exact-string removal — **not a rule**. An
earlier attempt automated this (drop any alias whose normalized form equals a
volume title anywhere reachable from the line) and was reverted: of 360
aliases it dropped, only about 30 were actually bad; the rest included every
native-script series name whose ASCII-only ambiguity check made it collapse
to nothing, and a handful of real series and licensed titles (see HANDOFF.md
and `.superpowers/sdd/2026-09-23-followups/review.md`). A removal entry
targets one exact string on one exact line; it never infers a second one.

`export/to_mangarr.py` applies every removal last, after every other alias
source (the auto-generated fan-out and every `aliases.json` addition), and
deletes both the string as written and its `normalize()`-d form — the same
two rows an addition's `variants()` would have inserted for it, since
Mangarr's own lookup queries the normalized form. It raises if a removal
matches nothing: the export regenerates every alias from scratch each run, so
a removal that deletes 0 rows means the string or the line is stale, the same
"fails loudly" contract every other correction has.

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
Optional: `publisher`, `reason`, `origin_line`.

`work` is the OpenTome work id (`series.tome_work_id` in the published artifact,
on every sibling line). `market` is one of `JP EN FR DE KR IT ES BR CN TW HK`.
Every volume needs a `number`; `contains` lists the original-market volume
numbers each volume collects — `[1]` for a straight translation, `[1, 2]` for a
2-in-1 — and is how the cross-market mapping and the status rule see the
edition. Per-volume fields: `isbn13`, `release_date`, `page_count`, `title`,
`cover_url`. An ISBN whose registration group is another market's (a 978-4 on
an English line) is rejected: that is the single most common way a wrong row
gets in.

The line receives exactly the id the pipeline would give the same edition, so
if a source later carries it the two meet instead of duplicating, and the
consumer's series id never changes.

`origin_line` (optional): pins this new line's `orig_series_id` to an exact,
already-cataloged release line, for the case the export's own name-key
matching (`export/to_mangarr.py`'s `origin_line()`) cannot pair the two.
`export/to_mangarr.py` matches a licensed line to its origin-market
counterpart by an EXACT string match on the two lines' names — which fails
when a work has more than one line sharing (work, medium, market): Mushoku
Tensei's JP manga has both the main serial and a "Roxy Gets Serious"
spin-off, and the JP spin-off's own `line_name` claim is not Japanese at
all — it is the French string cross-parsed from the FR Wikipedia table
("Mushoku Tensei : Les Aventures de Roxy"), the same string the FR spin-off
line carries (which is why FR pairs with JP correctly today). A new EN line
named "Mushoku Tensei: Roxy Gets Serious" cannot exact-match that string, so
without a pin it silently falls back to the JP work's MAIN manga line — the
new line then reads 12 of 25 volumes against a still-running series and
exports `stalled` instead of `completed`. Value: an existing release line id
(`rl_...`), which must belong to the SAME `work` and the SAME `medium`, and
sit in an origin market (`JP KR CN TW`) — `tier2/corrections.py` validates
all three and refuses a stale, cross-work, cross-medium or non-origin-market
target the same way a medium/market override refuses a stale line. It is
also used for `composition.ref_line_id` (the cross-market volume mapping)
in place of the same naive "any origin-market line for this work+medium"
query the whole-edition entry already relies on, which has the identical
ambiguity when more than one origin-market line exists.

### `lines.json` — medium override (a narrower entry shape, same file)

For a line the pipeline already has, but has classified as the wrong medium.
The case: Denma is a Korean webtoon (Naver, printed and licensed as a manga),
but every one of its three lines was tagged plain `manga` upstream (no medium
hint applies to it), which made the origin-market picker compare release
dates instead of trusting the medium — and the Japanese edition's earlier
print date won, so the Korean line resolved to its own Japanese translation
as "the origin".

```json
[
  {
    "line": "rl_266a70c679ed",
    "medium": "manhwa",
    "source_url": "https://en.wikipedia.org/wiki/Denma",
    "reason": "a Korean webtoon tagged plain 'manga' upstream; see the other two entries for the same work",
    "checked": "2026-09-23"
  }
]
```

Required: `line`, `medium`, `source_url`, `checked`. This entry has no
`volumes` key at all — that absence is exactly what distinguishes it from a
normal `lines.json` entry above (a normal entry always requires a non-empty
one). Do not add a `work`, `market` or `name` to one of these; it targets an
EXISTING line by its own id, not a natural key.

`line` is an OpenTome release-line id (`series.tome_id` in the published
artifact) — **not** the work id, and not something you compute: copy it from
the pipeline or the published artifact. `medium` is one of the pipeline's own
names (`manga`, `light_novel`, `manhwa`, `manhua`, `novel`, `artbook` —
`tier0/release_lines.py`'s `MEDIUM_HINTS`; not `webtoon`, which tier0 always
canonicalises to `manhwa`, so no line ever carries that value).

**Retag every line of the work that should move together, not just one.** The
origin picker groups a work's lines by `(work, medium)` and only ever compares
candidates inside the same group: retagging only the Korean line would split
it into a group of its own (an origin of one market is trivially itself) and
leave the English line still resolving to the Japanese one. Denma needed all
three of its lines (Japanese, English, Korean) retagged together.

Applied as a plain `UPDATE release_line SET medium = ...` — the line's id
never changes, so a rebuild that re-detects the same medium upstream (nothing
changed there) recomputes the same id and the correction keeps applying
cleanly; if the line is ever renamed or reclassified upstream, the id changes
and this correction fails loudly (`STALE CORRECTION`) instead of silently
attaching to the wrong line.

### `excluded.json` — a whole work that should not be in the catalogue at all

For a work that entered through a source but is not in scope: *The Walking
Dead (comic book)* is a US comic that came in through an English Wikipedia
list-of-volumes page, not manga/light-novel/manhwa/manhua.

```json
[
  {
    "work": "w_5e8c089527e9",
    "source_url": "https://en.wikipedia.org/wiki/The_Walking_Dead_(comic_book)",
    "reason": "a US comic; out of scope",
    "checked": "2026-09-23"
  }
]
```

Required: `work`, `source_url`, `checked`. Optional: `reason`.

`work` is the OpenTome work id (`series.tome_work_id` in the published
artifact, on every sibling line) -- the same identity a medium override keys
its line on, and stable the same way: a rebuild that reprocesses the same
Wikipedia article recomputes the same id, so the exclusion keeps applying.

Applied before every other correction (`tier2/corrections.py`'s
`apply_exclusions`, stage 5b, first): every release line the work owns, their
volumes, compositions, and every claim/override/external_id on any of those
entities or the work itself is deleted outright. Aliases and volumes "go with
the line" -- once the release_line row is gone there is nothing left for a
later stage, including the exporter's own alias fan-out, to read. Be certain:
this is broader than a single line, and removes every market edition of the
work at once. Do not use it on a work that is legitimately in scope just
because one of its lines is bad -- *Arrietty (Comics)*, a real Japanese
Studio Ghibli film comic that also came in through a list-of-volumes page,
stays.

`check()` accepts a `work` that resolves against the published artifact's
`series.tome_work_id` as usual, OR one recorded in the artifact's
`meta.excluded_works` (a JSON array the exporter writes for every exclusion it
applied): once a publish actually removes the work, `series` no longer
carries it, and treating that as a stale correction would fail every future
corrections PR for a correction that is working exactly as intended.

### `lines.json` — market override (a third entry shape, same file)

For a line the pipeline has correctly found but tagged the wrong MARKET.
The case: Denma's line tagged `ja` is not a Japanese print edition at all --
its titles are hangul and its numbering is the Naver webtoon's own
episode-arc list (2010-01 to 2012-01), i.e. the same Korean web serialization
the `ko` line's print volumes collect, not a translation of it.

```json
[
  {
    "line": "rl_266a70c679ed",
    "market": "KR",
    "source_url": "https://en.wikipedia.org/wiki/Denma",
    "reason": "hangul titles, Naver webtoon episode-arc numbering -- the same Korean serialization the ko line collects, not a JP translation of it",
    "checked": "2026-09-23"
  }
]
```

Required: `line`, `market`, `source_url`, `checked`. Like the medium override,
this entry has no `volumes` key -- and, to keep the two override shapes
unambiguous, no `medium` key either: an entry with neither `volumes` nor
`medium` but a `market` is a market override, checked against the pipeline's
own `MARKET_LANG` table (`schema/load.py`). It targets an EXISTING line by its
own id; do not add `work`, `medium` or `name`.

Applied as a plain `UPDATE release_line SET market=?, language=?` (language
follows `MARKET_LANG[market]` automatically) -- the line's id never changes,
so a rebuild that re-detects the same market upstream (nothing changed there)
recomputes the same id and the correction keeps applying cleanly. Retagging a
line's market can change which line the origin picker treats as another
line's counterpart (`export/to_mangarr.py`'s `origin_line`, matched by exact
name within a market) -- read the result, do not assume it.

### `anilist.json` — a hand-checked AniList id for a line

For a line `export/resolve_anilist.py` binds to the wrong AniList entry, where no
safe rule can tell the right one from the wrong one. The case: the English
*Worst* (3 volumes) has two AniList entries titled exactly "Worst" on its search
page — 31741 (33 volumes) and 147044 (4 volumes). The volume rule rejects the
33-volume one (more than 4x the line) and binds the 4-volume one, a different
work. The line's own `orig_series_id` is the Japanese *Worst* line, 33 volumes:
the right entry is 31741, and a person can see that where the resolver cannot.
Mangarr takes the series' poster and synopsis from this id and pins it on every
add, so a wrong one is worth a correction.

```json
[
  {
    "line": "rl_1cc5f2e75d35",
    "anilist_id": 31741,
    "source_url": "https://anilist.co/manga/31741",
    "reason": "orig_series_id is the 33-volume JP 'Worst'; 31741 has volumes: 33, the resolver's 147044 is a different 4-volume work",
    "checked": "2026-09-24"
  }
]
```

Required: `line`, `anilist_id`, `source_url`, `checked`. Optional: `reason`.

`line` is an OpenTome release-line id (`series.tome_id` in the published
artifact), the same key `aliases.json` and the `lines.json` overrides use: it is
stable across rebuilds and names exactly one line, where a series name does not
(many lines share one). `anilist_id` is a JSON integer (not a string); `source_url`
is the AniList entry that was checked. Put the evidence in `reason` — which
catalogue fact the entry matches (volume count of the origin line, author, dates).

Applied in stage 8a, right after `export/resolve_anilist.py`, by
`python3 tier2/corrections.py --anilist build/manga-metadata.sqlite.new`: a plain
`UPDATE series SET anilist_id` on the exported artifact, so it overrides whatever
the resolver picked (the resolver only ever fills NULL ids). A pin whose line is
not in the artifact stops the build (`STALE CORRECTION`), and
`export/test_artifact.py` fails if a pinned line carries any other id.

Clean room: the pin is an id, the same lookup key the resolver writes — no AniList
title, synonym or description enters the artifact through it.

Covers: `build/anilist-covers.json` (the site's fallback cover for a line with no
ISBN-keyed volume cover) is filled last in stage 8a, by
`export/resolve_anilist.py --covers-only` after the pins land, so a pinned id gets
its fallback cover exactly like a resolved one.

## Checking before you open the pull request

Every key is resolved against the **published artifact**, not against a
database you would have to build. Download it, then:

```bash
curl -fsSLO https://github.com/DrAwesome441/mangarr-metadata/releases/download/metadata/manga-metadata.sqlite
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
