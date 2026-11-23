#!/usr/bin/env python3
"""Round C merges (spec §3.2). Run: python3 tier0/test_round_c_merge.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import round_c_merge as m
FAILS = []
def eq(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok: FAILS.append(label)

def V(rng, isbn=True): return {n: ("978%010d" % n if isbn else None) for n in rng}
eq("extend: 31-35 after 1-30", m.verdict(V(range(31, 36)), V(range(1, 31))), "extend")
eq("duplicate: same numbers, same ISBNs", m.verdict(V(range(31, 36)), V(range(1, 36))), "duplicate")
eq("duplicate: candidate without ISBNs", m.verdict(V(range(1, 4), False), V(range(1, 10))), "duplicate")
eq("kept: same number, different ISBN", m.verdict({1: "9780000000099"}, V(range(1, 10))), "kept")
eq("kept: a gap below the target's top", m.verdict(V(range(5, 8)), {1: None, 2: None, 10: None}), "kept")
eq("kept: empty candidate", m.verdict({}, V(range(1, 4))), "kept")
eq("kept: non-int candidate number", m.verdict({"A": None}, V(range(1, 4))), "kept")
eq("duplicate: string numbers", m.verdict({"1": None}, {"1": "x"}), "duplicate")
eq("kept/gap: Gamaran 31-35 after 1-22 (the tail continues the sequel)",
   m.verdict_why(V(range(31, 36)), V(range(1, 23))), ("kept", "gap"))
eq("extend/no reason: 31-35 after 1-30", m.verdict_why(V(range(31, 36)), V(range(1, 31))), ("extend", None))
eq("kept/verdict: same number, different ISBN", m.verdict_why({1: "9780000000099"}, V(range(1, 10))), ("kept", "verdict"))
def L(i, name, wt="Black Butler", arc=False, medium="manga", market="FR"):
    return {"id": i, "work_id": "w", "work_title": wt, "market": market, "medium": medium, "name": name, "arc_split": arc}
eq("T candidate", m.candidates([L("t", "Black Butler (Tomes 31 à aujourd'hui)"), L("b", "Black Butler")]), [("t", "b", "T")])
eq("W2 candidate", m.candidates([L("t", "Black Butler (Mangas)"), L("b", "Black Butler")]), [("t", "b", "W2")])
NOL = [L("t", "Kuro (Tomes 31 à aujourd'hui)"), L("b", "Kuro")]
ARCL = [L("t", "Black Butler (Tomes 31 à aujourd'hui)", arc=True), L("b", "Black Butler")]
eq("not the work's own line -> none", m.candidates(NOL), [])
eq("not the work's own line -> candidates_all lists it held", m.candidates_all(NOL), [("t", "b", "T", "not-own-line")])
eq("arc split out of the group -> none", m.candidates(ARCL), [])
eq("arc split out of the group -> candidates_all lists it held", m.candidates_all(ARCL), [("t", "b", "T", "arc")])
eq("candidates_all: a mergeable one has no reason",
   m.candidates_all([L("t", "Black Butler (Mangas)"), L("b", "Black Butler")]), [("t", "b", "W2", None)])
eq("other market -> none", m.candidates([L("t", "Black Butler (Tomes 31 à aujourd'hui)"), L("b", "Black Butler", market="JP")]), [])
eq("nested parens: last ' (' splits", m.candidates([L("t", "X (Y) (Mangas)", wt="X (Y)"), L("b", "X (Y)", wt="X (Y)")]), [("t", "b", "W2")])


# ---- the stage on a tiny catalogue (run(db, carry)) -------------------------------------------------
# helpers copied from tier0/test_carried_ids.py (never import a test file)
import json, sqlite3, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for d in (os.path.join(ROOT, "schema"), os.path.join(ROOT, "export"), os.path.join(ROOT, "tier2")):
    sys.path.insert(0, d)
import corrections as corr
from load import load, _id
os.environ.pop("OPENTOME_COLD_START", None)
TMP = tempfile.mkdtemp(prefix="opentome-roundc-")
corr.DIR = tempfile.mkdtemp(prefix="opentome-nocorr-")          # no corrections in play


def catalogue(name, works):
    """works: [(work_key, title, [(market, medium, line, [(number, isbn, date)])])] -> db path.
    A line tuple may carry a 5th item: the line it is an arc of (arc_of)."""
    path = os.path.join(TMP, name + ".db")
    db = sqlite3.connect(path)
    db.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
    for key, title, lines in works:
        recs = [dict({"volume": n, "line": ln[2], "medium": ln[1],
                      "markets": {"original": {"market": ln[0], "isbn13": isbn, "date": date,
                                               "date_precision": "day" if date else None}}},
                     **({"arc_of": ln[4]} if len(ln) > 4 and ln[4] else {}),
                     **({"wiki": ln[5]} if len(ln) > 5 else {}))
                for ln in lines for n, isbn, date in ln[3]]
        load(db, title, recs, work_key=key)
    db.commit()
    db.close()
    return path


def rl(key, market, line, medium="manga"):
    return _id("rl_", _id("w_", key), medium, market, line)


def vols(prefix, n, first=1, date=True):
    return [(str(i), "97840%08d" % (prefix * 1000 + i), "2010-01-%02d" % (i % 28 + 1) if date else None)
            for i in range(first, first + n)]


def carry_with(merges):
    path = tempfile.mktemp(suffix=".sqlite", dir=TMP)
    A = sqlite3.connect(path)
    A.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    A.execute("INSERT INTO meta VALUES('round_c_merges', ?)", (json.dumps(merges),))
    A.commit()
    A.close()
    return path


def state(path, line):
    db = sqlite3.connect(path)
    have = db.execute("SELECT 1 FROM release_line WHERE id=?", (line,)).fetchone() is not None
    nums = sorted(int(n) for (n,) in db.execute("SELECT number FROM volume WHERE release_line_id=?", (line,)))
    meta = json.loads((db.execute("SELECT value FROM meta WHERE key='roundc:merged'").fetchone() or ["null"])[0])
    db.close()
    return have, nums, meta


BB = "fr:Black Butler"
TAIL = "Black Butler (Tomes 31 à aujourd'hui)"
main, tail = rl(BB, "FR", "Black Butler"), rl(BB, "FR", TAIL)

# extend: 1-30 + a tail 31-35
p = catalogue("extend", [(BB, "Black Butler", [("FR", "manga", "Black Butler", vols(1, 30)),
                                                ("FR", "manga", TAIL, vols(1, 5, 31))])])
m.run(p)
have, nums, meta = state(p, tail)
eq("extend: the tail line is gone", have, False)
eq("extend: the main line holds 35 numbers", state(p, main)[1], list(range(1, 36)))
eq("extend: meta lists the merge", meta, [[tail, main, "T", "extend", 5, 0, "rule"]])
D = sqlite3.connect(p)
eq("extend: meta roundc:names records the candidate's pipeline name",
   json.loads(D.execute("SELECT value FROM meta WHERE key='roundc:names'").fetchone()[0]), {tail: TAIL})
D.close()

# gap: Gamaran 1-22 + a "(Tomes 31 à aujourd'hui)" tail 31-35 that continues the sequel -> kept/gap
GA = "fr:Gamaran"
GTAIL = "Gamaran (Tomes 31 à aujourd'hui)"
gmain, gtail = rl(GA, "FR", "Gamaran"), rl(GA, "FR", GTAIL)
p = catalogue("gap", [(GA, "Gamaran", [("FR", "manga", "Gamaran", vols(1, 22)),
                                       ("FR", "manga", GTAIL, vols(1, 5, 31))])])
m.run(p)
eq("gap: the tail stays with 31-35, main keeps 1-22, meta lists kept/gap",
   (state(p, gtail), state(p, gmain)[1]),
   ((True, list(range(31, 36)), [[gtail, gmain, "T", "kept", 0, 0, "rule", "gap"]]), list(range(1, 23))))
# ... and a carried merge of that pair (an older build's extend) is refused: carry-conflict/gap
p = catalogue("gap-carry", [(GA, "Gamaran", [("FR", "manga", "Gamaran", vols(1, 22)),
                                             ("FR", "manga", GTAIL, vols(1, 5, 31))])])
m.run(p, carry_with([[gtail, gmain, "extend", "T"]]))
eq("gap: a carried extend of a gap pair is carry-conflict/gap",
   state(p, gtail), (True, list(range(31, 36)), [[gtail, gmain, "T", "carry-conflict", 0, 0, "carry", "gap"]]))

# duplicate: the tail repeats 31-35 with the main line's ISBNs
p = catalogue("dup", [(BB, "Black Butler", [("FR", "manga", "Black Butler", vols(1, 35)),
                                             ("FR", "manga", TAIL, vols(1, 5, 31))])])
m.run(p)
eq("duplicate: tail gone, main keeps 35, meta records 0 moved 5 dropped",
   (state(p, tail)[0], state(p, main)[1], state(p, tail)[2]),
   (False, list(range(1, 36)), [[tail, main, "T", "duplicate", 0, 5, "rule"]]))

# kept: a W2 line whose vol 1 has another ISBN
W2 = "Black Butler (Mangas)"
w2 = rl(BB, "FR", W2)
p = catalogue("kept", [(BB, "Black Butler", [("FR", "manga", "Black Butler", vols(1, 10)),
                                              ("FR", "manga", W2, vols(2, 3))])])
m.run(p)
eq("kept: the W2 line stays with its volumes, meta lists it 0/0",
   state(p, w2), (True, [1, 2, 3], [[w2, main, "W2", "kept", 0, 0, "rule", "verdict"]]))

# arc: an arc was split out of the tail's rows (release_line.parent_id = the tail) -> not a candidate
ARC = "Black Butler (Arc du cirque)"
p = catalogue("arc", [(BB, "Black Butler", [("FR", "manga", "Black Butler", vols(1, 30)),
                                             ("FR", "manga", TAIL, vols(1, 5, 31)),
                                             ("FR", "manga", ARC, vols(3, 2), TAIL)])])
m.run(p)
eq("arc: the tail stays (an arc came out of it), listed kept/arc", state(p, tail),
   (True, list(range(31, 36)), [[tail, main, "T", "kept", 0, 0, "rule", "arc"]]))

# re-apply 1: the carry recorded the merge; this build's tail is renamed and still a candidate
TAIL2 = "Black Butler (Volumes 31 à aujourd'hui)"
tail2 = rl(BB, "FR", TAIL2)
c1 = carry_with([[tail, main, "extend"]])
p = catalogue("renamed", [(BB, "Black Butler", [("FR", "manga", "Black Butler", vols(1, 30)),
                                                 ("FR", "manga", TAIL2, vols(1, 5, 31))])])
m.run(p, c1)
eq("re-apply: a renamed tail is still a candidate and merges by rule",
   (state(p, tail2)[0], state(p, main)[1], state(p, tail2)[2]),
   (False, list(range(1, 36)), [[tail2, main, "T", "extend", 5, 0, "rule"]]))

# re-apply 2: no rule matches any more (the work's title changed: the target is not the work's own
# line), but both ids exist -> the carry's record merges it
p = catalogue("carry", [(BB, "Kuroshitsuji", [("FR", "manga", "Black Butler", vols(1, 30)),
                                               ("FR", "manga", TAIL, vols(1, 5, 31))])])
m.run(p, c1)
eq("re-apply: no rule matches, the carry record merges by id",
   (state(p, tail)[0], state(p, main)[1], state(p, tail)[2]),
   (False, list(range(1, 36)), [[tail, main, "T", "extend", 5, 0, "carry"]]))

# carry-conflict (a): the carry recorded tail -> main, but this build splits an arc out of the tail
p = catalogue("conflict-arc", [(BB, "Black Butler", [("FR", "manga", "Black Butler", vols(1, 30)),
                                                      ("FR", "manga", TAIL, vols(1, 5, 31)),
                                                      ("FR", "manga", ARC, vols(3, 2), TAIL)])])
m.run(p, c1)
D = sqlite3.connect(p)
eq("carry-conflict (arc): the tail stays, the arc still hangs under it, listed carry-conflict/arc",
   (state(p, tail), D.execute("SELECT parent_id FROM release_line WHERE id=?", (rl(BB, "FR", ARC),)).fetchone()[0]),
   ((True, list(range(31, 36)), [[tail, main, "T", "carry-conflict", 0, 0, "carry", "arc"]]), tail))
D.close()

# carry-conflict (b): main grew to 1-32; the tail's 31-32 carry other ISBNs -> no merge, nothing dropped
p = catalogue("conflict-isbn", [(BB, "Kuroshitsuji", [("FR", "manga", "Black Butler", vols(1, 32)),
                                                       ("FR", "manga", TAIL, vols(5, 5, 31))])])
m.run(p, c1)
D = sqlite3.connect(p)
eq("carry-conflict (verdict): the tail keeps 31-35, main 1-32, 37 volumes in all, listed carry-conflict",
   (state(p, tail), state(p, main)[1], D.execute("SELECT COUNT(*) FROM volume").fetchone()[0]),
   ((True, list(range(31, 36)), [[tail, main, "T", "carry-conflict", 0, 0, "carry", "verdict:kept"]]),
    list(range(1, 33)), 37))
D.close()

# re-apply 3: a carry record whose target is gone does nothing
p = catalogue("gone", [(BB, "Kuroshitsuji", [("FR", "manga", TAIL, vols(1, 5, 31))])])
m.run(p, carry_with([[tail, main, "extend"]]))
eq("re-apply: a record whose target is absent is skipped", state(p, tail), (True, list(range(31, 36)), []))

# zero-padded numbers: counted and printed, never fatal
import contextlib, io
p = catalogue("padded", [(BB, "Black Butler", [("FR", "manga", "Black Butler", [("01", None, None), ("2", None, None)])])])
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    m.run(p)
eq("padded: a zero-padded number is reported", "1 line(s) with zero-padded volume numbers" in buf.getvalue(), True)

# the export writes the applied merges (not the kept ones) as artifact meta round_c_merges
from to_mangarr import export
p = catalogue("export", [(BB, "Black Butler", [("FR", "manga", "Black Butler", vols(1, 30)),
                                                ("FR", "manga", TAIL, vols(1, 5, 31)),
                                                ("FR", "manga", W2, [("1", "9784099999999", None)])])])
m.run(p)
art = p.replace(".db", ".sqlite")
export(p, art, None)
A = sqlite3.connect(art)
eq("export: meta round_c_merges lists applied merges only",
   json.loads((A.execute("SELECT value FROM meta WHERE key='round_c_merges'").fetchone() or ["null"])[0]),
   [[tail, main, "extend", "T", TAIL]])
A.close()

# a carry-conflict ships the candidate again on purpose: the export lists it in meta round_c_conflicts
p = catalogue("export-conflict", [(BB, "Kuroshitsuji", [("FR", "manga", "Black Butler", vols(1, 32)),
                                                         ("FR", "manga", TAIL, vols(5, 5, 31))])])
m.run(p, c1)
art = p.replace(".db", ".sqlite")
export(p, art, None)
A = sqlite3.connect(art)
meta = dict(A.execute("SELECT key, value FROM meta"))
eq("export: meta round_c_conflicts lists the refused carried merge, round_c_merges stays absent",
   (json.loads(meta.get("round_c_conflicts", "null")), "round_c_merges" in meta),
   ([[tail, main, "verdict:kept"]], False))
A.close()
# ---- the corrections round (2026-11-23): kinds P, D, C -------------------------------------------------
# P: "<own line> (any qualifier)" whose volumes DUPLICATE the own line merges; an extend never does
eq("P candidate: any other qualifier on the own line",
   m.candidates_all([L("s", "Black Butler (Saison 1 : La rage)"), L("b", "Black Butler")]), [("s", "b", "P", None)])
eq("P: not the own line -> held as before", m.candidates_all([L("s", "Kuro (Saison 1)"), L("b", "Kuro")]), [("s", "b", "P", "not-own-line")])
HS = "fr:Hajime no Sample"
hmain, hs1, hs2, hsuite = (rl(HS, "JP", n) for n in ("Hajime no Sample", "Hajime no Sample (Saison 1 : La rage)",
                                                       "Hajime no Sample (Saison 2 : Destins)", "Hajime no Sample (Suite)"))
p = catalogue("kind-p", [(HS, "Hajime no Sample", [("JP", "manga", "Hajime no Sample", vols(7, 10)),
                                                    ("JP", "manga", "Hajime no Sample (Saison 1 : La rage)", vols(7, 5)),
                                                    ("JP", "manga", "Hajime no Sample (Saison 2 : Destins)", vols(8, 5)),
                                                    ("JP", "manga", "Hajime no Sample (Suite)", vols(7, 5, 11))])])
done = m.run(p)
eq("P: the duplicate section line is gone", state(p, hs1)[0], False)
eq("P: a section line with other ISBNs stays", state(p, hs2)[0], True)
eq("P: a contiguous tail with a plain qualifier stays (P never extends)", state(p, hsuite)[0], True)
eq("P: meta records the merge only (a kept P line is an ordinary sub-line)",
   sorted((d[0], d[2], d[3]) for d in done), [(hs1, "P", "duplicate")])

# D: two lines of one work, market and medium whose volumes duplicate each other (shared numbers carry the same
# ISBNs, at least 3 of them) merge; the own line survives, else the unqualified name, else the English article's,
# else the smaller id; the survivor takes the other's extra numbers
SW = "en:Sword Sample"
prog, arc1 = rl(SW, "JP", "Sword Sample: Progressive"), rl(SW, "JP", "Arc 1 - Sword Sample: Progressive")
p = catalogue("kind-d", [(SW, "Sword Sample", [("JP", "manga", "Sword Sample: Progressive", vols(3, 7), None, "en"),
                                               ("JP", "manga", "Arc 1 - Sword Sample: Progressive", vols(3, 7), None, "fr")])])
done = m.run(p)
eq("D: the French-article twin is gone, the English-article line survives", (state(p, arc1)[0], state(p, prog)[0]), (False, True))
eq("D: meta row", [(d[0], d[1], d[2], d[3]) for d in done], [(arc1, prog, "D", "duplicate")])
YS = "en:Yowamushi Sample"
ymain, yvols = rl(YS, "JP", "Yowamushi Sample"), rl(YS, "JP", "Yowamushi Sample volumes")
p = catalogue("kind-d-prefix", [(YS, "Yowamushi Sample", [("JP", "manga", "Yowamushi Sample", vols(4, 95)),
                                                          ("JP", "manga", "Yowamushi Sample volumes", vols(4, 101))])])
done = m.run(p)
eq("D: the own line survives and takes the longer twin's extra numbers", (state(p, yvols)[0], state(p, ymain)[1][-1]), (False, 101))
eq("D: meta row counts the moved numbers", [(d[0], d[1], d[2], d[3], d[4]) for d in done], [(yvols, ymain, "D", "duplicate", 6)])
p = catalogue("kind-d-two", [(YS, "Yowamushi Sample", [("JP", "manga", "Yowamushi Sample", vols(4, 95)),
                                                       ("JP", "manga", "Yowamushi Sample volumes", vols(5, 2))])])
done = m.run(p)
eq("D: fewer than three shared ISBNs is no evidence", (state(p, yvols)[0], done), (True, []))
p = catalogue("kind-d-diff", [(YS, "Yowamushi Sample", [("JP", "manga", "Yowamushi Sample", vols(4, 10)),
                                                        ("JP", "manga", "Yowamushi Sample (Perfect)", vols(5, 10))])])
done = m.run(p)
eq("D/P: other ISBNs on every number: nothing merges, nothing recorded", (state(p, rl(YS, "JP", "Yowamushi Sample (Perfect)"))[0], done), (True, []))

# C: "(= Volumes N à M =)" chunks with continuous numbering and no own line fold into the lowest chunk
AO = "fr:Aoashi Sample"
c1, c2, c3 = (rl(AO, "FR", n) for n in ("Aoashi Sample (= Volumes 1 à 10 =)", "Aoashi Sample (= Volumes 11 à 20 =)", "Aoashi Sample (= Volumes 21 à 30 =)"))
p = catalogue("kind-c", [(AO, "Aoashi Sample", [("FR", "manga", "Aoashi Sample (= Volumes 1 à 10 =)", vols(9, 10)),
                                                ("FR", "manga", "Aoashi Sample (= Volumes 11 à 20 =)", vols(9, 10, 11)),
                                                ("FR", "manga", "Aoashi Sample (= Volumes 21 à 30 =)", vols(9, 10, 21))])])
done = m.run(p)
eq("C: the later chunks are gone, the first holds 1-30", (state(p, c2)[0], state(p, c3)[0], state(p, c1)[1]), (False, False, list(range(1, 31))))
eq("C: meta rows", [(d[0], d[1], d[2], d[3]) for d in done], [(c2, c1, "C", "extend"), (c3, c1, "C", "extend")])
p = catalogue("kind-c-gap", [(AO, "Aoashi Sample", [("FR", "manga", "Aoashi Sample (= Volumes 1 à 10 =)", vols(9, 10)),
                                                    ("FR", "manga", "Aoashi Sample (Tomes 21 à 30)", vols(9, 10, 21))])])
done = m.run(p)
eq("C: a gap keeps the chunks apart", (state(p, rl(AO, "FR", "Aoashi Sample (Tomes 21 à 30)"))[0], [d[3] for d in done]), (True, ["kept"]))
eq("C: chunk pattern", [m.chunk_range(n) for n in ("= Volumes 1 à 10 =", "Tomes 21 à 30", "Volumes 11-20", "Tomes 31 à aujourd'hui", "Saison 1")],
   [(1, 10), (21, 30), (11, 20), None, None])

# a licensed line named like the retired twin is pinned to the survivor -- with a non-ASCII capital in the name
# (SQLite's LOWER() leaves "Édition" as it is; the match is made in Python)
CE = "fr:Cat Sample"
cmain, ctwin, cfr = rl(CE, "JP", "Cat Sample"), rl(CE, "JP", "Cat Sample (Édition deluxe)"), rl(CE, "FR", "Cat Sample (Édition deluxe)")
p = catalogue("accent-pin", [(CE, "Cat Sample", [("JP", "manga", "Cat Sample", vols(6, 10)),
                                                 ("JP", "manga", "Cat Sample (Édition deluxe)", vols(6, 10)),
                                                 ("FR", "manga", "Cat Sample (Édition deluxe)", vols(7, 10))])])
m.run(p)
D = sqlite3.connect(p)
eq("a licensed line named like the retired twin (É) is pinned to the survivor",
   D.execute("SELECT value, source FROM claim WHERE entity='release_line' AND entity_id=? AND field='origin_line'", (cfr,)).fetchone(), (cmain, "opentome"))
D.close()

# a derived origin pin (an earlier merge's) that names the twin a P merge retires follows it to the survivor
DQ = "fr:Dragon Sample"
jmain, jtwin, fr = rl(DQ, "JP", "Dragon Sample"), rl(DQ, "JP", "Dragon Sample (Édition 2020)"), rl(DQ, "FR", "Dragon Sample (Édition 2020)")
p = catalogue("stale-pin", [(DQ, "Dragon Sample", [("JP", "manga", "Dragon Sample", vols(2, 10)),
                                                   ("JP", "manga", "Dragon Sample (Édition 2020)", vols(2, 10)),
                                                   ("FR", "manga", "Dragon Sample (Édition 2020)", vols(3, 10))])])
D = sqlite3.connect(p)
D.execute("INSERT INTO claim VALUES('release_line',?,'origin_line',?,'opentome',NULL,'open','x','')", (fr, jtwin))
D.commit(); D.close()
m.run(p)
D = sqlite3.connect(p)
eq("stale derived pin: follows the retired twin to the survivor",
   D.execute("SELECT value FROM claim WHERE entity='release_line' AND entity_id=? AND field='origin_line'", (fr,)).fetchone(), (jmain,))
D.close()

# P / D tolerate one differing ISBN on an otherwise identical twin; a number one side lacks an ISBN for is neutral
eq("near_duplicate: identical", m.near_duplicate(V(range(1, 11)), V(range(1, 11))), True)
one_off = V(range(1, 11)); one_off[11 - 1] = "9780000000099"
eq("near_duplicate: one typo in 10", m.near_duplicate(one_off, V(range(1, 11))), True)
two_off = dict(one_off); two_off[9] = "9780000000098"
eq("near_duplicate: two differ -> no", m.near_duplicate(two_off, V(range(1, 11))), False)
eq("near_duplicate: target lacks ISBNs on some numbers", m.near_duplicate(V(range(1, 11)), {**V(range(1, 11)), 4: None, 7: None}), True)
eq("near_duplicate: too few shared", m.near_duplicate(V(range(1, 3)), V(range(1, 11))), False)
# P: the target may be the line the candidate hangs under, not only the work's own line
eq("P candidate: the candidate's parent is a valid target",
   m.candidates_all([dict(L("s", "Kuro (Saison 1)"), parent="b"), L("b", "Kuro")]), [("s", "b", "P", None)])
# a dropped twin's claims move to the kept volume
KZ = "fr:Kekkai Sample"
kmain, ktwin = rl(KZ, "JP", "Kekkai Sample"), rl(KZ, "JP", "Kekkai Sample (Chapter and volume list)")
p = catalogue("moved-claims", [(KZ, "Kekkai Sample", [("JP", "manga", "Kekkai Sample", [(str(i), "97840%08d" % (12000 + i), None) for i in range(1, 6)]),
                                                     ("JP", "manga", "Kekkai Sample (Chapter and volume list)", [(str(i), "97840%08d" % (12000 + i), "2011-02-%02d" % i) for i in range(1, 6)])])])
m.run(p)
D = sqlite3.connect(p)
kept_v = D.execute("SELECT id FROM volume WHERE release_line_id=? AND number='3'", (kmain,)).fetchone()[0]
eq("moved claims: the kept volume now carries the twin's date claim",
   D.execute("SELECT value FROM claim WHERE entity='volume' AND entity_id=? AND field='release_date'", (kept_v,)).fetchone(), ("2011-02-03",))
eq("moved claims: the twin is gone", state(p, ktwin)[0], False)
D.close()

print("FAILED: %d" % len(FAILS) if FAILS else "all passed"); sys.exit(1 if FAILS else 0)
