# Cleanup pass — what the audit found and what it cost to fix

`tier2/audit.py` finds problems and fixes nothing. Every check answers one question:
**would an integrator notice this and lose trust?**

## The headline defect was not dirt — it was a missing join

The audit surfaced 19,002 ISBNs appearing in more than one release line. Chasing that
number down led somewhere much worse than duplication:

> **"Attack on Titan" and "L'Attaque des Titans" were separate works with separate ids,
> and the `work_title` table designed to link them had zero rows.**

The catalogue was three parallel language catalogues wearing one schema. The flagship
query — *"I own French volume 5, what is that in English?"* — was **unanswerable**,
because the two editions belonged to unrelated works. Every quality metric looked fine;
the thing that made it *one* catalogue simply did not exist.

## Four fixes, measured

| | original | +heading fix | +identity | +title-union |
|---|---:|---:|---:|---:|
| works | 5,163 | 5,109 | 4,896 | **4,664** |
| **work_titles** | **0** | **0** | 10,928 | **10,683** |
| release lines | 13,993 | 13,426 | 13,251 | **12,986** |
| volumes | 145,149 | 137,756 | 135,597 | **132,549** |
| **duplicate ISBNs** | **19,002** | 12,182 | 9,963 | **6,928** |

**64% reduction in duplicate ISBNs.** Volume count fell because duplicates collapsed, not
because data was lost.

1. **Leaked generic headings.** *"Liste des volumes"* alone produced 1,991 spurious lines,
   so the same Japanese release line was created once per language wiki under a different
   name. Futari Ecchi had 32 JP lines.
2. **Cross-language work identity** via Wikipedia langlinks — union-find over article
   equivalence classes, deterministic so ids never churn between runs (the ID contract
   forbids that). Also populates the localized-title index that Step 0 identified as a
   hard prerequisite and that had never been built.
3. **Title-union**, fixing a regression *this pass introduced*: keying identity on the
   article split same-language multi-part articles ("List of Naruto chapters (Part I)"
   and "(Part II)") into separate works. The old title-hash keying did not have that bug.
4. **Year and alternative-grouping headings** — "1998", "Story arcs", "Tomes classiques"
   are organisational groupings, not release lines.

## The remaining 6,928 are mostly not our bugs

| cause | share |
|---|---:|
| different line_name | 64% |
| different work | 30% |
| different medium | 5% |

`9781421517810` is filed under both *Gimmick!* and *Tower of the Future* in Wikipedia.
An ISBN identifies exactly one physical product, so that is an **upstream data error**,
and no amount of parser work fixes wrong source data.

These are therefore **flagged, not guessed at**: affected volumes get an
`isbn_collision` claim and the confidence layer carries the dispute to consumers.
Choosing which of two contradictory sources is right, with no evidence, is precisely the
silent-wrongness this project keeps guarding against.

## Also fixed

- **`release_date_type` was `unknown` on all 145,149 volumes** — a field argued as
  essential and never populated. Now set to `published` **only for openBD**, whose ONIX
  PublishingDateRole 11 explicitly states which milestone it is. Every other source is
  silent, and labelling them would manufacture the precision the field exists to prevent.
- **118 Jan-1 dates** downgraded from day to year precision — the project's oldest known
  artefact, where a year-only source stamps 01-01 and the precision becomes a lie.
  Downgraded, not deleted: the year is still true.
- Malformed ISBNs nulled; implausible future dates (>2 years out) nulled.

## One audit check was a false alarm

"1,146 work+market pairs with conflicting medium" was flagged as a defect. It is not —
Re:Zero legitimately has both a manga *and* a light-novel line in Japan. That is the
open-ended `medium` field working as designed. Recorded as a false positive rather than
"fixed", because fixing correct data is worse than leaving it alone.

## Reproducibility

`tier0/rebuild_all.sh` runs the whole pipeline in dependency order. Every stage is
cache-backed: a full rebuild takes **0.9 minutes at 110 articles/sec** versus 111 minutes
on the first network run, and costs zero additional requests.

---

# Final state after the full cleanup pipeline

| | |
|---|---:|
| Works | **4,733** |
| Work titles (cross-language index) | **10,677** |
| Release lines | 13,092 |
| Volumes | **133,762** |
| Claims | 379,155 |
| Day-precision dates | 104,438 (78%) |
| Volumes with ISBN | 113,569 (85%) |
| Database size | 206 MB |

| Market | Lines | Volumes |
|---|---:|---:|
| JP | 7,327 | 72,089 |
| EN | 3,678 | 37,336 |
| FR | 2,055 | 23,956 |
| DE | 32 | 381 |

Resolution: 24.1% auto-acceptable (≥0.85), 0.3% needing review. `agreed` rose from
2,841 to **10,080** — a direct consequence of merging works across languages, since
sources that previously described "separate" works now corroborate each other.

## Driven to zero

Jan-1 fake precision · implausible future dates · malformed ISBNs · wiki markup in
titles · empty titles · duplicate volume numbers within a line · page-count outliers ·
empty release lines · orphan works.

## Known limitations, documented rather than hidden

| | count | why it stays |
|---|---:|---|
| duplicate ISBNs | 7,485 | dominated by upstream Wikipedia errors; flagged via `isbn_collision` |
| duplicate work titles | 89 (1.9%) | articles no langlink or title match connects |
| `release_date_type` unknown | 74,018 | only openBD states its milestone; labelling the rest would invent precision |
| volumes with neither date nor ISBN | 18,701 | genuinely absent upstream |
| single-volume release lines | 804 | some real, some parse artefacts — unseparated |
| conflicts / escalated | 1,507 / 211 | surfaced through confidence, not silently resolved |

## A silent failure I caused, and the guard added

Running the enrichment stages in a loop with `>/dev/null 2>&1`, the scripts failed on
relative paths, wrote **zero** claims, and the pipeline **reported success**.
Auto-acceptable silently fell from 24% to 3.5% and nothing surfaced it until a later
audit.

That is this project's recurring failure class — silent success — and this time it was
self-inflicted by hiding diagnostics. `rebuild_all.sh` now runs under `set -euo pipefail`
with a comment recording why stderr is never suppressed in this pipeline.
