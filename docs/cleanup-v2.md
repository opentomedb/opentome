# Cleanup v2 — what "38 of 41 matched" was hiding (2026-09-03)

The first Mangarr-shaped export was measured by one aggregate: how many of the
live library's 41 series resolved to *some* line. 38 did, better than the
hand-curated artifact's 37, and that was reported as a win.

Measured line by line, the same artifact would have damaged the library on its
first refresh. This document records what was wrong, how it was found, and what
changed. Every number below comes from a script against `build/`, a copy of the
live `readarr.db`, or the cached wikitext.

## The three ways the aggregate lied

**Wrong line, right name.** Six series resolved to a line that carried the
series' name as an alias but was not the series:

| library series (owned) | line picked | why |
|---|---|---|
| Attack on Titan (34) | *Before the Fall* spin-off, 17 vols | main line flagged omnibus, spin-off not |
| That Time I Got Reincarnated as a Slime (29) | *Clayman's Revenge*, 9 vols, 0 dates | same |
| Tokyo Ghoul (14) | the light novel, 3 vols | same, plus no medium in the export |
| The Apothecary Diaries (13) | *Maomao's Notes*, 22 vols, 2 dates | same |
| Solo Leveling (15) | a Korean-ISBN "English" line, 24 vols, 0 dates | ISBN 979-11 labelled English; bigger count won |
| My Hero Academia (42) | *Smash!!*, 5 vols | same as the first |

Coverage passed for none of these. Attack on Titan's owned volumes 18–34 had no
row in the picked line, and volumes 1–17 would have received *Before the Fall*'s
dates and ISBNs through Mangarr's release-date ratchet.

**Phantom volumes.** 121 volumes beyond what the library owns would have been
created as monitored Books, 49 of them past-dated and therefore in the
six-hourly missing-search rotation. Vinland Saga alone contributed 15: Kodansha's
14 two-in-one hardcovers were exported as 29 volumes.

**Zero-data lines.** 745 English and 607 French release lines had no volume with
a date or an ISBN, and Mangarr's ranking put language `en` first — so a phantom
English line outranked a fully dated Japanese one.

## Root causes, each with its measurement

1. **`composition` meant chapters to us and omnibus volumes to Mangarr.** The
   export wrote chapter lists (`[1,2,3,4]`) into `volumes.composition`; the C#
   reads that column as "original volumes this volume contains" and flags the
   series omnibus when any list has more than one entry. 3,356 of 13,001 lines —
   every well-documented main line — were flagged, and Mangarr's tiebreak
   `ThenBy(IsOmnibus)` handed each of them to its own least-documented
   spin-off. Five of the six wrong picks trace to this alone.

2. **A market entry was emitted on parameter *presence*, not content.** The
   Wikipedia template skeleton nearly always carries `LicensedRelDate` /
   `LicensedISBN`; the parser tested whether the parameter existed, so a
   Japanese-only row with `LicensedRelDate = —` produced an English volume with
   nothing in it. Re-parsing the cache: 11,020 of 37,336 English volumes (29.5%)
   and 7,394 of 23,926 French (30.9%) were such phantoms; 99.7% of them had a
   Japanese sibling row *with* data. The French template's own
   `langage_unique=oui` flag, which says outright that no translation exists,
   was ignored on 6,431 rows.

3. **Two-in-one editions were emitted once per original volume.** Wikipedia
   represents an English omnibus by repeating the licensed ISBN and date on
   consecutive Japanese rows. Nothing collapsed them: 187 English lines carried
   645 surplus rows. The pairs are unmistakable — identical ISBN, identical
   date, consecutive numbers — and Nick's 14 hand-verified Vinland Saga dates
   match rows 1, 3, 5 … 27 exactly.

4. **Date templates were stripped before parsing.** `{{start date|2023|2|9}}`,
   `{{dts|…}}`, the one-argument `{{Date|16 septembre 2010}}` and the numeric
   `{{Date|10|03|1998}}` all reached the date parser as empty strings: 5,235
   dates lost outright and 6,276 French dates degraded to year-only. Placeholders
   (`—`, `N/A`, `TBA`) counted as data.

5. **The ISBN registration-group table keyed on one digit.** 979-11 (Korea) and
   979-10 (France) mapped to English, 979-8 (US) to nothing. Solo Leveling's
   Korean originals became an English line. Separately, the template's first
   slot was hard-coded Japanese: 233 "JP" lines held no Japanese ISBN at all.

6. **Work-level titles were attached as aliases to every line of the work.**
   "attack on titan" answered 43 series, "sword art online" 116; 14,691 of
   19,302 alias strings were ambiguous. Combined with (1), the wrong line won.

7. **Volume labels were not canonical.** `01` and `1` from the English and
   French articles of one work were two volumes (576 cases the audit could not
   see, because it compared text); the export dropped one with `INSERT OR
   IGNORE` while still counting it in `volume_count`.

8. **The audit could not fail.** `tier2/audit.py` printed "0 defects" and exited
   0 regardless, and had no check for any class above. The rebuild script
   resumed on the existing database, so a parser fix reparsed zero articles and
   still printed `REBUILD COMPLETE`.

## What changed

| where | change |
|---|---|
| `tier0/isbn.py` (new) | one registration-group table (978-0/1, 979-8 EN; 978-2, 979-10 FR; 978-3 DE; 978-4 JP; 978-89, 979-11 KR; …); JAN barcodes rejected as ISBNs |
| `tier0/wikipedia_volumes.py` | market entry iff a parsed date **or** an ISBN; placeholders are blank; `OneLanguage`/`langage_unique` honoured; original market from the ISBN group; announced rows land in the original market only; date templates expanded; 3-letter and numeric months; invalid days degrade to month; labels canonicalised (`01`→`1`, `1 (18)`→`1`, `Volume 3`→`3`, `9 RE:`→`9`, dashes dropped, `17-18` kept as a range with composition) |
| `tier0/collapse.py` (new) | consecutive rows with one licensed ISBN and one date collapse into one volume with `composition = [original volumes]`; the line renumbers its own units; never applied to Japanese rows |
| `tier0/release_lines.py` | `{{lang\|…}}` and `<sup>` stripped from headings; "Adaptations" is generic |
| `tier0/de_tables.py` | shared ISBN table; duplicate (volume, market) entries from a second edition dropped and counted |
| `schema/load.py` | writes `composition contains='volume'` with `ref_line_id` = the original line; `format='omnibus'`; per-market language map |
| `tier1/enrich*.py` | licence per source from the one table (openBD and Open Library were labelled `open`; 93,492 non-commercial claims sat in `clean_claim`) |
| `tier1/verify.py` | openBD `pubdate` parsed by shape: `2014-5 (第9刷)` was becoming month 59; day precision kept when present |
| `tier2/resolve.py` | on `agreed_coarse` the most precise compatible value is published, not the highest-ranked source's coarse one |
| `tier2/audit.py` | int-equal duplicates, placeholder labels, market vs ISBN group, phantom licensed lines, collapsible runs, month > 12, licence mismatches, markup in line names; **exits non-zero on any defect** |
| `tier0/rebuild_all.sh` | builds into a fresh database and renames it over the old one; runs unit tests first; carries integer ids from the previous artifact; runs the artifact contract test |
| `export/to_mangarr.py` | composition from `contains='volume'` only, chapters in `volume_chapters`; `medium`, `dated_count`, `is_main`, `tome_id`, `tome_work_id` columns; `volume_count` = rows written; `release_date` day-precision only, coarser values in `release_date_raw` + precision; resolved page counts; work aliases on the main line only, sub-lines get their own name and a specific arc title; deterministic alias order; NOCASE indexes |
| `export/merge_aliases.py` | majority vote over ISBNs, same-language target only (re-routed to the sibling line), joins with no shared name token refused and printed |
| `export/test_artifact.py` (new) | the C# contract as assertions; run by the rebuild |
| `export/measure_library.py` (new) | replays Mangarr's lookup and ranking against a copy of `readarr.db`; fails if any owned volume is missing from the picked line |
| `tier0/test_parser.py` (new) | every shape above as a unit test |

Mangarr side (the Mangarr repository, commit `62d7496`): `FindSeriesByTitle`
now ranks English lines only, exact name first, the market's main line, manga
before light novels, then non-omnibus, most dated, most volumes; the optional
columns are read through a guarded query so a schema-v1 artifact still works;
`FindSeriesBySubtitle` resolves franchise-prefixed folder names by their arc
title (3+ words, exact alias equality kept); `ParseDate` accepts `yyyy-MM-dd`
only. Metadata fixtures (homelab run): 95/95 (three were born failing in teardown).

## Measured result

Against the live library copy (`export/measure_library.py`), preview export
from the rebuilt database:

| | first export | v2 |
|---|---:|---:|
| series matched | 38 / 41 | **40 / 41** |
| wrong line (owned volumes missing from the pick) | 6 | **0** |
| volumes beyond owned, past-dated (searchable) | 49 | 34 |

Of the 34: 14 are Marriagetoxin (0 owned, 14 real English volumes — it was
already fully wanted from AniList before), 7 are Sword Art Online Progressive
(see below), and the rest are single newly released volumes.

Catalogue shape: 13,001 → 11,629 lines and 129,900 → 112,048 readable volumes,
which is the phantom removal the cache re-parse predicted (−1,351 lines vs
−1,356 predicted). Vinland Saga English is 15 volumes with `[1,2]…[27,28]`
compositions; Erased is 5; Solo Leveling's English line is the Yen Press one
with 15 dated volumes and its Korean originals are a `KR` line.

## Still true, deliberately

- **Mushoku Tensei: Roxy Gets Serious has no English line** because the English
  Wikipedia article has no section for it. The old artifact had 12 volumes from
  GCD; this one falls back to Mangarr's live sources. The clean-room rule means
  the GCD rows are not carried over.
- **Sword Art Online Progressive** is 14 volumes because the English article
  numbers the *Barcarolle of Froth* and *Scherzo of Deep Night* follow-ups 8–14
  in the same table. Yen Press numbers them from 1. Rows 8–14 have distinct
  ISBNs and dates, so nothing in the data distinguishes them from a continuing
  line; those seven will show as wanted.
- **`series.status` is null.** OpenTome has no source that states whether a
  series is finished; the old artifact drove status for every matched series.
  Mangarr falls back to AniList/MangaUpdates, which is what it did for any
  series the old artifact missed.
- **Same-ISBN rows with different dates** (129 in licensed lines: comics trade
  paperbacks listed per issue, copy-paste errors like Togari 3 = 2007 and 4 =
  2001) are reported as information, not merged. Merging would invent volumes.
- **Cross-article claim collisions** (`docs` D6-04: the en and fr articles'
  opinions of one Japanese volume overwrite each other in `claim`) and the
  **ID-churn** risks in `work_identity` are recorded but not fixed here; neither
  affects the Mangarr artifact, which reads `volume.*`.

---

# v2.1 (2026-09-04) — the pure build, and corrections as data

The v2 artifact still leaned on `merge_aliases.py` to reach 40/41: aliases
carried over from the GCD-derived artifact. That is fine for a private
deployment and impossible for a published one, so the gap had to close upstream.

## Why a clean build missed three series

The corpus is discovered through `embeddedin` on the volume-list template, so
every English article in it is a LIST article. `work_title()` reduces "List of
Frieren chapters" to "Frieren", and that becomes the work's English name — which
is not what anyone's folder is called. A build with no curated aliases missed
exactly the series whose official English title carries a subtitle:

| folder | work title in the catalogue |
|---|---|
| Frieren: Beyond Journey's End | Frieren |
| Mushoku Tensei: Jobless Reincarnation | Mushoku Tensei |

The fourth miss had a different cause. Work-level titles were attached to a
work's MAIN line per market, and a line's own arc title only to sub-lines —
either/or. Re:Zero's five English manga arcs are all sub-lines by name, so
`is_main` fell to whichever had the most volumes, and that one lost its arc
alias: "The Sanctuary and the Witch of Greed" resolved to nothing at all.

## What fixed it

`tier0/main_titles.py` (stage 3b). Two sources, both about the work's MAIN
article, which the list article's lead names as its first italic wikilink:

1. **A piped link carries the official title as its display text** —
   `''[[Frieren|Frieren: Beyond Journey's End]]''`. Free: the wikitext is
   already cached, so this costs no request at all.
2. **The main article's redirects are the names readers type.** One batched
   call per 50 works. Frieren → "Frieren: Beyond Journey's End", "Sousou no
   Frieren", 葬送のフリーレン. Mushoku Tensei → "Mushoku Tensei: Jobless
   Reincarnation". Re:Zero → "Re:ZERO -Starting Life in Another World-", which
   is the live library's folder name exactly.

4,342 main articles resolved, 13,832 title rows added. Export now gives every
line its own name and arc title, and additionally gives the main line the
work's titles; the other-work guard applies to every work-level alias rather
than only to subtitle heads.

## Measured

| | v2 (merged aliases) | v2.1 pure |
|---|---:|---:|
| series matched | 40 / 41 | **40 / 41** |
| coverage failures | 0 | **0** |
| picks differing from the deployed artifact | — | **0 of 41** |
| aliases merged from the GCD-derived artifact | ~1,900 | **0** |

The one miss is *Mushoku Tensei: Roxy Gets Serious*, which has no English line
in the corpus at all — a gap in the source, not in the matching.

## Corrections as data

`corrections/` replaces the idea of a community editing website. `volumes.json`
carries per-field values, applied to the `override` table **and** onto the
volume row — writing only the first produces a correction visible in the
provenance and absent from the artifact, which is the same silent-success
failure this pipeline keeps guarding against. `aliases.json` adds names to one
release line. Every entry needs a `source_url`; a stale target fails the build;
`export/test_artifact.py` asserts each one landed.

## Publishing

`export/publish.sh` writes the manifest Mangarr's updater already polls and
uploads both assets, only under `PUBLISH=1`. It refuses unless
`meta.alias_provenance` is exactly `opentome` — a build that merged aliases
from elsewhere fails the check rather than passing it by omission.

## Two defects found while doing this

- **The French Open Library pass ran twice.** `enrich_more.py both` already
  runs EN, FR and BnF; a second `olfr` line re-queried every French ISBN that
  had no record, for 4 records and 0 claims across 292 batches against a source
  we are asked to be polite to. Removed.
- **Never edit a shell script while it is running.** Bash reads a script by
  byte offset as it executes; the rebuild was mid-run when `rebuild_all.sh` was
  edited. Verify the `REBUILD COMPLETE` marker, never the exit code.

# v2.2 (2026-09-04, later) — arcs, facts about the work, covers, and a wrong main article

Four gaps closed in one rebuild, plus a defect that the work on the fourth exposed.

## Continuous-numbering arcs

Wikipedia numbers *Sword Art Online: Progressive* 1–14. Rows 8–14 are titled
"Progressive: Barcarolle of Froth 1–2", "Scherzo of Deep Night 1–3", "Canon of
the Golden Rule 1–2" — three series Yen Press numbers from 1 each. Exported as
one 14-volume line, Mangarr wanted seven volumes that do not exist under that
name, and the series looked unfinished forever.

`tier0/release_lines.split_arcs`: within one heading, a run of ≥2 consecutive
rows whose row-title stem differs from the line's own stem and whose title
numbering restarts at 1 is its own release line, numbered by its titles. The
rule is deliberately narrow — a single odd row is left alone — and corpus-wide
it fires on 20 lines in 8 articles, every one a genuinely separately-numbered
series (Ascendance of a Bookworm Parts 2–5, W.I.T.C.H. republication parts,
Classmates: Blanc). Row titles are now stored on `volume.title` so the audit
can assert no un-split arc remains. Naming: a stem that *begins* with the work
title is already a full name; one that merely contains it is qualified as
`Work (stem)` — the first cut used "contains" and produced a series called
"Part IX. 100% W.I.T.C.H.". "Livre" and "Book" are number words like "Volume".

## Facts about the work: status, publishers, demographic

`tier0/main_articles.py` (stage 3c) fetches each work's MAIN article once —
cached forever — and reads `{{Infobox animanga/Print}}`: `last` present means
the run ended, `first` alone means ongoing; `publisher` / `publisher_en`;
demographic; magazine. Mangarr's `MapGcdStatus` reads `completed | ongoing`.

A licensed line does not simply inherit the work's status. The infobox says
the *Japanese* run ended; Gintama's English edition stopped at volume 23 of 77
and is not finished, it is stalled. Export rule: a licensed line is `completed`
only if the work ended **and** the line has reached the original run's last
volume, counting the originals an omnibus contains. The contract test asserts
no non-omnibus licensed line is `completed` while behind its same-named
original-market line.

List templates inside infobox fields (`{{ubl|[[Kodansha]]|[[Kodansha USA]]}}`,
`{{Plain list| * … }}`) are split depth-aware and the first entry taken; the
first cut shipped "{{ubl" as the publisher of 80 lines. `{{English manga
publisher(s)}}` is read NA → UK → positional → AUS; One Piece's copy of the
template is malformed (`| NA/UK | [[Viz Media]]`) and the positional pass is
for it.

## Covers keyed by the edition's ISBN

`tier1/covers.py` (stage 4b) reads cover URLs out of the Open Library and
openBD responses that are **already in `.cache/`** — zero requests. A cover
looked up by the edition's ISBN is that edition's cover; a title search
returns *a* cover for *some* edition of *something* with that name, which is
how a volume ends up wearing another volume's face. URLs only, with the
source; the image is never stored. Mangarr (10.0.0.160) seeds each volume's
cover from the artifact and lets its title-search backfills fill only what is
still null.

## The wrong main article

Checking why One Piece had no status exposed a v2.1 defect: stage 3b takes the
list article's *first italic wikilink* as the work's main article, and for 34
of 4,638 works that was the magazine ("Weekly Shōnen Jump"), the generic
"tankōbon" article, "Graphic novel" or a franchise page. Their redirects then
became the work's aliases — One Piece carried 45 names for Shōnen Jump
("Jump Next", "Takuan & Batsu's Daily Demon Diary"), and any search for the
magazine would have matched it. This shipped in the 09-04 (a) artifact.

Fix: every italic link in the lead is tried in order and the first whose
target or display *contains* the work's title wins. Containment is one-way on
purpose — allowing the shorter candidate too made 12 spin-offs resolve to
their parent (Dragon Ball Z → Dragon Ball, five Kaiji sequels → Kaiji), which
is worse than no main article. Italics inside the link display
(`[[Aria (manga)|''Aqua'' and ''Aria'']]`) are accepted. For a list article
with no prose at all (One Piece's volume list is headings and `{{Main}}`
links), the facts stage — never the alias stage — tries the article named
exactly after the work and keeps it only if its infobox names the work back:
the header's `name`, or `volume_list` pointing at the very list article we
came from. Losses accepted: *Moyashimon* (article "Moyasimon") gets no main
article.

Two things the live refresh then showed, fixed in the same session:

- **The last single volume of a 2-in-1 line had no composition.** The collapse
  wrote `contains` only for runs; Erased's English volume 5 (= Japanese 9) and
  Vinland Saga's 15 (= 29) carried nothing, so "reached the last original
  volume" fell one short and both finished series showed *Continuing*. Every
  integer row of a renumbered line now records the original it maps to; the
  `omnibus` format flag stays reserved for rows that contain more than one.
- **Arcs inherited the work's status.** Re:Zero's four finished manga arcs
  became *ongoing* because the work's main article is the ongoing light novel.
  Only a line named after the work carries the work's status now; an arc or
  spin-off line exports NULL and Mangarr's own fallback (AniList knows the arc)
  decides, as before.

## An edition no source carries

`corrections/lines.json` adds a whole release line from a hand-checked volume
list, for the case the pipeline cannot solve: the English *Mushoku Tensei:
Roxy Gets Serious* (Seven Seas, 12 volumes) is on no Wikipedia article, Open
Library has never seen its ISBNs, and the publisher's site refuses robots. The
line receives the id the loader would have given the same edition, every value
is written as claim + override + row, `contains` maps each volume to the
original-market volumes it collects, and an ISBN whose registration group is
another market's is rejected. The file is empty until a person reads the
twelve ISBN/date pairs off the publisher's page.

## Measured

| | v2.1 (deployed 09-04 a) | v2.2 |
|---|---:|---:|
| release lines / volumes | 11,629 / 112,048 | 11,657 / 112,082 |
| lines with a status (lines named after their work only) | 0 | 7,703 (4,507 completed, 3,196 ongoing) |
| lines with a publisher | 0 | 8,620 |
| volumes with an ISBN-keyed cover URL | 0 | 12,366 |
| works with main-article facts | — | 4,163 |
| library: matched / coverage failures | 40 / 41, 0 | **40 / 41, 0** |
| SAO Progressive volumes | 14 | **7** (+3 arc lines) |
| live ids changed | — | **0** (28 new arc lines; 0 renamed) |

The one library miss remains *Roxy Gets Serious*, waiting on `lines.json`.
