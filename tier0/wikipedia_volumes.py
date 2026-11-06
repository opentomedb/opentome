"""Tier 0: extract per-volume records from Wikipedia {{Graphic novel list}} templates.

Clean room: no GCD data, no Readarr code. Facts only (volume no., date, ISBN,
chapter range) -- never prose/summaries. Each record keeps the article + any <ref>
so the primary source stays attributable.
"""
import datetime, hashlib, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from isbn import isbn_market, normalise_isbn, isbn10_to_13   # noqa: F401 (re-exported)

UA = ("manga-metadata-research/0.1 "
      "(non-commercial catalogue evaluation; https://github.com/opentomedb)")
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


_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


def _japonais_parts(parts):
    """{{japonais|texte|kana|romaji}} (fr-wiki): the first slot that carries no Japanese
    script, taking the part after ' / ' when an editor glued 'romaji / translation' into
    one. `parts` is already split at depth 0 (see _unwrap_one) -- a slot that is itself a
    nested template ('{{nowrap|C}}') travels as one whole param, never split on its own '|'."""
    cleaned = [re.sub(r"<br\s*/?>", " ", p).strip() for p in parts]
    for p in cleaned:
        if p and not _CJK.search(p):
            return p.split(" / ")[-1].strip() if " / " in p else p
    return cleaned[0] if cleaned else ""


# A proper roman-numeral GRAMMAR, uppercase only (real Wikipedia part-number
# templates are written {{I}}, {{VIII}}, {{XII}}) -- not just "every character is
# one of IVXLCDM", which also matched {{ill}} (a real interlanguage-link template)
# and any lowercase word built only from those letters (e.g. 'mix', 'did', 'civil').
_ROMAN_NUMERAL_RE = re.compile(r"^M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")


def _last_positional(params):
    """The last parameter that is not a named 'key=value' one -- {{lang|en|Kase-san
    and Morning Glories}}'s real text is its LAST positional slot (often a language
    code comes first), not its first."""
    positional = [p for p in params if not re.match(r"^\s*[\w-]+\s*=", p)]
    chosen = positional or params
    return chosen[-1].strip() if chosen else ""


def _unwrap_one(body):
    """body is one brace-balanced '{{...}}' span, braces included (see _unwrap_templates).
    nihongo/nihongo2/nihongo3 and japonais unwrap to clean text; lang/langue/nowrap pass
    through their last positional parameter and ruby-ja its base (first) parameter --
    these are pure formatting/language-tag wrappers around real title text, not noise; a
    bare roman-numeral template name ({{I}}..{{XII}}, or generally {{<ROMAN>}}) passes
    through as the numeral itself -- a volume/part number, not noise either. Every other
    template -- known or not -- contributes nothing, same as the old flat catch-all, but
    a template nested inside one of these (a {{nowrap}}, a {{lang}}, a footnote) is now
    consumed whole by the depth-0 param split instead of leaking a stray '}}' or '|'.
    Whatever a branch below returns is run back through _unwrap_templates(): a template
    nested INSIDE the chosen slot (not just alongside it) needs resolving too, or it is
    left as literal, still-templated text in the output (review round 1, finding 5)."""
    inner = body[2:-2]
    name_raw = inner.split("|", 1)[0].strip()
    name = name_raw.lower()
    params = _split_params(inner.split("|", 1)[1]) if "|" in inner else []
    if name in ("nihongo", "nihongo2", "nihongo3"):
        result = params[0].strip() if params else ""
    elif name == "japonais":
        result = _japonais_parts(params)
    elif name in ("lang", "langue", "nowrap"):
        result = _last_positional(params)
    elif name == "ruby-ja":
        result = params[0].strip() if params else ""
    elif name_raw and _ROMAN_NUMERAL_RE.match(name_raw):
        result = name_raw
    else:
        return ""
    return _unwrap_templates(result)


def _unwrap_templates(v):
    """Brace-balanced pass over every top-level {{...}} in v, the same depth counter
    _templates() uses to pull whole template bodies. The regex it replaces only ever
    matched up to the FIRST '}}' it found, so a template nesting another template
    (a {{nowrap}}, a {{lang}}, a footnote) either leaked the outer's own trailing '}}'
    (when the inner one had its own) or, unterminated, matched nothing and left a
    stray '{{' + '|' in the output."""
    out, i, n = [], 0, len(v)
    while i < n:
        if v[i:i + 2] == "{{":
            start, depth, j = i, 0, i
            while j < n:
                if v[j:j + 2] == "{{":
                    depth += 1; j += 2; continue
                if v[j:j + 2] == "}}":
                    depth -= 1; j += 2
                    if depth == 0:
                        break
                    continue
                j += 1
            if depth != 0:
                out.append(v[start:])          # unterminated: not a template, leave literal
                break
            out.append(_unwrap_one(v[start:j]))
            i = j
            continue
        out.append(v[i])
        i += 1
    return "".join(out)


def _clean(v):
    v = re.sub(r"<!--.*?-->", "", v, flags=re.S)      # editor notes are not values
    v = re.sub(r"<!--.*$", "", v, flags=re.S)          # an unterminated one is not a value either
    v = re.sub(r"<ref[^>]*/>", "", v)
    v = re.sub(r"<ref.*?</ref>", "", v, flags=re.S)
    v = re.sub(r"<br\s*/?>", " ", v, flags=re.I)
    v = re.sub(r"<rp>.*?</rp>|<rt>.*?</rt>", "", v, flags=re.S | re.I)   # furigana: keep the base text
    v = re.sub(r"</?ruby[^>]*>", "", v, flags=re.I)
    v = _unwrap_templates(v)
    v = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", v)
    v = re.sub(r"\[\[([^\]]*)\]\]", r"\1", v)
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
        "original_titles": ("OriginalTitle",),
        "licensed_titles": ("LicensedTitle",),
        "generic_titles": ("Title",),
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
        "original_titles": ("titre_1",),
        "licensed_titles": ("titre_2",),
        "generic_titles": ("titre",),
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


# ---- chapter numbers --------------------------------------------------------------------------
# Between two numbers, a dash written as an em dash, two hyphens, an entity or a template is the same
# dash ("1—9", "93--99", "3&ndash;5"). Only there: "Chapter 1 — A Title" stays unread, as it always was.
_CH_DASH_FORMS = re.compile(
    r"(?<=\d)\s*(?:--|&ndash;|&mdash;|&#8211;|&#8212;|—"
    r"|\{\{\s*(?:ndash|en ?dash|snd|spnd|spaced (?:ndash|en ?dash)|mdash|em ?dash|nbnd)\s*\}\})\s*(?=\d)", re.I)
# An entry's number, then the separator before its title -- past a part of that chapter in brackets
# ("Chapter 2 (Part 1): Title" is chapter 2).
_CH_FIRST = re.compile(r"\b(?:Chapter|Round|Episode|Act|Case|Night|Quest|Page|File|#)?"
                       r"\s*(\d{1,4})(\.\d+)?\s*(?:\((?:[Pp]art|[Pp]t|[Pp]artie)\.?\s*[0-9IVXivx]{1,4}\)\s*)?([:.–-])")
# An entry that is a chapter word and its number and nothing else: "Chapter 13", "File 41".
_CH_BARE = re.compile(r"['\"\s]*(Chapter|Round|Episode|Act|Case|Night|Quest|Page|File)\.?\s*(?:#\s*)?"
                      r"(\d{1,4})(\.\d+)?['\"\s]*", re.I)
# the far end of "12–21": an optional repeat of the label ("File.27 – File.41") and the number...
_CH_END = re.compile(r"\s*(?:([^\W\d_]{1,12})\.?\s*|#\s*)?(\d{1,4})(\.\d+)?(?!\d)")
# ...and then the end of the line or punctuation: "5 - 10 Things" is chapter 5 and its title, and
# "1 – 24.12.2029" ends on a date. After a plural ("Chapters 16–30 from the magazine") the entry
# can only be a range.
_CH_END_OF_ENTRY = re.compile(r"[ \t]*(?:$|\n|[(),;<{\[|}'\"]|[:.](?!\d))")
# The start of a range must sit where a chapter number sits: at the head of the entry, after markup
# and at most two words ("Chapters 12–21", "Lesson Time 15–21"), or right after a chapter word in a
# sentence that has no earlier number ("This book holds chapters 129-138.").
_CH_HEAD = re.compile(r"[\s'\"“”‘’\[\(#.:]*(?:[^\W\d_]{1,12}(?:[\s.:#]+|\Z)){0,2}")
_CH_WORDS = {"chapter", "round", "episode", "act", "case", "night", "quest", "page", "file", "issue",
             "chapitre", "épisode"}
# ...and never after a word for something that is numbered apart from the chapters.
_CH_NOT_CHAPTERS = {"special", "extra", "bonus", "side", "omake", "part", "vol", "volume", "book",
                    "tome", "short", "prologue", "epilogue", "interlude", "intermission",
                    "gaiden", "season", "arc", "ex",
                    "spécial", "spéciaux", "hors", "partie", "livre", "saison"}
# Of those, the words whose entry gives no number at all ("Bonus 1: ...", "Special Chapter 2: ...",
# "Extra Scene 3."): its number counts extras, and read as a chapter it claims a chapter of another
# volume. NOT part / vol / book / tome / season / arc: some series number their chapters "Vol 3".
_CH_APART = {"special", "extra", "bonus", "side", "omake", "short", "prologue", "epilogue", "interlude",
             "intermission", "gaiden", "ex", "spécial", "spéciaux", "hors"}
_CH_MAX_SPAN = 150      # a longer "range" is two unrelated numbers
# Entries that are not '*' bullets. A line that opens with ':' or '#', an HTML <li>, a '<br>' in a cell
# with no list markup, an item of a {{Bulleted list}}: each is an entry too, marked _CH_STRICT because it gives a
# number only at its HEAD -- a ':' line is often a note under a bullet, and "pages 5: ..." in it is
# no chapter.
_CH_STRICT = "\x00"
_CH_HEADING = "\x01"          # read like a strict entry, and never as a bare "File 20": that is the list's heading
_CH_WRAPPED = re.compile(r"^(?:\s*\{\{[^{}|]*\|)+")       # ':{{Nihongo|Theme 1. "A"|...}}': the head is inside the template
_CH_NOWIKI = re.compile(r"</?nowiki\s*/?>", re.I)
_CH_BR = re.compile(r"<br\s*/?>", re.I)
_CH_LINE_MARK = re.compile(r"^[ \t]*[:#]+", re.M)
_CH_ITEM_LISTS = ("Bulleted list", "Unbulleted list", "Ubl")
# Implicit numbers are read only where the source says where the count starts: {{Numbered list|start=N}}
# and its real name {{Ordered list}}, <ol start="N">, a '#' list whose item carries <li value="N">.
_CH_COUNTED_LISTS = ("Numbered list", "Ordered list")
_CH_OL = re.compile(r"<ol\b[^>]*\bstart\s*=\s*[\"']?(\d+)[^>]*>(.*?)(?=</ol\s*>|<ol\b|\Z)", re.I | re.S)
_CH_LI = re.compile(r"<li\b[^>]*>", re.I)
_CH_ITEM_OWN = re.compile(r"\b(?:Chapter|Chapitre|Episode|[ÉE]pisode)\s+(\d{1,4})\b", re.I)
_CH_HASH_ITEM = re.compile(r"^[ \t]*#(?![#*:;])[ \t]*(?:<li\s+value\s*=\s*[\"']?(\d+))?", re.M | re.I)
# An entry that opens with its number and goes straight into a quoted or templated title, with no
# separator: '07 "Title"', "Fight 1 {{nihongo|...}}". Markup and at most one word before the number.
_CH_TITLED = re.compile(r"([\s'\"“”‘’\[\(#.:]*)(?:([^\W\d_]{1,12})[\s.:#]*)?"
                        r"(\d{1,4})(\.\d+)?\s*(?=[\"“{]|'')")
# When quotes or bold opened before the number ("'''Chapitre 14''' : Title"), the mark after it
# closes them, and the entry is read only if a separator, a template or a title follows, or the
# word is a chapter word ('"Chapter 4" and extras'): in "''Sample 009'' Part II" and '"After 7"'
# the number is the end of a title.
_CH_AFTER_CLOSE = re.compile(r"['\"”’]+\s*(?:[:.–-]|\{\{|[\"“]|'')")
# A range in words, read only at the head of an entry and after a chapter word.
_CH_WORDED = re.compile(r"['\"\s]*(chap(?:ters?|itres?)|[ée]pisodes?)\s*(?::\s*)?"
                        r"(\d{1,4})(\.\d+)?\s+(?:à|to)\s+(\d{1,4})(\.\d+)?(?!\d)", re.I)


def _one_of(word, vocabulary):
    """`word` (lower case) or its singular is in `vocabulary`."""
    return word in vocabulary or (word.endswith("s") and word[:-1] in vocabulary)


def _chapter_number(whole, fraction):
    """18 -> 18, 18.5 -> 18.5 (a half chapter). Any other fraction is a part of chapter N -> N."""
    return int(whole) + 0.5 if fraction == ".5" else int(whole)


def _words(text):
    return [w.lower() for w in re.findall(r"[^\W\d_]+", text)]


def _range_tail(line, m):
    """The chapters after the first one when the entry gives a range ("Chapters 12–21" -> 13..21),
    else nothing. `m` is the _CH_FIRST match of the entry's first number."""
    if m.group(3) not in "–-":
        return []
    head = line[:m.start(1)]
    words = _words(head)
    if any(_one_of(w, _CH_NOT_CHAPTERS) for w in words[-2:]):
        return []
    label = words[-1] if words else ""
    after_chapter_word = (_one_of(label, _CH_WORDS) and re.search(r"[^\W\d_][\s.:#]*\Z", head)
                          and not re.search(r"\d", re.sub(r"\{\{[^{}]*\}\}", "", head)))
    if not (_CH_HEAD.fullmatch(head) or after_chapter_word):
        return []
    t = _CH_END.match(line, m.end())
    if not t:
        return []
    if t.group(1) and t.group(1).lower().rstrip("s") != label.rstrip("s"):   # "File.27 – File.41"
        return []
    plural = after_chapter_word and label.endswith("s")
    if not (plural or _CH_END_OF_ENTRY.match(line, t.end())):
        return []
    if len(m.group(1)) > 1 and m.group(1)[0] == "0" and len(t.group(2)) != len(m.group(1)):
        return []                                                            # "002–005", never "01-2"
    return _span(_chapter_number(m.group(1), m.group(2)), _chapter_number(t.group(2), t.group(3)))


def _span(first, last):
    """The chapters after `first` up to `last`; nothing when the two are not a range."""
    if not first < last <= first + _CH_MAX_SPAN:
        return []
    if first != int(first) and last != int(last):                            # "1.5–5.5": the halves
        return [first + k for k in range(1, int(last - first) + 1)]
    tail = list(range(int(first) + 1, int(last) + 1))
    if last != int(last):
        tail.append(last)
    return tail


def _worded_range(line):
    """Every chapter of an entry that opens with a range in words ("Chapitres 1 à 12",
    "Chapters 1 to 7"), else nothing."""
    m = _CH_WORDED.match(line)
    if not m or not (m.group(1).lower().endswith("s") or _CH_END_OF_ENTRY.match(line, m.end())):
        return []
    first = _chapter_number(m.group(2), m.group(3))
    tail = _span(first, _chapter_number(m.group(4), m.group(5)))
    return [first] + tail if tail else []


def _counted(v):
    """The numbers a cell states by COUNT: the items of a list that says where it starts."""
    nums = []
    for name in _CH_COUNTED_LISTS:
        for _p, body in _templates(v, name):
            parts = _split_params(body[2:-2])
            if any(re.match(r"\s*list[_-]style[_-]type\s*=", part) for part in parts[1:]):
                continue                                 # its own marker ('118.5. '): the items are not counted
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
    for m in _CH_OL.finditer(v):
        items = _CH_LI.split(m.group(2))[1:]
        # an item that names its own chapter ("Chapter 9" as the tenth item, after a prologue) says the
        # positions are not the chapter numbers: such a list is not counted
        own = [(k, int(x.group(1))) for k, it in enumerate(items, int(m.group(1)))
               for x in [_CH_ITEM_OWN.search(it[:120])] if x]
        if all(k == n for k, n in own):
            nums += range(int(m.group(1)), int(m.group(1)) + len(items))
    at = None                                            # a '#' list: counted from its first <li value="N">
    for m in _CH_HASH_ITEM.finditer(v):
        if m.group(1):
            at = int(m.group(1))
        if at is not None:
            nums.append(at)
            at += 1
    return nums


def _entries(v):
    """A chapter cell as [(mark, entry)]: mark '*' for a bullet (and the text before the first one),
    _CH_STRICT for an entry of another shape (a ':' / '#' line, a <li>, a '<br>' piece, a list-template
    item), _CH_HEADING for the text before the first entry of such a list ("File 20", then a '#' list)."""
    v = _CH_DASH_FORMS.sub("–", _CH_NOWIKI.sub("", v).replace("：", ":"))
    for name in _CH_ITEM_LISTS:
        for pos, body in reversed(list(_templates(v, name))):
            items = [p for p in _split_params(body[2:-2])[1:] if p.strip() and not re.match(r"\s*\w+\s*=", p)]
            v = v[:pos] + "".join("\n" + _CH_STRICT + it for it in items) + "\n" + v[pos + len(body):]
    v = _CH_LI.sub(_CH_STRICT, v)                        # an HTML list item (one _counted did not count)
    first = _CH_HEADING
    if "*" not in v and _CH_STRICT not in v and not _CH_LINE_MARK.search(v):
        v = _CH_BR.sub(_CH_STRICT, v)                    # no list markup at all: '<br>' parts the entries,
        first = "*"                                      # and the first one is read as the whole cell was
    parts = re.split("([*%s])" % _CH_STRICT, _CH_LINE_MARK.sub(_CH_STRICT, v))
    return [(first if parts[1:2] == [_CH_STRICT] else "*", parts[0])] + list(zip(parts[1::2], parts[2::2]))


def parse_chapters(v):
    """Chapter NUMBERS only -- pure facts, never titles.

    Three conventions in the wild:
      1. {{Numbered list|start=N|item|item|...}}  -> numbers implicit in item count (_counted)
      2. "* Chapter N: Title" / "* Chapter N" / '* N "Title"' -> numbers explicit
      3. "* Chapters N–M" / "Chapitres N à M"    -> a range, every chapter in it
    A half chapter ("18.5: Title") stays a half: floored, it would claim a chapter of another
    volume. A whole number that is not there is the costly mistake, so a doubtful entry gives
    its first number only, or nothing -- and an entry numbered apart from the chapters ("Bonus 1")
    gives nothing.
    """
    nums = []
    # fr: "* {{5e|episode}} : ..." -- ordinal template carries the number
    ord_hits = re.findall(r"\{\{\s*(\d{1,4})\s*(?:e|er|re)\s*\|", v)
    if ord_hits:
        return sorted({int(x) for x in ord_hits})
    nums = _counted(v)
    if nums:
        return sorted(set(nums))
    bare, tails, words, pair_starts, lead = [], [], set(), {}, None
    for mark, line in _entries(v):
        line = line.strip()
        m = _CH_BARE.fullmatch(line)
        if m:
            if mark != _CH_HEADING:
                bare.append(m)
            continue
        worded = _worded_range(line)
        if worded:
            nums += worded
            continue
        m = _CH_TITLED.match(line)
        if m:
            word = (m.group(2) or "").lower()
            in_quotes = re.search(r"['\"“‘]", m.group(1))
            if _one_of(word, _CH_NOT_CHAPTERS) or (in_quotes and not _one_of(word, _CH_WORDS)
                                                   and not _CH_AFTER_CLOSE.match(line, m.end())):
                continue            # "Bonus 1 ...", or a title that ends in a number: not this entry's number
            nums.append(_chapter_number(m.group(3), m.group(4)))
            if word:
                words.add(word.rstrip("s"))
            continue
        m = _CH_FIRST.search(line)
        if not m:
            continue
        if m.group(3) == "." and line[m.end():m.end() + 1].isdecimal():
            continue                # "103.5 A Title", "24.12.2029": a decimal point or a date, no separator
        first = _chapter_number(m.group(1), m.group(2))
        head = line[:m.start(1)]
        if any(_one_of(w, _CH_APART) for w in _words(head)[-2:]):
            continue                # "Bonus 1: ...", "Special Chapter 2: ...": numbered apart, no chapter
        if mark != "*" and not _CH_HEAD.fullmatch(_CH_WRAPPED.sub("", head)):
            continue                # an entry of another shape gives a number only at its head
        word = (_words(head)[-1:] or [""])[0]
        # ...and only under the word the cell's first numbered entry uses: "Parallel 1." after "06." "07."
        # "08." is numbered apart, whatever the word is
        if lead is None:
            lead = word.rstrip("s")
        elif mark != "*" and word.rstrip("s") != lead:
            continue
        nums.append(first)
        apart = _one_of(word, _CH_NOT_CHAPTERS)
        word = word.rstrip("s")
        if word and not apart and _CH_HEAD.fullmatch(head):
            words.add(word)                             # the word this list numbers its entries with
        if m.group(3) in "–-" and _CH_END.match(line, m.end()):
            pair_starts[word, first] = pair_starts.get((word, first), 0) + 1
            tails.append(_range_tail(line, m))
    # "Block 3-1", "Block 3-2", "Block 3-3": two pairs that start alike are parts of one chapter,
    # and then no pair in this list is trusted as a range.
    if all(n == 1 for n in pair_starts.values()):
        nums += [n for tail in tails for n in tail]
    # A bare entry is a chapter unless the list numbers its entries with another word: "Act 2"
    # under "Episode 7: Title" is a part of that episode.
    for m in bare:
        if all(w == m.group(1).lower() for w in words):
            nums.append(_chapter_number(m.group(2), m.group(3)))
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

        def _pick(keys):
            return next((_clean(p[k]) for k in keys if not _is_blank(p.get(k))), None)
        # The row title above is whatever is filled first; a market row wants ITS title
        # (the English list's English title on the English row, the Japanese one on the
        # Japanese row), else the generic field.
        generic = _pick(d.get("generic_titles", ()))
        t_orig = _pick(d.get("original_titles", ())) or generic
        t_lic = _pick(d.get("licensed_titles", ())) or generic
        if t_orig:
            rec["title_original"] = t_orig
        if t_lic:
            rec["title_licensed"] = t_lic
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
