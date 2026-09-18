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

`id_redirect` is a pipeline table (`schema/schema.sql`) and is not yet exported to the
published `manga-metadata.sqlite`, so a retired id is not yet resolvable from the
published file; the guarantee holds in the pipeline and the export follows once the
first merge is published.

## What is *not* guaranteed

- **Ordering.** Ids are opaque. Do not sort by them, parse them, or infer recency.
- **Meaning.** The hex carries no information. Do not derive anything from it.
- **Stability of the natural key.** If a work's natural key genuinely changes (a merge, a
  split), a *new* id is issued and the old one is written to `id_redirect`. The old id
  keeps resolving; it simply points somewhere new.

## Merges and splits

| Event | Handling |
|---|---|
| Two records found to be the same work | Keep the older id. Write the newer to `id_redirect` with `reason='duplicate_merge'`. |
| One record found to be two works | Keep the original id on the larger part. Issue a new id for the split-off part. Write `reason='split'`. |
| Wrong entity type | Issue a new id of the correct type; redirect the old with `reason='correction'`. |

**Deletion is not a supported operation.** Nothing is ever removed from `id_redirect`.

## Why this is written down

The project's own history motivates it. The predecessor's blueprint records the lesson in
its own words — *do not big-bang re-key existing series* — after an ID migration nearly
orphaned a live library. That was one person's instance. A published scheme has the same
failure mode multiplied by every consumer, and no way to walk it back.
