"""Unit tests for the tier-0 parser. Run: python3 tier0/test_parser.py

Every case here is a shape that was measured in the corpus and mis-handled
before (docs/cleanup-v2.md). No network: everything is synthetic wikitext.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wikipedia_volumes import parse_date, canon_number, parse_volumes, _is_blank, FR_MONTHS, _clean
from isbn import isbn_market, normalise_isbn
from collapse import collapse_licensed
import release_lines as RL
import main_articles as MA

FAILS = []


def eq(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok:
        FAILS.append(label)


# ---- dates -------------------------------------------------------------
eq("plain mdy", parse_date("October 13, 2013<ref>x</ref>"), ("2013-10-13", "day"))
eq("mdy no comma", parse_date("May 4 2020"), ("2020-05-04", "day"))
eq("3-letter month", parse_date("Nov 3, 2021"), ("2021-11-03", "day"))
eq("{{start date}}", parse_date("{{start date|2023|2|9}}"), ("2023-02-09", "day"))
eq("{{Start date|df}}", parse_date("{{Start date|2023|2|9|df=y}}"), ("2023-02-09", "day"))
eq("{{dts}} numeric", parse_date("{{dts|2020|4|21}}"), ("2020-04-21", "day"))
eq("{{dts}} text", parse_date("{{dts|April 21, 2020}}"), ("2020-04-21", "day"))
eq("fr {{date|d|mois|y}}", parse_date("{{date|16|juillet|2010}}", FR_MONTHS), ("2010-07-16", "day"))
eq("fr {{Date|d mois y}}", parse_date("{{Date|16 septembre 2010}}", FR_MONTHS), ("2010-09-16", "day"))
eq("fr {{Date|dd|MM|yyyy}}", parse_date("{{Date|10|03|1998}}", FR_MONTHS), ("1998-03-10", "day"))
eq("fr 1er", parse_date("{{date|1er|janvier|2010}}", FR_MONTHS), ("2010-01-01", "day"))
eq("fr {{date rapide}}", parse_date("{{date rapide|2010|3|17}}", FR_MONTHS), ("2010-03-17", "day"))
eq("fr {{date-}}", parse_date("{{date-|2 octobre 1975}}", FR_MONTHS), ("1975-10-02", "day"))
eq("month only", parse_date("September 2003"), ("2003-09", "month"))
eq("year only", parse_date("2019"), ("2019", "year"))
eq("invalid day degrades", parse_date("February 30, 2020"), ("2020-02", "month"))
eq("dash is none", parse_date("—"), (None, "none"))
eq("TBA is none", parse_date("TBA"), (None, "none"))

# ---- placeholders ------------------------------------------------------
for v in ("", " ", "—", "-", "&mdash;", "N/A", "N/A (Part of omnibus volume 3)", "TBA", "{{nc}}", "?"):
    eq(f"blank {v!r}", _is_blank(v), True)
eq("not blank", _is_blank("978-1-61262-420-4"), False)

# ---- volume labels -----------------------------------------------------
eq("01 -> 1", canon_number("01")[:2], ("1", "int"))
eq("1.0 -> 1", canon_number("1.0")[:2], ("1", "int"))
eq("1 (18) dual", canon_number("1 (18)")[:2], ("1", "int"))
eq("Volume 3", canon_number("Volume 3")[:2], ("3", "int"))
eq("9 RE:", canon_number("9 RE:")[:2], ("9", "int"))
eq("7.5 decimal", canon_number("7.5")[:2], ("7.5", "decimal"))
eq("17-18 range", canon_number("17-18")[:2], ("17-18", "range"))
eq("SP special", canon_number("SP")[:2], ("SP", "special"))
eq("Ex3 special", canon_number("Ex3")[:2], ("Ex3", "special"))
eq("dash blank", canon_number("—")[1], "blank")
eq("katakana dash blank", canon_number("ー")[1], "blank")

# ---- isbn --------------------------------------------------------------
eq("978-4 JP", isbn_market("9784063842760"), "JP")
eq("978-1 EN", isbn_market("9781612624204"), "EN")
eq("979-8 EN", isbn_market("9798888779347"), "EN")
eq("979-11 KR", isbn_market("9791170336662"), "KR")
eq("979-10 FR", isbn_market("9791030000000"), "FR")
eq("978-89 KR", isbn_market("9788912345678"), "KR")
eq("978-2 FR", isbn_market("9782723456789"), "FR")
eq("JAN rejected", normalise_isbn("4573000000000"), (None, None))
eq("isbn10 -> 13", normalise_isbn("4088735048")[0], "9784088735047")

# ---- emission rule -----------------------------------------------------
W = """
{{Graphic novel list/header |Language = Japanese |SecondLanguage = English}}
{{Graphic novel list
 | VolumeNumber    = 1
 | OriginalRelDate = March 17, 2010
 | OriginalISBN    = 978-4-06-384276-0
 | LicensedRelDate = June 19, 2012
 | LicensedISBN    = 978-1-61262-024-4
}}
{{Graphic novel list
 | VolumeNumber    = 02
 | OriginalRelDate = {{start date|2010|7|16}}
 | OriginalISBN    = 978-4-06-384299-9
 | LicensedRelDate = —
 | LicensedISBN    =
}}
{{Graphic novel list
 | VolumeNumber    = 3
 | OriginalRelDate =
 | OriginalISBN    =
 | LicensedRelDate = N/A (Part of omnibus volume 1)
 | LicensedISBN    =
 | Title           = Announced Title
}}
{{Graphic novel list
 | VolumeNumber    = 4
 | RelDate         = January 5, 2020
 | ISBN            = 979-11-7033-666-2
 | LicensedRelDate = March 2, 2021
 | LicensedISBN    = 978-1-9753-1943-4
}}
{{Graphic novel list/footer}}
"""
recs = parse_volumes(W, "List of Test chapters", "en")
eq("4 rows parsed", len(recs), 4)
r1, r2, r3, r4 = recs
eq("row1 both markets", sorted(r1["markets"]), ["licensed", "original"])
eq("row1 JP market", r1["markets"]["original"]["market"], "JP")
eq("row2 number canon", r2["volume"], "2")
eq("row2 start-date parsed", r2["markets"]["original"].get("date"), "2010-07-16")
eq("row2 NO phantom EN entry", "licensed" in r2["markets"], False)
eq("row3 announced JP only", (r3.get("announced"), list(r3["markets"])), (True, ["original"]))
eq("row3 title kept", r3.get("title"), "Announced Title")
eq("row4 Korean original -> KR", r4["markets"]["original"]["market"], "KR")
eq("row4 EN licensed", r4["markets"]["licensed"]["market"], "EN")

FRW = """
{{TomeBD|volume=1|langage_unique=oui|sortie_1={{date|16|juillet|2010}}|isbn_1=978-4-06-384276-0|sortie_2=|isbn_2=}}
{{TomeBD|volume=2|langage_unique=non|sortie_1=2010|isbn_1=978-4-06-384299-9|sortie_2={{Date|10|03|1998}}|isbn_2=978-2-7234-5678-9}}
"""
fr = parse_volumes(FRW, "Liste des chapitres de Test", "fr")
eq("fr single-language skips licensed", list(fr[0]["markets"]), ["original"])
eq("fr licensed FR numeric date", fr[1]["markets"]["licensed"].get("date"), "1998-03-10")

# ---- per-market title (2026-09-21) -------------------------------------
# a separate small fixture: adding this row to W would break "4 rows parsed"
W_TITLE = """
{{Graphic novel list
 | VolumeNumber    = 1
 | OriginalTitle   = アインクラッド
 | LicensedTitle   = Aincrad
 | OriginalRelDate = April 10, 2009
 | OriginalISBN    = 978-4-06-384276-0
 | LicensedRelDate = April 15, 2014
 | LicensedISBN    = 978-1-61262-024-4
}}
"""
recs_title = parse_volumes(W_TITLE, "List of Test chapters", "en")
# per-market title (2026-09-21): the licensed row must not carry the Japanese title
r = next(x for x in recs_title if x["volume"] == "1")
eq("row title is still the first non-blank field", r["title"], "アインクラッド")
eq("original title", r.get("title_original"), "アインクラッド")
eq("licensed title", r.get("title_licensed"), "Aincrad")
eq("Nihongo2 template is unwrapped", _clean("{{Nihongo2|Boruto!!|ボルト}}"), "Boruto!!")
eq("nihongo is case-insensitive", _clean("{{Nihongo|Aincrad|アインクラッド|Ainkuraddo}}"), "Aincrad")
eq("japonais keeps the non-Japanese text", _clean("{{japonais|ノー・ガール・ノー・クライ<br />|Nō Gāru Nō Kurai / No Girl No Cry|| }}"), "No Girl No Cry")
eq("japonais with a leading French slot", _clean("{{Japonais|Asagao et Kase-san|あさがおと加瀬さん。|Asagao to Kase-san.}}"), "Asagao et Kase-san")
eq("japonais with an empty first slot falls back to the romaji", _clean("{{Japonais||あさがおと加瀬さん。|Asagao to Kase-san.}}"), "Asagao to Kase-san.")
eq("br is a space", _clean("Aincrad<br />Part 2"), "Aincrad Part 2")
eq("ruby keeps the base text", _clean("いとしき<ruby>歳月<rp>(</rp><rt>としつき</rt><rp>)</rp></ruby>(前編)"), "いとしき歳月(前編)")
eq("an unterminated comment is not a title", _clean("<!--"), "")
eq("angle brackets in plain text survive", _clean("境界線上のホライゾンI<上>"), "境界線上のホライゾンI<上>")

# ---- _clean nested-template unwrap (2026-09-23 follow-up) ---------------
# The old regex unwrap only matched up to the FIRST '}}' it found, so a
# template nesting another template leaked a stray '}}' (or, when the outer
# match failed to close at all, a stray '|'). _clean now walks every
# top-level {{...}} brace-balanced, the same depth counter _templates() uses.
eq("japonais survives a nested nowrap (no leaked '}}')",
   _clean("{{japonais|A|B|{{nowrap|C}}}}"), "A")
eq("japonais with a nested nowrap earlier in the slot list",
   _clean("{{japonais|A|{{nowrap|B}}|C}}"), "A")
eq("nihongo with a nested lang template (no leaked '}}')",
   _clean("{{Nihongo|Attack on Titan|{{lang|ja|進撃の巨人}}|Shingeki no Kyojin}}"), "Attack on Titan")
eq("an unterminated nested template stays literal (still markup, not garbled)",
   _clean("{{japonais|A|{{nowrap|B}}"), "{{japonais|A|{{nowrap|B}}")

# ---- pass-through templates + recursive unwrap on the returned slot -----
# (review round 1, finding 5): _unwrap_one used to return the chosen slot
# RAW, so a template nested inside it (not alongside it) still leaked. These
# are the real shapes found by re-measuring every cached title value:
# {{ruby-ja}}/{{lang}}/{{langue}}/{{nowrap}} are pure wrappers around real
# title text, not noise, and a bare roman-numeral template name ({{I}}..
# {{XII}}) is a volume/part number, not noise either.
eq("ruby-ja passes through its base (first) parameter",
   _clean("{{ruby-ja|恐ろしき恋人|おそろしきこいびと}}"), "恐ろしき恋人")
eq("fr langue passes through its LAST positional parameter (not the language code)",
   _clean("{{Langue|en|Kase-san and Morning Glories}}"), "Kase-san and Morning Glories")
eq("nowrap passes through its parameter", _clean("{{nowrap|Some Text}}"), "Some Text")
eq("a bare roman-numeral template name passes through as the numeral",
   _clean("{{XII}}"), "XII")
eq("a roman-numeral template nested inside plain text passes through in place",
   _clean('Dai-yon-bu "Kizoku-in no jisho tosho iin {{VIII}}"'),
   'Dai-yon-bu "Kizoku-in no jisho tosho iin VIII"')
eq("nihongo's returned slot is itself recursively unwrapped (a nested roman numeral)",
   _clean("{{Nihongo|Part {{VIII}} Title|パート8}}"), "Part VIII Title")
eq("japonais's returned slot is itself recursively unwrapped (a nested ruby-ja)",
   _clean("{{japonais|{{ruby-ja|恐ろしき恋人|おそろしきこいびと}}|オソロシキ}}"), "恐ろしき恋人")
# a real interlanguage-link template ({{ill}}) is not a roman numeral just because
# every one of its letters is also a roman-numeral letter -- caught by re-measuring
# the fix over .cache/ (review round 1's re-measure step)
eq("{{ill}} is not mistaken for a roman numeral", _clean("Denma S.E. {{ill|Rami Record|ko|라미레코드}}"), "Denma S.E.")
eq("a lowercase word made only of IVXLCDM letters is not a roman numeral", _clean("{{mix}}"), "")
eq("a real uppercase roman numeral still passes through", _clean("{{XII}}"), "XII")

# ---- omnibus collapse --------------------------------------------------
def rec(n, isbn, date, pos):
    return {"volume": str(n), "_offset": pos, "medium": "manga", "line": "X",
            "markets": {"original": {"market": "JP", "isbn13": f"978400000000{n}"},
                        "licensed": {"market": "EN", "isbn13": isbn, "date": date}}}
vin = [rec(1, "A", "2013-10-13", 10), rec(2, "A", "2013-10-13", 20),
       rec(3, "B", "2014-01-21", 30), rec(4, "B", "2014-01-21", 40),
       rec(5, "C", "2026-10-06", 50)]
out = collapse_licensed(vin)
lic = [(r["volume"], r["markets"].get("licensed")) for r in out]
eq("collapse keeps JP rows", len(out), 5)
eq("collapse: 3 EN volumes", sum(1 for _, m in lic if m), 3)
eq("collapse: EN renumbered", [m["number"] for _, m in lic if m], ["1", "2", "3"])
eq("collapse: composition (single row maps too)", [m.get("contains") for _, m in lic if m], [[1, 2], [3, 4], [5]])
eq("collapse: first-of-run keeps date", lic[0][1]["date"], "2013-10-13")
# a line with no runs is untouched
plain = [rec(1, "A", "2020", 1), rec(2, "B", "2021", 2)]
eq("no-run line untouched", [(r["markets"]["licensed"].get("number"), r["markets"]["licensed"].get("contains")) for r in collapse_licensed(plain)], [(None, None), (None, None)])
# JP-only duplicate ISBNs never collapse (different dates => attribution error, not omnibus)
jp = [rec(1, "A", "2020-01-01", 1), rec(2, "A", "2021-01-01", 2)]
eq("different dates: no collapse", [r["markets"]["licensed"].get("contains") for r in collapse_licensed(jp)], [None, None])

# ---- arc split ------------------------------------------------------
def arc(n, title, pos):
    return {"volume": str(n), "_offset": pos, "medium": "manga", "line": "SAO: Progressive",
            "title": title, "markets": {"original": {"market": "JP", "isbn13": f"978400000{n:04d}"}}}
rows = [arc(i, f"SAO: Progressive {i}", i * 10) for i in range(1, 4)]
rows += [arc(4, "SAO: Progressive: Barcarolle of Froth 1", 40), arc(5, "SAO: Progressive: Barcarolle of Froth 2", 50)]
rows += [arc(6, "SAO: Progressive: Oddity 1", 60)]              # single row: NOT a run
rows += [arc(7, "SAO: Progressive 7", 70)]
sp = RL.split_arcs(rows, "SAO")
eq("arc: base keeps its rows", [r["volume"] for r in sp if r["line"] == "SAO: Progressive"], ["1", "2", "3", "6", "7"])
eq("arc: run becomes its own line", [r["volume"] for r in sp if "Barcarolle" in r["line"]], ["1", "2"])
eq("arc: named after the work", sp[3]["line"], "SAO: Progressive: Barcarolle of Froth")
eq("arc: raw name is the arc alone", sp[3]["line_raw"], "Barcarolle of Froth")
eq("arc: single odd row left alone", sp[5]["line"], "SAO: Progressive")
eq("arc: parent recorded", sp[3].get("arc_of"), "SAO: Progressive")
eq("arc: 'Livre'/'Book' is a number word", RL._stem("Nisemonogatari - Légendes Illusoires : Livre 2"), ("Nisemonogatari - Légendes Illusoires", 2))
eq("arc: 'Book' is a number word", RL._stem("Ascendance of a Bookworm Part 2 Book 3")[1], 3)
w = [arc(i, f"W.I.T.C.H. {i}", i * 10) for i in range(1, 3)]
w += [arc(3, "Part IX. 100% W.I.T.C.H. 1", 30), arc(4, "Part IX. 100% W.I.T.C.H. 2", 40)]
for r in w:
    r["line"] = "W.I.T.C.H."
eq("arc: stem containing (not starting with) the work is qualified",
   RL.split_arcs(w, "W.I.T.C.H.")[2]["line"], "W.I.T.C.H. (Part IX. 100% W.I.T.C.H.)")

# ---- heading classes (heading cleanup A+B, 2026-09-29; spec §3.1) ---------------------------------
# Class 1 names no line (falls through to the work title); class 2 names a medium (sets it, falls
# through); class 3 and anything not listed in the spec keep naming their line (round C).
HW = "A Sign of Affection"
for h in ("Médias", "Média", "MÉDIAS", "Parution", "Production", "Publications", "Publication history",
          "Publication and conception", "Books and publications", "Related media", "Works", "Personnages",
          "Synopsis", "Plot", "Plot summary", "Books", "Book", "Liste de volumes", "Listes des volumes",
          "Liste des tomes", "Détail des volumes", "List of chapters", "Chapter and volume list",
          "Manga volumes", "Tomes 21 à aujourd'hui", "Tome 31 à aujourd’hui", "Volumes 21 à aujourd'hui",
          "Volumes 11 to present"):
    eq("class 1: %r names no line" % h, RL.line_name([h], HW), (HW, HW))
for h, med in (("Roman", "novel"), ("Romans", "novel"), ("Roman illustré", "light_novel"), ("Roman web", "novel"),
               ("Liste des romans", "novel"), ("Novelizations", "novel"), ("Novel series", "novel"),
               ("Web novel", "novel"), ("Liste des light novel", "light_novel"),
               ("Liste des light novels", "light_novel"), ("Liste des volumes du light novel", "light_novel"),
               ("Bande dessinée", "manga"), ("Mangas", "manga"), ("Webtoon", "manhwa")):
    eq("class 2: %r sets the medium" % h, RL.detect_medium([h], HW, default=None), med)
    eq("class 2: %r names no line" % h, RL.line_name([h], HW), (HW, HW))
for h in ("Édition Deluxe", "Première édition", "New edition", "Part 1", "1re partie", "Second series",
          "Truth of Zero", "Jump Comics", "Shueisha Bunko", "English release", "Japanese volume list",
          "Tankōbon editions", "Spin-off manga", "Short stories", "TV series", "Listes des tomes",
          "Informations", "Novel list", "Liste des volumes de la série principale"):
    eq("class 3 / unlisted: %r still names its line" % h, RL.line_name([h], HW), ("%s (%s)" % (HW, h), h))
eq("a closed pagination range is still pagination", RL.line_name(["Tomes 1 à 20"], HW), (HW, HW))
eq("the article title never reads a heading hint (Cestvs: The Roman Fighter)",
   RL.detect_medium(["Volumes"], "Cestvs: The Roman Fighter", default=None), None)
eq("a heading hint needs the whole heading: an arc 'Le Roman de Chiyo' is no novel section",
   RL.detect_medium(["Le Roman de Chiyo"], HW, default=None), None)
eq("a MEDIUM_HINTS word anywhere in the path still wins over a heading hint",
   RL.detect_medium(["Manga", "Roman"], HW, default=None), "manga")
eq("a heading hint wins over the article title", RL.detect_medium(["Roman"], "Hyouka (manga)", default=None), "novel")
eq("no hint anywhere: the default", RL.detect_medium(["Volumes"], HW), "manga")
# hold=True: the name the collision guard restores -- only for what the round changed
eq("hold: a round-A heading names its line as before the round", RL.line_name(["Médias"], HW, hold=True),
   (HW + " (Médias)", "Médias"))
eq("hold: an open-ended pagination heading too", RL.line_name(["Tomes 21 à aujourd'hui"], HW, hold=True),
   (HW + " (Tomes 21 à aujourd'hui)", "Tomes 21 à aujourd'hui"))
for h in ("Media", "Publications", "Liste des tomes", "Novel series", "Volumes", "Tomes 1 à 20", "Manga"):
    eq("hold: %r was generic before the round and stays generic" % h, RL.line_name([h], HW, hold=True), (HW, HW))
hsrc = ("== Liste des volumes ==\n{{a}}\n== Médias ==\n=== Manga ===\n{{b}}\n"
        "== Tomes 21 à aujourd'hui ==\n{{c}}\n== Édition Deluxe ==\n{{d}}\n== Roman ==\n{{e}}\n")
hrecs = [{"volume": n, "_offset": hsrc.index(tag)} for n, tag in
         (("1", "{{a}}"), ("2", "{{b}}"), ("21", "{{c}}"), ("1", "{{d}}"), ("1", "{{e}}"))]
hout = RL.split(hsrc, "Liste des volumes de Hyouka", "Hyouka", hrecs)
eq("split: 'Médias > Manga' and the open-ended pagination load into the work's own line; "
   "'Roman' is its novel line; 'Édition Deluxe' stays a line",
   [(r["medium"], r["line"]) for r in hout],
   [("manga", "Hyouka"), ("manga", "Hyouka"), ("manga", "Hyouka"), ("manga", "Hyouka (Édition Deluxe)"),
    ("novel", "Hyouka")])
eq("split: a record that fell through a round-A heading carries its held name; the others none",
   [r.get("line_held") for r in hout],
   [None, "Hyouka (Médias)", "Hyouka (Tomes 21 à aujourd'hui)", None, "Hyouka (Roman)"])
eq("split: ... and its pre-round medium (no heading hint: 'Roman' was manga before the round)",
   [r.get("medium_held") for r in hout], [None, "manga", "manga", None, "manga"])
eq("detect_medium(headings=False) is the pre-round rule", RL.detect_medium(["Roman"], "Hyouka", headings=False), "manga")
# Maburaho / Re:Creators (fix F1 ruling 2): a class-2 heading ABOVE a named heading ("Roman illustré >
# Nouvelle") sets no medium -- the line names itself, so no group falls through; it keeps its pre-round
# medium and line id. HEADING_MEDIUM_HINTS take effect only for a group that falls through.
msrc = "== Roman illustré ==\n=== Nouvelle ===\n{{a}}\n=== Histoire secondaire ===\n{{b}}\n"
mout = RL.split(msrc, "Maburaho", "Maburaho", [{"volume": "1", "_offset": msrc.index("{{a}}")},
                                               {"volume": "1", "_offset": msrc.index("{{b}}")}])
eq("split: Maburaho -- a medium heading above a named heading keeps the pre-round medium (and so its line id)",
   [(r["medium"], r["line"], r.get("line_held")) for r in mout],
   [("manga", "Maburaho (Nouvelle)", None), ("manga", "Maburaho (Histoire secondaire)", None)])

# ---- the collision guard (heading cleanup, 2026-09-29; review C1; fix F1 ruling) ------------------
# A round-A group falls through ONLY as a pure duplicate: every one of its volumes lands on a line of
# the same work that already exists (another row, any article, or the catalogue) under the same number
# with the SAME ISBN (a volume without an ISBN: under a number that line already has). Otherwise it
# keeps its pre-round heading name, medium and heading alias.
def grec(n, isbn, pos, market="JP"):
    return {"volume": str(n), "_offset": pos, "markets": {"original": {"market": market, "isbn13": isbn}}}
gmain = "== Manga ==\n{{a}}\n"
gpub = "== Publication and conception ==\n{{b}}\n"
ngnl_a = RL.split(gmain, "No Game No Life", "No Game No Life",
                  [grec(n, "97840406611%02d" % n, gmain.index("{{a}}")) for n in (1, 2)])
ngnl_b = RL.split(gpub, "No Game No Life: Publications", "No Game No Life",
                  [grec(n, "97840406643%02d" % n, gpub.index("{{b}}")) for n in (1, 2, 3)])
held = RL.hold_clashes([("w_ngnl", ngnl_a), ("w_ngnl", ngnl_b)])
eq("guard: the No Game No Life shape (another article's list, same numbers, other ISBNs) is held",
   sorted(held), [(1, "No Game No Life (Publication and conception)")])
eq("guard: ... listing its three volumes (none a duplicate; two clash, the third is not on the line)",
   len(held[(1, "No Game No Life (Publication and conception)")]), 3)
eq("guard: hold() gives the held group its heading name back (and its pre-round medium, manga here too)",
   [(r["medium"], r["line"]) for r in RL.hold(ngnl_b, {"No Game No Life (Publication and conception)"})],
   [("manga", "No Game No Life (Publication and conception)")] * 3)
eq("guard: hold() leaves the other records alone", RL.hold(ngnl_a, {"No Game No Life (Publication and conception)"}), ngnl_a)
gbooks = "== Books ==\n{{b}}\n"
rr = RL.split(gbooks, "Red River", "Red River", [grec(n, "97840945200%02d" % n, gbooks.index("{{b}}")) for n in (1, 2)])
eq("guard: the Red River shape (a line already in the catalogue holds other ISBNs) is held",
   sorted(RL.hold_clashes([("w_rr", rr)], existing=[("w_rr", "manga", "JP", "Red River", "1", "9784091365019"),
                                                    ("w_rr", "manga", "JP", "Red River", "2", "9784091365026")])),
   [(0, "Red River (Books)")])
eq("guard: keys fold case and whitespace like the loader's _id (an existing line named 'red river ' still clashes)",
   sorted(RL.hold_clashes([("w_rr", rr)], existing=[("w_rr", "Manga", "jp", " red river ", "1", "9784091365019"),
                                                    ("w_rr", "manga", "JP", "RED RIVER", " 2", "9784091365026")])),
   [(0, "Red River (Books)")])
gcont = "== Tomes 1 à 20 ==\n{{a}}\n== Tomes 21 à aujourd'hui ==\n{{b}}\n"
cont = RL.split(gcont, "Liste des tomes de Dandadan", "Dandadan",
                [grec(1, "9784088825001", gcont.index("{{a}}")), grec(21, "9784088825021", gcont.index("{{b}}"))])
main_dd = RL.split(gmain, "Dandadan", "Dandadan", [grec(21, "9784088825021", gmain.index("{{a}}"))])
eq("guard: an open-ended section whose books another article already lists under the same numbers "
   "(same ISBNs) falls through: a pure duplicate",
   RL.hold_clashes([("w_dd", main_dd), ("w_dd", cont)]), {})
eq("guard: ... into the work's own line", [r["line"] for r in cont], ["Dandadan", "Dandadan"])
eq("guard: a real continuation (numbers the work's line does not have) is held -- round C, not a merge",
   RL.hold_clashes([("w_dd", cont)]), {(0, "Dandadan (Tomes 21 à aujourd'hui)"): [RL._nk("w_dd", "manga", "JP", "Dandadan", "21")]})
noisbn = RL.split(gmain, "Dandadan", "Dandadan", [grec(21, None, gmain.index("{{a}}"))])
eq("guard: a volume WITH an ISBN onto a number the line has without one is held (not provably the same book)",
   sorted(RL.hold_clashes([("w_dd", noisbn), ("w_dd", cont)])), [(1, "Dandadan (Tomes 21 à aujourd'hui)")])
cont_noisbn = RL.split(gcont, "Liste des tomes de Dandadan", "Dandadan",
                       [grec(1, "9784088825001", gcont.index("{{a}}")), grec(21, None, gcont.index("{{b}}"))])
eq("guard: a volume without an ISBN falls through onto a number the line already has",
   RL.hold_clashes([("w_dd", main_dd), ("w_dd", cont_noisbn)]), {})
eq("guard: ... and is held on a number the line lacks",
   sorted(RL.hold_clashes([("w_dd", cont_noisbn)])), [(0, "Dandadan (Tomes 21 à aujourd'hui)")])
gsame = "== Liste des volumes ==\n{{a}}\n== Médias ==\n{{b}}\n"
same_ok = RL.split(gsame, "Gosick", "Gosick", [grec(5, "9784047126930", gsame.index("{{a}}")),
                                              grec(5, "9784047126930", gsame.index("{{b}}"))])
same_bad = RL.split(gsame, "Gosick", "Gosick", [grec(5, "9784047126930", gsame.index("{{a}}")),
                                               grec(5, "9784047125582", gsame.index("{{b}}"))])
eq("guard: a 'Médias' section repeating the main list's books falls through", RL.hold_clashes([("w_g", same_ok)]), {})
eq("guard: one listing another book under the same number is held (same article too)",
   sorted(RL.hold_clashes([("w_g", same_bad)])), [(0, "Gosick (Médias)")])

gww = "== Liste des volumes du light novel ==\n{{a}}\n== Médias ==\n{{b}}\n"
# the English article's JP light-novel line (the real shape: the French LN list repeats its ISBNs)
gln = "== Light novels ==\n{{a}}\n"
ww_main = RL.split(gln, "Wandering Witch", "Wandering Witch", [grec(1, "9784797384352", gln.index("{{a}}"))])
ww_fr = RL.split(gww, "Wandering Witch (fr)", "Wandering Witch", [grec(1, "9784797384352", gww.index("{{a}}")),
                                                                  grec(1, "9784757560932", gww.index("{{b}}"))])
eq("guard: a group repeating the main line's books falls through; its sibling listing another book is held",
   sorted(RL.hold_clashes([("w_ww", ww_main), ("w_ww", ww_fr)])), [(1, "Wandering Witch (Médias)")])

eq("guard: ... the light-novel list would have made a NEW line without the English one -> held too",
   sorted(RL.hold_clashes([("w_ww", ww_fr)])),
   [(0, "Wandering Witch (Liste des volumes du light novel)"), (0, "Wandering Witch (Médias)")])

# Seraph of the End / Gamaran (C3 finding A): "Volumes 31 à aujourd'hui" fell through onto the base line,
# whose volumes stop at 30; its ISBNs sit on a SIBLING line (another article's "Vampire Reign"). Two lines
# then held every ISBN and stage 7b could not pick a successor. The base line lacks #31 -> held.
gser = "== Tomes 1 à 30 ==\n{{a}}\n== Volumes 31 à aujourd'hui ==\n{{b}}\n"
ser = RL.split(gser, "Seraph of the End", "Seraph of the End",
               [grec(30, "9784088835730", gser.index("{{a}}")), grec(31, "9784088836942", gser.index("{{b}}"))])
gvr = "== Seraph of the End: Vampire Reign ==\n{{a}}\n"
vr = RL.split(gvr, "Seraph of the End (en)", "Seraph of the End", [grec(31, "9784088836942", gvr.index("{{a}}"))])
eq("guard: Seraph of the End -- the ISBNs are on a sibling line, not the fall-through target -> held",
   sorted(RL.hold_clashes([("w_ser", vr), ("w_ser", ser)])), [(1, "Seraph of the End (Volumes 31 à aujourd'hui)")])

# Naruto (C3 finding B iii): the class-2 heading "Novelizations" made a NEW novel line under the ancestor
# heading's name ("Naruto (Fiction books)") that took the novel group's main slot and aliases from
# "Naruto (Original novels)". No novel line of the work holds its volumes -> held: old name, old medium,
# and its heading word back as line_raw (the heading alias).
gnar = "== Fiction books ==\n=== Original novels ===\n{{a}}\n=== Novelizations ===\n{{b}}\n"
nar = RL.split(gnar, "List of Naruto media", "Naruto",
               [grec(1, "9784087032208", gnar.index("{{a}}")), grec(1, "9784087032017", gnar.index("{{b}}")),
                grec(2, "9784087032024", gnar.index("{{b}}"))])
eq("guard: Naruto -- after the round the novelizations are a novel line named after the ancestor heading",
   [(r["medium"], r["line"]) for r in nar][1:], [("novel", "Naruto (Fiction books)")] * 2)
eq("guard: ... no existing line holds them -> held", sorted(RL.hold_clashes([("w_nar", nar)])), [(0, "Naruto (Novelizations)")])
eq("guard: ... hold() restores the old name, the old medium and the heading word (line_raw)",
   [(r["medium"], r["line"], r["line_raw"]) for r in RL.hold(nar, {"Naruto (Novelizations)"})][1:],
   [("manga", "Naruto (Novelizations)", "Novelizations")] * 2)

# a group that would become a NEW line (Angel Beats! "Related media": the article's only list) is held,
# even with no other row to clash with: a fall-through never creates a line
grel = "== Related media ==\n{{b}}\n"
ab = RL.split(grel, "Angel Beats!", "Angel Beats!", [grec(n, "97840486617%02d" % n, grel.index("{{b}}")) for n in (1, 2)])
eq("guard: a group whose fall-through would be a NEW line is held", sorted(RL.hold_clashes([("w_ab", ab)])),
   [(0, "Angel Beats! (Related media)")])
eq("guard: ... so is one whose licensed market has no line yet (the JP books are duplicates, the FR line would be new)",
   sorted(RL.hold_clashes([("w_g", RL.split(gsame, "Gosick", "Gosick", [
       grec(5, "9784047126930", gsame.index("{{a}}")),
       dict(grec(5, "9784047126930", gsame.index("{{b}}")),
            markets={"original": {"market": "JP", "isbn13": "9784047126930"},
                     "licensed": {"market": "FR", "isbn13": "9782811612345"}})]))])),
   [(0, "Gosick (Médias)")])
eq("guard: ... and with the FR line in the catalogue already (same ISBN) it falls through",
   RL.hold_clashes([("w_g", RL.split(gsame, "Gosick", "Gosick", [
       grec(5, "9784047126930", gsame.index("{{a}}")),
       dict(grec(5, "9784047126930", gsame.index("{{b}}")),
            markets={"original": {"market": "JP", "isbn13": "9784047126930"},
                     "licensed": {"market": "FR", "isbn13": "9782811612345"}})]))],
       existing=[("w_g", "manga", "FR", "Gosick", "5", "9782811612345")]), {})

# a fall-through never changes which line is main: the export makes the line named after the work main,
# else the biggest -- a duplicate may only fall onto the work's OWN line, never onto a sibling it could
# overtake or tie ("Gamaran - Le Tournoi ultime", an ancestor heading's line)
ganc = "== Le Tournoi ultime ==\n{{a}}\n=== Médias ===\n{{b}}\n"
anc = RL.split(ganc, "Gamaran", "Gamaran", [grec(1, "9784063842951", ganc.index("{{a}}")),
                                            grec(1, "9784063842951", ganc.index("{{b}}"))])
eq("guard: a duplicate onto a line not named after the work (an ancestor heading's) is held",
   sorted(RL.hold_clashes([("w_gam", anc)])), [(0, "Gamaran (Médias)")])

# ... nor in the medium it leaves: a class-2 group ("Roman", manga before the round) that duplicates the
# work's novel line takes its old manga line away. Fine when the work's manga line named after the work
# stays main (No. 6) or when it was the only manga line (Babylon); held when it could have been main of
# the manga lines left (no line named after the work among them)
grom = "== Roman ==\n{{b}}\n"
no6 = RL.split(grom, "No. 6 (roman)", "No. 6", [grec(1, "9784062125901", grom.index("{{b}}"))])
no6_novel = [("w_no6", "novel", "JP", "No. 6", "1", "9784062125901")]
eq("guard: a class-2 duplicate falls through when the work's own manga line stays (No. 6)",
   RL.hold_clashes([("w_no6", no6)], existing=no6_novel + [("w_no6", "manga", "JP", "No. 6", "1", "9784063144000")]), {})
eq("guard: ... or when its old manga line was the work's only one (Babylon)",
   RL.hold_clashes([("w_no6", no6)], existing=no6_novel), {})
eq("guard: ... and is held when the manga lines left have none named after the work",
   sorted(RL.hold_clashes([("w_no6", no6)], existing=no6_novel + [("w_no6", "manga", "JP", "No. 6 (Collections)", "1", "9784063144000")])),
   [(0, "No. 6 (Roman)")])

# a fall-through never re-parents: an arc split out of a group's rows points at the group's line
# (arc_of); if the group fell through, the arc would hang under the work's line instead -> held, and
# hold() points the arc back at the heading line (its pre-round parent)
garc2 = "== Books ==\n" + "".join("{{r%d}}\n" % n for n in range(1, 5))
def arow2(n, title, isbn):
    r = grec(n, isbn, garc2.index("{{r%d}}" % n))
    r["title"] = title
    return r
gmain2 = RL.split(gmain, "Foo (en)", "Foo", [grec(1, "9784000000011", gmain.index("{{a}}")),
                                             grec(2, "9784000000028", gmain.index("{{a}}"))])
arcs2 = RL.split(garc2, "Foo", "Foo", [arow2(1, "Foo 1", "9784000000011"), arow2(2, "Foo 2", "9784000000028"),
                                       arow2(3, "Foo: Bar 1", "9784000000035"), arow2(4, "Foo: Bar 2", "9784000000042")])
eq("guard: a group hosting an arc is held, even when its plain rows are duplicates",
   sorted(RL.hold_clashes([("w_foo", gmain2), ("w_foo", arcs2)])), [(1, "Foo (Books)")])
eq("guard: ... and hold() gives the arc rows their pre-round parent (the heading line)",
   [r.get("arc_of") for r in RL.hold(arcs2, {"Foo (Books)"})], [None, None, "Foo (Books)", "Foo (Books)"])

# a held class-2 group keeps its OLD medium as well as its old name: Hyouka's "Roman" list (tagged manga
# before the round) would land on the English article's JP novel line under other ISBNs -> held, it reloads
# as the manga line "Hyouka (Roman)" under its pre-round line id
groman = "== Roman ==\n{{b}}\n"
hy = RL.split(groman, "Hyouka", "Hyouka", [grec(n, "97840487361%02d" % n, groman.index("{{b}}")) for n in (3, 4)])
hy_held = RL.hold_clashes([("w_hy", hy)], existing=[("w_hy", "novel", "JP", "Hyouka", "3", "9784044271039"),
                                                    ("w_hy", "novel", "JP", "Hyouka", "4", "9784044271046")])
eq("guard: the Hyouka 'Roman' group (novel after the round) is held", sorted(hy_held), [(0, "Hyouka (Roman)")])
GROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(GROOT, "schema"))
from load import load as gload, _id as gid
hy_path = os.path.join(__import__("tempfile").mkdtemp(prefix="opentome-hy-"), "h.db")
hy_db = __import__("sqlite3").connect(hy_path)
hy_db.executescript(open(os.path.join(GROOT, "schema", "schema.sql"), encoding="utf8").read())
gload(hy_db, "Hyouka", RL.hold(hy, {"Hyouka (Roman)"}), work_key="k:hyouka")
eq("guard: the held group reloads as manga 'Hyouka (Roman)' under its pre-round line id",
   hy_db.execute("SELECT id, medium FROM release_line").fetchall(),
   [(gid("rl_", gid("w_", "k:hyouka"), "manga", "JP", "Hyouka (Roman)"), "manga")])
hy_db.close()

# split_arcs runs inside split(), after line_held is computed: an arc record keeps line_held (copied) but
# carries arc_of, and the guard and hold() skip arc records, so the arc name (from the row titles, never a
# heading) is the same held or not. Only the non-arc rows of the group take their heading name back.
garc = "== Books ==\n" + "".join("{{r%d}}\n" % n for n in range(1, 6))
def arow(n, title, isbn):
    r = grec(n, isbn, garc.index("{{r%d}}" % n))
    r["title"] = title
    return r
arcs = RL.split(garc, "Foo", "Foo", [arow(1, "Foo 1", "9784000000011"), arow(2, "Foo 2", "9784000000028"),
                                     arow(3, "Foo: Bar 1", "9784000000035"), arow(4, "Foo: Bar 2", "9784000000042")])
eq("arc + guard: the arc rows carry arc_of and still carry line_held", [(bool(r.get("arc_of")), bool(r.get("line_held"))) for r in arcs],
   [(False, True), (False, True), (True, True), (True, True)])
arc_line = arcs[2]["line"]
eq("arc + guard: an arc group is never held (only the plain group)",
   sorted(RL.hold_clashes([("w_foo", arcs)], existing=[("w_foo", "manga", "JP", "Foo", "1", "9784999999991")])), [(0, "Foo (Books)")])
eq("arc + guard: hold() renames the plain rows and leaves the arc rows exactly as split_arcs named them",
   [(r["line"], r["medium"]) for r in RL.hold(arcs, {"Foo (Books)"})],
   [("Foo (Books)", "manga")] * 2 + [(arc_line, "manga")] * 2)

# build_corpus wires it: every article is split first, then loaded with the held groups renamed.
import sqlite3, tempfile
import build_corpus as BC
gpages = {"No Game No Life": (gmain, [grec(n, "97840406611%02d" % n, gmain.index("{{a}}")) for n in (1, 2)]),
          "No Game No Life: Publications": (gpub, [grec(n, "97840406643%02d" % n, gpub.index("{{b}}")) for n in (1, 2, 3)]),
          "Dandadan": (gmain, [grec(21, "9784088825021", gmain.index("{{a}}"))]),
          "Liste des tomes de Dandadan": (gcont, [grec(1, "9784088825001", gcont.index("{{a}}")),
                                                  grec(21, "9784088825021", gcont.index("{{b}}"))])}
gident = {"en:No Game No Life": {"canonical": "k:ngnl", "titles": {"en": "No Game No Life"}},
          "en:No Game No Life: Publications": {"canonical": "k:ngnl", "titles": {"en": "No Game No Life"}},
          "en:Dandadan": {"canonical": "k:dd", "titles": {"en": "Dandadan"}},
          "en:Liste des tomes de Dandadan": {"canonical": "k:dd", "titles": {"en": "Dandadan"}}}
saved_bc = (BC.corpus, BC.wikitext, BC.parse_volumes, BC.load_identity)
BC.corpus = lambda lang: list(gpages)
BC.wikitext = lambda article, lang: gpages[article][0]
BC.parse_volumes = lambda w, article, lang: [dict(r) for r in gpages[article][1]]
BC.load_identity = lambda path=None: gident
gdb_path = os.path.join(tempfile.mkdtemp(prefix="opentome-guard-"), "c.db")
try:
    BC.main(gdb_path, langs=("en",))
finally:
    BC.corpus, BC.wikitext, BC.parse_volumes, BC.load_identity = saved_bc
gdb = sqlite3.connect(gdb_path)
eq("build_corpus: the held list is kept in meta corpus:held",
   __import__("json").loads(gdb.execute("SELECT value FROM meta WHERE key='corpus:held'").fetchone()[0]),
   [["en", "No Game No Life: Publications", "No Game No Life (Publication and conception)", 3]])
eq("build_corpus: the held group loads as its own line, the continuation into the work's line",
   sorted(gdb.execute("""SELECT c.value, COUNT(v.id) FROM release_line rl JOIN claim c ON c.entity='release_line'
                         AND c.entity_id=rl.id AND c.field='line_name' JOIN volume v ON v.release_line_id=rl.id
                         GROUP BY rl.id""")),
   [("Dandadan", 2), ("No Game No Life", 2), ("No Game No Life (Publication and conception)", 3)])
eq("build_corpus: no ISBN of either No Game No Life line was replaced",
   sorted(i for (i,) in gdb.execute("SELECT isbn13 FROM volume WHERE isbn13 LIKE '97840406%'")),
   ["9784040661101", "9784040661102", "9784040664301", "9784040664302", "9784040664303"])
gdb.close()
# a resumed build (KEEP_DB=1) compares against the catalogue's rows -- numbers without an ISBN too, so a
# volume without an ISBN can fall onto a number the catalogue's line already has
edb = sqlite3.connect(os.path.join(tempfile.mkdtemp(prefix="opentome-existing-"), "e.db"))
edb.executescript(open(os.path.join(GROOT, "schema", "schema.sql"), encoding="utf8").read())
gload(edb, "Dandadan", RL.split(gmain, "Dandadan", "Dandadan", [grec(20, "9784088825020", gmain.index("{{a}}")),
                                                                 grec(21, None, gmain.index("{{a}}"))]), work_key="k:dd")
eq("build_corpus: existing_rows lists the catalogue's numbers, with or without an ISBN",
   sorted(BC.existing_rows(edb), key=lambda r: r[4]),
   [(gid("w_", "k:dd"), "manga", "JP", "Dandadan", "20", "9784088825020"), (gid("w_", "k:dd"), "manga", "JP", "Dandadan", "21", None)])
edb.close()

# ---- work_title: French list articles (2026-09-25, alias-fix) -----------
# 'de' ate the start of 'des' ("s Enquêtes de Kindaichi" shipped as an alias); des/du now restore
# the title's own article, as to_mangarr.local_title does (the fragment is shared).
from build_corpus import work_title
eq("work_title: des restores Les (Kindaichi)", work_title("Liste des tomes des Enquêtes de Kindaichi"),
   "Les Enquêtes de Kindaichi")
eq("work_title: des restores Les (the measured Gouttes article)",
   work_title("Liste des chapitres des Gouttes de Dieu"), "Les Gouttes de Dieu")
eq("work_title: du restores Le", work_title("Liste des chapitres du Prince du tennis"), "Le Prince du tennis")
eq("work_title: a split part keeps its qualifier",
   work_title("Liste des chapitres des Enquêtes de Kindaichi (1re partie)"), "Les Enquêtes de Kindaichi (1re partie)")
eq("work_title: de unchanged", work_title("Liste des chapitres de L'Attaque des Titans"), "L'Attaque des Titans")
eq("work_title: d' unchanged", work_title("Liste des chapitres d'Ushio et Tora"), "Ushio et Tora")
eq("work_title: d’ unchanged", work_title("Liste des chapitres d’Ushio et Tora"), "Ushio et Tora")
eq("work_title: 'de la' unchanged (the article stays, as before)",
   work_title("Liste des volumes de la Rose de Versailles"), "la Rose de Versailles")
eq("work_title: English lists unchanged", work_title("List of One Piece chapters (1–186)"), "One Piece")

# ---- main-article detection -------------------------------------------
import main_titles as MT
eq("lead: first italic link when it names the work",
   MT.lead_link("''[[Attack on Titan]]'' is a manga", "Attack on Titan"), ("Attack on Titan", "Attack on Titan"))
eq("lead: magazine first, work later -> the work",
   MT.lead_link("''[[Weekly Shōnen Jump]]'' ran ''[[One Piece]]''", "One Piece"), ("One Piece", "One Piece"))
eq("lead: magazine only -> no main article",
   MT.lead_link("''[[Weekly Shōnen Jump]]'' only", "One Piece"), (None, None))
eq("lead: generic 'tankōbon' skipped",
   MT.lead_link("''[[tankōbon]]'' cover. ''[[Dragon Ball (manga)|Dragon Ball]]'' is", "Dragon Ball"),
   ("Dragon Ball (manga)", "Dragon Ball"))
eq("lead: italics inside the link display",
   MT.lead_link("[[Aria (manga)|''Aqua'' and ''Aria'']] is a manga", "Aria"), ("Aria (manga)", "Aqua and Aria"))
eq("lead: spin-off never takes its parent",
   MT.lead_link("''[[Dragon Ball (manga)|Dragon Ball]]'' sequel", "Dragon Ball Z"), (None, None))
eq("lead: no title -> first link (old behaviour)",
   MT.lead_link("''[[Weekly Shōnen Jump]]'' first", None), ("Weekly Shōnen Jump", "Weekly Shōnen Jump"))

# ---- main-article infobox --------------------------------------------
IB = """{{Infobox animanga/Header
| name = Test Work
| ja_kanji = テスト
| ja_romaji = Tesuto
| image = Test Work vol 1.jpg
| genre = {{ubl|[[Dark fantasy]]<ref>x</ref>|[[Adventure fiction|Adventure]]}}
}}
{{Infobox animanga/Print
| type = manga
| author = [[Kentaro Miura]]
| illustrator = [[Some Artist|Artist]]<br>[[Another]]
| imprint = [[Jets Comics]]
| publisher = {{ubl|[[Shueisha]]|[[Shueisha]] (bunko)}}
| publisher_en = {{English manga publisher|NA=[[Viz Media]]|UK=Viz Media}}
| demographic = [[Seinen manga|Seinen]]
| magazine = [[Weekly Young Jump]]
| first = September 8, 2011
| last = September 18, 2014
| volumes = 14
}}"""
mf = MA.parse_main(IB)
eq("infobox status ended", mf.get("status"), "ended")
eq("infobox first/last", (mf.get("first"), mf.get("last")), ("2011-09-08", "2014-09-18"))
eq("infobox volumes", mf.get("volumes"), 14)
eq("infobox publisher (first of list)", mf.get("publisher"), "Shueisha")
eq("infobox publisher_en (NA, unlinked)", mf.get("publisher_en"), "Viz Media")
for raw, want in [
    ("Tokyopop (former)<br />J-Novel Club", "J-Novel Club"),
    ("Tokyopop <small>(former)</small>", "Tokyopop"),
    ("Eclipse Comics (former)<br>Dark Horse (current)", "Dark Horse"),
    ("Kadokawa Shoten <small>(vol. 1-2)</small><br />Media Factory <small>(vol. 3-present)</small>", "Media Factory (vol. 3-present)"),
    ("Type-Moon <small>(original creator)</small><br>Kodansha <small>(commercial publisher)</small>", "Kodansha (commercial publisher)"),
    ("Coolmic (digital)<br>Seven Seas Entertainment (print)", "Seven Seas Entertainment (print)"),
    ("Moonlight Novels<br>(Shōsetsuka ni Narō)", "Moonlight Novels (Shōsetsuka ni Narō)"),
    ("Yen Press<br />Sol Press <small>(formerly)</small>", "Yen Press"),
    ("[[Viz Media]]}}<br>{{English manga publisher", "Viz Media"),
    ("Toyspress (former)}} [[Titan Publishing Group#Titan Manga", "Titan Manga"),
    ("[[Kodansha USA|Kodansha Comics]]<br>Tokyopop (former)", "Kodansha Comics"),
    ("Sun Magazine<br/>Ichijinsha<br>Futabasha", "Sun Magazine"),
    ("{{ubl|[[Shueisha]]|[[Shueisha]] (bunko)}}", "Shueisha"),
    ("", ""),
]:
    eq(f"publisher field {raw[:40]!r}", MA._publisher_field(raw), want)
eq("infobox demographic", mf.get("demographic"), "Seinen")
eq("infobox header name", mf.get("name"), "Test Work")
eq("infobox kanji/romaji", (mf.get("ja_kanji"), mf.get("ja_romaji")), ("テスト", "Tesuto"))
eq("infobox genres (list template, refs stripped)", mf.get("genre"), ["Dark fantasy", "Adventure"])
eq("infobox genres (plain list with a cite ref)", MA.parse_main(IB.replace("| genre = {{ubl|[[Dark fantasy]]<ref>x</ref>|[[Adventure fiction|Adventure]]}}",
   "| genre = [[Action fiction|Action]], [[Adventure]]<ref>{{cite web|url=https://www.madman.com.au/catalogue/view/19467|title=x|access-date=2018}}</ref>")).get("genre"), ["Action", "Adventure"])
eq("infobox genres (editor comment dropped)", MA.parse_main(IB.replace("| genre = {{ubl|[[Dark fantasy]]<ref>x</ref>|[[Adventure fiction|Adventure]]}}",
   "| genre = <!-- Note: Use\ncite reliable sources to identify genre -->{{ubl|[[Adventure fiction|Adventure]]|[[Fantasy]]}}")).get("genre"), ["Adventure", "Fantasy"])
TWO = IB + """
{{Infobox animanga/Print
| type = light novel
| volume_list = List of Test Work light novels
| first = 2009-04-10
| volumes = 29
| publisher = ASCII Media Works
}}"""
eq("infobox: the block whose volume_list is our list article wins", MA.parse_main(TWO, list_article="List of Test Work light novels").get("status"), "ongoing")
eq("infobox: without a list article the first block is used", MA.parse_main(TWO).get("status"), "ended")
eq("infobox author", mf.get("author"), ["Kentaro Miura"])
eq("infobox illustrators (<br> list)", mf.get("illustrator"), ["Artist", "Another"])
eq("infobox imprint", mf.get("imprint"), "Jets Comics")
eq("infobox image file", mf.get("image"), "Test Work vol 1.jpg")
import relations as REL
BN = {REL.norm(t): t for t in ("Attack on Titan", "Dragon Ball", "Bleach", "Blue", "Re:Zero")}
eq("relation: subtitle spin-off", REL.parent_of("Attack on Titan: Before the Fall", BN), ("Attack on Titan", "spin_off"))
eq("relation: Z sequel", REL.parent_of("Dragon Ball Z", BN), ("Dragon Ball", "sequel"))
eq("relation: Super sequel", REL.parent_of("Dragon Ball Super", BN), ("Dragon Ball", "sequel"))
eq("relation: same title is not its own parent", REL.parent_of("Bleach", BN), (None, None))
eq("relation: short parent ignored", REL.parent_of("Blue Lock", BN), (None, None))
eq("relation: plain word continuation is not a relation", REL.parent_of("Bleached Bones", BN), (None, None))
eq("publisher_en: lower-case, empty template -> none", MA._publisher_en("{{english manga publisher|NA=}}"), None)
eq("publisher_en: positional (One Piece shape)",
   MA._publisher_en("{{English manga publishers\n| AUS = [[Madman Entertainment]]\n| [[Northern America|NA]]/[[United Kingdom|UK]]|[[Viz Media]]\n}}"), "Viz Media")
eq("infobox ongoing when no last", MA.parse_main(IB.replace("| last = September 18, 2014\n", "")).get("status"), "ongoing")

# ---- line corrections ------------------------------------------------
import importlib.util, sqlite3
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("corrections", os.path.join(ROOT, "tier2", "corrections.py"))
corr = importlib.util.module_from_spec(spec); spec.loader.exec_module(corr)
cdb = sqlite3.connect(":memory:")
cdb.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
cdb.execute("INSERT INTO work(id,primary_title,created_at,updated_at) VALUES('w_t','Test Work','x','x')")
cdb.execute("INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at)"
            " VALUES('rl_jp','w_t','manga','JP','ja','x','x')")
LINE = {"work": "w_t", "market": "EN", "medium": "manga", "name": "Test Work", "publisher": "Seven Seas",
        "volumes": [{"number": "1", "isbn13": "978-1-64505-000-1", "release_date": "2020-10-06", "contains": [1]},
                    {"number": "2", "isbn13": "9798888779347", "release_date": "2021-02", "page_count": 180, "contains": [2, 3]}],
        "source_url": "https://example.test/series", "checked": "2026-09-04"}
corr.apply_line_corrections(cdb, entries=[LINE], verbose=False)
rid = corr._id("rl_", "w_t", "manga", "EN", "Test Work")
eq("line corr: line row", cdb.execute("SELECT market, language, publisher FROM release_line WHERE id=?", (rid,)).fetchone(),
   ("EN", "en", "Seven Seas"))
eq("line corr: name claim", cdb.execute("SELECT value, source FROM claim WHERE entity='release_line' AND entity_id=? AND field='line_name'", (rid,)).fetchone(),
   ("Test Work", "correction"))
eq("line corr: volumes", cdb.execute("SELECT number, isbn13, release_date, release_date_precision, page_count FROM volume WHERE release_line_id=? ORDER BY number", (rid,)).fetchall(),
   [("1", "9781645050001", "2020-10-06", "day", None), ("2", "9798888779347", "2021-02", "month", 180)])
eq("line corr: overrides + claims per value",
   (cdb.execute("SELECT COUNT(*) FROM override WHERE entity='volume'").fetchone()[0],
    cdb.execute("SELECT COUNT(*) FROM claim WHERE entity='volume' AND source='correction'").fetchone()[0]), (5, 5))
eq("line corr: composition points at the JP line",
   cdb.execute("SELECT ref_list, ref_line_id FROM composition c JOIN volume v ON v.id=c.volume_id WHERE v.release_line_id=? ORDER BY v.number", (rid,)).fetchall(),
   [("[1]", "rl_jp"), ("[2, 3]", "rl_jp")])
corr.apply_line_corrections(cdb, entries=[LINE], verbose=False)
eq("line corr: idempotent", cdb.execute("SELECT COUNT(*) FROM volume").fetchone()[0], 2)
try:
    corr.apply_line_corrections(cdb, entries=[dict(LINE, name="Other", volumes=[{"number": "1", "isbn13": "9784063842760"}])], verbose=False)
    eq("line corr: JP ISBN on an EN line rejected", "no error", "ValueError")
except ValueError:
    eq("line corr: JP ISBN on an EN line rejected", True, True)

# ---- origin_line pin (Mushoku Tensei "Roxy Gets Serious": two JP lines share
# (work, medium), so the naive "any JP line" query above is ambiguous -- an
# entry can name the exact one) ---------------------------------------------
cdb.execute("INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at)"
            " VALUES('rl_jp2','w_t','manga','JP','ja','x','x')")
PINNED = dict(LINE, name="Pinned Work", origin_line="rl_jp2")
corr.apply_line_corrections(cdb, entries=[PINNED], verbose=False)
prid = corr._id("rl_", "w_t", "manga", "EN", "Pinned Work")
eq("origin_line pin: composition points at the PINNED line, not rl_jp",
   cdb.execute("SELECT ref_list, ref_line_id FROM composition c JOIN volume v ON v.id=c.volume_id "
              "WHERE v.release_line_id=? ORDER BY v.number", (prid,)).fetchall(),
   [("[1]", "rl_jp2"), ("[2, 3]", "rl_jp2")])
eq("origin_line pin: claim written",
   cdb.execute("SELECT value, source FROM claim WHERE entity='release_line' AND entity_id=? AND field='origin_line'",
              (prid,)).fetchone(),
   ("rl_jp2", "correction"))
try:
    corr.apply_line_corrections(cdb, entries=[dict(LINE, name="Bad Origin A", origin_line="rl_does_not_exist")], verbose=False)
    eq("origin_line pin: nonexistent line rejected", "no error", "SystemExit")
except SystemExit:
    eq("origin_line pin: nonexistent line rejected", True, True)
cdb.execute("INSERT INTO work(id,primary_title,created_at,updated_at) VALUES('w_other','Other Work','x','x')")
cdb.execute("INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at)"
            " VALUES('rl_other_work','w_other','manga','JP','ja','x','x')")
try:
    corr.apply_line_corrections(cdb, entries=[dict(LINE, name="Bad Origin B", origin_line="rl_other_work")], verbose=False)
    eq("origin_line pin: line on a different work rejected", "no error", "ValueError")
except ValueError:
    eq("origin_line pin: line on a different work rejected", True, True)
cdb.execute("INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at)"
            " VALUES('rl_jp_novel','w_t','light_novel','JP','ja','x','x')")
try:
    corr.apply_line_corrections(cdb, entries=[dict(LINE, name="Bad Origin C", origin_line="rl_jp_novel")], verbose=False)
    eq("origin_line pin: line with a different medium rejected", "no error", "ValueError")
except ValueError:
    eq("origin_line pin: line with a different medium rejected", True, True)
try:
    corr.apply_line_corrections(cdb, entries=[dict(LINE, name="Bad Origin D", origin_line=prid)], verbose=False)
    eq("origin_line pin: non-origin-market (EN) line rejected", "no error", "ValueError")
except ValueError:
    eq("origin_line pin: non-origin-market (EN) line rejected", True, True)

# ---- medium override (2026-09-23 follow-up: the Denma orig_series_id defect) --
# Denma's shape: three already-cataloged lines (JP/EN/KR), all tagged plain
# 'manga' upstream (no medium hint), so pick_origin's step 2 (earliest date)
# picks JP even though the work is Korean in origin. The fix is a correction
# that retags the medium WITHOUT re-keying the line (medium is hashed into the
# id -- see _id() below -- so a fresh id computed from the new medium would not
# match the real line and would create a duplicate).
cdb.execute("INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at)"
            " VALUES('rl_kr','w_t','manga','KR','ko','x','x')")
before_ids = {r[0] for r in cdb.execute("SELECT id FROM release_line WHERE work_id='w_t'")}
MEDIUM_OVERRIDE = [
    {"line": "rl_jp", "medium": "manhwa", "source_url": "https://example.test/medium", "checked": "2026-09-23"},
    {"line": rid, "medium": "manhwa", "source_url": "https://example.test/medium", "checked": "2026-09-23"},
    {"line": "rl_kr", "medium": "manhwa", "source_url": "https://example.test/medium", "checked": "2026-09-23"},
]
corr.apply_line_corrections(cdb, entries=MEDIUM_OVERRIDE, verbose=False)
after_ids = {r[0] for r in cdb.execute("SELECT id FROM release_line WHERE work_id='w_t'")}
eq("medium override: ids unchanged", after_ids, before_ids)
eq("medium override: medium updated on all three lines",
   sorted(v for (v,) in cdb.execute("SELECT medium FROM release_line WHERE id IN ('rl_jp', ?, 'rl_kr')", (rid,))),
   ["manhwa", "manhwa", "manhwa"])
corr.apply_line_corrections(cdb, entries=MEDIUM_OVERRIDE, verbose=False)
eq("medium override: idempotent (still 3 lines, still manhwa)",
   cdb.execute("SELECT COUNT(*) FROM release_line WHERE work_id='w_t' AND medium='manhwa'").fetchone()[0], 3)
try:
    corr.apply_line_corrections(cdb, entries=[{"line": "rl_does_not_exist", "medium": "manhwa",
                                               "source_url": "https://example.test/medium", "checked": "2026-09-23"}],
                                verbose=False)
    eq("medium override: stale line rejected", "no error", "SystemExit")
except SystemExit:
    eq("medium override: stale line rejected", True, True)
try:
    corr.apply_line_corrections(cdb, entries=[{"line": "rl_jp", "medium": "not_a_medium",
                                               "source_url": "https://example.test/medium", "checked": "2026-09-23"}],
                                verbose=False)
    eq("medium override: unknown medium rejected", "no error", "ValueError")
except ValueError:
    eq("medium override: unknown medium rejected", True, True)

# ---- market override (2026-09-23 cleanup, item 3: Denma's mislabelled "ja" line) --
MARKET_OVERRIDE = [{"line": "rl_jp", "market": "KR",
                    "source_url": "https://example.test/market", "checked": "2026-09-23"}]
corr.apply_line_corrections(cdb, entries=MARKET_OVERRIDE, verbose=False)
eq("market override: market + language updated",
   cdb.execute("SELECT market, language FROM release_line WHERE id='rl_jp'").fetchone(),
   ("KR", "ko"))
eq("market override: id unchanged", cdb.execute("SELECT 1 FROM release_line WHERE id='rl_jp'").fetchone(), (1,))
corr.apply_line_corrections(cdb, entries=MARKET_OVERRIDE, verbose=False)
eq("market override: idempotent",
   cdb.execute("SELECT market FROM release_line WHERE id='rl_jp'").fetchone(), ("KR",))
try:
    corr.apply_line_corrections(cdb, entries=[{"line": "rl_does_not_exist", "market": "KR",
                                               "source_url": "https://example.test/market", "checked": "2026-09-23"}],
                                verbose=False)
    eq("market override: stale line rejected", "no error", "SystemExit")
except SystemExit:
    eq("market override: stale line rejected", True, True)
try:
    corr.apply_line_corrections(cdb, entries=[{"line": "rl_jp", "market": "XX",
                                               "source_url": "https://example.test/market", "checked": "2026-09-23"}],
                                verbose=False)
    eq("market override: unknown market rejected", "no error", "ValueError")
except ValueError:
    eq("market override: unknown market rejected", True, True)
try:
    corr.apply_line_corrections(cdb, entries=[{"line": "rl_jp",
                                               "source_url": "https://example.test/x", "checked": "2026-09-23"}],
                                verbose=False)
    eq("neither medium nor market nor volumes rejected", "no error", "ValueError")
except ValueError:
    eq("neither medium nor market nor volumes rejected", True, True)

# ---- exclusion (2026-09-23 cleanup: The Walking Dead is not in scope) --------
cdb.execute("INSERT INTO work(id,primary_title,created_at,updated_at) VALUES('w_x','Excluded Work','x','x')")
cdb.execute("INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at)"
            " VALUES('rl_x1','w_x','manga','EN','en','x','x')")
cdb.execute("INSERT INTO volume(id,release_line_id,number,created_at,updated_at)"
            " VALUES('v_x1','rl_x1','1','x','x')")
cdb.execute("INSERT INTO composition(volume_id,contains,ref_list) VALUES('v_x1','volume','[1]')")
cdb.execute("INSERT INTO claim(entity,entity_id,field,value,source,licence,retrieved_at)"
            " VALUES('volume','v_x1','release_date','2020-01-01','wikipedia','facts_only','x')")
cdb.execute("INSERT INTO claim(entity,entity_id,field,value,source,licence,retrieved_at)"
            " VALUES('release_line','rl_x1','line_name','Excluded Work','wikipedia','facts_only','x')")
cdb.execute("INSERT INTO work_title(work_id,language,title,kind) VALUES('w_x','en','Excluded Work','official')")
EXCLUSION = [{"work": "w_x", "source_url": "https://example.test/excluded", "checked": "2026-09-23"}]
corr.apply_exclusions(cdb, entries=EXCLUSION, verbose=False)
eq("exclusion: work row gone", cdb.execute("SELECT 1 FROM work WHERE id='w_x'").fetchone(), None)
eq("exclusion: release_line gone", cdb.execute("SELECT 1 FROM release_line WHERE id='rl_x1'").fetchone(), None)
eq("exclusion: volume gone", cdb.execute("SELECT 1 FROM volume WHERE id='v_x1'").fetchone(), None)
eq("exclusion: composition gone", cdb.execute("SELECT 1 FROM composition WHERE volume_id='v_x1'").fetchone(), None)
eq("exclusion: claims gone",
   cdb.execute("SELECT COUNT(*) FROM claim WHERE entity_id IN ('v_x1','rl_x1')").fetchone()[0], 0)
eq("exclusion: work_title gone", cdb.execute("SELECT 1 FROM work_title WHERE work_id='w_x'").fetchone(), None)
eq("exclusion: unrelated work untouched", cdb.execute("SELECT 1 FROM work WHERE id='w_t'").fetchone(), (1,))
# NOT idempotent within one already-built db, unlike the UPDATE-based medium
# override: a DELETE has nothing to re-apply. That's fine -- corrections run
# once per rebuild, against a freshly built db where the work always exists
# again (same as every other stage). Calling it twice on the same db state IS
# a stale correction: the work really is gone.
try:
    corr.apply_exclusions(cdb, entries=[{"work": "w_does_not_exist",
                                         "source_url": "https://example.test/excluded", "checked": "2026-09-23"}],
                          verbose=False)
    eq("exclusion: stale work rejected", "no error", "SystemExit")
except SystemExit:
    eq("exclusion: stale work rejected", True, True)

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1)
print("all parser tests passed")
