"""Unit tests for export/resolve_anilist.py. Run: python3 export/test_resolve_anilist.py

Offline: AniList responses were recorded once into export/fixtures/anilist/ (the resolver's
own cache format, so the real request/cache path runs) with
    ANILIST_RECORD=1 python3 export/test_resolve_anilist.py
Re-record only when AniList's data for these entries must be refreshed; the assertions are
the verdicts of Mangarr's 2026-09-15 metadata audit and must keep holding.
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("ANILIST_CACHE", os.path.join(HERE, "fixtures", "anilist"))
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

# ---- the seven audit entries, offline against the recorded fixtures --------
def page(term, novel=False):
    """A recorded page by term; a missing committed fixture is a FAIL line, not a traceback."""
    try:
        return R.search([term], novel)[term]
    except R.OfflineMiss:
        eq("fixture present for the recorded page %r" % term, "missing", "present")
        return []


def line(sid, name, medium, volume_count, aliases):
    return dict(id=sid, name=name, medium=medium, volume_count=volume_count, aliases=list(aliases),
                anilist_id=None, novel=medium in R.NOVEL_MEDIUMS)


# ---- the alias FLOW (Mangarr's AniListService.FindSeries): every alias is ranked against the
# name page for free; only the first ALIAS_LIMIT page-misses cost a fresh search, each ranked
# against its own page; an alias past the search budget still binds from the name page --------
def flow(name, aliases, pages, volume_count=20):
    calls = []
    real = R.search
    R.search = lambda terms, novel: (calls.append(list(terms)), {t: list(pages.get(t, [])) for t in terms})[1]
    try:
        ln = line(1, name, "manga", volume_count, aliases)
        R.resolve([ln])
    finally:
        R.search = real
    return ln, calls


a5 = {**serial, "id": 55, "title": {"english": "A5"}}
ln_, calls = flow("Foo", ["A1", "A2", "A3", "A4", "A5"], {"Foo": [a5]})
eq("flow: the 5th alias binds from the name page after the 3 searches are spent (A4 page-ranked only)",
   (ln_["pick"]["id"], ln_["via"], ln_["term"], ln_["searches"], calls),
   (55, "alias", "A5", 3, [["Foo"], ["foo"], ["A1"], ["A2"], ["A3"]]))
a2 = {**serial, "id": 22, "title": {"english": "A2"}}
ln_, calls = flow("Foo", ["A1", "A2", "A3"], {"A1": [a2]})
eq("flow: a fresh page is ranked for its own term only, then the walk continues on the name page",
   (ln_["pick"], calls), (None, [["Foo"], ["foo"], ["A1"], ["A2"], ["A3"]]))
ln_, calls = flow("Foo", ["A1", "A2"], {"A2": [a2]})
eq("flow: a fresh-search hit binds via alias with the searched term",
   (ln_["pick"]["id"], ln_["via"], ln_["term"], ln_["searches"]), (22, "alias", "A2", 2))
ln_, calls = flow("Foo", ["A1", "List of Foo volumes", "foo", "A1"], {})
eq("flow: list articles, the name's own key and duplicates never cost a search",
   (ln_["pick"], ln_["searches"], calls), (None, 1, [["Foo"], ["foo"], ["A1"]]))
big = {**serial, "id": 77, "volumes": 34, "title": {"english": "A1"}}
ln_, calls = flow("Foo", ["A1"], {"Foo": [big]}, volume_count=2)
eq("flow: R3 on the page-rank -- a 2-volume line's alias keeps the 4x ceiling against the name page",
   (ln_["pick"], calls), (None, [["Foo"], ["foo"], ["A1"]]))

# R6 (2026-09-24): the name without a trailing edition-qualifier parenthetical is a retry term after
# the de-slugged form, ranked like an alias (R3): "Inuyasha (VizBig edition)" -> "Inuyasha", but
# "Sailor Moon (Shinsōban short stories)" (2 vols) must not bind the 18-volume serial through the
# bare "Sailor Moon" -- the R3 failure again (its own entry is "Sailor Moon Short Stories", 2 vols).
eq("R6: edition qualifier stripped", R.edition_stripped("Inuyasha (VizBig edition)"), "Inuyasha")
eq("R6: version / release / tankobon / 2-in-1 are qualifiers",
   [R.edition_stripped(n) for n in ("Yo-kai Watch (Noriyuki Konishi version)", "Tomie (Original release)",
                                    "Arata: The Legend (Tank\u014dbon edition)", "Foo (2-in-1)", "Foo (Second printing)",
                                    "Foo (Shins\u014dban)", "Foo (English-language volume list)")],
   ["Yo-kai Watch", "Tomie", "Arata: The Legend", "Foo", "Foo", "Foo", "Foo"])
eq("R6: an unclosed outer parenthetical goes too",
   R.edition_stripped("Ranma \u00bd (2014 English release (2-in-1 Edition)"), "Ranma 1/2")   # for_search()'s numeric fold
eq("R6: never an arc, a chapter list, a nested series or a plain subtitle",
   [R.edition_stripped(n) for n in ("Re:Zero (Truth of Zero)", "The Wallflower (Chapter and volume list)",
                                    "Foo (Manga series (2010 edition))", "Restaurant to Another World (First series)",
                                    "Weed", "(Deluxe edition)")],
   [None, None, None, None, None, None])
eq("R6: never a parenthetical that quotes another work's title (straight or curly quotes)",
   [R.edition_stripped(n) for n in ('Amazing Agent Luna ("Amazing Agent Jennifer" Volume list)',
                                    "Amazing Agent Luna (\u201cAmazing Agent Jennifer\u201d Volume list)")],
   [None, None])
eq("R6: an apostrophe is not a quotation mark", R.edition_stripped("Marmalade Boy (Collector's edition)"), "Marmalade Boy")
# R6+ (round 2, 2026-09-24): Wikipedia's collection / list-article headings, an unclosed trailing
# parenthetical and a bare trailing "volumes" heading; "(@comic volumes)" is a spin-off, not an edition
eq("R6+: omnibus / perfect collection / publication / list of / manga list / overview / original manga / "
   "bunko / aizoban / kanzenban / deluxe / volumes are qualifiers",
   [R.edition_stripped("Foo (%s)" % q) for q in ("Omnibus", "Perfect Collection", "English publication", "List of books",
                                                 "Manga List", "Overview", "Original manga", "Bunko", "Aizōban",
                                                 "Kanzenban", "Deluxe", "Dark Horse volumes")], ["Foo"] * 12)
eq("R6+: an unclosed trailing parenthetical goes (Saiyuki (Enix Edition)",
   [R.edition_stripped(n) for n in ("Saiyuki (Enix Edition", "Jihai (Manga (volumes)")], ["Saiyuki", "Jihai"])
eq("R6+: a bare trailing 'volumes' / 'volume list' heading goes, only without parentheses",
   [R.edition_stripped(n) for n in ("Gunsmith Cats Burst volumes", "Blue Lock: Episode Nagi volumes", "Days volume list",
                                    '"Amazing Agent Luna" Volume list', "Foo (Bar) volumes")],
   ["Gunsmith Cats Burst", "Blue Lock: Episode Nagi", "Days", "Amazing Agent Luna", None])
eq("R6+ keeps the guards: '@comic volumes', a chapter list, a nested series (even unspaced after the fold), an arc",
   [R.edition_stripped(n) for n in ("My Youth Romantic Comedy Is Wrong, As I Expected (@comic volumes)",
                                    "Foo (Chapter and volume list)", "The Kindaichi Case Files (File series (27 volumes/19 files)",
                                    "A Certain Magical Index: New Testament (2011–2019", "Re:Zero (Truth of Zero)")],
   [None] * 5)
eq("retry order: de-slugged form, then the edition-stripped name, then the aliases",
   R.retry_terms(dict(name="Blue Box (VizBig edition)", aliases=["Ao no Hako"])),
   ["blue box vizbig edition", "Blue Box", "Ao no Hako"])
inu = {**serial, "id": 30676, "volumes": 56, "title": {"english": "Foo"}}
ln_, calls = flow("Foo (VizBig edition)", ["A1"], {"Foo": [inu]}, volume_count=18)
eq("flow R6: the edition-stripped name is searched after the de-slugged form and binds via alias",
   ((ln_["pick"] or {}).get("id"), ln_["via"], ln_["term"], calls),
   (30676, "alias", "Foo", [["Foo (VizBig edition)"], ["foo vizbig edition"], ["Foo"]]))
serial18 = {**serial, "id": 30092, "volumes": 18, "title": {"english": "Foo"}}
short2 = {**serial, "id": 38552, "volumes": 2, "title": {"english": "Foo Short Stories"}}
ln_, calls = flow("Foo (Shins\u014dban short stories)", [], {"Foo": [serial18, short2]}, volume_count=2)
eq("flow R6 keeps R3: a 2-volume line never binds the 18-volume serial through the stripped name",
   (ln_["pick"], "30092:volumes 18 > 4x 2" in ln_["rejected"]), (None, True))
ln_, calls = flow("Foo (Collector's edition)", [], {}, volume_count=5)
eq("flow R6: a stripped term with an empty page costs one search and binds nothing",
   (ln_["pick"], calls), (None, [["Foo (Collector's edition)"], ["foo collector s edition"], ["Foo"]]))

fb = {**serial, "id": 90, "volumes": 20, "title": {"english": "Foob Zero: The Beginning"}}
ln_, calls = flow("Foob Zero", [], {"foob zero": [fb]}, volume_count=20)
eq("flow: an R5 bind on the de-slugged page is reported as its tier, not 'alias'",
   ((ln_["pick"] or {}).get("id"), ln_["via"], ln_["term"]), (90, "substring", "foob zero"))


# ---- the POST-WALK tiers (post_walk(), 2026-09-24 round 2): only a line the whole walk left
# unbound, only the pages the walk already fetched (zero new queries), V1 -> V2 -> V3 -> V4 ---------
def pw(name, vc, orig, pages, medium="manga"):
    ln = line(1, name, medium, vc, [])
    ln["orig_vc"] = orig
    return R.post_walk_pick(ln, pages)[:2]


def pwid(name, vc, orig, pages, medium="manga"):
    m, via = pw(name, vc, orig, pages, medium)
    return ((m or {}).get("id"), via)


tail = {**serial, "id": 60, "volumes": None, "title": {"english": "Night Shift: Tale of a Vampire"}}
# V1 prefix
eq("V1: a bare name that heads AniList's full title binds (null volumes)",
   pwid("Night Shift", 5, None, [("Night Shift", [tail], True)]), (60, "prefix"))
eq("V1: word boundary ('Night Shifts ...' is not 'Night Shift' + a subtitle)",
   pw("Night Shift", 5, None, [("Night Shift", [{**tail, "title": {"english": "Night Shifts Forever"}}], True)]), (None, None))
eq("V1: gate -- a line of 1-2 volumes never binds by prefix",
   pw("Night Shift", 2, None, [("Night Shift", [tail], True)]), (None, None))
eq("V1: bare names only -- a parenthetical or a cut in the name is out",
   [pw(n, 5, None, [(n, [tail], True)]) for n in ("Night Shift (Omnibus)", "Night Shift: Dawn")], [(None, None)] * 2)
eq("V1: nothing title-equal on the page, even a rejected one (1 vol vs 5)",
   pw("Night Shift", 5, None, [("Night Shift", [tail, {**serial, "id": 61, "volumes": 1, "title": {"english": "Night Shift"}}], True)]),
   (None, None))
eq("V1: AniList's count may not be smaller than the line's (3 vs 5)",
   pw("Night Shift", 5, None, [("Night Shift", [{**tail, "volumes": 3}], True)]), (None, None))
eq("V1: own-name pages only (an alias page is out)", pw("Night Shift", 5, None, [("Night Shift", [tail], False)]), (None, None))
eq("V1: the term's key must be >= 6 characters", pw("Night", 5, None, [("Night", [{**tail, "title": {"english": "Night: X"}}], True)]),
   (None, None))
eq("V1: never a ONE_SHOT", pw("Night Shift", 5, None, [("Night Shift", [{**tail, "format": "ONE_SHOT"}], True)]), (None, None))
# V2 arc
arc_c = {**serial, "id": 62, "volumes": 11, "title": {"english": "Foob Chapter 3: Truth of Foob"}}
eq("arc_parts: base before the first cut, arc without its parentheses; an edition qualifier is no arc",
   [R.arc_parts(n) for n in ("Re:Zero (Truth of Zero)", "Mars: Horse With No Name", "Jiraishin (English Tokyopop release)", "Foo")],
   [("Re:Zero", "Truth of Zero"), ("Mars", "Horse With No Name"), ("Jiraishin", None), ("Foo", None)])
eq("V2: base AND arc inside one title, AniList count = the line's",
   pwid("Foob (Truth of Foob)", 11, None, [("Foob (Truth of Foob)", [arc_c], True)]), (62, "arc"))
eq("V2: ... or = the (different) origin line's (3 English, 6 Japanese)",
   pwid("Foob (Truth of Foob)", 3, 6, [("Foob (Truth of Foob)", [{**arc_c, "volumes": 6}], True)]), (62, "arc"))
eq("V2: any other count, or a null one, binds nothing",
   [pw("Foob (Truth of Foob)", 11, None, [("x", [{**arc_c, "volumes": v}], True)]) for v in (10, None)], [(None, None)] * 2)
eq("V2: the arc part is mandatory -- base-only containment never binds",
   pw("Foob (Truth of Foob)", 11, None, [("x", [{**arc_c, "title": {"english": "Foob Diablo"}}], True)]), (None, None))
eq("V2: unique candidate only",
   pw("Foob (Truth of Foob)", 11, None, [("x", [arc_c, {**arc_c, "id": 63}], True)]), (None, None))
# V3 amp
amp_c = {**serial, "id": 64, "volumes": 3, "title": {"english": "Kiss and Fly"}}
eq("V3: '&' in the term = 'and' in a primary title", pwid("Kiss & Fly", 3, None, [("Kiss & Fly", [amp_c], True)]), (64, "amp"))
eq("V3: 'and' in the term = '&' in a primary title",
   pwid("Kiss and Fly", 3, None, [("Kiss and Fly", [{**amp_c, "title": {"english": "Kiss & Fly"}}], True)]), (64, "amp"))
eq("V3: primary titles only -- a synonym carrier never binds (Shino & Ren's '...: Future')",
   pw("Kiss & Fly", 2, None, [("Kiss & Fly", [{**amp_c, "title": {"english": "Kiss & Fly: Future"}, "synonyms": ["Kiss and Fly"]}], True)]),
   (None, None))
eq("V3: never beside an exact title (a rejected one included)",
   pw("Kiss & Fly", 3, None, [("Kiss & Fly", [amp_c, {**serial, "id": 65, "volumes": 30, "title": {"english": "Kiss & Fly"}}], True)]),
   (None, None))
eq("V3 keeps the volume rule (1 vs 20)", pw("Kiss & Fly", 20, None, [("Kiss & Fly", [{**amp_c, "volumes": 1}], True)]), (None, None))
# V4 origin
ori = {**serial, "id": 66, "volumes": 19, "title": {"english": "Bar"}}
eq("V4: a retry term's equal title rejected only by the ceiling, AniList count = the origin line's",
   pwid("Bar (English release)", 3, 19, [("Bar (English release)", [], True), ("Bar", [ori], False)]), (66, "origin"))
eq("V4: never on the name page", pw("Bar", 3, 19, [("Bar", [ori], True)]), (None, None))
eq("V4: gate -- a line of 1-2 volumes never binds (Angel Beats! Related media)",
   pw("Bar (English release)", 2, 19, [("x", [], True), ("Bar", [ori], False)]), (None, None))
eq("V4: the count must be the origin line's (18 vs 19)",
   pw("Bar (English release)", 3, 19, [("x", [], True), ("Bar", [{**ori, "volumes": 18}], False)]), (None, None))
eq("V4: only a count past the ceiling (10 <= 4x 3 would have passed the volume rule)",
   pw("Bar (English release)", 3, 10, [("x", [], True), ("Bar", [{**ori, "volumes": 10}], False)]), (None, None))
_db = sqlite3.connect(":memory:")
_db.execute("CREATE TABLE series (gcd_series_id INTEGER, name TEXT, medium TEXT, volume_count INTEGER, anilist_id INTEGER, orig_series_id INTEGER)")
_db.execute("CREATE TABLE series_alias (gcd_series_id INTEGER, alias TEXT)")
_db.executemany("INSERT INTO series VALUES (?,?,?,?,?,?)",
                [(1, "Bar (English release)", "manga", 3, None, 2), (2, "Bar", "manga", 19, None, 2), (3, "Baz", "manga", 4, None, None)])
eq("load_line: orig_vc is the origin line's count, never the line's own (a JP line is its own origin)",
   [R.load_line(_db, i)["orig_vc"] for i in (1, 2, 3)], [19, None, None])
# the walk: post_walk() adds no search and never pre-empts a walk tier
ln_, calls = flow("Night Shift", ["A1"], {"Night Shift": [tail]}, volume_count=5)
eq("flow post-walk: binds by prefix after the whole walk, with exactly the walk's searches",
   ((ln_["pick"] or {}).get("id"), ln_["via"], calls), (60, "prefix", [["Night Shift"], ["night shift"], ["A1"]]))
ln_, calls = flow("Night Shift", ["Yakin"], {"Night Shift": [tail], "Yakin": [{**serial, "id": 67, "title": {"english": "Yakin"}}]},
                  volume_count=5)
eq("flow post-walk: an alias bind of the walk wins over a prefix candidate on the name page",
   ((ln_["pick"] or {}).get("id"), ln_["via"]), (67, "alias"))


# ---- the DISPLAY-ONLY fallback (display(), 2026-09-24): never a binding ---------------------
def display_db(rows, pages):
    """In-memory artifact rows (sid, name, language, medium, volume_count, anilist_id, work);
    search() answers from pages[(term, novel)] and records every term it is asked for."""
    db = sqlite3.connect(":memory:")
    db.execute("""CREATE TABLE series (gcd_series_id INTEGER PRIMARY KEY, name TEXT, language TEXT,
                  medium TEXT, volume_count INTEGER, anilist_id INTEGER, tome_work_id TEXT,
                  display_anilist_id INTEGER, display_anilist_via TEXT)""")
    db.executemany("INSERT INTO series VALUES (?,?,?,?,?,?,?,NULL,NULL)", rows)
    db.execute("UPDATE series SET display_anilist_id=999, display_anilist_via='parent' WHERE gcd_series_id=9")
    asked, real = [], R.search
    R.search = lambda terms, novel: (asked.append((sorted(terms), novel)),
                                     {t: list(pages.get((t, novel), [])) for t in terms})[1]
    try:
        by = R.display(db)
    finally:
        R.search = real
    got = {sid: (aid, via) for sid, aid, via in db.execute(
        "SELECT gcd_series_id, display_anilist_id, display_anilist_via FROM series WHERE display_anilist_id IS NOT NULL")}
    ids = dict(db.execute("SELECT gcd_series_id, anilist_id FROM series"))
    return by, got, ids, asked


eq("parent_name: the first ' (' / ': ' / ' - ' / ' / ' cut, en dash as ' - ', None without one",
   [R.parent_name(n) for n in ("Re:Zero (Truth of Zero)", "Foo: Bar (Baz)", "Foo – Bar", "Foo / Bar",
                               "Re:Zero", "Bungo Stray Dogs")],
   ["Re:Zero", "Foo", "Foo", "Foo", None, None])
adapt = {**serial, "id": 700, "volumes": None, "title": {"english": "Novela"}}
by, got, ids, asked = display_db([
    (1, "Foo", "en", "light_novel", 20, 100, "w1"),            # bound parent (a novel)
    (2, "Foo (Truth of Foo)", "en", "manga", 3, None, "w1"),    # arc, other medium -> parent 100
    (3, "Foo: Side Story", "en", "manga", 2, None, "w2"),       # same name, OTHER work -> nothing
    (4, "Bar", "en", "manga", 10, 200, "w3"),
    (5, "Bar", "en", "light_novel", 10, 201, "w3"),
    (6, "Bar (Episode Lyu)", "en", "manga", 3, None, "w3"),     # two bound 'Bar' ids -> ambiguous
    (7, "Novela", "en", "novel", 4, None, "w4"),               # medium: AniList has the adaptation
    (8, "Novela", "en", "manga", 4, None, "w5"),               # a manga line never gets 'medium'
    (9, "Pinned (Arc)", "en", "manga", 3, 555, "w6"),          # bound (a pin): a stale display id goes
    (10, "Foo (Truth of Foo)", "fr", "manga", 3, None, "w1"),  # never a non-EN line
    (11, "Twin", "en", "light_novel", 20, None, "w7"),         # its novel page has an equal NOVEL entry
    (12, "Twin", "en", "manga", 3, 300, "w7"),                 # rejected (1 vs 20): no 'medium'; no cut, no parent
], {("Novela", False): [adapt], ("Twin", True): [{**serial, "id": 301, "format": "NOVEL", "volumes": 1,
                                                  "title": {"english": "Twin"}}],
    ("Twin", False): [{**serial, "id": 300, "volumes": None, "title": {"english": "Twin"}}]})
eq("display: parent across mediums in the same work, medium for the novel only, nothing else",
   (got, by), ({2: (100, "parent"), 7: (700, "medium")}, {"parent": 1, "medium": 1}))
eq("display: anilist_id is never written", ids,
   {1: 100, 2: None, 3: None, 4: 200, 5: 201, 6: None, 7: None, 8: None, 9: 555, 10: None, 11: None, 12: 300})
eq("display: one search per page family, only the unbound EN novel lines without a parent candidate",
   asked, [(["Novela", "Twin"], True), (["Novela", "Twin"], False)])


MUSHOKU_ALIASES = [
    "Mushoku Tensei", "Jobless Reincarnation", "List of Mushoku Tensei volumes",
    "Mushoku Tensei: Jobless Reincarnation", "mushoku tensei jobless reincarnation",
    "Liste des chapitres de Mushoku Tensei"]
REZERO4_ALIASES = [
    "Re:Zero (The Sanctuary and the Witch of Greed)", "re zero the sanctuary and the witch of greed",
    "The Sanctuary and the Witch of Greed", "List of Re:Zero volumes", "list of re zero volumes", "List of Re",
    "Re:Zero", "re zero", "Memory Snow", "Re: Life in a Different World from Zero",
    "re life in a different world from zero", "Re: Zero", "Re:ZERO -Starting Life in Another World-",
    "re zero starting life in another world", "Re:Zero - Starting Life in Another World",
    "Re:Zero -Starting Life in Another World-: Death or Kiss",
    "re zero starting life in another world death or kiss", "Re:Zero kara Hajimeru Isekai Seikatsu",
    "re zero kara hajimeru isekai seikatsu", "Re:Zero kara Hajimeru Isekai Seikatsu: Memory Snow",
    "re zero kara hajimeru isekai seikatsu memory snow", "Re:Zero − Starting Life in Another World",
    "Re:Zero − Starting Life in Another World: Memory Snow",
    "re zero starting life in another world memory snow", "Re:Zreo", "re zreo", "Re:ゼロ", "re",
    "Re:ゼロから始める異世界生活", "Rezero",
    "Re：ゼロから始める異世界生活",
    "Liste des chapitres de Re:Zero − Re:vivre dans un autre monde à partir de zéro",
    "liste des chapitres de re zero re vivre dans un autre monde partir de z ro", "Liste des chapitres de Re",
    "Re:Zero − Re:vivre dans un autre monde à partir de zéro",
    "re zero re vivre dans un autre monde partir de z ro"]

SEVEN = [
    # (line, audited id, how the rules reach it)
    (line(148860797, "Fairy Tail", "manga", 63, ["Fairy Tail", "Feari Teiru"]), 30598, "primary"),
    (line(1121851499, "Black Clover", "manga", 37, ["Black Clover"]), 86123, "primary"),
    (line(448804592, "Blue Box", "manga", 22, ["Blue Box", "Ao no Hako"]), 132182, "primary"),
    (line(338575746, "Let's Do It Already!", "manga", 9, ["Let's Do It Already!"]), 120768, "primary"),
    (line(799116509, "Mushoku Tensei", "manga", 24, MUSHOKU_ALIASES), 85564, "alias"),
    (line(1237487995, "Re:Zero (The Sanctuary and the Witch of Greed)", "manga", 11, REZERO4_ALIASES), 112218, "alias"),
    (line(513287112, "Sword Art Online", "light_novel", 28, ["Sword Art Online", "Aincrad"]), 51479, "primary"),
]
seven = [c[0] for c in SEVEN]
try:
    R.resolve(seven)
except R.OfflineMiss as e:   # committed fixtures: a gap here is a repo defect, a FAIL not a traceback
    eq("fixtures cover the seven audit entries", "gap for %s" % ", ".join(map(repr, e.terms)), "ok")
    for ln in seven:
        ln.setdefault("pick", None); ln.setdefault("via", None); ln.setdefault("rejected", [])
for ln, want, want_via in SEVEN:
    got = ln["pick"]["id"] if ln["pick"] else None
    eq(f"{ln['name']} -> {want} via {want_via}", (got, ln["via"]), (want, want_via))
ft = seven[0]
eq("Fairy Tail: the anthology 128087 is rejected on volumes (1 vs 63)",
   any(r.startswith("128087:volumes") for r in ft["rejected"]), True)
eq("Black Clover: the one-shot 114652 is rejected as ONE_SHOT", "114652:ONE_SHOT" in seven[1]["rejected"], True)
eq("Blue Box: the one-shot 122342 is rejected as ONE_SHOT", "122342:ONE_SHOT" in seven[2]["rejected"], True)
# the recorded `Doll` and `Pupa` pages (the 2026-09-15 live run's two wrong binds under the rules
# before R1/R2): Doll (6-volume line) must stay unresolved -- "DOLL" 31566 (1 vol) falls to the volume
# rule and the 4-volume 128084 "Onegai, Sore wo Yamenaide" only carries "Doll" as a synonym; the right
# entry 30298 "DOLL: IC in a Doll" never key-equals "doll". Pupa (volume_count 1) binds the 5-volume
# serial 75613 over the 1-volume synonym carrier 191157 "Niku Yawame Mitsu Koime".
m, via, rej = R.pick(page("Doll"), "Doll", 6)
eq("Doll page: unresolved; 31566 rejected on volumes, 128084 rejected as synonym-only",
   (m, via, "31566:volumes 1 vs 6" in rej, "128084:synonym only (a primary-title candidate is on the page)" in rej),
   (None, None, True, True))
m, via, rej = R.pick(page("Pupa"), "Pupa", 1)
eq("Pupa page: 75613 via primary (5 vols vs a 1-volume line, no ceiling); 191157 rejected as synonym-only",
   ((m or {}).get("id"), via, "191157:synonym only (a primary-title candidate is on the page)" in rej), (75613, "primary", True))
# the recorded `Shingeki no Kyojin` page + the full Harsh Mistress line (the 2026-09-15 live run's
# one R2 side effect): the 2-volume spin-off's third alias is the bare franchise name, and only R3
# keeps the 34-volume 53390 out; the line's own name and de-slugged form find nothing, so it stays
# NULL (its own AniList entry carries no title the catalogue's names key-equal)
m, via, rej = R.pick(page("Shingeki no Kyojin"), "Shingeki no Kyojin", 2, own_name=False)
eq("Shingeki no Kyojin page as an alias of a 2-volume line: 53390 rejected past the ceiling",
   (m, "53390:volumes 34 > 4x 2" in rej), (None, True))
hm = line(80957137, "Attack on Titan: Harsh Mistress of the City", "manga", 2,
          ["Attack on Titan: Harsh Mistress of the City", "attack on titan harsh mistress of the city",
           "Shingeki no Kyojin: Kakuzetsu Toshi no Joō", "shingeki no kyojin kakuzetsu toshi no jo", "Shingeki no Kyojin",
           "L'Attaque des Titans: Hope of the City", "l attaque des titans hope of the city", "L'Attaque des Titans",
           "l attaque des titans", "進撃の巨人 隔絶都市の女王"])
R.resolve([hm])
eq("Harsh Mistress of the City resolves to nothing, never 53390", (hm["pick"], hm["via"]), (None, None))
# the recorded `Weed` and `Worst` pages (the opentome-2026-09-24 wrong binds): Weed (3 EN volumes)
# has only oversized exact matches on its name page -- 34010 "Ginga Densetsu WEED" (60 vols, synonym
# "WEED") and the 30-volume Orion spin-off, which never key-equals "weed" -- so R4 binds 34010. Worst
# (3 EN volumes) has 147044 "Worst" (4 vols) passing the ceiling, so R4 must NOT move it to 31741 (33
# vols, the right work) -- that one is corrections/anilist.json's pin, not a rule.
m, via, rej = R.pick(page("Weed"), "Weed", 3)
eq("Weed page: 34010 via the ceiling tier (synonym WEED); 45785 Orion rejected past the ceiling, never bound",
   ((m or {}).get("id"), via, "45785:volumes 30 > 4x 3" in rej), (34010, "ceiling", True))
m, via, _ = R.pick(page("Weed"), "Weed", 3, own_name=False)
eq("Weed page as an alias term: nothing (R3)", (m, via), (None, None))
m, via, _ = R.pick(page("Worst"), "Worst", 3)
eq("Worst page: 147044 stays (it passes the ceiling); R4 does not fire", ((m or {}).get("id"), via), (147044, "primary"))
wd = line(1868367905, "Weed", "manga", 3, ["Weed", "Ginga Dendetsu Weed", "Ginga Densetsu WEED"])
R.resolve([wd])
eq("Weed line: binds 34010 from its name page, before any alias search",
   ((wd["pick"] or {}).get("id"), wd["via"], wd["term"]), (34010, "ceiling", "Weed"))

# the recorded Ascendance of a Bookworm light-novel pages (R5, both directions): AniList lists the
# novel per Part, so the base line (3 volumes) is "Part 1" (87383, 3 vols) and the catalogue's
# "(Part 2: Apprentice Shrine Maiden)" line (4) is the SHORTER "Ascendance of a Bookworm: Part 2"
# (110800, 4). Every Part is on the base page; only the exact count picks one.
m, via, _ = R.pick(page("Ascendance of a Bookworm", novel=True), "Ascendance of a Bookworm", 3)
eq("Bookworm page: the 3-volume base line binds Part 1 (87383) by its exact count", ((m or {}).get("id"), via), (87383, "substring"))
m, via, _ = R.pick(page("Ascendance of a Bookworm", novel=True), "Ascendance of a Bookworm", 6)
eq("Bookworm page: a count no Part has (6) binds nothing", (m, via), (None, None))
t2 = "Ascendance of a Bookworm (Part 2: Apprentice Shrine Maiden)"
m, via, _ = R.pick(page(t2, novel=True), t2, 4)
eq("Bookworm Part 2 page: 110800 'Ascendance of a Bookworm: Part 2' (shorter than the term)", ((m or {}).get("id"), via), (110800, "substring"))

m, via, _ = R.pick(page("Hollow Regalia", novel=True), "Hollow Regalia", 6)
eq("Hollow Regalia page: 133016 'The Hollow Regalia' via the article tier (R7)", ((m or {}).get("id"), via), (133016, "article"))

# the recorded post-walk pages (round 2, 2026-09-24): the measured binds and the analyst's negatives
own = lambda t, novel=False: (t, page(t, novel), True)
retry = lambda t, novel=False: (t, page(t, novel), False)
eq("V1 recorded: Even Dogs Go to Other Worlds (6) -> 133396 '...: Life in Another World with My Beloved Hound'",
   pwid("Even Dogs Go to Other Worlds", 6, 7, [own("Even Dogs Go to Other Worlds")]), (133396, "prefix"))
eq("V1 recorded: Kase-san (10) binds nothing -- two titles start 'Kase-san ...', counted BEFORE the volume rule",
   pw("Kase-san", 10, 10, [own("Kase-san")]), (None, None))
eq("V1 recorded: (after the volume rule only 'Kase-san and Yamada' would be left -- the wrong bind)",
   [m["id"] for m in page("Kase-san") if R.volumes_pass(m, 10, True)
    and any(R._words(x).startswith("kase san ") for x in R._titles(m))], [98777])
eq("V1 recorded: Your Name (novel, 2) binds nothing -- the gate, and 'Another Side: Earthbound' (1) is smaller than the line",
   [pw("Your Name", vc, 2, [own("Your Name", True)], "novel") for vc in (2, 3)], [(None, None)] * 2)
eq("V1/V3 recorded: Shino & Ren (LN, 1) binds nothing -- 189694 'Shino & Ren: Future' (synonym 'Shino and Ren')",
   pw("Shino & Ren", 1, 2, [own("Shino & Ren", True)], "light_novel"), (None, None))
eq("V2 recorded: Umineko (Alliance of the Golden Witch) (3) -> 46144 Episode 4 (6 = the JP line's 6)",
   pwid("Umineko When They Cry (Alliance of the Golden Witch)", 3, 6,
        [own("Umineko When They Cry (Alliance of the Golden Witch)")]), (46144, "arc"))
eq("V2 recorded: Madoka Magica (Side Story) (8, JP 13) binds nothing -- Magia Record has no count",
   pw("Puella Magi Madoka Magica (Side Story)", 8, 13, [own("Puella Magi Madoka Magica (Side Story)")]), (None, None))
eq("V2 recorded: Index NT (LN 6, JP 22) never binds the 22-volume Index 42854 on the base page (the arc is mandatory)",
   pw("A Certain Magical Index: New Testament (2011–2019", 6, 22, [retry("A Certain Magical Index", True)], "light_novel"),
   (None, None))
eq("V3 recorded: Sword Art Online: Kiss & Fly (3) -> 117061 'Sword Art Online: Kiss and Fly'",
   pwid("Sword Art Online: Kiss & Fly", 3, 3, [own("Sword Art Online: Kiss & Fly")]), (117061, "amp"))
eq("V3 recorded: Ghost & Witch (3) -> 139107 'Ghost and Witch'", pwid("Ghost & Witch", 3, 3, [own("Ghost & Witch")]), (139107, "amp"))
jir = [own("Jiraishin (English Tokyopop release)"), retry("Jiraishin")]
eq("V4 recorded: Jiraishin (English Tokyopop release) (3, JP 19) -> 30379 'Jiraishin' (19), never Jiraishin Diablo 40444 (3)",
   pwid("Jiraishin (English Tokyopop release)", 3, 19, jir), (30379, "origin"))
eq("V2 recorded: ... and V2 alone never binds Diablo (the edition-qualified name has no arc)",
   pw("Jiraishin (English Tokyopop release)", 3, None, jir), (None, None))
eq("V4 recorded: Crayon Shin-chan - English - CMX (11, JP 50) -> 32435 (50) on the alias page 'Crayon Shin Chan'",
   pwid("Crayon Shin-chan - English - CMX", 11, 50, [own("Crayon Shin-chan - English - CMX"), retry("Crayon Shin Chan")]),
   (32435, "origin"))
eq("V4 recorded: Angel Beats! (Related media) (1, JP 11) never binds 49671 Heaven's Door (the gate)",
   pw("Angel Beats! (Related media)", 1, 11,
      [own("Angel Beats! (Related media)"), retry("Angel Beats! Heaven's Door")]), (None, None))

# the `Re:Zero` search page itself (recorded): three entries carry the synonym `ReZero`; only the
# arc with an unknown volume count survives the one-sided rule against the line's 11
m, via, rej = R.pick(page("Re:Zero"), "Re:Zero", 11)
eq("Re:Zero page: 112218 via synonym; chapter 2 (5 vols) and Kenki Renka (4 vols) rejected vs 11",
   ((m or {}).get("id"), via, {"85814", "110174"} <= {r.split(":")[0] for r in rej if "volumes" in r}), (112218, "synonym", True))

# ---- the 44 audited lines of the current build: no pick may move off its audited id -----
# (D9: a line already right stays right; a line the rules cannot reach stays NULL, never wrong)
AUDITED = {
    1688349463: 116401, 869082368: 180422, 1614839810: 53390, 235198204: 30002, 1121851499: 86123,
    448804592: 132182, 147190835: 105778, 435248217: 132029, 101154347: 87216, 1671491179: 69325,
    148860797: 30598, 597781225: 86310, 977985946: 118586, 1286632839: 72451, 1546561395: 101517,
    1391365692: 86635, 1247831263: 177806, 1966333010: 120760, 338575746: 120768, 1067107183: 147329,
    799116509: 85564, 464492586: 101583, 921676189: 85486, 731149751: 97842, 106977862: 85736,
    1916098245: 85814, 1014345923: 87259, 686054964: 118370, 1237487995: 112218, 806218467: 105398,
    513287112: 51479, 85713403: 82277, 764941466: 114613, 844542616: 114614, 1987129149: 131644,
    466915185: 86399, 1373146654: 99022, 1528562038: 140475, 448083641: 63327, 1435036878: 30642,
    1867685718: 110218, 647305486: 98263, 1852909690: 117195, 471915974: 97337,
}
# ---- KR/CN works without an English comic line (the lift, 2026-10-01) ----------------------------------
# Synthetic pages in a temporary cache (the resolver's own format): the country filter is AniList's, so offline
# what is tested is that a krcn-<country> family never reads another family's page, and the rules on top of it.
import json, tempfile  # noqa: E402
eq("krcn query: countryOfOrigin, type MANGA, format_not NOVEL", all(x in R._search_query(1, False, "KR") for x in (
    'countryOfOrigin: "KR"', "type: MANGA", "format_not: NOVEL")), True)
eq("krcn query: no country filter on the existing families", "countryOfOrigin" in R._search_query(1, False), False)
eq("krcn cache family: krcn-KR in the file name, a hash of its own",
   (os.path.basename(R._cache_path("search", "krcn-KR", "Phantom")).startswith("search-krcn-KR-phantom-"),
    R._cache_path("search", "krcn-KR", "Phantom") != R._cache_path("search", "manga", "Phantom")), (True, True))
lune = {"id": 6001, "format": "MANGA", "volumes": 60, "popularity": 5, "status": "FINISHED",
        "title": {"english": "Lune Rouge"}, "synonyms": []}
eq("R4 still binds on the existing families (ceiling)", R.pick([lune], "Lune Rouge", 3)[:2], (lune, "ceiling"))
eq("R4 off for the KR/CN works (fallback=False)", R.pick([lune], "Lune Rouge", 3, fallback=False)[0], None)
sub = {"id": 6101, "format": "MANGA", "volumes": 3, "popularity": 5, "status": "FINISHED",
       "title": {"english": "Lune Rouge: Le Retour"}, "synonyms": []}
eq("R5 still binds on the existing families (substring)", R.pick([sub], "Lune Rouge", 3)[:2], (sub, "substring"))
eq("R5 off for the KR/CN works", R.pick([sub], "Lune Rouge", 3, fallback=False)[0], None)
art = {"id": 6201, "format": "MANGA", "volumes": None, "popularity": 5, "status": "FINISHED",
       "title": {"english": "The Red Moon"}, "synonyms": []}
eq("R7 stays on for the KR/CN works (article)", R.pick([art], "Red Moon", 4, fallback=False)[:2], (art, "article"))
pre = {"id": 6301, "format": "MANGA", "volumes": 5, "popularity": 5, "status": "FINISHED",
       "title": {"english": "Even Dogs Go: Life With My Hound"}, "synonyms": []}
pln = {"name": "Even Dogs Go", "volume_count": 3, "orig_vc": None}
eq("V1 still binds on the existing families (prefix)", R.post_walk_pick(pln, [("Even Dogs Go", [pre], True)])[1], "prefix")
eq("V1 off for the KR/CN works (tiers=('amp',))", R.post_walk_pick(pln, [("Even Dogs Go", [pre], True)], tiers=("amp",)),
   (None, None, None))
r2 = {"id": 6501, "format": "MANGA", "volumes": 12, "popularity": 5, "status": "FINISHED",
      "title": {"english": "Petite Lune"}, "synonyms": []}
eq("R2 stays on the existing families: a 1-volume line binds a 12-volume serial on its own name",
   R.pick([r2], "Petite Lune", 1)[:2], (r2, "primary"))
eq("R2 off for the KR/CN works: the 4x ceiling holds for a 1-2 volume line on its own name too",
   R.pick([r2], "Petite Lune", 1, fallback=False)[0], None)
amp = {"id": 6401, "format": "MANGA", "volumes": 2, "popularity": 5, "status": "FINISHED",
       "title": {"english": "Kiss and Fly"}, "synonyms": []}
eq("V3 stays on for the KR/CN works (amp)", R.post_walk_pick({"name": "Kiss & Fly", "volume_count": 2, "orig_vc": None},
                                                             [("Kiss & Fly", [amp], True)], tiers=("amp",))[:2], (amp, "amp"))

kdb = sqlite3.connect(":memory:")
kdb.executescript("""
    CREATE TABLE series (gcd_series_id INTEGER PRIMARY KEY, name TEXT, language TEXT, medium TEXT, volume_count INTEGER,
                         anilist_id INTEGER, orig_series_id INTEGER, is_main INTEGER, tome_work_id TEXT);
    CREATE TABLE series_alias (gcd_series_id INTEGER, alias TEXT, language TEXT, kind TEXT);
    CREATE TABLE meta (key TEXT, value TEXT);
    INSERT INTO series VALUES (102, 'Königsklinge', 'de', 'manhwa', 2, NULL, NULL, 1, 'w_kr');
    INSERT INTO series VALUES (101, 'Lame Royale', 'fr', 'manhwa', 3, NULL, NULL, 1, 'w_kr');
    INSERT INTO series VALUES (103, 'Lame Royale (Intégrale)', 'fr', 'manhwa', 1, NULL, NULL, 0, 'w_kr');
    INSERT INTO series_alias VALUES (101, '왕의 검', 'ko', 'official');
    INSERT INTO series_alias VALUES (101, 'Wang-ui geom', 'ko', 'romanized');
    INSERT INTO series VALUES (201, 'Phantom', 'fr', 'manhua', 2, NULL, NULL, 1, 'w_cn');
    INSERT INTO series VALUES (301, 'Ciel d''Encre', 'fr', 'manhua', 4, NULL, NULL, 1, 'w_tw');
    INSERT INTO series VALUES (401, 'Lune Rouge', 'fr', 'manhwa', 3, NULL, NULL, 1, 'w_r4');
    INSERT INTO series VALUES (501, 'Semantic Error', 'en', 'novel', 1, NULL, NULL, 1, 'w_mix');
    INSERT INTO series VALUES (502, 'Semantic Error', 'de', 'manhwa', 4, NULL, NULL, 1, 'w_mix');
    INSERT INTO series VALUES (601, 'Has English', 'en', 'manhwa', 5, NULL, NULL, 1, 'w_en');
    INSERT INTO series VALUES (602, 'A l''anglaise', 'fr', 'manhwa', 5, NULL, NULL, 1, 'w_en');
    INSERT INTO series VALUES (701, 'Pas une oeuvre de bibliotheque', 'fr', 'manhwa', 5, NULL, NULL, 1, 'w_wiki');
    INSERT INTO series VALUES (801, 'Petite Lune', 'fr', 'manhwa', 1, NULL, NULL, 1, 'w_r2');
    ALTER TABLE series ADD COLUMN tome_id TEXT;
    UPDATE series SET tome_id = 'rl_' || gcd_series_id;
""")
kdb.execute("INSERT INTO meta VALUES ('krcn_ids', ?)", (json.dumps(
    {"works": ["w_kr", "w_cn", "w_tw", "w_r4", "w_mix", "w_en", "w_r2"],
     "created": ["w_kr", "w_cn", "w_tw", "w_r4", "w_mix", "w_en", "w_r2"], "lines": {}}),))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tier2"))
import corrections as CORR  # noqa: E402
_pins = tempfile.mkdtemp(prefix="anilist-pins-")
with open(os.path.join(_pins, "anilist.json"), "w", encoding="utf8") as f:
    json.dump([{"line": "rl_102", "anilist_id": None, "source_url": "https://anilist.co/", "checked": "2026-10-01"},
               {"line": "rl_101", "anilist_id": 5, "source_url": "https://anilist.co/manga/5", "checked": "2026-10-01"}], f)
_saved_dir, CORR.DIR = CORR.DIR, _pins
eq("unbind_pins: the lines anilist.json pins to null, nothing else", R.unbind_pins(), {"rl_102"})
CORR.DIR = _saved_dir
eq("unbind pin: an unbound English line is never searched again (load_lines skips it)",
   [ln["id"] for ln in R.load_lines(kdb, skip={"rl_601"})], [501])
eq("unbind pin: an unbound main line leaves its KR/CN work's search set (the other line stays)",
   [ln["id"] for ln in next(kw for kw in R.krcn_works(kdb, {"rl_102"}) if kw["work"] == "w_kr")["lines"]], [101])
kws = R.krcn_works(kdb)
eq("krcn_works: library works with no English comic line, one entry per work (c0292-shaped w_mix: its DE comic only)",
   [(kw["work"], [ln["id"] for ln in kw["lines"]], kw["countries"]) for kw in kws],
   [("w_cn", [201], ("CN", "TW")), ("w_kr", [101, 102], ("KR",)), ("w_mix", [502], ("KR",)), ("w_r2", [801], ("KR",)),
    ("w_r4", [401], ("KR",)), ("w_tw", [301], ("CN", "TW"))])
kr = next(kw for kw in kws if kw["work"] == "w_kr")
eq("krcn terms: FR name, its de-slug, DE name, its de-slug, native, romanized -- each against its own line's count, "
   "native / romanized against the anchor's, never as the own name",
   kr["terms"], [("Lame Royale", 3, True), ("lame royale", 3, True), ("Konigsklinge", 2, True), ("konigsklinge", 2, True),
                 ("왕의 검", 3, False), ("Wang-ui geom", 3, False)])
_saved_cache, R.CACHE = R.CACHE, tempfile.mkdtemp(prefix="anilist-krcn-")
try:
    hit = {"id": 5001, "format": "MANGA", "volumes": None, "popularity": 5, "status": "RELEASING",
           "title": {"romaji": "Wang-ui Geom", "native": "왕의 검"}, "synonyms": []}
    later = {"id": 5002, "format": "MANGA", "volumes": None, "popularity": 99, "status": "RELEASING",
             "title": {"romaji": "Wang-ui geom"}, "synonyms": []}
    tw = {"id": 7001, "format": "MANGA", "volumes": 4, "popularity": 5, "status": "FINISHED",
          "title": {"romaji": "Mo Tian"}, "synonyms": ["Ciel d'Encre"]}
    jp = {"id": 9001, "format": "MANGA", "volumes": 2, "popularity": 50, "status": "FINISHED",
          "title": {"english": "Phantom"}, "synonyms": []}
    PAGES = {("KR", "왕의 검"): [hit], ("KR", "Wang-ui geom"): [later], ("TW", "Ciel d'Encre"): [tw], ("KR", "Lune Rouge"): [lune],
             ("KR", "Petite Lune"): [r2]}
    for kw in kws:
        for c in kw["countries"]:
            for t, _, _ in kw["terms"]:
                R._cache_put(R._cache_path("search", "krcn-" + c, t), PAGES.get((c, t), []))
    R._cache_put(R._cache_path("search", "manga", "Phantom"), [jp])     # the Japanese 'Phantom' an English line would bind
    R.resolve_krcn(kws)
    got = {kw["work"]: (kw["pick"] or {}).get("id") for kw in kws}
    eq("resolve_krcn: the first term that binds wins (the native title, 5001 -- not the romanized term's 5002)",
       (got["w_kr"], kr["via"], kr["term"], kr["country"]), (5001, "primary", "왕의 검", "KR"))
    eq("resolve_krcn: a generic name (Phantom) reads only its krcn-CN / krcn-TW pages -> unbound, never the JP 9001",
       got["w_cn"], None)
    eq("resolve_krcn: a manhua found on the TW family after CN found nothing", (got["w_tw"], next(
        kw for kw in kws if kw["work"] == "w_tw")["country"]), (7001, "TW"))
    eq("resolve_krcn: an equal title 20x the line's volumes stays unbound (R4 off)", got["w_r4"], None)
    eq("resolve_krcn: a 1-volume line and an equal 12-volume title stay unbound (R2 off)", got["w_r2"], None)
    eq("write_krcn: the id goes to every main comic line of the work (FR and DE), never the non-main line",
       (R.write_krcn(kdb, kws, False), sorted(kdb.execute("SELECT gcd_series_id, anilist_id FROM series WHERE anilist_id IS NOT NULL"))),
       (3, [(101, 5001), (102, 5001), (301, 7001)]))
    eq("write_krcn: a line that has an id keeps it (writes only NULL ids)", R.write_krcn(kdb, kws, False), 0)
    _rp = os.path.join(R.CACHE, "krcn-anilist-bindings.tsv")
    R.report_krcn(kws, _rp)
    eq("report_krcn: one row per binding (work, lines, id, title, country, via, term)",
       open(_rp, encoding="utf8").read().splitlines(),
       ["\t".join(R.KRCN_BINDINGS_HEADER),
        "w_kr\tLame Royale | Königsklinge\t5001\tWang-ui Geom / 왕의 검\tKR\tprimary\t왕의 검",
        "w_tw\tCiel d'Encre\t7001\tMo Tian\tTW\tsynonym\tCiel d'Encre"])
    kdb.execute("UPDATE series SET anilist_id=5001 WHERE gcd_series_id=601")      # w_en's English line: the same id
    rows = R.krcn_collisions(kdb)
    eq("krcn_collisions: a created work whose AniList id is on another work's line (one row per pair)",
       rows, [["anilist", "w_en", "Has English", "w_kr", "Lame Royale", "", "", "", "5001"]])
    _dp = os.path.join(R.CACHE, "krcn-duplicates.tsv")
    with open(_dp, "w", encoding="utf8") as f:
        f.write("\t".join(R.DUP_HEADER) + "\ntitle\tw_a\tA\tw_b\tB\tka\tkb\t0.950\t\nanilist\tw_old\tO\tw_p\tP\t\t\t\t1\n")
    R.write_krcn_duplicates(_dp, rows)
    eq("write_krcn_duplicates: the title rows stay, the anilist rows are replaced",
       [r.split("\t")[:2] for r in open(_dp, encoding="utf8").read().splitlines()],
       [["kind", "work"], ["title", "w_a"], ["anilist", "w_en"]])
finally:
    R.CACHE = _saved_cache

# ---- F2 (2026-10-01): V3 ranks each page against the volume count of the line its term came from ----------------
_saved_cache, R.CACHE = R.CACHE, tempfile.mkdtemp(prefix="anilist-krcn-v3-")
try:
    big = {"id": 8101, "format": "MANGA", "volumes": 12, "popularity": 5, "status": "FINISHED",
           "title": {"english": "Kiss and Fly"}, "synonyms": []}
    small = dict(big, id=8102, volumes=2)
    for t, page in (("Lame Royale", []), ("Kiss & Fly", [big])):
        R._cache_put(R._cache_path("search", "krcn-KR", t), page)
    mk = lambda: {"work": "w_v3", "countries": ("KR",), "pick": None,
                  "lines": [{"name": "Lame Royale", "volume_count": 10}, {"name": "Kiss & Fly", "volume_count": 2}],
                  "terms": [("Lame Royale", 10, True), ("Kiss & Fly", 2, True)]}
    got = R.resolve_krcn([mk()])[0]
    eq("V3 for a KR/CN work: the DE line's 2-volume term does not bind a 12-volume entry (the anchor's 10 would let it)",
       got["pick"], None)
    R._cache_put(R._cache_path("search", "krcn-KR", "Kiss & Fly"), [small])
    got = R.resolve_krcn([mk()])[0]
    eq("V3 for a KR/CN work: a 2-volume entry for the 2-volume line's term binds", (got["pick"] or {}).get("id"), 8102)
finally:
    R.CACHE = _saved_cache
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tier0"))
import build_krcn as BK_  # noqa: E402
eq("DUP_HEADER is the same list as build_krcn.DUP_HEADER", R.DUP_HEADER, BK_.DUP_HEADER)

ART = os.environ.get("OPENTOME_ART", os.path.join(os.path.dirname(HERE), "build", "manga-metadata.sqlite"))
if os.path.exists(ART):
    db = sqlite3.connect("file:%s?mode=ro" % ART, uri=True)
    lines = []
    for sid in AUDITED:
        ln = R.load_line(db, sid)
        eq(f"line {sid} present in the artifact", ln is not None, True)
        if ln:
            ln["anilist_id"] = None
            lines.append(ln)
    # A fixture gap (an alias row of an audited line changed since the recording) is a replay
    # limitation, not an artifact defect: report it, never abort tier0/rebuild_all.sh step 0.
    try:
        R.resolve(lines)
    except R.OfflineMiss as e:
        print("  info  44-line replay skipped: fixture gap for %s (re-record with ANILIST_RECORD=1)"
              % ", ".join(map(repr, e.terms)))
    else:
        wrong = [(ln["name"], ln["pick"]["id"]) for ln in lines if ln["pick"] and ln["pick"]["id"] != AUDITED[ln["id"]]]
        eq("no audited line resolves to a different id than the audit's", wrong, [])
        unresolved = [ln["name"] for ln in lines if not ln["pick"]]
        eq("at least 40 of the 44 audited lines resolve", len(lines) - len(unresolved) >= 40, True)
        print("  info  unresolved audited lines (stay NULL, Mangarr's own search handles them): %s" % (unresolved or "none"))
else:
    print("  info  44-line replay skipped: no artifact at %s" % ART)

# ---- round C: the AniList before/after diff against the carry (round_c_diff) ----------------
import tempfile
_t = tempfile.mkdtemp(prefix="opentome-rcanilist-")
_carry = os.path.join(_t, "carry.sqlite")
_c = sqlite3.connect(_carry)
_c.execute("CREATE TABLE series (tome_id TEXT, name TEXT, anilist_id INTEGER)")
_c.executemany("INSERT INTO series VALUES (?,?,?)", [("rl_a", "Foo (novel series)", 11), ("rl_b", "Bar", 22),
                                                      ("rl_gone", "Old", 33)])
_c.commit(); _c.close()
_n = sqlite3.connect(":memory:")
_n.execute("CREATE TABLE series (tome_id TEXT, name TEXT, anilist_id INTEGER)")
_n.executemany("INSERT INTO series VALUES (?,?,?)", [("rl_a", "Foo", 11), ("rl_b", "Bar", 22), ("rl_new", "New", 1)])
eq("round C diff: only lines in both whose name changed, with the id before and after",
   R.round_c_diff(_n, _carry), [("rl_a", "Foo", 11, 11)])
eq("round C diff: no carry -> nothing", R.round_c_diff(_n, None), [])
_p = os.path.join(_t, "round-c-anilist.tsv")
R.write_round_c_diff(_p, [("rl_a", "Foo", None, 11)])
eq("round C diff: TSV header and a NULL before", open(_p).read(),
   "tome_id\tname\tanilist_before\tanilist_after\nrl_a\tFoo\t\t11\n")

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1)
print("all resolve_anilist tests passed")
