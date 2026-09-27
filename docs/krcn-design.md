# KR/CN coverage — licensed print editions of manhwa and manhua (design, 2026-09-27)

Status: DRAFT for Nick. Decisions 1–3 below are his (2026-09-27, binding). Points marked **NICK** are still open, and each carries a recommendation.

This spec follows `docs/dnb-design.md` and uses the same structure. Sources studied: the source research (`~/Claude/scratch/mangarr-session/krcn/sources.md`) and this round's spike. The spike code, caches and netlog are in `~/Claude/scratch/mangarr-session/krcn/`: `sru.py`, `loc_analyze.py`, `loc_yield.py`, `dnb_spike.py`, `bnf_analyze.py`, `combine.py`, `cache/` and `netlog.tsv`. The DNB responses are in the repo's `.cache/`, fetched through `tier0/dnb_sru`.

Numbers are marked [M] when measured in the spike and [E] when estimated. The baseline is the published artifact `opentome-2026-09-25` (`build/alias-fix/carry.sqlite`) together with the pipeline catalogue `build/opentome.db` of 2026-09-24. The catalogue was only ever opened read-only.

The spike wrote to the repo only in these gitignored places:
- DNB cache files in `.cache/`: 7 count probes and 5 parent batches. The batches were fetched outside `.cache/dnb-parents.json`, so production's own chunking will re-fetch about 5 batches.
- Appended lines in `build/dnb-netlog.tsv`.

`docs/superpowers/` is gitignored, so this spec is local-only, like its sibling specs.

Requests made in the spike:

| Source | Requests | Results | Notes |
|---|---|---|---|
| Library of Congress | 137 | all HTTP 200 | 42 of them were SRU diagnostics (see Access) |
| BnF | 36 | all HTTP 200 | |
| DNB | 12 new | | 7 count probes and 5 parent batches. The `spo=kor` / `spo=chi` result sets were already cached by the source research (50 requests on 2026-09-27 07:27) |
| AniList | 0 | | |
| Open Library | 0 | | |

## 0. In one paragraph

The segment is larger than the catalogue suggests. Today OpenTome has 54 works with a manhwa or manhua line [M]: 23 EN manhwa lines, 2 EN manhua, 6 FR manhwa and 0 DE. The three national libraries add the following.

- **DNB:** 396 German lines / 1,644 volumes [M], run through the existing DNB parser and clustering unchanged.
- **BnF:** 203 French lines / 1,278 volumes [M] from publisher channels, filtered on UNIMARC `101 $c`.
- **LoC, DLC-created records only:** 74 new English lines / 386 volumes, plus ISBNs for 107 of the 235 volume ISBNs already on existing EN KR/CN lines [M].

Only 11–23 lines per market link to works OpenTome already has. The rest cluster into roughly 520 candidate new works [E], and **only ~72 of them have an English line** [E]. So most new works are German- or French-anchored. They cannot bind to AniList the way existing works do (the resolver binds English lines only), and Mangarr cannot reach them today (its ranking is English-only). The round is therefore worth doing, but three things have to land with it:

- a stricter bar for creating a work than for linking one;
- an id rule for works that are born from library records and later meet a Wikipedia article;
- a Mangarr follow-up so that works without an English line are reachable.

## Decisions (Nick, 2026-09-27 — binding)

1. **New works may be created for KR/CN titles from library records.** For this segment this reverses DNB decision 1 ("no DNB-only works").
   - A work's anchor is its English line when one exists.
   - New works bind to AniList the same way existing works do: `export/resolve_anilist.py` (stage 8a) plus `corrections/anilist.json` pins, one cached search per line. There is no mass collection: AniList's terms forbid it.
2. **Library of Congress records are treated as US-government public domain, but only records whose `040 $a` is `DLC`** (created by LoC). All other LoC records are unverified and excluded. A LICENSE-DATA row is added.
3. **Publisher sites stay "cited, never fetched"** (`docs/legal-position.md`). The **National Library of Korea is out of scope.**

Decisions that follow from the spike but are Nick's to confirm (**NICK**) are collected in §15.

## 1. Baseline — what exists (checked 2026-09-27, not remembered)

**KR/CN works today.** 54 works have a `manhwa` / `manhua` line [M]. At least 5 of them also hold Japanese content:

- **Wind Breaker:** the Japanese Kodansha manga and the Korean webtoon were merged by title in `tier0/work_identity.py`'s title-union.
- **Pandemonium:** a Japanese manga plus a Korean manhwa.
- **Monster Eater**, **Demons' Crest** and **The Brilliant Healer's New Life in the Shadows:** Japanese works with a manhwa-tagged line.

Another **14 works carry a `ko` / `zh` line but no manhwa/manhua medium** [M]: I Love Amy, King of Hell, Banya, Biao Ren, the Pili Fantasy lines, Dr. Frost and others. **English-only KR works tagged `manga`** also exist: Chronicles of the Cursed Sword, The Tarot Café, Jack Frost [M: LoC ISBN overlap]. So "is this work Korean or Chinese" cannot be read off `medium` alone. §10 defines the rule this round uses.

**What the medium label currently touches.**
- `dnb_link.Index.non_japanese` is the set of works with a manhwa/manhua/webtoon line. It sends a German DNB line that links to such a work to `out_of_scope`. Today that affects 2 lines (Ultramarine Magmell, Priest; 9 volumes) [M].
- The same set wrongly contains the 5 mixed works above, so a German line of their Japanese side would also be dropped. Today there are 0 such lines [M], so this is a latent defect only.
- `release_lines.MEDIUM_HINTS` maps a "webtoon" heading to `manhwa`. The artifact has **0 `webtoon` lines** [M].
- Korean and Chinese prose is `novel` (ko 6, en 3 lines) [M].

**BnF and Open Library.** Both are used today only for ISBN-level enrichment in `tier1/enrich_more.py`, not as line sources:
- BnF: one `bib.isbn` SRU call per FR volume, which yields `volume_number` and `page_count` claims.
- Open Library: 50-ISBN batches for EN and FR.

`sources.md`'s "existing BnF pipeline" is imprecise. What exists is a client and a UNIMARC field reader. There is no enumeration and no line building.

**LoC was rejected once.** `tier1/enrich_more.py`'s docstring says LoC SRU "returned zero records even for control queries". Here is what differs now:
- The endpoint is `http://lx2.loc.gov:210/lcdb` with the `bath.isbn` index.
- The control `bath.isbn=9781975319434` returns the Solo Leveling set record [M].
- The gateway answers **"First record position out of range" on 42 of 137 requests** [M]. All of these were HTTP 200, all were record pages, and all 40 count probes succeeded.

The earlier "zero records" was almost certainly this diagnostic. §3 handles it, and the canary gate in §13 keeps a silent zero from ever shipping.

## 2. Licence and exclusions (per source)

| Source | Licence label (`schema/load.py` LICENCE) | Kept | Never read |
|---|---|---|---|
| DNB | `cc0` (existing) | as in dnb-design.md | covers, `856` blurbs (`X:MVB`), TOC PDFs |
| **LoC** | **new `us_gov_pd`** | only records with `040 $a` = `DLC`: bibliographic fields | `520` (publisher summary, "Provided by publisher"), `856`, cover links; the processing fields `906`/`923`/`925`/`955` are never stored (`955`'s "v. 1 rec'd 2021-07-15" is a receipt date, **not** a release date — same rule as DNB's `015`) |
| BnF | `open` (Etalab, existing) | as today | cover links |
| Open Library | `noncommercial` (existing) | dates, pages by ISBN (existing enrichment) | — |
| AniList | none stored | an id per line (existing) | titles, synonyms, descriptions |
| Publisher sites | — | cited in `corrections/*.json` only | never fetched (decision 3) |

**The LoC licence rests on 17 USC §105** (US government works). It is Nick's decision, not a stated LoC licence: MDSConnect says only "research and development usage".

**A non-DLC record is not read at all.** It is not a twin, not a classification hint, and not linker evidence. A DLC record whose `040 $d` lists modifying agencies other than LoC is still DLC-created and is kept.

**The license change is three edits and one gate.**
- `LICENCE["loc"] = "us_gov_pd"`.
- `schema.sql` `clean_claim` must list `us_gov_pd` explicitly. Today it is `licence IN ('cc0','open','facts_only')`, so a new label would silently fall **out** of the commercial subset.
- `free_claim` needs no change.

LICENSE-DATA.md needs a new row:

> | Library of Congress (LoC) | US government work (17 USC §105), public domain in the US — records created by LoC only (`040 $a DLC`) | English volumes, ISBNs, year dates and page counts of licensed Korean/Chinese comics. Records LoC copied from other libraries are excluded; publisher summaries (`520`) and links (`856`) are never read |

`meta.attribution` gains "Library of Congress (US government work; LoC-created records only)". `docs/legal-position.md` gains a row. Outside the US, public-domain status for a US government work is an assumption; the existing EU database-right caveat applies.

**What the DLC rule costs, measured on the channels enumerated.** It excludes the following publishers almost entirely: WEBTOON Unscrolled (0/6 DLC), Inklore (0/7), Seven Seas (0/2 KR/CN comic records; the current 979-8-88843 / 979-8-89160 blocks hold 2 and 1 LoC records at all), Drawn & Quarterly (0/8), and most legacy Tokyopop (DLC 13/88, 16/50, 74/151 on its three stems) [M].
- Excluded: **73 new English lines / 218 volumes**, including the Tower of God and Noblesse English lines, which are non-DLC.
- Kept: 74 lines / 386 volumes [M].

## 3. Access and politeness

All three sources share the following:
- serial access with at least 3 s between requests across processes (the `dnb_sru` throttle pattern with a stamp file per source);
- the descriptive User-Agent of `tier0/dnb_sru.UA`;
- a disk cache under `.cache/` keyed `sha256(url)[:32].xml`;
- a netlog per source (`build/<src>-netlog.tsv`);
- `<SRC>_OFFLINE=1`;
- one Retry-After wait, then a stop on a second 429/503;
- a result set is cached whole or not at all (`dnb_sru.search()` semantics), and it is complete only when the distinct records paged equal `numberOfRecords`.

**DNB.** Nothing changes; the client is `tier0/dnb_sru.py`. Parents come through `dnb_enumerate.fetch_parents` and its `.cache/dnb-parents.json` index. The 129 KR/CN parents missing from the index cost 5 batches [M].

**LoC** (`http://lx2.loc.gov:210/lcdb`, SRU 1.1, `recordSchema=marcxml`):
- `maximumRecords=100` works [M]. No key is needed and no limit is documented.
- **Diagnostic retry.**
  - An HTTP 200 response carrying `<diag:message>First record position out of range` is a transient failure. It is never cached; it is retried up to 3 times, 10 s apart.
  - In the spike every page recovered within 3 attempts except one: `bath.isbn=97988554*` records 301–400 failed on all 5 attempts [M].
  - A page that still fails leaves its result set incomplete. The existing DNB rule then applies: the build fails, or on a refresh run it keeps the previous complete set and marks the build degraded (`meta.loc_degraded`), and publishing is refused.
  - Page size made no difference: pages of 50 failed as well [M].
- **Canary.** Each run first sends `bath.isbn=9781975319434` and must get exactly 1 record with `040 $a DLC`; otherwise the stage fails.
- **Refresh.** ECIP records at encoding level `5` are upgraded later. Suggested window: `LOC_REFRESH_DAYS=28` on all channels [E: ~40 pages ≈ 60 requests with retries per refresh].

**BnF** (`https://catalogue.bnf.fr/api/SRU`, SRU 1.2, `recordSchema=unimarcxchange`):
- `maximumRecords=500` works (330 records in one 1.9 MB response) [M]. The first run is about 12 requests [M-scaled].
- Note: the existing per-ISBN enrichment throttles BnF at 1.0 s (`enrich_more._fetch_xml`). The new channel uses 3 s.

**Seed the CI cache before the first CI build.** This is the HANDOFF rule, and it applies here harder than it did for DNB:
- Regenerate `opentome-cache.tar.zst` from the **full** local `.cache`, never append. It must hold the new DNB `spo=kor` / `spo=chi` slices, their parent batches, and the LoC and BnF result sets.
- Upload it as the `seed` asset, then run the seed-cache workflow.
- Without the seed, a cold CI build has no complete earlier result sets, and one persistently failing LoC page fails it. The spike saw one such page: `97988554*` records 301–400 failed on all 5 attempts.

**Budget of a cold first run [E]:**
- DNB: ~70 requests (spo slices, parents, counts).
- LoC: ~130 (channels below plus retries).
- BnF: ~15.
- AniList: see §11.

A rerun is zero requests.

## 4. Enumeration

### DNB (German)
The existing machinery handles this, with new channels and the origin rule inverted.
1. `spo=kor and bbg=A*` — 2,273 records [M] (1,565 with `sgt=741.5` [M]).
2. `spo=chi and bbg=A*` — 2,646 records [M] (250 with `sgt=741.5` [M]). This channel is mostly Chinese literature, and the classifier drops that (§7).
3. The existing imprint channel (`dnb_enumerate.IMPRINT_Q`, already cached): records with no `041 $h` whose `245 $c` says "aus dem Koreanischen / Chinesischen" or whose keyword (`653`) says manhwa / webtoon / manhua — 42 records [M].
   - `sw=Manhwa`, `sw=Webtoon` and `sw=Manhua` return 0 [M]. `653` keywords are not in the `sw` index.

Each channel is sliced by `jhr` with the `not jhr>0` remainder, exactly as `dnb_enumerate.run_channel` does. Parents come from `773 $w`.

Total: 4,959 records [M]; 373 parent sets known after the fetch.

### LoC (English) — ISBN stems plus subject channels
- **ISBN stems.** `bath.isbn=<stem>*` truncation matches any `020` in a record, so a set record is found through any of its volume ISBNs. Stems were derived from the registrants of the ISBNs already on the carry's EN KR/CN lines, not from memory [M counts]:

| Stem | Imprint | Records |
|---|---|---:|
| `97984009` | Ize Press / Yen | 55 |
| `97988554` | Yen | 562 |
| `9781975` | Yen | 1,551 |
| `97807595` | Yen / Hachette | 227 |
| `978159816` | Tokyopop | 151 |
| `978159182` | Tokyopop | 89 |
| `978159532` | Tokyopop | 50 |
| `978199025` | Wattpad WEBTOON | 30 |
| `978168579` | Seven Seas | 63 |
| `978163858` | Seven Seas | 276 |
| `979888843` | Seven Seas | 2 |
| `979889160` | Seven Seas | 1 |
| `9781998854` / `9781990778` | WEBTOON Unscrolled | 3 each |

  - The Yen, Tokyopop and Seven Seas stems are mostly Japanese manga, so the filter is local (§7).
  - `9781427*` (3,685), `9798217*` (3,193), `97805938*` (2,385) and `97805939*` (1,214) are shared Bowker / Penguin Random House blocks: too broad to page, and not used.
- **Subject channels** [M counts]:
  - `dc.subject="Comic books, strips, etc.--Korea"` 387
  - `...--China` 240
  - `...--Taiwan` 22
  - `dc.subject="webcomics"` 137
  - `dc.subject="manhwa"` 23
  - `dc.subject="Graphic novels" and dc.subject="Korea"` 116
  - `... "China"` 91
  - `dc.subject="Comics (Graphic works)" and dc.subject="Korea"` 49
  - `dc.subject="manhua"` 0
  - `cql.anywhere="translated from the Korean"` 199, mostly prose
- **Not usable:**
  - `dc.publisher` returns nothing (source research).
  - `cql.anywhere="Ize Press"` returns 4 of the 55 Ize records [M].
- The spike paged 3,236 distinct records [M]. The channels also held 337 Korean-language and 95 Chinese-language originals (§16).
- **Headline LoC metrics [M]:**

| Set | Records | DLC (`040 $a`) | Origin evidence | Other |
|---|---:|---|---|---|
| Translated, KR/CN origin | 324 (312 in English) | 214 (66%) | 290 by `041 $h`, 34 by note only | — |
| English comic subset | 75 | 35 | — | per-volume ISBNs (`$q v. N`) on 18 set records covering 114 volumes; the other 57 are single-volume records; 23 volume numbers carry two ISBNs |
| Ize Press (stem `97984009*`) | 55 | 54 English, all DLC | no `041` on all 40 level-5 records | 40 at encoding level `5`, 2 CIP |

- Separating comic from novel in LoC: see §7.

### BnF (French) — publisher channels filtered on `101 $c`
Channels [M counts; share with `101 $c kor`]:

| Channel | Records | `101 $c kor` |
|---|---:|---:|
| `bib.publisher all "Tokebi"` | 453 | 402 |
| `"Kbooks"` | 330 | 266 |
| `"Saphira"` | 259 | 228 |
| `"Samji"` | 208 | 174 |
| `"Clair de lune" and bib.subject all "manhwa"` | 194 | 137 |
| `"Kotoon"` | 98 | 35; 54 have no `101 $c` |
| `"Ki-oon" and ...manhwa` | 572 | 54 |
| `"Pika" and ...manhwa` | 1,333 | 13 |
| `"Delcourt" and ...manhwa` | 805 | 0 |

- `bib.subject all "manhwa"` is contaminated. It returns 12,966 records per the source research, and Delcourt's 805 "manhwa" hits hold 0 Korean records.
- `bib.subject all "webtoon"` / `"manhua"` return 0, and `"bandes dessinées coréennes"` returns 0 [M].
- **Chinese in French is a gap:** Xiao Pan has 39 records, of which 4 carry `101 $c chi` and 35 have none [M]. The `101 $c` filter misses most French manhua.
- Webtoon Factory has 1 record and Verytoon 0 [M].
- Total: 1,304 KR/CN records (kor 1,300, chi 4) out of 4,285 paged [M].
- 137 of the 203 lines date from 2003–2014 (the Tokebi / Saphira / Samji era) [M].
- The channel list is an allowlist in code. Adding an imprint is a one-line change plus a count probe; it is not a recurring manual step.

## 5. Parsing

**DNB:** `tier0/dnb_marc.py` unchanged. Pages 97.5%, ISBN 100% [M].

**LoC** is MARC21 slim in the same namespace, so `dnb_marc.records()` parses it [M]. The differences, each of which needs its own function or rule:

- **`020`.**
  - `$q` holds the volume: `v. 1`, `(v. 1 ;` or `v. 14 ;`, followed by the binding (`trade paperback`, `hardcover`). The parse is `^\W*v\.\s*(\d+)`.
  - 18 set records carry at least 2 `$q v. N` ISBNs, covering 114 volumes [M]. 23 volume numbers carry two ISBNs (hardcover and paperback) [M]. The volume keeps the ISBN an existing OpenTome volume already has, otherwise the paperback (`$q` contains "paperback"), otherwise the first listed. The second ISBN is stored as a claim `isbn13_alt` and not exported in v1.
  - `$z` is never read, as for DNB.
- **Encoding level.** `leader/17` = `5` (ECIP preliminary) on 40 of the 55 Ize records [M]. These have no `041`, `082`, `050` or `655` and carry `300 "volumes cm"`. `leader/17 = 8` is CIP (announcement), with the same meaning as DNB's `is_announcement`.
- **`263`.** YYMM (`2610` = 2026-10), **not** DNB's YYYYMM, and `1111` means unknown [M: 7 CIP records with a real 263; `1111` on 7 Ize records]. `dnb_marc.planned_month` would reject YYMM, so LoC needs its own parser with a `1111` guard.
- **`008`.**
  - Date type `m`/`d` (a multi-volume set: `m20219999` means "2021 to open"), 35 of 75 comic records [M]: date1 is the **set's** start year and never dates a volume.
  - Date type `s`/`t` (single volume): date1 is that volume's year.
- **Classification signals.** `082` (741.5 vs 895.7x / 895.1x); `050` (`PN6790` / **`PN8323`** is used for manhwa/webcomics — Solo Leveling, Tower of God [M] — vs `PL9xx` / `PL2xxx`); `655` LCGFT ("Comics (Graphic works)", "Graphic novels", "Manhwa", "Webcomics" vs "Fantasy fiction", "Light novels"); `650 "Comic books, strips, etc."`.
- **Origin.** `041 $h kor|chi`, else a "Translated from the Korean/Chinese" note (`500`/`546`/`245 $c`). The `008/35-37` language gives Korean-language *originals* (out of scope).
- **Titles.** `245 $a` (strip the ISBD " /" and " :"), `$n`/`$p`, `490`/`830 $v`, `246`, and the original title in `240` or `765 $t`, present on 44 of 75 comic records [M]. `880` vernacular (Hangul/Hanzi) is on only 4 of 75 [M]. Romanisation is ALA-LC (`Chinjihan kŏn`), so it does not key against DNB's (§9).
- **Creators.** `100`/`700` with `$4` / `$e` (`dnb_marc.creators()` applies, `trl` dropped).
- **Pages.** `300 $a "283 pages"`, only on single-volume records: 22 of 75 [M].
- **Not read.** `520`, `856`, `906`, `923`, `925`, `955`.
- **Source URL.** `https://lccn.loc.gov/<010 $a>`.

**BnF** (UNIMARC via marcxchange). Field map:
- `010 $a` ISBN (89% of KR records) [M]
- `100 $a/9-12` date
- `101 $a` text language / **`$c` original language**
- `200 $a` title, `$h` volume number (87%) [M], `$i` part title, `$e` other title
- `210`/`214 $c` publisher, `$d` year (100%) [M]
- `215 $a` "192 p." (64%) [M]
- `225 $a`/`$v` and `461 $t`/`$v` series (90%) [M]
- `454 $t` / `500 $a` original or uniform title (29%) [M]
- `700`/`701`/`702 $a $b $4`

Extend `enrich_more`'s field reader into a `tier0/bnf_unimarc.py` module with the same pure-function shape as `dnb_marc`. Source URL: the record's ark (`003`).

## 6. Scope of a record

A record is in scope when **all** of the following hold:
1. **Origin:** Korean or Chinese, by `041 $h` / `101 $c`, or by a statement ("aus dem Koreanischen", "Translated from the Korean"), or by a KR-only imprint (§7).
2. **Class:** comic (§7). Prose is handled by §7's novel rule.
3. **Print.** DNB `bbg=A*`; LoC `338 volume`; BnF monograph (`leader/6-7 = am`: 1,304 of 1,304) [M].
4. **Not a bundle, box, artbook or guide** (the `dnb_marc.classify` exclusions; LoC/BnF text equivalents: "box set", "coffret", "artbook", "guide").
5. **LoC only:** `040 $a DLC`.

## 7. Medium classification

**Mediums: `manhwa` for Korean origin, `manhua` for Chinese / Taiwanese origin, `novel` for prose.**
- No `webtoon` value is introduced. `release_lines.MEDIUM_HINTS` already maps webtoon to manhwa, the artifact has 0 `webtoon` lines, and a print collection of a webtoon is a manhwa volume.
- Mangarr treats every non-novel medium as manga (§14), so no consumer change is needed for the value itself.
- `light_novel` stays reserved for Japanese light novels.

**Comic vs prose.**
- **DNB.** `dnb_marc.classify` as-is. `manga` becomes manhwa/manhua, `light_novel` becomes `novel`, and `other` is out (literature, non-fiction).
  - On the 4,715 non-parent records: 1,641 comic, 54 prose, 2,915 other, 99 bundle, 6 extra [M].
  - The DDC and the classifier agree on 1,622 of 1,641 comics; 18 carry no DDC (Thema/VLB signals only) and 1 a literature DDC [M].
  - Only 1 record has a literature DDC but a comic class [M].
- **LoC.** Comic when `082` 741.5, or `050` PN6790/PN8323, or `655`/`650` comic terms, **and** no prose signal. Prose when `082` 895.x, `050` PL, or `655` fiction / light novels with no comic signal.
  - Translated KR/CN-origin records (312 of 324 in English): 84 comic, 188 prose, 1 both, 51 neither [M]. "Both" and "neither" go to review.
- **LoC level-5 records (Ize).**
  - Ize prints both manhwa and prose. *Semantic Error* has a 6-volume comic record and a 3-volume novel record; ORV has an 11-volume comic record and a 4-volume novel record [M].
  - A level-5 Ize record's medium is resolved in this order:
    1. an existing OpenTome line it attaches to by ISBN;
    2. a same-work line classified in DNB or BnF (title key match);
    3. otherwise it goes to **review**.
  - Measured: 20 of 35 unclassified Ize lines resolve through (2), and 15 go to review [M].
  - A re-run after LoC upgrades the record (a refresh) classifies it on its own.
- **BnF.** Every KR record in the publisher channels is a comic; the channels are comic imprints. A `608 "Bandes dessinées"` form appears on 291 of 1,304 [M] and is supporting evidence only.

**Novels.** A `novel` line ships **only when it links to a work that also has a comic line** (existing or created in this round). This matches the existing ko/en `novel` lines of Solo Leveling, ORV, Villains and TBATE. No work is ever created from prose alone.
- Measured: 16 German novel lines / 51 volumes (Bramble / TOKYOPOP danmei novels: Grandmaster of Demonic Cultivation, Heaven Official's Blessing, …) and 188 English prose records, most of them Korean literary fiction [M].

## 8. Lines and clustering

**Line keys come from source data only, as with DNB, so relinking a line never re-keys it.**
- **DNB:** `dnb:<parent IDN>` or `dnb:<lowest member IDN>`, the existing rule, with publisher families extended to the KR imprints (papertoons, C Lines, Manhwa Cult, Altraverse).
- **LoC:** a set record, i.e. at least 2 ISBNs with `$q v. N`, **is** a line: `loc:<LCCN>`. Single-volume records cluster by folded `490`/`830` series, else by the folded bare title, plus the publisher family (Ize = Yen Press/Ize Press = Yen); key `loc:<lowest member LCCN>`.
- **BnF:** by folded `461 $t` / `225 $a`, else `200 $a`, plus the publisher family (Kbooks = Delcourt-Kbooks = Groupe Delcourt-Kbooks). Key `bnf:<lowest member ark>`.

**Merge with existing lines.** This reuses `build_dnb.assign_roles`: a new line holding a strict majority of the smaller side's shared ISBNs merges and keeps the existing `rl_` id; a second such line becomes a sibling. The existing DE/FR/EN line ids must survive.
- DNB: 1 merged (Solo Leveling), 1 sibling [M].
- BnF: 10 lines attach to existing FR lines by ISBN [M].
- LoC: 10 lines attach to existing EN lines [M] (8 of KR/CN-tagged works, 2 of KR works tagged `manga`).

**Library fixture check** (`export/fixtures/library.json` holds Solo Leveling, Solo Leveling (Second edition), and The Beginning After the End):

| Line | LoC DLC ISBNs of the existing Wikipedia EN line | Result |
|---|---|---|
| Solo Leveling | 15/15 | attaches, never a sibling |
| Solo Leveling (Second edition) | 8/8 | attaches, never a sibling |
| The Beginning After the End manhwa | 11/12 | attaches, never a sibling |
| The Beginning After the End novel | 0/11 | untouched |

All measured [M]. The measure replay therefore cannot flip on these three.

**Volumes.**
- The LoC `$q v. N` number is the volume number.
- DNB's volume logic is unchanged.
- BnF `200 $h`, else `225 $v` / `461 $v`.
- An existing Wikipedia volume with the same ISBN gains the library's claims and fills only empty columns (`build_dnb.fill_attached`). It never replaces a Wikipedia day date.

## 9. Work creation and identity (the public contract)

**When a line may create a work.** The bar is stricter than for linking, because a published work id can never be deleted. All four must hold:
1. The linker finds no existing work at high, medium, low or ambiguous tier. Low and ambiguous go to review, never to a new work.
2. The cluster contains at least one record with **explicit** origin: `041 $h` or `101 $c` kor/chi, or a translation statement. An imprint rule alone (Ize level 5, DNB's no-041 imprint records) is not enough.
   - WEBTOON Unscrolled and Inklore print Western originals (Boyfriends, Everything Is Fine) [M].
   - 1,662 of the 3,236 LoC records have no 041 [M].
3. At least one comic-classified volume.
4. **The containment guard (new).** No existing KR/CN work's official title key contains the line's key, or is contained in it (at least 5 characters). No existing work shares its original-title key. Otherwise the line goes to review.
   - Measured false "new" works that this catches: DE *Raeliana* (Altraverse, 9 vols) is the existing *Why Raeliana Ended Up at the Duke's Mansion*.
   - DE *Athanasia – plötzlich Prinzessin* (9 vols) is the existing *Who Made Me a Princess*. The guard does **not** catch it. It carries only a syllable-split romanised original title ("Eo neu nal gong ju ga doe eo beo lyeoss da") and syllable-split creators ("Seu pun" = Spoon) [M]. This is the class of error the review file exists for.

**What the work id hashes.** `w_<hash("krcn|" + anchor line key)>`. The anchor is the cluster's English line when there is one (`loc:<LCCN>`), else the German one (`dnb:<IDN>`), else the French one (`bnf:<ark>`). Library works are created **after** Wikipedia works and linking (a stage `3f`), so a work Wikipedia knows is never duplicated in the same build.

**Frozen through the carry.**
- Rule: once published, a library work keeps its id. The anchor can change later (an English LoC line appears for a German-anchored work), and re-hashing would then re-key the work.
- So stage 3f first reads the carry: every line whose `tome_id` shipped under a library work id keeps that `tome_work_id`.
- When two carried library works turn out to be one, the **older** keeps its id. "Older" means the lower minimum line integer in `id_map`, which is issue order, is carried, and is deterministic. The other gets `id_redirect(reason='duplicate_merge')`.
- `carried_ids.py` 7b already writes work redirects and gates orphans.

**When a Wikipedia article later covers a library work.** **NICK** decides; see §15-1.
- `docs/id-scheme.md` says to keep the older id, which here is the library id. `work_identity.py` would instead issue `w_<hash(wiki key)>`, and 7b would redirect library → wiki: the opposite.
- Recommendation: an **adoption rule**. When a Wikipedia work absorbs lines that shipped under a library work id, the Wikipedia work publishes under the carried library id; the wiki id is internal and never published. It is implemented as an internal→public work-id map in the export (the `id_map` pattern), so no redirect row is written.
- The alternative, the redirect, is simpler, but it breaks "keep the older id" and makes consumers follow a redirect.

**Titles of a library work.**
- `primary_title`: the English line's title; else a romanised original title that appears on two or more records; else the anchor line's own title.
- `work_title`: official titles per language (`en` / `de` / `fr` from each line), plus the original title as `romanized` (with its romanisation system unknown).
- `native_title` from `880` / Hangul `246` (DNB *Bastard* carries 후레자식 in `246` [M]), when present.
- Measured: 248 of 372 German new-work candidate lines carry an original title [M]. Many are German titles over English ones ("Overgeared", "The remarried empress" ship under their English title in German).

**Series integers and status.** New lines get integers through `id_map` as usual. Work `status` is left NULL (libraries do not say "completed").

## 10. Cross-market linking

**Linker changes** (`tier0/dnb_link.py`, shared by all three sources; each needs a test):
- **Hangul is dropped today.** `fold('나 혼자만 레벨업')` returns `''` [M]: NFD splits Hangul into jamo, and the kept range covers only kana and CJK. The fix: recompose (NFC) before the character filter and keep U+AC00–D7A3. `Index._add` gains Hangul keys.
- **KR/CN names need a full-name match.** `same_person` accepts a shared family name within one edit at 4+ letters. That is fine for Japanese names, but Park, Zhang, Wang and Chugong/Chu-Gong all pass [M]: `Park, Jin-hwan` = `Park Sun-young` evaluates True.
  - For a KR/CN line, author evidence requires the whole token set to be equal (after dropping hyphens and spaces inside given names).
  - This matters less than it sounds: only 5 of the 54 KR/CN works have any author claim [M], so KR/CN links are title-only (medium tier) in practice.
- **Japanese-work guard.** A KR/CN line whose best candidate is a work with a JP line and no KR/CN line goes to review. Measured: DNB *Ouroboros* (papertoons, Korean) linked at medium to the Japanese *Ouroboros* [M]; this is the Wind Breaker collision shape.
- **The KR/CN work set replaces `Index.non_japanese`.** A work is KR/CN when it has a manhwa/manhua line, **or** a KR/CN/TW market line, **or** it was created in this round. This fixes the German round's latent drop of the mixed JP works (§1) and admits the 14 ko/zh works tagged `manga`, such as King of Hell, which the DNB spike linked [M].
- **Romanised original titles do not key across libraries.** DNB syllable-splits ("Tem ppal" for Overgeared, "Eo neu nal gong ju ga …"), LoC uses ALA-LC (ŏ/ŭ, `Chinjihan kŏn`), and BnF often has none. Original titles key **within** a library only. Across libraries only the English title (which DE/FR records often carry verbatim), Hangul/Hanzi, and ISBN-free author sets link.

**Measured linker results** (existing works; ground truth by eye, no labelled set yet):
- **DNB:** 17 lines linked to 17 existing KR/CN works (Solo Leveling, TRK, ORV ×2, Villains ("Penelope – Das Böse ist dem Tod geweiht"), Sweet Home, Viral Hit, …). All 17 look right; 1 wrong (Ouroboros, blocked by the guard above). Plus 4 lines to KR/CN works tagged `manga` (King of Hell ×2, Love Is an Illusion!, Biao Ren), and 1 review (*Bastard*: Hangul key lost) [M].
- **BnF:** 10 attach by ISBN plus 11 title links (9 to KR/CN works); 18 distinct existing works; 0 to JP works [M].
- **LoC:** 10 attach by ISBN plus 1 title link (Solo Leveling: Ragnarok → Solo Leveling, a spin-off) [M].
- A linker fixture like DNB's is part of the gates (§13): the spike's title links (DNB 21, BnF 11, LoC 1) as `must_link`, and Ouroboros → the JP work as `must_not_link`.

**A German or French line to an English-anchored new work.** Library works are built in one pass over all three sources:
1. Cluster the unlinked lines of all markets by folded English title and Hangul/Hanzi keys. Titles only; a romanised key only within one library.
2. Attach clusters to existing works when the linker says so.
3. Create the rest.

Measured cross-market shape of the 628 new-work candidate lines [E: title-key clustering, precision unmeasured]:

| Markets | Candidate works |
|---|---:|
| DE only | 292 |
| FR only | 133 |
| EN only | 42 |
| DE + EN | 25 |
| DE + FR | 23 |
| EN + FR | 3 |
| DE + EN + FR | 2 |
| **Total** | **520** |

- **Only 72 of the 520 have an English line** [E].
- *A Business Proposal* EN/DE/FR, *Hanami* EN/FR, *Moon Boy* = *Le garçon de la lune*, *Level Up with the Gods* and *Under the Oak Tree* cluster correctly. So does *Astelle und der geheime Sohn des Kaisers* = *Comment cacher le fils de l'empereur*, through a shared original title [M examples].

**Works with no English line.** They ship. They are German- and French-anchored works, which is decision 1. Their consequences for AniList (§11) and Mangarr (§14) are the price.

## 11. AniList binding of new works

Existing practice is `export/resolve_anilist.py` stage 8a:
- **English lines only** (`load_lines`: `language='en' AND anilist_id IS NULL`);
- one cached name search per line, then the de-slug, R6 and at most 3 alias searches;
- 8 searches per GraphQL request, 2.1 s apart, cached per term under `.cache/anilist/`;
- then `corrections/anilist.json` pins.

**New English lines join automatically.**
- 74 new EN lines need about 74–300 searches, i.e. about 10–40 requests [E]. None are cached (0 of 74 names) [M].
- AniList `volumes` is typically null for webtoons. The volume rule skips null, so binding falls to title equality alone. The existing R1 guard (a synonym never beats a primary title) still applies.
- `format_not: NOVEL` also admits `MANHWA`-country entries; AniList's format for manhwa is `MANGA`. Mangarr does not request `countryOfOrigin` either (§14).

**Works with only DE/FR lines (~448 [E]) do not bind under the existing practice.** **NICK** decides; see §15-3.
- Recommendation: keep the practice (English lines only) this round.
- Binding a German or French line by its title would search localized titles ("Athanasia – plötzlich Prinzessin"), which AniList mostly does not hold. The ranker's title-equality rules would leave most unbound, and any bind found through an alias is exactly the fuzzy guess the resolver refuses.
- Mangarr also never looks a line up **by** `anilist_id` (§14), so a binding on a German line would not be read today.
- Revisit after Mangarr follow-up M1 lands, with a replay-measured rule, for example: bind a DE/FR line only on exact English-title equality with an English title the DNB/BnF record itself carries.
- Pins in `corrections/anilist.json` remain the per-work manual path.

## 12. Dates

- **DNB:** unchanged.
  - `008` year → `published` at year precision.
  - `263` YYYYMM → `projected` at month precision.
  - Future-year announcements are held.
  - Spike: **deposited volumes 1,196, dated 1,196 (100%)** [M].
  - **Announced-only volumes 448 (27% of 1,644)** [M]: 123 carry a projected month, 68 are held (future year), 257 are undated. That is a far larger announcement share than the Japanese round's, because the German manhwa market is new. Over all volumes, 80.2% are dated [M].
- **LoC.** Year precision, type `published`, **only** from a single-volume record's `008` date1 (date type `s`/`t`), and **only when `leader/17` is neither `5` nor `8`**.
  - On a CIP (`8`) or ECIP-preliminary (`5`) record, date1 is a pre-publication estimate. This is DNB's announcement case: such a volume is dated only through a `263` YYMM, as `projected` at month precision (never `1111`), under DNB's 12-month expiry; otherwise it ships undated.
  - **A set record's `264 $c 2021-` / `008 m2021` never dates a volume.**
  - `955` receipt dates are never used.
- **BnF.** `210`/`214 $d` year, precision year, type `published` (100% of KR records) [M]. A `100 $a` date that disagrees with it is ignored.
- **Open Library** (existing, EN and FR by ISBN): day dates and pages.
  - **Coverage for this segment is low:** on today's EN corpus, 979-prefixed ISBNs (almost every post-2022 Ize / Seven Seas volume) have an Open Library day date on 85 of 3,512 volumes (2.4%), any Open Library claim on 41%, and pages on 21% [M]. 978-prefixed ISBNs reach 23% day dates [M].
  - Expect most new English volumes to ship undated or year-dated. The existing 979 volumes of EN KR/CN lines are 104/104 day-dated only because Wikipedia dates them [M].
- **Resolve.** The existing tier2/resolve rule, extended to `loc` and `bnf`: a bare library year never beats a finer date it disagrees with.

**Enrichment hazard (must be fixed first).** `enrich_openlibrary` batches the **sorted** market ISBN list 50 per URL, the same shape as the openBD gotcha in HANDOFF.
- The hazard is already live on today's corpus. Locally, only 64 of the 515 current EN batch URLs and 76 of the 337 FR batch URLs are cached **before** anything is added [M]. The local cache is not CI's.
- This round's ISBNs make it worse. The 436 new EN ISBNs leave 5 of those 64 cached EN batch URLs intact. The 1,087 new FR ISBNs leave 45 of 358 FR batch URLs cached [M, offline].
- The cache that matters is CI's seed. Size the burst against the seed before the first build.
- Online, every re-keyed batch is an Open Library request on an API that asks bulk users to use the dumps. Offline, a re-keyed batch silently drops dates.
- Fix: batch the new round's ISBNs **separately** (their own sorted list, their own URLs) so existing batches keep their URLs. Better, per-ISBN cache keys. Either way, before this round's first build.
- Likewise `enrich_bnf` would issue one SRU call per new FR volume (~1,100 [E]) for data the BnF line source already has. Skip volumes whose line source is `bnf`.

## 13. Gates

**Contract** (`export/test_artifact.py`, new rules):
- Every `loc` claim is `us_gov_pd`, and its source record's `040 $a` is `DLC`. A staging table `loc_member(lccn, f040a, line_key, volume_id, fate)` makes this checkable.
- No `loc` claim from a `520`, `856` or `955` field.
- No `loc` date on a volume that came from a set record.
- No `loc` `published` date from a record at encoding level `5` or `8`. Such a record dates a volume only as `projected` (from `263`).
- `loc`, `bnf` and `dnb` published dates are year precision; projected dates are month precision and never override published or on_sale.
- No volume dated from a `263 1111`.
- **Every library-created work has at least one line with explicit KR/CN origin and at least one comic line.** No library-created work has a JP-market line.
- No `novel` line in a work without a comic line.
- The existing ids survive:
  - the EN/FR/DE lines of the 54 KR/CN works (a fixture of their ids, like `de_lines_pre_dnb.json`);
  - the 3 library-fixture lines.
- The linker fixture (§10): 0 wrong on `must_link` / `must_not_link`.
- `clean_claim` contains the `loc` claims (the view lists `us_gov_pd`).

**Canary.** The LoC control query returns 1 DLC record, otherwise the stage fails. A result set counts as complete only when its distinct records equal `numberOfRecords`.

**Measure** (`export/measure_library.py`, set after the first real build; values below are from the spike):

| Market | Line floor | Volume floor | Other floors |
|---|---|---|---|
| DE KR/CN (spike: 396 lines / 1,644 volumes, minus review) | 300 | 1,250 | deposited-year coverage ≥ 95% (spike: 100%); page coverage ≥ 90% (spike: 97.5%); announced-only volumes reported, not gated |
| FR KR/CN (spike: 203 / 1,278) | 160 | 1,000 | year coverage ≥ 95%; pages reported, not gated (64%) |
| EN KR/CN (spike: 74 + existing) | 60 new | — | date coverage reported only (Open Library-bound, §12) |

- Library works: count reported; at least 72 with an English line.
- The idempotent reload gives the same ids (`same_ids` pattern).
- The library replay, including Solo Leveling ×2 and TBATE, is unchanged.

**The existing German gates must not blur.**
- `measure_de`'s link rate today is 1,455 exported / 4,340 DNB lines = 33.5% [M], against a 30% floor.
- If the ~396 KR/CN lines join `dnb_line` with only the ~23 linked ones counted as exported, the rate drops to about 31.2% [E]. That still passes, but only by about a point, and it mixes two populations.
- KR/CN lines therefore get their own staging (`krcn_line` / `krcn_member`, one table set for all three sources) and their own meta key (`krcn_lines`). The German JP gates stay exactly as they are.

**The `fold()` change must not move the German JP round.** `dnb_link.fold` also feeds `build_dnb` cluster keys, and a re-cluster can change a line's lowest member IDN, and with it the line id. Two gates:
- `fold()` must return byte-identical output for every string with no Hangul, checked over all catalogue strings plus all DNB strings (the narrow-fold method).
- A replay of the German JP build must show 0 changed `dnb_line` keys and 0 changed tiers.

The carried-id gate (7b) already covers every market and every entity; its caps apply as they are. **Watch:** a first KR/CN build moves no carried id, but a refresh that re-clusters DE KR/CN lines counts toward the retired-line cap of 10.

## 14. Mangarr follow-ups (a separate Mangarr task; not implemented here)

Read on 2026-09-27; line numbers are as of that read. Nothing in Mangarr filters on `medium = 'manga'`, and no SQL filters `medium`.

**Medium: no change needed.** `GcdMetadataService.IsLightNovel` (`medium.Contains("novel") || medium == "artbook"`, L271-276) is the only medium test. `manhwa` / `manhua` rows count as manga everywhere:
- `Rank` L237-242
- `EditionResolver.Options` L177-178 and `PickSibling`
- Collections `collectionCards.js` L11-19

`novel` rows count as light novels. The Manga vs Light Novels tab comes from the `~ln` foreign id, not from `medium`.

**Follow-ups needed:**
1. **M1 — find a line by `anilist_id`.** There is no `WHERE anilist_id` anywhere. An AniList id never finds a line; the artifact's id only picks the AniList entry *from* an English hint line (`MangaSeriesMetadataProvider` L1844-1846).
   - Add `FindSeriesByAnilistId` for any language, preferring en and `is_main`.
   - Use it in `GetSeries` (Provider L640-652).
   - Read `anilist_id` from any line of the work via `tome_work_id`. The comment at L1842 ("null on every line today") is stale.
2. **M2 — works without an English line.**
   - `Rank` keeps only `language == "en"` lines (L238).
   - With the default English-only Preferred Edition chain, `EditionRequestFor` returns null (`BookInfoProxy` L224-226). The series then falls back to live sources with `TomeLineId = null` (Provider L1464), and a light novel gets `NotInCatalogue` (L680-689).
   - This needs a policy: fall back to the work's `is_main` line in the chain's languages, or in all languages. The ~448 DE/FR-only works are unreachable until it lands. `EditionResolver` L131-141 should also resolve an anchorless work by `anilist_id` / `tome_work_id`, not only by title.
3. **M3 — `IsCounterpart` without `orig_series_id`.** It returns false (`EditionResolver` L234-238).
   - New works have no KR/CN original line, so `pick_origin` (`to_mangarr.py`) finds no ORIGIN market and every line's `orig_series_id` is NULL.
   - Fall back to `is_main` or the work's origin by `country`.
   - Alternatively, OpenTome could ingest KR originals (§16).
4. **M4 — AniList `countryOfOrigin`.** Add it to `MediaFields` (`AniListService.cs` L107-109) and `AniListSeries`. KR/CN `MANGA` entries are accepted today unchecked. Use it for tagging and default naming.
5. **M5 — ko/zh edition support.**
   - `EditionLanguages.VolumeLabel` (L83-95; "N권", "第N卷") and `EditionVolumeTokens` (L55-80; fr/de/ja only).
   - `EditionDisplayName` L549 and `BuildEditionAltTitles` L395 (native only for ja).
   - `ReleaseLanguageParser` L45-66: an untagged Hangul release counts as English.
   - `Subtitles.cs` L263/288.
6. **M6 — "japaneseTotal" / Coming Soon** (Provider L754-773). For manhwa, the "original total" is the Korean print count, or a MangaDex chapter-like number. Rename it, and guard when AniList `volumes` is null (typical for webtoons).
7. **M7 — Collections.** `CollectionController` L100/132 uses English-only `Rank`, so no collection forms for a work without an English line.
8. **M8 — tests.** Nothing tests `medium` = manhwa/manhua. Add cases to `GcdRankFixture` (a de-only work), `EditionResolverFixture` (ko origin; `anilist_id` on a non-en line), and `MangaSeriesMetadataProviderFixture`.

OpenTome does not emit `webtoon` (§7), so the webtoon-vs-print ranking question the Mangarr read raised does not arise.

## 15. Open points for Nick (with recommendations)

The first three block shipping.

1. **A library work later covered by Wikipedia** (§9). This is a public-contract question.
   - Recommendation: the adoption rule. The library id stays public and no redirect is written, which keeps the older id.
2. **The review path.** The linker, containment guard, JP guard and Ize-medium rules send lines to review files (`build/krcn-review.tsv`): at least 1 DE + 2 FR + 15 Ize + containment hits [M], plus German-titled duplicates like *Athanasia* [E: tens].
   - As with `dnb-review.tsv`, there is no correction type for "link this library line" yet.
   - Recommendation: add `corrections/lines.json` `link_work` (library line key → work id) this round. Without it, a reviewed line can never ship.
3. **AniList and reachability for works without an English line** (§11, Mangarr M2): about 448 works.
   - Recommendation: bind English lines only this round, which is the existing practice.
   - Schedule Mangarr M1/M2 as the follow-up that makes these works reachable. Until then they serve only users whose Preferred Edition chain includes de/fr, and only by title.
4. **Confirm the measured cost of decision 2** (§2). The DLC-only rule excludes 73 new English lines / 218 volumes, including the WEBTOON Unscrolled (Tower of God, Noblesse), Inklore, Seven Seas and Drawn & Quarterly lines.
   - Recommendation: keep the rule. Fill important gaps with per-title `corrections/*.json` entries that cite the publisher page (facts, not fetched). Say plainly in the README that English KR/CN coverage is Ize/Yen-heavy.
5. **Scope of pre-2015 French manhwa** (Tokebi / Saphira / Samji: 137 of 203 FR lines, mostly long-finished runs) [M].
   - Recommendation: include them. They are real print lines and cost nothing extra.

## 16. Out of scope

- The National Library of Korea (decision 3).
- **Korean- and Chinese-language originals held by LoC:** 337 Korean and 95 Chinese records in the channels paged [M], many DLC gifts from the Publication Industry Promotion Agency of Korea. A later round could build KR/CN origin lines from them, which would also give new works an `orig_series_id` (Mangarr M3).
- Non-DLC LoC records. Publisher sites (cited only). MangaUpdates (worklist only; not stored).
- Digital-only webtoons.
- A `webtoon` medium value.
- Retagging existing Wikipedia KR lines tagged `manga`: Solo Leveling DE / ko `manga`, I Love Amy, King of Hell, … This is `corrections/lines.json` medium overrides, one entry each, and not re-keying.
- Splitting the 5 mixed JP/KR works (Wind Breaker, Pandemonium, …). This is a separate work-identity fix: split and redirect.
- French manhua beyond the `101 $c` filter (Xiao Pan: 35 of 39 records carry no `101 $c`).

## 17. Scale and yield

| Market / source | Records | Lines | Volumes | To existing works | New-work lines | ISBN / date / pages |
|---|---|---|---|---|---|---|
| DE / DNB | 4,959 [M] | 396 [M] | 1,644 [M] | 23 lines (17 works) [M] | 355 comic (1,433 vols) + 16 novel (51) [M] | 100% / 80.2% year / 97.5% [M] |
| FR / BnF | 1,304 KR/CN of 4,285 [M] | 203 [M] | 1,278 [M] | 21 lines (18 works) [M] | 180 (1,104 vols) [M] | 89% / 100% year / 64% [M] |
| EN / LoC (DLC only) | 214 DLC of 324 translated KR/CN-origin records; 54 Ize (all DLC) [M] | 85 [M] | ~470 [M] | 11 lines (ISBN fill: 107/235) [M] | 74 (386 vols; 35 of them medium-unresolved) [M] | 100% / year on single-volume records only / 29% of comic records [M] |
| **New works** | — | — | — | — | **~520 [E]** (72 with an EN line, ~448 DE/FR-only) | — |

- Existing KR/CN works touched: DE 17, FR 18, EN 9 (distinct works) [M].
- After review and the containment guard, expect roughly 400–480 new works, 550–620 new lines and 3,000–3,300 new volumes [E].
- The catalogue's DE market grows by about 25% in lines. The first EN/FR KR/CN lines outside Wikipedia appear.

## 18. Risks

- **LoC gateway diagnostics** (31% of requests) [M]. A permanently failing page (one did [M]) blocks a result set. The mitigations are the degraded-refresh rule and a **complete CI cache seed** (§3); a first run must retry until complete, or fail.
- **ISBN-stem enumeration is incomplete by construction.** New imprints and registrant blocks appear (Seven Seas moved to 979-8-88843 / 979-8-89160, which LoC barely holds). The subject channels are the safety net. Report per-channel counts in `build/loc-report.json` so a new stem is noticed.
- **Level-5 ECIP records** lack origin and class (40 of 55 Ize) [M]. The medium depends on cross-market evidence or a later LoC upgrade.
- **False new works** (German/French titles of existing works; *Athanasia*) [M]. Ids are permanent, so every false new work becomes a merge plus a redirect later. The containment guard and review file are the defence. Precision is not yet measured: build a labelled sample of ~50 new-work clusters before the first publish, as DNB's labelled set did.
- **Romanisation mismatch** between libraries (§10): cross-market clustering leans on English titles.
- **Open Library batch re-key** (§12) and a BnF per-ISBN burst: fix before the first build.
- **Dates:** EN mostly undated or year-only. A consumer that treats undated as missing will search for them (the same caveat as the 879 undated DE volumes).
- **Mixed JP/KR works** already in the catalogue (Wind Breaker) can attract KR lines to a JP-anchored work. The JP guard sends these to review, but the existing mixed work stays mixed until split.
- **The legal basis of the LoC rule is Nick's inference** (17 USC §105), not a published LoC licence. Record it as such in legal-position.md.

## Rulings (controller, 2026-09-27 — Nick: "Continue with your recs")

- **R1 Work ids.** A library-created KR/CN work keeps its id when Wikipedia later covers the same work (adopt; no redirect), per the id-scheme's "keep the older id".
- **R2 Review path.** Add a `link_work` correction type in this round, so a reviewed low/ambiguous line can ship.
- **R3 AniList binding.** Bind new works that have an English line (as today). Works with no English line wait for the Mangarr consumer round (find-by-anilist-id, non-English-only works), which follows this round; their binding is added then.
- **R4 LoC scope (controller ruling, stricter than Nick's approval — he approved "LoC records are public domain"; the DLC-only limit came from the source research).** Build with LoC-created records only (040 $a DLC); the parser reads both record kinds and a single switch includes non-DLC records limited to bare facts (ISBN, volume number, title, year) if Nick chooses. Cost of DLC-only: 73 English lines / 218 volumes (WEBTOON Unscrolled incl. Tower of God and Noblesse, Inklore, Seven Seas) wait for a later licence review.
- **R5 French backlist.** Pre-2015 French manhwa (137 of 203 FR lines) are included.
- **Pre-build items** (plan tasks): regenerate the CI cache seed from the full local `.cache`; batch the new ISBNs separately in the Open Library enrichment; the Hangul fold() change leaves every non-Hangul key byte-identical, gated by a German JP replay.
- **Sequence:** this OpenTome round → publish → Mangarr consumer round (find line by anilist_id, non-English-only works, IsCounterpart without orig_series_id, AniList countryOfOrigin, KR/CN volume tokens + Hangul, japaneseTotal naming, Collections) → AniList binding for non-English-only works.
- **R6 Hold works with no English line (controller, 2026-09-27, after review).** ~425 DE-only / FR-only candidate works [E] cannot be joined across markets reliably (German vs French titles, romanisation mismatch) and ids are a public contract — a wrong split becomes a published merge + redirect. This round builds and gates them but EXPORTS only: lines linked to existing works (DE 23 / FR 21 / EN 11 [M]) and new works that have an English line (~72 [E]) with their DE/FR siblings. The rest go to a hold file (`build/krcn-held.tsv`, like dnb-review.tsv) until the Mangarr consumer round + AniList binding can join them (DNB decision-1 precedent). Mangarr cannot reach them before that round anyway.
- **R7 LoC paging.** The 42 "SRU errors" [M] are all diagnostic 61 "First record position out of range" at deep start positions although numberOfRecords is larger — a server-side reachable-window limit, not flakiness. The client slices queries (narrower ISBN prefixes / subject+year) until each set is fully pageable, asserts distinct records == announced count per slice (DNB-style completeness), caches whole sets only, and has a degraded mode (cached set, else fail the stage) before CI depends on it.
