"""Post-extraction cleanup. Every rule here refuses to invent precision.

Run AFTER a corpus build and enrichment, BEFORE resolve.
"""
import datetime, re, sqlite3, sys
from datetime import date, timedelta

import os


def _build(name):
    """Default build-output path. Never /tmp: macOS cleaned it and destroyed a
    fully-built catalogue. Outputs belong beside the cache, inside the repo."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(root, "build")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


NOW = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def clean(db, verbose=True):
    c = db.cursor()
    rep = {}

    # --- 1. release_date_type: label ONLY where the source semantics are explicit.
    # openBD carries ONIX PublishingDateRole 11 = "date of first publication", which
    # is a real statement about which milestone the date is. Nothing else in the
    # pipeline says which milestone it recorded, and guessing would recreate exactly
    # the silent-wrongness this field exists to prevent -- so the rest stays 'unknown'.
    n = c.execute("""UPDATE volume SET release_date_type='published'
                     WHERE id IN (SELECT entity_id FROM claim
                                  WHERE source='openbd' AND field='release_date')
                       AND release_date_type='unknown'""").rowcount
    rep["date_type=published (openBD ONIX role 11)"] = n

    # --- 2. Jan-1 is the year-only tell. It is the project's oldest known data
    # artefact: a source with only a year stamps 01-01 and the precision becomes a
    # lie. Downgrade to year rather than delete -- the year is still true.
    n = c.execute("""UPDATE volume
                     SET release_date = SUBSTR(release_date,1,4),
                         release_date_precision='year'
                     WHERE release_date LIKE '%-01-01'
                       AND release_date_precision='day'""").rowcount
    rep["Jan-1 day->year (fake precision)"] = n

    # --- 3. malformed ISBNs: not 13 digits after normalisation. Null the field
    # rather than keep a value that fails its own check digit.
    bad = [r[0] for r in c.execute("SELECT id FROM volume WHERE isbn13 IS NOT NULL")
           if False]
    n = c.execute("""UPDATE volume SET isbn13=NULL
                     WHERE isbn13 IS NOT NULL
                       AND LENGTH(REPLACE(REPLACE(isbn13,'-',''),' ',''))<>13""").rowcount
    rep["malformed isbn13 nulled"] = n

    # --- 4. implausible future dates. A real announced volume can be ~18 months
    # out; beyond 2 years it is a typo or a mis-parse.
    cutoff = str(date.today() + timedelta(days=730))
    n = c.execute("""UPDATE volume SET release_date=NULL, release_date_precision=NULL
                     WHERE release_date > ?""", (cutoff,)).rowcount
    rep["implausible future dates nulled"] = n

    # --- 5. ISBN collisions. An ISBN identifies exactly one physical product, so
    # the same ISBN in two release lines is a defect. After fixing leaked headings,
    # cross-language work identity and title-union, the survivors are dominated by
    # UPSTREAM errors -- 9781421517810 is filed under both "Gimmick!" and "Tower of
    # the Future" in Wikipedia. Better parsing cannot fix wrong source data, so
    # these are FLAGGED, not guessed at: the volumes are recorded as disputed and
    # the confidence layer carries it to consumers.
    c.execute("""INSERT OR REPLACE INTO claim
        (entity,entity_id,field,value,source,source_url,licence,retrieved_at)
        SELECT 'volume', v.id, 'isbn_collision', 'true', 'opentome', NULL, 'open', ?
        FROM volume v WHERE v.isbn13 IN (
            SELECT isbn13 FROM volume WHERE isbn13 IS NOT NULL
            GROUP BY isbn13 HAVING COUNT(DISTINCT release_line_id) > 1)""", (NOW,))
    rep["volumes flagged isbn_collision"] = c.execute(
        "SELECT COUNT(*) FROM claim WHERE field='isbn_collision'").fetchone()[0]

    db.commit()
    if verbose:
        for k, v in rep.items():
            print("  %-44s %8s" % (k, format(v, ",")))
    return rep


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else _build("opentome.db")
    clean(sqlite3.connect(p, timeout=60))
