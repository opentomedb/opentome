# DNB as the German primary source — design (2026-09-24)

Status: APPROVED by Nick 2026-09-24 ("go with your recommendations"). Follows `docs/german-market.md` (German
Wikipedia is not a viable source; DNB, enumerated by publisher, is the German strategy). Evidence: the 2026-09-24
spike (spike code + `measured.json` in `~/Claude/scratch/mangarr-session/dnb/`, ~137 cached SRU responses in `.cache/`).
Numbers marked [M] were measured in the spike, [E] estimated.

## Decisions (Nick, 2026-09-24)
1. **Unlinked German lines are held back from export** (no DNB-only works in v1). Only lines linked to an existing
   OpenTome work at high/medium confidence ship; low/ambiguous links go to a review file, not the artifact.
2. **New `release_date_type` value `projected`** for MARC `263` (planned month YYYYMM on announcement records; matched
   the real month 25/26 [M]). A projected date never outranks a published/on_sale date for the same volume.
3. **Print only** — e-book records (`bbg=O*`, 8,370 [M]) are out of v1.
4. **Korean/Chinese-origin titles** (`spo=kor` 1,664 / `spo=chi` 292 [M]) are a follow-up round (same pipeline).

## Licence and exclusions
DNB bibliographic data is **CC0 1.0** (https://www.dnb.de/businessmodel.html, 17.12.2024). **Covers are NOT CC0**
(dbv/VG Bild-Kunst agreement; reuse via VLB) — store no cover URL. Also exclude `856` blurb links marked `X:MVB` and
table-of-contents PDFs. Every DNB claim: `source='dnb'`, `licence='cc0'`, `source_url=https://d-nb.info/<IDN>`.

## Access
SRU `https://services.dnb.de/sru/dnb?version=1.1&operation=searchRetrieve&query=<CQL>&recordSchema=MARC21-xml&maximumRecords=100&startRecord=N`
(100/response, 99,000/result set). Indexes: `spo` (041$h original language), `sgt` (741.5 = comics), `bbg`
(Ac parent / Af volume-in-set / Aa standalone / O* e-book), `vlg`, `jhr`, `idn` (OR-batch ~30), `num` (ISBN).
Politeness: serial, **≥3 s between requests across processes**, honour `Retry-After` on 429/503 (a 429 was hit after
~46 requests at ~1.7 s [M]; DNB documents no limit), descriptive User-Agent, disk cache with the repo's
`sha256(url)[:32].xml` convention (`tier1/enrich_more._fetch_xml`); current/future-year slices get an opt-in freshness
window so refreshes can pick up new announcements. First run ≈340 requests ≈22 min [E]; reruns zero network.

## Enumeration (three channels, each sliced by `jhr` for stable paging)
1. `spo=jpn and bbg=A*` (print, Japanese original; 22,101 print records incl. 741.5 [M]).
2. Manga-imprint phrases `and bbg=A* not spo=jpn` (TOKYOPOP 1,480 / altraverse 656 / Egmont Manga 257 / Carlsen Manga
   104 / Panini Manga 21 / Planet Manga 4 [M]) — classify with `041` and Thema `926` codes; keep only Japanese-origin
   (others wait for the KR/CN round). **The Kazé family is NOT in the list (measured 2026-11-07).** DNB holds Pegasus Manga 284 / KAZÉ 77 / Crunchyroll Manga 469 / VIZ Media Switzerland 38 records `not spo=jpn`; adding the four names re-clusters the German market: +862 records, of which most are second catalogue copies of books channel 1 already has under other set records (604 twin records merged instead of 382), 15 new same-name line pairs (Shy, Orient, Dandadan, ...), 340 carried volumes moved or retired. A later round can take it with that measurement in hand; the volumes channel 1 loses to DNB's re-cataloguing come back through the carried-ISBN recovery below.
3. Parents fetched by `idn` from each volume's `773$w`.
Manga signals: `041$h jpn`, DDC `741.5`, `655` "Comic", `653` VLB-WN 1182/2182 "Manga, Manhwa", Thema `XAM*`.
LN signals: Thema `FYS`/`YFZS` ("Ranobe"), "Light Novel" in title/keywords (publishers also stamp XAM on LNs —
XAM ≠ manga); page count (LN median 289 vs manga 186 [M]) is supporting only. LN medium = light_novel.

## Parsing and volumes
MARC21-xml via `xml.etree.ElementTree`; strip non-sort markers `\x98…\x9c`. Volume number: `245$n`, else `490`/`830 $v`,
else a trailing number in `245$a` (Egmont "Car Crush 02"); DNB vs Wikipedia volume number agreed 368/369 [M].
ISBN `020$a` (935/1,000 [M]); merge twin records by ISBN first (pre-publication + deposit copy, or special edition
sharing the ISBN; twins agree on year 22/22 [M]); a box-set ISBN shared by several volumes is dropped from those
volumes. Page count `300$a` ("N Seiten", "N S.", "circa N Seiten", "[N] S.", "N, [N] S.", "N ungezählte Seiten").
Bundles/box sets/samplers ("Bundle", "Doppelband", "Sammelschuber", "Komplettpack", "im Schuber") are not volumes in v1.
Legal-deposit holes exist (Egmont 2015–2019 print volumes, TOKYOPOP 2005–2009 combined "1 - 3" records [M]) — no
completeness claim.

## Dates
- `release_date` = `008[7:11]` year, `release_date_precision='year'`, `release_date_type='published'` (late-December
  releases can carry the next year — Wikipedia day dates win resolution). `264$c` is unreliable except a month on a
  few recent records (9/930 [M]) — may be used as month precision when it parses as "Mai 2025".
- `263` planned month → `release_date_type='projected'`, precision 'month' (new type, decision 2).
- The A-listing week (`015`) is NOT a release date (median lag 120 days [M]); if kept, a separate claim type.
- Announcement-only records with an `008` year after the current year never produce a dated exported volume
  (2027–2030 placeholders, likely cancellations).

## Lines
Clustering [M: 32/34 overlap lines]: key on parent IDN; else folded series + publisher; else folded bare title +
publisher; fold series/bare-title keys into the parent line whose folded `245$a` + publisher match when neither side
has an edition marker (`250` "Deluxe Edition", "Massiv", "Mehrfachband", "Perfect Edition", "Collector's Edition",
"limitierte Ausgabe" → separate lines). Keys from source data only: `dnb:<parent IDN>` / `dnb:<lowest member IDN>`;
a changed key keeps the published id when the line still holds a strict majority of that line's published ISBNs (`build_dnb.adopt_published_ids`, 2026-11-07 -- the JP round's "continuity first", docs/id-scheme.md), else `id_redirect`; never a silent re-key (ids are a public contract).

**Carried-ISBN recovery (2026-11-07, `dnb_enumerate.recover_carried`).** A published German volume whose ISBN no record of the run holds is fetched by `num=<isbn> and bbg=A*`, once (a cached result set, never refreshed; at most `RECOVER_MAX` = 60 new lookups a run, lowest ISBNs first, the rest next run; a DNB failure skips the lookup and never fails or degrades the build), and its set record when that is new. The record is then judged like every other (`select`, `origin_in_scope`); one DNB deleted returns nothing and the volume retires as before. Cause: the 11-07 refresh showed DNB re-cataloguing the Pegasus Manga records of *Das Biest des Königs* (Bd. 2–16, 18) without `041$h`, so channel 1 lost 17 published volumes while `num=` still returned them -- the kind of source index churn the retired-volume cap is there to catch, and the catalogue's own published state is the natural list of what to ask for again.

**Continuity (2026-11-07, `adopt_published_ids`).** The 11-07 DNB refresh re-keyed nine published lines and their 37 volumes in one build (Mission: Yozakura Family, Heart Gear, Dr. Slump Massiv, ...): DNB had catalogued a set record for each series, so a line keyed `dnb:<lowest member IDN>` folded into `dnb:<parent IDN>`, the id followed the key, and every volume id (`v_` = line id + number) moved with it -- 37 redirects, and the German retired-volume cap tripped. The line is the same line. Now a built line whose own-key id was never published takes the published German line (not a Wikipedia line -- those merge by `assign_roles`; not a KR/CN-born one -- `carried_isbns` leaves `meta.krcn_ids` out) that no built line keeps by its own key, when it holds a STRICT majority of that line's published ISBNs; several lines for one id: the most ISBNs held, then the lowest own key; one line for several: the most held, then the lowest id. Everything else stays 7b's (a redirect by majority, a retirement, a loud orphan). Measured on the 11-07 refresh: 9 lines keep their ids, 0 German volumes move.

**A new edition line named like a published one (2026-11-07, `name_new_editions`).** A set record with a 250 edition marker is its own line (above), and DNB titles it like the ordinary edition: the 2026 Loewe hardcover of *Mein Buchcafé in einer anderen Welt* (`250 Perfect edition`, 2 Bände of ~400 pages) is titled exactly like the five-volume paperback set. One work never has two lines of one language and medium with the same name (docs/round-c.md; `export/test_artifact.py` `name_collisions`, which passes the 144 German pairs the carry already had and fails a new one). A NEW edition line (its id never published) whose name repeats another exported line's of its work and medium is named `<title> – <edition>` (`EDITION_LABEL`: Deluxe Edition, Massiv, Mehrfachband, Perfect Edition, Collector's Edition, Limitierte Ausgabe, Kanzenban), the section lines' shape; a title that already names its edition (Dr. Slump Massiv) and every published line keep their names.
Merge with the existing ~35 Wikipedia DE lines: majority-ISBN match reuses the `rl_` id; volumes (`v_` from line +
number) merge and gain `dnb` claims; one Wikipedia line ↔ several DNB lines: most-ISBN keeps the id, others are new
siblings; several ↔ one: keep the larger, redirect the rest. The 35 current DE line ids must survive.

**Sets filed in sections (2026-11-07, `build_dnb.split_sections(home=True)`).** DNB keeps a series published in arcs
or seasons under one set record and numbers each arc from 1 (`245 $n '[...]' $p 'Gold und Silber' $n '1'`). Read as
one line, every number after the first arc's was a duplicate. A section whose numbers repeat another's is now its own
line, keyed `dnb:<set IDN>#<folded section>` and named `<set title> – <section>`, with the set's title kept as a title
of the line (the linker needs it). The section catalogued first -- the one holding the set's lowest-IDN numbered
volume -- stays the set itself under `dnb:<set IDN>` and the set's name, because the published line holds exactly
that section's volumes (the first volume seen per number): Pokémon - die großen Abenteuer and Gorgeous Carat keep
every line and volume id, no redirect. Measured on the cached records: 5 sets, 8 new section lines, 19 volumes that
were dropped as duplicates; 3 of the 5 sets are unlinked and stay so. The KR/CN round (`home=False`, 2026-11-06) moves
every section, as published in `opentome-2026-11-06`.

## Linking to works (no ISBNs)
Title keys (fold case, macrons, ou/oo/uu, wo→o, the non-sort markers, trailing volume numbers on the DNB side only;
stripped + unstripped) from `240`/`245$b`/`246`, `245$a`, `490`/`830` WITH `$v` only (a `490` without `$v` is an imprint
collection name: "Action", "Romance") vs OpenTome `primary_title`, official `work_title`, `ja_romaji`/`ja_kanji` claims,
`line_name` claims and the `de` official title; aliases only as a low tier (the alias table holds character/place
names). Author match: `100`/`700` token sets (name order inverted; drop `trl`) vs author/illustrator claims. Add an
author + title-prefix tier. Tiers: high (official title + author), medium (official title), low (alias only) —
export high + medium; low/ambiguous → `build/dnb-review.tsv`. Spike: ground truth 32/34 correct, 0 wrong; labelled
sample 43/45 correct (high 30/31, medium 13/14); known error shapes: spin-offs attaching to their parent ("Episode of
Thriller Bark" → One Piece), generic one-shot titles.

## Gates
Contract (`export/test_artifact.py`): every `dnb` claim is `cc0`; no `dnb` cover/blurb; `dnb` published dates are
year precision, projected dates month precision and never override published/on_sale; no dated volume from an
announcement-only future-year record; no ISBN twice within a line; the pre-DNB DE line ids still present; a linker
fixture (the spike's hand-labelled lines) with 0 wrong on the ground-truth set and ≥95% on the labelled set.
Measure (`export/measure_library.py`): DE line/volume counts above a floor, DE year-date coverage ≥95%, page-count
coverage ≥90%, link-rate floor, idempotent reload (same ids).

## Scale [E]
~19,000 print volumes after ISBN merge (+~800 Japanese-origin without `spo`); ~2,000–2,400 multi-volume lines + one-shots;
exportable at high/medium ≈ 1,200–1,400 lines / 11,000–12,000 volumes (from 35 lines / 391 volumes today).

## Risks
Undocumented rate limit; `spo` gaps and deposit holes; year-only published dates; clustering across mixed record
shapes; linker false positives (generic titles, spin-offs, alias noise, existing OpenTome duplicates such as
Narutaru/Shadow Star); LN classification fuzziness.

## As built (2026-09-24, branch `dnb-ingest`)

Code: `tier0/dnb_sru.py` (client), `tier0/dnb_enumerate.py`, `tier0/dnb_marc.py`,
`tier0/dnb_link.py`, `tier0/build_dnb.py` (stage 3e), tests `tier0/test_dnb.py`; gates in
`export/test_artifact.py` / `export/measure_library.py`. Measured results:
`docs/german-market.md`. Where the build departs from, or adds to, the text above:

- **Enumeration.** `jhr` is multi-valued and some records have none (7 + 304): each channel
  also pages `not jhr>0`, and the check is distinct records == the unsliced total.
- **Origin.** Records with no 041$h stay in scope unless 245$c says "aus dem Koreanischen"
  (etc.) or a keyword says manhwa / webtoon / manhua -- nothing else separates the Japanese
  manga catalogued without 041 from German originals; the linker is the gate.
- **Manga signal.** The pre-2004 DNB subject group `08` counts as a comic signal alongside
  DDC 741.5.
- **Announcements.** leader/17 = '8' marks an announcement record. Announcement-only
  volumes dated after the current year are not volumes at all (held back, not exported
  undated -- undated they would sink date coverage and ship placeholders). Current-year
  announcements without a 263 month stay undated.
- **264$c months** are not read (9/930 in the spike; not worth the second date semantics).
- **Linker.** The prefix tier reads original titles only ("Detektiv Conan" is the start of
  every Conan spin-off's German title); among several matching works, the one whose title IS
  the line's own title proper wins (own-title); author overlap picks the work sharing the
  most creators. A spin-off-shape cap was tried and dropped (see german-market.md).
- **Merge.** Any DNB volume whose ISBN is a German Wikipedia volume's attaches to it (gains
  dnb claims, fills only empty columns); a line holding the majority of the smaller side's
  ISBNs merges and keeps the rl_ id. Several Wikipedia lines <-> one DNB line leaves the
  Wikipedia lines as they are (all 35 ids stay present; none occurred).
- **Redirects.** Prior-build state is the carried artifact: a German tome_id it has that the
  build lost is redirected to the line now holding most of its ISBNs, volumes by number, and
  the export hands the old integer id to the successor. Since 2026-09-25 a general writer does
  the same for every market and entity (`tier0/carried_ids.py`, stage 7b, `docs/carried-ids.md`)
  and the carried-id gate covers every market; this stage-3e pass stays, and 7b leaves the ids
  it redirected as they are.
- **Freshness.** `DNB_REFRESH_DAYS=N` refetches last year's slice (deposit lag), the current
  and future years, the no-year remainder and parent batches older than N days; a refresh run
  re-reads the totals and re-pages only frozen slices whose count changed. Default off.
- **Resolve.** A bare DNB year never beats a finer claim it disagrees with (9 of the 223
  volumes with both a DNB year and another date); scoped to DNB, it changes 0 other values.

### Review round (2026-09-24)

NFC at parse time; medium links need no author contradiction (fuzzy romanised name match);
part titles out of link keys; box ISBNs and box set records out; publisher families and
signature merging in clustering; 245$a numbers before 490$v; exported `id_redirect`, `kept`
lines and a carried-id gate; date floor on deposited volumes, projected months dropped after 12
months; refresh window 6 days with a cache fallback; parents fetched once via
`.cache/dnb-parents.json`; manhwa / manhua works out. Details: `docs/german-market.md`.
