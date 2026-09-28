"""Library of Congress MARC21 field logic (docs/krcn-design.md §5, §6, §7, §12).

Pure functions of ONE record in the dict shape tier0/dnb_marc.records() returns: LoC's marcxml is
MARC21 slim in the same namespace, so dnb_marc parses it. Only records whose 040 $a is DLC are
read past is_dlc() (decision 2, R4); tier0/krcn_lines.py drops every other record first.

Never read (the suite asserts this file names none of these tags): the publisher summary, the
link fields, and LoC's processing fields -- their receipt notes ("v. 1 rec'd 2021-07-15") are
receipt dates, not releases, the same rule as DNB's 015.
"""
import datetime, re

import dnb_marc as M
from dnb_link import fold

URL = "https://lccn.loc.gov/"
PROJECTED_MAX_AGE = 12          # months: tier0/build_dnb.py's rule for a plan that never arrived


def _months_ago(ym):
    t = datetime.date.today()
    return (t.year - int(ym[:4])) * 12 + t.month - int(ym[5:7])


# ---- identity ------------------------------------------------------------------------------------

def normalise_lccn(raw):
    """LoC's LCCN normalisation: blanks removed, everything from a '/' dropped, a hyphenated
    'YYYY-N' turned into the year + the serial zero-padded to 6 digits; an alphabetic prefix is
    kept, lowercased. None when what is left is not an LCCN."""
    s = re.sub(r"\s+", "", raw or "").split("/")[0].lower()
    if "-" in s:
        head, serial = s.split("-", 1)
        if serial.isdigit() and len(serial) <= 6:
            s = head + serial.zfill(6)
    return s if re.fullmatch(r"[a-z]{0,3}\d{8,10}", s) else None


def lccn(r):
    return normalise_lccn(M.first(r, "010", "a"))


def url(lc):
    return URL + lc


def f040a(r):
    return (M.first(r, "040", "a") or "").strip()


def is_dlc(r):
    """Created by LoC (040 $a DLC). A record LoC copied from another library (040 $a ZCU / OCLC,
    even with DLC among its $d modifiers) is not, and is never read further (R4)."""
    return f040a(r) == "DLC"


def is_monograph(r):
    return r["leader"][6:8] == "am"


def is_print(r):
    """RDA carrier 338 $a 'volume' (the ebook twin of a print record says 'online resource'); an
    older record without 338 is print unless its 300 says 'online resource'."""
    c = [v.strip().lower() for v in M.subs(r, "338", "a")]
    if c:
        return any(v.startswith("volume") for v in c)
    return "online resource" not in " ".join(M.subs(r, "300", "a")).lower()


def encoding_level(r):
    return r["leader"][17] if len(r["leader"]) > 17 else " "


def is_prelim(r):
    """leader/17 '8' (CIP: an announcement) or '5' (ECIP preliminary): 008 date1 is an estimate."""
    return encoding_level(r) in ("5", "8")


def date_type(r):
    return (r["cf"].get("008") or "").ljust(7)[6]


def date1(r):
    y = (r["cf"].get("008") or "")[7:11]
    return y if re.fullmatch(r"(19|20)\d\d", y) else None


def text_language(r):
    return (r["cf"].get("008") or "")[35:38]


# ---- ISBNs and volumes -------------------------------------------------------------------------------

# the volume a $q names, searched anywhere in it: 'v. 1', '(v. 1 ;', 'volume 1', 'pbk. : v. 1',
# 'hbk. : v. 1 : alk paper', 'bk. 1'; a leading bare number before a binding ('1 : pbk') too. A
# half volume stays one ('v. 5.5': its own number, never volume 5's). '6-pack' names no volume.
_VOL = re.compile(r"\b(?:v(?:ol(?:ume)?)?|bk|book)\.?\s*(\d+(?:\.\d+)?)(?![\d-])|"
                  r"^\W*(\d+(?:\.\d+)?)\s*:\s*(?:pbk|paperback|hbk|hardcover)", re.I)
PAPERBACK = re.compile(r"paperback|pbk", re.I)


def qualified_isbns(r):
    """020 $a ISBN-13s with the volume their $q names: [(number | None, isbn13, qualifiers)], record
    order. EVERY $q is read -- LoC writes '$q v. 1 $q trade paperback', '$q trade paperback $q v. 1',
    '(v. 1 ;', 'pbk. : v. 1', '1 : pbk' and 'bk. 1' (plan ruling P4) -- and the number is
    canonicalised by dnb_marc ('01' -> '1', '5.5' stays '5.5'). $z (cancelled, ebook) is never read."""
    out = []
    for f in M.fields(r, "020"):
        a = next((v for c, v in f if c == "a"), None)
        i13 = M._isbn13(a) if a else None
        if not i13:
            continue
        qs = [v for c, v in f if c == "q"]
        num = next((M.canon_number(m.group(1) or m.group(2))[0] for q in qs for m in [_VOL.search(q)] if m), None)
        out.append((num, i13, " ".join(qs)))
    return out


def volume_isbns(r):
    """{volume number: [(isbn13, qualifiers)]} -- two ISBNs for one number are the hardcover and the
    paperback (23 volume numbers in the spike)."""
    out = {}
    for num, i13, q in qualified_isbns(r):
        if num:
            out.setdefault(num, []).append((i13, q))
    return out


def is_set(r):
    """A multi-volume set record: at least 2 distinct volume numbers among its ISBNs (§8: it IS a line)."""
    return len(volume_isbns(r)) >= 2


def pick_isbn(cands, existing=()):
    """One ISBN per volume (§5): the one an OpenTome volume already has, else the paperback
    ('paperback' / 'pbk' in $q, ruling P5), else the first listed. cands: [(isbn13, qualifiers)]."""
    for i, _ in cands:
        if i in existing:
            return i
    for i, q in cands:
        if PAPERBACK.search(q or ""):
            return i
    return cands[0][0] if cands else None


# ---- dates -------------------------------------------------------------------------------------------

def planned_month(r):
    """263 'YYMM' -> 'YYYY-MM' (LoC's projected publication date is YYMM, not DNB's YYYYMM);
    '1111' means unknown and is never a date."""
    for v in M.subs(r, "263", "a"):
        v = v.strip()
        if v == "1111":
            continue
        m = re.fullmatch(r"(\d\d)(0[1-9]|1[0-2])", v)
        if m:
            return "20%s-%s" % m.groups()
    return None


def volume_date(r, set_record):
    """(value, precision, type) | None for the ONE volume a record describes (§12):
      * a set record never dates a volume -- 008 m2021 / 264 $c 2021- are the SET's start, and a
        263 on it names no particular volume (plan ruling P6);
      * a single-volume record (008 type s / t) below encoding level 5 / 8: date1, year, published;
      * at level 5 or 8 date1 is an estimate: only a 263 month, projected, unless it is more than
        PROJECTED_MAX_AGE months past (no future-year hold for LoC: ruling P7);
      * nothing else."""
    if set_record:
        return None
    if is_prelim(r):
        ym = planned_month(r)
        if ym and _months_ago(ym) <= PROJECTED_MAX_AGE:
            return (ym, "month", "projected")
        return None
    if date_type(r) in ("s", "t") and date1(r):
        return (date1(r), "year", "published")
    return None


def pages(r):
    """300 $a 'N pages' / 'N p.' -- single-volume records only carry it (22 of 75 in the spike);
    a roman-numbered preliminary sequence is not counted ('viii, 106 p.' -> 106)."""
    a = M.clean(M.first(r, "300", "a"))
    m = re.match(r"^(?:[ivxlc]+\s*,\s*)?\[?(\d{1,4})\]?\s*(?:unnumbered\s+)?(?:pages|p\.)", a)
    return int(m.group(1)) if m and 0 < int(m.group(1)) <= 2000 else None


def volume_number(r):
    """A single-volume record's number: the one volume its 020 $q names, else dnb_marc's rule
    (245 $n, 490 / 830 $v -- 'book 3' reads 3 --, else a trailing number in 245 $a)."""
    qn = set(volume_isbns(r))
    if len(qn) == 1:
        return next(iter(qn))
    num, kind, _ = M.volume_number(r)
    return num if kind in ("int", "decimal") else None


# ---- origin and class --------------------------------------------------------------------------------

TRANSLATED = re.compile(r"translat\w*\s+from\s+(?:the\s+)?(korean|chinese)", re.I)


def publisher(r):
    p = M.publisher(r)
    return re.sub(r"[\s,:;]+$", "", p) if p else None


def is_ize(r):
    return bool(re.search(r"\bize\b", publisher(r) or "", re.I))


def pubfam(p):
    """Publisher family for clustering single-volume records (§8): Yen Press / Ize Press = yen."""
    if re.search(r"\b(yen|ize)\b", p or "", re.I):
        return "yen"
    return fold(re.sub(r"(?i)\b(press|publishing|books?|inc|llc)\b", "", p or ""), False)[:6]


def origin(r):
    """-> (origin, explicit): ('kor' | 'chi', True) from 041 $h, else from a 'Translated from the
    Korean / Chinese' statement (500 / 546 / 245 $c); ('kor', False) for an Ize Press record that
    says neither (its ECIP-preliminary records carry no 041, §7 -- an imprint signal, never enough
    to create a work, §9); (None, False) otherwise:
      * a text that is not English (008/35-37): a LoC line is an English-market line, so neither a
        Korean- or Chinese-LANGUAGE original (out of scope §16) nor a Japanese translation of a
        Chinese comic (Ransei ni eiyū arawaru, 041 $h chi) is one;
      * an 041 $h naming any language besides Korean / Chinese: a relay translation (The blue
        dragon, 2011930915: $h fre + $h chi, translated from the French)."""
    if text_language(r) != "eng":
        return None, False
    h = {v.strip().lower() for v in M.subs(r, "041", "h")}
    if h:
        if not h <= {"kor", "chi", "zho"}:
            return None, False
        return ("kor", True) if "kor" in h else ("chi", True)
    m = TRANSLATED.search(" ".join(M.subs(r, "500", "a") + M.subs(r, "546", "a") + M.subs(r, "245", "c")))
    if m:
        return ("kor" if m.group(1).lower() == "korean" else "chi"), True
    if is_ize(r):
        return "kor", False
    return None, False


COMIC_TERMS = re.compile(r"comics \(graphic works\)|graphic novels|manhwa|manhua|webcomics|webtoons|comic books|"
                         r"\bcomics\b", re.I)
PROSE_TERMS = re.compile(r"\bfiction\b|light novels|\bnovels\b", re.I)


def comic_signal(r):
    """082 741.5, 050 PN6790 / PN8323 (LoC files manhwa and webcomics under PN8323: Solo Leveling,
    Tower of God), 655 comic genre terms, 650 'Comic books, strips, etc.'."""
    ddc = " ".join(M.subs(r, "082", "a"))
    lcc = " ".join(M.subs(r, "050", "a"))
    s650 = " | ".join(M.subs(r, "650", "a") + M.subs(r, "650", "v") + M.subs(r, "650", "x"))
    return ("741.5" in ddc or re.search(r"\bPN(?:6790|8323)", lcc) is not None
            or COMIC_TERMS.search(" | ".join(M.subs(r, "655", "a"))) is not None
            or re.search(r"comic books, strips|graphic novels", s650, re.I) is not None)


def prose_signal(r):
    """082 895.7x / 895.1x, 050 PL, or a 655 fiction / light-novel term WITHOUT a comic signal
    ('Fiction' sits on comic records too: Solo Leveling)."""
    ddc = " ".join(M.subs(r, "082", "a"))
    if re.search(r"\b895\.[17]", ddc) or any(re.match(r"PL\d", v.strip()) for v in M.subs(r, "050", "a")):
        return True
    return PROSE_TERMS.search(" | ".join(M.subs(r, "655", "a"))) is not None and not comic_signal(r)


def classify(r):
    """'comic' | 'prose' | 'both' (review) | 'unresolved' (no signal: the level-5 Ize records)."""
    c, p = comic_signal(r), prose_signal(r)
    return {(True, False): "comic", (False, True): "prose", (True, True): "both"}.get((c, p), "unresolved")


BUNDLE = re.compile(r"box(?:ed)? set|boxset|\bbox\b|slipcase", re.I)
# 'guide' alone is a title word: I Picked Up This World's Strategy Guide, The Genius Prince's Guide ...
EXTRA = re.compile(r"artbook|art book|\bthe art of\b|guide ?book|official (?:visual )?guide|colou?ring book|"
                   r"sticker|calendar|postcard", re.I)


def excluded_kind(r):
    """A bundle / box / artbook / guide is not a volume (§6.4; the dnb_marc.classify exclusions).
    A set record (is_set) is a series with numbered volumes, never an extra by its title words."""
    t = " ".join(M.subs(r, "245", "a") + M.subs(r, "245", "b") + M.subs(r, "245", "p") + M.subs(r, "250", "a")
                 + [v for f in M.fields(r, "020") for c, v in f if c == "q"])
    if BUNDLE.search(t):
        return "bundle"
    if EXTRA.search(t) and not is_set(r):
        return "extra"
    return None


# ---- titles and people ---------------------------------------------------------------------------------

def _isbd(s):
    return re.sub(r"[\s/:;=,.]+$", "", M.clean(s or "")).strip()


def title_proper(r):
    """245 $a without the ISBD, then its part number / part name ($n / $p) in field order (§5)."""
    f = next(iter(M.fields(r, "245")), [])
    return ". ".join(x for x in (_isbd(v) for c, v in f if c in ("a", "n", "p")) if x)


def full_title(r):
    """The title proper with its other title information (245 $b): 'Solo leveling : Ragnarok' --
    a sequel that is its own work, which the title proper alone reduces to its parent's name."""
    b = _isbd(" ".join(M.subs(r, "245", "b")))
    return title_proper(r) + " : " + b if b else title_proper(r)


def bare_title(r):
    """245 $a without the ISBD and a trailing volume number ('Tower of god. 1' -> 'Tower of god')."""
    t = title_proper(r)
    m = M._TRAILING.match(t)
    return m.group(1).rstrip(" ,.:;–—-") if m and not re.search(r"\d$", m.group(1)) else t


def original_titles(r):
    """240 $a (uniform title) and 765 $t (original-language entry) -- ALA-LC romanisation, so it keys
    within LoC only (§10)."""
    return [x for x in (_isbd(v) for v in M.subs(r, "240", "a") + M.subs(r, "765", "t")) if x]


# A uniform title's language note ($l) that a vernacular 880 folds into its $a: the 880 paired with 240
# "Myŏlmang ihu ŭi segye. $l English" reads "멸망 이후의 세계. English" (LoC 2022942912, 2024951923).
# Kept, its normalize() is 'english' -- an alias Mangarr then matched on (export fixes E2, 2026-09-28).
_LANG_NOTE = re.compile(r"\s*\.\s*(?:English|Korean|Chinese|Japanese|French|German)\s*$")


def native_titles(r):
    """Vernacular titles: 880 fields paired ($6) with 245 / 246 / 240 / 130, and 246 $a in Hangul or
    Hanzi, each without a trailing '. <language>' note. An 880 paired with a 700 (a related work's
    author) is not a title."""
    out = []
    for f in M.fields(r, "880"):
        six = next((v for c, v in f if c == "6"), "")
        if re.match(r"(245|246|240|130)-", six):
            a = next((v for c, v in f if c == "a"), None)
            if a and _isbd(a):
                out.append(_isbd(a))
    out += [_isbd(v) for v in M.subs(r, "246", "a") if re.search("[\uac00-\ud7a3\u4e00-\u9fff]", v)]
    out = [_isbd(_LANG_NOTE.sub("", t)) for t in out]
    return list(dict.fromkeys(t for t in out if t))


def variant_titles(r):
    """The full title (245 $a : $b) when it differs from the title proper, then 246 $a (not in
    Hangul / Hanzi) -- the linker titles beyond title_proper / bare_title."""
    out = [full_title(r)] if full_title(r) != title_proper(r) else []
    out += [x for x in (_isbd(v) for v in M.subs(r, "246", "a")) if x and not re.search("[\uac00-\ud7a3\u4e00-\u9fff]", x)]
    return list(dict.fromkeys(out))


def series(r):
    return [(_isbd(n), v) for n, v in M.series_statements(r)]


CREATOR_RELATORS = {"aut", "art", "ill", "cre", "author", "artist", "illustrator", "creator", "cartoonist"}
RESP_SKIP = re.compile(r"translat|letter|rewrite|edit|adapt|colou?r|design|cover", re.I)
# a role label before the name ('original story, X', 'art by Y'); whole words only -- 'Artie Kim' keeps 'Art'
RESP_LABEL = re.compile(r"^(?:english\s+)?(?:original\s+)?(?:(?:story|art|script|illustrations?|written|drawn|"
                        r"created|webtoon|comic)\b)?(?:\s*by\b)?\s*[,:]?\s*", re.I)


def creators(r):
    """100 / 700 creators (relator from $4 -- LoC gives a URI, its last segment is the code -- or
    $e; translators, adapters, letterers out), a 700 naming the source work's author ($t), then the
    names in 245 $c ('original story, Chugong' -> Chugong; translation / rewrite / lettering out)."""
    out = []

    def add(n):
        n = re.sub(r"[\s,.;:]+$", "", M.clean(n))
        if n and n not in out:
            out.append(n)
    for tag in ("100", "700"):
        for s in M.fields(r, tag):
            a = next((v for c, v in s if c == "a"), None)
            if not a:
                continue
            if tag == "700" and any(c == "t" for c, _ in s):
                add(a)                                  # 'Graphic novelization of (work): Chugong.'
                continue
            roles = {v.rstrip("/").rsplit("/", 1)[-1].strip(" .,").lower() for c, v in s if c in ("4", "e")}
            if roles and not roles & CREATOR_RELATORS:
                continue
            add(a)
    for c in M.subs(r, "245", "c"):
        for seg in M.clean(c).split(";"):
            if RESP_SKIP.search(seg):
                continue
            add(RESP_LABEL.sub("", seg.strip()))
    return out
