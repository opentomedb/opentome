# OpenTome ID scheme — the public contract

**This document describes the one thing in OpenTome that can never change.**

Consumers (Mangarr, Kavita, Komga, Suwayomi) store these identifiers in their own
databases. The moment they do, the scheme stops being ours to revise: churn breaks every
consumer simultaneously and silently. IMDb and TheTVDB are defensible because of their
identifiers, not their bytes — the IDs *are* the moat.

Treat everything below as frozen.

## Form

```
w_a3f21c9d4b07     work         — the canonical creative work, medium- and market-neutral
rl_88e0d2114f6a    release line — one medium, one market, one publisher
v_5c7be0913a2d     volume       — one physical/digital unit within a release line
ch_1f04a7cd88b2    chapter      — one canonical serialized unit
```

Prefix names the entity type; the remainder is 12 hex characters, opaque.

**Typed prefixes, not branded ones** — this follows IMDb (`tt`/`nm`/`co`) and MusicBrainz
(bare UUIDs). The brand belongs in the *field name* a consumer stores, not inside the
identifier.

## Canonical consumer field name

```
tome_id
```

Use `tome_id` alongside the fields integrators already carry (`tvdb_id`, `tmdb_id`,
`anilist_id`). Where a consumer must disambiguate entity types, `tome_work_id`,
`tome_volume_id` etc. are the sanctioned forms.

## Guarantees

1. **Never reused.** A retired identifier is never issued to a different entity, ever.
2. **Never re-keyed.** An entity's id does not change because a fact about it was
   corrected. Ids are opaque precisely so that no correction can force a re-key.
3. **Always resolvable.** A merged or superseded id resolves through `id_redirect`
   forever. It must never 404 — consumers holding it get the successor, not an error.
4. **Idempotent generation.** Ids derive from a stable natural key by hash, so
   re-ingesting the same source produces the same ids. Verified: reloading a populated
   database leaves the volume count unchanged.
   **Since 2026-09-27 an id is no longer derivable from the natural key alone**
   (`docs/krcn-design.md` §8–9). A work or line that shipped keeps its published id even when a
   later build derives a different natural key for it: a library line whose lowest member
   LCCN / ark changes, or a library-born work that a Wikipedia work later covers. The build looks
   the entity up in the carry (the previous artifact) first and mints from the natural key only
   when nothing carried matches. Re-running the same build on the same carry still gives the
   same ids.

`id_redirect` is a pipeline table (`schema/schema.sql`), and since 2026-09-24 the published
`manga-metadata.sqlite` carries it too: `id_redirect(old_tome_id, new_tome_id, entity, reason,
old_series_id, new_series_id)`, chains collapsed to an id present in that file. Each build
re-reads the previous artifact's rows, so a redirect is never lost. A retired volume with no
successor volume resolves to its line (reason `retired`).

Since 2026-09-25 the pipeline writes those rows for every market and every entity, work
included (`tier0/carried_ids.py`, `docs/carried-ids.md`): a carried id the build lost goes to the
work / line / volume now holding its evidence (ISBNs, else dated volumes, volumes by number),
and the contract test fails on any carried id, in any market, left without a present target.

Integer ids (`series.gcd_series_id`) follow the same rule: a successor line with no integer of
its own takes the retired line's; a successor that already has one keeps it, the retired
integer resolves through `id_redirect.old_series_id -> new_series_id`, and it stays reserved in
`id_map` (kind `retired`) so it is never issued again. A German line the DNB linker stops
linking stays published under its published work (role `kept`) rather than disappearing.

## What is *not* guaranteed

- **Ordering.** Ids are opaque. Do not sort by them, parse them, or infer recency.
- **Meaning.** The hex carries no information. Do not derive anything from it.
- **Stability of the natural key.** If a work's natural key genuinely changes (a merge, a
  split), a *new* id is issued and the old one is written to `id_redirect` (unless the carry
  keeps the published id, Guarantee 4). The old id
  keeps resolving; it simply points somewhere new.

## Merges and splits

| Event | Handling |
|---|---|
| Two records found to be the same work | Keep the older id. Write the newer to `id_redirect` with `reason='duplicate_merge'`. "Older" between two published ids is the lower (minimum line) integer in `id_map`. |
| A published work or line meets one whose id was never published (a library-born KR/CN work or line later covered by Wikipedia) | **Adoption:** the published id stays public and the merged entity ships under it; the unpublished id is internal only, so no redirect is written. Adoption runs before the carried-id stage, so it never counts as a move. |
| One record found to be two works | Keep the original id on the larger part. Issue a new id for the split-off part. Both ids are present, so neither gets a row. What moved to the split-off part and lost its published id is redirected by the carried-id stage (7b, `docs/carried-ids.md`): a line to the line now holding a strict majority of its ISBNs (else of its dated volumes) in its work, then to the line holding a strict majority of its ISBNs anywhere in its market and medium (a line re-attached to another work), with reason `duplicate_merge` when that line was published, else `correction`, or to its work's main line with `retired`; a volume to the volume now holding its ISBN or number, reason `correction` (`duplicate_merge` when its line was redirected `duplicate_merge` and it matched inside that line), or to its line with `retired`. No stage writes `reason='split'`. |
| A published library-born line meets the build, or splits across several built lines (controller ruling 2026-09-27 "continuity first", final; `tier0/krcn_identity.py line_ids`) | In priority order. **1. Continuity:** a built line whose own natural-key id is in the carry keeps it, unconditionally, and never takes or absorbs another published id; so the line whose record minted a published id keeps it even when it now holds a minority of that line's volumes, or none. **2. Lookup** (only when the minting record is gone): a built line whose own-key id was never published may take a published library line of its source that step 1 did not keep, when it holds at least one of its volumes (a bare volume number counts) and (a) shares at least 2 distinct ISBNs with it (volume numbers never count here), or (b) has its folded name and, the published line having a publisher, the same publisher family (the source's line-builder family: DNB `build_dnb.pubkey`, LoC `loc_marc.pubfam`, BnF `bnf_unimarc.pubfam`). Several such lines: the one holding the most of its volumes (a split's plurality), then the one holding its lowest volume number, then the lowest own key. One line qualifying for several: it takes the older (lowest `id_map` integer). A take by a line holding less than a strict majority of the published line's ISBNs is reported (`taken_weak`) and gates publishing. **3. No absorption:** a published id neither kept nor taken is left to the carried-id stage (7b): a redirect by an ISBN or dated-volume majority, a retirement, or a reported orphan that fails the contract test (loud, never a silent move). Every other built line, including every other part of a split, mints its own natural key; no split-id formula exists (nothing split-minted was ever published). The moved volumes' published ids are redirected by 7b as in the row above (reason `correction`), so no `split` row is written. Step 1 never claims a German JP-round id: the two rounds' `dnb:` keys are disjoint because stage 3f defers a KR/CN line whose key the JP round mints (`deferred_to_jp_round`, plan P25) before assigning ids, and `line_ids` refuses any line minting an id passed as reserved. |
| Wrong entity type | Issue a new id of the correct type; redirect the old with `reason='correction'`. |

**Deletion is not a supported operation.** Nothing is ever removed from `id_redirect` -- with one
exception (2026-09-25, `docs/carried-ids.md`): a row whose OLD id is present again (a re-key
reverted, "s X" -> "Les X" -> "s X") is dropped, because the id now resolves by being present, and
keeping the row would send a live id elsewhere and close a cycle.

## Why this is written down

The project's own history motivates it. The predecessor's blueprint records the lesson in
its own words — *do not big-bang re-key existing series* — after an ID migration nearly
orphaned a live library. That was one person's instance. A published scheme has the same
failure mode multiplied by every consumer, and no way to walk it back.
