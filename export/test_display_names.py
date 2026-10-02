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

if __name__ == "__main__":
    run_d()
    print("FAILED: %d" % len(FAILS) if FAILS else "all passed")
    sys.exit(1 if FAILS else 0)
