# Data licence

The code in this repository is MIT-licensed (`LICENSE`). This file is about the
**catalogue** — the published `manga-metadata.sqlite` and any other dataset built
from this repository.

## The compilation

As far as the compilation is ours — the selection, reconciliation, ids, confidence
scoring and structure — the catalogue is released under
**[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)**: free to use,
copy and redistribute, with attribution, for non-commercial purposes.

The artifact says the same in its `meta` table: *Free/non-commercial use. openBD and
Open Library terms are non-commercial; see docs/legal-position.md before any paid use.*

## The sources control their own fields

Provenance is recorded per claim in the pipeline (the `claim` table in
[`schema/`](schema/): source, source URL and licence for every value). The published
file does **not** carry it per field — a downloader cannot tell which source a given
date or ISBN came from — so the whole published file is treated as non-commercial:
CC BY-NC 4.0 plus the strictest terms of any source in it. Those terms, per source:

| Source | Terms | What that means here |
|---|---|---|
| Bibliothèque nationale de France (BnF) | Etalab Open Licence (Licence Ouverte) | any use, attribution required |
| Deutsche Nationalbibliothek (DNB) | CC0 | any use, no conditions |
| Wikipedia | facts only | we extract facts (dates, ISBNs, counts), never prose; CC BY-SA does not attach to facts |
| openBD | purpose-limited | granted for "book promotion and introduction"; the data must not be altered |
| Open Library / Internet Archive | non-commercial, research | access is for scholarship and research; use certified non-commercial |

**Google Books, MangaDex and Rakuten Books are not used.** All three forbid
database-building and/or commercial use.

Because openBD and Open Library values are in the full build and the file does not
say which values they are, the full build is non-commercial. A commercial-clean
subset (BnF, DNB and Wikipedia-fact values only, selected from the pipeline's
provenance) is possible and is a separate, later decision.

## Attribution

Ship this with any copy of the data (it is `meta.attribution` in the artifact):

> Bibliographic data: Bibliotheque nationale de France (Licence Ouverte/Open Licence); Deutsche Nationalbibliothek (CC0); openBD; Open Library / Internet Archive; Wikipedia contributors (facts only). Cover art is not included.

## What we do not know

We are not lawyers. Facts are not copyrightable in the United States (*Feist*); the
EU *sui generis* database right is an open question we have not had answered, and
Europe is a target market. The full record of what each source's terms say, checked
rather than assumed, is in [`docs/legal-position.md`](docs/legal-position.md). Read
it before any paid use.
