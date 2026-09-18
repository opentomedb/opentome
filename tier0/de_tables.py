"""German Wikipedia volume extraction — wikitables, not templates.

de.wikipedia does not use a volume-list template, so this is NOT a dialect entry
in wikipedia_volumes.DIALECTS. It needs its own extractor.

Structure (Attack on Titan, typical):

    ! rowspan=3 | Band !! colspan=2 | Japanisch !! colspan=4 | Deutsch
    ! VÖ-Datum !! ISBN !! VÖ-Datum(x2) !! ISBN(x2)
    ! Einzel !! Deluxe !! Einzel !! Deluxe
    | {{0}}1 || {{DatumZelle|2010-03-17}} || ISBN 978-4-06-384276-0
             || {{DatumZelle|2014-03-18}} || ... || ISBN 978-3-551-74233-9

Three complications, and one gift:

  * rowspan cells shift column positions on following rows, so ANY parser keyed
    on cell index is wrong within three rows.
  * {{0}} is a zero-padding template inside the volume number.
  * Einzel (standard) and Deluxe are two distinct release lines in one table.

  * THE GIFT: ISBN registration groups identify the market outright.
    978-4 = Japan, 978-3 = German-language, 978-2 = French-language,
    978-0/978-1 = English-language. Market assignment therefore needs no
    column arithmetic at all, which sidesteps rowspan entirely.
"""
import os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# The registration-group table used to live here and keyed on the 4th digit
# only, which labelled 979-11 (Korea) and 979-10 (France) as English and
# dropped 979-8 (US). Solo Leveling bound to a Korean-ISBN "English" line with
# no dates because of it. One shared table now, see isbn.py.
from isbn import isbn_market   # noqa: F401

DATE_RE = re.compile(r"\{\{\s*DatumZelle\s*\|\s*(\d{4}-\d{2}-\d{2})", re.I)
ISBN_RE = re.compile(r"97[89][\s\-]?(\d)[\d\s\-]{7,14}[\dXx]")
ROW_SPLIT = re.compile(r"^\|-", re.M)


def tables(w):
    return re.findall(r"\{\|.*?\n\|\}", w, re.S)


def _volume_number(cell):
    c = re.sub(r"\{\{\s*0+\s*\}\}", "", cell)          # {{0}} zero-padding
    c = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", c)
    c = re.sub(r"<[^>]+>", " ", c)
    c = re.sub(r"\{\{[^{}]*\}\}", " ", c)
    c = re.sub(r"[!|]", " ", c)
    m = re.match(r"^\s*(\d{1,4}(?:[.,]\d)?)\s*$", c)
    return m.group(1).replace(",", ".") if m else None


def parse_table(t):
    """-> list of {volume, markets:{MKT:{date,isbn13}}}. rowspan-immune."""
    out = []
    for raw in ROW_SPLIT.split(t):
        if raw.lstrip().startswith("!") or "||" not in raw and "|" not in raw:
            continue
        cells = [c for c in re.split(r"\|\||\n\|", raw) if c.strip()]
        if not cells:
            continue
        vol = None
        for c in cells[:2]:
            vol = vol or _volume_number(c)
        if not vol:
            continue
        dates = DATE_RE.findall(raw)
        isbns = [re.sub(r"[^0-9Xx]", "", m.group(0)) for m in ISBN_RE.finditer(raw)]
        isbns = [i for i in isbns if len(i) == 13]
        if not (dates or isbns):
            continue
        rec = {"volume": vol, "markets": {}}
        # ISBNs self-identify their market; dates follow the header order
        # (Japanisch first, then the local market), which rowspan does not disturb
        # because we count dates rather than columns.
        by_mkt = {}
        for i in isbns:
            m = isbn_market(i)
            if m and m not in by_mkt:
                by_mkt[m] = i
        order = [m for m in ("JP", "DE", "FR", "EN") if m in by_mkt]
        order += [m for m in by_mkt if m not in order]        # KR, IT, ... keep their ISBN
        for idx, m in enumerate(order):
            e = {"isbn13": by_mkt[m]}
            if idx < len(dates):
                e["date"] = dates[idx]
                e["date_precision"] = "day"
            rec["markets"][m] = e
        if rec["markets"]:
            out.append(rec)
    return out


def extract(w, article):
    """All volume records from every ISBN-bearing table in the article."""
    recs = []
    for t in tables(w):
        if not ISBN_RE.search(t):
            continue
        for r in parse_table(t):
            r["article"] = article
            r["wiki"] = "de"
            recs.append(r)
    # de-duplicate on (volume, DE isbn) -- collapsible tables repeat content.
    # Volume labels are canonicalised ('01' -> '1') so two tables listing the
    # SAME volume of different editions of one market do not become two
    # volumes (Solo Leveling: 979-11 originals from two Korean editions). The
    # second edition's ISBN is dropped, and counted, not lost silently.
    seen, uniq, dropped = set(), [], 0
    for r in recs:
        r["volume"] = re.sub(r"^0+(\d)", r"\1", r["volume"])
        k = (r["volume"], r["markets"].get("DE", {}).get("isbn13"))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    by_num = {}
    for r in uniq:
        for mkt in list(r["markets"]):
            if (r["volume"], mkt) in by_num:
                del r["markets"][mkt]
                dropped += 1
            else:
                by_num[(r["volume"], mkt)] = True
    uniq = [r for r in uniq if r["markets"]]
    if dropped:
        print(f"    {article}: {dropped} duplicate (volume, market) entries dropped "
              f"(second edition in the same table set)", flush=True)
    return uniq
