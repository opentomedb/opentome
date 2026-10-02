#!/usr/bin/env python3
"""Round C display names (docs/superpowers/specs/2026-10-02-round-c-line-names-design.md). Run: python3 export/test_display_names.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import display_names as dn

FAILS = []
def eq(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok:
        FAILS.append(label)

def run_d():
    W = "The Water Magician (novel series)"
    eq("D: whole name is the work title", dn.strip_work_disambiguator(W, W), "The Water Magician")
    eq("D: prefix before a part qualifier", dn.strip_work_disambiguator(W + " (Part 1)", W), "The Water Magician (Part 1)")
    for w in ("Gate (novel series)", "K (TV series)", "Ghost Hunt (novel series)", "X (2017 manga)", "X (Clamp manga)",
              "X (manga, 2021)", "X (webcomic)", "X (literary series)", "X (Japanese TV series)", "X (2025 TV series)",
              "Shiki (roman)", "Radiant (bande dessinée)", "Y (jeu vidéo)"):
        eq("D: listed disambiguator %r" % w, dn.strip_work_disambiguator(w, w), w[:w.index(" (")])
    eq("D: work title without a disambiguator -> no-op even if the line ends in a listed word",
       dn.strip_work_disambiguator("Arifureta (Bande dessinée)", "Arifureta"), "Arifureta (Bande dessinée)")
    eq("D: line not starting with the exact work title -> no-op",
       dn.strip_work_disambiguator("Something Else (Part 1)", W), "Something Else (Part 1)")
    eq("D: unlisted qualifier on the work title -> no-op",
       dn.strip_work_disambiguator("Monster (Urasawa)", "Monster (Urasawa)"), "Monster (Urasawa)")
    eq("D: full-width parentheses are part of the title",
       dn.strip_work_disambiguator("オトメン（乙男）", "オトメン（乙男）"), "オトメン（乙男）")

def run_sw():
    eq("S: subtitle that names the work", dn.self_named("86 (86: Eighty-Six - Fragmental Neoteny)", "86"),
       "86: Eighty-Six - Fragmental Neoteny")
    eq("S: K Days of Blue", dn.self_named("K (K: Days of Blue)", "K"), "K: Days of Blue")
    eq("S: word boundary -- Gate never matches Gatekeeper", dn.self_named("Gate (Gatekeeper Saga)", "Gate"),
       "Gate (Gatekeeper Saga)")
    eq("S: an edition qualifier is not a spin-off title", dn.self_named("Gate (New Edition)", "Gate"), "Gate (New Edition)")
    eq("S: case-insensitive", dn.self_named("Re:Zero (re:zero ex)", "Re:Zero"), "re:zero ex")
    eq("W: section word dropped", dn.strip_round_a_word("Whispered Words (Médias)", "manga"), ("Whispered Words", "manga", "W"))
    eq("W: Mangas", dn.strip_round_a_word("Kaina of the Great Snow Sea (Mangas)", "manga"),
       ("Kaina of the Great Snow Sea", "manga", "W"))
    eq("M: class-2 word retags a manga line", dn.strip_round_a_word("Hyouka (Roman)", "manga"), ("Hyouka", "novel", "M"))
    eq("M: roman illustré -> light_novel", dn.strip_round_a_word("Goblin Slayer (Roman illustré)", "manga"),
       ("Goblin Slayer", "light_novel", "M"))
    eq("M: an already-novel line keeps its medium (only the word goes)",
       dn.strip_round_a_word("Princess Lover! (Liste des romans)", "light_novel"), ("Princess Lover!", "light_novel", "W"))
    eq("W: open-ended pagination is T, not W", dn.strip_round_a_word("Black Butler (Tomes 31 à aujourd'hui)", "manga"),
       ("Black Butler (Tomes 31 à aujourd'hui)", "manga", None))
    eq("W: a real qualifier stays", dn.strip_round_a_word("Gate (Édition deluxe)", "manga"), ("Gate (Édition deluxe)", "manga", None))
    W = "The Water Magician (novel series)"
    eq("display: D then nothing", dn.display(W + " (Part 1)", W, "manga"), ("The Water Magician (Part 1)", "manga", ["D"]))
    eq("display: D then S", dn.display("86 (novel series) (86: Eighty-Six - Fragmental Neoteny)", "86 (novel series)", "manga"),
       ("86: Eighty-Six - Fragmental Neoteny", "manga", ["D", "S"]))
    eq("display: untouched", dn.display("Naruto (2e partie)", "Naruto", "manga"), ("Naruto (2e partie)", "manga", []))

def L(tid, wid, wt, name, medium="manga", market="JP", born=False):
    fam = "comic" if medium in ("manga", "manhwa", "manhua") else medium
    return {"tome_id": tid, "work_id": wid, "work_title": wt, "market": market, "medium": medium,
            "family": fam, "name": name, "born": born}

def run_guards():
    r = dn.plan_names([L("a", "w1", "Whispered Words", "Whispered Words (Médias)")], set(), {})
    eq("guard: alone -> renamed", (r["a"]["name"], r["a"]["held"]), ("Whispered Words", None))
    r = dn.plan_names([L("a", "w1", "Insomniacs", "Insomniacs (Mangas)"), L("b", "w1", "Insomniacs", "Insomniacs")], set(), {})
    eq("guard: within-work clash -> pipeline name kept", (r["a"]["name"], r["a"]["held"]), ("Insomniacs (Mangas)", "held-clash"))
    eq("guard: the sibling is untouched", r["b"]["name"], "Insomniacs")
    r = dn.plan_names([L("a", "w1", "Gate (novel series)", "Gate (novel series)"), L("b", "w2", "Gate", "Gate")], set(), {})
    eq("guard: cross-work clash keeps the disambiguator", (r["a"]["name"], r["a"]["held"]), ("Gate (novel series)", "held-cross"))
    r = dn.plan_names([L("a", "w1", "Gate (novel series)", "Gate (novel series)"), L("b", "w2", "Gate", "Gate")],
                      {("JP", "comic", "gate")}, {})
    eq("guard: a pair the carry already had is not new -> renamed", r["a"]["name"], "Gate")
    r = dn.plan_names([L("a", "w1", "Solo Leveling", "Solo Leveling (Roman web)", market="KR"),
                       L("b", "w1", "Solo Leveling", "Solo Leveling", market="KR")], set(),
                      {"a": {"1", "2", "3"}, "b": {"1", "2", "3"}})
    eq("guard: M retag held when the line duplicates a line by ISBN", (r["a"]["medium"], r["a"]["held"]), ("manga", "held-isbn"))
    r = dn.plan_names([L("a", "w1", "Hyouka", "Hyouka (Roman)"), L("b", "w1", "Hyouka", "Hyouka", medium="novel")], set(), {})
    eq("guard: retag into a medium where the name exists -> clash held", (r["a"]["name"], r["a"]["medium"], r["a"]["held"]),
       ("Hyouka (Roman)", "manga", "held-clash"))
    r = dn.plan_names([L("a", "w1", "X (novel series)", "X (novel series)", born=True)], set(), {})
    eq("guard: library-born line never renamed", (r["a"]["name"], r["a"]["rules"]), ("X (novel series)", []))
    la = L("a", "w1", "Solo", "Solo (Roman)", market="KR")
    lb = L("b", "w1", "Solo", "Solo: Side (Roman)", market="KR")
    isb = {"a": {"1", "2", "3"}, "b": {"1", "2", "4"}}
    r1, r2 = dn.plan_names([la, lb], set(), isb), dn.plan_names([lb, la], set(), isb)
    eq("guard: ISBN guard is order-independent", r1, r2)
    eq("guard: ISBN guard holds both lines", (r1["a"]["held"], r1["b"]["held"]), ("held-isbn", "held-isbn"))
    r = dn.plan_names([L("a", "w1", "Hyouka (novel series)", "Hyouka (novel series) (Roman)"), L("b", "w2", "Hyouka", "Hyouka", medium="novel")], set(), {})
    eq("guard: cross-work revert never retags", (r["a"]["name"], r["a"]["medium"], r["a"]["held"]),
       ("Hyouka (novel series) (Roman)", "manga", "held-cross"))

def C(tid, wid, name, medium, vols=7, sid=1):
    return {"tome_id": tid, "work_id": wid, "name": name, "language": "en", "medium": medium, "is_omnibus": 0,
            "dated_count": vols, "volume_count": vols, "gcd_series_id": sid}

def run_lookup():
    before = [C("ln", "w", "The Water Magician (novel series)", "light_novel", sid=1),
              C("mg", "w", "The Water Magician (novel series) (Part 1)", "manga", sid=2)]
    after = [C("ln", "w", "The Water Magician", "light_novel", sid=1),
             C("mg", "w", "The Water Magician (Part 1)", "manga", sid=2)]
    eq("lookup: the LN rename that would win the manga library's bare-title lookup is held",
       dn.lookup_holds(before, after), {"ln": "held-lookup"})
    eq("lookup: a rename with no competing line is not held",
       dn.lookup_holds([C("a", "w", "Gate (novel series)", "light_novel")], [C("a", "w", "Gate", "light_novel")]), {})

if __name__ == "__main__":
    run_d()
    run_sw()
    run_guards()
    run_lookup()
    print("FAILED: %d" % len(FAILS) if FAILS else "all passed")
    sys.exit(1 if FAILS else 0)
