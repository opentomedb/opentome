"""Split a flattened Wikipedia volume article into distinct release lines.

Franchise articles stack every sub-series into one list, so "v2" means
different works in different rows. Cross-verification caught this: SAO "v6"
was actually *Progressive 3 (light novel)*.

The fix needs NO external source. Section headings already identify the
lines exactly, and the hierarchy carries the medium:

    Light novels > Volumes                              -> light_novel, main line
    Manga > Main arcs > Truth of Zero                   -> manga, "Truth of Zero"
    Volumes > Sword Art Online: Unital Ring             -> manga, "Unital Ring"

Independently corroborated: Google Books returned "Unital Ring, Vol. 2
(manga)" and "Chapter 4: the Sanctuary and the Witch of Greed" for the same
ISBNs -- matching these headings. Google Books is disqualified as a stored
source (ToS forbids database-building); headings give the same answer free.
"""
import re

HEADING_RE = re.compile(r"^(={2,5})\s*(.+?)\s*\1\s*$", re.M)

# ordered: first match wins, so "light novel" beats bare "novel"
MEDIUM_HINTS = [
    ("light_novel", r"light\s*novel|\bln\b"),
    ("manhwa",      r"manhwa|webtoon"),
    ("manhua",      r"manhua"),
    ("manga",       r"manga|4-?koma|comic"),
    ("novel",       r"\bnovels?\b"),
    ("artbook",     r"art\s*book|databook|guide\s*book"),
]

# Headings that NAME a medium in words MEDIUM_HINTS lacks (heading cleanup A, 2026-09-29, spec §3.1
# class 2). Each matches ONE WHOLE heading of the path, never a substring and never the article
# title: r"\broman\b" over the title would make "Cestvs: The Roman Fighter" a novel, and an arc
# heading "Le Roman de Chiyo" is not a novel section. Read after MEDIUM_HINTS, before the title.
# "Roman illustré" is French Wikipedia's [[Light novel|Roman illustré]] (_clean_heading keeps the
# label): light_novel, or its volumes would copy the JP light-novel line as a 'novel' line.
HEADING_MEDIUM_HINTS = [
    ("light_novel", re.compile(r"^roman illustr[ée]$", re.I)),
    ("manga", re.compile(r"^bande dessin[ée]e$", re.I)),
    ("novel", re.compile(r"^(?:romans?|roman web|liste des romans|novelizations?)$", re.I)),
]

# Round-A headings (heading cleanup A, 2026-09-29, spec §3.1 classes 1 and 2): words that name no
# line, or name only a medium. None of them was in GENERIC before the round ("media", "publications",
# "liste des tomes", "novel series" already were), so HELD below is exactly what the round changed.
_ROUND_A = (
    r"médias?|medias|parution|production|publication history|publication and conception|"
    r"books and publications|related media|works|personnages|synopsis|plot(?: summary)?|books?|"
    r"liste de volumes|listes des volumes|d[ée]tail des volumes|list of chapters|"
    r"chapter and volume list|manga volumes|"
    r"romans?|roman illustr[ée]|roman web|liste des romans|novelizations?|"
    r"liste des light novels?|liste des volumes du light novel|bande dessin[ée]e|mangas|web novels?")
# pagination with an open end: "Tomes 21 à aujourd'hui", "Volumes 11 to present"
_OPEN_END = r"^(?:tomes?|volumes?)\s*\d+\s*(?:à|a|to)\s*(?:aujourd['’]hui|today|present)$"

# leaf headings that name no line -- fall through to the work title
GENERIC = re.compile(
    r"^(volumes?|volume list|tomes?|chapitres?|chapters?|list|main|"
    r"main arcs?|side stories|spin-?offs?|other|others|media|publications?|"
    r"volumes? reli[\u00e9e]s?|tomes? reli[\u00e9e]s?|s[\u00e9e]rie principale|"
    r"liste des (?:volumes|tomes|chapitres)(?: et chapitres)?|list of volumes|"
    r"chapter list|volumes? listing|volumes? list|novel series|main series|"
    r"tank[\u014do]bon|production et supports|productions et supports|"
    r"production and release|other media|autres m[\u00e9e]dias|"
    r"(?:19|20)\d{2}(?:\s*[-\u2013]\s*(?:19|20)\d{2})?|"
    r"story arcs?|tomes? classiques?|arcs? narratifs?|"
    r"light novels?|manga|manhwa|manhua|novels?|webtoons?|"
    r"adaptations?|manga adaptations?|adaptations? en manga|"
    + _ROUND_A + r"|"
    r"releases?)$", re.I)

# Pagination headings chunk a long list for readability -- "Tomes 1 à 10",
# "Volumes 11-20", "Bände 1 bis 10". They are NOT release lines. Splitting on
# them shatters one line into arbitrary decades.
PAGINATION = re.compile(
    r"^(tomes?|volumes?|b[\u00e4a]nde?|chapters?|chapitres?|vols?\.?)\s*"
    r"\d+\s*(?:\u00e0|a|to|bis|[-\u2013\u2014])\s*\d+$|" + _OPEN_END, re.I)

# What the round made fall through. line_name(hold=True) names a line after these again -- the name the
# collision guard (hold_clashes) restores when a fall-through would land on another edition's volumes.
HELD = re.compile(r"^(?:" + _ROUND_A + r")$|" + _OPEN_END, re.I)


def _headings(w):
    return [(m.start(), len(m.group(1)), m.group(2).strip())
            for m in HEADING_RE.finditer(w)]


def _stack_at(heads, pos):
    stack = []
    for hpos, lvl, txt in heads:
        if hpos > pos:
            break
        stack = [x for x in stack if x[0] < lvl]
        stack.append((lvl, txt))
    return [t for _, t in stack]


def _clean_heading(t):
    t = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"\[\[([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"<ref.*?</ref>", "", t, flags=re.S)
    t = re.sub(r"<ref[^>]*/>", "", t)
    # {{lang|en|Light novel}} / {{langue|ja-latn|Tankōbon}} / {{nihongo|X|...}}
    # -> the text. 59 line names shipped with raw template syntax before this.
    t = re.sub(r"\{\{\s*(?:lang|langue|lang-\w+|nihongo|transl)\s*\|(?:[^|{}]*\|)?([^|{}]*)[^{}]*\}\}",
               r"\1", t, flags=re.I)
    t = re.sub(r"\{\{[^{}]*\}\}", "", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", t).strip(" ()")


def detect_medium(path, article_title, default="manga", headings=True):
    """Medium from the heading path, else a whole heading that names one (HEADING_MEDIUM_HINTS,
    deepest first), else the article title, else default. headings=False skips HEADING_MEDIUM_HINTS:
    the pre-round rule, the medium a group the collision guard holds keeps."""
    joined = " > ".join(path)
    for medium, pat in MEDIUM_HINTS:
        if re.search(pat, joined, re.I):
            return medium
    for txt in (reversed(path) if headings else ()):
        for medium, pat in HEADING_MEDIUM_HINTS:
            if pat.match(txt.strip()):
                return medium
    for medium, pat in MEDIUM_HINTS:
        if re.search(pat, article_title or "", re.I):
            return medium
    return default


def _tokens(s):
    return {w for w in re.sub(r"[^\w\s]", " ", s.lower()).split() if len(w) > 3}


def line_name(path, work_title, hold=False):
    """Return (qualified, raw).

    `raw` is the deepest non-generic heading as written -- how readers refer
    to it ("Unital Ring"). `qualified` is unambiguous across works, which a
    catalogue needs: a bare "Second edition" or "Truth of Zero" means nothing
    without its parent work. hold=True names the line after a round-A heading
    (HELD) as before the round: the name the collision guard restores.
    """
    raw = None
    for txt in reversed(path):
        c = _clean_heading(txt)
        if c and ((not GENERIC.match(c) and not PAGINATION.match(c)) or (hold and HELD.match(c))):
            raw = c
            break
    if not raw:
        return work_title, work_title
    # already names its own work? leave it alone. Substring, not token overlap:
    # "Truth of Zero" shares the token "zero" with "Re:Zero" but is NOT self-naming.
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    if norm(work_title) and norm(work_title) in norm(raw):
        return raw, raw
    return f"{work_title} ({raw})", raw


# A row title of the form "<stem> <n>" -- "Sword Art Online: Progressive: Barcarolle
# of Froth 1". The stem is everything before the trailing number.
TITLE_NUM = re.compile(r"^(.*?)[\s,:\-\u2013]*(?:vol(?:ume)?\.?|tome|band|livre|book|#)?\s*(\d{1,3})\s*$", re.I)


def _stem(title):
    m = TITLE_NUM.match(title or "")
    if not m or not m.group(1).strip():
        return None, None
    return m.group(1).strip(" :,-\u2013"), int(m.group(2))


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def split_arcs(records, work_title):
    """Split follow-up arcs that Wikipedia numbers continuously inside ONE heading.

    The English *Sword Art Online: Progressive* table numbers its rows 1-14, but
    rows 8-14 are titled "Progressive: Barcarolle of Froth 1", "... 2",
    "Scherzo of Deep Night 1" ... -- separate series that Yen Press numbers
    from 1. Left alone, a consumer sees a 14-volume line, seven volumes it can
    never find, and a series that looks permanently unfinished.

    The signal is in the row TITLE, not the heading: a run of two or more
    consecutive rows whose title stem differs from the line's own stem and
    whose title numbering restarts at 1 is its own release line, numbered by
    its titles. A single odd row is left alone -- one row is not a run.
    """
    groups = {}
    for i, r in enumerate(records):
        groups.setdefault((r.get("medium"), r.get("line")), []).append(i)
    out = [dict(r) for r in records]
    for (_, line), idxs in groups.items():
        idxs.sort(key=lambda i: records[i].get("_offset", i))
        stems = [_stem(records[i].get("title")) for i in idxs]
        base = next((s for s, n in stems if s), None)
        if not base:
            continue
        j = 0
        while j < len(idxs):
            s, n = stems[j]
            if s and _norm(s) != _norm(base) and n == 1 and not GENERIC.match(s):
                k = j + 1
                while (k < len(idxs) and stems[k][0] and _norm(stems[k][0]) == _norm(s)
                       and stems[k][1] == stems[k - 1][1] + 1):
                    k += 1
                if k - j >= 2:
                    # name it the way line_name() would: self-named if it carries
                    # the work title, else qualified; the arc alone is the raw name
                    raw = s
                    for prefix in (base, work_title):
                        if _norm(prefix) and _norm(raw).startswith(_norm(prefix)) and len(raw) > len(prefix):
                            raw = re.sub(r"^" + re.escape(prefix) + r"[\s:,\-\u2013]*", "", raw, flags=re.I).strip() or raw
                    # a stem that BEGINS with the work title is already a full name
                    # ("Sword Art Online: Progressive: Barcarolle of Froth"); one that
                    # merely contains it ("Part IX. 100% W.I.T.C.H.") is not
                    qualified = s if _norm(s).startswith(_norm(work_title)) else f"{work_title} ({s})"
                    for idx in idxs[j:k]:
                        rec = out[idx]
                        rec["line"], rec["line_raw"] = qualified, raw
                        rec["volume"] = str(_stem(rec.get("title"))[1])
                        rec["arc_of"] = line
                    j = k
                    continue
            j += 1
    return out


def split(wikitext_src, article_title, work_title, records):
    """Annotate parsed volume records with medium / line / heading path.

    Each record carries its own `_offset` from the parser, so attribution
    can never drift out of alignment -- pairing two parallel lists by index
    was a real bug that silently reassigned volumes between lines.
    """
    heads = _headings(wikitext_src)
    out = []
    for rec in records:
        pos = rec.get("_offset", 0)
        path = [_clean_heading(t) for t in _stack_at(heads, pos)]
        rec = dict(rec)
        rec["medium"] = detect_medium(path, article_title)
        rec["line"], rec["line_raw"] = line_name(path, work_title)
        held = line_name(path, work_title, hold=True)
        if held[0] != rec["line"]:              # it fell through a round-A heading: hold_clashes may restore it
            rec["line_held"], rec["line_held_raw"] = held
            rec["medium_held"] = detect_medium(path, article_title, headings=False)     # and its pre-round medium
        rec["line_path"] = path
        out.append(rec)
    return split_arcs(out, work_title)


def summarise(records):
    from collections import Counter
    c = Counter((r["medium"], r["line"]) for r in records)
    return sorted(c.items(), key=lambda kv: -kv[1])
