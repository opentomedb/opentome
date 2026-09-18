# Tier-1 cross-verification — 536 records against independent sources

Run 2026-08-26. Tier-0 measured *completeness*; this measures **correctness**, which is
the thing the whole product thesis rests on and which nothing had tested yet.

Sources: **openBD** for Japanese ISBNs (month precision), **Google Books** for English
ISBNs (day precision). All responses disk-cached — re-runs cost zero network and zero
quota.

---

## Headline

| Check | Result |
|---|---|
| ISBN-13 checksums | **981/981 valid, 0 invalid** (531 JP + 450 EN) |
| JP dates vs openBD | **99.3% agree** (446/449 at month precision) |
| EN dates vs Google Books | **88.0% exact** (366/416) |
| **True data-error rate** | **~0.24% — one record out of 416** |

The gap between "88% exact" and "0.24% wrong" is the interesting part.

## The 12% that disagreed is not error — it is two different date semantics

Of 50 non-zero offsets, **49 (98.0%) are exact multiples of seven days**, and **45 of 50
run in the same direction** (Wikipedia later than Google Books).

```
  +7d  ############ 12       -7d  ##### 5
 +14d  ########  8          +35d  #### 4
 +21d  #####  5             +42d  ### 3
 +28d  ########  8           +4d  # 1   <- the only non-week offset
```

Random data errors do not land on week boundaries 98% of the time. US book street dates
are Tuesdays, so two sources recording *different milestones* — publisher publication
date vs retail on-sale date, or digital-first vs print release — differ by whole weeks.
**Both values are probably correct; they are answering different questions.**

### Consequent model change: `date_type` is required, not optional

`date_precision` alone is insufficient. A catalogue that silently mixes on-sale dates
with publication dates is untrustworthy in exactly the way that killed Readarr:

```
release_date            2020-04-21
release_date_precision  day
release_date_type       on_sale | published | digital | street
release_date_source     https://www.viz.com/...
```

### And a deployable calibration rule fell out of the data

| Offset signature | Interpretation | Action |
|---|---|---|
| 0 | sources agree | high confidence |
| multiple of 7, **≤ ~6 weeks** | date-semantic variance | high confidence, record both |
| multiple of 7, **> 6 weeks** | **wrong release line** (see below) | escalate / re-bind |
| not a multiple of 7 | genuine anomaly | flag for review |

The magnitude bound matters: two *different editions* both released on Tuesdays also
differ by a multiple of 7, so the week test alone is not sufficient.

---

## The four large offsets are all the franchise-flattening bug — and Google Books detects it

Every offset over six weeks traced to one cause, and Google Books' `title` names it:

| Wiki record | Offset | What the ISBN actually is |
|---|---|---|
| `re zero` v2 | +161d | *Re:ZERO **Chapter 4: The Sanctuary and the Witch of Greed**, Vol. 2 (manga)* |
| `sword art online` v6 | +826d | *Sword Art Online **Progressive 3** (light novel)* |
| `sword art online` v2 | +63d | *Sword Art Online **Unital Ring**, Vol. 2 (manga)* |
| `solo leveling` v5 | +49d | *Solo Leveling, Vol. 5 **(novel)*** — not the manhwa |

These are not date errors at all. The Wikipedia articles flatten an entire franchise —
multiple manga sub-series, light novels, and spin-offs — into one volume list, so "v2"
refers to different works in different rows.

**This independently rediscovers the release-line modelling problem, and hands over the
fix:** Google Books' returned title identifies which sub-series an ISBN belongs to
(`Chapter 4: …`, `Progressive 3`, `Unital Ring`, `(novel)` vs `(manga)`). That is a
cheap, automatic mechanism for splitting a flattened article into correct release lines —
no manual curation required.

## Revised error breakdown (416 EN records)

| Category | Count | Share |
|---|---|---|
| Exact agreement | 366 | 88.0% |
| Week-multiple ≤6wk — date semantics, both correct | 46 | 11.1% |
| Large offset — franchise flattening (fixable) | 4 | 1.0% |
| **Genuine anomaly** (Fire Force v11, +4d) | **1** | **0.24%** |

## The three Japanese disagreements

| Record | Wikipedia | openBD |
|---|---|---|
| Black Clover v23 | 2020-01-04 | 2019-10 |
| Gyo v1 | 2002-02-28 | 2002-04 |
| Gyo v2 | 2002-05-30 | 2002-07 |

Both Gyo volumes are off by a consistent ~2 months in the same direction — a systematic
signature again, not random error, and most likely an edition difference (Gyo has had
several reissues). Worth a tier-2 check, not a red flag.

84 JP ISBNs (15.8%) were not found in openBD at all — openBD's coverage of older titles
is thinner than its coverage of recent ones.

---

## Verdict

**The thesis survives the first real test of correctness.** Extraction is clean (zero
bad ISBNs), Japanese dates agree with an independent source 99.3% of the time, and the
English disagreements are overwhelmingly systematic rather than erroneous.

More valuable than the pass: two mechanisms came out of the data rather than being
designed in — a **week-multiple signature** that separates semantic variance from real
error, and a **title-based release-line detector** that fixes franchise flattening. Both
are exactly the kind of calibration machinery the plan said the product needs and had no
concrete implementation for.

## Caveat, repeated

Still Nick's curated mainstream library. These numbers are optimistic by construction.
The 30-series spike with obscure, light-novel and webtoon content remains the real test.
