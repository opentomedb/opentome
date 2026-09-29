"""Stage 4b2: the comic medium of a Korean / Chinese work (heading cleanup B, 2026-09-29; spec
docs/superpowers/specs/2026-09-29-heading-cleanup-design.md §3.2).

    python3 tier0/comic_medium.py build/opentome.db

Many Korean and Chinese works' comic lines load as 'manga' because no source said otherwise:
release_lines.detect_medium's default (a French article's Korean original slot, a German table), and
a KR/CN library line merged into such a line takes its medium (build_krcn.decide). Rule: a 'manga'
line of a work whose ORIGIN market is KR becomes 'manhwa'; CN or TW -> 'manhua'. The origin is the
export's own decision (export/to_mangarr.origin_markets: pick_origin per (work, medium), then the
comic family, E3), computed over this catalogue. pick_origin already makes JP the origin of a work
whose Japanese 'manga' line shipped first; the one case it cannot see is a work with no 'manga' line in
any origin market whose origin came from the comic FAMILY -- a Japanese light novel with a Korean manhwa
adaptation and a German 'manga' edition. Those are left alone when the work has a JP line, and listed
as `guarded` for review.

The medium changes IN PLACE: the line keeps its id (ids are a public contract; its id hashed 'manga'
once, and every build flips it again the same way). Then a line the flip made the SAME line as another
-- same work, market, new medium and name.strip().lower() (the export's line_key, not normalize()) --
is folded into it with carried_ids.merge_line (the Recast shape: the French article's ko 'manga' line and
the English article's ko 'manhwa' line, 6 volumes each). The survivor is the line that already had the
medium, else the one with more volumes, else the lower id; stage 7b redirects the folded id
(carried_ids.redirects follows its ISBNs into the new medium). Stage 4c cannot do this fold: it only
compares an absorbed work's re-keyed lines, never two lines the carry both has. Never folded, only
reported: a line a library owns (a dnb_line or krcn_line row points at it: the 8d reload gates compare
those ids) or a corrections/lines.json entry names (`kept`), and a pair whose volumes disagree -- a
number both lines have under different ISBNs, which merge_line would drop from the folded line
(`differ`: Solo Leveling's two ko lines, 13 of 15 ISBNs different, are two editions). After the retag
both lines of a `differ` pair carry one name and one medium, so the export's name match (to_mangarr
line_key, last write wins) would send every licensed line to the same one: each other-market line that
paired by name with one of the two BEFORE the retag gets a derived origin_line pin to it (source 'opentome',
the pin carried_ids.merge_line writes), unless it already has one.

After 3f (a library line merged into a Wikipedia line flips with it) and the enrichment (4c's
reason: a line dropped earlier shifts openBD's batch cache); before 4c and 5b, so a
corrections/lines.json medium entry still has the last word."""
import collections, json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "export"))
from to_mangarr import origin_markets, normalize          # noqa: E402
from carried_ids import merge_line, _table, LICENCE, NOW    # noqa: E402
import corrections as CORR                                  # noqa: E402  (tier2, on carried_ids' path)

TARGET = {"KR": "manhwa", "CN": "manhua", "TW": "manhua"}


def _names(db):
    """{line: name}: its Wikipedia line_name claim, else another source's (the earliest row wins)."""
    out = {}
    for rid, v in db.execute("""SELECT entity_id, value FROM claim WHERE entity='release_line' AND field='line_name'
                                ORDER BY source='wikipedia', rowid DESC"""):
        out[rid] = v
    return out


def _corrected_lines():
    """Line ids a corrections/lines.json entry names: an override's `line`, an added line's hashed id,
    an `origin_line` pin's target."""
    out = set()
    for e in CORR._read("lines.json", CORR.DIR):
        if e.get("line"):
            out.add(e["line"])
        if "volumes" in e:
            out.add(CORR._id("rl_", e["work"], e["medium"], e["market"].upper(), e["name"].strip()))
        if e.get("origin_line"):
            out.add(e["origin_line"])
    return out


def plan(db):
    """-> (flips {line: new medium}, merges [(folded line, survivor)], kept [(owned line, survivor)],
    differ [(line, survivor, numbers that disagree)], guarded [(line, medium it would take)]) for the
    catalogue as it stands. Changes nothing."""
    works = dict(db.execute("SELECT id, primary_title FROM work"))
    names = _names(db)
    lines = db.execute("SELECT id, work_id, market, medium FROM release_line ORDER BY id").fetchall()
    size = dict(db.execute("SELECT release_line_id, COUNT(*) FROM volume GROUP BY 1"))
    first = dict(db.execute("""SELECT release_line_id, MIN(release_date) FROM volume WHERE release_date IS NOT NULL
                               AND release_date_precision IN ('day','month') GROUP BY 1"""))
    isbn_of = collections.defaultdict(dict)                 # line -> {number: isbn13}
    for rid, number, isbn in db.execute("SELECT release_line_id, number, isbn13 FROM volume"):
        isbn_of[rid][number] = isbn
    name_of = lambda rid, wid: names.get(rid) or works[wid]
    markets_of, groups = collections.defaultdict(set), collections.defaultdict(list)
    for rid, wid, market, medium in lines:
        markets_of[(wid, medium)].add(market)
        groups[(wid, market, medium)].append((normalize(name_of(rid, wid)) != normalize(works[wid]),
                                              -size.get(rid, 0), rid))
    # the export's main line per (work, market, medium): the line named after the work, else the biggest
    main_of = {k: sorted(v)[0][2] for k, v in groups.items()}
    origin_of, family = origin_markets(markets_of, main_of, first)
    jp_works = {wid for _, wid, market, _ in lines if market == "JP"}
    flips, guarded = {}, []
    for rid, wid, market, medium in lines:
        if medium != "manga" or origin_of.get((wid, "manga")) not in TARGET:
            continue
        if wid in jp_works and (wid, "manga") in family:
            guarded.append((rid, TARGET[origin_of[(wid, "manga")]]))
        else:
            flips[rid] = TARGET[origin_of[(wid, "manga")]]
    owned = _corrected_lines()
    if _table(db, "dnb_line"):
        owned |= {r for (r,) in db.execute("SELECT rl_id FROM dnb_line WHERE rl_id IS NOT NULL")}
    if _table(db, "krcn_line"):
        owned |= {r for row in db.execute("SELECT rl_id, target FROM krcn_line") for r in row if r}
    same = collections.defaultdict(list)
    for rid, wid, market, medium in lines:
        same[(wid, market, flips.get(rid, medium), name_of(rid, wid).strip().lower())].append(rid)
    merges, kept, differ = [], [], []
    for key in sorted(same):
        rids = same[key]
        if len(rids) < 2 or not any(r in flips for r in rids):
            continue                    # only a duplicate THIS flip made; older twins are not ours
        keep = sorted(rids, key=lambda r: (r in flips, -size.get(r, 0), r))[0]
        for r in rids:
            if r == keep:
                continue
            clash = sorted(n for n, i in isbn_of[r].items() if i and n in isbn_of[keep] and isbn_of[keep][n] != i)
            if r in owned:
                kept.append((r, keep))
            elif clash:
                differ.append((r, keep, len(clash)))
            else:
                merges.append((r, keep))
    return flips, merges, kept, differ, sorted(guarded)


def differ_pins(db, differ):
    """[(other-market line, the differ-pair line it paired with by name BEFORE the retag)]: same work, another
    market, the same pre-retag medium and name.strip().lower(), no origin_line claim yet. Read before apply()
    changes any medium."""
    if not differ:
        return []
    works = dict(db.execute("SELECT id, primary_title FROM work"))
    names = _names(db)
    info = {rid: (wid, market, medium) for rid, wid, market, medium in
            db.execute("SELECT id, work_id, market, medium FROM release_line ORDER BY id")}
    pinned = {e for (e,) in db.execute("SELECT entity_id FROM claim WHERE entity='release_line' AND field='origin_line'")}
    key = lambda rid: (names.get(rid) or works[info[rid][0]]).strip().lower()
    out = []
    for dup, keep, _ in differ:
        for line in (keep, dup):
            wid, market, medium = info[line]
            out += [(o, line) for o, (ow, om, od) in info.items()
                    if ow == wid and om != market and od == medium and o not in pinned and key(o) == key(line)]
    return sorted(set(out))


def apply(db):
    """Stage 4b2. -> {"flips": [(line, medium)], "merges": [(folded, survivor, moved, dropped)],
    "kept": [(owned line, survivor)], "differ": [(line, survivor, n)], "guarded": [(line, medium)],
    "pins": [(licensed line, origin line)]}, also written to meta 'comic_medium' (merged into a stored report: each
    list a de-duplicated union, so a re-run keeps what the first run did)."""
    flips, merges, kept, differ, guarded = plan(db)
    pins = differ_pins(db, differ)
    c = db.cursor()
    for lid, origin in pins:
        c.execute("""INSERT OR IGNORE INTO claim(entity,entity_id,field,value,source,source_url,licence,retrieved_at)
                     VALUES('release_line',?,'origin_line',?,'opentome',NULL,?,?)""", (lid, origin, LICENCE["opentome"], NOW))
    for rid, medium in sorted(flips.items()):
        c.execute("UPDATE release_line SET medium=? WHERE id=?", (medium, rid))
    done = []
    for dup, keep in merges:
        moved, dropped = merge_line(c, dup, keep)
        done.append((dup, keep, moved, dropped))
    rep = {"flips": sorted(flips.items()), "merges": done, "kept": kept, "differ": differ, "guarded": guarded,
           "pins": pins}
    stored = {}                         # a re-run past 4b2 (KEEP_DB=1) finds nothing left to do: keep the earlier report
    row = c.execute("SELECT value FROM meta WHERE key='comic_medium'").fetchone()
    if row:
        try:
            stored = json.loads(row[0])
        except ValueError:
            stored = {}
    merged = {}
    for k, new_rows in rep.items():
        seen, out = set(), []
        for r in list(stored.get(k, [])) + [list(x) for x in new_rows]:
            if json.dumps(r) not in seen:
                seen.add(json.dumps(r))
                out.append(r)
        merged[k] = out
    c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('comic_medium',?)", (json.dumps(merged),))
    db.commit()
    return rep


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    rep = apply(sqlite3.connect(argv[1], timeout=60))
    by = collections.Counter(m for _, m in rep["flips"])
    print("  'manga' lines of Korean / Chinese works retagged in place: %d (%s)" % (
        len(rep["flips"]), ", ".join("%s %d" % kv for kv in sorted(by.items())) or "none"))
    for dup, keep, moved, dropped in rep["merges"]:
        print("    folded %s into %s (%d volumes moved, %d dropped; 7b redirects it)" % (dup, keep, moved, dropped))
    for dup, keep in rep["kept"]:
        print("    NOT folded: %s is a library or corrected line -- the same line as %s; review" % (dup, keep))
    for dup, keep, n in rep["differ"]:
        print("    NOT folded: %s and %s disagree on %d volume(s) -- two editions; review" % (dup, keep, n))
    for lid, origin in rep["pins"]:
        print("    origin_line pin (a differ pair shares one name now): %s -> %s" % (lid, origin))
    for rid, medium in rep["guarded"]:
        print("    guarded (JP line, family-derived origin): %s stays manga (would be %s); review" % (rid, medium))


if __name__ == "__main__":
    main(sys.argv)
