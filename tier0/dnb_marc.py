"""MARC21-xml parsing and the per-record field logic for DNB records.

Everything here is a pure function of one record (or one response text), so it is
unit-tested on synthetic records in tier0/test_dnb.py with no network. The field
choices are the ones the 2026-09-24 spike verified (docs/dnb-design.md):

  volume number   245$n, else 490/830 $v, else a trailing number in 245$a
                  (DNB vs Wikipedia volume number agreed 368/369)
  ISBN            020$a (and $z is NOT read: a cancelled/invalid ISBN)
  pages           300$a in its German shapes ("N Seiten", "N S.", "circa N Seiten",
                  "[N] S.", "N, [N] S.", "N ungezählte Seiten")
  year            008[7:11] -- year precision; late-December releases can carry the
                  next year, which is why a Wikipedia day date wins resolution
  planned month   263 YYYYMM on announcement records (matched the real month 25/26)
  announcement    leader/17 = '8' (prepublication level, CIP): the record describes a
                  book that has not been deposited yet

Never read: 856 (the X:MVB blurb links and table-of-contents PDFs are not CC0 --
publisher text, and covers belong to the VLB agreement), 245$b as a title (on VLB-fed
records it is marketing copy: "sexy anthropomorphe Fabelwesen | Harem | ...").
"""
import re
import unicodedata
import xml.etree.ElementTree as ET

MARC = "{http://www.loc.gov/MARC21/slim}"
# DNB wraps a title's non-sorting article in these control characters: "\x98Die\x9c Welt"
NONSORT = re.compile(r"[\x98\x9c\u0098\u009c]")


def nfc(s):
    return unicodedata.normalize("NFC", s or "")


def records(text):
    """SRU response text -> list of records {leader, cf: {tag: text}, df: [(tag, i1, i2, [(code, value)])]}.

    Every string is NFC-normalised here, once: DNB delivers NFD ('ä' as 'a' + U+0308), so an
    unnormalised 'ungezählte' in a pattern never matched 300$a, and NFD names reached the
    artifact (review 2026-09-24)."""
    root = ET.fromstring(text)
    out = []
    for rec in root.iter(MARC + "record"):
        r = {"leader": "", "cf": {}, "df": []}
        for el in rec:
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "leader":
                r["leader"] = el.text or ""
            elif tag == "controlfield":
                r["cf"][el.get("tag")] = nfc(el.text)
            elif tag == "datafield":
                subs = [(s.get("code"), nfc(s.text)) for s in el]
                r["df"].append((el.get("tag"), el.get("ind1") or " ", el.get("ind2") or " ", subs))
        if r["cf"].get("001"):
            out.append(r)
    return out


def fields(r, tag):
    """Every datafield with this tag, as its subfield list."""
    return [s for t, _, _, s in r["df"] if t == tag]


def subs(r, tag, code):
    return [v for s in fields(r, tag) for c, v in s if c == code]


def first(r, tag, code):
    v = subs(r, tag, code)
    return v[0] if v else None


def clean(s):
    """Strip DNB's non-sort markers, collapse whitespace, NFC."""
    return re.sub(r"\s+", " ", NONSORT.sub("", nfc(s))).strip()


def idn(r):
    return r["cf"]["001"]


def is_parent(r):
    """A multi-part set record (bbg=Ac): the series head, not a volume."""
    return len(r["leader"]) > 19 and r["leader"][19] == "a"


def is_announcement(r):
    """leader/17 = '8': prepublication (CIP) level -- the book is announced, not deposited."""
    return len(r["leader"]) > 17 and r["leader"][17] == "8"


def parent_idns(r):
    """773$w '(DE-101)1234567' -> ['1234567'] (the set this volume belongs to)."""
    return [m.group(1) for w in subs(r, "773", "w")
            for m in [re.match(r"\(DE-101\)\s*(\S+)", w)] if m]


# ---- identifiers -----------------------------------------------------------------

def _isbn13(v):
    from isbn import normalise_isbn, isbn13_check
    i13, _ = normalise_isbn((v or "").split(" ")[0])
    return i13 if i13 and isbn13_check(i13) else None


def cased_book(r):
    """One book that ships in a case: no set (773), one paginated extent ('2394 Seiten') and no
    bundle text in its title -- Death Note All-in-One, 'Broschur in Behältnis'. Its cased ISBN
    is its own, and it is a volume, not a box."""
    if parent_idns(r) or is_parent(r) or BUNDLE_TEXT.search(_title_text(r)):
        return False
    return bool(re.match(r"^\s*(?:ca\.|circa)?\s*\[?\d{2,4}\]?\s*(?:ungezählte\s+)?Seiten\b",
                         clean(first(r, "300", "a"))))


def box_isbns(r):
    """ISBN-13s of 020 fields qualified as a box ('Kassette 1', ', in Schuber', 'Broschur in
    Behältnis') -- none for a cased single book (cased_book)."""
    if cased_book(r):
        return set()
    return {i for f in fields(r, "020") if _box_020(f) for c, v in f if c == "a" for i in [_isbn13(v)] if i}


def isbns(r):
    """The record's own valid ISBN-13s from 020$a, in record order, ISBN-10s converted. 020$z
    (cancelled / invalid) is deliberately not read, nor a box's ISBN: a volume sold in a box
    carries the box's ISBN too -- once qualified, and often again unqualified as an ISBN-10."""
    box = box_isbns(r)
    out = []
    for v in subs(r, "020", "a"):
        i13 = _isbn13(v)
        if i13 and i13 not in box and i13 not in out:
            out.append(i13)
    return out


# ---- volume number ----------------------------------------------------------------

_NUM_WORD = r"(?:vol(?:ume)?\.?|band|bd\.?|teil|nr\.?|no\.?|tome|buch|#|n[uú]mm?er|folge)"
_RANGE = re.compile(r"(\d+)\s*(?:[-–/+]|und|bis|&)\s*(\d+)", re.I)
_NUM = re.compile(r"^\s*\[?\s*(?:" + _NUM_WORD + r"\s*)?(\d{1,4})(?:[.,](\d{1,2}))?\s*\.?\s*\]?\s*$", re.I)
# a trailing volume number on a bare 245$a: "Car Crush 02", "Die Monster Mädchen – Band 21"
_TRAILING = re.compile(r"^(.*?\S)\s*(?:[,.:;–—-]\s*)?(?:" + _NUM_WORD + r"\s*)?(\d{1,3})\s*$", re.I)


def canon_number(raw):
    """'1.' / '01' / 'Vol. 3' / 'Band 3' -> ('1'|'3', 'int'); '7.5' -> ('7.5', 'decimal');
    '1 - 3' -> ('1-3', 'range'); anything else -> (None, 'none')."""
    # older records append the statement of responsibility: "2. / [Aus dem Japan. von ...]"
    s = clean(raw).split(" / ")[0].strip()
    if not s or not re.search(r"\d", s):
        return None, "none"
    m = _RANGE.search(s)
    if m and int(m.group(2)) > int(m.group(1)):
        return "%d-%d" % (int(m.group(1)), int(m.group(2))), "range"
    m = _NUM.match(s)
    if not m:
        # a part number with a word or a subtitle around it: "Song 2.", "Lektion 3.",
        # "23 : Rubin und Saphir" -- $n IS the part number, so one integer in it is that number
        nums = re.findall(r"\d+", s)
        if len(nums) == 1 and not re.search(r"\d[.,]\d", s):
            return str(int(nums[0])), "int"
        return None, "none"
    if m.group(2):
        return "%d.%s" % (int(m.group(1)), m.group(2)), "decimal"
    return str(int(m.group(1))), "int"


def series_statements(r):
    """(name, $v) from 490/830 WITH a $v only. A 490 without $v is an imprint collection
    ("Action", "Romance"), not a series (spike finding)."""
    out = []
    for tag in ("830", "490"):
        for s in fields(r, tag):
            d = dict(s)
            if d.get("v") and (d.get("a") or d.get("t")):
                out.append((clean(d.get("a") or d.get("t")), d["v"]))
    return out


# an explicit volume word inside 245$a: "Kaiju No. 8 – Band 16 (Finale)", "... – Band 8 – Limited Edition"
_BAND = re.compile(r"^(.*?\S)\s*[,.:;–—-]?\s*\b(?:band|bd\.|vol\.|volume)\s*(\d{1,3})\b", re.I)


def title_number(r):
    """-> (number, the title before it) from 245$a alone: an explicit 'Band N' anywhere, else a
    trailing number ('Car Crush 02'); (None, None) when there is neither."""
    a = clean(first(r, "245", "a"))
    m = _BAND.match(a)
    if m:
        return str(int(m.group(2))), m.group(1).rstrip(" ,.:;–—-")
    m = _TRAILING.match(a)
    if m and not re.search(r"\d$", m.group(1)):
        return str(int(m.group(2))), m.group(1).rstrip(" ,.:;–—-")
    return None, None


def volume_number(r):
    """-> (number, kind, source): 245$n, else 490/830 $v, else the number in 245$a -- except
    that where the title is exactly '<series name> <N>' and N disagrees with $v, N wins:
    Record of Ragnarok 11 and 12 carry $v 23 / 24 (a continuous count across two series)."""
    for n in reversed(subs(r, "245", "n")):
        num, kind = canon_number(n)
        if kind != "none":
            return num, kind, "245n"
    tnum, before = title_number(r)
    for name, v in series_statements(r):
        num, kind = canon_number(v)
        if kind == "none":
            continue
        # the title's number wins only when the title minus that number IS the series name
        # ("Record of Ragnarok 11" in series "Record of Ragnarok" $v 23). A chapter title
        # ("Auf in die Zone 7", Toriko $v 33), a title that is a number ("No. 6" $v 3) or a
        # sub-series ("JoJo ... Part 4 11", $v 28) keeps the series count.
        if tnum and tnum != num and _fold_name(before) == _fold_name(name):
            return tnum, "int", "title"
        return num, kind, "series_v"
    if tnum:
        return tnum, "int", "title"
    return None, "none", None


def _fold_name(s):
    return re.sub(r"[^0-9a-z]", "", unicodedata.normalize("NFKD", clean(s)).encode("ascii", "ignore").decode().lower())


def bare_title(r):
    """245$a without its volume number ('Car Crush 02' -> 'Car Crush', 'Kaiju No. 8 – Band 16
    (Finale)' -> 'Kaiju No. 8')."""
    a = clean(first(r, "245", "a"))
    if subs(r, "245", "n"):
        return a
    _, before = title_number(r)
    return before or a


# ---- extent, dates ------------------------------------------------------------------

def pages(r):
    """300$a -> page count: numbered + unnumbered pages when both are stated."""
    a = clean(first(r, "300", "a"))
    if not a:
        return None
    m = re.match(r"^(?:ca\.|circa)?\s*\[?(\d{1,4})\]?\s*(?:ungezählte\s+)?(?:Seiten|S\.)?"
                 r"(?:\s*,\s*\[?(\d{1,3})\]?\s*(?:ungezählte\s+)?(?:Seiten|S\.))?", a)
    if not m or not re.search(r"Seiten|S\.", a):
        return None
    n = int(m.group(1)) + (int(m.group(2)) if m.group(2) else 0)
    return n if 0 < n <= 2000 else None          # beyond 2000 is a box or a misparse


def year(r):
    """008[7:11] when it is a plausible year, else None."""
    y = (r["cf"].get("008") or "")[7:11]
    return y if re.fullmatch(r"(19|20)\d\d", y) else None


def planned_month(r):
    """263 'YYYYMM' (the planned publication month of an announcement) -> 'YYYY-MM'."""
    for v in subs(r, "263", "a"):
        m = re.match(r"^\s*((?:19|20)\d\d)(0[1-9]|1[0-2])", v)
        if m:
            return "%s-%s" % (m.group(1), m.group(2))
    return None


# ---- what kind of book ---------------------------------------------------------------

def origin_languages(r):
    return {v.strip().lower() for v in subs(r, "041", "h")}


def origin_in_scope(r):
    """Japanese origin, or an origin the record does not state.

    041$h names the original language: 'jpn' is in scope, anything else (kor, chi, eng,
    fre) is not -- Korean and Chinese titles are the follow-up round (decision 4). Where
    041$h is absent (~975 records of the manga-imprint channel, 2026-09-24) the record
    cannot say: those are mostly Japanese manga catalogued without it (Komi Can't
    Communicate, Yotsuba&!) next to some German originals, and no field separates them
    reliably. They stay in scope unless the statement of responsibility says 'aus dem
    Koreanischen / Chinesischen / Englischen / ...' or a keyword says manhwa / webtoon /
    manhua; a German original then only ships if it links to an OpenTome work -- in which
    case it IS that work's German line."""
    langs = origin_languages(r)
    if langs:
        return "jpn" in langs
    resp = " ".join(subs(r, "245", "c") + subs(r, "500", "a") + subs(r, "546", "a"))
    if re.search(r"aus dem (?!jap)\w+", resp, re.I):          # 'Aus dem Japan.' is Japanese
        return False
    kw = {clean(v).lower() for v in subs(r, "653", "a")}
    return not kw & {"manhwa", "webtoon", "manhua", "k-comic", "korea", "korean"}


def thema(r):
    return [v.strip().upper() for v in subs(r, "926", "a")]


LN_THEMA = {"FYS", "YFZS"}
LN_TEXT = re.compile(r"light[\s-]?novel|ranobe", re.I)
EXTRA_TEXT = re.compile(r"artbook|art book|artworks?\b|malbuch|kochbuch|kalender|postkarten|sticker|"
                        r"fanbook|fan book|character ?book|making[- ]of|\bguide\b|zeichnen lernen|"
                        r"zeichenkurs|how to draw|rätselbuch|notizbuch|tagebuch zum|poster|"
                        r"illustrations?\b|visual ?book|databook|data book|anthology book|tarot[\s-]?buch|guidebook|"
                        r"fotostrecke|fotobuch|photo ?book|bildband", re.I)
BUNDLE_TEXT = re.compile(r"bundle|doppelband|sammelschuber|komplettpack|komplettbox|schuber|"
                         r"\bbox\b|\bboxset\b|box-set|schmuckbox|starter[\s-]?pack|double[\s-]?pack|doppel[\s-]?pack|"
                         r"\d+er[\s-]?pack|einsteiger[\s-]?set|\bset\b.*\d+\s*b[äa]nde|mit dekorama|"
                         r"mit acryl[\s-]?aufsteller", re.I)
# the record describes a box or a set in a case: 020$c / 300 "in Behältnis", "Kassette", "Schuber"
BOXED = re.compile(r"behältnis|kassette|schuber|\bbox\b", re.I)


def _title_text(r):
    """The title-ish text a bundle / extra is recognised in: 245 $a$n$p, 250, 490, and the
    variant titles (246: Btooom!'s 'Gravity angel' is '246 Himikos erste Fotostrecke')."""
    return " ".join(clean(x) for x in subs(r, "245", "a") + subs(r, "245", "n") + subs(r, "245", "p")
                    + subs(r, "250", "a") + subs(r, "490", "a") + subs(r, "246", "a"))


def _box_020(f):
    """An 020 field that names a box or a case ($q 'Kassette 1', $c ', in Schuber, kart.')."""
    return any(BOXED.search(v) for c, v in f if c in ("q", "c"))


def boxed(r):
    """The record IS a box or a set in a case: its extent or edition says so (300 'Behältnis
    19 x 14 x 13 cm', 250 'Schuberauflage'), or every ISBN it has is a box's. A volume that
    also carries its own ISBN is a book that was sold in a box as well -- not boxed. A parent's
    bare '9 Bände' is NOT a signal: every multi-part set record states its extent that way."""
    if cased_book(r):
        return False
    if BOXED.search(" ".join(subs(r, "300", "a") + subs(r, "300", "c") + subs(r, "250", "a"))):
        return True
    return bool(box_isbns(r)) and not isbns(r)


def box_parent(p):
    """A set record that is a box: boxed(), a box ISBN among its ISBNs, or a bundle title."""
    return boxed(p) or any(_box_020(f) for f in fields(p, "020")) or classify(p) == "bundle"


def comic_signal(r):
    """DDC 741.5, the older DNB subject group 08 (records before ~2004: Akira, Banana Fish,
    Spriggan -- every 08 record among the Japanese-origin ones is a comic), or the GND
    content type 'Comic' -- the strong comic signals."""
    ddc = any(v.strip().startswith("741.5") or v.strip() == "08" for v in subs(r, "082", "a"))
    return ddc or any(v.strip().lower() == "comic" for v in subs(r, "655", "a"))


def manga_signal(r):
    """The weaker manga signals: Thema XAM*, VLB-WN 1182/2182 'Manga, Manhwa'."""
    if any(t.startswith("XAM") for t in thema(r)):
        return True
    return any(re.match(r"\(VLB-WN\)[12]182", v) for v in subs(r, "653", "a"))


def ln_signal(r):
    if LN_THEMA & set(thema(r)):
        return True
    text = " ".join(subs(r, "245", "a") + subs(r, "490", "a") + subs(r, "653", "a") + subs(r, "500", "a"))
    return bool(LN_TEXT.search(text))


def classify(r):
    """-> 'manga' | 'light_novel' | 'extra' (artbook, guide, merchandise) | 'bundle' | 'other'.

    Thema FYS/YFZS ("Ranobe") is an explicit light-novel code and wins. Otherwise a strong
    comic signal (DDC 741.5, GND 'Comic') is manga; a 'Light Novel' / 'Ranobe' mention is a
    light novel (publishers also stamp Thema XAM on light novels -- XAM != manga); the weak
    manga signals alone are manga; nothing at all is 'other' (Japanese literature, non-fiction)."""
    t = _title_text(r)
    if BUNDLE_TEXT.search(t) or boxed(r):
        return "bundle"
    if EXTRA_TEXT.search(t):
        return "extra"
    if LN_THEMA & set(thema(r)):
        return "light_novel"
    if comic_signal(r):
        return "manga"
    if ln_signal(r):
        return "light_novel"
    if manga_signal(r):
        return "manga"
    return "other"


EDITION = [
    ("deluxe", re.compile(r"deluxe", re.I)),
    ("massiv", re.compile(r"\bmassiv\b", re.I)),
    ("mehrfachband", re.compile(r"mehrfachband|\b\d\s*in\s*1\b|sammelband|omnibus", re.I)),
    ("perfect", re.compile(r"perfect edition", re.I)),
    ("collector", re.compile(r"collector'?s?[’']?s? edition", re.I)),
    ("limited", re.compile(r"limitierte|limited edition|sonderausgabe|special edition", re.I)),
    ("kanzenban", re.compile(r"kanzenban|ultimative edition|ultimate edition", re.I)),
]


def edition_marker(r):
    """An edition that is its own release line ('Naruto Massiv', a Deluxe Edition), or None.
    Read from 250 and the title proper, never from 245$b (marketing text)."""
    t = " ".join(clean(x) for x in subs(r, "250", "a") + subs(r, "245", "a") + subs(r, "245", "p")
                 + [a for a, _ in series_statements(r)])
    for name, rx in EDITION:
        if rx.search(t):
            return name
    return None


# ---- titles and people ---------------------------------------------------------------

def original_titles(r):
    """240$a (uniform title), 246$a (other titles), and a 245$b parallel title ('= ...')."""
    out = [clean(v) for v in subs(r, "240", "a") + subs(r, "246", "a")]
    out += [clean(v.strip()[1:]) for v in subs(r, "245", "b") if v.strip().startswith("=")]
    return [x for x in out if x]


def publisher(r):
    for tag in ("264", "260"):
        for v in subs(r, tag, "b"):
            if clean(v):
                return clean(v)
    return None


# creator roles (relator codes, $4). 'trl' (translator) and 'edt' never count; a field with
# no $4 (older records) is judged by its $e: Übersetzer / Herausgeber / Bearbeiter are out.
CREATOR_ROLES = {"aut", "art", "ill", "oth", "ant", "cre", "ctb"}
NOT_CREATOR_E = re.compile(r"übers|hrsg|herausg|bearb|lektor|redakt|letter", re.I)
RESP_SKIP = re.compile(r"aus dem|übers|deutsch|bearb|redakt|letter|lektor|hrsg|herausg|nach einer|nach dem", re.I)
RESP_LABEL = re.compile(r"^(?:text|story|zeichnungen?|illustrationen?|art|artwork|manga|original(?:idee)?|"
                        r"idee|character design|charakterdesign|von|by)\s*:?\s*", re.I)


def creators(r):
    """Raw names of the record's creators: 100/700 (translators and editors excluded), then
    the names in the statement of responsibility (245$c) -- older records often credit the
    author only there ("Harold Sakuishi. [Aus dem Japan. von ...]")."""
    out = []
    for tag in ("100", "700"):
        for s in fields(r, tag):
            roles = {v.strip() for c, v in s if c == "4"}
            if roles and not roles & CREATOR_ROLES:
                continue
            if not roles and any(NOT_CREATOR_E.search(v) for c, v in s if c == "e"):
                continue
            name = next((v for c, v in s if c == "a"), None)
            if name and clean(name) not in out:
                out.append(clean(name))
    for c in subs(r, "245", "c"):
        c = re.split(r"\[", clean(c))[0]
        for seg in c.split(";"):
            if RESP_SKIP.search(seg):
                continue
            for part in re.split(r",|&|\+|\bund\b|\band\b|/|\.\s+(?=[\w -]+:)", seg):
                # a role label is anything up to the LAST ':' ("Original-Story: X", "Mitarbeit: Y",
                # "work: Z"), then "presented by" / "präsentiert von"
                n = part.rsplit(":", 1)[-1] if ":" in part else part
                n = re.sub(r"^\s*(?:[\w-]+\s+){0,2}(?:presented by|präsentiert von|by|von|nach)\s+", "", n, flags=re.I)
                n = RESP_LABEL.sub("", re.sub(r"\s*\([^)]*\)?\s*$", "", n).strip(" .:")).strip(" .")
                if n and len(n.split()) <= 4 and not re.search(r"\d", n) and n not in out:
                    out.append(n)
    return out
