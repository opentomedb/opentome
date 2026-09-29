"""Unit tests for tier0/comic_medium.py (stage 4b2: the comic medium of a Korean / Chinese work).
Run: python3 tier0/test_comic_medium.py

No network, no build/: every catalogue is built from schema/schema.sql with schema/load.py (ids hash
exactly as in a real build), exported with export/to_mangarr.py into a carried artifact where a test
needs one, retagged, redirected (stage 7b) and checked with export/test_artifact.py's run_ids.
"""
import os, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for d in (HERE, os.path.join(ROOT, "schema"), os.path.join(ROOT, "export"), os.path.join(ROOT, "tier2")):
    sys.path.insert(0, d)
import comic_medium as CM
import carried_ids as K
import corrections as corr
from load import load, _id
from to_mangarr import export
import test_artifact as TA

FAILS = []
os.environ.pop("OPENTOME_COLD_START", None)      # the export reads it; a CI cold-start run must not skew these
TMP = tempfile.mkdtemp(prefix="opentome-comic-")
corr.DIR = tempfile.mkdtemp(prefix="opentome-nocorr-")          # no corrections in play


def eq(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok:
        FAILS.append(label)


def catalogue(name, works):
    """works: [(work_key, title, [(market, medium, line, [(number, isbn, date)])])] -> db path."""
    path = os.path.join(TMP, name + ".db")
    db = sqlite3.connect(path)
    db.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
    for key, title, lines in works:
        recs = [{"volume": n, "line": line, "medium": med,
                 "markets": {"original": {"market": market, "isbn13": isbn, "date": date,
                                          "date_precision": "day" if date else None}}}
                for market, med, line, vols in lines for n, isbn, date in vols]
        load(db, title, recs, work_key=key)
    db.commit()
    db.close()
    return path


def artifact(db_path, carry=None):
    out = db_path.replace(".db", ".sqlite")
    export(db_path, out, carry)
    return out


def rl(key, market, line, medium="manga"):
    return _id("rl_", _id("w_", key), medium, market, line)


def vols(prefix, n, first=1):
    return [(str(i), "97840%08d" % (prefix * 1000 + i), "2010-01-%02d" % i) for i in range(first, first + n)]


def medium_of(db, rid):
    row = db.execute("SELECT medium FROM release_line WHERE id=?", (rid,)).fetchone()
    return row[0] if row else None


# ---- which lines flip: the origin market decides (spec §3.2) ------------------------------------
cat = catalogue("origins", [
    ("en:Baptist", "Baptist", [("KR", "manga", "Baptist", vols(1, 3)), ("FR", "manga", "Baptist", vols(2, 3))]),
    ("en:Biao", "Biao Ren", [("CN", "manga", "Biao Ren", vols(3, 2))]),
    ("en:Pili", "Pili", [("TW", "manga", "Pili", vols(4, 2))]),
    ("en:Hinted", "Hinted", [("KR", "manhwa", "Hinted", vols(5, 2)), ("EN", "manhwa", "Hinted", vols(6, 2))]),
    ("en:Isekai", "Isekai", [("JP", "light_novel", "Isekai", vols(7, 2)), ("KR", "manhwa", "Isekai", vols(8, 2)),
                             ("DE", "manga", "Isekai", vols(9, 2))]),
    ("en:Naruto", "Naruto", [("JP", "manga", "Naruto", vols(10, 2)), ("KR", "manga", "Naruto", vols(11, 2))]),
    ("en:Omniscient", "Omniscient", [("KR", "novel", "Omniscient", vols(12, 2)),
                                     ("KR", "manga", "Omniscient (Webtoon)", vols(13, 2))]),
    ("en:Radiant", "Radiant", [("FR", "manga", "Radiant", vols(14, 2))])])
db = sqlite3.connect(cat)
rep = CM.apply(db)
eq("origins: exactly the 'manga' lines of KR / CN / TW works flip (KR -> manhwa, CN / TW -> manhua)",
   rep["flips"], sorted([(rl("en:Baptist", "KR", "Baptist"), "manhwa"), (rl("en:Baptist", "FR", "Baptist"), "manhwa"),
                         (rl("en:Biao", "CN", "Biao Ren"), "manhua"), (rl("en:Pili", "TW", "Pili"), "manhua"),
                         (rl("en:Omniscient", "KR", "Omniscient (Webtoon)"), "manhwa")]))
eq("origins: the line keeps its id (retagged in place)", medium_of(db, rl("en:Baptist", "FR", "Baptist")), "manhwa")
eq("origins: a line that already carries its medium hint keeps it", medium_of(db, rl("en:Hinted", "EN", "Hinted", "manhwa")), "manhwa")
eq("origins: a JP-origin work (Japanese light novel, Korean manhwa adaptation) is unchanged",
   medium_of(db, rl("en:Isekai", "DE", "Isekai")), "manga")
eq("origins: a work whose JP manga line is its origin keeps its ko 'manga' line (pick_origin: JP, not guarded)",
   medium_of(db, rl("en:Naruto", "KR", "Naruto")), "manga")
eq("origins: a novel line is never touched", medium_of(db, rl("en:Omniscient", "KR", "Omniscient", "novel")), "novel")
eq("origins: no origin market at all (a French-only comic): unchanged", medium_of(db, rl("en:Radiant", "FR", "Radiant")), "manga")
eq("origins: nothing folded here", (rep["merges"], rep["kept"], rep["differ"]), ([], [], []))
eq("origins: the JP-origin work's line is listed as guarded, for review",
   rep["guarded"], [(rl("en:Isekai", "DE", "Isekai"), "manhwa")])
eq("a second run changes nothing (idempotent)", CM.apply(db),
   {"flips": [], "merges": [], "kept": [], "differ": [], "guarded": [(rl("en:Isekai", "DE", "Isekai"), "manhwa")],
    "pins": []})
db.close()

# ---- the Recast shape: the flip makes two ko lines one; the duplicate folds and 7b redirects it ----
RC = "en:Recast (manhwa)"
rv = vols(20, 6)
works = [(RC, "Recast", [("KR", "manhwa", "Recast", rv), ("EN", "manhwa", "Recast", vols(21, 6)),
                         ("KR", "manga", "Recast", rv), ("FR", "manga", "Recast", vols(22, 6))])]
carry = artifact(catalogue("recast1", works))
after = catalogue("recast2", works)
db = sqlite3.connect(after)
rep = CM.apply(db)
eq("Recast: the ko 'manga' line folds into the ko 'manhwa' line (every number there: 0 moved, 6 dropped)",
   rep["merges"], [(rl(RC, "KR", "Recast"), rl(RC, "KR", "Recast", "manhwa"), 0, 6)])
eq("Recast: one KR line left", db.execute("SELECT COUNT(*) FROM release_line WHERE market='KR'").fetchone()[0], 1)
eq("Recast: the FR line is manhwa, same id", medium_of(db, rl(RC, "FR", "Recast")), "manhwa")
red = K.redirects(db, carry, excluded=set())
eq("Recast: 7b redirects the folded id to the published survivor (duplicate_merge)",
   db.execute("SELECT new_id, reason FROM id_redirect WHERE old_id=?", (rl(RC, "KR", "Recast"),)).fetchone(),
   (rl(RC, "KR", "Recast", "manhwa"), "duplicate_merge"))
eq("Recast: the folded line's volumes follow by ISBN; no orphan",
   (db.execute("SELECT new_id FROM id_redirect WHERE old_id=?", (_id("v_", rl(RC, "KR", "Recast"), "3"),)).fetchone(),
    red["orphans"]), ((_id("v_", rl(RC, "KR", "Recast", "manhwa"), "3"),), []))
db.close()
art = artifact(after, carry)
TA.FAILS[:] = []
TA.run_ids(art, carry)
eq("Recast: the carried-id gate passes", list(TA.FAILS), [])
A = sqlite3.connect(art)
eq("Recast: the FR series exports as manhwa, the ko manhwa line its origin",
   A.execute("""SELECT s.medium, o.tome_id FROM series s JOIN series o ON o.gcd_series_id=s.orig_series_id
                WHERE s.tome_id=?""", (rl(RC, "FR", "Recast"),)).fetchone(), ("manhwa", rl(RC, "KR", "Recast", "manhwa")))
C = sqlite3.connect(carry)
eq("Recast: the FR line's carried origin was the folded ko line",
   C.execute("""SELECT o.tome_id FROM series s JOIN series o ON o.gcd_series_id=s.orig_series_id
                WHERE s.tome_id=?""", (rl(RC, "FR", "Recast"),)).fetchone(), (rl(RC, "KR", "Recast"),))
eq("Recast: E3 explains that origin change by the folded id's duplicate_merge redirect",
   TA.carried_orig_changes(A, C), [])
C.close()
A.close()

# ---- a library line is never folded away (the 8d reload gates compare its id): King of Hell DE ----
KH = "en:King of Hell"
cat = catalogue("koh", [(KH, "King of Hell", [("KR", "manga", "King of Hell", vols(30, 3)),
                                              ("DE", "manga", "King of Hell", vols(31, 1, first=8)),
                                              ("DE", "manhwa", "King of Hell", vols(32, 3))])])
db = sqlite3.connect(cat)
db.execute("CREATE TABLE dnb_line (key TEXT PRIMARY KEY, rl_id TEXT NOT NULL, role TEXT NOT NULL)")
db.execute("INSERT INTO dnb_line VALUES('dnb:997592818', ?, 'linked')", (rl(KH, "DE", "King of Hell"),))
rep = CM.apply(db)
eq("a DNB line the flip made a duplicate is reported, not folded",
   (rep["merges"], rep["kept"]), ([], [(rl(KH, "DE", "King of Hell"), rl(KH, "DE", "King of Hell", "manhwa"))]))
eq("... it is still retagged in place", medium_of(db, rl(KH, "DE", "King of Hell")), "manhwa")
db.close()
LM = "en:La Mosca"
cat = catalogue("mosca", [(LM, "La Mosca", [("KR", "manga", "La Mosca", vols(40, 2)), ("KR", "manhwa", "La Mosca", vols(40, 2))])])
db = sqlite3.connect(cat)
db.execute("CREATE TABLE krcn_line (key TEXT PRIMARY KEY, rl_id TEXT, target TEXT)")
db.execute("INSERT INTO krcn_line VALUES('bnf:ark:/12148/x', NULL, ?)", (rl(LM, "KR", "La Mosca"),))
rep = CM.apply(db)
eq("a line a KR/CN library row targets is reported, not folded",
   (rep["merges"], rep["kept"]), ([], [(rl(LM, "KR", "La Mosca"), rl(LM, "KR", "La Mosca", "manhwa"))]))
db.close()

# ---- two editions under one name are not folded: Solo Leveling's ko lines (13 of 15 ISBNs differ) ------
# Both are manhwa "Solo Leveling" after the retag, so the licensed lines that paired with each by name before
# it (DE 'manga' -> the ko 'manga' line, EN 'manhwa' -> the ko 'manhwa' line) get derived origin_line pins.
SL = "en:Solo Leveling"
sl_works = [(SL, "Solo Leveling", [("KR", "manhwa", "Solo Leveling", vols(50, 3)), ("KR", "manga", "Solo Leveling", vols(51, 3)),
                                   ("DE", "manga", "Solo Leveling", vols(52, 3)), ("EN", "manhwa", "Solo Leveling", vols(53, 3))])]
sl_carry = artifact(catalogue("solo1", sl_works))
cat = catalogue("solo2", sl_works)
db = sqlite3.connect(cat)
rep = CM.apply(db)
eq("a pair that disagrees on its numbers' ISBNs is reported (differ), not folded",
   (rep["merges"], rep["differ"]), ([], [(rl(SL, "KR", "Solo Leveling"), rl(SL, "KR", "Solo Leveling", "manhwa"), 3)]))
eq("... both ko lines stay, the 'manga' one retagged",
   sorted(db.execute("SELECT market, medium FROM release_line WHERE market='KR'")), [("KR", "manhwa"), ("KR", "manhwa")])
eq("... each licensed line is pinned to the ko line it paired with before the retag",
   rep["pins"], sorted([(rl(SL, "DE", "Solo Leveling"), rl(SL, "KR", "Solo Leveling")),
                        (rl(SL, "EN", "Solo Leveling", "manhwa"), rl(SL, "KR", "Solo Leveling", "manhwa"))]))
db.close()
sl_art = sqlite3.connect(artifact(cat, sl_carry))
orig = lambda t: sl_art.execute("""SELECT o.tome_id FROM series s JOIN series o ON o.gcd_series_id=s.orig_series_id
                                   WHERE s.tome_id=?""", (t,)).fetchone()
eq("... after export the DE line keeps the ko 'manga' line as its origin", orig(rl(SL, "DE", "Solo Leveling")),
   (rl(SL, "KR", "Solo Leveling"),))
eq("... and the EN line keeps the ko 'manhwa' line", orig(rl(SL, "EN", "Solo Leveling", "manhwa")),
   (rl(SL, "KR", "Solo Leveling", "manhwa"),))
eq("... E3 sees no origin change", TA.carried_orig_changes(sl_art, sqlite3.connect(sl_carry)), [])
sl_art.close()

# ---- a line a corrections/lines.json entry names is never folded away ----------------------------------
CR = "en:Corrected"
cat = catalogue("corr", [(CR, "Corrected", [("KR", "manhwa", "Corrected", vols(60, 2)), ("KR", "manga", "Corrected", vols(60, 2))])])
with open(os.path.join(corr.DIR, "lines.json"), "w", encoding="utf8") as f:
    __import__("json").dump([{"line": rl(CR, "KR", "Corrected"), "medium": "manhwa", "source_url": "https://example.test/c",
                              "checked": "2026-09-29"}], f)
db = sqlite3.connect(cat)
rep = CM.apply(db)
os.remove(os.path.join(corr.DIR, "lines.json"))
eq("a corrected line is reported, not folded",
   (rep["merges"], rep["kept"]), ([], [(rl(CR, "KR", "Corrected"), rl(CR, "KR", "Corrected", "manhwa"))]))
db.close()

# ---- meta.comic_medium survives a re-run (KEEP_DB=1 past 4b2): the report is merged, not replaced ----------
cat = catalogue("meta", [("en:Baptist2", "Baptist2", [("KR", "manga", "Baptist2", vols(70, 3)), ("FR", "manga", "Baptist2", vols(71, 3))]),
                         ("en:Isekai2", "Isekai2", [("JP", "light_novel", "Isekai2", vols(72, 2)), ("KR", "manhwa", "Isekai2", vols(73, 2)),
                                                    ("DE", "manga", "Isekai2", vols(74, 2))])])
db = sqlite3.connect(cat)
first = CM.apply(db)
stored1 = __import__("json").loads(db.execute("SELECT value FROM meta WHERE key='comic_medium'").fetchone()[0])
second = CM.apply(db)
stored2 = __import__("json").loads(db.execute("SELECT value FROM meta WHERE key='comic_medium'").fetchone()[0])
eq("re-run: the first run flipped something", len(first["flips"]) > 0, True)
eq("re-run: the second run itself finds nothing to flip", second["flips"], [])
eq("re-run: the stored report still holds the first run's flips", stored2["flips"], stored1["flips"])
eq("re-run: ... and every other list of the first run", {k: stored2[k] for k in stored1}, stored1)
db.close()

# ---- E1 (export/test_artifact.py carried_regressions): a line 4b2 retagged into a group with a larger main
# line loses is_main and the work aliases there with no redirect to explain it -- King of Hell DE, ORV EN.
# meta.comic_medium's flips explain it; any other carried line still fails the rule.
KE = "en:King of Hell E1"
e1_works = [(KE, "King of Hell", [("KR", "manga", "King of Hell", vols(70, 3)),
                                  ("DE", "manga", "King of Hell", vols(71, 1, first=8)),
                                  ("DE", "manhwa", "King of Hell", vols(72, 3))])]
e1_carry = artifact(catalogue("e1a", e1_works))
e1_after = catalogue("e1b", e1_works)
db = sqlite3.connect(e1_after)
db.execute("CREATE TABLE dnb_line (key TEXT PRIMARY KEY, rl_id TEXT NOT NULL, role TEXT NOT NULL)")
db.execute("INSERT INTO dnb_line VALUES('dnb:997592818', ?, 'linked')", (rl(KE, "DE", "King of Hell"),))
rep = CM.apply(db)
db.close()
e1_art = artifact(e1_after, e1_carry)
A, C = sqlite3.connect(e1_art), sqlite3.connect(e1_carry)
lost = TA.carried_regressions(A, C)
eq("E1: without the retag list, the retagged DE line's lost is_main is a regression",
   (rl(KE, "DE", "King of Hell"), "is_main lost", "") in lost, True)
eq("E1: meta.comic_medium's flips explain it", TA.carried_regressions(A, C, retagged=TA.retagged_lines(sqlite3.connect(e1_after))), [])
eq("E1: retagged_lines reads exactly the flips", TA.retagged_lines(sqlite3.connect(e1_after)), {r for r, _ in rep["flips"]})
A.close()
C.close()

# ORV's physical EN line (rl_273f63e59345): tagged 'manga', the only EN manga line (main there); retagged
# manhwa, it joins the EN manhwa group whose 13-volume line is main
OR = "en:Omniscient Reader's Viewpoint E1"
orv_works = [(OR, "Omniscient Reader's Viewpoint", [
    ("KR", "manhwa", "Omniscient Reader's Viewpoint", vols(80, 13)),
    ("EN", "manhwa", "Omniscient Reader's Viewpoint", vols(81, 13)),
    ("EN", "manga", "Omniscient Reader's Viewpoint (Physical publication)", vols(82, 5))])]
orv_carry = artifact(catalogue("orv1", orv_works))
orv_after = catalogue("orv2", orv_works)
db = sqlite3.connect(orv_after)
CM.apply(db)
db.close()
A, C = sqlite3.connect(artifact(orv_after, orv_carry)), sqlite3.connect(orv_carry)
orv_line = rl(OR, "EN", "Omniscient Reader's Viewpoint (Physical publication)")
eq("E1: ORV's physical EN line, retagged, loses is_main -- a regression without the retag list",
   (orv_line, "is_main lost", "") in TA.carried_regressions(A, C), True)
eq("E1: ... explained by meta.comic_medium's flips",
   TA.carried_regressions(A, C, retagged=TA.retagged_lines(sqlite3.connect(orv_after))), [])
A.close()
C.close()

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("all comic medium tests passed")
