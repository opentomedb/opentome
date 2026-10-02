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
def L(i, name, wt="Black Butler", arc=False, medium="manga", market="FR"):
    return {"id": i, "work_id": "w", "work_title": wt, "market": market, "medium": medium, "name": name, "arc_split": arc}
eq("T candidate", m.candidates([L("t", "Black Butler (Tomes 31 à aujourd'hui)"), L("b", "Black Butler")]), [("t", "b", "T")])
eq("W2 candidate", m.candidates([L("t", "Black Butler (Mangas)"), L("b", "Black Butler")]), [("t", "b", "W2")])
eq("not the work's own line -> none", m.candidates([L("t", "Kuro (Tomes 31 à aujourd'hui)"), L("b", "Kuro")]), [])
eq("arc split out of the group -> none", m.candidates([L("t", "Black Butler (Tomes 31 à aujourd'hui)", arc=True), L("b", "Black Butler")]), [])
eq("other market -> none", m.candidates([L("t", "Black Butler (Tomes 31 à aujourd'hui)"), L("b", "Black Butler", market="JP")]), [])
eq("nested parens: last ' (' splits", m.candidates([L("t", "X (Y) (Mangas)", wt="X (Y)"), L("b", "X (Y)", wt="X (Y)")]), [("t", "b", "W2")])
print("FAILED: %d" % len(FAILS) if FAILS else "all passed"); sys.exit(1 if FAILS else 0)
