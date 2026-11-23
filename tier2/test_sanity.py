#!/usr/bin/env python3
"""tier2/sanity.py (stage 6b, the corrections round 2026-11-23). Run: python3 tier2/test_sanity.py"""
import os, sqlite3, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sanity as S

FAILS = []
def eq(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok: FAILS.append(label)

def fresh():
    db = sqlite3.connect(":memory:")
    db.executescript(open(os.path.join(os.path.dirname(HERE), "schema", "schema.sql")).read())
    db.execute("INSERT INTO work(id,primary_title,created_at,updated_at) VALUES('w','Sample Saga','x','x')")
    return db

def line(db, rid, market, lang):
    db.execute("INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at) VALUES(?,?,'manga',?,?,'x','x')",
               (rid, "w", market, lang))

def vol(db, rid, num, isbn=None, date=None):
    db.execute("INSERT INTO volume(id,release_line_id,number,isbn13,release_date,release_date_precision,release_date_type,created_at,updated_at)"
               " VALUES(?,?,?,?,?,?,?,'x','x')", (f"v_{rid}_{num}", rid, str(num), isbn, date, "day" if date else None, "unknown"))

def held(db, vid, field):
    return [v for (v,) in db.execute("SELECT value FROM claim WHERE entity='volume' AND entity_id=? AND field=?", (vid, field))]

eq("isbn_market: 978-4 is Japan", S.isbn_market("9784065100912"), "JP")
eq("isbn_market: 979-10 is France", S.isbn_market("9791032704073"), "FR")
eq("isbn_market: 979-8 is the United States", S.isbn_market("9798765432109"), "EN")
eq("isbn_market: an unknown group is None", S.isbn_market("9789812345678"), None)
eq("isbn_market: garbage is None", S.isbn_market("12"), None)

# --- A: a foreign registration group on a line --------------------------------------------------------------
db = fresh(); line(db, "rl_fr", "FR", "fr"); line(db, "rl_en", "EN", "en")
vol(db, "rl_fr", 1, "9781421506159"); vol(db, "rl_fr", 2, "9782723449618"); vol(db, "rl_en", 1, "9789812345678"); vol(db, "rl_en", 2, "9781421506159")
out = tempfile.mkdtemp()
rep = S.run(db, out)
eq("A: an English ISBN on a French line is held", db.execute("SELECT isbn13 FROM volume WHERE id='v_rl_fr_1'").fetchone(), (None,))
eq("A: the hold is a claim", held(db, "v_rl_fr_1", "isbn_held"), ["market:EN"])
eq("A: a French ISBN on the French line stays", db.execute("SELECT isbn13 FROM volume WHERE id='v_rl_fr_2'").fetchone(), ("9782723449618",))
eq("A: an unknown group stays", db.execute("SELECT isbn13 FROM volume WHERE id='v_rl_en_1'").fetchone(), ("9789812345678",))
eq("A: the English line keeps its English ISBN", db.execute("SELECT isbn13 FROM volume WHERE id='v_rl_en_2'").fetchone(), ("9781421506159",))
eq("A: counted", rep["isbn market"], 1)
eq("A: reported", any("v_rl_fr_1" in l and "market:EN" in l for l in open(os.path.join(out, "isbn-held.tsv"))), True)

# --- B: one ISBN on two volumes of a line: the lower number keeps it ----------------------------------------
db = fresh(); line(db, "rl", "EN", "en")
vol(db, "rl", 1, "9780316346115"); vol(db, "rl", 2, "9780316346122"); vol(db, "rl", 3, "9780316346139"); vol(db, "rl", 4, "9780316346122")
vol(db, "rl", 10, "9780316346184"); vol(db, "rl", "7.5", "9780316346184")
out = tempfile.mkdtemp(); rep = S.run(db, out)
eq("B: vol 4 loses the ISBN vol 2 carries", db.execute("SELECT isbn13 FROM volume WHERE id='v_rl_4'").fetchone(), (None,))
eq("B: vol 2 keeps it", db.execute("SELECT isbn13 FROM volume WHERE id='v_rl_2'").fetchone(), ("9780316346122",))
eq("B: the hold names the keeper", held(db, "v_rl_4", "isbn_held"), ["duplicate-of:2"])
eq("B: a fractional number sorts by value (7.5 keeps, 10 loses)",
   (db.execute("SELECT isbn13 FROM volume WHERE id='v_rl_7.5'").fetchone(), db.execute("SELECT isbn13 FROM volume WHERE id='v_rl_10'").fetchone()),
   (("9780316346184",), (None,)))
eq("B: counted", rep["isbn duplicate in line"], 2)

# --- C: a year typo between its neighbours ------------------------------------------------------------------
db = fresh(); line(db, "rl", "JP", "ja")
vol(db, "rl", 4, date="2016-12-06"); vol(db, "rl", 5, date="2016-06-06"); vol(db, "rl", 6, date="2017-12-06")
vol(db, "rl", 10, date="2018-06-01"); vol(db, "rl", 11, date="2018-03-01"); vol(db, "rl", 12, date="2018-09-01")   # out of order, not a typo
vol(db, "rl", 20, date="2020-05-01"); vol(db, "rl", 21, date="2020-07-01")                                          # in order
out = tempfile.mkdtemp(); rep = S.run(db, out)
eq("C: the year typo is held", db.execute("SELECT release_date, release_date_precision FROM volume WHERE id='v_rl_5'").fetchone(), (None, None))
eq("C: the hold is a claim", held(db, "v_rl_5", "date_held"), ["year-typo:2016-06-06"])
eq("C: a genuine out-of-order date stays", db.execute("SELECT release_date FROM volume WHERE id='v_rl_11'").fetchone(), ("2018-03-01",))
eq("C: counted", (rep["date year typo"], rep["date out of order (reported)"]), (1, 1))
lines = open(os.path.join(out, "date-order.tsv")).read()
eq("C: both pairs are in the report", ("v_rl_5" in lines and "year-typo" in lines, "v_rl_11" in lines and "unresolved" in lines), (True, True))
eq("C: running again holds nothing more", S.run(db, out)["date year typo"], 0)

print("\n%d failure(s)" % len(FAILS)); sys.exit(1 if FAILS else 0)
