# Verification coverage — and an important distinction I initially blurred

"Verified" is not one thing. A source can confirm that a volume **exists with that ISBN
and volume number** without saying anything about **when it shipped**. Reporting those as
one number is misleading, and I did exactly that before checking.

## The corrected picture

| Market | Volumes w/ ISBN | Existence verified | **Dates corroborated** |
|---|---:|---:|---:|
| JP | 81,986 | 69,742 (85%) | **69,742 (85%)** — openBD supplies dates |
| EN | 25,826 | 18,417 (71%) | **15,699 (61%)** — Open Library supplies dates |
| FR | 16,419 | 13,530 (82%) | **0 (0%)** — see below |

## What BnF actually returns

BnF contributed **22,321 claims and not one of them was a date**:

| field | claims |
|---|---:|
| `volume_number` (200$h) | 12,557 |
| `page_count` (215$a) | 9,764 |
| `release_date` | **0** |

Step 0 recorded this exact fact — *"210$d (date) was absent on every per-volume record"* —
and I built the enricher anyway, then reported "82% verified" as though dates were
covered. They were not. All **15,257 French dates remain `single_source`**.

BnF is still worth having: it independently confirms that a French volume exists, carries
that ISBN, and sits at that volume number. That is real corroboration of *structure*, and
structure is what the release-line split depends on. It simply is not date corroboration.

## Why the auto-acceptable percentage fell

25.3% → 23.4% after BnF looks like a regression and is not. BnF added ~22k **new**
single-source field entries (`volume_number`, `page_count`) that had no prior claim at
all, enlarging the denominator. No field got less confident. A rate over a changing
denominator is the wrong headline number; the per-market table above is the right one.

## The French date gap is a real limitation of the differentiator

France is the market that makes OpenTome distinctive, and French dates are the least
corroborated data in the catalogue. Honest options, none of them free:

| Source | FR date coverage | Cost |
|---|---|---|
| **Open Library** | ~15% on probe (6/40), all with dates | cheap — same batched API |
| Publisher sites (Pika, Glénat, Ki-oon, Kana) | high | per-publisher scrapers, ongoing maintenance |
| Google Books | good | **disqualified** — ToS forbids database-building |
| BnF | 0% | already exhausted |

Open Library at 15% is being run because it is nearly free. It will not close the gap.
**French day-precision dates will remain predominantly single-source**, and the catalogue
should say so through `resolution.basis` rather than implying a confidence it has not
earned.

## Date-format hazard found while wiring this up

Open Library's French listings use `DD/MM/YYYY`. `05/03/2022` is 5 March in France and
3 May in the US, and picking wrong writes a plausible, silent, wrong date — the exact
failure class this project keeps hitting. The parser therefore accepts numeric dates at
**day precision only when unambiguous** (one field > 12); otherwise it degrades to month
precision rather than guess.
