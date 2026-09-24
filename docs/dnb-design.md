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
   (others wait for the KR/CN round).
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
a changed key → `id_redirect`, never a silent re-key (ids are a public contract).
Merge with the existing ~35 Wikipedia DE lines: majority-ISBN match reuses the `rl_` id; volumes (`v_` from line +
number) merge and gain `dnb` claims; one Wikipedia line ↔ several DNB lines: most-ISBN keeps the id, others are new
siblings; several ↔ one: keep the larger, redirect the rest. The 35 current DE line ids must survive.

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
