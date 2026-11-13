# HANDOFF — OpenTome

## The #corrections AniList round (2026-11-12) -- **PUSHED + PUBLISHED 2026-11-13 09:27 CST as `opentome-2026-11-13` (main 6bc82b5); Mangarr pulled it**

A thread in the Discord #corrections forum ("Anilist corrections", 2026-11-12 evening, from the Gutter developer)
listed seven English lines whose AniList id is another author's work with the same title. Each checked on AniList
(author, year, volume count) and against the published artifact (same wrong ids): Kurogane rl_1b66d4b8b80f 59447 -> 31598,
Doubt!! rl_696165fac48a 35293 -> 30884, Amefurashi rl_f4b61971809d 98500 -> 44493, Classmates rl_d045f8964385
91597 -> 39699, Wind Breaker rl_81db300c8574 86099 -> 135083, Guin Saga (The Seven Magi) rl_635fdc6eedfb 45150 -> 42927,
Punch! rl_e8a418c6130b 32319 -> 30788. Pinned in `corrections/anilist.json` (45 entries now), commit d3b67e6.

**Proof:** `tier2/corrections.py --check` -> `corrections check ok ... 45 anilist ... resolve against manga-metadata.sqlite
(opentome-2026-11-08)` (the published file, sha f5962a7f); `--anilist` on a copy of it writes the seven ids; `--display`
(offline) on that copy moves `Classmates (Blanc)` rl_9ab4a354e90e from 91597 to 39699 via its parent line, display rows
71 -> 71; `tier2/test_corrections_check.py` 84 OK. The contract test (`export/test_artifact.py`) asserts every pin, so
CI's 8c proves the landing.

**Done 2026-11-13 morning (Nick: "1. Push 2. Post It"):** pushed GitHub + Forgejo main 6bc82b5; build-only run 43450454576 green on every gate (8a `anilist id pins applied 45`, every other number identical to run 42901776035: 2821 resolved, 168 EN lines without an id, 34 redirects, 0 German volumes retired, `artifact contract ok`, library gate ok, 8d floors; the printed `STALE CORRECTION -- lines.json cluster_with dnb:139599577X` is in both runs, pre-existing). Publish run 43451811441: release `opentome-2026-11-13`, sha256 ed3e3bbc, 37,425,152 bytes, `metadata` alias re-pointed; pages run 43452815851 put the site manifest up. Mangarr: the first MetadataUpdate (cmd 438854, ~1 min after the publish) saw the OLD site manifest -- GitHub Pages' CDN lags a minute or two behind the pages run; the second (cmd 438858) pulled it (`Updated GCD metadata to opentome-2026-11-13`, integrity ok). Live file sha ed3e3bbc; the seven lines and Classmates (Blanc) carry the new ids. FlightLog line 2026-11-13 09:29 + backups `mangarr-manga-metadata.sqlite.before-20261113-opentome`, `LEDGER.md.20261113-opentome`. **Gotcha:** after a publish, wait for the pages run AND a minute of CDN before forcing Mangarr's MetadataUpdate, or it reports "up to date" against the old manifest.

**Posted as Nick from his Chrome on his "Post It" (2026-11-13 09:15 CST):** the thread reply (msg 1570819295137501225) and the #general reply to the Gutter developer (msg 1570819388863422526) -- the latter commits OpenTome to (a) the work's AniList id on every line and (c) binding JP-only works by native title, and offers (b) a MAL id if it helps their matcher. **Measured for (a):** a same-medium-family rule (comic = manga/manhwa/manhua, novel = light_novel/novel) gives 4,881 NULL lines an id (JP manga 2,617, DE manga 1,007, FR manga 673, JP LN 367 ...); 984 NULL lines sit in 121 families whose bound EN lines carry different ids (arcs / spin-offs: Re:Zero, Bungo Stray Dogs, Magic Knight Rayearth) -- those need the display fallback's name rule (line name cut at ` (` / `: ` equals a bound EN line's name), not a blanket copy.

**NEXT:** (1) the thread note that the fix is out -- draft: "Out as opentome-2026-11-13; the seven lines carry the ids above now." -- on Nick's "post it"; (2) round (a) as designed above (brainstorm -> spec -> plan; a contract test that no pinned or bound id is overwritten and that a conflicting family copies nothing); (3) round (c) after it; (4) the Kurogane JP line below.

**Related finding, OPEN (a JP-line item, no correction shape covers it):** the Kurogane work w_2bdd2c36614d. Its JP main
line rl_85cef1a1d2cb ("Kurogane", local_name 黒鉄, publisher Kodansha, 2011, 8 volumes) holds Shueisha ISBNs
(9784088703596, 9784088703787, 9784088704234 ..., 2011-12 to 2013) -- Haruto Ikezawa's クロガネ, another work; Kei
Toume's own JP line rl_5a2e167d2417 (1996, 5 volumes) sits under it as a non-main child, as does Kurogane Kai
rl_52b46e28d61e. The EN line's orig_series_id already points at the 1996 line. Likely why the resolver reached for 59447.

**Coverage facts for the Gutter conversation (the developer wrote in #general 11-12 that OpenTome "doesn't have enough
AniList or other links" to train their matcher):** 5,061 works; 2,587 carry an AniList id on some line; 2,616 works have
no English line and 2,373 of those carry no AniList id at all (1,572 JP-only, 616 JP + DE/FR, 153 DE/FR-only). The id
sits on the EN line (and on the KR/CN works' main lines) only -- a JP/DE/FR sibling line shows NULL unless the consumer
joins through tome_work_id. `mangaupdates_id` and `mangadex_id` exist and are NULL on every row; no MAL id anywhere.
Options for Nick: (a) write the work's AniList id onto every main line, as the KR/CN lift already does -- same data,
no new requests; (b) store `idMal` from the same AniList response (one column; read AniList's terms first);
(c) bind JP-only works by native title -- a resolver round.

**Draft thread reply (NOT posted; Nick posts or says "post it"):** "Thanks -- all seven checked out on AniList (author,
year, volume count) and are pinned at the source. They land with the next catalogue publish; I'll note here when it is
out. Your list also showed that the Japanese side of Kurogane has the 2011 Shueisha serial mixed into Kei Toume's work;
that is a separate fix on the Japanese line and is on the list."

## The Sunday 11-08 scheduled build -- **RED; FIXED, PUSHED 2026-11-10 (main 08a226b), build-only run GREEN; nothing to publish**

Run 42496125741 (schedule, 11-08 15:42Z, same tree b4d8e38 as the green publish 14 hours earlier, same data: records
28,339, 34 redirects) failed two contract rules on one line: E1 `rl_9234c886dfe2 alias rows lost` and a same-name
pair for w_dc0f270e3cb4 (Mein Buchcafé in einer anderen Welt, de manga). Cause: that run was the first to CARRY
from the 11-08 publish, where the Loewe hardcover ships as "Mein Buchcafé in einer anderen Welt – Perfect Edition";
`name_new_editions` names only NEW edition lines (rl_id not in the carry), so the now-carried line was rebuilt under
the set record's bare title -- its two published alias rows gone and the paperback's name repeated. The fix:
`name_new_editions(lines, W, carried, carried_names)` -- a carried edition line whose published name (the carry's
`series.name`) is the built name plus its edition label keeps the published name; any other published name is left
to the build. Tests: the old "published edition keeps its name" case now passes `carried_names` and expects the
suffixed name (it failed without the fix), plus "not counted as a new naming" and "another published name is left to
the build". docs/dnb-design.md has the paragraph.

**Local mirror (offline, carry = the published 11-08 artifact, same cache as CI): `artifact contract ok`**, the
hardcover exports as "… – Perfect Edition" with its 2 alias rows, 0 German volumes retired, moved 0, 34 redirects --
the Sunday run's numbers with its two failures gone. 8d stops at the library fixture, as always.

**Pushed on Nick's word "Push" (11-10 15:05 CST); build-only run 42901776035 green on every gate** -- records 28,339,
34 redirects, 0 German volumes retired, `artifact contract ok`, library gate ok, `DNB reload gives the same ids: 21,757
member records, 0 in another line, 0 line ids re-keyed`; three new edition lines named (the hardcover is no longer
"new": it keeps its published name). **Nothing to publish:** the published 11-08 file already has the right name; the
fix keeps the scheduled builds green (next one Sunday 11-15). **NEXT:** nothing open in this round.

## The 11-07 DNB refresh -- **PUBLISHED 2026-11-07 19:25 CST as `opentome-2026-11-08` (main b4d8e38); Mangarr pulled it**

Nick, 11-07: "1. Push" for the parked round's five commits. Pushed (GitHub + Forgejo main 601168c), build-only run
42413457514 **red** on two contract rules -- not the round's code: the run made 155 live DNB requests (`DNB_REFRESH_DAYS: 6`,
2022-2024 re-paged, 28,110 -> 28,308 records) where the 11-06 green runs made 0, and the same tree rebuilt locally
with the same refresh reproduces the failure exactly (same 37 redirects, same first ids). The "two rules only the
local DNB cache produces" of the sections below were this: the local cache had been refreshed first. One commit,
587d71a, fixes the three causes (its message carries the measurements):
- **Continuity for the JP round** (`build_dnb.adopt_published_ids`): nine published lines re-keyed by new DNB set
  records now keep their ids and names; 4 adopt on this data, the other 5 are stray volumes DNB linked to their set
  lines (legitimate, redirected). docs/id-scheme.md has the row, docs/dnb-design.md the paragraph.
- **A new edition line named with its edition** (`build_dnb.name_new_editions`): the 2026 Loewe hardcover of Mein
  Buchcafé in einer anderen Welt (`250 Perfect edition`) and three more new edition lines; published names unchanged.
- **Carried-ISBN recovery** (`dnb_enumerate.recover_carried`): Das Biest des Königs Bd. 2-16, 18 (DNB dropped their
  041$h; `spo=jpn` lost them, `num=` returns them) are back; 31 of 54 asked ISBNs found, at most 60 new lookups a run.
- **Tried and reverted:** the Kazé family in the imprint channel (+862 records, 15 new same-name pairs, 340 volumes
  moved). A round of its own; measurement in docs/dnb-design.md.

**Offline rebuild on the refreshed cache: `artifact contract ok`** (German volumes gone 9, cap 25; E1/E3 0; same-name
pairs 0; moved 15; retired volumes 1). Local 8d stops at the library fixture (a CI secret), as always.

**Second push word, 11-07 evening:** 587d71a + 74b143c went up on Nick's word; build-only run 42420214817 was green
through 8c and the library gate and **red on 8d's "DNB reload gives the same ids"** -- `measure_library.same_ids` reloaded
the cache without the build's three new steps, so it saw 54 member records in other lines and 4 ids re-keyed. 74e797e
makes the reload repeat the build: `recover_carried` for the ISBNs the build asked (offline, cache only), the JP
`split_sections(home=True)` before clustering, and the adoptions from meta `dnb:stats` (an adopted line's own key
maps to the published id it kept). Local: `21,757 member records, 0 in another line, 0 line ids re-keyed`.

**Done 11-07 evening:** build-only run 42433336733 on b4d8e38 green on every gate (3e `recovery 54 carried ISBN(s) ...:
31 found, 0 failed, 0 deferred`, `continuity: 4 line(s)`, 4 new edition lines named, `live requests: DNB 0`; 8c
`artifact contract ok`, 0 German volumes retired over the cap, moved 15, 37 redirects; 8d every floor, library gate ok,
`DNB reload gives the same ids: 21,757 member records, 0 in another line, 0 line ids re-keyed`). Publish run
42433848174; site manifest `opentome-2026-11-08`, sha f5962a7f, 37,425,152 bytes. Mangarr pulled it at once
(MetadataUpdate cmd 424279, file sha matched, integrity ok; FlightLog line + backup
`mangarr-manga-metadata.sqlite.before-20261108-opentome`). **Measured on the published file against 448a1018
(11-06):** volumes passing Mangarr's adjacency rule EN 10,917 -> 11,112, FR 7,364 -> 7,508, JP 19,159 -> 19,496, all
37,493 -> 38,160; one-whole-chapter lists EN 109 -> 61, FR 157 -> 139, JP 267 -> 224; KO 40 -> 31 passing (6 lists fewer,
the KR/CN side of the parked round). The refreshed DNB cache is saved; the next refresh falls on or after 11-13.

**NEXT:** nothing of this round is open once the #beta note is posted (draft offered to Nick 11-07 evening). **What CI must confirm** on top of the list in the section below: 3e prints
`recovery 54 carried ISBN(s) ...: 31 found` (or fewer missing: CI's cache may still hold some), `continuity: 4 line(s)`,
`new edition lines named with their edition: [4]`; 8c German cap ok; 8d every floor and the library gate. The refreshed
cache is saved (opentome-cache-42413457514-1), so the next run refreshes nothing for six days.

**Gotcha, learned:** a local rebuild is a mirror of CI only when the local cache is as fresh; before calling a failure
"local-only", run `DNB_REFRESH_DAYS=1` once and compare the `records` line with CI's.

## The backlog of the parked round -- **FIXED LOCALLY 2026-11-07 (main 1b3099b + this file), NOT PUSHED; nothing published**

Nick, 11-06: "do the backlog" (the four items the section below lists as still open). Four commits on top of bf6b664,
local only. **Pushing them needs Nick's push or his word.** The published catalogue is `opentome-2026-11-06`
(sha 448a1018, the second publish of 11-06), which is also the local id carry now (`build/manga-metadata.sqlite`;
the morning's 71a79453 file is `build/manga-metadata.sqlite.published-20261106a`).

**NEXT, in order:** (1) push main (GitHub + Forgejo); (2) `gh workflow run catalogue.yml -R opentomedb/opentome --ref main`
(build-only) and read the log against "What CI must confirm" below; (3) green -> the same dispatch with
`-f publish=true`; (4) wait until opentomedb.com/catalogue/version.json carries the new sha (up to 10 minutes), then
Mangarr Metadata Update on the homelab + its ledger line; (5) measure chapter lists on the published file against
sha 448a1018 (English volumes passing Mangarr's adjacency rule 10,917; all languages 37,493; English one-chapter
lists 109).

**1. 7b re-points a retired volume id -- 1562e0e** (`carried_ids.redirects` step 1c; docs/carried-ids.md). A carried
row that retired a volume to its line was only re-read; when the volume is filed again under the other publisher
name of the same edition (one season as two lines), the old id `v_<hash(line, number)>` gives the number back and the
twin's volume of that number is the successor (reason `correction`). Only while the line itself still lacks the
number and exactly one same-named twin of the work, market and medium holds it; a volume back on its own line is the
stale case. On the carry: one row, v_1a962f064793 -> v_6468d08af096 (The Pawn's Revenge, 3rd season vol 1).

**2. The JP-origin German sets with the season layout -- 26a7614** (`build_dnb.split_sections(home=True)`, moved from
krcn_lines and shared; docs/dnb-design.md). The five sets split: Wonderful Wonder World - Country of Clubs, Pokémon -
die großen Abenteuer, Record of Lodoss War, Gorgeous Carat, The Legend of Zelda. The section catalogued first (the
set's lowest-IDN numbered volume) stays the set under its published key and name, because the published line holds
exactly that section's volumes (checked: Pokémon vols 1-3 = Rot, Blau und Gelb 1-3; Gorgeous Carat 1-4 = Der Reiz der
Finsternis 1-4); only the other sections move. **Moved ids: none.** No published line or volume id changes, no
redirect is written; 8 new section lines (2 of them in published, linked sets: "Pokémon™ - die großen Abenteuer –
Gold und Silber" 2 vols, "Gorgeous carat – La esperanza : die Madonna der Hoffnung" 2 vols; the other 3 sets are
unlinked, as before). Duplicates dropped in the JP round 226 -> 207. The KR/CN round keeps `home=False` (every
section moves) because its section keys are published. The set's title proper is a title of every section line
(shape_line) so the sections link to one work.

**3. The 123 edition lines -- 02c7cdc.** Not by name. `is_omnibus` is set (and the id listed in `omnibus_lines_named`)
only where the data says the line collects: clearly fewer books than its work's main line of the market, else the
origin line (at most three quarters of a main line of at least 4), and thicker ones (at least 3 known page counts
with a median 1.3 times the main line's, or 320 pages when the main line's are unknown). On the published artifact
10 of the 123 pass, in the offline rebuild 9 lines flip, every one a collected edition on inspection: Parasyte
kanzenban (8 for 12), Sailor Moon shinsōban (12 for 18), Lone Wolf and Cub aizōban (4 x 697 pp), Soul Eater Perfect
Edition, Spriggan deluxe, Nodame Cantabile deluxe, Racaille Blues Masterpiece, Shaman King and YuYu Hakusho Star
Editions. Of the rest: 95 have fewer than 3 page counts, 10 no main line to compare, 8 pass one half of the test
(Hikaru no Go deluxe: fewer, not thicker; Maison Ikkoku Collector's: thicker, but the JP main line the catalogue
holds has 2 volumes). They stay as they are; the evidence is too thin for a cleaner rule.

**4. Chapter lists -- 1b3099b** (`tier0/wikipedia_volumes.py`, 15 new tests).
- A number inside a title is left alone: glued to a slash ("X/1999 - ..."), hyphenated to a word ("365-Step",
  "Class 2-B,", "1-Karat", "6-toshi"; not a label and its separator, "15-R :", "1-A."), deep inside an open quote
  ("The Guardians of Desire (2–3)"), in a later argument of {{nihongo}} / {{japonais}}. Measured on every cached
  cell: 141 English and 42 French lists lose a number, each one read out of a title (looked at one by one; two
  Maburaho lists lose a real "Dai 7-wa"), no list gains one by this rule. Requiring every number at the head of its
  entry was tried earlier and rejected (it drops "{{N°}}45 :", "Reincarnation 216.", "Kill-17 :").
- Shapes read only in a run of entries that follow each other: a quoted label and number ('"Mission:14"', three
  or more), an ordinal and a word ("24th day", "44th Night", "1st Life"), a zero-padded number and a title ("01
  Sample"), an entry that is a bare number ("* 25"); never a year, never under a word for things numbered apart; a
  heading ordinal before a chapter range ("2nd Stage: Chapters 9–17") no longer stops the range; <div> wrappers are
  dropped (the last entry of a French cell carried "</div>"). 252 English and 138 French lists gain numbers.
- Not done: Roman numerals ("Chapter IV:") -- light novels only, whose chapters restart per volume; the "two lists
  for one volume" pick (Air Gear's JP line loses 2 trusted volumes where the French cell's list now wins over the
  English one).
- **Measured** (stage 2 built into scratch databases before and after, cache only; comic lines): lists of one whole
  chapter EN 98 -> 50, FR 157 -> 139, JP 268 -> 218; volumes passing Mangarr's adjacency rule EN 10,949 -> 11,126,
  FR 7,385 -> 7,529, JP 19,331 -> 19,641; whole chapters claimed by two volumes of a line EN 643 -> 586. On the
  rebuilt artifact against the published 448a1018 file: English one-chapter lists 109 -> 61 (165 on the morning's
  publish, 2,014 on 10-20), English volumes passing 10,917 -> 11,112, all languages 37,493 -> 38,160.
  English-market volume records whose list is one chapter, at the parser: 108 -> 61 (167 before the 11-06 round).

**Verified:** every stage-0 suite green. One full offline rebuild against the 448a1018 carry: it stops at 8c on the
two rules only the LOCAL DNB cache produces (55 carried German volumes retired; a shared name in w_dc0f270e3cb4),
and only those; the two omnibus rules pass; 7b prints `re-pointed 1 retired volume id(s)`; 3f ids "kept 551, taken 2
(weak 0), left 1" (the one left is local-cache drift, there before); no name, work, integer or AniList id of a
published line changes; 0 lines or volumes gone without a redirect. **8d (measure gate, library gate) was not reached
locally.**

**What CI must confirm:**
- 8c green with `omnibus_lines` 194 -> about 203 (the 9 count-rule flips; CI's records are fresher).
- 3e: `dropped_duplicate_number` 226 -> 207 in the German JP round; DE lines +2 exported (the Pokémon and Gorgeous
  Carat sections, if the linker links them as it links their sets); no German line retired for it.
- 7b: `re-pointed 1 retired volume id(s) ... ['v_1a962f064793']`; against 448a1018, 0 carried ids moved.
- 8d: every floor, and the library gate (9 flags flipped; a non-omnibus line ranks before an omnibus one).
- Then the chapter-list numbers above on the published file.

## Parked data items -- **PUBLISHED 2026-11-06 (second publish of the day) as `opentome-2026-11-06`** (main 368fa14; sha 448a1018; build-only 42261912642, publish 42263016184; Mangarr pulled it 11:53 CST)

Nick, 11-06: "3. yes" to pushing the five commits 0e9dc54..368fa14 (a one-time word; the rule that Nick pushes main is
unchanged). Build-only green, published, public manifest and opentomedb.com both carry sha 448a1018 (same label as
the morning's publish; Mangarr compares the sha for an equal label).

**What CI showed:** `artifact contract ok`, library gate ok, every 8d floor ok. Against the morning's publish
(sha 71a79453): 13,464 -> 13,469 lines (the five new ones are the German season lines of two series), 125,468 ->
125,493 volumes, 0 lines gone, 0 carried ids moved or retired, v_14bfad9af2dc present again; library works 428 -> 429
(created 1); omnibus-flagged lines 161 -> 194, of which 33 are published lines that flipped (the offline rebuild
said 31; CI's records are fresher). Measure-gate moves are the season lines only (DE lines 1,782 -> 1,787, DE
exported lines 325 -> 330).

**Chapter lists on the published file:** English volumes passing Mangarr's adjacency rule 10,477 -> 10,917 (8,570 on
10-20); English one-chapter lists 165 -> 109; all languages passing 35,860 -> 37,493.

**Gotcha, corrected:** after a publish the site's `catalogue/version.json` can lag by the full cache lifetime
(`max-age=600`): this time about 10 minutes, not 4. Compare its sha with the release's before running Mangarr's
Metadata Update.

**Still open as of this publish:** the four items the section at the top of this file took on 11-07 (fixed locally there).

## Parked data items -- **FIXED LOCALLY 2026-11-06 (main 5c32881 + this file), NOT PUSHED; nothing published**

Nick, 11-06 after the publish: "Can you work on those?" (the parked list). Four commits on top of 1e77bfd, local only.
**Pushing them needs Nick's push or his word.** The published catalogue is still `opentome-2026-11-06` (sha 71a79453).

**NEXT, in order:** (1) push main (GitHub + Forgejo); (2) `gh workflow run catalogue.yml -R opentomedb/opentome --ref main`
(build-only) and read the log against "What CI must confirm" below; (3) green -> the same dispatch with
`-f publish=true`; (4) wait until opentomedb.com/catalogue/version.json names the new label, then Mangarr Metadata
Update on the homelab + its ledger line; (5) measure chapter lists on the published file against `opentome-2026-11-06`
(English volumes passing Mangarr's adjacency rule 10,477; all languages 35,860; English one-chapter lists 165).

**1. German sets filed in sections -- 0e9dc54** (`krcn_lines.split_sections`, KR/CN round only; docs/krcn-design.md §8).
DNB keeps a series published in seasons under ONE set record and numbers each season from 1: 245 $n '[1st season]'
$n '1' ... $n '2nd season' $n '1' (773 $q '11st 11', '12nd 11'), or 245 $n '[...]' $p 'Season II' $n '1'. Read as one
line, every number after the first season's was a duplicate and the set sat in review. A section whose numbers repeat
another's is now its own line, keyed `dnb:<set IDN>#<folded section>`, named `<set title> – <section>` (the
publisher's own series statement of that name wins), with the set's title, original title and creators kept so the
seasons land in one work. `build_dnb.cluster` / `shape_line` are untouched: the sections reach them as pseudo-sets.
- Why the key is never a member's IDN: the IDN of the 3rd season's vol. 1 is the natural key that minted
  rl_9b3ea88520d6, the line of the OTHER publisher name; continuity would hand that id over and re-key both lines
  (test "S:" in test_krcn.py).
- Nothing published is re-keyed. A set splits only when numbers collide across sections, and a collision has always
  meant review `duplicate_numbers` (never exported). A plain number above the volume number is not a section (a
  group over a running count; the volume number above a part of an arc).
- Cached records: 2 sets, 6 section lines, 15 volumes that were dropped as duplicates. "The Pawn's Revenge": the
  3rd-season section line takes rl_9e8ed759862f (shares vols 3, 5), so vol. 2 is back under its ORIGINAL id
  v_14bfad9af2dc (7b drops its retired redirect); vol. 1 is back under a NEW id v_6468d08af096 -- its old id
  v_1a962f064793 lived on the other publisher-name line (rl_9b3ea88520d6, which keeps vol. 4) and stays a `retired`
  redirect to that line. New lines: 1st season (5 vols), 2nd season (5 vols), and "Killing stalking" Season I / II /
  III (4 / 4 / 5 vols; that set was never exported at all).
- **Not done, on purpose:** the German JP round has the same shape in 5 sets (13 section lines, 41 volumes: Wonderful
  Wonder World - Country of Clubs, Pokémon - die großen Abenteuer, Record of Lodoss War, Gorgeous Carat, The Legend
  of Zelda). Those lines are published with the first volume seen per number, so a split there moves published
  volumes: a deliberate round with redirects, not a side effect. Measured, not applied.

**2. Omnibus flag -- c8691e6.** `is_omnibus` was set only where a volume lists the original volumes it holds
(`composition`). A line that only SAYS it is an omnibus shipped as an ordinary line: a Wikipedia section named
"(Omnibus edition)" / "(2-in-1 Edition)" / "(VizBig edition)" / "(Volumes doubles)" / "(Édition double)" / "(Format
double)" / "(Édition intégrale)" whose table gives no list, and every DNB line whose edition statement says "Massiv" /
"Sammelband" (the catalogue has `release_line.format = 'omnibus'` for these; the export never read it). Such a line
is flagged now: 31 published lines (DE 14, EN 6, FR 4, JP 7), `omnibus_lines` 161 -> 192. No composition is invented,
the status rule still asks the composition, and meta `omnibus_lines_named` lists the ids so the contract test keeps
refusing any other flag without a list (two rules replace the old one).
- What it does in Mangarr (read, not changed): `IsCollectedEdition` is true for the line, so the origin market's
  volume total is no longer shown as "X of Y" and no Coming Soon rows are invented for it (13 of the 31 have no
  page-count tell and could get them: DE 4, EN 1, FR 1, JP 7); a same-ranked non-omnibus line is preferred at lookup; a line already tracked keeps
  its id, volumes and name.
- **Judgment calls, NOT decided** (123 published lines: JP 86, EN 20, FR 17; 115 without Mangarr's page-count tell):
  deluxe, perfect, kanzenban, bunkoban / bunko, aizōban, shinsōban, wideban, collector's, "new edition", "complete",
  master / anniversary / special editions. Some renumber (a kanzenban usually holds more than a tankōbon), some do
  not, and the name does not say. Also left: "(Box sets)", "(Collected editions)", "(English double issues)" (two
  stories in one issue, same count as the main line). Recommendation: leave them until a volume list (composition)
  says so; flagging by name would hide real Coming Soon rows on editions that follow the original count.

**3. Chapter lists -- 84951fd + 5c32881** (`tier0/wikipedia_volumes.py`; 40 new parser tests).
- Entries that are not `*` bullets: a line opening with `:` or `#`, an HTML `<li>`, a `<br>` in a cell with no list
  markup (the French articles' usual shape), the items of `{{Bulleted list}}` / `{{Unbulleted list}}`. Such an entry
  gives a number only at its HEAD (a `:` line is often a note), only under the word the cell's first numbered entry
  uses ("Parallel 1." after "06." "07." is numbered apart), and the text before such a list is its heading ("File 20").
- Counted lists, only where the source says where the count starts: `{{Ordered list|start=N}}` (the numbered-list
  template's real name, also inside `{{columns-list}}`), `<ol start="N">`, a `#` list with `<li value="N">` (every
  Naruto volume was unread). Not counted: a list with its own marker (`list_style_type`), an HTML list whose items
  name another chapter than their place ("Chapter 9" as item 10, after a prologue).
- An entry numbered apart gives no number: special, extra, bonus, side, omake, short, prologue, epilogue, interlude,
  intermission, gaiden, ex, spécial, hors -- as the word before the number or one word earlier ("Special Chapter 2",
  "Extra Scene 3."). NOT vol / part / book / tome / season / arc (Tokyo Babylon numbers its chapters "Vol 2").
  311 lists lose such a number (EN 227, FR 84); 23 more lose a number that had been read out of a title or a
  heading (each one looked at).
- Small readings: `<nowiki>#</nowiki>49`, a full-width colon, `93--99`, `Chapter 2 (Part 1): ...`.
- **5c32881 (review finding, verified):** the first `<ol start>` pattern tried an unbounded `[^>]*` twice from every
  `<ol`; 800 x `<ol start=1 ` with no `>` took 0.65 s and the time grew with the cube (20,000 would run for hours),
  `<li` without `>` was quadratic. Every tag pattern is bounded now (no `<` inside, at most 200 characters, capped
  whitespace), `<ol>` / `</ol>` are collected in one pass, the omnibus name pattern is capped too; 20,000 repeats
  parse in 0.015 s (tests "hostile cells"). All 40,469 cached cells read exactly as with 84951fd.
- **Measured, cache only** (stage 2 built into scratch databases before and after; comic lines): lists of one whole
  chapter 1,252 -> 536 (EN market 143 -> 98, FR 455 -> 157, JP 636 -> 268); volumes passing Mangarr's adjacency rule
  36,066 -> 37,698 (EN 10,516 -> 10,949, FR 7,025 -> 7,385, JP 18,497 -> 19,331); whole chapters claimed by two
  volumes of a line 3,092 -> 2,783; raw cells that parse to nothing 3,082 -> 2,591 (EN articles). On the artifact of
  the offline rebuild, against the published 11-06 file: English one-chapter lists 165 -> 109, English volumes
  passing 10,477 -> 10,917, all languages 35,860 -> 37,493; `volume_chapters` changed on 1,913 volumes.
- **The 165 English one-chapter lists, classified** (167 volume records in 49 articles at the parser): 59 were parse
  misses fixed here. Of the 108 left: about 30 are genuine as listed (one long chapter, an open range "Chapters
  144-", a last volume); about 44 are a number read out of a TITLE ("X/1999 - ...", "365-Step March", "(2–3)" part
  ranges, "Class 2-B"); 19 are Denma's webtoon links; about 15 are shapes still unread (below).

**Verified:** every stage-0 suite green. One full offline rebuild (11-06, after 3 of the 4 commits; the fourth reads
every cached cell and every line name the same): it stops at 8c on the two rules only the LOCAL DNB cache produces
(55 carried German volumes retired; a shared name in w_dc0f270e3cb4) -- the same two as the morning rebuild, and the
only ones. 3f: `dropped_duplicate_number` 29, ids "kept 546, taken 2 (weak 0), left 1" (the one left, rl_cff0e88346db,
is local-cache drift, there before the change); 7b dropped the redirect of v_14bfad9af2dc; no line changed its name,
work, integer or AniList id against the published file. **8d (measure gate, library gate) was not reached locally.**

**What CI must confirm (a local rebuild is not a mirror of CI):**
- 8c green, with the two new rules `is_omnibus=1 ... no place in omnibus_lines_named` and `omnibus_lines_named names
  a line that is absent ...`; export line `omnibus_lines 192` (161 + 31).
- 3f: `dropped_duplicate_number` 44 -> 29; DE exported lines 325 -> 330; `taken 2 (weak 0 ...)`, `left 0`. The
  `taken_ok` entry for dnb:1380197465 in the linker fixture is no longer needed (the carry holds only vol. 4 of that
  line now) and harmless.
- 7b: v_14bfad9af2dc among the dropped redirects; nothing German retired beyond what 11-06 already had.
- 8d: every floor, and the LIBRARY gate -- its ranking puts a non-omnibus line before an omnibus one, so 31 flipped
  flags can move a pick; if the gate moves, read build/measure-library.log (never printed) before publishing.

**Left open:**
- 7b never re-points a `retired` volume redirect when the volume returns under another id (v_1a962f064793 resolves
  to its old line, not to the new vol. 1).
- One season under two publisher names stays two lines (Hayabusa is Carlsen's imprint; the announcement records name
  either). It converges as DNB files each deposited volume into the set; a `hayabu -> carlse` publisher family would
  merge them now but changes JP-round clustering too. Not done.
- Chapter lists: a number inside a title is still read from a `*` entry (requiring the number at the head of every
  entry was tried: it would drop 818 English and 1,543 French numbers, most of them real -- "{{N°}}45 :",
  "Reincarnation 216.", "Kill-17 :"); unread shapes: Roman numerals ("Chapter IV:"), ordinals ("24th day"), a quoted
  label ("Mission:01"), an entry that is a bare number ("* 25"), "Episode 1, part 1–3", "01 Title" with no separator;
  counted lists that restart per arc or case (7 Seeds, Kindaichi, Higurashi, Umineko) are read as the source numbers
  them and overlap inside a line, which Mangarr's rule already refuses; "two lists for one volume" is unchanged.
- The JP-round sections and the edition judgment calls above.

## KR/CN refresh round + chapter lists -- **PUBLISHED 2026-11-06 as `opentome-2026-11-06`** (main 974ae80; sha 71a79453; build-only 42225539914, publish 42226810075; Mangarr pulled it 07:46 CST)

Nick, 11-06 morning: "Push the fixed" (the nine commits 726fc91..974ae80; a one-time word, the rule that Nick
pushes main is unchanged) and "Yes go ahead" for the alert secret. Pushed to GitHub + Forgejo, build-only run green
in 8 minutes (the LoC cache of the 11-05 run was fresh: 3 live LoC requests), publish run green, public manifest and
opentomedb.com/catalogue/version.json both name `opentome-2026-11-06`.

**What the CI log showed (the things only CI could show):**
- LoC follow-up, end to end: `1 carried ISBN(s) no channel delivered -- found 1 [('9789811286315', ['2025398065'])]`;
  "Science battles!" keeps rl_8438f51ce15b / w_76652aa46c96. `krcn-report.json` `loc.follow_up` carries it
  (`loc-report.json` is written before the follow-up and does not).
- No crossed page in CI's cache: `foreign` 0, no WARNING line, `degraded` None.
- 8c `artifact contract ok`, library gate ok, 8d every floor ok. Ids: carried lines kept 543, taken 2 (weak 1, the
  confirmed `taken_ok`), left 0; works created 3 (w_1c81add0d1fc "Seven Sundays", w_8c6958849f0f "Special Civil
  Servant", w_d7ed37cea85d "Bring it on!"); "My secretly hot husband" (en) sits under w_fdd8ef0310ff.
- Against the 10-20 artifact: 13,461 -> 13,464 lines, 125,432 -> 125,468 volumes, 7 lines gone (all German, all
  with an id_redirect: 6 corrections, 1 retired = "The Marshal King Limited Edition" folded into the plain line),
  10 new, 0 lines under another work, romanised aliases 454 -> 455 (`romanised_aliases_carried` 12).
- Measure-gate moves vs 10-20 are 16 days of library drift, none near a floor: DE lines 1,783 -> 1,782, DE volumes
  13,816 -> 13,836, KR/CN DE staged lines 380 -> 395, EN exported lines 70 -> 74, library works 425 -> 428.

**Chapter lists, measured on the published file (Mangarr's adjacency rule; `ot_artifact_measure.py` of the 11-05
session):** English volumes passing 8,570 -> 10,477 (+1,907); English lists of one whole chapter 2,014 -> 165;
all languages passing 29,419 -> 35,860; one-chapter lists 5,909 -> 1,328; 427 lists now carry a half chapter.

**Failure alert:** secret `DISCORD_ALERT_WEBHOOK` is set (2026-11-06, the private #releases webhook). The
`report-failure` job was skipped on both green runs, as it should be; it has NOT yet fired on a real red build
(only its script was dry-run locally). The first red Sunday build is its live test.

**Gotcha found at the publish:** Mangarr's first manifest is opentomedb.com/catalogue/version.json, which the
`pages` workflow redeploys after the catalogue run; Pages kept serving the previous deploy for about 4 minutes
(`cache-control: max-age=600`). A Metadata Update run in that window says "up to date". Wait until the site
manifest names the new label, then run it.

**#beta note posted 11-06** (Mangarr Desk bot, message 1568272446585573387; Nick: "Post it"): the chapter-list
numbers above. **Open:** only the items under "Gotchas / left open" below; none needs Nick.

**Crossed result sets -- where it stands (Nick asked 11-06):** closed for everything that can be checked. CI's
stored sets are clean (`foreign` 0). The one crossed page of the LOCAL cache (`97807595*`, 2026-09-29) was refetched
on 11-06 with `search_set(q, force=True)`: 227 records, 0 foreign (locally `LOC_REFRESH_DAYS` is unset, so nothing
refreshes by age). What stays unchecked is a crossed page of one of the ten SUBJECT searches. Its effect is bounded:
the strangers are dropped record by record (`loc_lines` reads DLC, LCCN, print monograph and KR/CN origin from the
record itself; the channel is never evidence), a published volume the page hides is asked for by ISBN (follow-up) or
turns the build red (alert), and a NEW record on that page arrives at that search's next 28-day refresh. So the
worst case is a new KR/CN English volume up to four weeks late. No further guard is planned.

**What each red rule was -- checked against the live library records on 11-06 (two of the 11-05 guesses were wrong):**

1. `library-created works without a line of explicit KR/CN origin: 2` -- Ize's "Seven Sundays" and "Special Civil
   Servant" (LoC, origin by imprint, explicit 0). Their German edition states 041 $h kor but every volume is still
   announced, so that line is `absorbed`. The planner read the cluster (§9 criterion 2), the gate only exported
   lines. **1b53527:** the gate reads the work's cluster too (docs/krcn-design.md §13 says so now).
2. `published KR/CN lines absent`: rl_8438f51ce15b "Science battles!" v. 8 (+ its work, volume, series integer,
   must_create). NOT a set record displacing it (the 11-05 guess): LoC re-catalogued the record on 2026-10-06
   (lccn 2025398065, 005 20261006): its subjects no longer hold "Comic books, strips, etc.--Korea" nor "Graphic
   novels" + Korea, and its ISBN (978-981-12-...) is under no §4 stem, so NO channel returns it. The record is
   still DLC, 041 eng $h kor, 655 Comics. **801c311 / 4a44729:** `loc_sru.follow_up` -- stage 3f (and 8d's reload)
   asks LoC `bath.isbn=<isbn>` for every ISBN of a carried LoC line that no DLC record of the run carries: a result
   set like any other (cached, LOC_REFRESH_DAYS), a count and a page each, at most 25 a run, listed in
   `krcn-report.json` (`loc.follow_up`: asked / found / gone / unanswered). An ISBN it could not ask for, or a
   follow-up set whose refresh failed, degrades the run (meta `loc:degraded`, no publish). Run live on 11-06: found
   2025398065, and `loc_lines` builds the same line (key loc:2025398065, v. 8, 9789811286315).
3. `taken_weak [rl_9b3ea88520d6, dnb:1380197465, 1, 2]` -- "The Pawn's Revenge - 3rd Season" (DE). DNB did NOT
   delete vol 1 (the 11-05 guess): on 2026-10-30 it re-catalogued vols 1 and 2 (IDN 1307414842, 1362788554) as
   parts of the multi-part set 1278917055 (245 $n "3rd season" $n "1", 773 $q "13rd 11"). The line is vol 4 alone
   under the same name, publisher, work and volume id. **476816f:** `taken_ok` + a `taken_ok_why` text.
4. `E1 alias rows lost: 7` -- six works lost a romanised title because DNB's 240 sits on the publisher-supplied
   announcement record and is gone once the volume is catalogued; `build_dnb`'s half-of-the-volumes rule then drops
   it (56 of the 222 German KR/CN lines with any 240 are under half today, each with ONE distinct title, so this
   would recur every week). **d3769ab:** the export keeps a `romanized` alias row the carry ships on the line that
   shipped it (works in `krcn:ids` only; never another work's own title; before the curated removals; meta
   `romanised_aliases_carried`). The seventh loss ("3 Body Problem 06".."10", per-volume 240s) is kept by the same
   rule: junk, harmless, left alone.
5. Not failing: "My Secretly Hot Husband" (EN, loc:2024941991) was a second work beside its German edition
   (dnb:1357946228). **476816f:** a `link_work` to w_fdd8ef0310ff (same original title in two romanisations, same
   creators).

**Found on the way -- LoC answers with another search's records (a crossed result set).** The first live follow-up
(`bath.isbn=9789811286315`) came back with numberOfRecords 2 and two unrelated records, and with the right two a
minute later. The local cache holds the same thing from 2026-09-29: the `97807595*` page 101-200 has 50 records
without any ISBN of the stem. Every record is distinct and the page is full, so every completeness rule passed and
the search's own records were silently missing. **801c311 / f6fd4c7:** `loc_sru.foreign` checks each page of an ISBN
search record by record (020 / 024 $a $z: as written, as an ISBN-10 under 978, normalised; on the 4,476 cached
records the 50 crossed ones are the only misses); a crossed or malformed page is a failed page (`crossed`,
`malformed`: retried, re-paged, sliced, never stored). `enumerate_loc` counts the foreign records of sets cached
before the check (`foreign` per channel, a WARNING line): CI's cache of 11-05 was read without the check, so READ
THAT LINE in the next log -- such a set heals at its 28-day refresh, and the follow-up asks for any published volume
it hides. A subject search cannot be checked this way (a word match misreads LoC's index; tried, 11 false hits).

**Also done: fe146e8** -- `report-failure`, a second job of catalogue.yml (`needs: build`, `if: failure()`): one
embed to the `DISCORD_ALERT_WEBHOOK` secret's channel, skipped while the secret is unset. It ships nothing; the
build job's steps are unchanged.

**Verified:** every suite of stage 0 green. Full `rebuild_all.sh` offline from the cached records (11-06): of CI's
rules, 1, 3, 4 and the link_work check pass (rule 2 cannot fail locally: the local subject sets predate the
re-cataloguing, so the follow-up was run by hand instead). It still stops at 8c on the two rules only the LOCAL
DNB cache produces (78 carried German volumes retired; a shared name in w_dc0f270e3cb4) -- CI's log of 11-05 has
neither. **A local rebuild is not a mirror of CI**: only the build-only run says green.

**Gotchas / left open:**
- LoC budget: the 4-weekly refresh used 249 of `LOC_MAX_REQUESTS=260` on 11-05 (many diagnostic-61 retries). A
  follow-up adds two requests per missing volume; a run over the cap is degraded and does not publish.
- A curated removal (`corrections/aliases.json` `remove`) of an alias that only the continuity rule keeps goes
  stale after the next publish (the carry no longer has the row, the removal matches nothing and stops the build):
  delete the entry once it has shipped.
- German "The Pawn's Revenge" (seasons under one DNB set, read as duplicate numbers): FIXED locally in 0e9dc54,
  top section.
- The local `.cache`: the crossed `97807595*` page was refetched on 11-06 (227 records, 0 foreign).
- `build/manga-metadata.sqlite` locally is the PUBLISHED 11-06 artifact (sha 71a79453, the id carry; put there on
  11-06, the 10-20 one is `build/manga-metadata.sqlite.published-20261020`); `*.local-20261002` are older local
  files; `build/manga-metadata.sqlite.new` and `build/opentome.db` are the second 11-06 offline rebuild (top section).

## Chapter lists read in full — **PUBLISHED 2026-11-06 in `opentome-2026-11-06`** (pushed 2026-11-05 as main f391b79; numbers in the section above)

- **Why.** Mangarr's chapter builder found that about 17 % of the English chapter lists held only a volume's
  FIRST chapter (v1 `[1]`, v2 `[12]`). Cause, in `tier0/wikipedia_volumes.py` `parse_chapters`: an entry's first
  number was taken and the rest of a range dropped ("Chapters 12–21" -> 12). 3,396 of 29,442 English lists parsed
  to one number; 2,609 of those state a range in the source.
- **What `parse_chapters` reads now** (each with tests in `tier0/test_parser.py`, block "chapter lists"):
  a range at the head of an entry or right after a chapter word in a sentence ("Chapters 12–21", "002–005.",
  "File.27 – File.41"); a range in words after a chapter word ("Chapitres 1 à 12", "Chapters 1 to 7"); an entry
  that opens with its number and goes straight into a quoted / templated title (`07 "Title"`, `Fight 1 {{...}}`,
  `'''Chapitre 14''' : ...`); an entry that is only a chapter word and its number ("Chapter 13"); a half
  chapter as a half (18.5, never floored to 18). Reviewed twice by a separate reviewer against every raw list
  (both rounds' findings fixed; the reviews and probe scripts were scratch files, not kept).
- **What it refuses, on purpose** (a whole number that is not there is the costly mistake: it makes a good volume
  contradict its neighbour): a pair after a word for something numbered apart (special, extra, bonus, side, part,
  volume, book, season, arc, ... and the French ones); a descending pair, a span over 150, a pair ending on a
  date / time; "5 - 10 Things" (a title), "01-2" (a part of a padded chapter); every pair of a list in which two
  pairs start alike ("Block 3-1", "Block 3-2" = parts); a bare entry when the list numbers its entries with another
  word (acts under an episode); a decimal or date with no separator ("103.5 Title", "24.12.2029") gives nothing;
  a number inside quotes that opened before it (`"After 7"`, `''Sample 009'' Part II`) unless a separator, a
  template or a title follows the closing mark or the word is a chapter word.
- **Half chapters are JSON numbers** in `composition.ref_list` and so in the artifact's `volume_chapters`
  (`[21, 22, 23, 23.5]`). The export copies the text; Mangarr reads a list of doubles and treats a half as an
  optional extra. Nothing writes the string form shown in `schema/schema.sql`'s comment.
- **Measured, cache only, no network** (4,270 English + 1,553 French articles; stage 2 built into a scratch
  database before and after, with `_get` replaced by a cache-only reader; same volumes, lines and works). Lists
  that parse to one number: English 3,396 -> 779, French 750 -> 515; lists with text and no number: English
  3,493 -> 3,082, French 2,592 -> 1,483. Volumes with a chapter list 42,254 -> 44,150 (462 with a half chapter).
  Comic lines: one whole chapter 5,876 -> 1,264 (English market 2,004 -> 143); neighbouring volumes whose lists
  adjoin 28,911 -> 34,814 of 38,016; volumes that pass Mangarr's adjacency rule (unbroken, no overlap, confirmed
  by a neighbour) 29,565 -> 36,128 (English market 8,582 -> 10,524). In 119 lists a number the old code read is
  gone, each a floored decimal, a date, or a number inside a title. Whole chapters claimed by two volumes of a
  line 2,949 -> 3,096: numbering that restarts every volume, now read in full. Output is identical on Python
  3.9 and 3.14 over all 40,469 lists; the whole corpus parses in about 1.5 s.
- **Not run locally: the full `rebuild_all.sh`.** The measure gate needs the private library fixture (CI secret)
  and the local carry is the 2026-10-02 artifact. The export only copies `ref_list`, and `export/test_artifact.py`
  has no rule on `volume_chapters`; no id, line or ISBN changes. The build-only run is the check.
- **Next.** Nick pushes main (github + forgejo) -> build-only CI green -> publish (`catalogue`, `publish=true`) ->
  Mangarr Metadata Update -> FlightLog line. Then re-measure on the published artifact before any public wording
  (Mangarr beta.5 notes) quotes a number.

### Chapter lists: measured leftovers (as of 11-05; the 11-06 round at the top fixed the numbered-apart words, the
### `<br>` / `#` / `:` shapes and the counted lists -- what is still open is listed there)

- **Two lists for one volume** (646 volumes: the English and the French article describe the same original
  volume and disagree). `export/to_mangarr.py` keeps whichever row comes last (`comp_ch[vid] = ref_list`), in 468
  of them the shorter. "Unbroken run first, then longest" would add about 480 trusted volumes on JP lines and
  none on English lines, so it was left; a better rule would use the neighbours.
- **First numbers after numbered-apart words are still emitted** ("Bonus 1: ...", "Special chapters 1–2", a part
  number inside a title): about 415 lists, false whole numbers that pre-date this change. Dropping them is safe
  after special / extra / bonus / side / epilogue ..., NOT after part / vol (some series number their chapters
  "Vol N").
- `<br>`-separated lists and `#` / `:` lists read one number per `*` entry (about 90 lists, 16 articles); entries
  such as "Sample Story act.50" (two words before the number, no separator), `<nowiki>#</nowiki>425` and a quoted
  label whose word is the series' own (`"Mission:01"`, 16 lists) read nothing.
- Still expanded, by the reviewer's made-up inputs only (no list in the corpus): "Chapter 1-2: Title" (a part
  number, unpadded, alone in its list), "1-1. A / 2-5. B", "issues 12–20 of a magazine" in a sentence;
  `Top 10 "Things"` and `1945 "Title"` read their number.
- Edition lines without the omnibus flag: looked at on 11-06 (top section, item 2). Lines that say omnibus are
  flagged locally (c8691e6); collector's / bunkoban / kanzenban and the like are judgment calls, listed there.

## Labelled-run lines + Re:Zero spin-off aliases — **on main, awaiting Nick's push + a build** (2026-10-20)

- `prefix_run()` in `export/to_mangarr.py`: a line with NO plain-numbered volume whose labels are one run
  ("Ex, Ex2 ... Ex6", "APPEND1..5"; bare prefix = 1; exactly 1..n) exports them as volumes 1..n instead of
  `volumes_special`, which Mangarr never reads. Measured on opentome-2026-10-20: 8 lines -- Re:Zero (Ex) EN + JA,
  Re:Zero Ex JA, Monogatari (Box sets) EN, Strike the Blood (Side-stories), Tokyo Ravens EX1-4, Saekano FD/FD2,
  Hatena Illusion R/R2. Singletons (Roman, Fanbook, DJCD) and mixed lines stay specials.
- `aliases.json`: the Yen Press series titles for Re:Zero (Ex) and Re:Zero (Short story collections) -- Mangarr
  searched the display names ("Re Zero Short story collections"), which no release carries.
- Watch on the build-only run: the JA Ex ISBNs are on two JA lines (Re:Zero (Ex), Re:Zero Ex) -- now as numbered
  volumes on both.

## `cover_url: "none"` corrections — **PUBLISHED 2026-10-20 as `opentome-2026-10-20`** (main 0d27ff0; sha 717514ce; build-only 39504191996, publish 39504985695; Mangarr pulled it the same evening)

- A `corrections/volumes.json` `cover_url` entry may now carry `"none"`: it removes a wrong ISBN-lookup cover
  when no source has the right one (no cover beats a wrong one; Mangarr falls back to its own). `pick_cover()`
  in `export/to_mangarr.py`, the value check in `tier2/corrections.py --check`, and `test_artifact.py` asserts
  the cover is NULL. First two entries: Goblin Slayer manga Vol. 1 (Open Library's cover is an interior page)
  and The Apothecary Diaries manga Vol. 1 (Japanese cover). Google Books stays excluded (Nick, 2026-10-20).
- Build-only 39502780586 (d5bd564): both cover corrections applied and asserted; RED only on E1 — DNB fixed the
  German Reincarnation Damage Control line's working title, dropping the alias 'Rückkehr in meine Welt'. Added to
  `ALIAS_LOSS_OK`. Next: Nick pushes main, build-only again, then publish.

## `rank-class-first` — **MERGED (main 0a9ee09) + PUBLISHED 2026-10-18 as `opentome-2026-10-18`** (sha 9e948677; build-only 39158199134, publish 39158706597; Tower pulled it 14:32 CDT; Mangarr beta.2 = 899 carries the class-first Rank)

### (was) Branch `rank-class-first` (2026-10-17) — the round C follow-ups

- **Lookup replay = Mangarr 10.0.0.897.** Mangarr's catalogue `Rank` now puts the library's class before an exact
  name (a manga entry keeps the manga line even when the light novel's line is named exactly the title).
  `display_names._rank` and `measure_library.rank_new` mirror it, so round C's `held-lookup` lines (The Water
  Magician EN light novel and the others in `round-c-report.tsv`) are released on the next build. **Publish only
  once a public Mangarr release carries the new Rank** (live on the build server since 897; the public beta
  image still has the old order, where an exact-named novel line beats the manga line for a manga entry).
- **Measure gate reads the library class.** `snapshot_library.py` records `novel` (Mangarr's `~ln` foreign id) and
  `measure_library` ranks those entries as light-novel lookups; the class-first replay otherwise failed Re:Zero and
  SAO (light-novel entries replayed as manga lookups). The `OPENTOME_LIBRARY_JSON` secret was re-set 2026-10-17
  with `novel` on the 5 entries that were light novels when the snapshot was taken (local copy in Nick's scratch,
  never in git). Build-only run 39093387939 GREEN: library gate ok, renamed 247 -> 250, `held-lookup` 3 -> 0,
  everything else as on main (`moved: 15` is on main too).
- **No origin guard in `resolve_anilist.pick()` — decided against (2026-10-17).** Measured: of the 76 bound EN
  manhwa/manhua lines, 2 have an AniList `countryOfOrigin` that disagrees (Raiders 40230, Black God 30982) and
  both bindings are right (AniList flags them JP). A Mangarr-style guard would unbind two correct lines and
  fix none; the KR/CN works' path already searches by country.

_Last updated: 2026-10-01 (KR/CN lift published as opentome-2026-10-02)_

## Branch `round-c` (2026-10-02, NOT merged, NOT published) — line names

Spec/plan: docs/superpowers/specs|plans/2026-10-02-round-c* (local, gitignored); reader doc `docs/round-c.md`.
Ledger: .superpowers/sdd/2026-10-02-round-c/. Trigger: MangarrBot request #1 (The Water Magician).

**Local build GREEN (2026-10-02, carry = public `opentome-2026-10-02` sha `930e12ac…`; artifact sha `19b0d22d…`):**
13,551 → 13,463 lines (88 merged: 24 T-extend, 16 T-duplicate, 48 W2-duplicate; 28 kept + 3 kept beside an M
retag), 247 lines renamed (94 D, 132 W, 12 D+S, 3 D+W), 6 retagged (M); lines with a parenthetical 2,310 → 2,001;
0 lost ids, 1,494 carried ids redirected, moved 0 (910 excluded as recorded round C merges), measure 49/49.
The Water Magician EN manga → `The Water Magician (Part 1)`; the EN light novel keeps `(novel series)` (held-lookup:
the bare title would win a manga-library lookup in Mangarr).

- Export-time names (`export/display_names.py`, called from `export/to_mangarr.py`): D strips only a BARE kind
  disambiguator of the work title ("(novel series)", "(manga)"…); a qualified one ("(Ito manga)", "(1994 manga)")
  stays, because stripping it bound other adaptations on AniList (measured). S, W, M as the spec says; guards
  within-work, cross-work (D only), ISBN, medium (origin/main/parent), lookup replay, origin pairing (held-origin).
  Ids hash the pipeline name, so renames move nothing; every name-based export decision reads the pipeline name.
- Stage 4c2 (`tier0/round_c_merge.py`): T tails and W2 duplicate sections merge into the work's own line —
  extend only when contiguous (Gamaran's "31+" tails continue the sequel: kept, reason gap), duplicate when every
  number matches by ISBN or has none. Carried merges re-apply only when this build agrees (else carry-conflict).
  7b redirects them (ISBN vote, plus an explicit round C step for ISBN-less merges).
- Gates (`export/test_artifact.py`): moved-id exclusion only for recorded merges the redirect confirms; re-ship
  rule with the conflict exemption; within-work and cross-work name rules relative to the carry (150 pre-existing
  DNB duplicate-name groups are noted, not failed).
- Reports in `build/`, uploaded by CI: `round-c-report.tsv` (one row per line, lookup column),
  `round-c-anilist.tsv`, `round-c-unmatched-disambiguators.tsv` (44 rows: qualified tags left for review),
  `round-c-mainless.tsv` (5 JA novel groups left without a main line by M retags; is_main unchanged).
- AniList moves checked against AniList (controller): Ghost Hunt and Liar, Liar now bind the right manga; the two
  wrong binds the qualified strips caused are gone with the bare-only rule.

Gotchas:
- A local build overwrites `build/manga-metadata.sqlite`; restore the public artifact before using it as a carry
  (copies in `build/round-c-before/`). Don't set PREV_ARTIFACT locally: `merge_aliases.py` then re-adds removed
  aliases (CI never sets it).
- Mangarr follow-up: its title Rank prefers an exact name of the other library over the library's own class; once
  fixed, held-lookup lines can be released.

Next: Nick merges `round-c` → main and pushes; build-only CI compared with this build; publish; Mangarr
MetadataUpdate on Tower + lookup check (The Water Magician); FlightLog; Nick runs `/fixed 1` in Discord.

## 2026-10-01 — branch `krcn-lift`: the KR/CN hold (R6) lifted

Spec/plan: docs/superpowers/specs|plans/2026-10-01-krcn-lift* (local, gitignored). Ledger:
.superpowers/sdd/2026-10-01-krcn-lift/progress.md. Design notes: `docs/krcn-design.md` §9 / §11 / §13 and the
R6 ruling; `docs/krcn-market.md` "The R6 hold (lifted)" and "Lift build".

**PUBLISHED 2026-10-02 (UTC) as `opentome-2026-10-02`** (sha256 `9f6ceec7…`; publish run 36945152362; build-only
run 36943425972 green and row-for-row identical to the gated local build). Merged to main at b8a2a6b (Nick merged
it). Mangarr 10.0.0.857 pulled it (MetadataUpdate cmd 326970, Tower file sha `9f6ceec7`); lookups of the FR-only
"PK" (Player Kill, `rl_317210cccfe3`), "Palais" and "Sabre et dragon" each return their line as an `fr` fallback
under an English-only edition chain. FlightLog LEDGER 2026-10-01 19:25 (backup `before-20261001-1917-krcn-lift`).

**The public release is the REBUILD `930e12ac…` (publish run 36945214575, 00:29 UTC), not `9f6ceec7`.** Two
copies of the same Claude session (a terminal `--resume` and a desktop fork) ran Tasks 17–18 in parallel; the
second publish run rebuilt the same commit b8a2a6b with `9f6ceec7` as its carry, so every series and volume row,
every binding and the measure are identical — only `meta.carried_from` / `carried_sha256`, `krcn_ids.created`
(empty: the 371 works are carried now), `krcn-duplicates.tsv` (empty) and `status-transitions.tsv` (no
transitions) differ. Tower kept `9f6ceec7` until Mangarr's daily metadata check pulled `930e12ac`; both runs posted
the same "Catalogue published" embed in Discord #catalogue. Gotcha: never run one session twice (`claude --resume`
in a terminal while the desktop app holds the same conversation) during a publish round.

Shipped:
- The 408 held clusters of catalogue run 44 (`krcn-held.tsv`, 444 lines) → **371 new library works**, 53 frozen
  (published ids kept), 0 held, 91 review rows, 0 lift lines dropped. Exported: DE 327 lines / 1,399 volumes,
  FR 176 / 986, EN 70 / 399; 424 library works. The flood gate was exempted by anchor-key id for this build only.
- Anchor: the comic line with the lowest key in any market (`bnf:` sorts before `dnb:`, so a DE+FR cluster anchors
  on its French line); a frozen work anchors on the line its id hashes, titled with the carried name.
- Joins in `corrections/lines.json`: 22 `cluster_with` (the DE and FR halves of one work, e.g. Bibi) and 8
  `link_work` (Athanasia → Who Made Me a Princess, Hanami, Chronicles of the Cursed Sword with `override_jp_guard`,
  …); the `review` shape stops a build on a cluster until it is read. `tier2/corrections.py --check` validates all.
- Duplicate gate: `build/krcn-duplicates.tsv` (29 rows this build) against
  `export/fixtures/krcn_lift_duplicates_reviewed.tsv` (30 `not-a-duplicate` verdicts); rows at ≥ 0.9 and every
  AniList-id row block without a verdict or a correction.
- AniList 8a families `krcn-KR` / `krcn-CN` / `krcn-TW`: 369 works considered, 239 bound, 0 collisions, every
  binding read (`build/krcn-anilist-bindings.tsv`); 5 pins (2 unbind `null`; 38 in `corrections/anilist.json`).
  Projected dates are re-resolved after 7b (`tier2/resolve.py --dates`, `dated_by_now`).
- Floors raised (`export/measure_library.py`): DE 278 / 1,189, FR 150 / 838, `KRCN_MIN_WORKS` 360. Measure 49/49;
  carried ids 0 lost; German JP round unchanged.
- Review: 20 plan tasks, each task-reviewed, whole-branch review clean; fix rounds F1a–F6 are in the ledger.

Gotchas:
- `export/fixtures/krcn_lift_input.tsv` is DELETED (this commit): its lift-input rule and the flood-gate exemption
  ran only while it existed.
- The `cluster_with` entries STAY — they are not cleanup. Without one, the two halves it joined are decided as
  separate clusters again.
- A `cluster_with` / `review` key whose line is published and now placed elsewhere prints `CLUSTER_WITH SKIPPED` /
  `REVIEW SKIPPED` and is harmless (delete the entry when convenient).
- A weekly build that stops on a `review` entry whose line the linker now links, or whose reviewed cluster has
  gained a carried (published) line (`lines.json review <key> (cluster <cid>): it holds the published line …`):
  delete that entry, or replace it with a `link_work`.
- The duplicate gate is permanent: a new row needs a correction or a verdict in the reviewed fixture.
- A wrong binding with no right AniList entry gets an unbind pin (`anilist_id: null`), which 8a respects in every
  later run. The R2 ceiling is off only for the krcn-* families.
- A successful local build moves its artifact over `build/manga-metadata.sqlite`: copy the published artifact
  back before the next local build, or the build carries from itself.

## 2026-09-29 — branch `heading-cleanup`: section headings and KR/CN medium (cleanup round A+B)

Spec/plan: docs/superpowers/specs|plans/2026-09-29-heading-cleanup* (local, gitignored). Ledger:
.superpowers/sdd/2026-09-29-heading-cleanup/progress.md.

Done:
- Class-1/2 Wikipedia section headings ("Médias", "Parution", "Liste de volumes", "Tomes N à aujourd'hui",
  "Roman illustré"…) no longer name a line — `release_lines.GENERIC` / `PAGINATION` / `HEADING_MEDIUM_HINTS`.
- **Pure-duplicate guard** (`release_lines.hold_clashes` / `hold`, `build_corpus` two passes, `meta corpus:held`):
  a heading group falls through ONLY when every volume already exists on an existing line of the work with the
  same ISBN. Otherwise it is held exactly as before the round (name, medium, heading alias). A fall-through never
  creates a line, moves main or re-parents. Heading medium hints apply only to groups that fall through.
- Stage 7b follows a carried line whose medium changed (ISBN / dated-volume majority, else retire / orphan).
- New stage **4b2** `tier0/comic_medium.py`: 'manga' lines of a KR/CN/TW-origin work → manhwa / manhua
  (`to_mangarr.origin_markets`, now module level); folds a same-name duplicate only when the two agree volume by
  volume; a work with a `differ` pair is left untouched; library (DNB/KR-CN) and corrected lines never fold;
  `meta.comic_medium` holds flips / merges / kept / differ / guarded (unioned across re-runs).
- Contract: krcn_lines_pre ids may follow a duplicate_merge / correction redirect; E1 treats 4b2 flips as explained.
- Local build (eba2076, published carry 53c64146): 27 duplicate heading lines merged, 269 carried heading lines
  held (164 groups), 29 KR/CN lines retagged (23 manhwa, 6 manhua), Recast folded; 323 moved ids (under 500, no
  allowance needed — plan Task 7 skipped); 0 lost ids, 0 lost ISBNs, 0 copies; E1/E3 0; library 49/49; German JP
  round unchanged apart from King of Hell DE (a 4b2 flip).

**PUBLISHED 2026-09-29 17:01 as `opentome-2026-09-29`** (sha256 `c91484c4…`, catalogue run 44); merged to main
(bbc5784 was main when the lift branched). It is the carry the KR/CN lift built on.

Gotchas / left for round C:
- Held class-2 lines keep their pre-round 'manga' medium (Hyouka (Roman), Goblin Slayer / Tsukimichi (Roman
  illustré), Naruto (Novelizations), Maburaho, Solo Leveling FR (Roman web) and DE). Continuation lists
  ("Tomes 31 à aujourd'hui") stay separate lines. Round C (spin-off naming) relabels / renames them.
- Solo Leveling KR keeps its manga + manhwa pair (the two editions disagree on 13 volumes).
- `novel series` / `webtoon` are work-title disambiguators, not headings — round C.
- 3e prints "NO SUCCESSOR for 41": KR/CN lines 3f adopts after 3e; all present in the artifact (benign).

## 2026-09-27 — branch `krcn`: Korean / Chinese editions (DNB, BnF, LoC)

Design: `docs/krcn-design.md` (spec + R1–R7 rulings), market doc: `docs/krcn-market.md`.

**PUBLISHED 2026-09-29 as `opentome-2026-09-29`** (sha256 `53c64146…`; publish run 36580345557;
build-only 36578803076 green). Merged to main at aceb1a8 (Nick merged it). Mangarr pulled it
(MetadataUpdate cmd 320631). The controller runbook C0–C9 is done:
- **C0:** LoC enumerated on a GitHub runner (run 36561675299), because this workstation's IP is
  blocked by lx2.loc.gov. Result: 3,742 distinct, 177 live, not degraded. Two rulings on the
  way: stems announcing > 500 positions are sliced before reading (`WINDOW`, 757f38a); a set is
  read ONCE and its gap is reported, not failed (option 1, bcb6fbf). 52 positions are
  unconfirmed across 14 sets (`.cache/loc-dups.json`). The LoC round used 395 of its 400 requests.
- **C3:** the first full build and its checks. The German JP round is unchanged (4,340
  `dnb_line` keys). Library 49/49; 0 carried ids lost.
- **C4 (fd771b4):** exported floors at 85% of the first build; see `docs/krcn-market.md`
  "First build".
- **C5 (aceb1a8):** 53 new works labelled `must_create`. Delusion `dnb:1362776327` ships under
  w_015d8619f82f via `link_work`.
- **C6:** AniList ran in CI's 8a: 33 pins applied; EN lines without an id are within the allowance.
- **C7:** new seed uploaded to `opentomedb/opentome-cache` (full local `.cache` minus 458
  cached Google Books responses left over from the tier1-crossverify spike, which nothing reads);
  `seed-cache` run 36578693497.
- **C8:** published. The M1–M8 Mangarr follow-ups (§14 of the design) are recorded in Mangarr's
  HANDOFF.
- **Still open:**
  - The 458 Google Books files remain in this workstation's `.cache`. Deleting them is Nick's call
    (clean-room rule).
  - English KR/CN volumes are thinly dated: 107/395 exported. LoC CIP records are
    announced-only, and dates come only on single-volume records.

Gotchas from the 09-29 run:
- **Local builds cannot reach LoC** (connections from this IP are closed instantly since ~09-27).
  Build locally with `LOC_OFFLINE=1 LOC_UNREACHABLE=1`. The canary otherwise forces a live
  request and fails 3f. CI runners do reach LoC, so LoC refreshes only in CI (28 days) or from
  a runner, the reverse of the plan's P13 note.
- **`DNB_REFRESH_DAYS=6` in CI.** A refresh can bring new KR/CN works. The first-build rule
  "unlabelled new works" is only a hard fail while the carry has no `krcn_ids`; since this
  publish it has them, so new works are reported, not failed.
- **Pushing to main from a Claude session is blocked** by the auto-mode classifier (CI bypass /
  merge without review). Nick pushes, or adds a permission rule.

Done (design `docs/krcn-design.md`, results `docs/krcn-market.md`):
- Stages: **3f krcn** (Korean / Chinese print editions, after 3e dnb: DNB `spo=kor`/`spo=chi` +
  `IMPRINT_Q` split, BnF publisher channels, LoC DLC-created records; lines link to existing
  works, merge by ISBN, cluster across markets; works created only with an English line, the
  rest held; ids adopted before 4c/7b).
- New modules: `tier0/lib_sru.py` (the shared polite-SRU base: throttle, whole-set cache,
  netlog, `_OFFLINE`, degraded mode, canary hook), `tier0/loc_sru.py` (the R7 paging ladder:
  100→50→25, then slices; duplicate-position handling), `tier0/loc_marc.py` (LCCN, `$q`
  volumes, `263` YYMM, `008`, DLC/encoding-level, origin, comic/prose classification),
  `tier0/bnf_sru.py` / `tier0/bnf_unimarc.py` (BnF client + UNIMARC field map, 101 $c origin),
  `tier0/krcn_lines.py` (lines per source), `tier0/krcn_identity.py` (carry lookup, split/take
  rules), `tier0/build_krcn.py` (stage 3f itself), `tier0/krcn_replay.py` (jp-snapshot /
  jp-diff), `tier0/test_krcn.py` (stage 0).
- Changed: `tier0/dnb_link.py` (`fold()` keeps Hangul -- NFC after the combining-mark strip,
  U+AC00–D7A3 added, a 2-syllable minimum for Hangul-only keys; the KR/CN work set and the new
  JP out-of-scope test; the full-name author rule for KR/CN lines), `tier0/dnb_enumerate.py` /
  `tier0/dnb_sru.py` / `tier0/build_dnb.py` (the new channels, `DNB_MAX_REQUESTS`, the
  `IMPRINT_Q` split, P25 deferral to the JP round), `tier2/corrections.py` (`link_work`, R2),
  `tier2/resolve.py`, `schema/schema.sql` (`clean_claim` gains `us_gov_pd` -- the
  `krcn_line`/`krcn_member`/`loc_member` staging tables are `build_krcn.STAGING_DDL`, not
  schema.sql), `schema/load.py` (`LICENCE["loc"]`), `export/to_mangarr.py`
  / `export/test_to_mangarr.py` / `export/test_artifact.py` (the KR/CN contract rules of §13),
  `export/measure_library.py` (staged KR/CN floors), `export/publish.sh`, `tier1/enrich_more.py`
  / `tier1/covers.py` / `tier1/verify.py` (Open Library per-ISBN cache keys), LICENSE-DATA.md,
  `docs/id-scheme.md`, `corrections/README.md`.
- Fixtures: `export/fixtures/krcn_lines_pre.json` (the 54 existing KR/CN works' EN/FR/DE line
  ids + the 3 library-fixture lines), `export/fixtures/krcn_linker_labels.json` (`must_link`/
  `must_not_link`, plus `taken_ok`), `export/fixtures/krcn_new_works.json` (empty until C5).
- CI (this task): `LOC_REFRESH_DAYS`/`BNF_REFRESH_DAYS` = 28 on the weekly cron,
  `LOC_MAX_REQUESTS` = 260; a "LoC reachability" and a "BnF reachability" step, each a single
  probe that appends one line to `build/loc-netlog.tsv` / `bnf-netlog.tsv` (lib_sru's columns)
  and on failure sets `LOC_OFFLINE=1`/`BNF_OFFLINE=1` plus `LOC_UNREACHABLE=1`/`BNF_UNREACHABLE=1`
  rather than failing the job; the source cache is saved by a final `actions/cache/save` step
  gated on the `build/sources-complete.marker` marker (see Gotchas); the KR/CN files
  (`krcn-review.tsv`, `krcn-held.tsv`, `krcn-new-works.tsv`, `krcn-report.json`,
  `loc-report.json`, `loc-netlog.tsv`, `bnf-netlog.tsv`) added to the run's uploaded artifact.
- Docs: `docs/legal-position.md` (LoC row + the §105-inference note), README.md (LoC in the
  sources list; the Ize/Yen-heavy English-coverage sentence, R4), `docs/german-market.md`
  (a short pointer: KR/CN German lines are `krcn_line`, not `dnb_line`; the JP gates are
  unchanged), `docs/krcn-market.md` (new: sources, scope, keys/identity, R6, files, gates, the
  spike table, an empty "First build" section for C4).

Measured request counts (Tasks 7-9):
- **BnF (Task 7):** 11 live requests total (cap 20); a rerun made 0 (fully cached).
- **DNB `spo=kor`/`spo=chi` (Task 9):** 80 live requests, all HTTP 200 (netlog 454 → 534
  lines); reruns made 0 (fully cached). The 14 P25 parent sets that split across the JP and
  KR/CN rounds are deferred whole to the JP round (exactly as predicted); the set-level split
  itself is a follow-up left for Nick (see "Open for Nick" below).
- **LoC (Task 8): BLOCKED, not finished, not fully cached.** 140 of the 400-request cap used
  (5 probe + 16 run 1 + 102 run 2 + 17 run 3); the gateway closed the connection instantly on
  three consecutive requests after ~120 requests in ~25 minutes, which reads as throttling
  rather than a paging fault. The controller's ruling: **stop live LoC now.** The live
  enumeration becomes **controller step C0**, before C1: a >=24h cool-off (not before
  2026-09-28 ~23:00 CDT), `LOC_INTERVAL` **20 s** start-to-start (the already-committed
  default -- pages may slow to ~10 s under strain; watch for a full page slowing from ~3 s to
  >=8 s as an early warning), a session cap of 260 (the remaining budget under the 400 total),
  stop on a second `RemoteDisconnected`/refusal and escalate to Nick -- no further automatic
  retries, estimated 165-230 requests for a complete enumeration. Only 1 of the 24 LoC
  channels (`bath.isbn=97984009*`, 55 records) is complete in the cache today.

Controller steps still open: **C3** (first full build, needs C0 done first), **C4** (set the
exported floors + fill `docs/krcn-market.md`'s "First build" section, same commit), **C5**
(label `krcn-new-works.tsv` by eye, re-verify the linker fixture), **C6** (AniList for the new
EN lines -- automatic in 8a, no separate step needed beyond letting CI's build-only run make
the ~8-30 requests), **C7** (regenerate and upload the CI cache seed, dispatch `seed-cache`,
then a build-only CI run), **C8** (publish -- Nick's gate, only after a green build-only run
with `CARRY_SHA256` set and no degraded flag).

Gotchas:
- **C0 ruling 2026-09-29: an ISBN stem over the 500-position window is sliced before any page.**
  LoC blocks the workstation's IP since the 09-27 burst (a GitHub runner is served), so C0 runs on a
  runner. There, `97988554*` (564) was re-read at 100/50/25, and each read found records the others
  had missed (`LocIncomplete`, 51 requests). `loc_sru.WINDOW` = 500 now sends any stem whose count is
  over it straight to its ten prefixes (`9781975*` 1,551 and `97988554*` 562 today; every subject
  channel is under 500).
- **Option 1, one read (Nick 2026-09-29): a LoC set is read once and a gap is reported, not failed.**
  On the runner, even the slice `979885540*` (223, under the window) returned new records on every
  re-read ([0, 5, 1] at 100/50/25), so the 09-27 rule of confirming reads could never pass on the Yen
  stems, and re-reading costs ~7x the pages, past the 400-request budget. `_verified` now accepts the one
  read; `announced - distinct` goes to `loc-dups.json` / `loc-report.json` as `unconfirmed`. It is never
  `degraded` and never blocks. More distinct than announced is still `LocIncomplete`.
- **Until C0 is done, run this branch's `rebuild_all.sh` / `build_krcn.py` only with
  `LOC_OFFLINE=1`.** Without it, stage 3f pages LoC live and would re-enter the throttling the
  cool-off exists to avoid. Offline, an uncached LoC channel fails the stage loudly (R7) --
  that is the intended behaviour until C0 finishes.
- **3f cannot re-run after an adoption.** Adoption moves staging rows and remaps their volumes
  onto the surviving public id; a second `unload`/reload on the same catalogue after that point
  is not supported.
- **The new-work fixture must be labelled (plan C5) before the first publish.** 8c fails on an
  unlabelled `krcn-new-works.tsv` row by design (P19).
- **Regenerate the seed from the full `.cache`, and merge the manifests as JSON.** The LoC /
  BnF result sets and `.cache/loc-sets.json` / `.cache/bnf-sets.json` are in the local cache
  now. When building the seed side directory, merge each `.cache/<src>-sets.json` manifest as
  JSON (union the entries) rather than copying only the files the seed is missing --
  copy-only-missing drops set entries a CI run itself fetched that never got a corresponding
  new cache *file* the naive diff would notice.
- **A copied catalogue keeps its old `clean_claim` view.** `clean_claim` is a SQL view baked in
  at schema-creation time; a catalogue copied from before this round predates `us_gov_pd` and
  will silently exclude every LoC claim from the commercial subset; a fresh build recreates it
  from `schema/schema.sql`.
- **Ize ECIP records resolve their medium only through the review file or a later LoC
  upgrade.** A level-5 Ize record (no `041`/`082`/`050`/`655`) has no classification signal of
  its own; it either matches an existing DE/FR sibling's medium or goes to `krcn-review.tsv`.
- **BnF origin inheritance is child-first.** A child record's own `101 $c` always wins over its
  head's; it inherits the head's KR/CN origin only when it has *no* `101 $c` of its own (a
  non-KR/CN own origin, e.g. `jpn`/`fre` under a `kor` head, is `origin_out_of_scope`, never
  overridden). Measured exposure today: 0 of 3,438 cached BnF records hit the inheriting case
  with a non-empty non-KR/CN own origin.
- **A carried KR/CN line never demotes.** 8c's `run_krcn` fails on any `krcn_line` row with
  `carried=1`, `exported=0` and role `held` / `review` / `unlinked` (absorbed / merged rows stay
  7b's). The fix for a real one is a `link_work` correction. Step 5 of `decide` first resolves the
  line's published work through the carry's work `id_redirect` rows and the carry's adoptions.
- **An adopted work is re-adopted every build, never split.** A catalogue line (Wikipedia, 3e)
  whose published work is a library work id now sits under an internal Wikipedia work W: 3f
  renames W back to the public id (step 7), and every placement of that public id -- a
  `link_work`, a frozen cluster, a kept line -- goes to W first. `link_work` may name a
  Wikipedia work, a published library-born work, or an adopted public id -- never an id the carry
  redirected (stale; the log names the id to use); 8c's `run_link_work` reads the corrected work
  through `krcn:adopted` renames and counts `adopting` lines as shipped. A public id whose present
  lines now sit under SEVERAL works stops 3f (load's SystemExit names the works, lines and public
  id): decide with a `link_work` correction.
- **`loc:offline` / `bnf:offline` are NOT blocking.** When CI's probe finds a gateway
  unreachable, 3f records `{"reason": "unreachable", "stale_sets": N}` (N = result sets served
  past their refresh window) in catalogue meta and `krcn-report.json` and prints a NOTE; the
  export does not copy it and `publish.sh` does not refuse it (P13). Only `loc:degraded` /
  `bnf:degraded` (a refresh that failed mid-run) still block. `unload` clears both.
- **The CI cache is saved once the library sources are complete, even if a later gate fails.**
  `tier0/rebuild_all.sh` removes `build/sources-complete.marker` before 3e and writes it right after
  3f; `catalogue.yml` restores with `actions/cache/restore` and its last step
  (`actions/cache/save`, the same key `opentome-cache-<run id>-<attempt>`) runs when the run was not cancelled, the marker exists and the
  restore was not an exact hit. A failure after 3f keeps that run's LoC / BnF / DNB fetches; a
  failure or kill before the marker saves nothing (as before). Stage-4+ cache writes saved along
  with it: Open Library per-ISBN entries are tmp+rename; openBD / OL batch JSON (`verify._fetch`),
  BnF per-ISBN XML (`enrich_more._fetch_xml`) and AniList (`resolve_anilist._cache_put`) are single
  whole-file writes of an in-memory response, not tmp+rename (partial only on an OSError mid-write).
- **3e's DNB stop carries into 3f.** `build_krcn.run` seeds `dnb_sru.DEGRADED` from catalogue
  meta `dnb:degraded` (3e's value; read after `unload`), so 3f serves stale DNB sets from the
  cache instead of re-requesting DNB after 3e was throttled; the run is then DNB-degraded.
- **3e's linker index skips 3f's works** (meta `krcn:works_made`), so a `KEEP_DB=1` rerun of 3e
  after 3f reads the same index a fresh build's 3e reads. `same_ids` (8d) no longer rewrites
  `build/loc-report.json`, and a reserved (JP-round) id is never taken in step 2 either.
- **Only `taken_weak` and the demotion rule block publishing** among the KR/CN id checks; of
  `krcn-report.json`'s `gate` lists only `taken_weak` blocks (the others --
  `left`, `kept_no_overlap`, `absorbed_weak`, `p22_thin`, `work_redirects`, `adopt_conflicts`,
  `carried_not_exported`, `carried_work_changed`, `hangul_only_authors`, `authors_differ`,
  `deferred_to_jp_round`, `jp_guard_overrides` and `adoption_isbn_clash` -- are informational,
  per `build_krcn.gate_report`'s docstring). A `taken_weak` entry `[line key, carried id]` is
  confirmed as safe only through `export/fixtures/krcn_linker_labels.json`'s `taken_ok` list.
- **A refresh that re-clusters DE KR/CN lines counts toward `run_ids`'s retired-line cap of 10**
  (§13 "Watch"). The carry lookup before minting (§8) keeps a re-clustered line from being
  re-keyed if it was already published -- a trip against the cap is a real change worth looking
  at, not an artifact of the cap itself.
- **Step 5 of Task 14 (the offline pipeline-order dry run) must be re-run with the committed
  `run()` after C0 finishes.** Every dry run so far used an uncommitted driver
  (`build/krcn-replay/t14/dryrun.py`) that skips only the LoC channels the cache can't serve;
  it is not `tier0/rebuild_all.sh`'s real call path and was never intended to be committed. Any
  figure drawn from these dry runs is provisional until
  then (1 of 24 LoC channels cached; the LoC-side counts are a lower bound, not the real EN
  set).

Open for Nick (listed, not argued):
- **R4: whether non-DLC LoC records may be taken as bare facts** (ISBN, volume number, title,
  year) rather than excluded outright. Today: DLC-only. Cost of staying DLC-only: 73 English
  lines / 218 volumes excluded (WEBTOON Unscrolled incl. Tower of God and Noblesse, Inklore,
  Seven Seas).
- **P25, the set-level split.** 14 DNB parent sets have some volumes claimed by the JP round's
  `select` and others by the KR/CN round's; this round defers each whole set to the JP round
  rather than splitting it. A set-level split (each round keeps only the volumes it claims) is
  a possible follow-up.
- **Open (new, narrower than before): merging BnF heads across an imprint rename.** See
  "2026-09-28 follow-ups" below -- the publisher-family rule is done, but 4 of the 14 titles
  are split by two distinct BnF head records, which the family rule cannot merge. Joining
  those heads is a separate, head-identity change with public-id consequences and needs its
  own ruling.

**2026-09-28 follow-ups (post-code-complete; two dnb_sru commits + one bnf_unimarc commit):**
- **DNB transport gap, fixed.** `dnb_sru._live`'s retry tuple, and `get()`'s/`search()`'s outer
  degrade tuples, now catch `http.client.HTTPException` (`IncompleteRead` and friends, raised
  mid-read) and `socket.timeout` (`TimeoutError`'s alias only from Python 3.10) the same way
  they already catch `URLError`/`TimeoutError`/`ConnectionError`: an ERR netlog line, 3
  attempts 30 s apart, then (in `get()`/`search()`) degrade a refresh run onto its cached
  response/set instead of crashing. Checked `lib_sru.py` (LoC/BnF): its `fetch()` already
  catches `(URLError, OSError, http.client.HTTPException)`, which covers `socket.timeout` and
  `ConnectionError` via `OSError` -- confirmed, not re-fixed.
- **The BnF publisher renames (Tokebi/Saphira → Samji) -- the family rule is done.**
  `bnf_unimarc.pubfam` now folds Samji/Tokebi/Saphira to one family (P10 triggered). Measured
  against the cached BnF records: the fix only relabels `pubfam` on 73 lines published by one
  of the three names -- it changes no grouping, membership, volume list or review status for
  any of the 196 FR lines / 1,165 volumes (identical before/after, confirmed line by line and
  by re-running the pipeline-order dry run). Of the 14 named titles: 10 were already one line
  each (rejoined earlier by 461 $0 head identity, independent of this fix; 6 of those 10 --
  Veritas, Les ailes du phénix, Metal heart, Rure, Trois soeurs jumelles, Yongbi -- are in
  `duplicate_numbers` review, pre-existing, not caused by this fix); the other 4 -- Yureka,
  Demon king, Platina, Unbalance X2 -- are still two lines each. Each of those 4 has its
  pre-rename and post-rename volumes under two (or three) DISTINCT BnF head records (461 $0 set
  records); `bnf_lines` groups head-numbered volumes strictly by head id, never by publisher
  family, so unifying the family cannot merge them. **Yureka's Samji reissue does NOT land in
  `duplicate_numbers` review**, contrary to the original prediction, which assumed a headless
  (no-461-$0) matching mechanism these 4 titles don't actually use.

**2026-09-28 export fixes E1-E4 (from the Mangarr consumer scoping, `krcn-consumer-findings.md`;
report `.superpowers/sdd/2026-09-27-krcn-coverage/export-fixes-report.md`):**
- **E1, Solo Leveling. New library lines never take precedence over carried lines.** Two layers:
  - 3f `decide`: a NEW library line (not carried) that is linked by title (not a `link_work`
    correction) or is an ISBN `sibling`, has no vol 1, and sits in a work + market that already
    has a carried line of the same novel/comic class goes to **review, reason `fragment`** (joined
    onto any earlier reason). The dry run's two: FR Kbooks
    `bnf:ark:/12148/cb46910428j` (vols 4/15/17) and DE `dnb:1281034274` (8/11/15; the existing
    rules cannot merge it -- `attach_roles` merges one line per target and `dnb:1216062943` holds
    that merge). `read_carry` now records each carried line's market (`K["line_market"]`).
  - `to_mangarr`: a new library-born line (in `krcn:ids`, absent from the carry) sorts after every
    carried line of its (work, market, medium) group for `is_main`, is never the named line a
    carried group's unnamed lines hang under, and keeps an `orig_series_id` only when a carried
    line of its work, market and novel/comic class shares it (Mangarr's `PickSibling` ranks a
    counterpart first). Without a carry (cold export) nothing changes.
- **E2.** `loc_marc.native_titles` strips a trailing ". English|Korean|Chinese|Japanese|French|
  German" (a 240 `$l` a vernacular 880 folds into its `$a`) -- only after ". " and only when
  Hangul / Hanzi / kana precede it ("Mr. English" stays); the alias `english` is gone.
- **E3.** `to_mangarr`'s origin lookup treats manga / manhwa / manhua as one comic family, used
  only when a line's own medium has no origin line (a same-medium origin always wins): King of
  Hell DE, Unbalance X2 FR, Biao Ren DE gain an origin; one carried line changes (ORV
  "(Physical publication)" EN: NULL -> the ko line, status NULL -> ongoing), listed in
  `ORIG_CHANGE_OK`. `run()`'s "orig_series_id ... origin-market mismatch" rule
  (`orig_mismatches`) accepts a comic-family medium pair only when the origin market has no line
  of the licensed line's own medium (never a novel).
- **E4.** A library-born FR line whose work has no official fr title takes its `bnf` line_name as
  `local_name` (5 lines).
- **New BLOCKING rules in `run_krcn`:** with a carry -- no carried line loses `is_main`,
  `local_name` or alias rows, or is parented under a line absent from the carry (allowed: a
  carried id redirect -- the old parent redirected to the new one, or a carried line of the same
  (work, market, medium) retired into that group's current main line -- and `ALIAS_LOSS_OK`, today the 3 Kindaichi lines' broken
  "s Enquêtes" aliases, base drift); carried `orig_series_id` changes only in `ORIG_CHANGE_OK` (keyed line, old orig, new orig);
  always -- no alias, series name, local_name or catalogue work title that is only a language name
  (en/fr/de forms, raw or normalized). Gotcha: the carried-line rule has no churn allowance -- a
  Wikipedia refresh that legitimately renames or re-mains a carried line fails it until the row is
  listed or explained.
- **Measure floor:** the offline dry run's DE exported volumes drop 273 -> 270 (the DE fragment's
  3 volumes), under the provisional floor 273 (`KRCN_EXPORTED_FLOORS`, set for real at C4).

## 2026-09-28 — Moved to the `opentomedb` GitHub org

`opentome`, `mangarr-metadata` (the catalogue releases) and `opentome-cache` moved from DrAwesome441 to the
**`opentomedb`** org (Nick's decision; Mangarr's repos moved too). Old URLs redirect, release-asset downloads included.
Every repo reference, the site links and the source user agents now say `opentomedb`. **Tokens:** the two
Actions secrets `MANGARR_METADATA_TOKEN` (write, mangarr-metadata) and `OPENTOME_CACHE_TOKEN` (read, opentome-cache)
were personal-account fine-grained PATs and could not reach the org's repos after the move (checked with a
throwaway workflow: 404); they are replaced by org-owned fine-grained tokens (resource owner `opentomedb`).
Publish command is now `gh workflow run catalogue.yml -R opentomedb/opentome --ref main -f publish=true`.
The site serves `catalogue/version.json` (a copy of the release manifest) for Mangarr's stable-URL fetch.

## 2026-09-25 — branch `alias-fix`: work_title des/du, a general carried-id redirect writer

Not merged, not pushed, not published -- Nick's gate (CI build-only first; publish = standing OK
after a green build-only run).

Done (one commit per step; design + numbers: `docs/carried-ids.md`):
- `tier0/carried_ids.py redirect` (stage **7b**, after the audit, before the export): every work,
  line and volume id of the carried artifact the build lost -> `id_redirect`, any market, any
  cause (ISBN majority, else dated volumes, volumes by number; `retired` to the line / main line
  when nothing else holds). Excluded works retire without a row; anything else is an orphan.
  The export now counts work ids as present, so a `work` redirect reaches the artifact.
- `tier0/carried_ids.py merge` (stage **4c**, after the enrichment): a work the carry published
  that is now part of another brings re-keyed lines; one that repeats a PUBLISHED line of the
  survivor (same market + medium, most ISBNs) merges into it -- the published line untouched, its
  name partners pinned to it (`origin_line`, source `opentome`). Scoped to absorbing works and
  unpublished lines: the 496 published same-edition pairs in today's catalogue are not touched.
- `export/test_artifact.py run_ids`: every market, works included, plus every id the carry's own
  `id_redirect` already resolved; excluded works exempt; DE cap (25) unchanged; new cap: > 100
  carried volumes RETIRED (not resolving to a volume) fails (fix round 1: also lines > 10, moved > 500).
- `work_title()`: des/du restore Les/Le; the article fragment is shared with `local_title`.
- Measured offline against the published `opentome-2026-09-25` (downloaded once, as CI's "restore
  id carry" does; zero other network): 4 of 9,668 names change; 13 lines / 247 volumes / 1 work
  leave the artifact, all 261 redirected (line correction 10, line duplicate_merge 3, volume
  correction 175, volume duplicate_merge 72, work duplicate_merge 1), 0 retired, 0 orphans.
  Series 13,035 -> 13,032, volumes 123,930 -> 123,858, aliases 90,380 -> 90,379. Every id in both
  builds: identical columns; only other change: 3 Kindaichi Case Files lines' alias "s Enquêtes de
  Kindaichi" -> "Les Enquêtes de Kindaichi". Contract: only the two AniList rules (8a not run);
  measure 49/49, 0 coverage failures, DE floors unchanged. Second build on the new artifact: 0 new
  / 0 changed, and the gate re-checks the 261 redirected ids (0 lost); `volumes_special` identical;
  the unfixed corpus through the new stages: identical to main.

**Fix round 1 (same day, after review "not safe to publish"):**
- C1: no carry in CI (`OPENTOME_CI=1` / `CI=true`) fails the restore step, `rebuild_all.sh` and
  4c/7b, unless `OPENTOME_COLD_START=1` (catalogue.yml input `cold_start`); `meta.carried_from`;
  publish.sh refuses an artifact without it (unless cold start); the gate checks carried integers.
- C2: a retired line's volumes never match by number (unique ISBN in the market, else `retired` to
  the line); caps: retired lines > 10, retired volumes > 100, ids moved THIS build > 500.
- I1: chains stop at the first present id; a carried row whose old id is live again is dropped
  (reported by 7b, skipped by the export) -- a reverted re-key makes no cycle.
- I2: majority ties are ambiguous (reported, an orphan, the gate fails), never broken by hash
  order. I4: 4c merges only a line matching one of the ABSORBED work's published lines; merges are
  recorded in `meta.merged_lines` so later builds repeat them. I3: docs/mangarr-migration.md
  documents line / volume / work rows and `old_series_id` lookup.
- Minors: derived origin pins warn instead of raising; 7b's presence = the export's (volumes_special
  not present); volumes match a unique ISBN in the successor line first; stage 0 prints a failing
  suite's output.
- Also: a gate that a duplicate recorded in the carry's `meta.merged_lines` never ships again, and
  `docs/id-scheme.md` names the one exception to "nothing is removed from id_redirect" (a row whose
  old id is live again).
- New caps (retired lines > 10, volumes > 100, moved > 500) are unmeasured against a DNB refresh:
  DE lines 3e retires count toward the line cap -- watch the first scheduled CI build; raise the
  threshold if it trips spuriously.
- Re-measured offline (same setup, 0 new cache files): the same 261 redirects byte for byte, same
  integers, gate green apart from the two AniList rules, measure 49/49 (log identical to main's),
  second build a no-op (moved 0); OPENTOME_CI=1 without a carry fails, with cold start it builds.

**Fix round 2 (same day, re-review "safe to publish" with three fixes):**
- N1: a tie goes to the single candidate NEW in this build (a re-key beside its published
  same-edition twin -- 456 of the 496 pairs nest); any other tie is still ambiguous.
- N2: 3e (build_dnb.redirects) uses 7b's volume rule (`carried_ids.volume_successor`): a retired
  German line's volumes never match the main line's books by number.
- N3: publish.sh refuses a `cold-start` artifact without `OPENTOME_COLD_START=1` at publish time,
  and a carried one unless `CARRY_SHA256` (CI: `build/carry.sha256` from the restore step; by
  hand: the live version.json's sha256) equals `meta.carried_sha256`. ROLLBACK_TO past this
  release un-publishes its redirects -- Nick's go-ahead.
- Re-verified: 7b re-run on the measured catalogue + export: the same 261 redirects and integers,
  gate green (AniList rules aside), measure 49/49; no full rebuild (3e wrote 0 redirects here).

Next:
- **Publishing from a workstation now needs `CARRY_SHA256`** (the live version.json's sha256).
- Merge, CI build-only, then publish. Mangarr reads `id_redirect` for `release_line` rows; the
  `work` and `volume` rows are additive; integers resolve through `old_series_id` (the coordinator
  sends Mangarr the matching follow-up).
- Open, deliberately left: the 496 published same-work same-edition line pairs (merging them
  retires consumer-held ids -- a separate decision), and the openBD batch-cache hazard (Gotchas).
- Nick: the French Gouttes de Dieu lines are now named "Drops of God (Les Gouttes de Dieu)" /
  "... - Mariage" (the work's title is English now; `local_name` stays "Les Gouttes de Dieu").
  The French article's JP data for the merged volumes is dropped; Drops of God JP vol 25 keeps
  the English article's ISBN 9784063728491 (vol 23's) where the French article had
  9784063729153 -- a `corrections/volumes.json` candidate.

Gotchas:
- **Stage 0 now gates the build** (f182bbb): before it, `python3 t.py >/dev/null && echo ok` under
  `set -e` only skipped the echo when a suite failed (bash exempts non-final `&&` members), so a red
  suite never stopped a build. Now a failing suite prints its whole output and exits 1 (f520796).
  This makes the `narrow-fold` "BLOCKER for CI" below real: until that branch's fixture term is
  recorded, its failing `test_resolve_anilist.py` stops the build at stage 0.
- openBD is cached by whole 80-ISBN batches of the sorted JP ISBNs: anything that changes the JP
  ISBN set before stage 4 re-keys every later batch (the merge moved from 3a to 4c for that).
  Offline, a missed batch drops dates silently (`_fetch` returns an error dict); locally 217 of
  755 batch URLs are uncached already.
- A merge pins by exact line name (a derived `origin_line`, source `opentome`); if it disagrees
  with the picked origin market the export warns and falls back (a correction's pin still raises).


## preferred-edition-v0 (2026-09-24, NOT published)

Mangarr's Preferred Edition (spec: mangarr docs/superpowers/specs/2026-09-24-preferred-edition-design.md §6 a–d + plan A6)
needs four additive artifact reads: `series.local_name`, `series.country` (market code verbatim), `series_alias.language/kind`,
meta `markets`, plus `id_redirect` (entity `release_line`) for retired line ids. Tests: test_to_mangarr.py (local_title cases from the measured
FR/DE/JP data), contract rules in test_artifact.py. Alias ORDER unchanged (diffed against the pre-change export). Next:
review, merge, build-only CI green, then publish (standing OK) — Mangarr v1 reads these behind guards and works without them.

The `work_title()` "de eats des" item deferred here is done on branch `alias-fix` (below).

## 2026-09-24 — branch `dnb-ingest`: the German market from DNB (stage 3e)

**Review round (same day):** the independent review's ten items are fixed, one commit each
(NFC; linker precision + `must_not_link` fixture; bundles / boxes + protected-line gate; id
contract: exported `id_redirect`, `kept`, carried-id gate, integer rule; clustering: publisher
families + signature merge; volume numbers; CI: `DNB_REFRESH_DAYS=6`, refresh fallback, stable
parent batches; date floor on deposited volumes; origin regex; Magmell / leading "The").
Re-measured offline, zero DNB requests: **DE 1,459 lines / 12,470 volumes**, linked 1,229 high
+ 194 medium, merged 31, sibling 1; review 207; ground truth 31/33, 0 wrong; labelled 44/45;
dates 99.8% of deposited; split editions 13 works / 26 lines (was 49 / 111). Numbers below are
the first build's.

Not merged, not pushed, no CI triggered -- Nick's gate.

Done (design: `docs/dnb-design.md`, results: `docs/german-market.md`):
- `tier0/dnb_sru.py` (>= 3 s cross-process throttle, one Retry-After wait then stop, cache,
  `build/dnb-netlog.tsv`, `DNB_OFFLINE`, opt-in `DNB_REFRESH_DAYS`), `tier0/dnb_enumerate.py`
  (spo=jpn print + manga imprints + parents; jhr slices + a `not jhr>0` remainder; distinct
  totals checked), `tier0/dnb_marc.py`, `tier0/dnb_link.py`, `tier0/build_dnb.py` (stage 3e,
  after relations), tests `tier0/test_dnb.py` (stage 0).
- Export: `volumes.release_date_type` (additive), DNB in `meta.attribution` + LICENSE-DATA.md,
  `meta.dnb_lines`, redirected lines keep their integer id. `tier2/resolve.py`: a bare DNB
  year never beats a finer date it disagrees with (9 volumes; 0 resolution changes elsewhere).
- CI uploads `build/dnb-review.tsv`, `dnb-report.json`, `dnb-netlog.tsv` with the build.
- Gates: DNB rules in `export/test_artifact.py` (needs the catalogue as 2nd arg -- the
  rebuild passes it) incl. the linker fixture `export/fixtures/dnb_linker_labels.json` and
  the 35 pre-DNB ids `export/fixtures/de_lines_pre_dnb.json`; German floors in
  `export/measure_library.py` (`--catalogue=`), printed after the `matched` line.
- Stage 8a ran locally through a driver in `build/` (not committed) that leaves uncached
  AniList terms unbound; the rebuild's final `mv` never ran, so `build/manga-metadata.sqlite`
  is still the 2026-09-20 artifact and the DNB build is `build/manga-metadata.sqlite.new`.
- Measured (offline rebuild, warm cache): DE 35 lines / 391 vols -> **1,593 / 12,678**
  (1,557 linked + 30 merged + 1 sibling + the 5 unmerged Wikipedia lines); linker
  high 1,246 / medium 353 / low 210 / ambiguous 7 / none 2,740; ground truth 30/32 linked,
  0 wrong; labelled set 43/44 (97.7%); dates 95.8%, pages 97.8%; review file 217 lines.
  392 live DNB requests in all, all 200. Non-German side byte-identical to a DNB-free
  export; replay `--base main` 0 new / 0 changed / 0 lost.

Next:
- **Seed the CI cache before the next CI build -- and regenerate the seed, never append.**
  CI's cache has no DNB responses. Unseeded, the first CI build has no complete earlier result
  sets, so any DNB failure fails it (DnbIncomplete), and `actions/cache` saves only on success.
  The only procedure: rebuild the tarball from the FULL current local `.cache`, which now holds
  the DNB responses AND `.cache/dnb-parents.json` (the parent-batch index):
  `tar --zstd -cf opentome-cache.tar.zst -C .cache .`, upload it as the private
  opentome-cache repo's `seed` release asset, run the seed-cache workflow. Never append files
  to the old tarball and never build it from a subset -- a partial seed silently lacks
  whatever it misses, and the next cold CI run re-fetches it (or, for AniList, binds
  differently).
- Refreshing: `DNB_REFRESH_DAYS=6` is now set in `catalogue.yml` (last year, this year and
  later, the no-year remainder, when older than 6 days: ~62 requests a week, plus up to 42
  small recounts when a total moved). Parents are fetched once (stable batches via
  `.cache/dnb-parents.json`), never refreshed. A result set is cached whole or not at all. When
  DNB fails during a refresh, a result set with a previous COMPLETE page set keeps that set
  (never a partial or empty one), the build continues, and it is marked degraded
  (`meta.dnb_degraded`): `export/publish.sh` refuses to publish it. A result set with NO complete
  earlier set -- a first run, an unseeded cache, a new slice -- fails the build loudly, refresh
  window or not (CI always sets one). The contract also fails when more than 25 carried German
  volumes are retired in one build.
- Nick: `build/dnb-review.tsv` (207 low/ambiguous lines) -- confirmed ones could become
  corrections; the design has no correction type for "link this DNB line" yet.
- Follow-ups: KR/CN round (decision 4); light novels are thin (19 lines) -- LN works are
  linked less often; the 518 current-year announcements without a 263 month are undated.

Gotchas:
- The date floor is now on deposited volumes (99.8%); announced-only volumes are reported
  apart and cannot trip it.
- `dnb_member.volume_id` can point at a volume a later stage deleted (5b exclusions).
- The spike's `From the sea` (Okubo one-shot in the Fire Force series statement) still links
  to Fire Force; spin-offs named inside a parent's series statement link to the parent.
- 13 works still split across lines by a subtitle variant between set records ("Kemono jihen"
  / "Kemono Jihen. Gefährlichen Phänomenen auf der Spur"); a post-link merge would fix it.
- `id_map` now keeps `retired` rows for carried line ids a build no longer has: 55 today, all
  outside the German market (en 27, ja 25, fr 3) -- the lines of works excluded since the
  20 September artifact (W.I.T.C.H., Mechademia, The Walking Dead, The Adventures of Rabbi
  Harvey, ...). A correct catalogue-wide fix: each reserves its integer so it is never reissued.
  They have NO `id_redirect` row, deliberately: an excluded work has no successor line to point
  at (none shares work + language + name). Nothing but the exporter reads `id_map`. Say this in
  the merge commit message. The carried-id gate has only met the 35 German Wikipedia lines so
  far; the DNB-line redirect path is unit-tested and meets real data at the second publish.
- `DNB_REFRESH_DAYS` is 6 on the rebuild step (87c7f0f replaced the step's 7 per the review:
  a 7-day window on a 7-day cron skips alternate weeks). Revert 87c7f0f for 7.
- 879 German volumes ship undated (announced, no planned month, or a plan older than 12 months);
  a consumer that treats undated as "missing" will search for them.
- DE lines of Swiss publishers carry 978-2 ISBNs (Kazé / Crunchyroll SA): the audit's
  "DE lines with no DE-group ISBN" info line counts them; 14 volumes collide with FR lines
  citing the same ISBN (flagged, info).

## 2026-09-24 — branch `anilist-round2`: post-walk tiers, R6+, 26 pins, 4 exclusions

Not merged, not pushed, no CI triggered -- Nick's gate (CI build-only; bar 0 changed / 0 lost).

Done (one commit each, each droppable):
- `export/resolve_anilist.py` post-walk tiers (`post_walk()`, spec in the module docstring): V1
  prefix / V2 arc / V3 amp / V4 origin, only for lines still unbound after the whole walk, over
  pages the walk already fetched (zero new queries). `load_line()` carries `orig_vc`. Offline
  replay `--base main` on opentome-2026-09-24: 52 new (26 / 19 / 5 / 2), 0 changed, 0 lost. V3 is
  primary-title only (its one synonym match was the doubtful Shino & Ren -> "...: Future").
- R6+ (own commit): wider edition allowlist, unclosed trailing parenthetical, bare "volumes"
  heading; the nested-series guard also catches "series(" now. +3 over the post-walk commit, 0 / 0;
  19 new stripped terms uncached (live-only).
- `corrections/anilist.json`: 26 pins (18 high + 8 medium from the analysis), each re-verified on
  the cached page. Nausicaä (Perfect Collection) -> 30651 not pinned: the id is on no cached page.
- `corrections/excluded.json`: W.I.T.C.H. (takes the wrong 41582 bind with it), IDW My Little
  Pony, Mechademia, Fair, then Partly Piggy.

Next:
- CI build-only; watch the 19 uncached R6+ terms and the live-only post-walk pages. Live CHANGED
  watch list (bound today through an alias; R6+ now searches an uncached stripped name first):
  `Days volume list` (86600 via "DAYS" -> "Days", the likeliest to flip), `Golgo 13 (Viz Media
  English volumes)` (31298 via "Duke Togo" -> "Golgo 13"), `The World of Narue (Manga volumes)`
  (34844 via "Narue no Sekai" -> "The World of Narue"). Post-walk binds report as prefix / arc /
  amp / origin in `anilist-resolve-report.tsv`; R6+ binds report as `alias`.
- Nick: Rick and Morty (w_80704d7f33e4) is NOT excluded -- the work also carries the OEL
  "Rick and Morty: The Manga" line and an exclusion takes every line of the work.
- Nick: the four `[]` The Beginning After the End pages in `.cache/anilist/` (manga + novel, name
  + deslug, all written 2026-09-15) look like a bad fetch; purge + refetch is his call.

Gotchas:
- V1's only guard against a 3+-volume line binding a differently-titled sequel entry (Shino & Ren
  -> "Shino & Ren: Future" shape) is uniqueness + the >= 3 gate; the Shino line is 1 volume.
- `export/test_artifact.py` against the CI artifact fails until a rebuild applies the new pins and
  exclusions (checked on a patched copy: contract ok).

## 2026-09-24 — branch `narrow-fold`: Latin-only accent strip + numeric-symbol fold + alias seen seed

Not merged, not pushed, no CI triggered -- Nick's gate (CI build-only, live diff vs the published
report; ship bar 0 lost / 0 changed).

Done (three commits, each droppable -- `git revert` of the seed or of the numeric fold applies
cleanly on top; reverting the Latin strip alone needs a one-hunk hand merge in fold()):
- `fold()` in `export/resolve_anilist.py`, shared by `key()` and `for_search()`:
  `strip_latin_marks()` (NFD, a combining mark dropped only after a Latin-script letter, NFC;
  unchanged strings come back byte for byte -- kana voicing, Hangul, Cyrillic, CJK untouched,
  checked over 59,110 catalogue + cached AniList strings) and `fold_numeric()` (No / Nl ->
  NFKC per character, U+2044 -> "/": "Ranma ½" is searched as "Ranma 1/2", AniList's own romaji;
  key() still gives ranma12).
- `alias_terms()` seeds `seen` with key(name), key(deslug(name)) and key(ascii_normalize(name))
  (a mirror of to_mangarr.normalize, asserted equal in the tests).
- Offline replay vs 2146f47 on the ci-mf build (3,054 EN lines): 1 new (Café Terrace), 0 changed,
  7 lost -- every one through a changed, uncached search term (MÄR, Übel Blatt, Ōoku, Saintia Shō,
  BakéGyamon, both Ranma ½ edition lines). A proxied replay (a folded term borrows the accented
  term's cached page) keeps 6 on the same id; BakéGyamon binds by name on the cached
  case-variant "Bakegyamon" page. No loss comes from key()/pick() ranking a page differently.
  The seed alone: 0 / 0 / 0, +26 uncached alias terms.

Next:
- BLOCKER for CI: `tier0/rebuild_all.sh` step 0 runs `export/test_resolve_anilist.py`, and with
  the Latin strip that suite fails on the unrecorded fixture term (Gotchas). (Written when stage 0
  did not actually gate -- a failing suite under `&&` never tripped `set -e`; since f182bbb on
  `alias-fix` it does, so this blocks.)
  Either record that one page (`ANILIST_RECORD=1 python3 export/test_resolve_anilist.py` fetches
  only the missing term) or drop the Latin strip; the seed alone, and numeric + seed, run green.
- Then CI build-only; the numbers above are all live-only. If a part loses binds live, revert it.
- Live CHANGED watch list: 24 lines (22 names) keep their id offline but now cross an uncached
  folded alias term BEFORE the alias that binds them (Arifureta, Hell Mode x2, Bumpkin x2, Trinity
  Seven, Rascal, Papillon, ...); plus the 12 published edition lines (Tankōbon / Shinsōban /
  Aizōban) whose name and deslug terms change. The seed alone and numeric + seed: none.
- Mangarr: mirror fold() in TitleMatcher.Normalize / TitleNormalizer.ForSearch (separate task).
  Latin = `c.isalpha()` and "LATIN" in the character's Unicode name (C# needs an explicit table).

Gotchas:
- `export/test_resolve_anilist.py` aborts offline: the Harsh Mistress fixture's alias
  "...Kakuzetsu Toshi no Joō" is now searched as "...Joo", which is not recorded (nor in
  `.cache/anilist/`). Needs `ANILIST_RECORD=1` (a live request) -- the maintainer's call. With that
  page proxied locally the suite is 181/181, the 44 audited lines unmoved.
- "Ranma 1/2" (the search term since 0e2e3e4, AniList's romaji) is uncached locally; the proxied
  replay borrows the "Ranma ½" page for it, so the two Ranma lines are CI's call.

## 2026-09-24 — branch `display-fallback`: display-only AniList fallback + two stray exclusions

Not merged, not pushed, no CI triggered -- Nick's gate.

Done:
- `series.display_anilist_id` / `display_anilist_via` (`parent` | `medium`): a cover / synopsis
  id for an EN line the resolver leaves NULL -- never a binding (never copied into `anilist_id`,
  never an alias source, not read by Mangarr). `export/resolve_anilist.py --display`, stage 8a's
  third call (resolve, pins, display, covers-only); `anilist-covers.json` now covers display ids.
  Spec in `display()`'s docstring and `docs/schema-v1.md`; contract in `export/test_artifact.py`.
  Measured offline on a fresh export: 68 via parent (9 more skipped as ambiguous), 15 via medium.
- `corrections/excluded.json`: Sweet Tooth (Vertigo) and The Adventures of Rabbi Harvey -- the
  only two Western comics among the 31 unresolved EN lines with no origin line; the OEL /
  German / French manga and webtoons in that set stay (Nick's ruling).
- Offline replay vs 6a7c0f3: 0 new / 0 changed / 0 lost binds. Piecewise offline stages 5b
  (new exclusions only) - 8d: audit 0 defects, contract ok, measure 49/49.

Next:
- CI build-only run: the `medium` tier searches the manga-family page for each unbound novel
  name; 49 of those pages are uncached locally, so the live count may exceed 15.
- The homelab browser (not in this repo) reads `anilist-covers.json` by id; it shows display
  covers only if it also looks up `display_anilist_id`.
- Data follow-ups seen, not fixed: Gothic Sports is medium `novel` (a comic); the Monogatari EN
  lines are `novel` while the JA line is `light_novel`, which is likely why they have no
  `orig_series_id` and stay unbound.

Gotchas:
- Stage 8a is now FOUR calls. `--display` recomputes from scratch, so it must run after the pins.
- `parent` is same-work, any medium: an arc can take a different-medium parent's cover (the
  `Re:Zero (Truth of Zero)` manga shows the Re:Zero light novel's), and some arcs have their own
  AniList entry that the rules cannot reach (Truth of Zero is 87259). Display only, by design.

## 2026-09-24 — branch `anilist-resolve`: AniList resolver accuracy round

Not merged, not pushed, no CI triggered -- Nick's gate. Everything measured OFFLINE against
`.cache/anilist/` with the new `export/replay_anilist.py` (stock `ca0935f` vs working tree over
all 3,056 EN lines of the `opentome-2026-09-24` release artifact, anilist_id reset, curated alias
removals applied; a cache miss = no result, counted as uncached).

Done:
- `corrections/anilist.json` -- new correction type, a hand-checked AniList id per line
  (`line` = `series.tome_id`). Applied by `tier2/corrections.py --anilist` right after
  `resolve_anilist.py` in stage 8a; validated by `--check`; asserted by `test_artifact.py`.
  Seed: Worst (EN, 3 vols) -> 31741.
- `corrections/aliases.json`: "Ginga Densetsu Riki" and "Ginga Legend Riki" removed from Weed.
- `pick()` tiers (docstring = spec): R4 ceiling fallback (Weed -> 34010, +10 short English
  runs; stands down beside any equal title that passes the ceiling), R5 substring + exact volumes (own name only; +14, Der Werwolf 98367 -> 114483 -- 10 of
  the analysis's 14; the missing 4 (Haruhi-chan, Re:Zero Truth of Zero / Frozen Bond,
  Restaurant First series) only match through alias terms and are left out by design; the
  other 4 are one-to-two-volume lines outside the analysis's scope: Bookworm Royal Academy
  Stories, Fairy Tail: Ice Trail, Slime (Again!) Workaholic, The Obsessed Mage),
  R6 edition-qualifier paren-strip retry (ranked like an alias; +9), R7 leading-article
  equality (+1, Hollow Regalia). Net: 35 new binds, 1 changed (Der Werwolf), 0 lost; vs the
  published artifact also Weed 38901 -> 34010; EN >= 3 vols unresolved 307 -> 280.
- Diacritic fold (fix #5) and alias-prefix-first order (fix #4): committed and REVERTED under
  the round's zero-change rule. The replay lost 8 and 5 currently-bound lines through changed
  or no-longer-searched terms -- all uncached, so unmeasured; a live A/B could reverse this.

Next:
- CI build-only run for the live numbers: 30 R6 stripped terms are uncached locally (upper
  bound), and the via tally now also prints article / substring / ceiling.
- Mangarr's AniListRanker has none of R4-R7; parity is its own decision.

Gotchas:
- `bash tier0/rebuild_all.sh` cannot run locally: without `ANILIST_OFFLINE=1` step 8a makes
  live requests; with it, 8a aborts on `OfflineMiss` (Roxy Gets Serious + two Hoshin Engi
  terms were already uncached). Stages 8-8d were verified piecewise offline (the round's
  report, delivered to the maintainer; replay outputs in the private sdd notes).
- Stage 8a is three calls (four since `display-fallback`): resolve, `corrections.py --anilist` (pins), then
  `resolve_anilist.py --covers-only`, so pinned ids get their fallback cover too.
- A diacritic fold in `for_search()` rewrites live search strings: NFKD drops kana voicing
  marks and turns ½ into 1⁄2 -- the narrow retry is branch `narrow-fold` (Latin-only strip),
  judged by a live A/B.

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
