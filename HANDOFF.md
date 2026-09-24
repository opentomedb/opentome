# HANDOFF — OpenTome

_Last updated: 2026-09-24_

## 2026-09-24 — branch `roxy-en`: the English Roxy Gets Serious line, and an `origin_line` correction

Closes the one library measure-gate miss HANDOFF.md has been carrying since 2026-09-04
(v2.1/v2.2: *Mushoku Tensei: Roxy Gets Serious* has no English line because the English
Wikipedia article has no section for it). Not merged from here -- Nick's gate.

`corrections/lines.json` gains the English Seven Seas edition (12 volumes, EN manga,
`w_179929c7bc15`), read off the publisher's series page by the maintainer on 2026-09-24
with every ISBN-13 check digit validated. Adding it exposed a real defect, not just a
missing row: Mushoku Tensei's JP manga has TWO lines under the same (work, medium) --
the main serial and this Roxy spin-off -- and the JP Roxy line's own `line_name` claim
is not Japanese at all, it's the French string cross-parsed from the FR Wikipedia table
("Mushoku Tensei : Les Aventures de Roxy", the same string the FR Roxy line carries,
which is why FR pairs with JP correctly today). `export/to_mangarr.py`'s `origin_line()`
pairs a licensed line to its origin-market counterpart by an EXACT name-string match,
so the new EN line (named "Mushoku Tensei: Roxy Gets Serious", per Nick's instruction --
no reason to invent a mismatched key) cannot match it, and without a fix silently falls
back to the JP work's MAIN manga line: the new line would have read 12 of 25 volumes
against a still-running series and exported `stalled` instead of `completed`.

Fix, not a workaround: `corrections/lines.json` whole-edition entries gain an optional
`origin_line` key naming the exact origin-market line id. `tier2/corrections.py` validates
it (same work, same medium, market in `JP KR CN TW`, existence -- refusing a stale/wrong
target the same way the medium/market override shapes already do) and uses it for BOTH
`composition.ref_line_id` (in place of the same naive "any origin-market line for this
work+medium" query, which has the identical multi-line ambiguity) and a new `release_line`
claim (`field='origin_line'`) that `export/to_mangarr.py`'s `origin_line()` now checks
before falling back to the name-key match / main-line default. See `corrections/README.md`
for the full writeup. TDD: `tier0/test_parser.py` (apply + all four validation failures),
`tier2/test_corrections_check.py` (5 new cases against the published-artifact shape),
`export/test_to_mangarr.py` (an end-to-end fixture: two same-work JP lines, one pinned EN
line resolving to the spin-off, one unpinned EN line reproducing the defect against the
main line -- proves the fix without disturbing the unpinned default).

Verified OFFLINE, zero network (`find .cache -type f -newer <marker>` empty): a full
`ANILIST_OFFLINE=1 bash tier0/rebuild_all.sh` run against the warm cache. Stage 5b: "line
corrections applied 3 (39 volumes)" (the two pre-existing entries plus this one's 12).
Stage 7 audit: 0 outstanding defects. Stage 8a aborted as expected on `OfflineMiss` for
three uncached AniList search terms -- 'Mushoku Tensei: Roxy Gets Serious' (new, expected)
plus two unrelated pre-existing gaps ('Hoshin Engi' arc terms, nothing to do with this
change). Stage 8c (`export/test_artifact.py`) against the resulting `manga-metadata.sqlite.new`:
every rule passes except "EN lines without anilist_id" (2,523/2,523 unresolved -- expected,
since 8a never ran and wrote no ids at all, not specific to Roxy). Stage 8d (measure gate):
**49/49 matched, 0 coverage failures** (was 48/49; diffed against the pre-round `measure.log`,
only the Roxy row changed). Direct query: the new line's `orig_series_id` resolves to
`rl_e5f7e5f4fab0` (gcd_series_id 64852282, the JP Roxy line) -- not `rl_51690cde3090` (the
JP main manga line, gcd_series_id 2142409694) -- and its status exports `completed`, not
`stalled`. `tier2/corrections.py --check` against the new artifact: ok, 3 line / 3 medium /
1 market / 27 alias / 1 excluded entries resolve.

Next: a maintainer merges `roxy-en`, and the next `publish=true` dispatch (which also runs
a real, online `resolve_anilist.py`) ships both this line and its AniList id together.

## 2026-09-23 — cleanup-0923: exclude Walking Dead, curated alias removals, Denma market fix

Three corrections, TDD'd on branch `cleanup-0923` (not merged/published from here --
Nick's gate): (1) `corrections/excluded.json` (new file, new shape) removes The Walking
Dead (comic book) entirely -- a US comic that entered via a Wikipedia list-of-volumes
page; Arrietty (Comics), a legitimate Japanese Ghibli film comic that came in the same
way, stays. (2) `corrections/aliases.json` gains a `"remove": true` curated-removal form
and ~26 exact (line, alias) entries -- the "Good" set from the followups-0923
alias-hygiene review, re-verified against a fresh rebuild; NOT a re-introduction of the
reverted automated rule. (3) `corrections/lines.json` gains a market override (a third
narrow entry shape) retagging Denma's mislabelled "ja" line to KR -- it's the Naver
webtoon's own episode-arc list, not a Japanese print edition; see the 2026-09-23
"follow-up" entry below for the defect this fixes. Full details, measured numbers and
per-string reasoning are in the branch's two commits and `corrections/README.md`.

Deferred (Nick's call, not done): an automated Western-comics check at ingest time
(flag any incoming Wikipedia list-of-volumes page whose work isn't manga/light-novel/
manhwa/manhua before it ever reaches the catalogue). Walking Dead is one stray in
13,001 series -- not enough signal yet to justify a general rule; excluded.json handles
it and anything like it case by case for now.

## 2026-09-23 — follow-up: Denma's "ja" line is really the Naver webtoon

Logged during the `followups-0923` branch review (item 4, the Denma `orig_series_id`
fix — a `corrections/lines.json` medium override retagging all three of Denma's
lines `manhwa` so the KR line resolves as the origin; see `corrections/README.md`'s
"medium override" section). The override is correct, but it exposed a mislabelling
one level up: the line tagged `ja` is not a Japanese print edition at all — its
titles are hangul and its numbering is the Naver webtoon's own episode-arc list
(2010-01 to 2012-01), i.e. the SAME Korean web serialization the `ko` line's print
volumes collect, not a translation of it. The `en` line is the LINE Webtoon
translation of those same episode arcs. Follow-up (not done): either correct the
`ja` line's `market` to `KR` (it would then likely fold into the `ko` line or need
its own composition mapping), or teach `export/line_status.py` to exclude an
episode-arc line from the stalled/behind comparison entirely — comparing 16 web
episode arcs against 19 print volumes is comparing different units, which is why
the fix's two newly-`stalled` lines (`Denma (Episodes) [en]` and `[ja]`, both "16 of
19, last dated vs. origin last dated") are an artefact of the mislabelling rather
than a real signal. Not blocking; the origin fix itself (`orig_series_id` now
pointing at the Korean line) is correct and should ship.

## 2026-09-21 — publish opentome-2026-09-21 (Rascal Does Not Dream vol. 16)

Nick's "Publish the OpenTome catalogue" (10:53 CDT): `catalogue.yml` dispatched with `publish=true` (run 35622036076: every gate green, publish + Discord announce succeeded; `manga-metadata.sqlite` 30,756,864 B on the `metadata` release at 15:56Z). Only change since 09-18: `corrections/lines.json` entry adding the English *Rascal Does Not Dream* vol. 16 (*Beach Queen +*, Yen Press 2026-08-11, 979-8-8554-3445-3) — the pipeline had the line at 15. Mangarr picked it up on a forced `MetadataUpdate` (opentome-2026-09-18 → 2026-09-21) and the entry now shows 16 volumes with the Audible ASIN on vol. 16. `lines.json` is additive (INSERT OR IGNORE on the line and its volumes), so a single new volume is the right shape for a missing tail volume.

## What this is now

OpenTome is a CI-built catalogue. The `catalogue` workflow runs the whole pipeline
(`tier0/rebuild_all.sh`) every Sunday and on demand: every unit test, the audit, the
artifact contract test and the measure gate, on a warm source cache. A scheduled run
builds and gates and stores the artifact as a run artifact — it never publishes.
Publishing is a human decision: someone presses *Run workflow* with `publish = true`,
and `export/publish.sh` creates the release `opentome-YYYY-MM-DD` on
`DrAwesome441/mangarr-metadata` and re-points the `metadata` alias at it. Every Mangarr
install polls that alias's `version.json`, verifies the sha256 and swaps the new
catalogue in — nothing to configure on the user side.

The repository carries no browser and no editing site. Corrections arrive as pull requests against
`corrections/*.json` (see `corrections/README.md`, `CONTRIBUTING.md`); a check runs on
every PR. Issues use the four templates under `.github/ISSUE_TEMPLATE/`.

## State of play

Last measured build: `opentome-2026-09-18` (the artifact's `meta.gcd_dump`).

- Artifact `manga-metadata.sqlite`: 11,657 series (release lines), 112,083 volumes
  + 938 `volumes_special`; 78,956 aliases; corrections applied: 0 (all three files are
  still `[]`).
- Measure gate (stage 8d, replaying Mangarr's series pick over the committed
  `export/fixtures/library.json`): matched 48/49, coverage failures 0. The one miss is
  *Mushoku Tensei: Roxy Gets Serious*, a spin-off line the catalogue does not carry yet.
- AniList ids: 42/48 picked lines carry one; 2,214 of the 2,522 English lines with
  three or more volumes are bound (the README's 2,614 / 3,053 figure counts every
  English line, not only those with 3+ volumes).
- Every source response is cached under `.cache/` (never committed); the CI cache is
  seeded once by the `seed-cache` workflow and kept warm by `cache-keepalive`.

## Gates

Every one of these exits non-zero and stops the build; none is optional.

- **Stage 0 — unit tests:** `tier0/test_parser.py`, `tier2/test_resolve.py`,
  `export/test_resolve_anilist.py`, `export/test_measure_fixture.py`.
- **Stage 7 — audit:** `tier2/audit.py` reports remaining defects and fails on any.
- **Stage 8c — artifact contract:** `export/test_artifact.py` asserts the consumer's
  schema, the id contract and every committed correction.
- **Stage 8d — measure gate:** `export/measure_library.py` replays a real library's
  series matching against `export/fixtures/library.json`; a coverage failure (an owned
  volume the picked line lacks) fails the build before the new artifact replaces the old.

`export/publish.sh` adds two refusals of its own: the label must be `opentome-YYYY-MM-DD`
and `meta.alias_provenance` must be `opentome` — the clean-room guard.

### 2026-09-19 — publisher hygiene, Discord announce
- `tier0/main_articles._publisher_field`: one clean publisher from a `<br>`/`<small>`/residue-glued infobox field (prefers the entry that is not former/expired/revoked, then one marked current/present/print, else the first); used for `publisher` and every `publisher_en` value. Contract rule `publishers with markup` in `export/test_artifact.py`. CI build 35453130837: `publishers with markup: 0` (was 113), measure gate `matched 48/49, 0 coverage failures`. **Not published yet — the next `publish=true` dispatch ships it** (Nick's gate).
- `catalogue.yml`: on a publish, an embed goes to the Mangarr Discord `#catalogue` (secret `DISCORD_CATALOGUE_WEBHOOK`; the step is skipped when the secret is unset).
- Looked at and left: 3,947 lines with blank status (1,530 main lines whose work has no Wikipedia status, 1,558 sub-lines that deliberately do not inherit the work's status) and 53 lines with zero volumes (real works without a volume table; 13 are sub-lines that could be folded into their parent via `id_redirect` — not done, no consumer needs it).

### 2026-09-20 — `series.author`
- `export/to_mangarr.py`: new nullable `series.author` column, the first name of the work's tier-0 `author` claim (the main article's infobox), on every line of the work; Mangarr reads it when present (a pin there overrides it). Wiki residue tier-0's one-pass template strip leaves behind (`Kentaro Miura ({{nowrap| 1–41}})`) is removed at export; a parenthetical that still says something (`Jitakukeibihei (Natsume Akatsuki)`) stays; an entry that is only a qualifier (`(1994–1998)`) is not a name. Contract rule `authors with markup` + info line `series with an author` in `export/test_artifact.py`. Local build: 9,598 / 11,658 lines carry an author, ids carried with 0 churn, measure gate `matched 48/49, 0 coverage failures`. **Not published — the next `publish=true` dispatch ships it** (Nick's gate).

### 2026-09-21 — volume titles, per-line status, orig_series_id, cover harvest guard
- `export/to_mangarr.py` binds `volumes.title` from the pipeline's row title instead of `None`, dropping a title that is number-only, carries wiki markup (`{{ }} [[ ]] <ref <br <!-- <ruby </`), is in kana/CJK/hangul on a non-origin-market line, or merely restates the series name plus a number. A leading series-name prefix (`Sword Art Online 1: Aincrad` → `Aincrad`) is stripped first. Local export (against a pipeline DB that predates the tier-0 change below): 9,317 titles kept (ja 7,018 / en 1,882 / fr 406 / ko 11); dropped: number-only 6, markup 143, wrong-script 1,766 (EN 1,750, FR 16), redundant 213; prefix stripped 57. The wrong-script count is the measure of the old title pick: the row's title was the first non-blank of `(Title, OriginalTitle, LicensedTitle)` regardless of market. **Tier 0 now picks per market (7a200b6, this round):** `wikipedia_volumes.py` carries `title_original` / `title_licensed` (en: `OriginalTitle` / `LicensedTitle`; fr: `titre_1` / `titre_2`; generic `Title` / `titre` as fallback) and `schema/load.py` binds the licensed one on the licensed row — the CI rebuild is the first build to show it (expect the wrong-script drops to collapse and en titles to rise). `_clean` also unwraps `{{Nihongo2|…}}`, `{{japonais|…}}`, `<ruby>` and drops an unterminated `<!--`.
- `series.status` is now per LINE for a licensed market with a resolvable origin (`completed | ongoing | stalled`), from new `export/line_status.py` + `export/test_line_status.py`: `stalled` = at least two volumes behind the origin, nothing dated in 24 months, origin kept shipping. Origin-market and omnibus lines keep the work's status. `series.orig_series_id` is written for every resolved licensed line — the origin counterpart chosen by medium (manhwa/webtoon → KR, manhua → CN then TW), else earliest first release, else the old JP/KR/CN/TW order. Known accepted defect: Denma (medium `manga`, ko line) still resolves to its ja edition — the medium hint only applies to manhwa/manhua/webtoon.
- Transition table against the 2026-09-20 artifact (`export/to_mangarr.py` prints it and writes `build/status-transitions.tsv`): NULL→completed 594, NULL→ongoing 309, NULL→stalled 40, ongoing→stalled 153 — 193 lines stalled in all, 122 of them English (Warlord left the set once its origin resolved to KR).
- Contract additions in `export/test_artifact.py`: allowed `status` set is now `{completed, ongoing, stalled, NULL}`; `stalled` invariants (`orig_series_id` required, no dated volume in the last 24 months, at least two volumes behind its origin); `orig_series_id` pointing at a missing series, another work, or an origin-market mismatch; volume titles with wiki markup; volume titles that are only a number.
- `tier1/covers.py:45`: the openBD cache reader checked only the FIRST element of a cached response list for a `summary` key, so a batch whose first ISBN was unknown was skipped whole. Now checks every element. Cache-only, zero requests (`covers_from_cache`); local before/after on this workstation's `.cache/`: `cache files 15,695 -> cover URLs for 12,311 ISBNs (openbd 125, openlibrary 12,186)` → `... 12,313 ISBNs (openbd 127, openlibrary 12,186)`. English/French coverage does not move — bounded by what Open Library returns for ISBNs it knows, which is already fully harvested (`docs/legal-position.md`, `corrections/README.md`).
- Local gate (`export/test_artifact.py`): 33/34 rules ok. The one fail, `publishers with markup: 114`, is the local pipeline DB predating the tier-0 publisher fix from 2026-09-19 (`_publisher_field`); CI, which rebuilds from a clean cache, reports 0 — not a regression from this round.
- Stage 0 unit tests green: `tier0/test_parser.py`, `tier2/test_resolve.py`, `export/test_resolve_anilist.py`, `export/test_measure_fixture.py`, `export/test_line_status.py`.
- **Not published — the next `publish=true` dispatch ships it** (Nick's gate); the Sunday `catalogue` build picks it up regardless.
- Two rules a reader of the status column needs: (1) a non-main licensed line (arc, side story) that has reached its origin's top volume with neither market shipping for 24 months is `completed` even if the work is `ongoing` (207 lines take this path; all were NULL before); (2) `release_line.status` is no longer consulted for a licensed line with a resolved origin — the corrections-only `cancelled` idea would need the exporter to read it first. Hand-checked title corrections bypass the lossy title filters (`title_for_export(trusted=...)`) so `corrections/volumes.json` titles round-trip; markup / number-only rejects still apply and the corrections check should refuse those at authoring time (follow-up). CI now keeps `build/status-transitions.tsv` as a run artifact. The first post-merge CI build (run 35678933785) failed in `tier2/audit.py`: its un-split-arc scan read the new per-market titles and saw an English publisher's sub-series numbering restart ("… Progressive 1/2") inside a line the splitter left whole — the scan now covers origin-market rows only (the titles the splitter itself reads).
- **PUBLISHED 2026-09-22 ~01:00 CDT by Nick's dispatch (run 35726050230, publish + Discord announce green) as `opentome-2026-09-22`; the build-only rehearsal was run 35679310812 (same numbers):** titles kept 11,454 (ja 7,522 / en 3,465 / fr 456 / ko 11) — the tier-0 pick lifted English titles from 1,882 to 3,465 and cut wrong-script drops from 1,766 to 170; markup drops 54; prefix stripped 95; redundant 247. SAO's English light novels read Aincrad / Fairy Dance. Transition table unchanged in shape: NULL→completed 596, NULL→ongoing 309, NULL→stalled 40, ongoing→stalled 153 (193 stalled, 122 English). The run's `status-transitions.tsv` lists every stalled line — read before `publish=true`. Seen in the samples, a follow-up: a `LicensedTitle` like `Mushoku Tensei: Jobless Reincarnation (Light Novel) Vol. 14` survives the redundancy check because of the `(Light Novel)` qualifier between name and number.
- Open items: the Denma `orig_series_id` defect (accepted, not blocking); the local `build/opentome.db` needs a full rebuild to reflect the tier-0 title pick; `_clean`'s `{{japonais|…}}` / `{{nihongo…}}` unwrap is regex-based and garbles a title whose template nests another template (~101 of 1,028 fr `titre_*` fields, ~4 en) — the exporter's markup filter drops the ones that keep a `}}`, the rest leak a stray `|`; follow-up: brace-balanced unwrapping with the depth counter `_templates()` already uses. Mangarr consumer follow-ups (separate repo, after publish): `SubtitleOf` should take the artifact title as its first candidate before the Google Books record; `MapGcdStatus` should map `stalled` to a visible Stalled state instead of falling back to AniList (which reads a still-running Japanese series as Continuing — safe but loses the signal).

## Next

Phase 3 is done (2026-09-18). What runs where now:

- **Build + publish:** GitHub Actions in this repository. `catalogue` runs every Sunday
  09:00 UTC (build + every gate, never publishes); a maintainer publishes by dispatching it
  with `publish = true`. First CI build: run 35387125298 (identical figures to the last
  workstation build, ids carried exactly); first CI publish: run 35393862685 →
  `opentome-2026-09-18` on `DrAwesome441/mangarr-metadata`, alias `metadata` re-pointed,
  picked up by Mangarr the same hour.
- **Cache:** the Actions cache, seeded from the private `opentome-cache` repo's `seed`
  release (run 35387058848), kept warm by `cache-keepalive`.
- **Site:** `pages` builds `site/` on push, on every `catalogue` completion and on a
  Sunday schedule; live at the GitHub Pages URL, moving to opentomedb.com once DNS
  resolves (custom domain is set; HTTPS enforcement follows the certificate).
- **Corrections:** issues and pull requests here; `corrections check` runs on every PR.
  The first one through the path — #1, the English light-novel line of Mushoku Tensei
  (Seven Seas, 26 volumes, every ISBN and date from an Open Library edition record) — is
  merged and in the next build (`rl_250d21561d35`); it reaches Mangarr on the next publish.
  It also found a gate bug: the artifact contract's "multi-entry composition" heuristic
  (`LENGTH > 3`) refused `[10]`; the export now carries composition only for omnibus lines
  and the rule checks the real invariant.
- **Retired:** the old browser and the workstation rebuild agent — nothing OpenTome-related
  runs outside CI. The pre-CI history stays on the maintainer's private mirror.

Open, in order of value:

1. **Publish again** so the Mushoku Tensei line, the publisher hygiene and `series.author` reach consumers (a maintainer's dispatch).
2. The `metadata` alias release's notes on `mangarr-metadata` still describe the pre-OpenTome
   (GCD-era) artifact; they should be rewritten to the OpenTome text (maintainer decision —
   it changes existing release content).
3. Known data defects surfaced by the site: 113 `series.publisher` values carry Wikipedia
   infobox markup (`<br>`, `<small>`); 53 lines have `volume_count = 0`; `status` is blank on
   3,946 lines; `country` is empty everywhere; `mangaupdates_id`/`mangadex_id` are unfilled.
4. DNB as the German primary source (`docs/german-market.md`) — today's German lines come
   from Wikipedia only; the site says so.
5. The multi-market validation spike; per-line pages on the site (v2).

## Gotchas for contributors

- A `catalogue` run fails at its cache step (`fail-on-cache-miss`) until `seed-cache` has run once on `main`; that is deliberate — a cold build would spend hours of polite-rate requests and be killed by the 180-minute limit.
- **Never pipe a gate's exit away.** `set -o pipefail` is on in `rebuild_all.sh`; a
  `| tee` or `| head` around a gate outside it hides the failure the gate exists to raise.
- **`gcd_dump` is a legacy key name.** It labels the build (`opentome-YYYY-MM-DD`) and
  is kept for the updater's contract; the catalogue contains no GCD data.
- **Ids are a public contract.** `tome_id` / `tome_work_id` are never reused or
  re-keyed; the export carries integer ids forward through `id_map` from the last
  published artifact (CI downloads it before the rebuild). A merge writes `id_redirect`.
- **Corrections must pass `python3 tier2/corrections.py --check`** — well-formed,
  `source_url` and `checked` present, every key resolving against a published artifact
  (`--artifact <download>`; the default is the last local build). The PR check runs
  exactly that against the `metadata` release.
- **`.cache/` is never committed.** It is raw third-party responses whose redistribution
  the sources' terms do not allow. A cold build re-fetches everything under each
  source's rate limit (Wikipedia 429s without the 1.1 s throttle; put a real contact in
  the User-Agent) and takes hours.
- **Scheduled workflows on a public repository pause after 60 days without commits.**
  A merged PR resets the clock; a paused `catalogue` schedule shows on the Actions tab.

The pre-CI engineering history (2026-08 → 2026-09) is preserved on the maintainer's
private mirror.
