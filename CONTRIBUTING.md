# Contributing

OpenTome is a catalogue, so most contributions are facts: a date the sources got
wrong, a volume they do not carry, an edition that exists in a market and is
missing here. There are two ways in — an issue when you have noticed something,
a pull request when you have checked it.

## The one rule

**A correction records what a source says, not what someone believes.** Every
entry, in an issue or a pull request, names the publisher page, library record
or other primary source that was actually checked. A correction with no source
is a guess with better formatting, and the pipeline exists to keep guesses out.

## Filing an issue

Pick the template that fits; each asks for the OpenTome id (`tome_id`) or the
AniList id, the market, what is wrong or missing, and the source URL.

| Template | Use it when |
|---|---|
| **Wrong fact** | a date, ISBN, page count, title or name in the catalogue is wrong |
| **Missing volume** | a volume exists in a market and the catalogue does not have it |
| **New release line** | a whole edition is missing — a market, publisher or edition with no line at all |
| **Merge lines** | two entries are one release line, or two works are one work |

Mangarr's *Suggest a correction* link opens the **Wrong fact** form with the ids
already filled in.

## Opening a corrections pull request

Corrections are data, not code: three JSON files under `corrections/`, one
entry per fact, each with a `source_url` and a `checked` date.
[`corrections/README.md`](corrections/README.md) documents the three files, the
keys each entry needs and how to find an id.

1. Fork, branch, add your entries to `corrections/volumes.json`,
   `corrections/lines.json` or `corrections/aliases.json`.
2. Download the published artifact (the keys are checked against it):
   `https://github.com/itsnickspiro/mangarr-metadata/releases/download/metadata/manga-metadata.sqlite`
3. Run the check:

   ```bash
   python3 tier2/corrections.py --check corrections/ --artifact manga-metadata.sqlite
   ```

   It exits 0 with `corrections check ok` when every entry is well-formed and
   every id or ISBN resolves; otherwise it names the file, the index and the
   reason. It writes nothing.
4. Open the pull request. The same check runs on it automatically
   (`.github/workflows/corrections-check.yml`), with `tier0/test_parser.py` and
   `tier2/test_corrections_check.py`.

A merged correction lands in the next build and is asserted by the artifact's
contract test, so it cannot silently disappear in a later rebuild.

Corrections are for facts the sources get wrong or do not carry. If the pipeline
*mis-reads* a source, that is a parser bug: fix it in `tier0/` and every series
benefits. Pull requests for code are welcome too — keep them small, and run
`python3 tier0/test_parser.py` before opening one.

## What you license

By contributing you agree that your contribution is released under the
repository's terms: **MIT** for code (`LICENSE`), **CC BY-NC 4.0** for data
(`LICENSE-DATA.md`). Do not contribute data you do not have the right to
contribute under those terms.

## Politeness

- **`.cache/` is never committed.** It holds raw responses from third-party
  sources whose terms do not allow redistribution. `build/` is never committed
  either; builds are release assets.
- **No new source without a licence line.** Every claim the pipeline stores
  carries a `licence`; [`docs/legal-position.md`](docs/legal-position.md) records
  what each source's terms say and [`LICENSE-DATA.md`](LICENSE-DATA.md) what that
  means for the data (Google Books, MangaDex and Rakuten Books are excluded by
  their terms). A pull request that adds a source states its terms and the
  `licence` value it stores, or it is not merged.
- **Be polite to sources.** Serial access, throttled, disk-cached so a re-run
  costs zero requests. Never scrape a site whose `robots.txt` or terms refuse
  it — that is what `corrections/lines.json` is for.
