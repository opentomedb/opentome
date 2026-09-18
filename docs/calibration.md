# The week-multiple calibration rule — derivation and independent replication

The rule that separates *semantic variance* from *error* in release dates. It is the
mechanism that lets a consumer auto-accept a value instead of queueing it for review,
which is the difference between a catalogue and a scrape.

## The observation

Two sources give day-precision dates for the same volume in the same market, and they
differ. The naive reading is that one is wrong. **Overwhelmingly, neither is.**

US book street dates fall on Tuesdays. When two sources record *different milestones* —
publisher publication date versus retail on-sale date, digital-first versus print — the
gap is a whole number of weeks.

## Derivation (n=50, Wikipedia vs Google Books)

From `docs/tier1-crossverify.md`, 416 English volumes cross-checked:

- 366 exact agreement
- 50 disagreements, of which **49 (98%) were exact multiples of 7 days**
- **45 of 50 ran in the same direction**
- Exactly **one** genuine anomaly (+4 days)

## Independent replication (n=239, Wikipedia/publisher vs Open Library)

A different source, a larger sample, and the rule was **not retuned**:

| \|offset\| | count | multiple of 7? |
|---:|---:|---|
| 7d | 142 | ✅ |
| 14d | 55 | ✅ |
| 21d | 16 | ✅ |
| 28d | 15 | ✅ |
| 35d | 4 | ✅ |
| 42d | 7 | ✅ |
| **non-week** | **0** | — |

Same directional bias: Open Library runs *earlier* than Wikipedia and publisher dates.

A pattern derived from one source pair reproducing unchanged against an unrelated source
pair is the strongest evidence available that it reflects how publishing dates actually
work, rather than an artefact of one dataset.

## The rule as implemented

| Offset signature | Basis | Confidence | Meaning |
|---|---|---:|---|
| identical | `agreed` | 0.97 | sources concur |
| compatible at coarser precision | `agreed_coarse` | 0.90 | e.g. `2010-03` vs `2010-03-17` |
| multiple of 7, **≤ 42 days** | `semantic_variance` | 0.88 | different milestone; both correct |
| multiple of 7, **> 42 days** | `escalated` | 0.40 | different edition / wrong release line |
| ≤ 7 days, not a multiple of 7 | `minor_variance` | 0.65 | near-agreement, cause unknown (non-US markets) |
| **not** a multiple of 7, > 7 days | `conflict` | 0.30 | genuine anomaly — review |
| only one source | `single_source` | 0.70 | unverified |

**The magnitude bound is essential.** Two different *editions* both shipping on a Tuesday
also differ by a multiple of 7 — the four largest offsets in the derivation sample
(161d, 826d, 63d, 49d) were all week-aligned and all turned out to be *wrong release
lines*, not date semantics. Without the bound the rule would have blessed them.

## Scope — narrower than first claimed

**This rule applies to same-market, day-versus-day comparisons only.**

An earlier write-up presented it as general. It is not. Run against openBD — Japanese,
month-precision — it fired **once** in 66,975 comparisons, because that comparison has a
different failure mode entirely (coarser precision, resolved by `agreed_coarse`). The
rule needs two day-precision opinions on the same edition to say anything at all.

## The rule is US/English-market specific — a French finding

Adding Open Library coverage for French exposed a limit. French conflicts broke down as:

| offset | share |
|---|---:|
| **1–6 days** | **46%** |
| 7–90 days | 38% |
| 3–13 months | 9% |
| >13 months (reissues) | 6% |

Almost half sit *below* a week and are not week-multiples at all. The reason is that the
week-multiple signature encodes **US Tuesday street dates**. France has no equivalent
weekly release grid, so its sources disagree by a day or two rather than by clean weeks.

Applying the rule unchanged produced a 27% French conflict rate that largely reflected
**the rule not fitting the market**, not the data being wrong. Blaming data for a rule's
assumptions is the same mistake as trusting a rule that has never been tested.

### `minor_variance`

Sub-week, non-week-multiple gaps now get their own basis at confidence 0.65:

- calling them `conflict` blames the data for the rule's US assumption
- calling them `semantic_variance` claims an explanation we do not have

They are near-agreement of unknown cause, and the label says exactly that. Effect:
needs-review fell from 815 to 505 without any field being blessed it hadn't earned.

## Consequence for consumers

`resolution.confidence` and `resolution.basis` are part of the public API. A consumer
should auto-accept `>= 0.85` and queue the rest. That single threshold is the direct fix
for the silent-wrong-match class of bug that this project has hit repeatedly — including
binding 25% of a reference library to the wrong series with data that looked perfect.
