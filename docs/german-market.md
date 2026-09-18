# The German market — measured, and a required change of approach

## The extractor works. The source doesn't have the data.

`tier0/de_tables.py` parses German volume tables correctly. Verified against
*Attack on Titan* (de): 61 records, with Japanese **and** German dates and ISBNs per
volume, rowspan-immune.

It also produced an unplanned cross-check. German Wikipedia gives volume 1's Japanese
date as **2010-03-17, ISBN 9784063842760** — *identical* to what French Wikipedia
supplied independently. Two unrelated language editions agreeing exactly, which makes
cross-language Wikipedia agreement a corroboration source in its own right.

## But Attack on Titan is not representative

Random sample of 40 German articles drawn from the langlink set:

| | |
|---|---:|
| Contain any ISBN | 12 (30%) |
| Use `{{DatumZelle}}` | 1 (2%) |
| **Yield volume records** | **3 (8%)** |

**Projected usable German articles: ~68.**

Two compounding limits:

1. **Only 21% of English articles have a German equivalent** — 917 of 4,270. An earlier
   probe suggested 60%, but it sampled the first 200 articles, which skew toward older,
   well-established series. A biased sample gave a number 3× too high; the random sample
   corrected it.
2. **Of those 917, only ~8% carry volume tables.** German Wikipedia documents manga
   series without cataloguing their volumes, which English and French routinely do.

## Consequence: DNB becomes a PRIMARY source, not a verifier

DNB was deferred earlier on the grounds that it had nothing to verify. That reasoning
was right but the conclusion is now different: **German volume data should come from DNB
directly rather than from Wikipedia.**

This is a better position than the one we were aiming for:

- **DNB is CC0** — public domain, no attribution requirement, no share-alike,
  commercial use unrestricted. It is the cleanest-licensed source in the entire project,
  cleaner than Wikipedia facts.
- **Legal deposit means completeness.** Every book published in Germany is in it by law,
  including the long tail Wikipedia ignores.
- **Publisher-scoped queries already work.** Step 0 verified `TIT=… and VLG=Carlsen`
  returns clean per-volume records: `245$n` volume number, `300$a` extent, `008[7:11]`
  year.

The approach inverts: enumerate by publisher (Carlsen, Egmont, altraverse, TOKYOPOP,
Panini Manga Deutschland) rather than by series, and let legal deposit supply the
catalogue.

**The known cost:** DNB dates are year-precision only (`008`). Germany would have
complete coverage at low date precision — the mirror image of France, which has
day-precision dates and no corroboration.

## Actual result of the full pass

917 German articles, 0 errors, 15.9 minutes:

| | |
|---|---:|
| DE release lines | **32** |
| DE volumes | **381** (282 day-precision) |

The survey projected ~68 usable articles and the run produced 32 release lines from them
— the projection was right in scale.

### For comparison, the whole catalogue

| Market | Lines | Volumes |
|---|---:|---:|
| JP | 8,196 | 83,527 |
| EN | 3,729 | 37,355 |
| FR | 2,036 | 23,886 |
| **DE** | **32** | **381** |

**Germany is 0.26% of the catalogue.** For the market that is 20% of European manga
sales, that is not coverage — it is a rounding error.

This settles the question the survey opened. German Wikipedia is not a viable source for
the German market, and no amount of parser work changes that: the extractor is correct
and the articles are empty. **DNB, as a primary source, is the German strategy.** The 381
volumes here are a supplement worth keeping and nothing more.
