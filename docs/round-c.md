# Round C: line names

A Mangarr user sees an OpenTome line name as a series name. Round C cleans up names that were never real
qualifiers, and merges lines that are one series split in two. Design: `docs/superpowers/specs/2026-10-02-round-c-line-names-design.md`.

## What changes

Names are changed at export only, so no id moves. Merges happen in a pipeline stage and retire ids.

| Class | What it fixes | Example |
|---|---|---|
| D | The work's Wikipedia disambiguator inside the line name | `The Water Magician (novel series) (Part 1)` becomes `The Water Magician (Part 1)` |
| S | A spin-off line whose title already names the work | `86 (novel series) (86: Eighty-Six - Fragmental Neoteny)` becomes `86: Eighty-Six - Fragmental Neoteny` |
| W | A section word on a line that is alone in its work, market and medium | `Whispered Words (Médias)` becomes `Whispered Words` |
| M | A section word that says the medium, on a line tagged manga | `Hyouka (Roman)` is retagged to the word's medium |
| T | A continuation tail beside its main line | FR `Black Butler (Tomes 31 à aujourd'hui)` merges into `Black Butler` |
| W2 | A section-word line beside a same-name sibling | `Insomniacs After School (Mangas)` merges into `Insomniacs After School` |

Library-born lines (`dnb:`, `bnf:`, `loc:` keys) are never renamed.

## Guards

A rename that trips a guard keeps its pipeline name, and the line is listed with the reason.

- **Within a work:** two lines of one work, market and medium may not end up with the same name (`held-clash`).
- **Across works:** a rename may not create a name two works share, unless the previous artifact already had that pair. The line keeps the disambiguator instead.
- **ISBN:** an M retag is held when a line of the target medium in the same work and market shares most of its ISBNs, because a heading is not proof of medium (`held-isbn`).
- **Medium:** an M retag is also held when it would break the origin line, the main line or a parent link (`held-medium`).
- **Lookup:** Mangarr's title ranking is replayed for the new name and the base title in both libraries. A rename that would make a library pick the other library's line, or another work, is held (`held-lookup`).
- **Origin:** a licensed line pairs with an origin-market line (Japanese, Korean or Chinese) by name. A rename is held when the new name equals the name of a same-work, same-medium origin-market line that is not the line's own origin, because the pair would be false (`held-origin`). This runs last, in the lookup guard's loop, so a revert that creates such a clash is caught.

Only D renames are cross-work guarded. A W or S rename onto another work's name is not held: the export gate catches it and fails the build loudly.

A merge needs the target to be the work's own line and no arc split out of the candidate. The verdict is `extend` when the candidate's volumes continue the target's: no shared number, and the candidate's first number is the target's last number plus one. It is `duplicate` when every candidate volume is already on the target with the same ISBN-13, or carries no ISBN at all. Anything else is `kept`. A candidate wholly above the target with a gap is kept with the reason `gap`: Gamaran's `(Tomes 31 à aujourd'hui)` tail continues the sequel, not the 22-volume original.

## How merges retire ids

- Stage 4c2 (`tier0/round_c_merge.py`) merges the candidate into the target with `carried_ids.merge_line` and records every decision in the build database as `roundc:merged`, with each candidate's pipeline name as `roundc:names`.
- Stage 7b writes a redirect for each retired line and volume, so a client holding an old id follows it to the surviving one. It reads `roundc:merged` before any ISBN vote: the candidate line goes to its target, and each volume to the target's volume of the same number. Lines without ISBNs would otherwise tie or retire.
- The artifact meta carries `round_c_merges` (applied merges, rows of candidate, target, verdict, kind and the candidate's name) and `round_c_conflicts` (carried merges the data now refuses). The next build re-applies each carried merge by id, under the same verdict, so a carried merge with a gap becomes a `carry-conflict`.
- The re-ship gate fails the build if a carried merge candidate is still shipped, except the ids listed in `round_c_conflicts`.
- The moved-id gate excludes exactly the ids of this build's recorded merges and their volumes, and prints both counts.

## Reports

All four land in `build/` next to the artifact and are uploaded with the catalogue CI artifact.

- `round-c-report.tsv`: one row per renamed, retagged, held or merge-decided line, and a tome_id appears once. Columns: tome_id, work_id, market, medium before and after, name before and after, rules, held, lookup. Merge rows use the rules `T-extend`, `T-duplicate`, `W2-extend`, `W2-duplicate`, `kept` and `carry-conflict`. A line with both a rename row and a merge decision gets one row, its rules and held values joined with commas.
- The held column holds a guard label (`held-clash`, `held-cross`, `held-isbn`, `held-medium`, `held-lookup`, `held-origin`) or, on a `kept` or `carry-conflict` row, the reason: `verdict:kept`, `gap`, `arc` or `not-own-line`.
- A kept or carry-conflict row shows the candidate line itself with its pipeline medium. A merged row shows the target's work, market, medium and written name, and the candidate's name from stage 4c2, else from the previous artifact's series row, else from its `round_c_merges` row.
- The lookup column is filled for renamed English lines: the lookup guard's replay of the written names, as the comic and novel library picks before and after the rename (per query when the base title is a second query), or `unchanged`.
- `round-c-unmatched-disambiguators.tsv`: work_id, work_title, parenthetical, lines. One row per work whose primary title ends in a ` (...)` the disambiguator rule does not match, as candidates for new disambiguator words.
- `round-c-mainless.tsv`: work_id, language, medium, tome_ids. A (work, language, medium) group of the written series with no main line after an M retag. `is_main` is not changed; the groups are listed for review.
- `round-c-anilist.tsv`: tome_id, name, AniList id before and after, for every line present in both this build and the previous artifact whose name changed. Written by `export/resolve_anilist.py --carry`, no network.
