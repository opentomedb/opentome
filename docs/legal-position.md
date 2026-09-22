# Legal position — verified 2026-08-27

**I am not a lawyer and this is not legal advice.** It is a record of what each source's
published terms actually say, checked rather than assumed.

## A retraction

I previously reported **"100% commercially clean claims."** That figure was circular. It
counted claims by a `licence` label, and I had assigned those labels myself — marking
openBD, Open Library and "publisher" as `open` based on Step 0 to-dos I never completed.
The data was clean because I said it was clean.

Having actually read the terms, the honest numbers are:

| | share |
|---|---:|
| Usable in a **free** release | **100.0%** (375,347 / 375,347) |
| Usable in a **commercial** product | **75.1%** (281,855 / 375,347) |

## Source by source

| Source | Claims | Verified terms | Commercial |
|---|---:|---|---|
| **BnF** | 22,409 | **Etalab Open Licence** since 2014. Commercial reuse explicitly permitted, attribution required. | ✅ |
| **DNB** | (few) | **CC0** — public domain, no conditions. | ✅ |
| **Wikipedia** | 194,668 | Facts are not copyrightable (*Feist*). We extract facts only, never prose. | ⚠️ US yes; **EU open question** |
| **"publisher"** | 50,926 | Wikipedia-derived values whose `<ref>` cites a publisher page. We never fetched the publisher. Provenance is Wikipedia; attribution points onward. | ⚠️ same as Wikipedia |
| **openBD** | 58,929 | Rights granted for **"book promotion and introduction"**; data must not be altered. | ❌ **purpose-limited** |
| **Open Library** | 34,563 | Internet Archive terms: access for **"scholarship and research purposes only"**, use certified **"noncommercial"**. API explicitly *not* intended as a bulk backend — use the monthly dumps. | ❌ **noncommercial** |
| Google Books / MangaDex / Rakuten | 0 | All forbid database-building and/or commercial use. **Not used.** | ❌ (excluded by design) |

## What is genuinely settled

- A **free, non-commercial release is defensible today.** Every source permits it.
- **BnF and DNB are clean for any use**, including paid — they are the only two verified so.
- The three sources we walked away from *were* correctly excluded, and that judgement holds.
- Nothing was scraped. Publisher pages are cited, never fetched. Rate limits were
  respected; one 429 from Wikipedia led to a 1.1s throttle and disk caching.

## What is not settled

1. **openBD's purpose limitation.** "Book promotion and introduction" plausibly covers a
   free catalogue that drives people to buy books. A paid metadata API is a harder
   argument. Needs either permission or exclusion from the commercial tier.
2. **Open Library is noncommercial by Internet Archive's terms** — that is explicit, not
   ambiguous. Also: we made ~25,000 individual API calls where they direct bulk users to
   the dumps. **Switching to the dumps is both more correct and better behaved**, and
   should happen regardless of the commercial question.
   Cover coverage is bounded by Open Library itself: every cover the API returns for an
   ISBN it knows is already harvested from the cached responses with no further requests,
   and an ISBN it does not know yields nothing from any endpoint. Raising cover coverage
   is a source question, not a request-volume one.
3. **The EU sui generis database right.** Facts are free in the US under *Feist*; the EU
   grants exactly the sweat-of-the-brow protection *Feist* rejected. Europe is the target
   market, so this is not theoretical. **This is the one that genuinely needs a lawyer.**
4. **Attribution is required and not yet surfaced.** BnF's licence and openBD's terms both
   require retaining source attribution. We store `source_url` per claim but no published
   artifact displays it. A dump must ship attribution.

## Practical consequences

- **Ship the free release.** It is clean, and it is the step that tests adoption anyway.
- **Do not sell access to the current dataset.** At 75.1% commercially usable, a paid tier
  would need to be built from `clean_claim` only — losing every openBD and Open Library
  date, which is most of the Japanese and much of the English corroboration.
- **The commercial path runs through DNB and BnF**, both verified clean, both national
  libraries, both usable at any scale. That reinforces the earlier finding that DNB should
  be a primary source rather than a verifier.
- **Get counsel before charging anyone**, specifically on the EU database right and on
  whether openBD's purpose limitation admits a paid API.
