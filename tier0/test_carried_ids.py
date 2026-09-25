"""Unit tests for tier0/carried_ids.py (stage 7b redirects). Run: python3 tier0/test_carried_ids.py

No network, no build/: every catalogue is built from schema/schema.sql with schema/load.py (the
loader the corpus stage uses, so ids hash exactly as in a real build), exported with
export/to_mangarr.py into a carried artifact, rebuilt with the change under test, redirected,
exported again against the carry, and checked with export/test_artifact.py's run_ids.
"""
import os, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for d in (HERE, os.path.join(ROOT, "schema"), os.path.join(ROOT, "export"), os.path.join(ROOT, "tier2")):
    sys.path.insert(0, d)
import carried_ids as K
import corrections as corr
from load import load, _id
from to_mangarr import export
import test_artifact as TA

FAILS = []
TMP = tempfile.mkdtemp(prefix="opentome-carried-")
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


def vols(prefix, n, first=1, date=True):
    return [(str(i), "97840%08d" % (prefix * 1000 + i), "2010-01-%02d" % i if date else None)
            for i in range(first, first + n)]


def ids_ok(art, carry):
    TA.FAILS[:] = []
    TA.run_ids(art, carry)
    return list(TA.FAILS)


# ---- a re-key: the line name that feeds the id changed (the Kindaichi shape) ---------------------
K1 = "fr:Liste des chapitres des Enquêtes (1re partie)"
before = catalogue("rekey1", [(K1, "s Enquêtes (1re partie)", [
    ("JP", "manga", "s Enquêtes (1re partie) (FILE)", vols(1, 3)),
    ("FR", "manga", "s Enquêtes (1re partie) (FILE)", vols(2, 2))])])
carry = artifact(before)
after = catalogue("rekey2", [(K1, "Les Enquêtes (1re partie)", [
    ("JP", "manga", "Les Enquêtes (1re partie) (FILE)", vols(1, 3)),
    ("FR", "manga", "Les Enquêtes (1re partie) (FILE)", vols(2, 2))])])
db = sqlite3.connect(after)
rep = K.redirects(db, carry, excluded=set())
old_jp, new_jp = rl(K1, "JP", "s Enquêtes (1re partie) (FILE)"), rl(K1, "JP", "Les Enquêtes (1re partie) (FILE)")
eq("re-key: the old JP line redirects to the re-keyed one (correction)",
   db.execute("SELECT new_id, entity, reason FROM id_redirect WHERE old_id=?", (old_jp,)).fetchone(),
   (new_jp, "release_line", "correction"))
eq("re-key: every volume follows by number",
   db.execute("SELECT new_id FROM id_redirect WHERE old_id=?", (_id("v_", old_jp, "2"),)).fetchone(),
   (_id("v_", new_jp, "2"),))
eq("re-key: 2 lines + 5 volumes, no orphan, the work untouched",
   (dict(rep["rows"]), rep["orphans"]),
   ({("release_line", "correction"): 2, ("volume", "correction"): 5}, []))
art = artifact(after, carry)
A, C = sqlite3.connect(art), sqlite3.connect(carry)
old_int = C.execute("SELECT gcd_series_id FROM series WHERE tome_id=?", (old_jp,)).fetchone()[0]
eq("re-key: the re-keyed line keeps the integer a consumer stored",
   A.execute("SELECT gcd_series_id FROM series WHERE tome_id=?", (new_jp,)).fetchone()[0], old_int)
eq("re-key: the artifact's id_redirect carries the old line id",
   A.execute("SELECT new_tome_id, new_series_id FROM id_redirect WHERE old_tome_id=?", (old_jp,)).fetchone(),
   (new_jp, old_int))
eq("re-key: the carried-id gate passes", ids_ok(art, carry), [])
db.close()

# ---- a rerun redirects nothing new; the carried rows are re-read (chains collapse) -----------------
carry2 = art
again = catalogue("rekey3", [(K1, "Les Enquêtes (1re partie)", [
    ("JP", "manga", "Les Enquêtes (1re partie) (FILE)", vols(1, 3)),
    ("FR", "manga", "Les Enquêtes (1re partie) (FILE)", vols(2, 2))])])
db = sqlite3.connect(again)
rep = K.redirects(db, carry2, excluded=set())
eq("next build: nothing lost, nothing written, the 7 carried rows re-read",
   (sum(rep["rows"].values()), rep["carried_rows"], rep["orphans"]), (0, 7, []))
art3 = artifact(again, carry2)
eq("next build: the redirects are still in the artifact",
   sqlite3.connect(art3).execute("SELECT COUNT(*) FROM id_redirect").fetchone()[0], 7)
eq("next build: the gate passes against the re-keyed carry", ids_ok(art3, carry2), [])
db.close()

# chain: a line of the re-keyed carry is re-keyed again -> the oldest id reaches the newest line
chain = catalogue("rekey4", [(K1, "Les Enquêtes (1re partie)", [
    ("JP", "manga", "Les Enquêtes (1re partie) - FILE", vols(1, 3)),
    ("FR", "manga", "Les Enquêtes (1re partie) (FILE)", vols(2, 2))])])
db = sqlite3.connect(chain)
K.redirects(db, carry2, excluded=set())
art4 = artifact(chain, carry2)
eq("chain: the first id resolves to the newest line in the artifact",
   sqlite3.connect(art4).execute("SELECT new_tome_id FROM id_redirect WHERE old_tome_id=?", (old_jp,)).fetchone(),
   (rl(K1, "JP", "Les Enquêtes (1re partie) - FILE"),))
eq("chain: the gate passes", ids_ok(art4, carry2), [])
db.close()

# ---- a merged work: its lines re-key under the survivor; the work id is redirected ---------------
WA, WB = "en:Drops of God", "fr:Liste des chapitres des Gouttes de Dieu"
jp = vols(3, 4)
before = catalogue("merge1", [
    (WA, "Drops of God", [("JP", "manga", "Drops of God", jp), ("EN", "manga", "Drops of God", vols(4, 4))]),
    (WB, "s Gouttes de Dieu", [("JP", "manga", "Les Gouttes de Dieu", jp),
                               ("FR", "manga", "Les Gouttes de Dieu", vols(5, 4))])])
carry = artifact(before)
after = catalogue("merge2", [
    (WA, "Drops of God", [("JP", "manga", "Drops of God", jp), ("EN", "manga", "Drops of God", vols(4, 4))]),
    (WA, "Drops of God", [("JP", "manga", "Drops of God (Les Gouttes de Dieu)", jp),
                          ("FR", "manga", "Drops of God (Les Gouttes de Dieu)", vols(5, 4))])])
db = sqlite3.connect(after)
rep = K.redirects(db, carry, excluded=set())
eq("merged work: the absorbed work redirects to the survivor (duplicate_merge)",
   db.execute("SELECT new_id, reason FROM id_redirect WHERE old_id=?", (_id("w_", WB),)).fetchone(),
   (_id("w_", WA), "duplicate_merge"))
eq("merged work: the JP line goes to the re-keyed copy when one exists (a new line first)",
   db.execute("SELECT new_id FROM id_redirect WHERE old_id=?", (rl(WB, "JP", "Les Gouttes de Dieu"),)).fetchone(),
   (rl(WA, "JP", "Drops of God (Les Gouttes de Dieu)"),))
art = artifact(after, carry)
eq("merged work: the work redirect reaches the artifact (works count as present)",
   sqlite3.connect(art).execute("SELECT new_tome_id, entity FROM id_redirect WHERE old_tome_id=?",
                                (_id("w_", WB),)).fetchone(), (_id("w_", WA), "work"))
eq("merged work: the gate passes", ids_ok(art, carry), [])
db.close()

# ---- shared ISBNs: the successor is looked for in the line's own work first ----------------------
WK, WO = "en:Kindaichi", "fr:Liste des chapitres des Enquêtes (2e partie)"
shared = vols(6, 3)
before = catalogue("shared1", [(WK, "Kindaichi", [("JP", "manga", "Kindaichi R", shared)]),
                               (WO, "s Enquêtes (2e partie)", [("JP", "manga", "s Enquêtes (2e partie) (R)", shared)])])
carry = artifact(before)
after = catalogue("shared2", [(WK, "Kindaichi", [("JP", "manga", "Kindaichi R", shared)]),
                              (WO, "Les Enquêtes (2e partie)", [("JP", "manga", "Les Enquêtes (2e partie) (R)", shared)])])
db = sqlite3.connect(after)
K.redirects(db, carry, excluded=set())
eq("shared ISBNs: the re-keyed line of the same work wins over another work's line",
   db.execute("SELECT new_id FROM id_redirect WHERE old_id=?", (rl(WO, "JP", "s Enquêtes (2e partie) (R)"),)).fetchone(),
   (rl(WO, "JP", "Les Enquêtes (2e partie) (R)"),))
db.close()

# ---- no ISBNs: a line follows its dated volumes; a vanished volume retires to its line --------------
WN = "en:Undated"
before = catalogue("sig1", [(WN, "Undated", [("JP", "manga", "Undated (Old name)",
                                               [("1", None, "2001-01-01"), ("2", None, "2001-02-01"), ("3", None, "2001-03-01")])])])
carry = artifact(before)
after = catalogue("sig2", [(WN, "Undated", [("JP", "manga", "Undated (New name)",
                                              [("1", None, "2001-01-01"), ("2", None, "2001-02-01")])])])
db = sqlite3.connect(after)
rep = K.redirects(db, carry, excluded=set())
new_line = rl(WN, "JP", "Undated (New name)")
eq("no ISBNs: the line follows its dated volumes",
   db.execute("SELECT new_id, reason FROM id_redirect WHERE old_id=?", (rl(WN, "JP", "Undated (Old name)"),)).fetchone(),
   (new_line, "correction"))
eq("a volume number that is gone retires to the successor line",
   db.execute("SELECT new_id, reason FROM id_redirect WHERE old_id=?",
              (_id("v_", rl(WN, "JP", "Undated (Old name)"), "3"),)).fetchone(), (new_line, "retired"))
art = artifact(after, carry)
eq("no ISBNs: the gate passes (one retirement is within the cap)", ids_ok(art, carry), [])
db.close()

# a line with no evidence at all retires to its work's main line of the market
before = catalogue("ret1", [(WN, "Undated", [("JP", "manga", "Undated", vols(7, 3)),
                                             ("JP", "manga", "Undated (Arc)", [("1", None, None), ("2", None, None)])])])
carry = artifact(before)
after = catalogue("ret2", [(WN, "Undated", [("JP", "manga", "Undated", vols(7, 3))])])
db = sqlite3.connect(after)
K.redirects(db, carry, excluded=set())
eq("no successor line: retired to the work's main line of that market",
   db.execute("SELECT new_id, reason FROM id_redirect WHERE old_id=?", (rl(WN, "JP", "Undated (Arc)"),)).fetchone(),
   (rl(WN, "JP", "Undated"), "retired"))
db.close()

# ---- an excluded work is retired on purpose; any other vanished work is an orphan ----------------
WX, WG = "en:Excluded", "en:Gone"
before = catalogue("gone1", [(WN, "Undated", [("JP", "manga", "Undated", vols(8, 2))]),
                             (WX, "Excluded", [("EN", "manga", "Excluded", vols(9, 2))]),
                             (WG, "Gone", [("EN", "manga", "Gone", vols(10, 2))])])
carry = artifact(before)
after = catalogue("gone2", [(WN, "Undated", [("JP", "manga", "Undated", vols(8, 2))])])
db = sqlite3.connect(after)
rep = K.redirects(db, carry, excluded={_id("w_", WX)})
eq("excluded work: no rows, counted as retired on purpose", (rep["excluded"], sum(rep["rows"].values())), (3, 0))
eq("a work gone for no known reason: its work, line and volumes are orphans",
   sorted(rep["orphans"]), sorted([_id("w_", WG), rl(WG, "EN", "Gone"),
                                   _id("v_", rl(WG, "EN", "Gone"), "1"), _id("v_", rl(WG, "EN", "Gone"), "2")]))
db.close()

# ---- no carry: nothing to do ---------------------------------------------------------------------
db = sqlite3.connect(after)
eq("no carried artifact: an empty report", K.redirects(db, None, excluded=set())["orphans"], [])
db.close()

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("all carried-id tests passed")
