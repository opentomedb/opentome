"""Stage 6b: sanity after resolve (the corrections round, 2026-11-23). Holds a resolved value the catalogue's own
shape contradicts; never deletes a claim, never rewrites a value.

    python3 tier2/sanity.py build/opentome.db [build-dir]

A. An ISBN whose registration group names another market than the line's (known groups only: 978-4 Japan,
   978-0 / 978-1 / 979-8 English, 978-2 / 979-10 France, 978-3 Germany, 978-89 / 979-11 Korea, 978-7 China) is
   held: the row's isbn13 is nulled and an `opentome` claim `isbn_held` = `market:<group's market>` records it.
   TypNull (2026-11-22): of 25 ISBNs on lines of two languages all 25 belonged to one of them -- the group's.
B. One ISBN on several volumes of a line stays on the lowest-numbered volume and is held on the others
   (`duplicate-of:<number>`): 7 of TypNull's 7 examples and the copy-paste-down shape of the sources.
C. A day-precision date that is earlier than both its dated neighbours while its plus-one-year value falls back
   between them is a year typo and is held (`date_held` = `year-typo:<value>`; the row's date and precision are
   nulled). Every other pair where a later volume is dated before the earlier one is only REPORTED
   (`unresolved`): a reissue or an out-of-order release is real.

Reports: <build-dir>/isbn-held.tsv, <build-dir>/date-order.tsv. Idempotent: a held row is null and is not held
again; the claims carry the reason for the next build's reader.
"""
import datetime, os, re, sqlite3, sys

NOW = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
# registration group -> market, longest prefix first
GROUP_MARKET = [("97910", "FR"), ("97911", "KR"), ("97889", "KR"), ("9784", "JP"), ("9780", "EN"), ("9781", "EN"),
                ("9798", "EN"), ("9782", "FR"), ("9783", "DE"), ("9787", "CN")]
# the markets the rule can judge: a line of another market (IT, ES, ...) is never held
JUDGED = {"JP", "EN", "FR", "DE", "KR", "CN"}


def isbn_market(isbn13):
    """The market an ISBN-13's registration group belongs to, None for an unknown group or a malformed value."""
    s = re.sub(r"[- ]", "", isbn13 or "")
    if len(s) != 13 or not s.isdigit():
        return None
    for prefix, market in GROUP_MARKET:
        if s.startswith(prefix):
            return market
    return None


def _num(n):
    try:
        return (0, float(n))
    except (TypeError, ValueError):
        return (1, str(n))


def _claim(c, vid, field, value):
    c.execute("""INSERT OR REPLACE INTO claim(entity,entity_id,field,value,source,source_url,licence,retrieved_at,via)
                 VALUES('volume',?,?,?,'opentome',NULL,'open',?,'')""", (vid, field, value, NOW))


def _plus_year(d):
    y, rest = d[:4], d[4:]
    return str(int(y) + 1) + rest


def run(db, build_dir=None, verbose=True):
    c = db.cursor()
    rep = {"isbn market": 0, "isbn duplicate in line": 0, "date year typo": 0, "date out of order (reported)": 0}
    isbn_rows, date_rows = [], []

    # --- A. registration group vs the line's market
    for vid, rid, num, isbn, market in c.execute("""SELECT v.id, rl.id, v.number, v.isbn13, rl.market FROM volume v
            JOIN release_line rl ON rl.id=v.release_line_id WHERE v.isbn13 IS NOT NULL""").fetchall():
        if market not in JUDGED:
            continue
        group = isbn_market(isbn)
        if group and group != market:
            c.execute("UPDATE volume SET isbn13=NULL WHERE id=?", (vid,))
            _claim(c, vid, "isbn_held", "market:" + group)
            isbn_rows.append((vid, rid, num, isbn, "market:" + group))
            rep["isbn market"] += 1

    # --- B. one ISBN on several volumes of a line: the lowest number keeps it
    for rid, isbn in c.execute("""SELECT release_line_id, isbn13 FROM volume WHERE isbn13 IS NOT NULL
                                  GROUP BY release_line_id, isbn13 HAVING COUNT(*) > 1""").fetchall():
        vols = c.execute("SELECT id, number FROM volume WHERE release_line_id=? AND isbn13=?", (rid, isbn)).fetchall()
        vols.sort(key=lambda r: _num(r[1]))
        keep = vols[0]
        for vid, num in vols[1:]:
            c.execute("UPDATE volume SET isbn13=NULL WHERE id=?", (vid,))
            _claim(c, vid, "isbn_held", "duplicate-of:" + str(keep[1]))
            isbn_rows.append((vid, rid, num, isbn, "duplicate-of:" + str(keep[1])))
            rep["isbn duplicate in line"] += 1

    # --- C. a year typo between its neighbours; every other out-of-order pair reported
    for (rid,) in c.execute("SELECT DISTINCT release_line_id FROM volume WHERE release_date_precision='day'").fetchall():
        vols = c.execute("""SELECT id, number, release_date FROM volume WHERE release_line_id=? AND release_date IS NOT NULL
                            AND release_date_precision='day' AND LENGTH(release_date)=10""", (rid,)).fetchall()
        vols.sort(key=lambda r: _num(r[1]))
        prev = vols[0][2] if vols else None
        for i in range(1, len(vols)):
            vid, num, d = vols[i]
            if d >= prev:
                prev = d
                continue
            nxt = vols[i + 1][2] if i + 1 < len(vols) else None
            fixed = _plus_year(d)
            if nxt is not None and prev <= nxt and prev <= fixed <= nxt:
                c.execute("UPDATE volume SET release_date=NULL, release_date_precision=NULL WHERE id=?", (vid,))
                _claim(c, vid, "date_held", "year-typo:" + d)
                date_rows.append((vid, rid, num, d, prev, nxt, "year-typo"))
                rep["date year typo"] += 1
                continue                                 # a held row leaves the chain: the next row reads the last kept date
            date_rows.append((vid, rid, num, d, prev, nxt or "", "unresolved"))
            rep["date out of order (reported)"] += 1
            prev = d
    db.commit()

    if build_dir:
        os.makedirs(build_dir, exist_ok=True)
        with open(os.path.join(build_dir, "isbn-held.tsv"), "w", encoding="utf-8") as f:
            f.write("volume\tline\tnumber\tisbn13\treason\n")
            for row in isbn_rows:
                f.write("\t".join(str(x) for x in row) + "\n")
        with open(os.path.join(build_dir, "date-order.tsv"), "w", encoding="utf-8") as f:
            f.write("volume\tline\tnumber\tdate\tprevious\tnext\tverdict\n")
            for row in date_rows:
                f.write("\t".join(str(x) for x in row) + "\n")
    if verbose:
        for k, v in rep.items():
            print("  %-36s %8s" % (k, format(v, ",")))
    return rep


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "opentome.db")
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(path))
    run(sqlite3.connect(path, timeout=60), out)
