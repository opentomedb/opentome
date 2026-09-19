"""Tier 0: extract per-volume records from Wikipedia {{Graphic novel list}} templates.

Clean room: no GCD data, no Readarr code. Facts only (volume no., date, ISBN,
chapter range) -- never prose/summaries. Each record keeps the article + any <ref>
so the primary source stays attributable.
"""
import datetime, hashlib, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from isbn import isbn_market, normalise_isbn, isbn10_to_13   # noqa: F401 (re-exported)

UA = ("manga-metadata-research/0.1 "
      "(non-commercial catalogue evaluation; https://github.com/DrAwesome441)")
API = "https://{lang}.wikipedia.org/w/api.php"

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cache")
MIN_INTERVAL = 1.1          # Wikipedia asks for serial, unhurried access
_last = [0.0]


def _throttle():
    wait = MIN_INTERVAL - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()


def _get(lang, params, retries=4):
    """Cached, throttled, backing-off GET. Cache makes re-runs hit zero network."""
    params = {**params, "format": "json", "formatversion": "2"}
    url = API.format(lang=lang) + "?" + urllib.parse.urlencode(params)
    os.makedirs(CACHE, exist_ok=True)
    key = os.path.join(CACHE, hashlib.sha256(url.encode()).hexdigest()[:32] + ".json")
    # The cache has no expiry by default -- a rebuild must be reproducible
    # offline. CACHE_MAX_AGE_DAYS opts into refreshing responses older than N
    # days, which is the only way new Wikipedia data ever enters the catalogue.
    max_age = float(os.environ.get("CACHE_MAX_AGE_DAYS", "0") or 0)
    if os.path.exists(key):
        fresh = (not max_age
                 or time.time() - os.path.getmtime(key) < max_age * 86400)
        if fresh:
            with open(key, encoding="utf8") as f:
                return json.load(f)
    delay = 2.0
    for attempt in range(retries):
        _throttle()
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.load(r)
            with open(key, "w", encoding="utf8") as f:
                json.dump(d, f, ensure_ascii=False)
            return d
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < retries - 1:
                time.sleep(delay); delay *= 2
                continue
            raise
    raise RuntimeError("exhausted retries")


def _norm_tokens(t):
    """Lowercase, strip punctuation, drop list-article filler words."""
    t = re.sub(r"[^\w\s]", " ", t.lower())
    stop = {"list", "of", "chapters", "volumes", "the", "manga", "series"}
    return {w for w in t.split() if w and w not in stop}


BAD_ARTICLE = re.compile(r"\b(characters?|episodes?|soundtrack|film|anime|season)\b", re.I)


def find_article(series, lang="en"):
    """Locate the volume/chapter list article, REJECTING non-matching series.

    A naive 'take the top hit' approach silently returned Kingdom for 'gyo',
    Ranma 1/2 for 'my dress up darling', and Hunter x Hunter for 'solo leveling'
    -- each with full, confident, entirely wrong volume data. Every candidate
    must now share the series' significant tokens, or we return None.
    """
    want = _norm_tokens(series)
    if not want:
        return None
    seen, ranked = set(), []
    for q in (f"List of {series} chapters", f"List of {series} volumes", series):
        try:
            hits = _get(lang, {"action": "query", "list": "search",
                               "srsearch": q, "srlimit": 8})["query"]["search"]
        except Exception:
            continue
        for h in hits:
            title = h["title"]
            if title in seen:
                continue
            seen.add(title)
            got = _norm_tokens(title)
            # every significant token of the series must appear in the title
            if not want <= got:
                continue
            tl = title.lower()
            score = 0
            if tl.startswith("list of"):
                score += 4
            if "chapter" in tl or "volume" in tl:
                score += 3
            if BAD_ARTICLE.search(title):
                score -= 6
            ranked.append((score, title))
    if not ranked:
        return None
    ranked.sort(key=lambda x: -x[0])
    return ranked[0][1]


def wikitext(title, lang="en"):
    d = _get(lang, {"action": "parse", "page": title, "prop": "wikitext"})
    if "parse" not in d:
        return None
    return d["parse"]["wikitext"]


def _split_params(body):
    """Split '|k = v' pairs at depth 0 only (values contain {{...}}, [[...]], <ref>)."""
    parts, buf, depth = [], [], 0
    i = 0
    while i < len(body):
        c2 = body[i:i + 2]
        if c2 in ("{{", "[["):
            depth += 1; buf.append(c2); i += 2; continue
        if c2 in ("}}", "]]"):
            depth -= 1; buf.append(c2); i += 2; continue
        if body[i] == "|" and depth == 0:
            parts.append("".join(buf)); buf = []; i += 1; continue
        buf.append(body[i]); i += 1
    parts.append("".join(buf))
    return parts


def _templates(w, name="Graphic novel list"):
    """Yield the body of each {{name ...}} template, brace-balanced."""
    for m in re.finditer(r"\{\{\s*" + re.escape(name), w, re.I):
        i, depth = m.start(), 0
        while i < len(w):
            if w[i:i + 2] == "{{":
                depth += 1; i += 2; continue
            if w[i:i + 2] == "}}":
                depth -= 1; i += 2
                if depth == 0:
                    yield (m.start(), w[m.start():i])
                    break
                continue
            i += 1


def _clean(v):
    v = re.sub(r"<!--.*?-->", "", v, flags=re.S)      # editor notes are not values
    v = re.sub(r"<ref[^>]*/>", "", v)
    v = re.sub(r"<ref.*?</ref>", "", v, flags=re.S)
    v = re.sub(r"\{\{nihongo\|([^|}]*)\|?([^|}]*)?.*?\}\}", r"\1", v, flags=re.S)
    v = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", v)
    v = re.sub(r"\[\[([^\]]*)\]\]", r"\1", v)
    v = re.sub(r"\{\{[^{}]*\}\}", "", v)
    v = re.sub(r"'''?", "", v)
    return re.sub(r"\s+", " ", v).strip()


def _refs(v):
    return re.findall(r"url\s*=\s*([^|}\s]+)", v)



# ---------------------------------------------------------------------
# DIALECTS -- language support is DATA, not code.
# Finding: fr.wikipedia uses {{TomeBD}}, isomorphic to en's
# {{Graphic novel list}} -- same architecture, different names. de.wikipedia
# uses wikitables instead and needs a separate extractor (not a dialect).
# ---------------------------------------------------------------------

EN_MONTHS = ["january","february","march","april","may","june","july",
             "august","september","october","november","december"]
FR_MONTHS = ["janvier","f\u00e9vrier","mars","avril","mai","juin","juillet",
             "ao\u00fbt","septembre","octobre","novembre","d\u00e9cembre"]

DIALECTS = {
    "en": {
        "template":      "Graphic novel list",
        "volume":        ("VolumeNumber",),
        "original_date": ("OriginalRelDate", "RelDate"),
        "original_isbn": ("OriginalISBN", "ISBN"),
        "licensed_date": ("LicensedRelDate",),
        "licensed_isbn": ("LicensedISBN",),
        "titles":        ("Title", "OriginalTitle", "LicensedTitle"),
        # the template's own "this work has no translation" flag
        "single_language": ("OneLanguage",),
        "chapter_prefix": "chapterlist",
        "months":        EN_MONTHS,
        "licensed_market": "EN",
    },
    "fr": {
        "template":      "TomeBD",
        "volume":        ("volume",),
        "original_date": ("sortie_1",),
        "original_isbn": ("isbn_1",),
        "licensed_date": ("sortie_2",),
        "licensed_isbn": ("isbn_2",),
        "titles":        ("titre_1", "titre_2", "titre"),
        "single_language": ("langage_unique",),
        "chapter_prefix": "chapitre",
        "months":        FR_MONTHS,
        "licensed_market": "FR",
    },
}

# The template's original-language slot is Japanese by convention, but the
# convention is wrong for Korean manhwa, French BD and US comics listed with
# the same template. The ISBN's registration group settles it when present.
DEFAULT_ORIGINAL_MARKET = "JP"

# Values an editor types to mean "none": a dash of any width, N/A, TBA, a bare
# question mark. These are NOT data, and treating them as data created 18,414
# English/French volumes with neither a date nor an ISBN.
PLACEHOLDER = re.compile(r"^(?:[-–—ー]+|&mdash;|&ndash;|n/?a\b.*|tba|tbd|\?+|none)$", re.I)


def _is_blank(v):
    """True when a template value carries no information after cleaning.
    Date templates are expanded first: `{{start date|2010|7|16}}` is data,
    even though _clean would strip it to nothing."""
    t = _clean(_expand_date_template(v or "")).strip()
    return not t or bool(PLACEHOLDER.match(t))


def _month_index(word, months):
    w = word.lower().strip(". ")
    if w.isdigit():
        n = int(w)
        return n if 1 <= n <= 12 else None
    for i, m in enumerate(months, 1):
        # full name, or a 3+ letter abbreviation in either direction
        # ("sept" ~ "september", "aug" ~ "august"; "mar" must not match "mai")
        if w == m or (len(w) >= 3 and (m.startswith(w) or w.startswith(m[:4]))):
            return i
        if len(w) == 3 and m[:3] == w:
            return i
    return None


_DATE_TPL = re.compile(
    r"\{\{\s*(start date|start-date|dts|date-|date rapide|date)\s*((?:\|[^{}]*)?)\}\}", re.I)


def _expand_date_template(v):
    """Flatten every date template to text parse_date can read.

    Forms seen in the corpus (counts from a full cache re-parse):
      {{start date|2023|2|9}}        1,383   -> 2023-02-09
      {{dts|2020|4|21}}                211   -> 2020-04-21
      {{date|16|juillet|2010}}               -> 16 juillet 2010   (the only form
                                                the old code handled)
      {{Date|16 septembre 2010}}     3,147   -> 16 septembre 2010
      {{Date|10|03|1998}}            6,276   -> 1998-03-10  (numeric month; was
                                                degraded to '1998')
      {{date-|...}} / {{date rapide|...}}     -> inner text
    Anything unrecognised is left for _clean to strip, exactly as before.
    """
    def one(m):
        parts = [p.strip() for p in m.group(2).split("|")[1:]]
        parts = [p for p in parts if p and "=" not in p]        # drop df=yes etc.
        if len(parts) >= 3:
            a, b, c = parts[0], parts[1], parts[2]
            a = re.sub(r"^(\d{1,2})(?:er|re|e)$", r"\1", a)      # 1er -> 1
            if a.isdigit() and b.isdigit() and c.isdigit():
                if len(a) == 4:                                  # Y|M|D
                    return f"{int(a):04d}-{int(b):02d}-{int(c):02d}"
                if len(c) == 4:                                  # D|M|Y
                    return f"{int(c):04d}-{int(b):02d}-{int(a):02d}"
            if a.isdigit() and c.isdigit():                      # D|month name|Y
                return f"{a} {b} {c}"
        if len(parts) == 2 and all(p.isdigit() for p in parts) and len(parts[0]) == 4:
            return f"{int(parts[0]):04d}-{int(parts[1]):02d}"    # Y|M
        return parts[0] if parts else ""
    return _DATE_TPL.sub(one, v)


DATE_PATS = [
    (r"\b((?:19|20)\d{2})-(\d{1,2})-(\d{1,2})\b", "ymd"),
    (r"\b(\w+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*((?:19|20)\d{2})\b", "mdy"),
    (r"\b(\d{1,2})(?:er|re|e)?\s+(\w+)\.?\s+((?:19|20)\d{2})\b", "dmy"),
]
MONTHS = {m.lower(): i for i, m in enumerate(
    ["January","February","March","April","May","June","July","August",
     "September","October","November","December"], 1)}


def _valid_day(y, mo, d):
    try:
        datetime.date(y, mo, d)
        return True
    except ValueError:
        return False


def parse_date(v, months=None):
    """-> (iso_or_none, precision) where precision in day|month|year|none.

    An invalid day (February 30) degrades to month precision rather than
    emitting a date that does not exist.
    """
    months = months or EN_MONTHS
    t = _clean(_expand_date_template(v))
    for pat, kind in DATE_PATS:
        m = re.search(pat, t)
        if not m:
            continue
        try:
            if kind == "ymd":
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            elif kind == "mdy":
                mo, d, y = _month_index(m.group(1), months), int(m.group(2)), int(m.group(3))
            else:
                d, mo, y = int(m.group(1)), _month_index(m.group(2), months), int(m.group(3))
        except (KeyError, ValueError, TypeError):
            continue
        if not mo or not 1 <= mo <= 12:
            continue
        if _valid_day(y, mo, d):
            return f"{y:04d}-{mo:02d}-{d:02d}", "day"
        return f"{y:04d}-{mo:02d}", "month"
    m = re.search(r"\b((?:19|20)\d{2})-(\d{1,2})\b", t)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}", "month"
    m = re.search(r"\b(\w+)\.?\s+((?:19|20)\d{2})\b", t)
    if m and _month_index(m.group(1), months):
        return f"{int(m.group(2)):04d}-{_month_index(m.group(1), months):02d}", "month"
    m = re.search(r"\b((?:19|20)\d{2})\b", t)
    return (m.group(1), "year") if m else (None, "none")


def parse_chapters(v):
    """Chapter NUMBERS only -- pure facts, never titles.

    Two conventions in the wild:
      1. {{Numbered list|start=N|item|item|...}}  -> numbers implicit in item count
      2. "* Chapter N: Title" bullets            -> numbers explicit
    """
    nums = []
    # fr: "* {{5e|episode}} : ..." -- ordinal template carries the number
    ord_hits = re.findall(r"\{\{\s*(\d{1,4})\s*(?:e|er|re)\s*\|", v)
    if ord_hits:
        return sorted({int(x) for x in ord_hits})
    for _p, body in _templates(v, "Numbered list"):
        parts = _split_params(body[2:-2])
        start, items = 1, 0
        for part in parts[1:]:                       # parts[0] is the template name
            m = re.match(r"\s*start\s*=\s*(\d+)", part)
            if m:
                start = int(m.group(1))
                continue
            if re.match(r"\s*\w+\s*=", part):        # any other named param
                continue
            if part.strip():
                items += 1
        nums += range(start, start + items)
    if nums:
        return sorted(set(nums))
    for line in v.split("*"):
        m = re.search(r"\b(?:Chapter|Round|Episode|Act|Case|Night|Quest|Page|File|#)?"
                      r"\s*(\d{1,4})(?:\.\d+)?\s*[:.\u2013-]", line.strip())
        if m:
            nums.append(int(m.group(1)))
    return sorted(set(nums))



ISBN_RE = re.compile(r"(97[89][\d\- ]{10,17}\d|\d[\d\- ]{8,12}[\dXx])")

# Volume labels an editor writes for the same physical thing. Canonicalise so
# '01' and '1' (from the en and fr articles of one work) hash to ONE volume,
# and so '1 (18)' / 'Volume 1' / '9 RE:' become the number they denote.
_NUM_PATS = [
    (r"^0*(\d+)$", 1),                                   # 01 -> 1
    (r"^0*(\d+)\.0$", 1),                                # 1.0 -> 1
    (r"^0*(\d+)\s*\(\s*\d+\s*\)$", 1),                   # 1 (18) dual numbering
    (r"^(?:volume|vol\.?|tome|band|bd\.?|#)\s*0*(\d+)$", 1),
    (r"^0*(\d+)\s+[A-Za-z:][^\d]*$", 1),                 # '9 RE:' -> 9 (label kept)
]
_RANGE = re.compile(r"^0*(\d+)\s*(?:[-–—]|&|à|to|bis)\s*0*(\d+)$")


def canon_number(label):
    """-> (number, kind, label) ; kind in int|range|decimal|special|blank.

    Returns number=None for placeholder rows ('—', '-', 'ー'), which are not
    volumes at all: they used to be stored and counted.
    """
    t = _clean(label or "").strip()
    if not t or PLACEHOLDER.match(t) or re.fullmatch(r"[-–—ー]+", t):
        return None, "blank", t
    for pat, g in _NUM_PATS:
        m = re.match(pat, t, re.I)
        if m:
            return str(int(m.group(g))), "int", t
    m = _RANGE.match(t)
    if m and int(m.group(1)) < int(m.group(2)):
        return f"{int(m.group(1))}-{int(m.group(2))}", "range", t
    if re.fullmatch(r"\d+\.\d+", t):
        return t, "decimal", t
    return t, "special", t


def _flag_true(v):
    return _clean(v or "").strip().lower() in ("yes", "oui", "on", "1", "true", "y")


def parse_volumes(w, article, lang="en"):
    d = DIALECTS.get(lang)
    if not d:
        return []
    months = d["months"]
    out = []
    for _pos, body in _templates(w, d["template"]):
        if "/" in body[:len(d["template"]) + 6]:      # skip /header, /Entête
            continue
        p = {}
        for part in _split_params(body[2:-2]):
            if "=" not in part:
                continue
            k, _, v = part.partition("=")
            p[k.strip()] = v.strip()
        raw_vn = next((p[k] for k in d["volume"] if p.get(k)), "")
        vn, kind, label = canon_number(raw_vn)
        if vn is None:
            continue
        rec = {"article": article, "wiki": lang, "volume": vn,
               "_offset": _pos, "markets": {}}
        if kind != "int":
            rec["special"] = True          # 'SP', 'Ex3', '7.5', '17-18' ...
        if label != vn:
            rec["volume_label"] = label
        if kind == "range":
            a, b = (int(x) for x in vn.split("-"))
            rec["contains_volumes"] = list(range(a, b + 1))
        title = next((_clean(p[k]) for k in d.get("titles", ()) if not _is_blank(p.get(k))), None)
        if title:
            rec["title"] = title
        single = any(_flag_true(p.get(k)) for k in d.get("single_language", ()))

        # A market entry exists only when that market has DATA -- a parsed date
        # or an ISBN. The template skeleton nearly always carries the licensed
        # params, so testing for their PRESENCE (as before) emitted an English
        # or French volume for every Japanese-only row: 29.5% of EN and 30.9%
        # of FR volumes were phantoms with neither date nor ISBN.
        for role, dks, iks, market in (
                ("original", d["original_date"], d["original_isbn"], DEFAULT_ORIGINAL_MARKET),
                ("licensed", d["licensed_date"], d["licensed_isbn"], d["licensed_market"])):
            if role == "licensed" and single:
                continue
            raw_d = next((p[k] for k in dks if not _is_blank(p.get(k))), None)
            raw_i = next((p[k] for k in iks if not _is_blank(p.get(k))), None)
            m = {}
            if raw_d:
                iso, prec = parse_date(raw_d, months)
                if iso:
                    m["date"], m["date_precision"] = iso, prec
                refs = _refs(raw_d)
                if refs:
                    m["date_source"] = refs[0]
            if raw_i:
                mm = ISBN_RE.search(_clean(raw_i))
                if mm:
                    i13, i10 = normalise_isbn(mm.group(1))
                    if i13:
                        m["isbn13"] = i13
                    if i10:
                        m["isbn10"] = i10
            if not (m.get("date") or m.get("isbn13")):
                continue
            # the original slot is Japanese by convention; its ISBN says otherwise
            # for Korean manhwa, French BD and US comics listed with the same template
            if role == "original" and m.get("isbn13"):
                market = isbn_market(m["isbn13"]) or market
            m["market"] = market
            rec["markets"][role] = m
        if not rec["markets"]:
            # An announced, unreleased volume: a title (or just a number) and
            # nothing else. It exists in the original market only -- never as a
            # licensed edition nobody has announced.
            if not (title or kind == "int"):
                continue
            rec["markets"]["original"] = {"market": DEFAULT_ORIGINAL_MARKET}
            rec["announced"] = True
        ch, raw_ch = [], ""
        for k, v in p.items():
            if k.lower().startswith(d["chapter_prefix"]):
                ch += parse_chapters(v)
                raw_ch += v
        if ch:
            rec["chapters"] = sorted(set(ch))
            rec["chapter_range"] = [min(ch), max(ch)]
        elif raw_ch.strip():
            # Content exists but carries NO numbers -- light-novel side-story
            # collections list named, unnumbered stories. Silently returning
            # nothing hid 8 such rows. The COUNT is a fact even when the titles
            # are not ours to copy, so record it and mark the shape.
            n = len(re.findall(r"^\s*[:*#]", raw_ch, re.M))
            if n:
                rec["contents_unnumbered"] = n
        out.append(rec)
    return out



def run(series, lang="en"):
    art = find_article(series, lang)
    if not art:
        return {"series": series, "error": "no article found"}
    w = wikitext(art, lang)
    if not w:
        return {"series": series, "article": art, "error": "no wikitext"}
    vols = parse_volumes(w, art, lang)
    if not vols and ("List of" not in art):
        pass
    return {"series": series, "article": art, "volumes": vols}


if __name__ == "__main__":
    res = run(sys.argv[1] if len(sys.argv) > 1 else "chainsaw man")
    print(json.dumps(res, ensure_ascii=False, indent=2)[:4000])
