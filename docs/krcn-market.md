# KR/CN coverage — Korean and Chinese licensed print editions (method and spike, 2026-09-27)

Design: `docs/krcn-design.md`. This file is the market-facing companion, in the shape of
`docs/german-market.md`: what the sources are, how lines and works are built and gated, and
the numbers — first the pre-implementation spike below, later (plan step C4) the first real
build.

## The three sources and their channels

**DNB (German).** The existing German-market machinery (`docs/german-market.md`), with two
new channels and the origin rule inverted: `spo=kor and bbg=A*` and `spo=chi and bbg=A*`,
plus the existing imprint channel (`IMPRINT_Q`) split between the JP and KR/CN rounds by
origin statement or keyword. Parents come from `773 $w`, sliced by `jhr` as today.

**LoC (English), `http://lx2.loc.gov:210/lcdb`.** Enumerated by ISBN stem (the registrants
already on the carry's EN KR/CN lines: Ize/Yen, Tokyopop, Seven Seas, WEBTOON Unscrolled, …)
plus subject channels (`dc.subject="Comic books, strips, etc.--Korea"` and its siblings). Only
records LoC itself created (`040 $a DLC`) are kept (R4); a non-DLC record is not read as a
twin, a classification hint, or linker evidence. Pages at 100 → 50 → 25 with a slicing ladder
on SRU diagnostic 61, whole-set caching, and a canary (`bath.isbn=9781975319434`) that must
return exactly one DLC record every run.

**BnF (French), `https://catalogue.bnf.fr/api/SRU`.** An allowlist of publisher channels
(Tokebi, Kbooks, Saphira, Samji, Clair de lune, Kotoon, Ki-oon, Pika), each filtered on
`101 $c kor`/`chi`. Adding an imprint is a one-line code change plus a count probe, not a
recurring manual step. Chinese in French is a known gap: `101 $c` is mostly absent on the one
Chinese-manhua imprint found (Xiao Pan).

All three share the DNB access pattern: serial requests ≥ 3 s apart, a descriptive
User-Agent, a whole-set disk cache, a netlog per source, `LOC_OFFLINE`/`BNF_OFFLINE`, one
Retry-After wait then a stop on a second 429/503, and `LOC_REFRESH_DAYS`/`BNF_REFRESH_DAYS`
(28 days) refresh windows on the weekly CI cron.

## Scope rules

- **Medium.** `manhwa` (Korean origin), `manhua` (Chinese/Taiwanese origin), `novel` (prose).
  No `webtoon` value is introduced. A `novel` line exports only under a work that also has a
  comic line; no work is ever created from prose alone.
- **Explicit origin required to create a work.** `041 $h` / `101 $c` kor/chi, or a translation
  statement — an imprint rule alone (Ize level-5, DNB's no-`041` imprint records) is not
  enough.
- **The containment guard.** No existing KR/CN work's title key may contain, or be contained
  in, a candidate line's key; no existing work may share its original-title key. Otherwise the
  line goes to review, never a new work.
- **The JP guard.** A KR/CN line whose best candidate is a work with a JP line and no KR/CN
  line goes to review, never a link.
- **DLC-only (R4).** No non-DLC LoC record is used, for any purpose. Measured cost: 73 English
  lines / 218 volumes excluded, mostly WEBTOON Unscrolled, Inklore, Seven Seas and Tokyopop.
- **Out of scope this round** (full list: `docs/krcn-design.md` §16): the National Library of
  Korea, non-DLC LoC records, Korean/Chinese-language originals held by LoC, relay
  translations (German editions of KR/CN works translated from Japanese), digital-only
  webtoons, French manhua beyond the `101 $c` filter, and splitting the catalogue's existing
  mixed JP/KR works.

## Line keys and identity

Natural keys come from source data only, as with DNB, so relinking a line never re-keys it:
`dnb:<parent or lowest member IDN>`, `loc:<lowest member LCCN>` (LCCN-normalised),
`bnf:<lowest member ark>` (ark-ordered). A key is minted into an `rl_` id only when no carried
line matches it, so a later stem, channel or slice that finds an older record never re-keys a
published line.

- **The carry lookup before minting.** The carry holds no LCCN or ark, so member overlap is
  judged by what each member put into the carry — its volume ISBNs, or, for a member without
  an ISBN, its volume number within a carried line of the same source and work. A built line
  whose members hold a strict majority of a carried line's volumes takes that line's `tome_id`.
- **Adoption.** When a Wikipedia line or work later covers one that shipped under a library
  id, the library id is kept (R1), and adoption runs before stage 4c and 7b: it moves the
  staged rows and remaps their volumes onto the surviving public id. A published line or work
  is never demoted.
- **Cross-market clustering.** Unlinked lines of all three markets cluster by folded English
  title and by Hangul/Hanzi keys (the `fold()` change: NFC after the combining-mark strip,
  Hangul added to the kept range, a 2-syllable minimum admitted for Hangul-only keys). A
  romanised original title keys only within one library — DNB syllable-splits, LoC uses
  ALA-LC, BnF usually carries none.

## The R6 hold

A cluster that would otherwise qualify to create a new library work but has no English line is
built, gated and written to `build/krcn-held.tsv` — it is not exported, and gets no `tome_id`,
`tome_work_id` or `id_map` integer anywhere. Cross-market joins across DE/FR alone are not
reliable enough for a permanent id (romanisation mismatch, no shared title), so held clusters
wait for the Mangarr consumer round plus AniList binding for non-English-only works. A
published line or work is never demoted to held.

## The files

- **`build/krcn-review.tsv`** — low/ambiguous linker ties, containment-guard hits, duplicate
  numbers, the JP guard, Ize level-5 records still medium-unresolved, and writer-only author
  ties: one row per KR/CN line that needs a human look.
- **`build/krcn-held.tsv`** — every R6-held cluster: its lines, member keys, the reason it
  wasn't exported, and its candidate title keys.
- **`build/krcn-new-works.tsv`** — every new library work the build would create, for the
  fixture label pass (plan C5): `must_create`, or `must_not_create` with the existing work or
  the reason.
- **`build/krcn-report.json`** — the run's `gate` lists (blocking and informational), the
  `krcn:stats` summary, and the id ledger (kept / taken / `taken_weak` / left / deferred).
- **`build/loc-report.json`** — per-channel LoC counts and `loc_degraded` state, so a new
  imprint or registrant block the ISBN-stem enumeration misses is noticed.

## The gates

- **Contract** (`export/test_artifact.py`): every `loc` claim is `us_gov_pd` from a `040 $a
  DLC` record; no claim from `520`/`856`/`955`; `loc` `source_url` is `https://lccn.loc.gov/…`,
  `bnf` line-source `source_url` is an ark URL; no cover or `856`-derived field from
  `dnb`/`loc`/`bnf`; every library-created work has an explicit-origin comic line and no
  JP-market line; R6 (no held cluster holds an id anywhere); the flood gate
  (`MAX_NEW_LIBRARY_WORKS`); `dnb_line`/`krcn_line` key disjointness; the existing-id
  fixtures; the linker fixture (0 wrong on `must_link`/`must_not_link`); the new-work fixture
  (0 wrong, labelled before the first publish).
- **Canary.** The LoC control query must return exactly one DLC record, every run, or the
  stage fails.
- **Measure** (`export/measure_library.py`): staged floors (what the build *built*, `krcn_line`
  including held/review lines) are set now, at ~75–80% of the spike below. Exported floors
  (what the artifact *ships*) are provisional until plan step C4 sets them at ~85% of the
  first real build's measurement — see "First build" below.
- **The existing German gates must not blur.** KR/CN lines have their own staging
  (`krcn_line`/`krcn_member`) and their own meta key (`krcn_lines`), so the German JP
  link-rate floor is never diluted by mixing the two populations.
- **The `fold()` change must not move the German JP round.** `fold()` must return
  byte-identical output for every string with no Hangul, and a replay of the German JP build
  must show 0 changed `dnb_line` keys, tiers, roles or exported flags.

## Spike (2026-09-27) [spike]

Pre-implementation feasibility numbers, from the design spec's spike (`docs/krcn-design.md`
§17) — not a real build. `[M]` = measured on the spike's cached data, `[E]` = estimated.

**Built** (staged in `krcn_line`, held and review lines included):

| Market / source | Records | Lines | Volumes | To existing works | New-work lines | ISBN / date / pages |
|---|---|---|---|---|---|---|
| DE / DNB | 4,959 [M] | 396 [M] | 1,644 [M] | 23 lines (17 works) [M] | 355 comic (1,433 vols) + 16 novel (51) [M] | 100% / 80.2% year / 97.5% [M] |
| FR / BnF | 1,304 KR/CN of 4,285 [M] | 203 [M] | 1,278 [M] | 21 lines (18 works) [M] | 180 (1,104 vols) [M] | 89% / 100% year / 64% [M] |
| EN / LoC (DLC only) | 214 DLC of 324 translated KR/CN-origin records; 54 Ize (all DLC) [M] | 85 [M] | ~470 [M] | 11 lines (ISBN fill: 107/235) [M] | 74 (386 vols; 35 of them medium-unresolved) [M] | 100% / year on single-volume records only / 29% of comic records [M] |

**Exported and held under R6** [E, provisional; spike clustering, before the explicit-origin
check on EN comic lines and before the containment guard on new-work clusters]:

| | Works | DE lines / vols | FR lines / vols | EN lines / vols |
|---|---:|---|---|---|
| Lines to existing works | — | 23 / 150 | 21 / 166 | 11 / 87 |
| New works, exported | 57 | 30 / 171 | 8 / 25 | 59 / 311 |
| **Exported total** | **57 new** | **53 / 321** | **29 / 191** | **70 / 398** |
| Held (`krcn-held.tsv`) | 448 | 342 / 1,317 | 174 / 1,087 | — |
| Review (Ize level 5, §7) | — | — | — | 15 / 75 |

- Existing KR/CN works touched: DE 17, FR 18, EN 9 (distinct works) [M].
- New lines in the artifact [E]: DE about 52 (the linked lines less the Solo Leveling merge, plus the siblings), about 3.6% of today's 1,459 DE lines; FR about
  19 (10 of the 21 linked lines attach to existing FR lines); EN about 60 (10 of the 11 linked
  lines attach).
- The first EN/FR KR/CN lines outside Wikipedia appear.

## First build

Filled from the first full build (plan C4).
