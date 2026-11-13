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

# ---- the spread (spread(), 2026-11-13): a work's id onto its NULL lines, by name or main line ----
def spread_db(rows, unbind=frozenset()):
    """In-memory artifact rows (sid, tome_id, name, language, medium, is_main, anilist_id, work)."""
    db = sqlite3.connect(":memory:")
    db.execute("""CREATE TABLE series (gcd_series_id INTEGER PRIMARY KEY, tome_id TEXT, name TEXT,
                  language TEXT, medium TEXT, is_main INTEGER, anilist_id INTEGER, tome_work_id TEXT)""")
    db.executemany("INSERT INTO series VALUES (?,?,?,?,?,?,?,?)", rows)
    res = R.spread(db, unbind)
    return res, dict(db.execute("SELECT tome_id, anilist_id FROM series"))


eq("family", [R.family(m) for m in ("manga", "manhwa", "manhua", "light_novel", "novel", None, "artbook")],
   ["comic", "comic", "comic", "novel", "novel", "comic", "artbook"])
res, ids = spread_db([
    (1, "rl_en1", "Wind Breaker", "en", "manga", 1, 135083, "w1"),
    (2, "rl_ja1", "Wind Breaker", "ja", "manga", 1, None, "w1"),      # name
    (3, "rl_de1", "Windbrecher", "de", "manga", 1, None, "w1"),       # main
    (4, "rl_de2", "Wind Breaker \u2013 Perfect Edition", "de", "manga", 0, None, "w1"),  # neither
    (5, "rl_en2", "Wind Breaker: The Novel", "en", "light_novel", 1, None, "w1"),   # other family
    (6, "rl_en3", "Re:Zero", "en", "manga", 1, 85737, "w2"),
    (7, "rl_en4", "Re:Zero (Truth of Zero)", "en", "manga", 0, 87259, "w2"),
    (8, "rl_de3", "Re:Zero", "de", "manga", 1, None, "w2"),           # name beats the 2-id family
    (9, "rl_fr1", "Re:Zero, la vie dans un autre monde", "fr", "manga", 1, None, "w2"),  # main, but the family holds 2 ids: nothing
    (10, "rl_fr2", "Bastard", "fr", "manhwa", 1, 100001, "w3"),
    (11, "rl_de4", "Bastard", "de", "manhwa", 1, 100001, "w3"),
    (12, "rl_ko1", "\ubc30\uc2a4\ud0c0\ub4dc", "ko", "manhwa", 1, None, "w3"),  # main, non-EN donors
    (13, "rl_en5", "Twin", "en", "manga", 1, 1, "w4"),
    (14, "rl_en6", "Twin", "en", "manga", 0, 2, "w4"),
    (15, "rl_ja2", "Twin", "ja", "manga", 1, None, "w4"),             # same-named donors disagree, 2 ids in the family: nothing
    (16, "rl_de5", "Wind Breaker", "de", "manga", 0, None, "w1"),     # unbind-pinned: skipped
    (17, "rl_ja3", "Wind Breaker", "ja", "manga", 0, 135083, "w1"),   # already bound: untouched, a donor
], unbind={"rl_de5"})
eq("spread: name rule", ids["rl_ja1"], 135083)
eq("spread: main rule", ids["rl_de1"], 135083)
eq("spread: non-main unmatched name stays NULL", ids["rl_de2"], None)
eq("spread: other family stays NULL", ids["rl_en2"], None)
eq("spread: name beats a two-id family", ids["rl_de3"], 85737)
eq("spread: main needs one id in the family (an arc beside the main: nothing)", ids["rl_fr1"], None)
eq("spread: main from non-EN donors", ids["rl_ko1"], 100001)
eq("spread: same-named donors with two ids write nothing", ids["rl_ja2"], None)
eq("spread: unbind pin skipped", ids["rl_de5"], None)
eq("spread: bound line untouched", ids["rl_ja3"], 135083)
eq("spread: counts", res["by"], {"name": 2, "main": 2})
eq("spread: rows", res["rows"], [
    ("rl_de1", "w1", "de", "manga", "Windbrecher", "main", 135083, "rl_en1"),
    ("rl_de3", "w2", "de", "manga", "Re:Zero", "name", 85737, "rl_en3"),
    ("rl_ja1", "w1", "ja", "manga", "Wind Breaker", "name", 135083, "rl_en1"),
    ("rl_ko1", "w3", "ko", "manhwa", "\ubc30\uc2a4\ud0c0\ub4dc", "main", 100001, "rl_de4"),
])
eq("spread: left in one-id families", res["left"], 1)
res3, ids3 = spread_db([
    (1, "rl_de7", "Bastard", "de", "manhwa", 1, 777, "w5"),       # a lifted work: FR/DE main lines bound
    (2, "rl_fr7", "Bastard", "fr", "manhwa", 1, 777, "w5"),
    (3, "rl_en7", "Bastard", "en", "manhwa", 1, None, "w5"),      # an EN line takes no id from non-EN donors
    (4, "rl_ko7", "\ubc30\uc2a4\ud0c0\ub4dc", "ko", "manhwa", 1, None, "w5"),  # a KO line does
])
eq("spread: an EN line needs an EN donor", (ids3["rl_en7"], ids3["rl_ko7"]), (None, 777))
res4, ids4 = spread_db([
    (1, "rl_en9", "Series (Arc)", "en", "manga", 0, 500, "w6"),   # the only donor is an arc (non-main)
    (2, "rl_en10", "Series", "en", "manga", 1, None, "w6"),       # the EN main line stays NULL
    (3, "rl_de9", "Serie", "de", "manga", 1, None, "w6"),         # so does the DE main line
    (4, "rl_ja9", "Series (Arc)", "ja", "manga", 0, None, "w6"),  # the JP arc matches by name
])
eq("spread: the main rule needs a main donor", (ids4["rl_en10"], ids4["rl_de9"], ids4["rl_ja9"]), (None, None, 500))
res5, ids5 = spread_db([
    (1, "rl_en11", "X", "en", "manga", 1, 9, "w7"),
    (2, "rl_en12", "X (Artbooks)", "en", "artbook", 1, None, "w7"),   # an artbook is its own family: no donor
    (3, "rl_ja11", "X (Artbooks)", "ja", "artbook", 1, None, "w7"),
    (4, "rl_ja12", "X", "ja", "manga", 1, None, "w7"),
])
eq("spread: artbooks take no comic id", (ids5["rl_en12"], ids5["rl_ja11"], ids5["rl_ja12"]), (None, None, 9))
res6, ids6 = spread_db([
    (1, "rl_en30", "Solo Leveling", "en", "manhwa", 1, 5, "w9"),
    (2, "rl_fr30", "Solo Leveling FR", "fr", "manhwa", 1, None, "w9"),         # two FR main lines in one family:
    (3, "rl_fr31", "Solo Leveling (Roman web)", "fr", "manga", 1, None, "w9"),  # the main rule trusts neither
    (4, "rl_de30", "Solo Leveling DE", "de", "manhwa", 1, None, "w9"),         # the sole DE main line: fine
])
eq("spread: a double main line gets nothing by the main rule", (ids6["rl_fr30"], ids6["rl_fr31"], ids6["rl_de30"]), (None, None, 5))
res7, ids7 = spread_db([
    (1, "rl_en20", "Alpha", "en", "manga", 1, 11, "w8"),
    (2, "rl_de20", "Alfa", "de", "manga", 1, None, "w8"),      # main rule, pass 1
    (3, "rl_de21", "Alfa", "de", "manga", 0, None, "w8"),      # name rule off the DE main line, pass 2
])
eq("spread: a run repeats until nothing more is written", (ids7["rl_de20"], ids7["rl_de21"], res7["by"]), (11, 11, {"name": 1, "main": 1}))
eq("spread: the chained row names its donor", res7["rows"][1], ("rl_de21", "w8", "de", "manga", "Alfa", "name", 11, "rl_de20"))   # rl_de2 (rl_de5 is pinned, rl_en2 is another family)
res2, ids2 = spread_db([(1, "rl_en1", "A", "en", "manga", 1, 7, "w1"), (2, "rl_ja1", "A", "ja", "manga", 1, 7, "w1")])
eq("spread: nothing to do is 0 rows", (res2["by"], res2["rows"], res2["left"]), ({"name": 0, "main": 0}, [], 0))

# ---- --spread: the stage-8a call, its TSV and its log lines; idempotent ---------------------
import contextlib, io, tempfile
_tmp = tempfile.mkdtemp()
_art = os.path.join(_tmp, "a.sqlite")
_db = sqlite3.connect(_art)
_db.execute("""CREATE TABLE series (gcd_series_id INTEGER PRIMARY KEY, tome_id TEXT, name TEXT,
               language TEXT, medium TEXT, is_main INTEGER, anilist_id INTEGER, tome_work_id TEXT)""")
_db.executemany("INSERT INTO series VALUES (?,?,?,?,?,?,?,?)",
                [(1, "rl_en1", "A", "en", "manga", 1, 7, "w1"), (2, "rl_ja1", "A", "ja", "manga", 1, None, "w1"),
                 (3, "rl_de1", "A: Edition", "de", "manga", 0, None, "w1"),
                 (4, "rl_de2", "Alpha", "de", "manga", 1, None, "w1"), (5, "rl_de3", "Alpha", "de", "manga", 0, None, "w1")])
_db.commit(); _db.close()
_out = io.StringIO()
with contextlib.redirect_stdout(_out):
    R.main([_art, "--spread"])
_lines = _out.getvalue().splitlines()
eq("--spread: log line", _lines[0], "anilist: spread 3 line(s) onto NULL lines (2 via name, 1 via main; de 2, ja 1)")
eq("--spread: leftover line", _lines[1], "anilist: spread left 1 NULL line(s) in one-id families (non-main, no name match)")
eq("--spread: tsv", open(os.path.join(_tmp, "anilist-spread.tsv"), encoding="utf8").read().splitlines(),
   ["\t".join(R.SPREAD_HEADER), "rl_de2\tw1\tde\tmanga\tAlpha\tmain\t7\trl_en1",
    "rl_de3\tw1\tde\tmanga\tAlpha\tname\t7\trl_de2", "rl_ja1\tw1\tja\tmanga\tA\tname\t7\trl_en1"])
_out = io.StringIO()
with contextlib.redirect_stdout(_out):
    R.main([_art, "--spread"])
eq("--spread again: idempotent", _out.getvalue().splitlines()[0],
   "anilist: spread 0 line(s) onto NULL lines (0 via name, 0 via main)")
eq("--spread again: header-only tsv",
   open(os.path.join(_tmp, "anilist-spread.tsv"), encoding="utf8").read().splitlines(), ["\t".join(R.SPREAD_HEADER)])


# ---- the JP binding: Japanese main lines with no English line in their family -----------------
def jp_db(series, aliases=()):
    """In-memory artifact: series rows (sid, tome_id, name, local_name, language, medium, is_main, anilist_id,
    work, volume_count, year_began); series_alias rows (sid, alias, language, kind)."""
    db = sqlite3.connect(":memory:")
    db.execute("""CREATE TABLE series (gcd_series_id INTEGER PRIMARY KEY, tome_id TEXT, name TEXT, local_name TEXT,
                  language TEXT, medium TEXT, is_main INTEGER, anilist_id INTEGER, tome_work_id TEXT,
                  volume_count INTEGER, year_began INTEGER, orig_series_id INTEGER)""")
    db.execute("CREATE TABLE series_alias (gcd_series_id INTEGER, alias TEXT, language TEXT, kind TEXT)")
    db.executemany("INSERT INTO series VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)", series)
    db.executemany("INSERT INTO series_alias VALUES (?,?,?,?)", aliases)
    return db

_jdb = jp_db([
    (1, "rl_j1", "Ghost Sweeper Mikami", "GS美神 極楽大作戦!!", "ja", "manga", 1, None, "w1", 39, 1992),
    (2, "rl_j2", "Ghost Sweeper Mikami (Wide-ban)", None, "ja", "manga", 0, None, "w1", 20, 2004),   # non-main: never
    (3, "rl_j3", "Bound", "縛", "ja", "manga", 1, None, "w2", 5, 2000),
    (4, "rl_e3", "Bound", None, "en", "manga", 1, None, "w2", 5, 2001),                              # EN line in the family: never
    (5, "rl_j4", "Novel Side", "小説", "ja", "light_novel", 1, None, "w2", 3, 2002),           # novel family of w2: considered
    (6, "rl_j5", "Done", "済", "ja", "manga", 1, None, "w3", 4, 2010),
    (7, "rl_j6", "Done Deluxe", "済 豪華", "ja", "manga", 0, 500, "w3", 4, 2015),          # bound line in the family: never
    (8, "rl_j7", "Art", None, "ja", "artbook", 1, None, "w4", 1, 2011),                               # artbook: never
    (9, "rl_j8", "Pinned", "ピン", "ja", "manga", 1, None, "w5", 2, 2012),                    # unbind-pinned: never
    (10, "rl_j9", "Same Key", "Same Key", "ja", "manga", 1, None, "w6", 7, 2013),                    # local_name key == name key
], aliases=[
    (1, "Ghost Sweeper Mikami", None, "line"),
    (1, "GS Mikami", "en", "alias"), (1, "Ghost Sweeper", "en", "alias"), (1, "GS Mikami Gokuraku", "en", "alias"),
    (1, "Ghost Sweeper Mikami Gokuraku Daisakusen", "en", "alias"),
    (1, "Ghost Sweeper Mikami: Gokuraku Daisakusen!!", "en", "official"),
    (1, "GS美神", "ja", "official"),
    (10, "Same Key!", "en", "alias"),
])
_jl = R.jp_lines(_jdb, skip={"rl_j8"})
eq("jp_lines: the considered lines, by tome_id", [ln["tome_id"] for ln in _jl], ["rl_j1", "rl_j4", "rl_j9"])
eq("jp_lines: fields", {k: _jl[0][k] for k in ("id", "work", "name", "medium", "novel", "volume_count", "year_began")},
   {"id": 1, "work": "w1", "name": "Ghost Sweeper Mikami", "medium": "manga", "novel": False, "volume_count": 39, "year_began": 1992})
eq("jp_lines: official aliases ja first, then en", _jl[0]["official"],
   ["GS美神", "Ghost Sweeper Mikami: Gokuraku Daisakusen!!"])
eq("jp_lines: alias-kind aliases in stored order", _jl[0]["aliases"],
   ["GS Mikami", "Ghost Sweeper", "GS Mikami Gokuraku", "Ghost Sweeper Mikami Gokuraku Daisakusen"])
eq("jp_lines: novel family considered beside an EN comic line", (_jl[1]["novel"], _jl[1]["work"]), (True, "w2"))
eq("jp_terms: order and kinds, alias capped at ALIAS_LIMIT", R.jp_terms(_jl[0]), [
    ("Ghost Sweeper Mikami", True, "name"), ("GS美神 極楽大作戦!!", False, "native"),
    ("GS美神", False, "official"), ("Ghost Sweeper Mikami: Gokuraku Daisakusen!!", False, "official"),
    ("GS Mikami", False, "alias"), ("Ghost Sweeper", False, "alias"), ("GS Mikami Gokuraku", False, "alias")])
eq("jp_terms: a local_name key-equal to the name is one term; an alias key-equal to the name is dropped",
   R.jp_terms(_jl[2]), [("Same Key", True, "name")])
eq("JP_HEADER", R.JP_HEADER, ["work", "line", "name", "local_name", "medium", "volume_count", "year_began",
                               "anilist_id", "title", "via", "term", "note"])


def summary():
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILED: {FAILS}")
        sys.exit(1)
    print("all resolve_anilist tests passed")


if __name__ == "__main__":
    summary()
