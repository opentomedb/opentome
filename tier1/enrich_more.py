"""Second-opinion enrichment for the EN and FR markets.

78.9% of resolved fields were `single_source` purely because openBD covers only
Japanese ISBNs -- the calibration machinery was starved of input for two of the
three markets, which capped auto-acceptable at 21% regardless of how good the
rule was. Verification COVERAGE, not the rule, was the limiting factor.

  EN -> Open Library   free, no key, batched, day-precision dates (20/20 on probe)
  FR -> BnF SRU        free, no auth, exact ISBN match, UNIMARC

Library of Congress was rejected here once: its SRU answered "zero records" even for control
queries. That was SRU diagnostic 61 ("First record position out of range", HTTP 200), which
the KR/CN round's LoC client pages through (tier0/loc_sru.py, docs/krcn-design.md §3).

    python3 tier1/enrich_more.py <db> plan
        Zero network: prints the EN and FR Open Library plan dicts (enrich_openlibrary(plan=True)),
        after deriving whatever new per-ISBN entries `ol_adopt` can from cached batches on disk.
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


import hashlib
import verify as _V

OL_API = "https://openlibrary.org/api/books?bibkeys=%s&format=json&jscmd=data"


def ol_url(isbns):
    return OL_API % ",".join("ISBN:" + x for x in isbns)


def ol_isbn_path(isbn):
    """The per-ISBN entry: the cache file of the SINGLE-ISBN url -- the answer Open Library gives
    for that url ({'ISBN:<isbn>': rec}, or {} when it holds nothing). tier1/covers.py reads it as
    it reads any batch. Keyed per ISBN, so adding ISBNs never re-keys anything (krcn-design §12)."""
    return os.path.join(_V.CACHE, hashlib.sha256(ol_url([isbn]).encode()).hexdigest()[:32] + ".json")


def ol_entry(isbn):
    """-> the per-ISBN record ({} = asked, not held), or None when there is no entry."""
    p = ol_isbn_path(isbn)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf8") as f:
        d = json.load(f)
    return d.get("ISBN:" + isbn, {}) if d else {}


# A negative entry ({}, "Open Library was asked and doesn't hold it") is retried after this many
# days (by mtime) -- Open Library's holdings grow, so a book missing today may be added later.
# <= 0 disables the retry: negatives are permanent, the original per-ISBN-cache behaviour. Cost:
# at most ceil(current negative count / batch) extra LIVE requests, once per window, forever --
# a recurring cost, unlike a positive entry's one-time ceil(new/50).
OL_NEG_REFRESH_DAYS = 60


def ol_needs_fetch(isbn):
    """True when there's no per-ISBN entry yet, or the entry is a negative older than
    OL_NEG_REFRESH_DAYS days (mtime). A positive entry is never stale. Used for both the live
    fetch loop and `plan` (so the plan dict reflects what a live run would actually request).
    Cost: once entries start aging past the window, at most ceil(negative count / batch) extra
    requests every OL_NEG_REFRESH_DAYS -- a recurring cost, not the one-time ceil(new/50)."""
    p = ol_isbn_path(isbn)
    if not os.path.exists(p):
        return True
    if OL_NEG_REFRESH_DAYS <= 0:
        return False
    with open(p, encoding="utf8") as f:
        d = json.load(f)
    if d:
        return False
    return (time.time() - os.path.getmtime(p)) / 86400 > OL_NEG_REFRESH_DAYS


def _put(isbn, rec, refresh=False):
    """Write the per-ISBN entry. Default: never overwrites an existing file (ol_adopt's offline
    derivation always uses this). `refresh=True` (only the live fetch loop, on an ISBN
    `ol_needs_fetch` already flagged) allows a STALE NEGATIVE to be re-answered: an upgrade to a
    positive record is written; a repeat negative just touches the file's mtime (no rewrite) so
    the next staleness check starts a fresh window. A positive entry is never overwritten either
    way."""
    p = ol_isbn_path(isbn)
    if os.path.exists(p):
        if not refresh:
            return False
        with open(p, encoding="utf8") as f:
            old = json.load(f)
        if old:                        # a positive entry is never overwritten
            return False
        if not rec:                    # still negative: just reset the staleness clock
            os.utime(p, None)
            return False
    tmp = p + ".part"
    with open(tmp, "w", encoding="utf8") as f:
        json.dump({"ISBN:" + isbn: rec} if rec else {}, f, ensure_ascii=False)
    os.replace(tmp, p)
    return True


_PREC_RANK = {"day": 3, "month": 2, "year": 1, None: 0}
_COVER_ID_RE = re.compile(r"/b/id/(-?\d+)-[SML]\.jpg")


def _cover_id(rec):
    """The Open Library cover's numeric id, read off any of its URLs, or None (no cover, or a
    non-positive id -- -1 means "no cover", per tier1/covers.py's ol_cover_ok)."""
    cov = (rec or {}).get("cover") or {}
    for size in ("large", "medium", "small"):
        u = cov.get(size)
        if u:
            m = _COVER_ID_RE.search(u)
            if m and int(m.group(1)) > 0:
                return int(m.group(1))
    return None


def _variant_rank(rec):
    """Ranks a candidate record for an ISBN when cached batches disagree, so the winner is the
    same on every machine regardless of glob/filesystem order: finest release-date precision,
    then page count present, then a positive cover id (the LOWEST id wins), then a canonical json
    dump as the final deterministic tiebreak."""
    _, prec = parse_ol_date(rec.get("publish_date"))
    cid = _cover_id(rec)
    return (_PREC_RANK.get(prec, 0), 1 if rec.get("number_of_pages") else 0,
            1 if cid else 0, -cid if cid else 0, json.dumps(rec, sort_keys=True))


def ol_adopt(legacy, batch=50):
    """Split cached legacy batches into per-ISBN entries -- offline, zero requests.
    Positive: every record of every cached Open Library batch response in .cache/*.json. When
    cached batches disagree about an ISBN (an older vs a newer Open Library snapshot), the best
    variant wins by `_variant_rank` -- NOT by glob/filesystem order, so the derived entry is the
    same regardless of directory listing order (Linux vs APFS, etc).
    Negative: the ISBNs a REBUILDABLE batch asked for and did not get -- the sorted 50-chunks of
    `legacy` (what the pre-round code requested); sha256 urls cannot be inverted, so no other
    batch can say what it asked for. Never overwrites an entry. -> (positive, negative) written."""
    import glob
    pos = neg = 0
    variants = {}
    for f in sorted(glob.glob(os.path.join(_V.CACHE, "*.json"))):
        try:
            with open(f, encoding="utf8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d and all(k.startswith("ISBN:") for k in list(d)[:3]):
            for k, rec in d.items():
                if rec:
                    variants.setdefault(k.split(":", 1)[1], []).append(rec)
    for isbn, recs in variants.items():
        pos += _put(isbn, max(recs, key=_variant_rank))
    legacy = sorted(set(legacy))
    for i in range(0, len(legacy), batch):
        chunk = legacy[i:i + batch]
        p = os.path.join(_V.CACHE, hashlib.sha256(ol_url(chunk).encode()).hexdigest()[:32] + ".json")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf8") as fh:
            d = json.load(fh)
        if not isinstance(d, dict) or "_error" in d or "_http_error" in d:
            continue
        for x in chunk:
            if "ISBN:" + x not in d:
                neg += _put(x, None)
    return pos, neg


def legacy_isbns(db, market):
    """The market's ISBNs as the pre-round code saw them: every volume ISBN, minus those stage 3f
    (tier0/build_krcn.py) introduced -- created volumes' and filled isbn13 values."""
    have = {r[0] for r in db.execute("""SELECT DISTINCT v.isbn13 FROM volume v JOIN release_line rl
        ON rl.id=v.release_line_id WHERE rl.market=? AND v.isbn13 IS NOT NULL""", (market,))}
    try:
        new = {r[0] for r in db.execute("""SELECT isbn13 FROM krcn_member WHERE isbn13 IS NOT NULL
                                           AND (fate='created' OR filled LIKE '%isbn13%')""")}
    except sqlite3.OperationalError:
        new = set()
    return sorted(have - new)


def enrich_openlibrary(db, batch=50, limit=None, market="EN", plan=False):
    """Claims release_date/page_count for `market`'s undated volumes from their per-ISBN entries
    (`ol_entry`), deriving new ones offline first (`ol_adopt` -- writes into .cache/, zero
    network) and then live-fetching only what's still missing (`ol_needs_fetch`). `plan=True`
    makes NO live request at all (still runs `ol_adopt`, which is offline) and returns
    {isbns, have, missing, requests} instead of writing claims -- the CLI's `plan` mode prints
    this for EN and FR (`python3 tier1/enrich_more.py <db> plan`)."""
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
    ol_adopt(legacy_isbns(db, market), batch)
    missing = [x for x in isbns if ol_needs_fetch(x)]
    if plan:
        return {"isbns": len(isbns), "have": len(isbns) - len(missing), "missing": len(missing),
                "requests": -(-len(missing) // batch)}
    print(f"  Open Library[{market}]: {len(isbns):,} distinct ISBNs, {len(missing):,} without a "
          f"current per-ISBN entry -> {-(-len(missing) // batch)} batch request(s)", flush=True)
    for i in range(0, len(missing), batch):
        chunk = missing[i:i + batch]
        # a chunk containing a stale negative may hash to an already-cached url (most sharply for
        # a size-1 chunk, whose url IS that ISBN's own per-ISBN key) -- fresh=True forces a live
        # attempt instead of silently re-serving the stale answer and never checking again
        stale = any(os.path.exists(ol_isbn_path(x)) for x in chunk)
        d = _fetch(ol_url(chunk), interval=0.6, fresh=stale)
        if not isinstance(d, dict) or "_error" in d or "_http_error" in d:
            continue                       # a failed fetch writes nothing -- not even negatives
        for x in chunk:
            _put(x, d.get("ISBN:" + x), refresh=True)   # refresh: x may be a stale negative
    hit = ins = 0
    for isbn in isbns:
        rec = ol_entry(isbn)
        if not rec:
            continue
        hit += 1
        iso, prec = parse_ol_date(rec.get("publish_date"), market)
        for vid in by[isbn]:
            if iso:
                _claim(db, vid, "release_date", iso, "openlibrary", f"https://openlibrary.org/isbn/{isbn}")
                ins += 1
            if rec.get("number_of_pages"):
                _claim(db, vid, "page_count", str(rec["number_of_pages"]), "openlibrary",
                       f"https://openlibrary.org/isbn/{isbn}")
    db.commit()
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
    except Exception:
        return None
    # whole or not at all (a truncated XML would parse to fewer records next run, silently); a write
    # error is not a network error: it propagates
    tmp = key + ".part"
    with open(tmp, "w", encoding="utf8") as f:
        f.write(t)
    os.replace(tmp, key)
    return t


if __name__ == "__main__":
    # `plan` (below) and every live `ol`/`both`/`olfr` run first call ol_adopt (via
    # enrich_openlibrary), which WRITES newly-derived per-ISBN entries into .cache/ from cached
    # batch responses already on disk -- zero network either way; `plan` never fetches live.
    p = sys.argv[1] if len(sys.argv) > 1 else _build("opentome.db")
    which = sys.argv[2] if len(sys.argv) > 2 else "ol"
    lim = int(sys.argv[3]) if len(sys.argv) > 3 else None
    db = sqlite3.connect(p)
    if which == "plan":
        for m in ("EN", "FR"):
            print("Open Library plan %s:" % m, enrich_openlibrary(db, market=m, plan=True))
        raise SystemExit(0)
    if which in ("ol", "both"):
        print("openlibrary:", enrich_openlibrary(db, limit=lim, market="EN"))
    if which in ("olfr", "both"):
        print("openlibrary FR:", enrich_openlibrary(db, limit=lim, market="FR"))
    if which in ("bnf", "both"):
        print("bnf:", enrich_bnf(db, limit=lim))
