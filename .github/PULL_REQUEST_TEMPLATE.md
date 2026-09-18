## What this changes

<!-- One line per correction: the volume / line / alias, and what the source says. -->

## Checklist

- [ ] Every entry has a `source_url` — the publisher page or library record I actually checked — and a `checked` date.
- [ ] I ran `python3 tier2/corrections.py --check corrections/ --artifact manga-metadata.sqlite` against the published artifact and it printed `corrections check ok`.
- [ ] This is a fact the sources get wrong or do not carry, not a workaround for a parser bug (those are fixed in the parser, for every series at once).
- [ ] Nothing under `.cache/` or `build/` is in this pull request.

By opening this pull request I license my contribution under the repository's terms: MIT for code, CC BY-NC 4.0 for data (`LICENSE-DATA.md`).
