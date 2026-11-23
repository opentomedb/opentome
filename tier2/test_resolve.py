"""Test the calibration rule's branches with synthetic claims.

The rule is the product's differentiator and, on real data so far, only its
'agree' paths have executed. Untested branches in the code that decides what
to trust is exactly the wrong place to have them.
"""
import os, sqlite3, sys, tempfile
from datetime import date
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from resolve import resolve, classify_dates, _compatible, apply_resolved_dates

CASES = [
    # (name, claim values by source, expected basis)
    ("identical",        {"wikipedia": "2020-04-21", "openbd": "2020-04-21"}, "agreed"),
    ("coarser openBD",   {"wikipedia": "2020-04-21", "openbd": "2020-04"},    "agreed_coarse"),
    ("7-day offset",     {"wikipedia": "2020-04-21", "publisher": "2020-04-14"}, "semantic_variance"),
    ("28-day offset",    {"wikipedia": "2020-04-21", "publisher": "2020-03-24"}, "semantic_variance"),
    ("42-day offset",    {"wikipedia": "2023-10-03", "publisher": "2023-08-22"}, "semantic_variance"),
    ("161-day (23wk)",   {"wikipedia": "2021-12-28", "publisher": "2021-07-20"}, "escalated"),
    ("826-day (118wk)",  {"wikipedia": "2018-01-30", "publisher": "2015-10-27"}, "escalated"),
    # sub-week, non-week-multiple: near-agreement of unexplained cause.
    # 46% of French conflicts looked like this -- the week-multiple rule encodes
    # US Tuesday street dates and France has no equivalent weekly grid.
    ("4-day (sub-week)",  {"wikipedia": "2018-08-18", "publisher": "2018-08-14"}, "minor_variance"),
    ("10-day non-week",   {"wikipedia": "2020-04-21", "publisher": "2020-04-11"}, "conflict"),
    ("100-day non-week",  {"wikipedia": "2020-04-21", "publisher": "2020-01-12"}, "conflict"),
    ("single source",    {"wikipedia": "2020-04-21"},                          "single_source"),
]

VALUE_CASES = [
    # DNB ranks above Wikipedia, but its 008 year is the coarsest date there is: a
    # late-December release catalogued under the next year must not beat the day date.
    ("dnb year vs wikipedia day, years differ", {"dnb": "2020", "wikipedia": "2019-12-20"}, "2019-12-20"),
    ("dnb year agrees with wikipedia day",      {"dnb": "2019", "wikipedia": "2019-12-20"}, "2019-12-20"),
    ("dnb year alone",                          {"dnb": "2019"},                            "2019"),
    # the rule is DNB's alone: a Wikipedia year keeps precedence over Open Library
    ("wikipedia year vs openlibrary day",       {"wikipedia": "2005", "openlibrary": "2003-11-14"}, "2005"),
    # krcn-design §12: a bare LoC / BnF year never beats a finer date it disagrees with (DNB's rule)
    ("loc year vs openlibrary day, years differ", {"loc": "2021", "openlibrary": "2020-12-29"}, "2020-12-29"),
    ("bnf year vs openlibrary day, years differ", {"bnf": "2021", "openlibrary": "2020-12-29"}, "2020-12-29"),
]


def run():
    fails = 0
    db = sqlite3.connect(":memory:")
    db.executescript(open(os.path.join(os.path.dirname(HERE), "schema", "schema.sql")).read())
    for i, (name, claims, expect) in enumerate(CASES):
        vid = f"v_test{i:08d}"
        for src, val in claims.items():
            db.execute("""INSERT INTO claim(entity,entity_id,field,value,source,licence,retrieved_at)
                          VALUES('volume',?,'release_date',?,?,'open','2026-01-01')""",
                       (vid, val, src))
    db.commit()
    resolve(db)
    print(f"{'case':<20}{'expected':<20}{'got':<20}{'conf':>6}")
    print("-"*68)
    for i, (name, claims, expect) in enumerate(CASES):
        vid = f"v_test{i:08d}"
        r = db.execute("SELECT basis, confidence FROM resolution WHERE entity_id=?",
                       (vid,)).fetchone()
        got, conf = r if r else ("<none>", 0)
        ok = got == expect
        fails += not ok
        print(f"{name:<20}{expect:<20}{got:<20}{conf:>6.2f}  {'' if ok else '<-- FAIL'}")
    print("-"*68)
    # the VALUE that wins, where precedence and precision disagree
    for name, claims, want in VALUE_CASES:
        vid = "v_val" + name[:20]
        for src, val in claims.items():
            db.execute("""INSERT INTO claim(entity,entity_id,field,value,source,licence,retrieved_at)
                          VALUES('volume',?,'release_date',?,?,'open','2026-01-01')""", (vid, val, src))
    db.commit()
    resolve(db)
    for name, claims, want in VALUE_CASES:
        got = db.execute("SELECT value FROM resolution WHERE entity_id=?", ("v_val" + name[:20],)).fetchone()[0]
        ok = got == want
        fails += not ok
        print(f"{name:<40}{want:<14}{got:<14}  {'' if ok else '<-- FAIL'}")
    # a projected date never outranks a real one (the KR/CN lift, 2026-10-01): a volume created with a projected
    # month takes the resolved real date, even a bare year, with its precision and type 'published'
    PROJ = [("v_projyear", "2025-12", "month", "projected", {"openlibrary": "2025"}, ("2025", "year", "published")),
            ("v_projday", "2025-12", "month", "projected", {"openlibrary": "2025-11-04", "loc": "2025-11-04"},
             ("2025-11-04", "day", "published")),
            ("v_projalone", "2025-12", "month", "projected", {}, ("2025-12", "month", "projected")),
            ("v_pubkeeps", "2024-05", "month", "published", {"openlibrary": "2024"}, ("2024-05", "month", "published"))]
    db.execute("INSERT INTO work(id,primary_title,created_at,updated_at) VALUES('w_p','P','x','x')")
    db.execute("INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at) "
               "VALUES('rl_p','w_p','novel','EN','en','x','x')")
    FUT = str(date.today().year + 1)
    PROJ += [("v_projfuture", FUT + "-03", "month", "projected", {"openlibrary": FUT}, (FUT + "-03", "month", "projected")),
             ("v_projwrongyr", "2025-12", "month", "projected", {"openlibrary": "2019"}, ("2025-12", "month", "projected")),
             ("v_projprev", "2025-12", "month", "projected", {"openlibrary": "2024-11"}, ("2024-11", "month", "published")),
             ("v_projtwo", "2025-12", "month", "projected", {"openlibrary": "2023-11"}, ("2025-12", "month", "projected"))]
    Y = date.today().year
    PROJ += [("v_yrlater", f"{Y + 1}-01", "month", "projected", {"openlibrary": str(Y)}, (f"{Y + 1}-01", "month", "projected")),
             ("v_yrpast", f"{Y}-01", "month", "projected", {"openlibrary": str(Y)}, (str(Y), "year", "published")),
             ("v_junkval", "2025-12", "month", "projected", {"openlibrary": "c.20"}, ("2025-12", "month", "projected")),
             ("v_junk199x", "2025-12", "month", "projected", {"openlibrary": "199x"}, ("2025-12", "month", "projected"))]
    for num, (vid, d, p, t, claims, _) in enumerate(PROJ, 1):
        db.execute("INSERT INTO volume(id,release_line_id,number,release_date,release_date_precision,release_date_type,"
                   "created_at,updated_at) VALUES(?,?,?,?,?,?,'x','x')", (vid, "rl_p", str(num), d, p, t))
        db.execute("""INSERT INTO claim(entity,entity_id,field,value,source,licence,retrieved_at)
                      VALUES('volume',?,'projected_date',?,'loc','open','2026-01-01')""", (vid, d))
        for src, val in claims.items():
            db.execute("""INSERT INTO claim(entity,entity_id,field,value,source,licence,retrieved_at)
                          VALUES('volume',?,'release_date',?,?,'open','2026-01-01')""", (vid, val, src))
    db.commit()
    resolve(db)
    for vid, _, _, _, _, want in PROJ:
        got = db.execute("SELECT release_date, release_date_precision, release_date_type FROM volume WHERE id=?",
                         (vid,)).fetchone()
        ok = got == want
        fails += not ok
        print(f"{'projected ' + vid:<40}{str(want):<40}{str(got):<40}  {'' if ok else '<-- FAIL'}")
    # 7b moves claim / resolution rows between volume ids after resolve ran: apply_resolved_dates converts again
    db.execute("INSERT INTO volume(id,release_line_id,number,release_date,release_date_precision,release_date_type,"
               "created_at,updated_at) VALUES('v_moved','rl_p','99','2025-12','month','projected','x','x')")
    db.execute("""INSERT INTO resolution(entity,entity_id,field,value,confidence,basis,n_agree,n_sources)
                  VALUES('volume','v_moved','release_date','2025-10',0.7,'single_source',1,1)""")
    got1 = apply_resolved_dates(db)
    got2 = apply_resolved_dates(db)
    row = db.execute("SELECT release_date, release_date_precision, release_date_type FROM volume WHERE id='v_moved'").fetchone()
    ok = (got1, got2, row) == (1, 0, ("2025-10", "month", "published"))
    fails += not ok
    print(f"{'moved resolution converts, idempotent':<40}{str((1, 0)):<40}{str((got1, got2, row)):<40}  {'' if ok else '<-- FAIL'}")
    n = len(CASES) + len(VALUE_CASES) + len(PROJ) + 1
    print(f"{n-fails}/{n} passed")
    return fails

# ---- the corrections round (2026-11-23): one claim per article, coarse months, write-back -------------------
ARTICLE_CASES = [
    # (name, field, [(source, via, value)], winning value)
    ("two articles agree, a third differs", "isbn13",
     [("wikipedia", "en", "9784065100912"), ("wikipedia", "fr", "9784065100912"), ("wikipedia", "de", "9784065104255")],
     "9784065100912"),
    ("1:1 between articles: the English article first", "isbn13",
     [("wikipedia", "fr", "9784065104255"), ("wikipedia", "en", "9784065100912")], "9784065100912"),
    ("1:1 between articles: the Japanese article before the French", "isbn13",
     [("wikipedia", "fr", "9784065104255"), ("wikipedia", "ja", "9784065100912")], "9784065100912"),
    ("the publisher page's ISBN beats the cell of the same row", "isbn13",
     [("wikipedia", "en", "9780316346122"), ("publisher", "en", "9780316346153")], "9780316346153"),
    ("two cells agreeing do not outvote a publisher page", "isbn13",
     [("wikipedia", "en", "9784065104255"), ("wikipedia", "fr", "9784065104255"), ("publisher", "en", "9784065100912")],
     "9784065100912"),
    ("a coarse month a year away outranks a lone day", "release_date",
     [("publisher", "en", "2016-06-06"), ("openbd", "", "2017-06")], "2017-06"),
    ("a coarse month four years away outranks a lone day", "release_date",
     [("wikipedia", "en", "2011-11-16"), ("openbd", "", "2007-11")], "2007-11"),
    ("an adjacent month: the day keeps winning", "release_date",
     [("wikipedia", "en", "2017-06-30"), ("openbd", "", "2017-07")], "2017-06-30"),
    ("the month agrees: the day wins as before", "release_date",
     [("wikipedia", "en", "2017-06-06"), ("openbd", "", "2017-06")], "2017-06-06"),
    ("two articles agree on a day against a third", "release_date",
     [("wikipedia", "en", "2010-11-18"), ("wikipedia", "fr", "2010-11-18"), ("wikipedia", "de", "2011-11-18")],
     "2010-11-18"),
    ("two days disagree, the month backs one", "release_date",
     [("wikipedia", "en", "2010-01-18"), ("wikipedia", "fr", "2011-01-18"), ("openbd", "", "2011-01")], "2011-01-18"),
]


def run_round():
    fails = 0
    db = sqlite3.connect(":memory:")
    db.executescript(open(os.path.join(os.path.dirname(HERE), "schema", "schema.sql")).read())
    db.execute("INSERT INTO work(id,primary_title,created_at,updated_at) VALUES('w_r','R','x','x')")
    db.execute("INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at) "
               "VALUES('rl_r','w_r','manga','JP','ja','x','x')")
    for i, (name, field, claims, want) in enumerate(ARTICLE_CASES):
        vid = f"v_round{i:04d}"
        db.execute("INSERT INTO volume(id,release_line_id,number,created_at,updated_at) VALUES(?,?,?,'x','x')", (vid, "rl_r", str(i)))
        for src, via, val in claims:
            db.execute("""INSERT INTO claim(entity,entity_id,field,value,source,licence,retrieved_at,via)
                          VALUES('volume',?,?,?,?,'open','2026-01-01',?)""", (vid, field, val, src, via))
    # write-back: the row carries the first article's value until resolve writes the resolved one
    WB = [("v_wb_date", {"release_date": "2010-01-18", "release_date_precision": "day"},
           [("release_date", "wikipedia", "en", "2011-01-18"), ("release_date", "openbd", "", "2011-01")],
           ("2011-01-18", "day", None)),
          ("v_wb_isbn", {"isbn13": "9784065104255"},
           [("isbn13", "wikipedia", "en", "9784065104255"), ("isbn13", "publisher", "en", "9784065100912")],
           (None, None, "9784065100912")),
          ("v_wb_jan1", {}, [("release_date", "wikipedia", "en", "2015-01-01")], ("2015", "year", None)),
          ("v_wb_month", {}, [("release_date", "openbd", "", "2015-03")], ("2015-03", "month", None)),
          ("v_wb_badisbn", {"isbn13": "9784065104255"}, [("isbn13", "wikipedia", "en", "97812345")], (None, None, "9784065104255"))]
    for num, (vid, row, claims, _) in enumerate(WB, 100):
        cols = ",".join(["id", "release_line_id", "number", "created_at", "updated_at"] + list(row))
        db.execute(f"INSERT INTO volume({cols}) VALUES({','.join('?' * (5 + len(row)))})",
                   [vid, "rl_r", str(num), "x", "x"] + list(row.values()))
        for field, src, via, val in claims:
            db.execute("""INSERT INTO claim(entity,entity_id,field,value,source,licence,retrieved_at,via)
                          VALUES('volume',?,?,?,?,'open','2026-01-01',?)""", (vid, field, val, src, via))
    db.commit()
    resolve(db)
    for i, (name, field, claims, want) in enumerate(ARTICLE_CASES):
        got = db.execute("SELECT value FROM resolution WHERE entity_id=? AND field=?", (f"v_round{i:04d}", field)).fetchone()
        got = got[0] if got else "<none>"
        ok = got == want
        fails += not ok
        print(f"{name:<58}{want:<16}{got:<16}  {'' if ok else '<-- FAIL'}")
    got = db.execute("SELECT basis FROM resolution WHERE entity_id='v_round0005'").fetchone()[0]
    ok = got == "coarse_outranks"
    fails += not ok
    print(f"{'basis of the coarse-month rule':<58}{'coarse_outranks':<16}{got:<16}  {'' if ok else '<-- FAIL'}")
    for vid, _, _, want in WB:
        got = db.execute("SELECT release_date, release_date_precision, isbn13 FROM volume WHERE id=?", (vid,)).fetchone()
        ok = got == want
        fails += not ok
        print(f"{'write-back ' + vid:<58}{str(want):<30}{str(got):<30}  {'' if ok else '<-- FAIL'}")
    n = len(ARTICLE_CASES) + 1 + len(WB)
    print(f"{n-fails}/{n} passed (round)")
    return fails


if __name__ == "__main__":
    sys.exit(1 if (run() + run_round()) else 0)
