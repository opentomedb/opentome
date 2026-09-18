"""Data-quality audit. Finds problems; fixes nothing.

Every check answers "would an integrator notice this and lose trust?"
"""
import re, sqlite3, sys, collections
from datetime import date

import os


def _build(name):
    """Default build-output path. Never /tmp: macOS cleaned it and destroyed a
    fully-built catalogue. Outputs belong beside the cache, inside the repo."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(root, "build")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


def run(path):
    db = sqlite3.connect(path, timeout=60)
    g = lambda q, *a: db.execute(q, a).fetchone()[0]
    out = []

    def check(name, n, detail="", kind="defect"):
        """kind: defect (must reach 0) | expected (correct by design) |
        honest (an absence we refuse to fake) | info (context, not a verdict)"""
        out.append((name, n, detail, kind))
        mark = {"defect": "" if n == 0 else "  <-- DEFECT: ",
                "expected": "  <-- expected: ",
                "honest": "  <-- by design: ",
                "info": "  <-- info: "}[kind]
        print("  %-44s %8s%s%s" % (name, format(n, ","),
                                   mark if n else "", detail if n else ""))

    print("=== STRUCTURE ===")
    check("release lines with 0 volumes",
          g("""SELECT COUNT(*) FROM release_line rl WHERE NOT EXISTS
               (SELECT 1 FROM volume v WHERE v.release_line_id=rl.id)"""))
    check("works with 0 release lines",
          g("""SELECT COUNT(*) FROM work w WHERE NOT EXISTS
               (SELECT 1 FROM release_line rl WHERE rl.work_id=w.id)"""))
    check("volumes with no date AND no ISBN",
          g("SELECT COUNT(*) FROM volume WHERE release_date IS NULL AND isbn13 IS NULL"),
          "genuinely absent upstream", "info")
    check("release lines with exactly 1 volume",
          g("""SELECT COUNT(*) FROM (SELECT rl.id FROM release_line rl
               JOIN volume v ON v.release_line_id=rl.id
               GROUP BY rl.id HAVING COUNT(*)=1)"""),
          "some real one-shots, some parse artefacts -- unseparated", "info")

    print("\n=== TITLES ===")
    check("work titles that are empty/whitespace",
          g("SELECT COUNT(*) FROM work WHERE TRIM(COALESCE(primary_title,''))=''"))
    check("work titles containing wiki markup",
          g("""SELECT COUNT(*) FROM work WHERE primary_title LIKE '%[[%'
               OR primary_title LIKE '%{{%' OR primary_title LIKE '%<%'"""))
    check("work titles starting 'List of'",
          g("SELECT COUNT(*) FROM work WHERE primary_title LIKE 'List of %'"),
          "work_title() failed to strip")
    check("work titles starting 'Liste des'",
          g("SELECT COUNT(*) FROM work WHERE primary_title LIKE 'Liste des %'"))
    dupes = db.execute("""SELECT LOWER(TRIM(primary_title)) t, COUNT(*) c FROM work
                          GROUP BY t HAVING c>1""").fetchall()
    check("duplicate work titles (case-insensitive)", len(dupes),
          "same work ingested twice" if dupes else "")

    print("\n=== DATES ===")
    check("dates in the future (> today+2y)",
          g("SELECT COUNT(*) FROM volume WHERE release_date > ?",
            str(date.today().replace(year=date.today().year + 2))))
    check("dates before 1950",
          g("SELECT COUNT(*) FROM volume WHERE release_date < '1950' AND release_date IS NOT NULL"))
    check("Jan-1 dates (year-only tell)",
          g("SELECT COUNT(*) FROM volume WHERE release_date LIKE '%-01-01'"),
          "fake day precision")
    check("precision=day but value not 10 chars",
          g("""SELECT COUNT(*) FROM volume WHERE release_date_precision='day'
               AND LENGTH(release_date)<>10"""))
    check("release_date_type 'unknown'",
          g("SELECT COUNT(*) FROM volume WHERE release_date_type='unknown'"),
          "only openBD states its milestone; labelling the rest would invent precision",
          "honest")

    print("\n=== ISBN ===")
    check("isbn13 not 13 digits",
          g("""SELECT COUNT(*) FROM volume WHERE isbn13 IS NOT NULL
               AND LENGTH(REPLACE(REPLACE(isbn13,'-',''),' ',''))<>13"""))
    dup = db.execute("""SELECT isbn13, COUNT(DISTINCT release_line_id) c FROM volume
                        WHERE isbn13 IS NOT NULL GROUP BY isbn13 HAVING c>1""").fetchall()
    check("same ISBN across >1 release line", len(dup),
          "dominated by upstream Wikipedia errors; flagged via isbn_collision claims",
          "info")

    print("\n=== VOLUME NUMBERING ===")
    check("duplicate volume numbers within a line",
          g("""SELECT COUNT(*) FROM (SELECT release_line_id, number FROM volume
               GROUP BY release_line_id, number HAVING COUNT(*)>1)"""))
    # '01' and '1' are the same volume; TEXT equality could not see 576 of them
    check("duplicate volume numbers within a line (int-equal)",
          g("""SELECT COUNT(*) FROM (SELECT release_line_id, CAST(number AS INTEGER) n
               FROM volume WHERE number GLOB '[0-9]*' AND number NOT GLOB '*[^0-9]*'
               GROUP BY release_line_id, n HAVING COUNT(*)>1)"""))
    check("placeholder volume labels ('-', '—', 'ー')",
          g("""SELECT COUNT(*) FROM volume WHERE number IN ('-','–','—','ー','?','')"""))
    check("non-numeric volume labels",
          g("""SELECT COUNT(*) FROM volume WHERE number NOT GLOB '[0-9]*'"""),
          "SP / Ex / Side Story -- real special editions the parser deliberately keeps",
          "expected")

    print("\n=== MARKET CONSISTENCY ===")
    # A line's market must agree with the registration group of its ISBNs.
    # 978-4 = JP, 978-0/1 + 979-8 = EN, 978-2 + 979-10 = FR, 978-3 = DE.
    grp = {"JP": "(isbn13 LIKE '9784%')",
           "EN": "(isbn13 LIKE '9780%' OR isbn13 LIKE '9781%' OR isbn13 LIKE '9798%')",
           "FR": "(isbn13 LIKE '9782%' OR isbn13 LIKE '97910%')",
           "DE": "(isbn13 LIKE '9783%')",
           "KR": "(isbn13 LIKE '97889%' OR isbn13 LIKE '97911%')"}
    for mkt, cond in grp.items():
        n = g(f"""SELECT COUNT(*) FROM release_line rl WHERE rl.market=?
                  AND (SELECT COUNT(*) FROM volume v WHERE v.release_line_id=rl.id
                       AND v.isbn13 IS NOT NULL) >= 3
                  AND NOT EXISTS (SELECT 1 FROM volume v WHERE v.release_line_id=rl.id
                       AND v.isbn13 IS NOT NULL AND {cond})""", mkt)
        check(f"{mkt} lines (3+ ISBNs) with no {mkt}-group ISBN", n,
              "editor put the wrong edition's ISBN in the slot -- upstream", "info")
    check("EN/FR/DE lines with 0 dated AND 0 ISBN volumes",
          g("""SELECT COUNT(*) FROM release_line rl WHERE rl.market IN ('EN','FR','DE')
               AND NOT EXISTS (SELECT 1 FROM volume v WHERE v.release_line_id=rl.id
                   AND (v.release_date IS NOT NULL OR v.isbn13 IS NOT NULL))"""),
          "phantom licensed lines: a market entry with no data")
    check("licensed (non-JP) volumes with no date AND no ISBN",
          g("""SELECT COUNT(*) FROM volume v JOIN release_line rl ON rl.id=v.release_line_id
               WHERE rl.market<>'JP' AND v.release_date IS NULL AND v.isbn13 IS NULL"""),
          "a licensed edition nobody has data for is not a volume")
    # The omnibus signature the collapse acts on: consecutive integer rows,
    # same ISBN, same (or no) date. Anything left with that shape is a bug.
    check("collapsible omnibus rows left in a non-JP line",
          g("""SELECT COUNT(*) FROM volume a
               JOIN volume b ON b.release_line_id=a.release_line_id AND b.isbn13=a.isbn13
                 AND COALESCE(b.release_date,'')=COALESCE(a.release_date,'')
                 AND a.number GLOB '[0-9]*' AND a.number NOT GLOB '*[^0-9]*'
                 AND b.number GLOB '[0-9]*' AND b.number NOT GLOB '*[^0-9]*'
                 AND CAST(b.number AS INTEGER)=CAST(a.number AS INTEGER)+1
               JOIN release_line rl ON rl.id=a.release_line_id
               WHERE rl.market<>'JP' AND a.isbn13 IS NOT NULL"""))
    # What remains is one ISBN on rows with DIFFERENT dates or non-adjacent
    # numbers: comics trade paperbacks listed per issue, copy-paste errors
    # upstream (Togari 3=2007 / 4=2001). Merging those would invent volumes.
    check("same ISBN on rows of a non-JP line (different dates / gaps)",
          g("""SELECT COUNT(*) FROM (SELECT v.release_line_id, v.isbn13 FROM volume v
               JOIN release_line rl ON rl.id=v.release_line_id
               WHERE rl.market<>'JP' AND v.isbn13 IS NOT NULL
               GROUP BY 1,2 HAVING COUNT(*)>1)"""),
          "upstream errors / per-issue rows; not collapsible without inventing data", "info")
    check("same ISBN repeated within a JP line",
          g("""SELECT COUNT(*) FROM (SELECT v.release_line_id, v.isbn13 FROM volume v
               JOIN release_line rl ON rl.id=v.release_line_id
               WHERE rl.market='JP' AND v.isbn13 IS NOT NULL
               GROUP BY 1,2 HAVING COUNT(*)>1)"""),
          "ISBN mis-attribution upstream (different dates) -- flagged, not merged", "info")

    # Arc restarts: rows in ONE line whose titles switch stem and restart at 1
    # for 2+ rows are a follow-up series Wikipedia numbered continuously
    # (SAO Progressive 8-14). tier0/release_lines.split_arcs separates them.
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tier0"))
    from release_lines import _stem, _norm
    unsplit = 0
    for (rlid,) in db.execute("SELECT DISTINCT release_line_id FROM volume WHERE title IS NOT NULL"):
        stems = [_stem(t) for (t,) in db.execute(
            "SELECT title FROM volume WHERE release_line_id=? ORDER BY rowid", (rlid,))]
        base = next((st for st, n in stems if st), None)
        if not base:
            continue
        for i in range(len(stems) - 1):
            st, n = stems[i]
            if st and _norm(st) != _norm(base) and n == 1 and stems[i + 1][0] \
                    and _norm(stems[i + 1][0]) == _norm(st) and stems[i + 1][1] == 2:
                unsplit += 1
                break
    check("lines with an un-split arc (title stem restarts at 1)", unsplit)

    print("\n=== CLAIMS ===")
    check("claim dates with month > 12",
          g("""SELECT COUNT(*) FROM claim WHERE field LIKE '%date'
               AND (SUBSTR(value,6,2) GLOB '[2-9][0-9]' OR SUBSTR(value,6,2) GLOB '1[3-9]')"""))
    lic_mismatch = 0
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "schema"))
        from load import LICENCE
        for src, lic in LICENCE.items():
            lic_mismatch += g("SELECT COUNT(*) FROM claim WHERE source=? AND licence<>?", src, lic)
    except ImportError:
        pass
    check("claims whose licence disagrees with LICENCE[source]", lic_mismatch,
          "noncommercial data leaking into clean_claim")
    check("line names containing wiki markup",
          g("""SELECT COUNT(*) FROM claim WHERE entity='release_line' AND field='line_name'
               AND (value LIKE '%{{%' OR value LIKE '%<%' OR value LIKE '%[[%')"""))

    print("\n=== PAGES ===")
    check("page_count <= 0 or > 2000",
          g("SELECT COUNT(*) FROM volume WHERE page_count IS NOT NULL AND (page_count<=0 OR page_count>2000)"))

    print("\n=== UNRESOLVED ===")
    for b in ("conflict", "escalated"):
        check("resolution basis = " + b,
              g("SELECT COUNT(*) FROM resolution WHERE basis=?", b),
              "surfaced through confidence, not silently resolved", "info")

    print("\n=== VERDICT ===")
    defects = sum(n for _, n, _, k in out if k == "defect")
    print("  outstanding DEFECTS: %s" % format(defects, ","))
    if defects == 0:
        print("  (everything else is expected, honest, or informational)")
    return out, defects

if __name__ == "__main__":
    _, defects = run(sys.argv[1] if len(sys.argv) > 1 else _build("opentome.db"))
    # A gate that cannot fail is not a gate: the audit used to print "0
    # defects" and exit 0 regardless, so rebuild_all.sh never noticed.
    sys.exit(1 if defects else 0)
