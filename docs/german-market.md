# The German market — measured, and a required change of approach

## The extractor works. The source doesn't have the data.

`tier0/de_tables.py` parses German volume tables correctly. Verified against
*Attack on Titan* (de): 61 records, with Japanese **and** German dates and ISBNs per
volume, rowspan-immune.

It also produced an unplanned cross-check. German Wikipedia gives volume 1's Japanese
date as **2010-03-17, ISBN 9784063842760** — *identical* to what French Wikipedia
supplied independently. Two unrelated language editions agreeing exactly, which makes
cross-language Wikipedia agreement a corroboration source in its own right.

## But Attack on Titan is not representative

Random sample of 40 German articles drawn from the langlink set:

| | |
|---|---:|
| Contain any ISBN | 12 (30%) |
| Use `{{DatumZelle}}` | 1 (2%) |
| **Yield volume records** | **3 (8%)** |

**Projected usable German articles: ~68.**

Two compounding limits:

1. **Only 21% of English articles have a German equivalent** — 917 of 4,270. An earlier
   probe suggested 60%, but it sampled the first 200 articles, which skew toward older,
   well-established series. A biased sample gave a number 3× too high; the random sample
   corrected it.
2. **Of those 917, only ~8% carry volume tables.** German Wikipedia documents manga
   series without cataloguing their volumes, which English and French routinely do.

## Consequence: DNB becomes a PRIMARY source, not a verifier

DNB was deferred earlier on the grounds that it had nothing to verify. That reasoning
was right but the conclusion is now different: **German volume data should come from DNB
directly rather than from Wikipedia.**

This is a better position than the one we were aiming for:

- **DNB is CC0** — public domain, no attribution requirement, no share-alike,
  commercial use unrestricted. It is the cleanest-licensed source in the entire project,
  cleaner than Wikipedia facts.
- **Legal deposit means completeness.** Every book published in Germany is in it by law,
  including the long tail Wikipedia ignores.
- **Publisher-scoped queries already work.** Step 0 verified `TIT=… and VLG=Carlsen`
  returns clean per-volume records: `245$n` volume number, `300$a` extent, `008[7:11]`
  year.

The approach inverts: enumerate by publisher (Carlsen, Egmont, altraverse, TOKYOPOP,
Panini Manga Deutschland) rather than by series, and let legal deposit supply the
catalogue.

**The known cost:** DNB dates are year-precision only (`008`). Germany would have
complete coverage at low date precision — the mirror image of France, which has
day-precision dates and no corroboration.

## Actual result of the full pass

917 German articles, 0 errors, 15.9 minutes:

| | |
|---|---:|
| DE release lines | **32** |
| DE volumes | **381** (282 day-precision) |

The survey projected ~68 usable articles and the run produced 32 release lines from them
— the projection was right in scale.

### For comparison, the whole catalogue

| Market | Lines | Volumes |
|---|---:|---:|
| JP | 8,196 | 83,527 |
| EN | 3,729 | 37,355 |
| FR | 2,036 | 23,886 |
| **DE** | **32** | **381** |

**Germany is 0.26% of the catalogue.** For the market that is 20% of European manga
sales, that is not coverage — it is a rounding error.

This settles the question the survey opened. German Wikipedia is not a viable source for
the German market, and no amount of parser work changes that: the extractor is correct
and the articles are empty. **DNB, as a primary source, is the German strategy.** The 381
volumes here are a supplement worth keeping and nothing more.

## 2026-09-24 — DNB wired in (`tier0/build_dnb.py`, stage 3e)

The design is `docs/dnb-design.md`; this is what the first full run measured.

**Access.** 353 SRU requests for the first full enumeration, 32 more for the no-year
remainder slices and the parent batches added after it, and 7 count probes: **392 requests
in all** (`build/dnb-netlog.tsv`), every one HTTP 200, 3.0 s apart; no 429 or 503. A rerun
is zero requests (the offline rebuild verified it: `DNB_OFFLINE=1`, no new cache file).

**Enumeration.** 25,270 records from `spo=jpn and bbg=A*`, 2,522 from the six manga-imprint
phrases (`not spo=jpn`), 794 parent sets fetched by `idn` (the rest were already in channel 1).
Two things the spike could not see, both caught by the completeness check:

- `jhr` is multi-valued: the year slices of channel 1 held 25,933 hits for 25,270 records.
- Some records have no `jhr` at all: 7 in channel 1, 304 in channel 2. Each channel now also
  pages a `not jhr>0` remainder, and the distinct records paged must equal the unsliced total.

**Selection** (27,792 records): 1,117 out of scope by origin (041$h kor 554, eng 238, fre
185, chi 60, ...), 2,456 neither manga nor light novel (Japanese literature, non-fiction),
216 bundles / box sets / starter packs, 123 artbooks / guides / colouring books, 9 combined
"1 - 3" records. Two findings changed the field logic:

- Records before ~2004 carry the DNB subject group `08` instead of DDC 741.5 (Akira, Banana
  Fish, Spriggan); every `08` record among the Japanese-origin ones is a comic.
- ~975 records of the imprint channel have no 041$h. They are mostly Japanese manga catalogued
  without it (Komi Can't Communicate, Yotsuba&!) next to a few German originals, and no field
  separates them. They stay in scope; a German original ships only if it links to an
  OpenTome work, and then it is that work's German line.

**Volumes and lines.** 21,770 volume records -> 21,331 volumes (439 ISBN twins merged, 95
box-set ISBNs dropped) -> 4,556 lines. Older records append the statement of responsibility
to the part number ("2. / [Aus dem Japan. von ...]", "# 7", "Song 2."); parsing those cut
the unnumbered drops from 1,198 to 57.

**Linking** (title + author, no ISBNs): high 1,246, medium 353, low 210, ambiguous 7, none
2,740. Exported: **1,557 linked lines + 30 merged into a German Wikipedia line + 1 ISBN
sibling**; 217 low/ambiguous lines are in `build/dnb-review.tsv`; 2,738 lines link to no
OpenTome work and are held back (decision 1).

- Ground truth, the DNB lines that share ISBNs with a German Wikipedia line: 32 lines, 30
  linked at high/medium, **0 wrong**.
- The spike's 80 hand-labelled lines (`export/fixtures/dnb_linker_labels.json`): 77 found,
  44 linked, **43 correct (97.7%)**, recall 43/49. The one wrong link is the spike's own:
  the Okubo one-shot "From the sea", published inside the Fire Force series statement.
- Spin-offs whose series statement names the parent franchise still link to the parent
  work ("Bungo Stray Dogs: dead apple"). A cap on that shape was tried and dropped: a
  German subtitle looks the same ("Hell Mode. Unterforderter Hardcore-Gamer ..."), and it
  sent three correct lines to review while catching none of the real ones.

**Dates.** A deposited record gives the 008 year (`published`, year precision). An
announcement-only volume takes its 263 month (`projected`); 142 announcement-only volumes
dated after this year are held back; 518 current-year announcements without a 263 stay
undated.

**Known gaps**: legal-deposit holes (Egmont 2015-2019, the TOKYOPOP 2005-2009 combined
records) mean no completeness claim; one-shots link rarely (generic titles); a Swiss
publisher's German editions carry 978-2 ISBNs (Kazé / Crunchyroll SA), which the audit's
"DE lines with no DE-group ISBN" line counts as information.

**In the artifact** (offline rebuild on the warm cache, 2026-09-24):

| Market | Lines | Volumes |
|---|---:|---:|
| JP | 6,978 | 67,703 |
| EN | 3,030 | 26,188 |
| FR | 1,493 | 16,857 |
| **DE** | **1,593** | **12,678** |

German went from 35 lines / 391 volumes (0.3% of the catalogue) to 1,593 / 12,678 (10.4%):
1,574 manga lines and 19 light-novel lines. Dates: 11,178 published years, 670 projected
months, 292 Wikipedia dates, 538 undated (95.8% dated); page counts on 97.8%. Nothing outside
the German market changed: series, aliases and volumes of every other language are
identical to a DNB-free export of the same catalogue, and the 35 German Wikipedia lines keep
their ids and integer ids.

## 2026-09-24 — after the independent review (same branch)

The review found real defects in the exported German data; all fixed, re-measured offline
(zero DNB requests):

- **NFC.** DNB text is NFD: "ungezählte" never matched (1,345 page counts short), umlaut
  patterns never fired, 99 names / 44 publishers / 99 aliases shipped NFD. Now normalised at
  parse time; a contract rule forbids non-NFC German strings.
- **Linker precision.** Medium needs one side without creator data; both sides naming creators
  with none shared is a title collision (review). Names fold romanisation and agree on a family
  name within one edit; 245$c credits and translator-free 700s count. Part titles (a volume's
  245$a inside a set / numbered series, anthology volumes' 240) no longer key links; an ISBN
  shared across two different sets with different titles twins nothing. The nine confirmed
  wrong links are gone and pinned in the fixture (`must_not_link`). Cost: 3 correct
  artist-credited lines now in review (Gate, AJIN, Puella Magi Madoka Magica; Cantarella's
  second line unclear).
- **Bundles and boxes.** Double Pack, Doppelpack, NNer-Pack, Schmuckbox, Einsteiger-Set,
  Dekorama / Acryl-Aufsteller editions, Schuberauflage, Tarot-Buch, Guidebook are out; a box
  ISBN (qualified "in Behältnis", "Kassette", "in Schuber", and again as a bare ISBN-10) is no
  volume's ISBN; a box set record never keys a line. Given (the German Wikipedia line) merges
  again; Death Note "The complete box", the Berserk Kassetten and the Double Packs are gone.
- **IDs.** The artifact exports `id_redirect`; each build re-reads the last artifact's; a line
  the linker stops linking stays published (`kept`); every German id of the carried artifact is
  gated present-or-redirected (426 today, all present).
- **Clustering.** Publisher families (VIZ Media Switzerland = KAZÉ = Crunchyroll = Pegasus;
  Planet = Panini); series-, title- and disjoint parent-keyed clusters of one signature merge.
  Split editions (the review's heuristic): 49 works in 111 lines -> 13 works in 26 lines (the
  rest are subtitle variants between set records).
- **Volume numbers.** 245$a's own number ("Band 16 (Finale)", a trailing number) beats a
  disagreeing 490$v; an unnumbered volume is 1 only when it is a real one-shot.
- **Dates.** The floor is measured on deposited volumes (99.8%); announced-only volumes are
  reported apart; a projected month more than 12 months past is dropped (381 had shipped).
- **Scope.** Works OpenTome knows as manhwa / manhua / webtoon are out (Ultramarine Magmell,
  Priest); "Aus dem Japan." counts as Japanese.

| | First build | After the review |
|---|---:|---:|
| DE lines / volumes | 1,593 / 12,678 | **1,459 / 12,470** |
| exported: linked (high / medium) + merged + sibling | 1,209 / 348 + 30 + 1 | **1,227 / 196 + 31 + 1** |
| linker on all lines: high / medium / low / ambiguous / none | 1,246 / 353 / 210 / 7 / 2,740 | 1,264 / 202 / 202 / 4 / 2,668 |
| review file | 217 | **206** |
| ground truth (linked, wrong) | 30/32, 0 | **31/33, 0** |
| labelled set | 43/44 (97.7%) | **44/45 (97.8%)**, recall 44/49 |
| dates | 95.8% of all | **99.8% of deposited**; 301 projected months; 92.8% of all |
| page counts | 97.8% | 97.8% (sums now include unnumbered pages) |
| split editions | 49 works / 111 lines | **13 / 26** |
