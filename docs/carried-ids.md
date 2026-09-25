# Carried ids — every published id keeps resolving (2026-09-25)

Status: built on branch `alias-fix` (not merged, not published). Code: `tier0/carried_ids.py`,
tests `tier0/test_carried_ids.py` (stage 0), gate `export/test_artifact.py` `run_ids`. The contract
it serves is `docs/id-scheme.md`; the German-only mechanism it generalises is
`tier0/build_dnb.py` `redirects()` (`docs/dnb-design.md`, "Redirects").

## Why

Ids hash natural keys (`schema/load.py`): a work is `w_<hash(identity key or title)>`, a line
`rl_<hash(work, medium, market, line name)>`, a volume `v_<hash(line, number)>`. A corrected fact
that feeds one of those keys issues new ids. Until this round only German ids had a redirect
writer, and the carried-id gate checked only German ids, so a re-key anywhere else would have
shipped green and orphaned every consumer that stored the old id. The round that exposed it:
`work_title()` read "Liste des chapitres des Gouttes de Dieu" as "s Gouttes de Dieu"; fixing it
re-keys the Kindaichi 1re / 2e partie lines (their names embed the title) and folds the French
Gouttes de Dieu work into Drops of God (the work-identity pass unions articles by title).

## Where it runs (`tier0/rebuild_all.sh`)

Both stages read the carried artifact, `ID_CARRY` = the last published `manga-metadata.sqlite`
(CI downloads it in "restore id carry"; locally it is `build/manga-metadata.sqlite`). With no
carry they do nothing.

- **4c. merged works** — `carried_ids.py merge`, after the enrichment, before clean.
- **7b. redirects** — `carried_ids.py redirect`, after the audit, before the export, so the
  export's integer carry sees the rows.

## 4c. An absorbed work's duplicate lines

A work the carry published that is now part of another work brings its lines along, re-keyed
under the survivor. Where a re-keyed line is the same edition as one of the survivor's
**published** lines it is merged into that line:

- same edition = same market and medium, and a strict majority of the smaller line's ISBNs
  shared; when either line has no ISBNs, a strict majority of its dated volumes (number + date,
  at least two);
- the published line keeps its id, its own volumes and their claims byte for byte; a volume
  number it lacks moves over as `v_<hash(line, number)>`; the duplicate's other volumes are
  dropped with their claims; every reference follows (composition volume and ref line, arc
  parent, claims, resolution, override, external ids, `dnb_member`, `dnb_line`);
- the lines in other markets that found the duplicate as their origin by line name get a derived
  `origin_line` claim (source `opentome`) naming the survivor — without it the FR "Mariage" line
  fell back to the JP main line and exported `ongoing` instead of `completed` (measured).

**Scope.** Only a line the carry does not have, in a work that absorbed another — in this build,
or through a carried `work` redirect (the duplicate comes back on every build, so the merge must
too). Today's catalogue has **496** same-work same-edition line pairs whose ids are all published
(JoJo printings, "Tomes 31 à aujourd'hui" tails, EN/FR-article JP twins); merging those would
retire hundreds of consumer-held ids and is a separate decision.

**Why after the enrichment.** openBD is cached by whole batches of 80 sorted JP ISBNs. The first
build of this round merged at stage 3a and dropped one distinct JP ISBN; every later batch became
a new URL — 363 of 755 batch URLs uncached — and, offline, 42,981 openBD date claims disappeared
(`release_date_type` moved on 42,464 volumes). With network it would have been a ~360-request
burst. After the enrichment the batches see the same ISBN set.

## 7b. Redirects

1. The carry's own `id_redirect` rows are re-read (stage 3e already re-reads them too), so a
   redirect survives every later build; the export collapses chains.
2. A carried **work** this build lost → the present work holding a strict majority of its
   volumes' ISBNs; else the work its lines' successors belong to. Reason `duplicate_merge` when
   that work was published, else `correction`.
3. A carried **line** this build lost → in its (successor) work, same market + medium: the line
   holding a strict majority of its ISBNs (ties: a line new in this build, then the larger, then
   the id); else a strict majority of its dated volumes; then the same ISBN test market-wide (a
   line that moved to another work); else the work's main line of that market + medium, reason
   `retired`. Reason `duplicate_merge` when the successor was published, else `correction`.
4. A carried **volume** this build lost → the volume of the same number in its line's successor
   (by number first: the English Drops of God article repeats vol 23's ISBN on vol 25); else the
   one volume of its market with its ISBN; else the successor **line**, reason `retired`.
5. Lines and volumes of a work in `corrections/excluded.json` are retired on purpose and get no
   row — an excluded work has no successor. Anything else without a present target is an
   orphan: printed, written to `meta` `carried:redirects`, and the gate fails.

Ids that stage 3e (DNB) already redirected are left as they are. A redirect's target is always
an id present in the catalogue at 7b.

The export (`export/to_mangarr.py`) counts work ids (`series.tome_work_id`) as present, so a
work redirect reaches the artifact (`entity='work'`, integers NULL). A re-keyed line with no
integer of its own takes the old line's integer (a consumer's stored `gcd_series_id` keeps
working); a merged line's integer resolves through `old_series_id -> new_series_id` and stays
reserved in `id_map` (kind `retired`).

## The gate (`export/test_artifact.py` `run_ids`, stage 8c)

- every work, line and volume id of the carry, **every market** -- and every id the carry's own
  `id_redirect` already resolved -- is present or resolves through the artifact's `id_redirect`
  to an id that is; ids of works in `meta.excluded_works` are exempt;
- unchanged: more than `MAX_RETIRED_DE_VOLUMES` = 25 carried German volumes gone fails;
- new: more than `MAX_RETIRED_VOLUMES` = 100 carried volumes **retired** in one build, any market,
  fails — retired = no longer resolving to a volume (redirected to its line, or not at all); ids a
  re-key or a merge moved to volumes do not count;
- every `id_redirect` target is in the artifact (works included).

## Measured (offline rebuild of the branch against the published `opentome-2026-09-25`)

The fix changes 4 of 9,668 distinct corpus / identity names (all "des"; no "du" occurs). Ids:
13 lines, 247 volumes and 1 work leave the artifact; all 261 are redirected, 0 retired, 0
orphans. Kindaichi 1re / 2e partie: 8 lines / 105 volumes re-keyed (`correction`), same data,
same integers. Gouttes de Dieu: `w_2e7699a81cd4` → `w_0153b28bb30b` (`duplicate_merge`); its
3 JP lines (72 volumes) merge into Drops of God's published JP lines (`duplicate_merge`, by
number); its 2 FR lines (70 volumes) re-key under Drops of God (`correction`, same integers).
Nothing else moved: every id present in both builds has identical series and volume columns;
the only other change is 3 Kindaichi Case Files main lines trading the alias "s Enquêtes de
Kindaichi" for "Les Enquêtes de Kindaichi". A second build against the new artifact: 0 new ids,
0 changed, the 261 rows identical, and the gate re-checks those 261 old ids (0 lost). The same stages on the unfixed corpus: 0 merges, 0 redirects,
an artifact identical to main's.
