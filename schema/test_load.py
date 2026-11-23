#!/usr/bin/env python3
"""schema/load.py: one claim per article, the publisher URL's ISBN. Run: python3 schema/test_load.py"""
import os, sqlite3, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import load as L

FAILS = []
def eq(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok: FAILS.append(label)

def fresh():
    db = sqlite3.connect(":memory:")
    db.executescript(open(os.path.join(HERE, "schema.sql")).read())
    return db

def rec(wiki, article, volume, date, isbn, date_source=None, market="JP", role="original"):
    m = {"date": date, "date_precision": "day", "isbn13": isbn, "market": market}
    if date_source: m["date_source"] = date_source
    return {"article": article, "wiki": wiki, "volume": volume, "markets": {role: m}}

# --- R1: two articles, one volume -> two claims, keyed by the article's wiki ---------------------------
db = fresh()
L.load(db, "Sample Saga", [rec("en", "List of Sample Saga chapters", "12", "2010-01-18", "9784091227713")])
L.load(db, "Sample Saga", [rec("fr", "Liste des chapitres de Sample Saga", "12", "2011-01-18", "9784091227713")])
claims = db.execute("""SELECT source, via, value FROM claim WHERE entity='volume' AND field='release_date'
                       ORDER BY via""").fetchall()
eq("two wikipedia date claims, one per article", claims,
   [("wikipedia", "en", "2010-01-18"), ("wikipedia", "fr", "2011-01-18")])
eq("the volume row keeps the first article's value (resolve writes back later)",
   db.execute("SELECT release_date FROM volume").fetchone(), ("2010-01-18",))
eq("the same article loaded twice replaces, never doubles",
   (L.load(db, "Sample Saga", [rec("fr", "Liste des chapitres de Sample Saga", "12", "2011-01-19", "9784091227713")]),
    db.execute("SELECT COUNT(*), MAX(value) FROM claim WHERE entity='volume' AND field='release_date' AND via='fr'").fetchone()),
   ((db.execute("SELECT id FROM work").fetchone()[0], 1, 1, 2), (1, "2011-01-19")))
eq("the line's name stays one claim, the last article's (names do not change with via)",
   db.execute("SELECT via, source_url FROM claim WHERE entity='release_line' AND field='line_name'").fetchall(),
   [("", "Liste des chapitres de Sample Saga")])

# --- R2: the publisher's URL states the ISBN -------------------------------------------------------------
db = fresh()
L.load(db, "Prison Sample", [rec("en", "List of Prison Sample chapters", "4", "2016-07-19", "9780316346122",
                                 date_source="http://www.hachettebookgroup.com/titles/x/prison-sample-vol-4/9780316346153/?yen",
                                 market="EN", role="licensed")])
got = sorted(db.execute("SELECT source, value FROM claim WHERE entity='volume' AND field='isbn13'").fetchall())
eq("publisher claim = the URL's ISBN; the cell stays the wikipedia claim", got,
   [("publisher", "9780316346153"), ("wikipedia", "9780316346122")])
eq("the date claim is attributed to the publisher URL (the URL carries no date)",
   db.execute("SELECT source, value FROM claim WHERE entity='volume' AND field='release_date'").fetchall(),
   [("publisher", "2016-07-19")])
db = fresh()
L.load(db, "Prison Sample", [rec("ja", "監獄サンプル", "26", "2017-08-04", "9784065104255",
                                 date_source="http://kc.kodansha.co.jp/product?isbn=9784065100912")])
eq("kodansha query-string ISBN", sorted(db.execute("SELECT source, value FROM claim WHERE field='isbn13'").fetchall()),
   [("publisher", "9784065100912"), ("wikipedia", "9784065104255")])
db = fresh()
L.load(db, "Prison Sample", [rec("ja", "監獄サンプル", "27", "2017-11-06", "9784065104255",
                                 date_source="http://kc.kodansha.co.jp/product?isbn=9784065104255")])
eq("URL and cell agree: one publisher claim, no wikipedia double",
   db.execute("SELECT source, value FROM claim WHERE field='isbn13'").fetchall(), [("publisher", "9784065104255")])
db = fresh()
L.load(db, "Prison Sample", [rec("ja", "監獄サンプル", "1", "2011-02-04", "9784063844054",
                                 date_source="https://kc.kodansha.co.jp/product?item=0000016776")])
eq("no ISBN in the URL: the cell's ISBN is the publisher claim, as before",
   db.execute("SELECT source, value FROM claim WHERE field='isbn13'").fetchall(), [("publisher", "9784063844054")])
eq("url_isbn: hyphenated shueisha", L.url_isbn("http://books.shueisha.co.jp/items/contents.html?isbn=978-4-08-880566-5"), "9784088805665")
eq("url_isbn: a bad check digit is ignored", L.url_isbn("https://yenpress.com/9781975372584/x"), None)
eq("url_isbn: no ISBN", L.url_isbn("https://kc.kodansha.co.jp/product?item=0000016776"), None)

print("\n%d failure(s)" % len(FAILS)); sys.exit(1 if FAILS else 0)
