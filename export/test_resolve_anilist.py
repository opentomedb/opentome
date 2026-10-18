"""Unit tests for export/resolve_anilist.py: the rules, no recorded pages.
Run: python3 export/test_resolve_anilist.py

The recorded half (AniList pages for the lines of a real library's metadata audit, and the
verdicts that must keep holding) is private: export/private/test_resolve_anilist_recorded.py
with its pages in export/private/fixtures/anilist/, fetched by CI from the private cache repo
and never committed here. It imports this file and adds its own checks.
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("ANILIST_CACHE", os.path.join(HERE, "private", "fixtures", "anilist"))
if not os.environ.get("ANILIST_RECORD"):
    os.environ.setdefault("ANILIST_OFFLINE", "1")
sys.path.insert(0, HERE)
import resolve_anilist as R  # noqa: E402

FAILS = []


def eq(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok:
        FAILS.append(label)


# ---- the rules, no fixtures --------------------------------------------
eq("key: punctuation, case, spacing", R.key("Re:ZERO -Starting Life-"), "rezerostartinglife")
eq("for_search: U+2019 -> '", R.for_search("Let\u2019s Do It Already!"), "Let's Do It Already!")
eq("for_search: dashes + NBSP + spaces", R.for_search("A\u00a0\u2013 B  \u2014 C"), "A - B - C")
# the Latin-only accent strip (2026-09-24; the broad NFKD fold it replaces was reverted): a mark
# goes only with a Latin base letter, everything else comes back byte for byte
for raw, want in [("Fushigi Y\u00fbgi", "Fushigi Yugi"), ("\u00dcbel Blatt", "Ubel Blatt"), ("Saintia Sh\u014d", "Saintia Sho"),
                  ("\u014coku", "Ooku"), ("Bak\u00e9Gyamon", "BakeGyamon"), ("W\u0101qw\u0101q", "Waqwaq"),
                  ("Vi\u1ec7t", "Viet"), ("u\u0302x", "ux")]:
    eq("for_search strips the Latin accent: %r" % raw, R.for_search(raw), want)
for raw in ["\u30b2\u30fc\u30e0", "\u30d1\u30f3", "\ud55c\uad6d\uc5b4", "\u0439", "1\u0302", " \u0302x", "\uf900"]:
    eq("fold leaves a non-Latin base's marks alone: %r" % raw, R.fold(raw), raw)
eq("key: an accented title and its ASCII spelling are one key", R.key("Fushigi Y\u00fbgi"), R.key("Fushigi Yugi"))
eq("key: kana voicing marks still count (\u30ac != \u30ab)", R.key("\u30ac") != R.key("\u30ab"), True)
eq("deslug of an accented name keeps the letter", R.deslug("Fushigi Y\u00fbgi"), "fushigi yugi")
# the numeric-symbol fold: No / Nl only, NFKC per character, the fraction slash -> "/" (AniList's "Ranma 1/2")
for raw, want in [("Ranma \u00bd", "Ranma 1/2"), ("Ranma \u00b9\u2044\u2082", "Ranma 1/2"), ("\u2161", "II"), ("x\u00b2", "x2"), ("\u2460", "1")]:
    eq("for_search folds the numeric symbol: %r" % raw, R.for_search(raw), want)
eq("key: Ranma \u00bd = Ranma 1/2 = Ranma \u00b9\u2044\u2082", {R.key("Ranma \u00bd"), R.key("Ranma 1/2"), R.key("Ranma \u00b9\u2044\u2082")}, {"ranma12"})
for raw in ["\uff32\uff41\uff4e\uff4d\uff41", "\ufb01"]:
    eq("fold leaves full-width / ligatures alone: %r" % raw, R.fold(raw), raw)

one_shot = {"id": 1, "format": "ONE_SHOT", "volumes": 1, "popularity": 9, "status": "FINISHED",
            "title": {"english": "X"}, "synonyms": []}
serial = {"id": 2, "format": "MANGA", "volumes": 20, "popularity": 5, "status": "FINISHED",
          "title": {"english": "X"}, "synonyms": []}
syn = {"id": 3, "format": "MANGA", "volumes": 21, "popularity": 99, "status": "FINISHED",
       "title": {"english": "Y"}, "synonyms": ["X"]}
m, via, rej = R.pick([one_shot, syn, serial], "X", 20)
eq("ONE_SHOT rejected; primary beats a more popular synonym (R1: the carrier is logged, not ranked)", (m["id"], via, rej),
   (2, "primary", ["1:ONE_SHOT", "3:synonym only (a primary-title candidate is on the page)"]))
m, via, _ = R.pick([syn, {**syn, "id": 4, "popularity": 100}], "X", 20)
eq("synonym ties break on popularity", (m["id"], via), (4, "synonym"))
# R1 (the 2026-09-15 live run): a synonym-only carrier never wins while ANY candidate on the page has
# primary-title equality, even one the rules rejected -- a primary rejected on volumes says "this is
# the work but the count disagrees", a same-named ONE_SHOT is the serial's pilot; either way the
# carrier is a chapter title wearing the name, and unresolved is recoverable where a wrong bind is not
eq("R1: synonym carrier never wins beside a primary-title candidate rejected on volumes (Doll-shaped)",
   R.pick([{**serial, "id": 31566, "volumes": 1}, {**syn, "id": 128084, "volumes": 4}], "X", 6),
   (None, None, ["31566:volumes 1 vs 6", "128084:synonym only (a primary-title candidate is on the page)"]))
eq("R1: synonym carrier never wins beside a same-named ONE_SHOT",
   R.pick([one_shot, {**syn, "volumes": 3}], "X", None),
   (None, None, ["1:ONE_SHOT", "3:synonym only (a primary-title candidate is on the page)"]))
m, via, _ = R.pick([{**syn, "volumes": 3}], "X", None)
eq("R1 does not fire without a primary-title candidate on the page", (m["id"], via), (3, "synonym"))
# the ONE-SIDED volume rule (contract "Volume rule"): smaller than the line by more than
# max(3, 40 %) rejects (x2 tolerance while RELEASING); larger than 4x the line rejects;
# larger within 4x never does (2-in-1 English lines, a catalogue that lags an ongoing series)
m, _, rej = R.pick([{**serial, "volumes": 1}], "X", 63)
eq("smaller by more than the tolerance (1 vs 63) rejects", (m, rej), (None, ["2:volumes 1 vs 63"]))
m, _, _ = R.pick([{**serial, "volumes": 5}], "X", 11)
eq("5 vs 11: 6 > max(3, 4.4) rejects", m, None)
m, _, _ = R.pick([{**serial, "volumes": 8}], "X", 11)
eq("8 vs 11: 3 <= max(3, 4.4) passes", m["id"], 2)
m, _, _ = R.pick([{**serial, "volumes": 4, "status": "RELEASING"}], "X", 11)
eq("RELEASING doubles the tolerance (11-4 = 7 <= 8.8)", m["id"], 2)
m, _, _ = R.pick([{**serial, "volumes": 9}], "X", 5)
eq("larger within 4x passes (Erased: 9 tankobon vs 5 English 2-in-1 books)", m["id"], 2)
m, _, _ = R.pick([{**serial, "volumes": 29}], "X", 15)
eq("larger within 4x passes (Vinland Saga: 29 vs 15)", m["id"], 2)
m, via, rej = R.pick([{**serial, "volumes": 63}], "X", 5)
eq("larger than 4x the line is rejected (63 vs 5) -- only R4's fallback tier then binds it",
   ((m or {}).get("id"), via, rej), (2, "ceiling", ["2:volumes 63 > 4x 5"]))
m, _, _ = R.pick([{**serial, "volumes": 20}], "X", 5)
eq("exactly 4x passes (20 vs 5)", m["id"], 2)
# R2 (the 2026-09-15 live run): no 4x ceiling for a line of 1-2 volumes -- a one-book release or a
# run cut short binds the full Japanese serial; the smaller-side rule still applies
m, _, _ = R.pick([{**serial, "volumes": 5}], "X", 1)
eq("R2: a 1-volume line has no ceiling (Pupa: 5 vs 1)", m["id"], 2)
m, _, _ = R.pick([{**serial, "volumes": 63}], "X", 2)
eq("R2: a 2-volume line has no ceiling (63 vs 2)", m["id"], 2)
m, via, rej = R.pick([{**serial, "volumes": 13}], "X", 3)
eq("R2 stops at 3 volumes: 13 > 4x 3 is rejected (only R4's fallback tier then binds it)",
   ((m or {}).get("id"), via, rej), (2, "ceiling", ["2:volumes 13 > 4x 3"]))
m, via, _ = R.pick([{**serial, "volumes": 5, "popularity": 12000}, {**syn, "volumes": 1, "popularity": 300}], "X", 1)
eq("R2 + primary over synonym: the tiny line binds the full serial, not the 1-volume carrier", (m["id"], via), (2, "primary"))
# R3 (the 2026-09-15 live run): the lifted ceiling is for the line's OWN name (and its de-slugged
# form); an alias retry always keeps it, or a spin-off's bare franchise alias binds the main serial
m, _, rej = R.pick([{**serial, "volumes": 34}], "X", 2, own_name=False)
eq("R3: an alias term keeps the ceiling for a tiny line (34 vs 2)", (m, rej), (None, ["2:volumes 34 > 4x 2"]))
m, _, _ = R.pick([{**serial, "volumes": 9}], "X", 2, own_name=False)
eq("R3: 9 > 4x 2 rejects on an alias term", m, None)
m, _, _ = R.pick([{**serial, "volumes": 8}], "X", 2, own_name=False)
eq("R3: exactly 4x passes on an alias term (8 vs 2)", m["id"], 2)
m, _, _ = R.pick([{**serial, "volumes": 34}], "X", 2, own_name=True)
eq("R3 leaves the own-name exemption alone (34 vs 2 passes on the name)", m["id"], 2)
m, _, _ = R.pick([{**serial, "volumes": 13}], "X", 3, own_name=False)
eq("R3: a 3-volume line never had the exemption (13 > 4x 3 rejects on an alias term)", m, None)
# R4 (Weed, 2026-09-24): an exact title match rejected SOLELY by the 4x ceiling binds when nothing
# passed the ceiling -- a short English run of the full Japanese serial (Weed: 3 English volumes of
# the 60-volume Ginga Densetsu Weed). Own-name terms only (R3), never over a ceiling-passing candidate.
m, via, _ = R.pick([{**serial, "volumes": 60}], "X", 3)
eq("R4: an exact primary rejected only by the ceiling binds when nothing else did (60 vs 3)", (m["id"], via), (2, "ceiling"))
m, via, _ = R.pick([{**syn, "volumes": 60}], "X", 3)
eq("R4: an exact synonym rejected only by the ceiling binds too", (m["id"], via), (3, "ceiling"))
m, via, _ = R.pick([{**serial, "volumes": 60}], "X", 3, own_name=False)
eq("R4 never fires on an alias term (R3 keeps the ceiling)", (m, via), (None, None))
m, via, _ = R.pick([{**serial, "id": 31741, "volumes": 33}, {**serial, "id": 147044, "volumes": 4}], "X", 3)
eq("R4 never replaces a candidate that passes the ceiling (Worst-shaped: 4 vols beats 33)", (m["id"], via), (147044, "primary"))
m, via, _ = R.pick([{**syn, "id": 8, "volumes": 60, "popularity": 999}, {**syn, "id": 9, "volumes": 3}], "X", 3)
eq("R4 never outranks a ceiling-passing synonym either", (m["id"], via), (9, "synonym"))
m, via, rej = R.pick([{**serial, "volumes": 60}, {**syn, "id": 9, "volumes": 3}], "X", 3)
eq("R4 never outranks a ceiling-passing synonym carrier, even one R1 rejected: nothing binds",
   (m, via, "9:synonym only (a primary-title candidate is on the page)" in rej), (None, None, True))
m, via, _ = R.pick([{**one_shot, "volumes": 60}], "X", 3)
eq("R4: a ONE_SHOT is never bound, whatever its volumes", (m, via), (None, None))
m, via, _ = R.pick([{**serial, "volumes": 1}, {**syn, "volumes": 60}], "X", 6)
eq("R4 keeps R1: an oversized synonym carrier never wins beside a primary-title candidate",
   (m, via), (None, None))
m, via, _ = R.pick([{**serial, "title": {"english": "X Gaiden"}, "volumes": 60}], "X", 3)
eq("R4 needs exact equality: a longer title rejected on the ceiling stays out", (m, via), (None, None))
# R5 (2026-09-24): no equality anywhere on the page -> ONE candidate whose title key contains the
# term's key (or sits inside it, shorter side >= 4) AND whose volumes equal the line's exactly binds.
# The exact count does the real work: "It's Just Not My Night" (3) is "It's Just Not My Night: Tale
# of a Fallen Vampire Queen" (3); "Ascendance of a Bookworm (Part 2: ...)" (4) is AniList's shorter
# "Ascendance of a Bookworm: Part 2" (4).
sub = {**serial, "id": 50, "volumes": 3, "title": {"english": "Night Shift: Tale of a Vampire"}}
m, via, _ = R.pick([sub], "Night Shift", 3)
eq("R5: the term inside a longer title, exact volumes, unique -> binds", (m["id"], via), (50, "substring"))
m, via, _ = R.pick([{**sub, "title": {"english": "Night Shift"}}], "Night Shift (Part 2: The Dawn)", 3)
eq("R5: a shorter title inside the term (the Bookworm Part N direction) -> binds", (m["id"], via), (50, "substring"))
m, via, _ = R.pick([{**sub, "synonyms": ["Night Shift: Tale"], "title": {"english": "Yakin"}}], "Night Shift", 3)
eq("R5 reads synonyms too", (m["id"], via), (50, "substring"))
eq("R5 never fires on an alias term", R.pick([sub], "Night Shift", 3, own_name=False)[:2], (None, None))
eq("R5 needs a unique candidate: two on the page -> nothing",
   R.pick([sub, {**sub, "id": 51, "title": {"english": "Night Shift Zero"}}], "Night Shift", 3)[:2], (None, None))
eq("R5 needs the exact count: off by one (4 vs 3) -> nothing", R.pick([{**sub, "volumes": 4}], "Night Shift", 3)[:2], (None, None))
eq("R5 needs the exact count: off by one (2 vs 3) -> nothing", R.pick([{**sub, "volumes": 2}], "Night Shift", 3)[:2], (None, None))
eq("R5 never compares null volumes", R.pick([{**sub, "volumes": None}], "Night Shift", 3)[:2], (None, None))
eq("R5: a ONE_SHOT is never bound", R.pick([{**sub, "format": "ONE_SHOT"}], "Night Shift", 3)[:2], (None, None))
eq("R5: the shorter side must be >= 4 characters ('Hou' inside 'Houseki')",
   R.pick([{**sub, "title": {"english": "Houseki"}}], "Hou", 3)[:2], (None, None))
eq("R5 does not fire beside an equal title rejected on volumes (Doll-shaped: the work, a disputed count)",
   R.pick([{**serial, "id": 31566, "volumes": 1}, {**sub, "volumes": 6, "title": {"english": "X: IC in a X"}}], "X", 6)[:2],
   (None, None))
eq("R5 does not fire beside a same-named ONE_SHOT either",
   R.pick([{**one_shot, "title": {"english": "Night Shift"}}, sub], "Night Shift", 3)[:2], (None, None))
m, via, _ = R.pick([{**sub, "title": {"english": "Night Shift"}}, {**sub, "id": 51}], "Night Shift", 3)
eq("R5 never outranks equality: the equal title wins, the substring one is ignored", (m["id"], via), (50, "primary"))
# R7 (2026-09-24): equality after dropping one leading the / a / an from both sides, a tier below
# exact equality ("Hollow Regalia" is AniList's "The Hollow Regalia")
art = {**serial, "id": 70, "title": {"english": "The Night Shift"}}
m, via, _ = R.pick([art], "Night Shift", 20)
eq("R7: 'Night Shift' binds 'The Night Shift'", (m["id"], via), (70, "article"))
m, via, _ = R.pick([{**art, "title": {"english": "Night Shift"}}], "A Night Shift", 20)
eq("R7: the article on the term's side drops too", (m["id"], via), (70, "article"))
m, via, _ = R.pick([art, {**serial, "id": 71, "title": {"english": "Night Shift"}}], "Night Shift", 20)
eq("R7 never outranks exact equality", (m["id"], via), (71, "primary"))
eq("R7: only a whole leading word is an article ('Theater' is not 'the ater')",
   R.pick([{**art, "title": {"english": "Theater Night"}}], "ater Night", 19)[:2], (None, None))
eq("R7 keeps the volume rule (1 vs 20)", R.pick([{**art, "volumes": 1}], "Night Shift", 20)[:2], (None, None))
eq("R7 keeps ONE_SHOT out", R.pick([{**art, "format": "ONE_SHOT"}], "Night Shift", 20)[:2], (None, None))
eq("R7 keeps R1: an article-equal synonym carrier never wins beside an article-equal primary rejected on volumes",
   R.pick([{**art, "volumes": 1}, {**syn, "id": 72, "synonyms": ["The Night Shift"]}], "Night Shift", 20)[:2], (None, None))
m, via, _ = R.pick([{**syn, "id": 72, "synonyms": ["The Night Shift"]}], "Night Shift", 20)
eq("R7 reads synonyms (no primary-title candidate on the page)", (m["id"], via), (72, "article"))
# R7 respects R1 ACROSS tiers (review, 2026-09-24): an exact primary-title candidate on the page -- even
# one rejected on volumes, or a same-named ONE_SHOT -- is the work with a disputed count, so an
# article-equal candidate beside it never binds; and R4 never binds an oversized exact title over an
# article-equal candidate that passes the ceiling
eq("R7 + R1 (Doll-shaped): 'Doll' 1 vol rejected on volumes beside 'The Doll' 6 vols -> nothing",
   R.pick([{**serial, "id": 31566, "volumes": 1, "title": {"english": "Doll"}},
           {**serial, "id": 80, "volumes": 6, "title": {"english": "The Doll"}}], "Doll", 6)[:2], (None, None))
eq("R7 + R1: a 'Doll' ONE_SHOT beside 'The Doll' 6 vols -> nothing",
   R.pick([{**one_shot, "title": {"english": "Doll"}},
           {**serial, "id": 80, "volumes": 6, "title": {"english": "The Doll"}}], "Doll", 6)[:2], (None, None))
eq("R4 + R7: an oversized 'Weed' (60) beside a 3-volume 'The Weed' -> nothing",
   R.pick([{**serial, "id": 34010, "volumes": 60, "title": {"english": "Weed"}},
           {**serial, "id": 81, "volumes": 3, "title": {"english": "The Weed"}}], "Weed", 3)[:2], (None, None))
m, _, _ = R.pick([{**serial, "volumes": None}], "X", 63)
eq("null volumes are never compared", m["id"], 2)
eq("no equality -> no pick, no rejection", R.pick([serial], "Z", 20), (None, None, []))
eq("alias terms: dedupe by key, skip the name and list articles, never capped (only searches are)",
   R.alias_terms("Fairy Tail", ["Fairy Tail", "List of Fairy Tail volumes", "Feari Teiru", "feari teiru",
                                "Fairy Tail (anime)", "Plot of Fairy Tail", "A", "B", "C", "D", "E", "F"]),
   ["Feari Teiru", "Fairy Tail (anime)", "A", "B", "C", "D", "E", "F"])
# the seen seed (2026-09-24, the Fushigi Yugi trace): the exporter's ASCII alias row of an accented
# name ("fushigi y gi") is the name, not a fresh search that burns one of ALIAS_LIMIT's slots
eq("alias terms: the name's stored ASCII normalize() row is skipped",
   R.alias_terms("Fushigi Yûgi", ["Fushigi Yûgi", "fushigi y gi", "Curious Play"]), ["Curious Play"])
from to_mangarr import normalize  # noqa: E402
eq("ascii_normalize() is the exporter's normalize()",
   [R.ascii_normalize(x) for x in ("Fushigi Yûgi", "Let’s Do It!", " Ranma ½ ", "Ⅰ Ａ")],
   [normalize(x) for x in ("Fushigi Yûgi", "Let’s Do It!", " Ranma ½ ", "Ⅰ Ａ")])
eq("deslug: Mangarr's de-slugged foreign id form", R.deslug("Let\u2019s Do It Already!"), "let s do it already")
eq("deslug keeps the name's key", R.key(R.deslug("Re:Zero (The Sanctuary and the Witch of Greed)")),
   R.key("Re:Zero (The Sanctuary and the Witch of Greed)"))
eq("retry order: de-slugged form first, then the aliases",
   R.retry_terms(dict(name="Blue Box", aliases=["Blue Box", "Blue Box (Manga)", "Ao no Hako"])),
   ["blue box", "Blue Box (Manga)", "Ao no Hako"])

def _gap_terms():
    try:
        R.search(["No Such Series XYZ"], False)
    except R.OfflineMiss as e:
        return e.terms
    return "no OfflineMiss raised"


eq("offline: an uncached term raises OfflineMiss naming the term (the replay reports it, never aborts)",
   _gap_terms(), ["No Such Series XYZ"])


def summary():
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILED: {FAILS}")
        sys.exit(1)
    print("all resolve_anilist tests passed")


if __name__ == "__main__":
    summary()
