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

## The R6 hold (lifted 2026-10-01)

From 2026-09-27 to 2026-10-01 a cluster that would otherwise qualify to create a new library work but had
no English line was built, gated and written to `build/krcn-held.tsv`, never exported. Mangarr 10.0.0.857
adds and binds works without an English line, so the lift round creates them: the anchor is the comic line
with the lowest key in any market (an FR+DE cluster anchors on its French line). A cluster of novels alone
is still held (`novel-without-comic`); `build/krcn-held.tsv` is expected to be empty. A published line or
work is never demoted to held.

## The files

- **`build/krcn-review.tsv`** — low/ambiguous linker ties, containment-guard hits, duplicate
  numbers, the JP guard, Ize level-5 records still medium-unresolved, and writer-only author
  ties: one row per KR/CN line that needs a human look.
- **`build/krcn-held.tsv`** — every R6-held cluster: its lines, member keys, the reason it
  wasn't exported, and its candidate title keys.
- **`build/krcn-new-works.tsv`** — every new library work the build would create, for the
  fixture label pass (plan C5): `must_create`, or `must_not_create` with the existing work or
  the reason.
- **`build/krcn-duplicates.tsv`** — every work created in the build whose title / native / original keys
  are close (difflib ≥ 0.8) to another created or existing work's, and (from stage 8a) every created work
  whose AniList id another work's line has. Rows at ≥ 0.9 and every AniList row need a correction or a
  verdict in `export/fixtures/krcn_lift_duplicates_reviewed.tsv` (`export/test_artifact.py`).
- **`build/krcn-anilist-bindings.tsv`** — every AniList id stage 8a gave a KR/CN work without an English
  comic line, read in full before a publish.
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

Filled from the first full build (plan C4), 2026-09-29, branch `krcn`, on this workstation
(`build/krcn-first-build.log`, `build/krcn-measure.log`). The carry was the live release,
`opentome` sha256 `99e35d4d…`. AniList (8a) had not run yet: that is C6, in CI.

**Staged** (`krcn_line`, all roles). Lines, with volumes in brackets:

| Market | Exported | linked | merged | new_work | held | review | unlinked |
|---|---:|---:|---:|---:|---:|---:|---:|
| DE | 44 (284) | 19 (127) | 1 (12) | 24 (145) | 291 (1,123) | 31 (112) | 16 (44) |
| FR | 24 (149) | 8 (43) | 11 (90) | 5 (16) | 152 (837) | 20 (179) | 0 |
| EN | 69 (396) | — | 14 (105) | 55 (291) | 1 (3) | 38 (108) | 73 (74) |

The build staged 759 lines in total. Another 14 DNB sets were deferred to the German JP round (P25).

**Works.** This build created 53 works, froze 0, and exported 53 library works (`meta.krcn_ids`: 53 works, 111 line ids).
There are 408 held clusters (R6: 444 lines, 1,963 volumes) and 89 lines in review. The review reasons are:
no-class-signal 18, ize-medium 18, duplicate_numbers 17, containment 16, writer_only 11, low 3,
linked-sibling-key 3, fragment 2, and 1 other. **Adopted ids: 0**, as expected on a first build.

**Volumes.** Member records by fate: created 608, attached 204, line_held 1,975, line_review 421,
line_unlinked 118, dropped_duplicate_number 40, dropped_unnumbered 24, held_future 21, and
dropped_number_clash 1.

**Coverage of exported volumes after stage 4:**

| Market | Volumes | Dated | Paged |
|---|---:|---:|---:|
| DE | 268 | 222 (82.8%) | 266 (99.3%) |
| FR | 149 | 149 (100%) | 108 (72.5%) |
| EN | 395 | 107 (27.1%) | 9 (2.3%) |

EN is thin for a structural reason. LoC gives a date and extent only on single-volume records, and 184 of the 396
EN member records are announced-only (CIP) records. Open Library (stage 4) raised the dated EN volumes from 10 to 107.

**Requests.**
- LoC: 3,742 distinct records, from run 36561675299 on a GitHub runner (177 live requests,
  `degraded=None`). One read per set (the C0 ruling, option 1) left 52 positions unconfirmed across 14
  sets (`.cache/loc-dups.json`). This workstation's IP is blocked by lx2.loc.gov, so the build read LoC
  from the cache (`LOC_OFFLINE=1`, meta `loc:offline`: unreachable, 0 stale sets). The whole round
  used 395 of the 400-request LoC budget.
- DNB, BnF: 0 live requests in the build (cached by Tasks 7 and 9).
- Stage 4: Open Library needed 6 EN and 2 FR batch requests. The other ISBNs were already cached per ISBN.

**Gates on this build.**
- German JP round: `dnb_line` equals the pre-round snapshot (4,340 keys; 0 added, removed or changed).
- Library measure: 49/49.
- Carried ids: 0 lost, 261 redirected, 0 of 500 moved.
- KR/CN reload: same ids (111/111).
- Library-fixture lines are targeted only by `merged` lines.

**Exported floors** (`export/measure_library.py`) are 85% of the counts above, rounded down:

| | Lines | Volumes |
|---|---:|---:|
| DE | 37 | 241 |
| FR | 20 | 126 |
| EN | 58 | 336 |

`KRCN_MIN_WORKS` = 45.

## Lift build

Built 2026-10-01 on this workstation from branch `krcn-lift` (through the Task 14 commit `c2db3ae`), carry = the live
`opentome-2026-09-29` artifact (sha256 `c91484c4…`, catalogue run 44), `LOC_OFFLINE=1 LOC_UNREACHABLE=1`.
Logs: `build/lift-local/krcn-lift-build2.log`, `build/lift-local/measure-floors.log`.

**Staged** (`krcn_line`), lines with volumes in brackets:

| Market | Exported | linked | merged | new_work | review | unlinked | absorbed | held |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| DE | 327 (1,399) | 24 (170) | 1 (12) | 302 (1,217) | 32 (116) | 15 (39) | 8 (9) | 0 |
| FR | 176 (986) | 12 (98) | 11 (90) | 153 (798) | 20 (179) | 0 | 0 | 0 |
| EN | 70 (399) | 0 | 14 (105) | 56 (294) | 39 (109) | 72 (73) | 0 | 0 |

The build staged 759 lines in total; another 14 DNB sets were deferred to the German JP round (P25). The
`absorbed` lines are the DE announcements the date rule holds back (no exportable volume, so no work is written).

**Works.** Created 371, frozen 53; held clusters 0 (`novel-without-comic` only, none left in this build). The lift
input's 444 held lines: 371 works created from them; 0 dropped. Reviewer corrections: 22 `cluster_with`
(Bibi included), 0 `review`, 9 `link_work` (Athanasia included); 31 non-comment rows in the duplicate-verdict
fixture (the header row plus 30 `not-a-duplicate` verdicts).

**AniList (8a, families krcn-KR / krcn-CN / krcn-TW).** 369 works considered, 239 bound (263 lines written),
every binding read (`build/krcn-anilist-bindings.tsv`); 5 new pins (38 in `corrections/anilist.json`).

**Exported floors** (`export/measure_library.py`), `round(0.85 × measured)`:

| | Lines | Volumes |
|---|---:|---:|
| DE | 278 (measured 327) | 1,189 (measured 1,399) |
| FR | 150 (measured 176) | 838 (measured 986) |
| EN | 58 (unchanged) | 336 (unchanged) |

`KRCN_MIN_WORKS` = 360 (measured 424 library works exported). Library measure 49/49; German JP round
unchanged (meta `dnb_lines` and `build/dnb-review.tsv` equal to the carry's).

Published 2026-10-02 (UTC) as `opentome-2026-10-02` (sha256 `9f6ceec7…`; build-only run 36943425972, publish run
36945152362).
