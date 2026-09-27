"""BnF UNIMARC (marcxchange) field logic (docs/krcn-design.md §5). Pure functions; records() returns
tier0/dnb_marc.records()'s dict shape, so dnb_marc.fields / subs / first / clean apply. The cover
link field ('Première de couverture') is never read.

  003 ark (http://catalogue.bnf.fr/ark:/12148/cb<8 digits><check>) -> the record's key and source url
  010 $a ISBN            101 $a text / $c ORIGINAL language (kor / chi; the §6 origin test)
  101 $b intermediate (relay) language -- information only, never a filter (controller ruling:
         a French edition translated via English is still a French edition of the KR/CN work)
  200 $a title, $h volume, $i part, $e other title
  214 (ind2 0, the publication statement; ind2 3 is the printer) / 210 $c publisher, $d year
  215 $a extent ('1 vol. (235 p.)')    225 $a / $v, 461 $t / $v series    454 $t / 500 $a original title
  700 / 701 / 702 $a $b $4 people (070 author, 440 illustrator; 730 translator is not a creator)
"""
import re
import xml.etree.ElementTree as ET

import dnb_marc as M
from dnb_link import fold

NS = "{info:lc/xmlns/marcxchange-v2}"
BASE = "https://catalogue.bnf.fr/"


def records(text):
    root = ET.fromstring(text)
    out = []
    for rec in root.iter(NS + "record"):
        r = {"leader": "", "cf": {}, "df": []}
        for el in rec:
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "leader":
                r["leader"] = el.text or ""
            elif tag == "controlfield":
                r["cf"][el.get("tag")] = M.nfc(el.text)
            elif tag == "datafield":
                r["df"].append((el.get("tag"), el.get("ind1") or " ", el.get("ind2") or " ",
                                [(s.get("code"), M.nfc((s.text or "").strip())) for s in el]))
        if r["cf"].get("001"):
            out.append(r)
    return out


def ark(r):
    m = re.search(r"(ark:/12148/cb\d{8}[0-9a-z])", r["cf"].get("003") or "")
    return m.group(1) if m else None


def ark_number(a):
    """'ark:/12148/cb47253773p' -> 47253773: arks order by their 8-digit record number (§8)."""
    return int(re.search(r"cb(\d{8})", a).group(1))


def url(a):
    return BASE + a


def isbns(r):
    out = []
    for v in M.subs(r, "010", "a"):
        i13 = M._isbn13(re.sub(r"[^0-9Xx]", "", v))
        if i13 and i13 not in out:
            out.append(i13)
    return out


def origin(r):
    c = {v.strip().lower() for v in M.subs(r, "101", "c")}
    if "kor" in c:
        return "kor"
    if c & {"chi", "zho"}:
        return "chi"
    return None


def relay_languages(r):
    """101 $b: the language a translation was made through ('eng'). Information only: origin() and
    scope ignore it -- a relayed French edition stays in scope (controller ruling, 2026-09-27)."""
    return [v.strip().lower() for v in M.subs(r, "101", "b") if v.strip()]


def is_monograph(r):
    return r["leader"][6:8] == "am"


def _pub214(r, code):
    """$code of the 214 publication statement (ind2 '0'), chosen by indicator, not by field order."""
    return next((v for t, _, i2, s in r["df"] if t == "214" and i2 == "0" for c, v in s if c == code and v), None)


def _date_field(r):
    return _pub214(r, "d") or M.first(r, "210", "d") or ""


def is_set_record(r):
    """An open-ended record ('2003-') with no volume number is the series head, not a volume (P8)."""
    return bool(re.search(r"\d{4}\s*-\s*$", _date_field(r))) and not M.subs(r, "200", "h")


BUNDLE = re.compile(r"coffret|sous étui|\bétui\b|\bbox\b|\bpack\b|\blot de\b", re.I)
EXTRA = re.compile(r"artbook|art book|\bguide\b|calendrier|coloriage|carnet|agenda", re.I)


def excluded_kind(r):
    t = " ".join(M.subs(r, "200", "a") + M.subs(r, "200", "e") + M.subs(r, "200", "i") + M.subs(r, "010", "b"))
    if BUNDLE.search(t):
        return "bundle"
    if EXTRA.search(t):
        return "extra"
    h = " ".join(M.subs(r, "200", "h"))
    if M.canon_number(h)[1] == "range" or re.search(r"\bvolumes\b", h, re.I):
        return "range"
    return None


def title(r):
    return M.clean(M.first(r, "200", "a"))


ROMAN = {r: i + 1 for i, r in enumerate("I II III IV V VI VII VIII IX X XI XII XIII XIV XV XVI XVII XVIII "
                                        "XIX XX".split())}
WORDS = {"one": 1, "two": 2, "three": 3}
_WORD_NUM = re.compile(r"^\s*\[?\s*(?:(?:vol(?:ume)?|tome|t)\.?\s+)?([A-Za-z]+)\s*\.?\s*\]?\s*$", re.I)


def _word_number(h):
    """200 $h 'IV' / 'Tome I' / 'Vol. VI' (roman I-XX) or 'One' / 'Two' / 'Three' -> '4' ...; else None."""
    m = _WORD_NUM.match(M.clean(h))
    if not m:
        return None
    w = m.group(1)
    n = ROMAN.get(w.upper()) or WORDS.get(w.lower())
    return str(n) if n else None


def volume_number(r):
    for tag, code in (("200", "h"), ("225", "v"), ("461", "v")):
        for v in M.subs(r, tag, code):
            num, kind = M.canon_number(v)
            if kind in ("int", "decimal"):
                return num
            if kind == "range":
                return None
            if tag == "200" and _word_number(v):
                return _word_number(v)
    return None


def series(r):
    return M.clean(M.first(r, "461", "t") or M.first(r, "225", "a") or "") or None


def publisher(r):
    return M.clean(_pub214(r, "c") or M.first(r, "210", "c") or "") or None


def pubfam(p):
    """Kbooks = Delcourt-Kbooks = Groupe Delcourt-Kbooks (§8); else the folded name's first 6."""
    if re.search(r"kbooks", p or "", re.I):
        return "kbooks"
    return fold(p or "", False)[:6]


def year(r):
    m = re.search(r"\b((?:19|20)\d\d)\b", _date_field(r))
    return m.group(1) if m else None


def pages(r):
    a = M.clean(M.first(r, "215", "a"))
    if re.match(r"^\s*(?:[2-9]|[1-9]\d+)\s+vol", a):
        return None                      # several volumes in one record
    m = re.search(r"(\d{2,4})\s*p\.", a)
    return int(m.group(1)) if m and 0 < int(m.group(1)) <= 2000 else None


def original_titles(r):
    return [x for x in (M.clean(v) for v in M.subs(r, "454", "t") + M.subs(r, "500", "a")) if x]


CREATOR_CODES = {"070", "440"}


def creators(r):
    out = []
    for tag in ("700", "701", "702"):
        for s in M.fields(r, tag):
            codes = {v.strip() for c, v in s if c == "4"}
            if codes and not codes & CREATOR_CODES:
                continue
            a = next((v for c, v in s if c == "a"), None)
            b = next((v for c, v in s if c == "b"), None)
            if a:
                n = M.clean(a + (" " + b if b else ""))
                if n not in out:
                    out.append(n)
    return out
