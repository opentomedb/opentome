"""Measure an artifact against a REAL Mangarr library (a copy of readarr.db, or the
committed snapshot of one).

    python3 export/measure_library.py build/manga-metadata.sqlite (readarr.db | library.json) [old-artifact]

For every series in the library this replays Mangarr's FindSeriesByTitle
(GcdMetadataService.cs) exactly -- the candidate query on name / alias /
normalized alias, then the ranking -- and checks the one thing that matters:
every volume Nick OWNS must exist in the line the artifact would pick. It
also counts the volumes beyond what he owns, because each past-dated one goes
into the scheduled missing-search rotation.

This is the regression gate. The first export "matched 38/41" on this library
and would still have overwritten Attack on Titan's 34 owned volumes with a
17-volume spin-off's dates, because aggregate match counts hide line-level
wrong picks. Clean room: the library's FOLDERS and OWNED VOLUME NUMBERS are
Nick's own facts; nothing from the old GCD artifact is used as truth here --
it is only shown side by side so a behavioural regression is visible.

The library argument may be `export/fixtures/library.json` -- the snapshot
`snapshot_library.py` writes from a readarr.db copy (names, folder basenames,
status, owned volume numbers). The gate then needs no database and no host:
that is what a CI run measures against.
"""
import json, os, sqlite3, sys, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from to_mangarr import normalize, heads

MANGA_FAMILY = ("manga", "manhwa", "manhua", "webtoon", None)
TODAY = str(datetime.date.today())


def candidates(db, title):
    t = (title or "").strip()
    n = normalize(title)
    ids = {r[0] for r in db.execute("""
        SELECT gcd_series_id FROM series WHERE name=? COLLATE NOCASE
        UNION SELECT gcd_series_id FROM series_alias WHERE alias=? COLLATE NOCASE
        UNION SELECT gcd_series_id FROM series_alias WHERE alias=? COLLATE NOCASE""", (t, t, n))}
    if not ids:
        return []
    cols = [r[1] for r in db.execute("PRAGMA table_info(series)")]
    has_medium = "medium" in cols
    rows = db.execute("SELECT * FROM series WHERE gcd_series_id IN (%s)" % ",".join(map(str, ids))).fetchall()
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        d.setdefault("medium", None)
        d.setdefault("dated_count", None)
        if d["dated_count"] is None:
            d["dated_count"] = db.execute("""SELECT COUNT(*) FROM volumes WHERE gcd_series_id=?
                                             AND release_date IS NOT NULL""", (d["gcd_series_id"],)).fetchone()[0]
        d["exact"] = normalize(d["name"]) == n
        out.append(d)
    return out


def rank_new(cands, query, prefer_novel=False):
    """The ranking the C# implements after the 2026-09-03 change (library-aware since
    2026-09-14): English only; a light-novel entry (prefer_novel) sees novel lines only;
    exact name first; manga family before light novels; non-omnibus first; more dated
    volumes; more volumes; lowest id."""
    en = [c for c in cands if c["language"] == "en"]
    if prefer_novel:
        en = [c for c in en if c["medium"] not in MANGA_FAMILY]
    if not en:
        return None
    return sorted(en, key=lambda c: (not c["exact"], c["medium"] not in MANGA_FAMILY,
                                     c["is_omnibus"], -c["dated_count"],
                                     -c["volume_count"], c["gcd_series_id"]))[0]


def rank_old(cands, query):
    """The ranking before the change (language=='en' first, then non-omnibus,
    then volume count) -- kept so the delta is visible."""
    if not cands:
        return None
    return sorted(cands, key=lambda c: (c["language"] != "en", c["is_omnibus"],
                                        -c["volume_count"], c["gcd_series_id"]))[0]


def pick(db, names, ranker):
    """Mangarr tries displayName then name; offline we try each stored name
    and then the arc title after the last ':' or ',' when it is 3+ words --
    exactly GcdMetadataService.FindSeriesBySubtitle, no more."""
    for q in names:
        c = candidates(db, q)
        if c:
            p = ranker(c, q)
            if p:
                return p, q
    for q in names:
        for sep in (":", ","):
            if sep not in q:
                continue
            tail = q.rsplit(sep, 1)[1].strip().rstrip("-–").strip()
            if len(normalize(tail).split()) >= 3:
                c = candidates(db, tail)
                if c:
                    p = ranker(c, tail)
                    if p:
                        return p, tail
    return None, None


def library(readarr):
    """One dict per series: id, name, folder, owned (sorted volume numbers), status.
    From a readarr.db copy, or from the .json snapshot of one (same rows, same order;
    the snapshot carries no Mangarr ids)."""
    if readarr.endswith(".json"):
        with open(readarr, encoding="utf8") as f:
            return [dict(id=None, name=s["name"], folder=s["folder"], owned=sorted(set(s["volumes"])), status=s["status"])
                    for s in json.load(f)]
    L = sqlite3.connect(readarr)
    rows = L.execute("""SELECT a.Id, am.Name, a.Path, am.Status FROM Authors a
                        JOIN AuthorMetadata am ON am.Id=a.AuthorMetadataId ORDER BY am.Name""").fetchall()
    out = []
    for aid, name, path, status in rows:
        owned = sorted({r[0] for r in L.execute("""
            SELECT b.VolumeNumber FROM BookFiles bf JOIN Editions e ON e.Id=bf.EditionId
            JOIN Books b ON b.Id=e.BookId JOIN Authors a ON a.AuthorMetadataId=b.AuthorMetadataId
            WHERE a.Id=? AND b.VolumeNumber IS NOT NULL""", (aid,))})
        out.append(dict(id=aid, name=name, folder=os.path.basename(path.rstrip("/")),
                        owned=owned, status=status))
    return out


def measure(art_path, readarr, old_path=None, verbose=True):
    A = sqlite3.connect(art_path)
    O = sqlite3.connect(old_path) if old_path and os.path.exists(old_path) else None
    fails, rows = [], []
    tot_beyond_past = 0
    n_pick_id = 0
    for s in library(readarr):
        names = [s["name"], s["folder"]]
        p, q = pick(A, names, rank_new)
        op, _ = pick(O, names, rank_old) if O else (None, None)
        owned = set(s["owned"])
        if p:
            n_pick_id += p.get("anilist_id") is not None
            have = {r[0] for r in A.execute("SELECT volume_number FROM volumes WHERE gcd_series_id=?", (p["gcd_series_id"],))}
            missing = sorted(owned - have)
            beyond = [r for r in A.execute("""SELECT volume_number, release_date FROM volumes
                        WHERE gcd_series_id=? AND volume_number>?""", (p["gcd_series_id"], max(owned) if owned else 0))]
            past = sum(1 for _, d in beyond if d and d <= TODAY)
            tot_beyond_past += past
            ok = not missing
            if not ok:
                fails.append((s["name"], p["name"], missing))
            rows.append((s["name"], len(owned), f"{p['name'][:34]} [{p['medium'] or '?'}] v{p['volume_count']} d{p['dated_count']}",
                         "OK" if ok else f"MISSING {missing[:6]}", f"+{len(beyond)} ({past} past)",
                         f"{op['name'][:22]} v{op['volume_count']}" if op else "--"))
        else:
            rows.append((s["name"], len(owned), "-- no match --", "miss", "", f"{op['name'][:22]} v{op['volume_count']}" if op else "--"))
    if verbose:
        print(f"{'series':40} {'own':>3}  {'NEW pick':52} {'coverage':22} {'beyond':14} OLD pick")
        for r in rows:
            print(f"{r[0][:40]:40} {r[1]:>3}  {r[2]:52} {r[3]:22} {r[4]:14} {r[5]}")
        matched = sum(1 for r in rows if r[3] != "miss")
        print(f"\nmatched {matched}/{len(rows)}   coverage failures {len(fails)}   past-dated volumes beyond owned {tot_beyond_past}")
        en3, en3_id = A.execute("SELECT COUNT(*), SUM(anilist_id IS NOT NULL) FROM series WHERE language='en' AND volume_count>=3").fetchone()
        print(f"anilist_id: picked lines with an id {n_pick_id}/{matched}   EN lines (volume_count >= 3) {en3_id or 0}/{en3}")
        for name, pick_name, missing in fails:
            print(f"  FAIL {name}: picked '{pick_name}' lacks owned volumes {missing}")
    return rows, fails


# German market floors (docs/dnb-design.md "Gates"). The first full DNB build (2026-09-24)
# measured 1,593 lines / 12,678 volumes, dates 95.8 %, page counts 97.8 %, link rate 34.9 %;
# the count floors leave ~15-20 % headroom, so a regression that loses a large part of the
# DNB lines fails the build instead of shipping quietly. The coverage floors are the design's.
DE_MIN_LINES = 1300
DE_MIN_VOLUMES = 10500
DE_MIN_YEAR_COVERAGE = 0.95      # German volumes with a date of any precision
DE_MIN_PAGE_COVERAGE = 0.90      # German volumes with a page count
DE_MIN_LINK_RATE = 0.30          # exported DNB lines / all DNB lines


def measure_de(art_path, catalogue=None):
    """-> list of failed German gates. Printed after the library replay (CI greps 'matched')."""
    A = sqlite3.connect(art_path)
    g = lambda q: A.execute(q).fetchone()[0]
    fails = []

    def gate(label, ok, detail):
        print(("  ok   " if ok else "  FAIL ") + label + ": " + detail)
        if not ok:
            fails.append(label)
    lines = g("SELECT COUNT(*) FROM series WHERE language='de'")
    vols = g("SELECT COUNT(*) FROM volumes v JOIN series s USING(gcd_series_id) WHERE s.language='de'")
    dated = g("""SELECT COUNT(*) FROM volumes v JOIN series s USING(gcd_series_id)
                 WHERE s.language='de' AND v.release_date_raw IS NOT NULL""")
    paged = g("""SELECT COUNT(*) FROM volumes v JOIN series s USING(gcd_series_id)
                 WHERE s.language='de' AND v.page_count IS NOT NULL""")
    print("\nGerman market (DNB):")
    gate("DE lines", lines >= DE_MIN_LINES, "%s (floor %s)" % (format(lines, ","), format(DE_MIN_LINES, ",")))
    gate("DE volumes", vols >= DE_MIN_VOLUMES, "%s (floor %s)" % (format(vols, ","), format(DE_MIN_VOLUMES, ",")))
    gate("DE date coverage", vols and dated / vols >= DE_MIN_YEAR_COVERAGE,
         "%.1f%% (%s/%s; floor %.0f%%)" % (100 * dated / max(vols, 1), format(dated, ","), format(vols, ","),
                                          100 * DE_MIN_YEAR_COVERAGE))
    gate("DE page-count coverage", vols and paged / vols >= DE_MIN_PAGE_COVERAGE,
         "%.1f%% (%s/%s; floor %.0f%%)" % (100 * paged / max(vols, 1), format(paged, ","), format(vols, ","),
                                          100 * DE_MIN_PAGE_COVERAGE))
    try:
        roles = json.loads(g("SELECT value FROM meta WHERE key='dnb_lines'") or "{}").get("roles", {})
    except (TypeError, sqlite3.OperationalError):
        roles = {}
    total = sum(roles.values())
    out = sum(roles.get(r, 0) for r in ("merged", "sibling", "linked", "kept"))
    gate("DNB link rate", total > 0 and out / total >= DE_MIN_LINK_RATE,
         "%.1f%% (%s of %s DNB lines exported; floor %.0f%%) %s" % (
             100 * out / max(total, 1), format(out, ","), format(total, ","), 100 * DE_MIN_LINK_RATE,
             json.dumps(roles, sort_keys=True)))
    if catalogue:
        gate("DNB reload gives the same ids", *same_ids(catalogue))
    return fails


def same_ids(catalogue):
    """Rebuild the DNB line keys from the cached records (offline) and compare them with the
    catalogue's: the same member records must land in the same lines, under the same ids."""
    os.environ["DNB_OFFLINE"] = "1"
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(root, "tier0"))
    import build_dnb as B, dnb_enumerate as E
    recs, parents, _ = E.enumerate_all(verbose=False)
    allparents = dict(parents)
    allparents.update({k: r for k, r in recs.items() if B.M.is_parent(r)})
    kept, _ = B.select(recs, allparents)
    groups, _ = B.twins(kept)
    now = {m["idn"]: key for key, gs in B.cluster(groups, allparents).items() for g in gs for m in g["members"]}
    C = sqlite3.connect(catalogue)
    was = dict(C.execute("SELECT idn, line_key FROM dnb_member"))
    # a merged line IS its Wikipedia line and carries that id by design
    ids = dict(C.execute("SELECT key, rl_id FROM dnb_line WHERE role<>'merged'"))
    moved = sum(1 for i, k in now.items() if was.get(i) != k)
    rekeyed = sum(1 for k, rid in ids.items() if B._id("rl_", k) != rid)
    return (moved == 0 and rekeyed == 0 and len(now) == len(was),
            "%s member records, %d in another line, %d line ids re-keyed" % (format(len(now), ","), moved, rekeyed))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--catalogue=")]
    cat = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--catalogue=")), None)
    rows, fails = measure(args[0], args[1], args[2] if len(args) > 2 else None)
    de_fails = measure_de(args[0], cat)
    sys.exit(1 if fails or de_fails else 0)
