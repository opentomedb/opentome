# CLAUDE.md — OpenTome

Read `docs/` before changing anything. Every design decision here came from a measured
finding, not a preference, and the docs say which.

## 🚨 CLEAN ROOM — the rule that must never be broken

This repo exists to produce a catalogue that is **neither GCD-derived (CC BY-SA) nor
Readarr-derived (GPL-3)**. That is the entire reason it is a separate repo from
the Mangarr repository (a sibling checkout).

- **No GCD dump data, no GCD-derived artifact, and no Readarr code may enter this repo.**
- **The existing `manga-metadata.sqlite` artifact is NOT a scoring reference.** Not
  ground truth, not a seed, not a tiebreaker. Tuning this pipeline until its output
  matches a CC BY-SA artifact is deriving from that artifact by a slower route and
  forfeits the only thing this repo protects.
- Reading `mangarr`'s ingest code for *techniques* is fine. Copying it is not.

## Source rules

**Never use as a stored source** — all three prohibit database-building and/or
commercial use, verified against their terms:

| Source | Why |
|---|---|
| Google Books | ToS forbids "building databases"; forbids charging users |
| MangaDex | ToS forbids compiling a database; forbids commercial use; forbids automated access |
| Rakuten Books | Forbids reproduction beyond product links |

**Safe**: DNB (CC0), BnF (open), openBD (verify terms), publisher pages (per-site
`robots.txt`/ToS), Wikipedia **facts only** — never prose or summaries.

Every claim MUST carry a `licence`. Per-field provenance is cheap now and unrecoverable
later; without it the commercial subset can never be reconstructed.

## Non-negotiables

- **IDs are a public contract.** Never reused, never re-keyed. Merges write
  `id_redirect`; retired ids resolve forever. Consumers store these.
- **Be polite to sources.** Serial access, ≥1.1s between Wikipedia calls, disk-cached in
  `.cache/` so re-runs hit zero network. We were 429'd once already.
- **No recurring manual step.** The GCD pipeline decayed because a human had to fetch a
  gated download every fortnight. One-time setup is fine; anything recurring must be
  automatable.
- **Never store a bare date.** Always `_precision` (day/month/year) and `_type`
  (on_sale/published/digital/…). Mixing date semantics is the quiet wrongness that
  killed Readarr.

## Deploys

Publishing is the `catalogue` workflow's `publish=true` dispatch — a human gate. Anything
public beyond that (a new release channel, a dataset elsewhere, a site change that ships
data) needs the maintainer's explicit go-ahead first.

## Handoff

Update `HANDOFF.md` (done / next / gotchas) as the last commit before ending a session.
