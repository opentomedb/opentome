# Step 0 findings — licensing and feasibility gate

Run 2026-08-24. All probes were live HTTP calls against the real endpoints, not
documentation reads. Raw evidence is quoted inline.

**Verdict: the multi-market thesis survives, but one core claim in the plan was wrong
and one gate is still open.** Details below, then a revised cost picture.

---

## Gate 1 — MangaDex terms: UNRESOLVED ⚠️

The API limitations page documents rate limits (**~5 requests/second per IP**, a
User-Agent header required, no CORS for external sites, image-proxy rules, IP bans for
persistent abuse) but says **nothing about commercial use, monetization, or
attribution**. The `mangadex.org/compliance` page is JS-rendered and returned no
content to a fetch.

**This needs a human to read the actual Terms of Service.** The chapter tier's
commercial viability is still an open question, and it gates whether chapters can be
part of a paid product or only a free one.

## Gate 2 — openBD: PASS, with two real gaps ⚠️

Live, no API key, fast. Probe: `9784063842760` (進撃の巨人 vol 1, Kodansha).

```
title    : 進撃の巨人. 1
publisher: 講談社          author: 諫山,創
pubdate  : 201003
Extent   : null
summary.volume: "4276. Shonen magazine comics"
```

- ✅ Exists, resolves by ISBN, returns title/publisher/author, has an ONIX block.
- ❌ **`Extent` (page count) is null.** No page count.
- ⚠️ **`PublishingDate` is `201003` — year and month, no day.**
- ⚠️ **`summary.volume` is imprint numbering, not the volume number.** The actual volume
  ("1") is embedded in the title string `進撃の巨人. 1` and must be parsed out.

Commercial-use terms still need confirming.

## Gate 3 — SRU national libraries: PASS, but the plan's cost claim was too optimistic

Both endpoints are live, unauthenticated, and generous.

### DNB (Germany) — the strongest source tested

Unscoped title search is useless: `WOE=Attack on Titan` returned 287 records led by a
**2027 wall calendar** and a **piano arrangement of the theme song**.

Publisher-scoping fixes it completely — `TIT="Attack on Titan" and VLG=Carlsen` → 162
records, all real:

```
ISBN=9783551744272  245$a='Attack on Titan' 245$n='12'
                    300$a='circa 472 Seiten'   008[7:11]='2023'
                    264$b='Carlsen Manga!'
```

- ✅ **Volume number is structured** in MARC 245$n — not embedded in a title string.
- ✅ Page count in 300$a (needs parsing: `circa`, `Seiten`).
- ⚠️ 264$c is unreliable (returned `'23'`). **The dependable year is 008 chars 7–10.**
- ❌ **Year only. No month, no day.**

### BnF (France) — works, but only with the localized title

`bib.title all "attack on titan"` returns mostly series-level records with no ISBN and
no volume number. The French edition is titled **« L'attaque des titans »**. Querying
that instead → 146 records:

```
ISBN=978-2-8116-5599-0  200$h='31'  215$a='1 vol. (non paginé [ca 190] p.)'
ISBN=978-2-8116-5783-3  200$h='32'  215$a='1 vol. (non paginé [ca 184] p.)'
```

- ✅ 8/8 sampled records carried ISBNs.
- ✅ Volume number in 200$h for main-series volumes (the un-numbered ones in the sample
  were legitimately separate spin-offs: *Before the Fall*, *Hope of the City*).
- ⚠️ Page counts are approximate (`non paginé [ca 190]`).
- ❌ **210$d (date) was absent on every per-volume record.** Where present elsewhere it
  is a dépôt-légal year (`DL 2017`).

---

## The four problems this uncovered

### 1. Two record schemas, not one — the plan understated this

The plan claimed adding a market is "an endpoint config plus a field mapping." SRU is
indeed a shared *protocol*, but the *record schemas differ*:

| Field | DNB (MARC21) | BnF (UNIMARC) |
|---|---|---|
| ISBN | `020$a` | `010$a` |
| Title | `245$a` | `200$a` |
| Volume no. | `245$n` | `200$h` |
| Extent | `300$a` | `215$a` |
| Date | `008[7:11]` | `210$d` |

**Bounded, not fatal** — MARC21 and UNIMARC are both standards, so this is two adapters
covering most of Europe rather than one per country. But it is a real per-schema
engineering cost, not a config line.

### 2. Localized titles break discovery — a hard prerequisite, not a nice-to-have

French is « L'attaque des titans ». German kept the English title, but that is luck,
not a rule. **A title-synonym layer (AniList / MangaDex `altTitles`) must exist before
any European market query can run at all.** This is now a blocking dependency in the
acquisition path, not an enrichment step.

### 3. Naive title search returns merchandise

DNB's unscoped query surfaced calendars and soundtracks. Publisher-scoping was the fix,
which means **curated per-market publisher lists are a required input** (Carlsen,
Egmont, altraverse for DE; Pika, Glénat, Ki-oon, Kana for FR; …).

### 4. ❗ No exact release dates anywhere — the most consequential finding

| Source | Date precision |
|---|---|
| openBD (JP) | year + month (`201003`) |
| DNB (DE) | **year only** (008) |
| BnF (FR) | **absent**, or dépôt-légal year |
| Open Library | year only (`'2010'`), 1 of 3 ISBNs found, no page count |

The existing Mangarr's headline achievement was **exact per-volume release dates** (421
volumes, 100%). **National libraries structurally cannot deliver that.**

Consequence for the plan: the "legitimate public APIs, no scraping, no ToS tightrope"
argument **covers breadth only**. Exact dates still require publisher catalogs, so the
precision layer remains scraping-dependent and the legitimacy story is weaker than the
plan claimed. This does not kill the thesis — it splits it:

- **National libraries** → breadth: existence, ISBN, volume number, page count. Free,
  CC0 in Germany's case, no scraping.
- **Publisher catalogs** → precision: exact dates. Still the hard, encumbered part.

An honest open question this raises: **does the product actually need day-precision
dates?** For a historical back-catalogue, year-month may be sufficient; day precision
matters mainly for upcoming releases, which is a much smaller set and where publisher
sites are both current and easy to poll.

---

## Two bonus findings

### Cross-market divergence confirmed in the wild ✅

German Carlsen volumes run **472 / 564 / 433 Seiten**; French Pika volumes run **~184–190
pp**; standard Japanese volumes are ~190pp. The German line is clearly omnibus
("Massiv") editions collecting multiple Japanese volumes.

This is live evidence that the composition-mapping problem is real and that **a
two-market JP↔EN spike would have missed it.** The decision to include French and German
is validated.

### ⚠️ Google Books keyless quota is now ZERO — likely breaking the running Mangarr

```
HTTP 429  "Quota exceeded ... limit 'Queries per day'"
quota_limit_value: "0"   quota_limit: defaultPerDayPerProject
```

Even a control query for an English ISBN failed. `GoogleBooksService.cs` is documented
as "works keyless at lower quota" and is described in the codebase as *the per-volume
backfill workhorse*.

**That backfill is probably silently failing in the live instance right now.** Worth
checking independently of this project — set `GOOGLE_BOOKS_API_KEY`.

(Because of the 429, the Google Books *coverage* question for non-English ISBNs is
**inconclusive**, not answered. Retest with a key before drawing conclusions.)

---

## Recommended plan amendments

1. **Reopen the date-precision requirement.** Decide whether year-month is acceptable
   for back-catalogue before building a scraping layer to chase days.
2. **Promote the title-synonym layer** from enrichment to a blocking prerequisite in the
   acquisition path.
3. **Add per-market publisher lists** as a required input artifact.
4. **Soften the "config, not engineering" claim** for new markets to "one adapter per
   record schema (MARC21, UNIMARC), then config per country."
5. **Resolve the MangaDex ToS question** before any chapter-tier work.
6. **Get a Google Books API key** before the spike, and retest coverage.

---

# DECISION (2026-08-26): day precision is required

Nick's call: full dates including day, as a differentiator and for reliability. Nothing
else in the market has this. Accepted — below is what it costs and the architecture it
forces.

## Day-precision source survey (all probed live)

| Market | Source | Day precision | Access |
|---|---|---|---|
| JP | openBD | ❌ year-month only (`201003`; ONIX + `hanmoto.dateshuppan` both confirm) | free API |
| JP | **Rakuten Books** | ✅ `salesDate` = `2016年10月26日` | free w/ app ID — **but terms prohibit reproduction of API data beyond product links. Likely DISQUALIFYING for a catalog.** |
| JP | **Kodansha** `kc.kodansha.co.jp` | ✅ 17 `YYYY年M月D日` on one product page | 200, scrapable |
| EN | **Viz** | ✅ `<div class="o_release-date"><strong>Release</strong> August 6, 2013</div>` + `o_isbn13` on the same page | 200, clean semantic HTML — ideal |
| EN | Kodansha USA | — | ❌ **403 blocked** |
| FR | Pika | ✅ dates present (9,583 visible words) | 200 |
| FR | Glénat | ✅ 33 date matches | 200 |
| DE | Carlsen | ⚠️ listing page has none; product pages untested | 200 |
| DE | altraverse | ⚠️ 319 words — likely JS-rendered | 200 |

**Verdict: day precision is achievable, but only from publisher sites.** No free
bibliographic API provides it. Rakuten has it and forbids reuse; openBD and every
national library top out at month or year.

## What this costs — state plainly

1. **Per-publisher adapters, not per-schema.** The breadth tier needed 2 adapters
   (MARC21, UNIMARC) covering many countries. The precision tier needs **one per
   publisher**, and there are 4–6 relevant publishers per market.
2. **Access is uneven.** Kodansha USA already returns 403. altraverse looks JS-rendered.
   Some publishers will need rework or will be unavailable.
3. **Ongoing maintenance.** Publisher sites change layout; national library schemas
   don't. This converts a build-once asset into a maintained one.
4. **The legitimacy story narrows.** "Clean public APIs, no scraping, no ToS tightrope"
   now describes the **breadth tier only**. Per-publisher `robots.txt` and ToS review
   becomes real, recurring diligence.

## The architecture this forces — and it's better than crawling

**Two tiers, joined by ISBN:**

- **Tier 1 — breadth (free, clean, API):** national libraries + openBD →
  existence, ISBN, volume number, page count, approximate date.
- **Tier 2 — precision (publisher sites):** resolve **known ISBNs from tier 1** to exact
  release dates.

The key move: **ISBN-keyed lookup, never crawling.** Tier 1 supplies the ISBN list, so
publisher sites are only ever asked to *resolve a specific known item*, not to be
*enumerated*. That is dramatically less traffic, politer, trivially cacheable, and it
degrades gracefully — a tier-2 miss leaves tier-1's approximate date in place instead of
a hole.

## Consequent model change: date precision is data, not a boolean

Replace any single confidence flag on dates with an explicit field:

```
release_date            2013-08-06
release_date_precision  day | month | year
release_date_source     viz | kodansha-jp | dnb | openbd | bnf
```

This is more honest than a confidence score and directly serviceable: a consumer wanting
a release calendar filters `precision = day`; one wanting coverage takes everything. It
also makes the tier-1/tier-2 join auditable.

## Amended spike metrics

- **Day-precision coverage** — % of volumes reaching `precision = day`, **per market**.
  This is now a primary metric, not a diagnostic.
- Date accuracy is measured only against `precision = day` records; month/year records
  are scored for *correct precision labelling*, not correct day.
- **Publisher-adapter viability** — for each of the 4 markets, how many of the relevant
  publishers are reachable, static, and parseable. Kodansha USA's 403 says this number
  will not be 100%.

## Still open

- **MangaDex ToS** — unresolved, gates the chapter tier.
- **Rakuten terms** — confirm whether the reproduction clause truly disqualifies it; if
  not, it solves Japanese day precision outright via a free API.
- **Carlsen / altraverse product pages** — untested; German precision viability unknown.
- **Google Books** — keyless quota is 0; needs a key before coverage can be judged.

---

# GATE 1 RESOLVED (2026-08-26): MangaDex is OUT

Nick supplied the actual Terms of Service. It is not ambiguous, and it is worse than
the "may foreclose commercial use" I guessed. Verbatim, the Site ToS prohibits:

> "systematically retrieve data or other content from the Site to **create or compile,
> directly or indirectly, a collection, compilation, database, or directory** without
> written permission from us"

That clause describes this project exactly. Three more independently disqualify it:

> "The Site may not be used in connection with any **commercial endeavors** except those
> that are specifically endorsed or approved by us."

> "use the Site and/or the Content for any **revenue-generating endeavor or commercial
> enterprise**" — listed under things you agree not to do.

> "no part of the Site and no Content … may be copied, reproduced, **aggregated**,
> republished … or otherwise exploited for any **commercial purpose whatsoever**, without
> our express prior written permission." (Access is granted for **personal use only**.)

Plus a blanket automation ban: *"engage in any automated use of the system, such as …
any data mining, robots, or similar data gathering and extraction tools"* and *"you will
not access the Site through automated or non-human means, whether through a bot, script,
or otherwise."*

**Verdict: MangaDex cannot be a source — not commercially, and not even non-commercially
for database-building, without written permission.** The API documentation grants no
broader rights; the API is part of "the Site."

**The one legitimate path** is that the compilation clause says *"without written
permission from us"* — permission is expressly contemplated. MangaDex US, Inc. is a
non-profit. A good-faith request describing an open catalog that credits scanlation
groups and links back may well succeed. It cannot be assumed, and nothing should be
built on MangaDex until it is granted in writing.

---

# THE REPLACEMENT: Wikipedia `{{Graphic novel list}}` — solves three problems at once

Probed live via the MediaWiki API. Manga volume-list articles use a **standardised
template**, machine-parseable, with everything this project needs:

```
| VolumeNumber    = 121
| RelDate         = May 17, 2018<ref>{{cite web|url=http://kc.kodansha.co.jp/product?item=0000053319 …
| ISBN            = 978-4-06-511417-9
| ChapterListCol1 = * Round 1208: {{nihongo|"Leaves"|木の葉|Ko no Ha}}
                    * Round 1209: {{nihongo|"Flashback"|flashback|flashback}}   …
| ChapterListCol2 = * Round 1213: …
```

One article yielded **25 volume entries, 25 ISBNs, 50 day-precision dates.**

This simultaneously delivers:

1. ✅ **Day-precision release dates** — the requirement Nick just set, *without scraping
   publisher sites*.
2. ✅ **Chapter → volume composition** — precisely what MangaDex was going to supply and
   the ToS just killed.
3. ✅ **ISBN + volume number**, joining cleanly to the national-library tier.

Three further advantages:

- **One parser, thousands of series.** It is a standard template, not a per-publisher
  layout. This is the opposite of the per-publisher-adapter cost the day-precision
  decision seemed to impose.
- **Every date is cited to the primary source** (here, `kc.kodansha.co.jp`) — so records
  are verifiable and attributable to the publisher, not to Wikipedia.
- **Non-English Wikipedias almost certainly carry their own market's volume lists**
  (fr.wikipedia for « L'attaque des titans », de.wikipedia for Carlsen editions). If so,
  the multi-market date problem is largely solved by the same parser. **Untested — first
  thing to check.**

### Licensing note

Wikipedia prose is CC BY-SA, which would reintroduce the share-alike problem *if prose
were copied*. It should not be. Under *Feist*, the extracted items — volume number,
release date, ISBN, chapter range — are **facts and not copyrightable**. Use Wikipedia
as a discovery and cross-check layer, extract facts only, never summaries, and cite the
primary source the article already names. Chapter *numbers and ranges* are pure fact;
for chapter *titles*, prefer the publisher's own.

---

# Revised acquisition architecture — three independent tiers

| Tier | Source | Supplies | Licensing |
|---|---|---|---|
| **0 — skeleton** | Wikipedia `{{Graphic novel list}}` | volume no., **day-precision date**, ISBN, **chapter composition** | facts only (Feist); cite primary source |
| **1 — verification** | DNB / BnF / openBD | independent existence, ISBN, page count, approximate date | CC0 (DNB), open APIs |
| **2 — tiebreak** | Publisher sites (Viz, Kodansha JP, Pika, Glénat) | authoritative confirmation | per-site `robots.txt` / ToS review |

**The key structural win: three genuinely independent sources enable real confidence
calibration.** Agreement across tiers 0 and 1 → high confidence. Disagreement → escalate
to tier 2 or flag. That is the calibration mechanism the spike's decisive metric
requires, and it now has a natural implementation rather than a hand-waved one.

It also demotes publisher scraping from *primary acquisition* to *tiebreaker*, which
substantially repairs the legitimacy story the day-precision decision had narrowed.

## Immediate next checks

1. **fr.wikipedia / de.wikipedia volume lists** — if the template travels, multi-market
   day precision is solved cheaply. Highest-value unknown.
2. **Template coverage for obscure series** — popular titles clearly have these articles;
   the mid-tier and obscure half of the spike sample is the real test.
3. **Wikidata** — CC0, may carry some of this structured already.
4. Google Books API key; Carlsen/altraverse product pages; optional MangaDex permission
   request.

---

# Google Books, keyed (2026-08-26): Western day precision solved without scraping

Retested with an API key. The earlier 429 had made this inconclusive; it is now answered.

| ISBN | Market | `publishedDate` | `pageCount` |
|---|---|---|---|
| 9784063842760 | JP Kodansha | `2010` — **year only** | 0 |
| 9783551744272 | DE Carlsen | **`2023-01-09`** ✅ | 450 |
| 9782811655990 | FR Pika | **`2020-08-19`** ✅ | 192 |
| 9781612620244 | EN Kodansha USA | **`2012-06-19`** ✅ | 0 |

**Google Books returns day-precision dates for English, German, and French from a single
free keyed API.** That removes publisher scraping from the critical path for all three
Western markets — a large repair to the legitimacy story the day-precision decision had
narrowed.

**Japanese remains the exception** (year only), so JP day precision comes from Wikipedia
(cited to `kc.kodansha.co.jp`) or the publisher directly.

### But its quality is uneven — cross-verification is mandatory, not optional

- `publisher` for the English *Attack on Titan* volume returned **"National Geographic
  Bo…"** — plainly wrong. Do not trust Google Books publisher attribution.
- `pageCount` is `0` for two of four records.
- German page count **450** vs DNB's **"circa 472 Seiten"** — a genuine ~5% cross-source
  disagreement, and a good worked example of why the calibration metric matters.
- French **192** vs BnF's **"ca 190"** — close agreement.

**Open question:** Google Books API terms restrict bulk storage/caching of returned data.
This needs the same read the MangaDex ToS just got, before Google Books is depended on as
a stored-catalogue source rather than a live lookup.

## Day-precision coverage after Step 0

| Market | Primary day source | Backup |
|---|---|---|
| EN | Google Books (keyed) | Viz `o_release-date`; Wikipedia |
| DE | Google Books (keyed) | Wikipedia; Carlsen product pages (untested) |
| FR | Google Books (keyed) | Wikipedia; Pika / Glénat |
| JP | **Wikipedia** (cited to publisher) | `kc.kodansha.co.jp` (17 dates on one page) |

Four largely independent source families — Wikipedia, Google Books, national libraries,
publisher sites — which is what makes a real confidence signal possible.

---

# Multi-market Wikipedia check (2026-08-26): the convention travels ✅

The highest-value open question — does the volume/chapter-list convention exist outside
English Wikipedia? **Yes, in every market tested.**

| Wiki | Article | Size | ISBNs | Day-precision dates |
|---|---|---|---|---|
| en | `List of Hajime no Ippo volumes (121–current)` | 32.8k | 25 | 50 (`May 17, 2018`) |
| de | `Attack on Titan` | 117.2k | **169** | 106 (`7. April 2013`) |
| fr | `L'Attaque des Titans` | 290.5k | 30 | **800** (`5 septembre 2017`) |

French also has a dedicated **`Liste des chapitres de L'Attaque des Titans`** article —
the chapter tier, in French, for the French release line.

**Caveat: the structures differ per language.** English uses the standardised
`{{Graphic novel list}}` template; French and German use their own conventions. So this
is **one parser per language (3–4 total)**, not one universal parser — still far cheaper
than one adapter per publisher, which is what the day-precision decision originally
implied.

**Net effect: day-precision dates and chapter composition are obtainable for all four
target markets without scraping a single publisher site.**

---

# ❗ Google Books ToS (2026-08-26): cannot be a stored-catalogue source

Checked because it became a primary source. The Google Books API Terms prohibit
exactly this project's shape:

> prohibits scraping, **building databases**, or creating permanent copies of content,
> or keeping cached copies longer than permitted by the cache header

> You **may not charge users any fee** for the use of your application, unless you have
> entered into a separate agreement with Google or obtained Google's written permission

That is the same class of disqualification MangaDex carries: **no database-building, and
no paid product.** Google also notes it licenses much of the underlying data, so it is
not theirs to sublicense.

**Mitigating fact: Google Books was never the primary source.** Tier-0 dates come from
Wikipedia (`LicensedRelDate`, cited to viz.com). Google Books was used only as the
independent *cross-verifier* in tier 1. So the extracted dataset survives; what needs
replacing is the verification channel — and national libraries plus publisher pages are
cleaner substitutes.

## Source licensing scoreboard

| Source | Build a stored database? | Usable in a paid product? |
|---|---|---|
| **DNB** (Germany) | ✅ **CC0 — unrestricted** | ✅ |
| **BnF** (France) | Open, unauthenticated — likely yes | probably; confirm |
| **Wikipedia** | Facts only (*Feist*); never prose | Facts yes; EU database-right exposure |
| Publisher sites | Per-site `robots.txt` / ToS | Per-site |
| openBD | Unverified | Unverified |
| **Google Books** | ❌ **prohibited** | ❌ **prohibited** |
| **MangaDex** | ❌ prohibited | ❌ prohibited |
| **Rakuten Books** | ❌ reproduction prohibited | ❌ |

Three of the most productive sources — Google Books, MangaDex, Rakuten — are all
unusable for a stored, commercial catalogue.

## Architectural consequence: tag provenance per field, from day one

Every value must carry `*_source`. That single discipline preserves the ability to emit
**two views** of the same catalogue later:

- **Full view** — everything, free/non-commercial only.
- **Clean view** — filtered to commercially unencumbered provenance (DNB, BnF,
  publisher-direct, own verification). Smaller, but licensable.

Without per-field provenance this option is gone permanently, because you cannot
retroactively determine which values came from where. This costs almost nothing now and
is unrecoverable later.
