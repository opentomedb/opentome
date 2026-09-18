# Corpus v1 — full build results

Built 2026-08-26. **5,823 / 5,823 articles processed, 0 errors**, 111 minutes.

## Scale

| | |
|---|---|
| Works | **5,163** |
| Release lines | **13,945** |
| Volumes | **144,431** |
| Claims (with provenance) | 260,846 |
| Volumes with chapter composition | 47,957 |

For scale: the project had **4 works** before this run.

## Quality

| Metric | Result |
|---|---|
| **Day-precision release dates** | **112,898 (78.2%)** |
| Volumes with ISBN | 124,231 (86.0%) |
| **ISBN-13 checksum validity** | **115,869 valid / 0 invalid — 0.0000%** |

**Zero invalid ISBNs out of 115,869**, extracted from freeform wikitext across two
languages. That is the strongest available evidence that extraction is genuinely clean
rather than merely clean-looking, and it costs nothing to verify — the check digit is
built into the standard.

Day-precision at 78.2% across 144k volumes is the differentiator surviving contact with
reality. No other manga/LN metadata source provides per-volume day-precision dates at
any scale.

## Coverage

**By market**

| Market | Release lines |
|---|---|
| JP | 8,186 |
| EN | 3,728 |
| FR | **2,031** |

France is the world's #2 manga market and had **no per-volume tooling whatsoever**
before this. 2,031 French release lines is the differentiator made concrete.

**By medium**

| Medium | Release lines |
|---|---|
| manga | 12,049 |
| light_novel | **1,568** |
| novel | 215 |
| manhwa | 95 |
| artbook | 12 |
| manhua | 6 |

1,896 non-manga release lines — a naming or schema decision that had boxed out light
novels would have discarded 13.6% of the catalogue, and the fastest-growing part of it.
This is why `medium` is open-ended TEXT and why the project is not called
"manga-something".

## Method notes

- **Discovery was exact, not sampled.** `list=embeddedin` returns every article using the
  volume-list template — precisely the parseable set. No guessing at categories, no
  crawling.
- **Resumable by construction.** Completed articles are recorded in `meta` and every
  response is disk-cached, so a re-run skips finished work at zero network cost. This
  was load-bearing: the first launch was orphaned at 58 articles and the restart lost
  nothing.
- **Polite throughput.** 0.9 articles/sec with a 1.1s serial throttle and exponential
  backoff. Wikipedia returned 429 once early in development; nothing since.
- **Zero errors across 5,823 articles.** Every failure path writes an `err:` key to
  `meta`; none fired.

## What this does not yet prove

Coverage is Wikipedia's coverage. Series without a volume-list article are invisible to
this pass regardless of how popular they are, and the 30-series validation spike — with
deliberately obscure, light-novel and webtoon-heavy selections — has still not been run.
Every quality number here describes what was extracted, not what exists.
