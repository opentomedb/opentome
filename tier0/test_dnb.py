"""Unit tests for the DNB stage (tier0/dnb_*.py, tier0/build_dnb.py). Run: python3 tier0/test_dnb.py

No network: synthetic MARC records shaped like the ones the 2026-09-24 spike read, an
in-memory catalogue built from schema/schema.sql, and DNB_OFFLINE=1 as a backstop.
"""
import datetime, json, os, sqlite3, sys, tempfile

os.environ["DNB_OFFLINE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import dnb_marc as M
import dnb_link as L
import build_dnb as B

FAILS = []
Y = datetime.date.today().year


def eq(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok:
        FAILS.append(label)


def rec(idn, *fields, year="2019", ann=False, parent=False):
    """A record: fields are (tag, [(code, value), ...])."""
    leader = "00000nam a22000008" if ann else "00000pam a2200000 "
    leader += "c" + ("a" if parent else "c") + "4500"
    leader = leader[:17] + ("8" if ann else " ") + leader[18:19] + ("a" if parent else "c") + leader[20:]
    return {"leader": leader, "cf": {"001": idn, "008": "190101s%s    gw ||||| |||| 00||||ger  " % year},
            "df": [(t, " ", " ", list(s)) for t, s in fields]}


JPN = ("041", [("a", "ger"), ("h", "jpn")])
MANGA = ("082", [("a", "741.5")])

# ---- parsing an SRU response -----------------------------------------------------------
XML = """<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/"><numberOfRecords>1</numberOfRecords>
<records><record><recordData><record xmlns="http://www.loc.gov/MARC21/slim" type="Bibliographic">
<leader>00000pam a2200000 cc4500</leader><controlfield tag="001">1355602858</controlfield>
<controlfield tag="008">250207s2025    gw ||||| |||| 00||||ger  </controlfield>
<datafield tag="245" ind1="1" ind2="0"><subfield code="a">\x98Die\x9c Snowball earth</subfield>
<subfield code="n">8</subfield></datafield>
<datafield tag="773" ind1="0" ind2="8"><subfield code="q">18</subfield><subfield code="w">(DE-101)1272267156</subfield></datafield>
</record></recordData></record></records></searchRetrieveResponse>"""
rs = M.records(XML)
eq("records parsed", len(rs), 1)
eq("idn", M.idn(rs[0]), "1355602858")
eq("non-sort markers stripped", M.clean(M.first(rs[0], "245", "a")), "Die Snowball earth")
eq("773$w parent idn", M.parent_idns(rs[0]), ["1272267156"])
eq("year from 008", M.year(rs[0]), "2025")
eq("deposited record is not an announcement", M.is_announcement(rs[0]), False)

# ---- volume numbers ----------------------------------------------------------------------
for raw, want in (("1.", ("1", "int")), ("01", ("1", "int")), ("Vol. 3", ("3", "int")),
                  ("Band 12", ("12", "int")), ("[...]", (None, "none")), ("1 - 3", ("1-3", "range")),
                  ("7.5", ("7.5", "decimal")), ("Teil 2", ("2", "int")), ("# 7", ("7", "int")),
                  ("2. / [Aus dem Japan. von X]", ("2", "int")), ("Bd. 3. / [Textbearb.: Y]", ("3", "int")),
                  ("Númer 5", ("5", "int")), ("Song 2.", ("2", "int")), ("23 : Rubin und Saphir", ("23", "int"))):
    eq("canon_number %r" % raw, M.canon_number(raw), want)
r = rec("1", ("245", [("a", "Naruto"), ("n", "5")]), ("490", [("a", "Naruto"), ("v", "6")]))
eq("245$n wins over 490$v", M.volume_number(r)[:2], ("5", "int"))
r = rec("1", ("245", [("a", "Die Monster Mädchen – Band 21")]), ("490", [("a", "Die Monster Mädchen"), ("v", "21")]))
eq("the 245$a number when no 245$n (agrees with 490$v)", M.volume_number(r)[:2], ("21", "int"))
r = rec("1", ("245", [("a", "Car Crush 02")]))
eq("trailing number in 245$a", M.volume_number(r), ("2", "int", "title"))
eq("bare title strips it", M.bare_title(r), "Car Crush")
r = rec("1", ("245", [("a", "Kaiju No. 8 – Band 16 (Finale)")]))
eq("'Band N' inside 245$a", (M.volume_number(r)[:2], M.bare_title(r)), (("16", "int"), "Kaiju No. 8"))
r = rec("1", ("245", [("a", "Record of Ragnarok 11")]), ("490", [("a", "Record of Ragnarok"), ("v", "23")]))
eq("245$a is '<series> N' and 490$v disagrees: the title wins", M.volume_number(r)[:2], ("11", "int"))
r = rec("1", ("245", [("a", "No. 6")]), ("490", [("a", "No. 6"), ("v", "3")]))
eq("a title that ends in a number ('No. 6', $v 3): the series count", M.volume_number(r)[:2], ("3", "int"))
r = rec("1", ("245", [("a", "Auf in die Zone 7")]), ("490", [("a", "Toriko"), ("v", "33")]))
eq("a chapter title with a number (Toriko $v 33): the series count", M.volume_number(r)[:2], ("33", "int"))
r = rec("1", ("245", [("a", "Traum und Realität")]), ("490", [("a", "Action")]))
eq("490 without $v is an imprint, not a series", (M.series_statements(r), M.volume_number(r)[1]), ([], "none"))

eq("NFD from DNB is NFC after parsing", M.first(M.records(XML.replace("Snowball earth", "Ma\u0308dchen"))[0], "245", "a"),
   "\x98Die\x9c M\u00e4dchen")
eq("an NFD 300$a still counts the unnumbered pages",
   M.pages(M.records(XML.replace("</record></recordData>",
        '<datafield tag="300"><subfield code="a">128 Seiten, 39 ungeza\u0308hlte Seiten</subfield></datafield>'
        '</record></recordData>'))[0]), 167)

# ---- pages -----------------------------------------------------------------------------------
for raw, want in (("158 Seiten", 158), ("180 Seiten, 10 ungezählte Seiten", 190), ("circa 200 Seiten", 200),
                  ("[192] S.", 192), ("192 S.", 192), ("96 ungezählte Seiten", 96), ("1 Band", None),
                  ("192, [8] S.", 200)):
    eq("pages %r" % raw, M.pages(rec("1", ("300", [("a", raw)]))), want)

# ---- dates -----------------------------------------------------------------------------------
eq("263 planned month", M.planned_month(rec("1", ("263", [("a", "202702")]))), "2027-02")
eq("263 bad month ignored", M.planned_month(rec("1", ("263", [("a", "202713")]))), None)
eq("announcement = leader/17 '8'", M.is_announcement(rec("1", ann=True)), True)

# ---- origin, classification -----------------------------------------------------------------------
eq("041$h jpn", M.origin_in_scope(rec("1", JPN)), True)
eq("041$h kor is out (the KR/CN round)", M.origin_in_scope(rec("1", ("041", [("a", "ger"), ("h", "kor")]))), False)
eq("no 041, 'aus dem Japanischen'", M.origin_in_scope(
    rec("1", ("245", [("a", "X"), ("c", "Autor ; aus dem Japanischen von Y")]))), True)
eq("no 041, 'aus dem Koreanischen'", M.origin_in_scope(
    rec("1", ("245", [("a", "X"), ("c", "Text: A ; aus dem Koreanischen von Y")]))), False)
eq("no 041, abbreviated 'Aus dem Japan.' is Japanese", M.origin_in_scope(
    rec("1", ("245", [("a", "Beck"), ("c", "Harold Sakuishi. [Aus dem Japan. von Claudia Peter]")]))), True)
eq("no 041, keyword Manhwa", M.origin_in_scope(rec("1", ("653", [("a", "Manhwa")]))), False)
eq("no 041, nothing said: unknown origin stays in scope (the linker decides)",
   M.origin_in_scope(rec("1", ("245", [("a", "X")]))), True)
eq("old DNB subject group 08 -> manga", M.classify(rec("1", ("082", [("a", "08")]))), "manga")
eq("'Starter Pack' is a bundle", M.classify(rec("1", MANGA, ("245", [("a", "Hatsu Haru Starter Pack")]))), "bundle")
eq("741.5 -> manga", M.classify(rec("1", MANGA)), "manga")
eq("GND content 'Comic' -> manga", M.classify(rec("1", ("655", [("a", "Comic")]))), "manga")
eq("Thema FYS -> light novel", M.classify(rec("1", ("926", [("a", "FYS")]), ("926", [("a", "XAM")]))), "light_novel")
eq("XAM + 'Light Novel' keyword -> light novel (XAM != manga)",
   M.classify(rec("1", ("926", [("a", "XAMG")]), ("653", [("a", "Light Novel")]))), "light_novel")
eq("741.5 + 'Light Novel' keyword stays manga (an adaptation)",
   M.classify(rec("1", MANGA, ("653", [("a", "Light Novel")]))), "manga")
eq("XAM alone -> manga", M.classify(rec("1", ("926", [("a", "XAMH")]))), "manga")
eq("VLB-WN 2182 -> manga", M.classify(rec("1", ("653", [("a", "(VLB-WN)2182: Taschenbuch / Manga")]))), "manga")
eq("Malbuch -> extra", M.classify(rec("1", MANGA, ("245", [("a", "Kleine Katze Chi – Das Malbuch")]))), "extra")
eq("Bundle -> bundle", M.classify(rec("1", MANGA, ("245", [("a", "Naruto Bundle 1-3")]))), "bundle")
for t in ("Colette beschließt zu sterben Double Pack 01 & 02", "Kakegurui Doppelpack", "Naruto 3er-Pack",
          "Sailor Moon Schmuckbox", "DuskMaiden of Amnesia - Einsteigerset", "Frieren mit Dekorama",
          "Spy x Family 10 mit Acryl-Aufsteller"):
    eq("bundle: %s" % t, M.classify(rec("1", MANGA, ("245", [("a", t)]))), "bundle")
eq("bundle: 'Schuber' inside a word (250 Schuberauflage)",
   M.classify(rec("1", MANGA, ("250", [("a", "1. Schuberauflage")]))), "bundle")
for t in ("Card captor Sakura Tarot-Buch", "One Piece Guidebook"):
    eq("extra: %s" % t, M.classify(rec("1", MANGA, ("245", [("a", t)]))), "extra")
BOXI, OWN = "9783755504245", "9783770498574"
boxchild = rec("1", MANGA, ("020", [("a", BOXI), ("c", "Broschur in Behältnis")]), ("020", [("a", "3755504243")]))
eq("a record whose only ISBN is the box's (13 and 10 digit) is a box, not a volume",
   (M.isbns(boxchild), M.boxed(boxchild), M.classify(boxchild)), ([], True, "bundle"))
sold_in_box = rec("1", MANGA, ("020", [("a", BOXI), ("q", "Kassette 1"), ("c", ", in Schuber, kart.")]),
                  ("020", [("a", OWN), ("c", "kart.")]))
eq("a volume with its own ISBN that was also sold in a box keeps its own ISBN and is a volume",
   (M.isbns(sold_in_box), M.classify(sold_in_box)), ([OWN], "manga"))
eq("a set record with 'N Bände' alone is not a box", M.box_parent(rec("1", ("300", [("a", "9 Bände")]), parent=True)), False)
eq("a set record 'in Behältnis' is a box",
   M.box_parent(rec("1", ("300", [("a", "9 Bände"), ("c", "18 cm, Behältnis 19 x 14 x 13 cm")]), parent=True)), True)
eq("no signal -> other", M.classify(rec("1", ("245", [("a", "Naokos Lächeln")]))), "other")
eq("250 Massiv -> edition", M.edition_marker(rec("1", ("250", [("a", "Massiv")]))), "massiv")
eq("no edition marker", M.edition_marker(rec("1", ("250", [("a", "1. Auflage")]))), None)
r = rec("1", ("100", [("a", "Oda, Eiichirō"), ("4", "aut")]), ("700", [("a", "Bockel, Antje"), ("4", "trl")]),
        ("700", [("a", "Dokico"), ("4", "edt")]))
eq("creators: translator and editor excluded", M.creators(r), ["Oda, Eiichirō"])
eq("original titles: 240, 245$b '='", M.original_titles(rec("1", ("240", [("a", "Wan pīsu")]),
   ("245", [("a", "One Piece"), ("b", "= Wan pīsu 2")]), ("245", [("b", "sexy | Harem")]))),
   ["Wan pīsu", "Wan pīsu 2"])


# ---- twins, dates, lines ----------------------------------------------------------------------
def vol(idn, num, isbn, series=None, parent=None, ann=False, year="2019", extra=()):
    f = [JPN, MANGA, ("245", [("a", series or "Snowball earth")] + ([("n", num)] if num else [])),
         ("264", [("b", "Altraverse GmbH")])]
    if isbn:
        f.append(("020", [("a", isbn)]))
    if parent:
        f.append(("773", [("w", "(DE-101)" + parent)]))
    return rec(idn, *(f + list(extra)), ann=ann, year=year)


I1, I2, I3 = "9783753935874", "9783753935881", "9783753935898"
recs = {r["cf"]["001"]: r for r in (
    vol("1300000001", "1", I1, parent="1200000000", ann=True),          # pre-publication record ...
    vol("1300000002", "1", I1, parent="1200000000"),                    # ... and its deposit copy
    vol("1300000003", "2", I2, parent="1200000000"),
    vol("1300000004", "3", I2, parent="1200000000"),                    # box-set ISBN shared by 2 and 3
)}
kept, drop = B.select(recs)
groups, boxset = B.twins(kept)
eq("twins merged by ISBN", len(groups), 3)
eq("box-set ISBN detected", boxset, {I2})
col = {r["cf"]["001"]: r for r in (vol("1310000001", "1", I3, parent="1210000000", series="Alpha"),
                                   vol("1310000002", "1", I3, parent="1220000000", series="Beta"))}
k2, _ = B.select(col)
g2, drop2 = B.twins(k2)
eq("one ISBN on records of two different sets with different titles: not twins, ISBN dropped",
   (len(g2), I3 in drop2), (2, True))
g1 = next(g for g in groups if g["num"] == "1")
eq("deposit copy is the primary", g1["primary"], "1300000002")
eq("box-set ISBN dropped from its volumes", sorted(g["isbn"] or "-" for g in groups if g["num"] in ("2", "3")), ["-", "-"])
eq("published year from the deposited record", g1["date"], ("2019", "year", "published"))


def m(r):
    return {"r": r, "ann": M.is_announcement(r)}


eq("announcement-only, 263 this year -> projected month",
   B.group_date([m(rec("1", ("263", [("a", "%d03" % Y)]), ann=True, year=str(Y)))]), ("%d-03" % Y, "month", "projected"))
eq("announcement-only, future year -> held back",
   B.group_date([m(rec("1", ("263", [("a", "%d02" % (Y + 1))]), ann=True, year=str(Y + 1)))])[0], "HELD")
old = datetime.date.today().replace(day=1) - datetime.timedelta(days=500)
eq("announcement-only, 263 more than 12 months past -> the date is dropped",
   B.group_date([m(rec("1", ("263", [("a", old.strftime("%Y%m"))]), ann=True, year=str(old.year)))]), None)
eq("announcement-only, no 263 -> undated",
   B.group_date([m(rec("1", ann=True, year=str(Y - 1)))]), None)

parent = rec("1200000000", JPN, ("245", [("a", "Snowball earth")]), ("264", [("b", "Altraverse GmbH")]), parent=True)
more = {r["cf"]["001"]: r for r in (
    vol("1400000001", "4", "9783753935904", series="Snowball earth",
        extra=[("490", [("a", "Snowball earth"), ("v", "4")])]),              # series-keyed, folds into the parent
    vol("1400000002", "1", "9783753935911", series="Snowball earth",
        extra=[("490", [("a", "Snowball earth"), ("v", "1")]), ("250", [("a", "Deluxe Edition")])]),
    vol("99286450X", "1", "9783753935928", series="Snowball earth",
        extra=[("490", [("a", "Snowball earth"), ("v", "1")]), ("926", [("a", "FYS")])]),
)}
kept, _ = B.select(dict(recs, **more))
groups, _ = B.twins(kept)
lines = B.cluster(groups, {"1200000000": parent})
keys = sorted(lines)
eq("series cluster folds into the parent line; edition and medium stay apart",
   sorted((k, sorted(g["num"] for g in gs)) for k, gs in lines.items()),
   sorted([("dnb:1200000000", ["1", "2", "3", "4"]), ("dnb:1400000002", ["1"]), ("dnb:99286450X", ["1"])]))
eq("lowest IDN compares as a number ('99286450X' < '1400000002')",
   min(["1400000002", "99286450X"], key=B.idn_key), "99286450X")
eq("publisher family: KAZÉ = Crunchyroll = Pegasus = VIZ Media Switzerland",
   {B.pubkey(p) for p in ("KAZÉ Manga", "Crunchyroll Manga", "Pegasus Manga GmbH", "VIZ Media Switzerland SA")}, {"kaze"})


def kvol(idn, num, isbn, parent, pub):
    return rec(idn, JPN, MANGA, ("245", [("a", "Ragna Crimson"), ("n", num)]), ("264", [("b", pub)]),
               ("020", [("a", isbn)]), ("773", [("w", "(DE-101)" + parent)]))


def kpar(idn, pub):
    return rec(idn, JPN, ("245", [("a", "Ragna Crimson")]), ("264", [("b", pub)]), parent=True)


ks = {r["cf"]["001"]: r for r in (kvol("1800000001", "7", "9782889216796", "1700000100", "KAZÉ Manga"),
                                  kvol("1800000002", "13", "9782889216802", "1700000200", "Crunchyroll Manga"),
                                  kvol("1800000003", "16", "9782889216819", "1700000300", "Pegasus Manga"),
                                  kvol("1800000004", "7", "9783753936000", "1700000400", "KAZÉ Manga"))}
kp = {"1700000100": kpar("1700000100", "KAZÉ Manga"), "1700000200": kpar("1700000200", "Crunchyroll Manga"),
      "1700000300": kpar("1700000300", "Pegasus Manga"), "1700000400": kpar("1700000400", "KAZÉ Manga")}
kk, _ = B.select(ks)
kg, _ = B.twins(kk)
kl = B.cluster(kg, kp)
eq("one series across publisher rebrands (disjoint numbers) is one line; a set repeating a number stays apart",
   sorted((k, sorted(g["num"] for g in gs)) for k, gs in kl.items()),
   [("dnb:1700000100", ["13", "16", "7"]), ("dnb:1700000400", ["7"])])
ln, lost = B.shape_line("dnb:1200000000", lines["dnb:1200000000"], {"1200000000": parent})
eq("line named from the parent record", ln["name"], "Snowball earth")
eq("one volume per number", sorted(g["number"] for g in ln["vols"]), ["1", "2", "3", "4"])
dup = [vol("1500000001", "1", "9783753935935"), vol("1500000002", "1", "9783753935942")]
kept, _ = B.select({r["cf"]["001"]: r for r in dup})
groups, _ = B.twins(kept)
ln2, lost2 = B.shape_line("dnb:x", groups, {})
eq("duplicate number: lowest IDN kept, the other dropped",
   ([g["primary"] for g in ln2["vols"]], [f for _, f in lost2]), (["1500000001"], ["dropped_duplicate_number"]))
one = [rec("1600000001", JPN, MANGA, ("245", [("a", "Gogo monster")]), ("020", [("a", "9783956401237")]))]
kept, _ = B.select({r["cf"]["001"]: r for r in one})
groups, _ = B.twins(kept)
eq("an unnumbered one-shot is volume 1", B.shape_line("dnb:1600000001", groups, {})[0]["vols"][0]["number"], "1")

# ---- linker ----------------------------------------------------------------------------------
cat = sqlite3.connect(":memory:")
cat.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
T = "2026-01-01"
for wid, title in (("w_op", "One Piece"), ("w_opher", "One Piece: Heroines"), ("w_gs", "Goblin Slayer"),
                   ("w_sa1", "Shadow Star"), ("w_sa2", "Narutaru"), ("w_long", "Overpowered and Underpaid: An OP Swordmaster"),
                   ("w_se", "Snowball Earth")):
    cat.execute("INSERT INTO work(id,primary_title,created_at,updated_at) VALUES(?,?,?,?)", (wid, title, T, T))
cat.execute("INSERT INTO work_title VALUES('w_op','ja','Wan Pīsu','official')")
cat.execute("INSERT INTO work_title VALUES('w_sa1','en','Narutaru','official')")
cat.execute("INSERT INTO work_title VALUES('w_gs','en','Priestess','alias')")
for wid, who in (("w_op", "Eiichiro Oda"), ("w_gs", "Kumo Kagyu"), ("w_long", "Mikoto Takano"),
                 ("w_se", "Yuhiro Tsujitsugu")):
    cat.execute("INSERT INTO claim VALUES('work',?,'author',?,'wikipedia',NULL,'facts_only',?)", (wid, json.dumps([who]), T))
idx = L.Index(cat)
eq("high: official title + author", L.link(idx, ["One Piece 12"], ["Oda, Eiichirō"])[:2], ("high", "w_op"))
eq("high via the romaji (macron fold)", L.link(idx, ["Wan pīsu"], ["Oda, Eiichiro"])[:2], ("high", "w_op"))
eq("medium: official title, no author evidence", L.link(idx, ["Snowball earth"], [])[:2], ("medium", "w_se"))
eq("ambiguous: two works answer the title, no author", L.link(idx, ["Narutaru"], [])[0], "ambiguous")
eq("medium: truncated original title + author (prefix)",
   L.link(idx, ["Overpowered and Underpaid"], ["Takano, Mikoto"], orig=["Overpowered and Underpaid"])[:2],
   ("medium", "w_long"))
eq("a German / series title never takes the prefix path",
   L.link(idx, ["Overpowered and Underpaid"], ["Takano, Mikoto"])[0], "none")
eq("several works answer: the line's own title proper decides",
   L.link(idx, ["One Piece", "One Piece: Heroines"], ["Oda, Eiichirō"], name="One Piece: Heroines")[:3],
   ("medium", "w_opher", ["w_op", "w_opher"]))
for x, y, want in (("Kōsuke", "Kohske", True), ("Hayashida, Kyū", "Q Hayashida", True),
                   ("Sakuishi, Harorudo", "Harold Sakuishi", True), ("Yayoisō", "Sō Yayoi", True),
                   ("Shin'ichi Sakamoto", "Shinichi Sakamoto", True), ("Kishimoto, Masashi", "Junji Ito", False),
                   ("Sakamoto, Akira", "Akira Toriyama", False), ("Umino, Chika", "Chica Umino", True),
                   ("Oda Eiichiro", "Eiichiro Oda", True), ("Umezz, Kazuo", "Kazuo Umezu", True)):
    eq("same person: %s = %s" % (x, y), L.same_person(L.name_key(x), L.name_key(y)), want)
eq("title matches one work but the authors disagree -> low (a title collision, not a missing credit)",
   L.link(idx, ["Snowball earth"], ["Kishimoto, Masashi"])[:2], ("low", "w_se"))
eq("title matches one work, the line names no creator -> medium",
   L.link(idx, ["Snowball earth"], [])[:2], ("medium", "w_se"))
eq("a romanisation variant of the author still agrees -> high",
   L.link(idx, ["Snowball earth"], ["Tsujitsugu, Yuhiro"])[:2], ("high", "w_se"))
eq("creators: 100 with a translator $e and no $4 is out; 245$c names count",
   M.creators(rec("1", ("700", [("a", "Konparu, Tomoko"), ("e", "Übers.")]),
                  ("245", [("a", "Beck"), ("c", "Harold Sakuishi. [Aus dem Japan. von Claudia Peter]")]))),
   ["Harold Sakuishi"])
eq("a leading 'The' does not matter", L.fold("The Snowball Earth", False), L.fold("Snowball earth", False))
eq("low: alias only", L.link(idx, ["Priestess"], [])[0], "low")
eq("low: official title is the START of the DNB title (spin-off shape)",
   L.link(idx, ["Goblin Slayer! Year one"], ["Kagyu, Kumo"])[:2], ("low", "w_gs"))
eq("the spin-off's own work wins when it exists", L.link(idx, ["One Piece - Heroines 1"], ["Oda, Eiichirō"])[:2],
   ("medium", "w_opher"))
eq("none", L.link(idx, ["Gogo monster"], ["Matsumoto, Taiyō"])[0], "none")

# ---- merge with Wikipedia, load, reload, redirect ----------------------------------------------
cat.execute("INSERT INTO release_line(id,work_id,medium,market,language,created_at,updated_at) "
            "VALUES('rl_wiki','w_se','manga','DE','de',?,?)", (T, T))
cat.execute("INSERT INTO claim VALUES('release_line','rl_wiki','line_name','Snowball Earth','wikipedia',NULL,'facts_only',?)", (T,))
cat.execute("INSERT INTO volume(id,release_line_id,number,isbn13,release_date,release_date_precision,release_date_type,"
            "created_at,updated_at) VALUES('v_w1','rl_wiki','1',?,'2019-12-20','day','unknown',?,?)", (I1, T, T))
cat.execute("INSERT INTO volume(id,release_line_id,number,created_at,updated_at) VALUES('v_w2','rl_wiki','2',?,?)", (T, T))
cat.commit()
allrecs = dict(recs, **more)
allrecs["1200000000"] = parent
W, w_isbn = B.wiki_lines(cat)
lines, stats, lost = B.build(allrecs, {}, L.Index(cat), W, w_isbn)
main = next(ln for ln in lines if ln["key"] == "dnb:1200000000")
eq("majority ISBN overlap merges into the Wikipedia line", (main["role"], main["wiki_line"]), ("merged", "rl_wiki"))
eq("ground truth: the Wikipedia line's work", main["truth_work"], "w_se")
B.load(cat, lines, lost, W, w_isbn)
snap = lambda: (sorted(r[0] for r in cat.execute("SELECT id FROM release_line")),
                sorted(r[0] for r in cat.execute("SELECT id FROM volume")),
                cat.execute("SELECT COUNT(*) FROM claim WHERE source='dnb'").fetchone()[0])
first_ids = snap()
eq("the Wikipedia line keeps its id", "rl_wiki" in first_ids[0], True)
eq("a Wikipedia day date is never replaced",
   cat.execute("SELECT release_date, release_date_precision FROM volume WHERE id='v_w1'").fetchone(), ("2019-12-20", "day"))
eq("the Wikipedia volume gains dnb claims",
   sorted(r[0] for r in cat.execute("SELECT field FROM claim WHERE entity_id='v_w1' AND source='dnb'")),
   ["isbn13", "page_count", "release_date", "volume_number"] if M.pages(allrecs["1300000002"]) else
   ["isbn13", "release_date", "volume_number"])
eq("an ISBN-less Wikipedia volume merges by number and gains the year",
   cat.execute("SELECT release_date, release_date_precision, release_date_type FROM volume WHERE id='v_w2'").fetchone(),
   ("2019", "year", "published"))
eq("new DNB volumes join the Wikipedia line with load.py's volume ids",
   cat.execute("SELECT id FROM volume WHERE release_line_id='rl_wiki' AND number='4'").fetchone()[0],
   B._id("v_", "rl_wiki", "4"))
eq("every dnb claim is cc0 with a d-nb.info url",
   cat.execute("SELECT COUNT(*) FROM claim WHERE source='dnb' AND (licence<>'cc0' OR source_url NOT LIKE 'https://d-nb.info/%')").fetchone()[0], 0)
eq("no dnb cover or blurb claim",
   cat.execute("SELECT COUNT(*) FROM claim WHERE source='dnb' AND field IN ('cover_url','description','blurb')").fetchone()[0], 0)
eq("no dnb line_name claim on the merged Wikipedia line",
   cat.execute("SELECT COUNT(*) FROM claim WHERE entity_id='rl_wiki' AND field='line_name' AND source='dnb'").fetchone()[0], 0)
B.load(cat, lines, lost, W, w_isbn)
eq("idempotent reload: same line ids, volume ids and claim count", snap(), first_ids)
lines2, _, lost2 = B.build(allrecs, {}, L.Index(cat), W, w_isbn)
eq("rebuild from the same records: same line keys and ids",
   sorted((ln["key"], ln["rl_id"]) for ln in lines2), sorted((ln["key"], ln["rl_id"]) for ln in lines))

# A parent-less series (keyed by its lowest member) that later gains a parent record:
# the key changes, so the carried artifact's id is redirected, never silently re-keyed.
cat2 = sqlite3.connect(":memory:")
cat2.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
cat2.execute("INSERT INTO work(id,primary_title,created_at,updated_at) VALUES('w_se','Snowball Earth',?,?)", (T, T))
cat2.execute("INSERT INTO claim VALUES('work','w_se','author',?,'wikipedia',NULL,'facts_only',?)",
             (json.dumps(["Yuhiro Tsujitsugu"]), T))
TS = ("100", [("a", "Tsujitsugu, Yuhiro"), ("4", "aut")])
before = {r["cf"]["001"]: r for r in (
    vol("1700000001", "1", "9783753936000", series="Snowball earth", extra=[TS, ("490", [("a", "Snowball earth"), ("v", "1")])]),
    vol("1700000002", "2", "9783753936017", series="Snowball earth", extra=[TS, ("490", [("a", "Snowball earth"), ("v", "2")])]))}
W2, wi2 = B.wiki_lines(cat2)
l_before, _, lost_b = B.build(before, {}, L.Index(cat2), W2, wi2)
eq("before: keyed by the lowest member IDN, linked high", [(ln["key"], ln["role"]) for ln in l_before],
   [("dnb:1700000001", "linked")])
B.load(cat2, l_before, lost_b, W2, wi2)
tmp = tempfile.mkdtemp()
art = os.path.join(tmp, "carry.sqlite")
A = sqlite3.connect(art)
A.executescript("CREATE TABLE series (gcd_series_id INTEGER PRIMARY KEY, tome_id TEXT, tome_work_id TEXT, language TEXT);"
                "CREATE TABLE volumes (id INTEGER PRIMARY KEY, gcd_series_id INTEGER, volume_number INTEGER,"
                " tome_id TEXT, isbn13 TEXT);")
old_rl = l_before[0]["rl_id"]
A.execute("INSERT INTO series VALUES(1, ?, 'w_se', 'de')", (old_rl,))
for n, (vid, isbn) in enumerate(cat2.execute("SELECT id, isbn13 FROM volume ORDER BY number"), 1):
    A.execute("INSERT INTO volumes VALUES(?, 1, ?, ?, ?)", (n, n, vid, isbn))
A.commit()
after = dict(before)
for k in after:
    after[k] = dict(after[k], df=after[k]["df"] + [("773", " ", " ", [("w", "(DE-101)1650000000")])])
after["1650000000"] = rec("1650000000", JPN, TS, ("245", [("a", "Snowball earth")]), ("264", [("b", "Altraverse GmbH")]),
                          parent=True)
l_after, _, lost_a = B.build(after, {}, L.Index(cat2), W2, wi2)
eq("after: keyed by the new parent", [ln["key"] for ln in l_after], ["dnb:1650000000"])
B.load(cat2, l_after, lost_a, W2, wi2)
moved, orphans = B.redirects(cat2, art)
eq("the old line id is redirected to the new one",
   cat2.execute("SELECT new_id, entity FROM id_redirect WHERE old_id=?", (old_rl,)).fetchone(),
   (l_after[0]["rl_id"], "release_line"))
eq("its volumes follow by number",
   cat2.execute("SELECT COUNT(*) FROM id_redirect WHERE entity='volume'").fetchone()[0], 2)
eq("no orphaned ids", orphans, [])

# the carried artifact's own redirects survive, and chain
A.execute("CREATE TABLE id_redirect (old_tome_id TEXT PRIMARY KEY, new_tome_id TEXT, entity TEXT, reason TEXT,"
          " old_series_id INTEGER, new_series_id INTEGER)")
A.execute("INSERT INTO id_redirect VALUES('rl_ancient', ?, 'release_line', 'correction', NULL, NULL)", (old_rl,))
A.commit()
B.redirects(cat2, art)
eq("a redirect carried in the artifact is re-read (and chains: ancient -> old -> new)",
   cat2.execute("SELECT new_id FROM id_redirect WHERE old_id='rl_ancient'").fetchone(), (old_rl,))

# a published line the linker no longer links is kept, never silently dropped
cat3 = sqlite3.connect(":memory:")
cat3.executescript(open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf8").read())
cat3.execute("INSERT INTO work(id,primary_title,created_at,updated_at) VALUES('w_se','Renamed Work',?,?)", (T, T))
W3, wi3 = B.wiki_lines(cat3)
l3, _, _ = B.build(before, {}, L.Index(cat3), W3, wi3)
eq("without the carried artifact the line is unlinked", [ln["role"] for ln in l3], ["unlinked"])
l3, _, _ = B.build(before, {}, L.Index(cat3), W3, wi3, carried={old_rl: "w_se"})
eq("with it, the published line is kept under its published work",
   [(ln["role"], ln["work"]) for ln in l3], [("kept", "w_se")])

# ---- the fetcher: politeness, cache, offline -- against a fake DNB (no network) ----------
import email.message, re as _re, time as _time, urllib.error, urllib.parse
import dnb_sru as S
import dnb_enumerate as E

SERVER = {"years": {}, "refuse": 0, "diagnostic": False}
CALLS, SLEEPS = [], []


def _matches(y, cond):
    if not cond:
        return True
    if cond == "not jhr>0":
        return y is None
    if y is None:
        return False
    m = _re.fullmatch(r"and jhr(=|<|>)(\d+)", cond)
    if m:
        return {"=": y == int(m.group(2)), "<": y < int(m.group(2)), ">": y > int(m.group(2))}[m.group(1)]
    m = _re.fullmatch(r"and jhr>=(\d+) and jhr<=(\d+)", cond)
    return int(m.group(1)) <= y <= int(m.group(2))


class _Resp:
    def __init__(self, text):
        self.data = text.encode()

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


CLOCK, AT = [1_000_000.0], []


def fake_urlopen(req, timeout=None):
    CALLS.append(req.full_url)
    AT.append(CLOCK[0])
    if SERVER.get("status"):
        code, SERVER["status"] = SERVER["status"], None
        raise urllib.error.HTTPError(req.full_url, code, "Server Error", email.message.Message(), None)
    if SERVER["refuse"]:
        SERVER["refuse"] -= 1
        h = email.message.Message()
        h["Retry-After"] = "7"
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", h, None)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)
    if SERVER["diagnostic"]:
        return _Resp('<searchRetrieveResponse><diag:diagnostic xmlns:diag="x"><diag:message>bad</diag:message>'
                     '</diag:diagnostic></searchRetrieveResponse>')
    query = q["query"][0]
    if query.startswith("idn="):
        want = {x.strip()[4:] for x in query.split(" or ")}
        ids = sorted(i for xs in SERVER["years"].values() for i in xs if i in want)
    else:
        cond = query[len("BASE"):].strip()
        ids = sorted(i for y, xs in SERVER["years"].items() for i in xs if _matches(y, cond))
    start, maxr = int(q["startRecord"][0]), int(q["maximumRecords"][0])
    body = "".join('<record xmlns="http://www.loc.gov/MARC21/slim"><leader>00000pam a2200000 cc4500</leader>'
                   '<controlfield tag="001">%s</controlfield></record>' % i for i in ids[start - 1:start - 1 + maxr])
    return _Resp('<searchRetrieveResponse><numberOfRecords>%d</numberOfRecords><records>%s</records>'
                 '</searchRetrieveResponse>' % (len(ids), body))


saved = (S.CACHE, S.STAMP, S.NETLOG, S.OFFLINE, S.REFRESH_DAYS, S.urllib.request.urlopen, S.time.sleep,
         E.CURRENT_YEAR, S.time.time, E.PARENT_INDEX)
tmp = tempfile.mkdtemp(prefix="dnb-fetch-")
S.CACHE, S.STAMP, S.NETLOG = tmp, os.path.join(tmp, ".stamp"), os.path.join(tmp, "netlog.tsv")
S.OFFLINE, S.REFRESH_DAYS = False, 0
S.urllib.request.urlopen = fake_urlopen
def _sleep(secs):
    SLEEPS.append(secs)
    CLOCK[0] += secs


S.time.sleep = _sleep
S.time.time = lambda: CLOCK[0]
E.PARENT_INDEX = os.path.join(tmp, "dnb-parents.json")
try:
    SERVER["years"] = {2025: ["a1", "a2"], 2026: ["b1"], None: ["n1"]}
    E.CURRENT_YEAR = 2026
    got, gap, _ = E.run_channel("t", "BASE", 2025, (), verbose=False)
    eq("cold run: every record, no gap (incl. the no-year remainder)", (sorted(got), gap), (["a1", "a2", "b1", "n1"], 0))
    eq("throttle: consecutive requests are >= 3 s apart",
       min(b - a for a, b in zip(AT, AT[1:])) >= 3.0 and len(AT) > 3, True)
    n = len(CALLS)
    E.run_channel("t", "BASE", 2025, (), verbose=False)
    eq("rerun: zero requests", len(CALLS) - n, 0)

    # late records: one in a refreshed year, one in a frozen older year
    SERVER["years"][2026].append("b2")
    SERVER["years"].setdefault(2020, []).append("z1")
    for f in os.listdir(tmp):
        os.utime(os.path.join(tmp, f), (_time.time() - 3 * 86400,) * 2)
    got, gap, refreshed = E.run_channel("t", "BASE", 2025, (), verbose=False)
    eq("refresh run: plain rerun keeps the cache (no refresh window)", sorted(got), ["a1", "a2", "b1", "n1"])
    S.REFRESH_DAYS = 1
    got, gap, refreshed = E.run_channel("t", "BASE", 2025, (), verbose=False)
    eq("refresh run: the current year and the frozen slice's late record both arrive, no gap",
       (sorted(got), gap, refreshed), (["a1", "a2", "b1", "b2", "n1", "z1"], 0, True))
    S.REFRESH_DAYS = 0
    E.CURRENT_YEAR = 2027                       # year rollover: new slice urls, cached total
    got, gap, _ = E.run_channel("t", "BASE", 2025, (), verbose=False)
    eq("year rollover: no false gap", (len(got), gap), (6, 0))

    # politeness on refusal
    SLEEPS.clear()
    SERVER["refuse"] = 1
    txt = S.get(S.url_for("BASE and jhr=1999"))
    eq("one 429: waits out Retry-After (7 s), then succeeds", (7 in SLEEPS, "numberOfRecords" in txt), (True, True))
    SERVER["refuse"] = 1
    try:
        S.get(S.url_for("BASE and jhr=1998"))
        eq("a second 429 in the run stops it", "no exception", "DnbThrottled")
    except S.DnbThrottled:
        eq("a second 429 in the run stops it", True, True)
    SERVER["refuse"], S._refusals[0] = 0, 0
    SERVER["diagnostic"] = True
    u = S.url_for("BASE and bad query")
    try:
        S.get(u)
        eq("an SRU diagnostic raises", "no exception", "DnbDiagnostic")
    except S.DnbDiagnostic:
        eq("an SRU diagnostic raises and is not cached", os.path.exists(S.cache_path(u)), False)
    SERVER["diagnostic"] = False
    S.OFFLINE = True
    try:
        S.get(S.url_for("BASE and jhr=1900"))
        eq("offline: a cache miss raises", "no exception", "DnbOfflineMiss")
    except S.DnbOfflineMiss:
        eq("offline: a cache miss raises", True, True)
    S.REFRESH_DAYS = 1
    for f in os.listdir(tmp):
        os.utime(os.path.join(tmp, f), (_time.time() - 3 * 86400,) * 2)
    n = len(CALLS)
    E.run_channel("t", "BASE", 2025, (), verbose=False)
    eq("offline: a stale cached copy is served, not refetched", len(CALLS) - n, 0)
    eq("every live request is in the netlog", sum(1 for _ in open(S.NETLOG)), len(CALLS))

    # refresh runs never fail the build over DNB: they fall back to the (stale) cache
    S.OFFLINE, S.REFRESH_DAYS = False, 1
    for f in os.listdir(tmp):
        os.utime(os.path.join(tmp, f), (CLOCK[0] - 3 * 86400,) * 2)
    SERVER["status"] = 500
    got, gap, _ = E.run_channel("t", "BASE", 2025, (), verbose=False)
    eq("refresh run + HTTP 500: falls back to the cache, no exception, same records",
       (len(got), bool(S.DEGRADED[0])), (6, True))
    S.DEGRADED[0] = None
    for f in os.listdir(tmp):
        os.utime(os.path.join(tmp, f), (CLOCK[0] - 3 * 86400,) * 2)
    SERVER["refuse"], S._refusals[0] = 2, 0
    got, gap, _ = E.run_channel("t", "BASE", 2025, (), verbose=False)
    eq("refresh run + a second 429: falls back to the cache, no exception", (len(got), bool(S.DEGRADED[0])), (6, True))
    n = len(CALLS)
    E.CURRENT_YEAR = 2031                       # new slice urls, never cached, while degraded
    got, gap, _ = E.run_channel("t", "BASE", 2025, (), verbose=False)
    eq("degraded: an uncached slice is skipped with a warning, no request", len(CALLS) - n, 0)
    S.OFFLINE, S.DEGRADED[0] = True, None      # the measure gate's offline reload of that cache
    got, gap, _ = E.run_channel("t", "BASE", 2025, (), verbose=False)
    eq("offline re-read of a degraded refresh run's cache skips the same urls, no exception", len(got), 6)
    S.OFFLINE = False
    SERVER["refuse"], S._refusals[0], S.DEGRADED[0], S.REFRESH_DAYS = 0, 0, None, 0
    S.OFFLINE = False
    try:
        SERVER["status"] = 500
        S.get(S.url_for("BASE and jhr=1977"))
        eq("a first run (no refresh window) stays strict on a 500", "no exception", "HTTPError")
    except urllib.error.HTTPError:
        eq("a first run (no refresh window) stays strict on a 500", True, True)

    # parents: one request per batch, stable batch urls through the cache index
    SERVER["years"] = {2025: ["p1", "p2", "p3"]}
    E.IDN_BATCH = 2
    n = len(CALLS)
    got = E.fetch_parents({}, {"p1", "p2"}, verbose=False)
    eq("parents fetched once", (sorted(got), len(CALLS) - n), (["p1", "p2"], 1))
    n = len(CALLS)
    got = E.fetch_parents({}, {"p0", "p1", "p2"}, verbose=False)
    eq("a new parent costs one request; the old batch url is kept", len(CALLS) - n, 1)
finally:
    (S.CACHE, S.STAMP, S.NETLOG, S.OFFLINE, S.REFRESH_DAYS, S.urllib.request.urlopen, S.time.sleep,
     E.CURRENT_YEAR, S.time.time, E.PARENT_INDEX) = saved
    S.DEGRADED[0], E.IDN_BATCH = None, 30

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("all dnb tests passed")
