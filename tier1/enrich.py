"""Write independent-source claims into the catalogue.

Tier-1 previously only *printed* its cross-verification. Nothing persisted, so
the resolver saw one claim per field and every field came back
"single_source" -- the calibration machinery had nothing to calibrate.

This adds a second, genuinely independent opinion per volume so agreement and
disagreement become measurable in the data rather than in a report.
"""
import datetime, json, os, sqlite3, sys, urllib.request, hashlib, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "schema"))
from verify import _fetch, openbd_batch          # cached + throttled
# Licence per source is declared ONCE, in schema/load.py. This file used to
# hardcode 'open' for openBD, which is purpose-limited, and thereby let 58,929
# non-commercial claims into the "commercially clean" view.
from load import LICENCE

import os


def _build(name):
    """Default build-output path. Never /tmp: macOS cleaned it and destroyed a
    fully-built catalogue. Outputs belong beside the cache, inside the repo."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(root, "build")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


NOW = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def enrich_openbd(db, limit=None):
    """JP ISBNs -> openBD publication date (year-month precision)."""
    rows = db.execute("""SELECT v.id, v.isbn13 FROM volume v
                         JOIN release_line rl ON rl.id = v.release_line_id
                         WHERE rl.market='JP' AND v.isbn13 IS NOT NULL
                           AND NOT EXISTS (SELECT 1 FROM claim c
                             WHERE c.entity='volume' AND c.entity_id=v.id
                               AND c.field='release_date' AND c.source='openbd')
                      """).fetchall()
    if limit:
        rows = rows[:limit]
    if not rows:
        return 0, 0
    by_isbn = {}
    for vid, isbn in rows:
        by_isbn.setdefault(isbn, []).append(vid)
    got = openbd_batch(sorted(by_isbn))
    ins = 0
    for isbn, dt in got.items():
        for vid in by_isbn.get(isbn, []):
            db.execute("""INSERT OR REPLACE INTO claim
                (entity,entity_id,field,value,source,source_url,licence,retrieved_at)
                VALUES('volume',?,'release_date',?,'openbd',?,?,?)""",
                (vid, dt, f"https://api.openbd.jp/v1/get?isbn={isbn}",
                 LICENCE["openbd"], NOW))
            ins += 1
    db.commit()
    return len(rows), ins


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else _build("opentome.db")
    db = sqlite3.connect(p)
    n, ins = enrich_openbd(db, int(sys.argv[2]) if len(sys.argv) > 2 else None)
    print(f"openBD: {n} JP volumes queried -> {ins} claims written")
    print("sources now in claim table:")
    for s, c in db.execute("SELECT source, COUNT(*) FROM claim GROUP BY source ORDER BY 2 DESC"):
        print(f"   {s:<12} {c:>6}")
