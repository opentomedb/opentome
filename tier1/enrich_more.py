"""Second-opinion enrichment for the EN and FR markets.

78.9% of resolved fields were `single_source` purely because openBD covers only
Japanese ISBNs -- the calibration machinery was starved of input for two of the
three markets, which capped auto-acceptable at 21% regardless of how good the
rule was. Verification COVERAGE, not the rule, was the limiting factor.

  EN -> Open Library   free, no key, batched, day-precision dates (20/20 on probe)
  FR -> BnF SRU        free, no auth, exact ISBN match, UNIMARC

Library of Congress was tried first for EN and rejected: its SRU returned zero
records even for control queries it certainly holds.
"""
import datetime, json, os, re, sqlite3, sys, time
import urllib.parse, urllib.request, urllib.error
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "schema"))
from verify import _fetch                      # disk-cached + throttled
from load import LICENCE                       # one licence table, not per-file guesses

import os


def _build(name):
    """Default build-output path. Never /tmp: macOS cleaned it and destroyed a
    fully-built catalogue. Outputs belong beside the cache, inside the repo."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(root, "build")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


NOW = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
UA = "opentome/0.1 (catalogue research; non-commercial evaluation)"

MONTHS = {m.lower(): i for i, m in enumerate(
    ["January","February","March","April","May","June","July","August",
     "September","October","November","December"], 1)}


def parse_ol_date(s, market="EN"):
    """Open Library dates are inconsistent. Observed forms:

        '2003'                year
        'September 2003'      month
        'September 9, 2003'   day
        'Sep 02, 2020'        day, abbreviated month
        '16/02/2022'          day, NUMERIC -- and DD/MM in French listings

    The numeric form is genuinely ambiguous: '05/03/2022' is 5 March in France
    and 3 May in the US, and guessing wrong writes a plausible, silent, wrong
    date -- the exact failure class this project keeps hitting. So a numeric
    date is only accepted at day precision when the first field is > 12 and
    therefore unambiguous; otherwise it degrades to month precision rather
    than gamble.
    """
    if not s:
        return None, None
    s = s.strip()

    def mi(word):
        w = word.lower().strip(".")
        for name, n in MONTHS.items():
            if w == name or (len(w) >= 3 and name.startswith(w)):
                return n
        return None

    m = re.match(r"^(\w+)\.?\s+(\d{1,2}),\s*(\d{4})$", s)      # Sep 02, 2020
    if m and mi(m.group(1)):
        return "%04d-%02d-%02d" % (int(m.group(3)), mi(m.group(1)), int(m.group(2))), "day"

    m = re.match(r"^(\d{1,2})\s+(\w+)\.?\s+(\d{4})$", s)        # 2 septembre 2020
    if m and mi(m.group(2)):
        return "%04d-%02d-%02d" % (int(m.group(3)), mi(m.group(2)), int(m.group(1))), "day"

    m = re.match(r"^(\w+)\.?\s+(\d{4})$", s)                     # September 2003
    if m and mi(m.group(1)):
        return "%04d-%02d" % (int(m.group(2)), mi(m.group(1))), "month"

    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)             # 16/02/2022
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12 and b <= 12:            # unambiguous: a is the day
            return "%04d-%02d-%02d" % (y, b, a), "day"
        if b > 12 and a <= 12:            # unambiguous: b is the day
            return "%04d-%02d-%02d" % (y, a, b), "day"
        return "%04d-%02d" % (y, b if market != "EN" else a), "month"   # ambiguous -> degrade

    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        return s, "day"
    m = re.match(r"^(\d{4})$", s)
    if m:
        return m.group(1), "year"
    return None, None


def _claim(db, vid, field, value, source, url, licence=None):
    licence = licence or LICENCE[source]
    db.execute("""INSERT OR REPLACE INTO claim
        (entity,entity_id,field,value,source,source_url,licence,retrieved_at)
        VALUES('volume',?,?,?,?,?,?,?)""", (vid, field, value, source, url, licence, NOW))


def enrich_openlibrary(db, batch=50, limit=None, market="EN"):
    rows = db.execute("""SELECT v.id, v.isbn13 FROM volume v
        JOIN release_line rl ON rl.id=v.release_line_id
        WHERE rl.market=? AND v.isbn13 IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM claim c WHERE c.entity='volume'
              AND c.entity_id=v.id AND c.source='openlibrary')""", (market,)).fetchall()
    if limit:
        rows = rows[:limit]
    by = {}
    for vid, isbn in rows:
        by.setdefault(isbn, []).append(vid)
    isbns = sorted(by)
    print(f"  Open Library[{market}]: {len(isbns):,} distinct ISBNs in {len(isbns)//batch+1} batches", flush=True)
    hit = ins = 0
    for i in range(0, len(isbns), batch):
        chunk = isbns[i:i+batch]
        url = ("https://openlibrary.org/api/books?bibkeys=" +
               ",".join("ISBN:"+x for x in chunk) + "&format=json&jscmd=data")
        d = _fetch(url, interval=0.6)
        if not isinstance(d, dict) or "_error" in d or "_http_error" in d:
            continue
        for key, rec in d.items():
            isbn = key.split(":", 1)[1]
            hit += 1
            iso, prec = parse_ol_date(rec.get("publish_date"), market)
            for vid in by.get(isbn, []):
                if iso:
                    _claim(db, vid, "release_date", iso, "openlibrary",
                           f"https://openlibrary.org/isbn/{isbn}")
                    ins += 1
                if rec.get("number_of_pages"):
                    _claim(db, vid, "page_count", str(rec["number_of_pages"]),
                           "openlibrary", f"https://openlibrary.org/isbn/{isbn}")
        db.commit()
        if (i//batch) % 20 == 0 and i:
            print(f"    {i:,}/{len(isbns):,}  found={hit:,} claims={ins:,}", flush=True)
    return len(isbns), hit, ins


BNF_NS = {"x": "info:lc/xmlns/marcxchange-v2", "s": "http://www.loc.gov/zing/srw/"}


def enrich_bnf(db, limit=None):
    rows = db.execute("""SELECT v.id, v.isbn13 FROM volume v
        JOIN release_line rl ON rl.id=v.release_line_id
        WHERE rl.market='FR' AND v.isbn13 IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM claim c WHERE c.entity='volume'
              AND c.entity_id=v.id AND c.source='bnf')""").fetchall()
    if limit:
        rows = rows[:limit]
    print(f"  BnF: {len(rows):,} FR volumes (one SRU call each)", flush=True)
    hit = ins = 0
    for n, (vid, isbn) in enumerate(rows, 1):
        url = ("https://catalogue.bnf.fr/api/SRU?version=1.2&operation=searchRetrieve"
               "&recordSchema=unimarcxchange&maximumRecords=1&query=" +
               urllib.parse.quote(f'bib.isbn all "{isbn}"'))
        raw = _fetch_xml(url)
        if not raw:
            continue
        try:
            root = ET.fromstring(raw)
        except Exception:
            continue
        rec = root.find(".//x:record", BNF_NS)
        if rec is None:
            continue
        hit += 1
        g = lambda t, c: next((s.text for df in rec.findall(f".//x:datafield[@tag='{t}']", BNF_NS)
                               for s in df.findall("x:subfield", BNF_NS) if s.get("code") == c), None)
        vol, ext = g("200", "h"), g("215", "a")
        src = f"https://catalogue.bnf.fr/api/SRU?query=bib.isbn+all+%22{isbn}%22"
        if vol:
            _claim(db, vid, "volume_number", vol.strip(), "bnf", src)
            ins += 1
        if ext:
            m = re.search(r"(\d{2,4})\s*p", ext)
            if m:
                _claim(db, vid, "page_count", m.group(1), "bnf", src)
                ins += 1
        if n % 200 == 0:
            db.commit()
            print(f"    {n:,}/{len(rows):,}  found={hit:,} claims={ins:,}", flush=True)
    db.commit()
    return len(rows), hit, ins


_last = [0.0]
def _fetch_xml(url, interval=1.0):
    """XML sibling of _fetch -- same disk cache, same politeness."""
    import hashlib
    from verify import CACHE
    os.makedirs(CACHE, exist_ok=True)
    key = os.path.join(CACHE, hashlib.sha256(url.encode()).hexdigest()[:32] + ".xml")
    if os.path.exists(key):
        return open(key, encoding="utf8").read()
    w = interval - (time.time() - _last[0])
    if w > 0:
        time.sleep(w)
    _last[0] = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            t = r.read().decode("utf8", "ignore")
        open(key, "w", encoding="utf8").write(t)
        return t
    except Exception:
        return None


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else _build("opentome.db")
    which = sys.argv[2] if len(sys.argv) > 2 else "ol"
    lim = int(sys.argv[3]) if len(sys.argv) > 3 else None
    db = sqlite3.connect(p)
    if which in ("ol", "both"):
        print("openlibrary:", enrich_openlibrary(db, limit=lim, market="EN"))
    if which in ("olfr", "both"):
        print("openlibrary FR:", enrich_openlibrary(db, limit=lim, market="FR"))
    if which in ("bnf", "both"):
        print("bnf:", enrich_bnf(db, limit=lim))
