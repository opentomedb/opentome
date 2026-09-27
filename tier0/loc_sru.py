"""The Library of Congress SRU client (docs/krcn-design.md §3, §4; R7). http://lx2.loc.gov:210/lcdb,
SRU 1.1, marcxml; no key, no documented limit -- serial at >= 3 s (tier0/lib_sru.py).

Diagnostic 61, "First record position out of range", arrives as HTTP 200. It is a FAILED PAGE,
never cached. The spike (137 requests) found it page-size dependent and partly transient -- at
startRecord=1 on sets of 63-137 records, three pages that failed 3 times at 100 worked at 50, two
failed pages later worked unchanged -- so every page goes through a ladder:

  1. the same page again: at most RETRIES attempts, RETRY_WAIT s apart;
  2. the same record range at the next smaller size (100 -> 50 -> 25), each sub-page laddered;
  3. slices of the query, each paged by this same ladder: an ISBN stem into its ten next-digit
     prefixes (97988554* -> 979885540* ... 979885549*); a subject channel by year plus a no-year
     remainder -- ONLY once the Task 8 probe confirmed the year index (YEAR_INDEX, NO_YEAR; plan
     ruling P11). At most MAX_DEPTH levels of slices.
Completeness: a slice is complete when its distinct records equal its count; a sliced set when the
UNION of its slices equals the set's count (a set record matches every prefix its volume ISBNs
fall under). Cached whole or not at all (lib_sru's manifest). Exhausted with a previous complete
set: that set, meta 'loc:degraded', no publish. Exhausted with none: the stage fails.

Each run first sends the canary (bath.isbn=9781975319434, the Solo Leveling set record): exactly
one record, 040 $a DLC -- else the stage fails. LOC_OFFLINE=1 reads it from the cache (P12).

    python3 tier0/loc_sru.py            # fetch every channel (cached), write build/loc-report.json
    python3 tier0/loc_sru.py --probe    # the one-off year-index probe (<= 10 live requests)
"""
import datetime, json, os, re, sys, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lib_sru as SRU
import dnb_marc as M
import loc_marc as LM

LOC = SRU.Source("loc", "http://lx2.loc.gov:210/lcdb", "1.1", "marcxml", 100,
                 "US government work, LoC-created records only", budget=400)
SIZES = (100, 50, 25)
RETRIES = 3
RETRY_WAIT = 10
LADDERED = ("61", "short")         # diagnostic 61 and a short page go down the ladder; others raise
MAX_DEPTH = 2
CANARY = "bath.isbn=9781975319434"
# Set by the Task 8 probe (Step 5); None = subject channels cannot be sliced (rung 3 unavailable).
YEAR_INDEX = None
NO_YEAR = None                     # e.g. '%s not dc.date>0' once probed

# §4: registrant stems of the ISBNs already on the carry's EN KR/CN lines (counts measured 2026-09-27)
STEMS = ("97984009", "97988554", "9781975", "97807595", "978159816", "978159182", "978159532",
         "978199025", "978168579", "978163858", "979888843", "979889160", "9781998854", "9781990778")
SUBJECTS = ('dc.subject="Comic books, strips, etc.--Korea"', 'dc.subject="Comic books, strips, etc.--China"',
            'dc.subject="Comic books, strips, etc.--Taiwan"', 'dc.subject="webcomics"', 'dc.subject="manhwa"',
            'dc.subject="Graphic novels" and dc.subject="Korea"', 'dc.subject="Graphic novels" and dc.subject="China"',
            'dc.subject="Comics (Graphic works)" and dc.subject="Korea"', 'dc.subject="manhua"',
            'cql.anywhere="translated from the Korean"')
CHANNELS = [("isbn %s" % s, "bath.isbn=%s*" % s) for s in STEMS] + \
           [("subject %d" % i, q) for i, q in enumerate(SUBJECTS, 1)]
REPORT = os.path.join(SRU.ROOT, "build", "loc-report.json")


class LadderExhausted(RuntimeError):
    pass


class LocCanaryFailed(RuntimeError):
    pass


class LocIncomplete(RuntimeError):
    """Duplicate positions that repeated reads could not confirm: an incomplete set (degraded rule).
    Not a failed page, so never sliced."""


def _where(url):
    """'query' start N size M -- the ladder log (the netlog shows a diagnostic page as a plain 200)."""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return "%r start %s size %s" % (q["query"][0], q["startRecord"][0], q["maximumRecords"][0])


def _retry61(fn):
    for attempt in range(RETRIES):
        try:
            return fn()
        except SRU.SourceDiagnostic as e:
            if e.code not in LADDERED:
                raise
            print("    loc diagnostic %s (attempt %d/%d): %s" % (e.code, attempt + 1, RETRIES, _where(e.url)), flush=True)
            if attempt == RETRIES - 1:
                raise
            LOC.sleep(RETRY_WAIT)


def _count(query):
    """numberOfRecords from a fresh maximumRecords=1 probe (the spike's 40 probes never drew 61)."""
    return SRU.count(_retry61(lambda: LOC.get(LOC.url_for(query, 1, 1), force=True)))


def _fetch_page(u, start, size, last):
    """One live page; a page holding fewer records than its range is a failed page ('short'),
    laddered like diagnostic 61 (live 2026-09-27: 97988554* paged 542 distinct of 562)."""
    text = LOC.fetch(u)
    got, want = len(SRU.ID_001.findall(text)), min(size, last - start + 1)
    print("    loc page %s: %d records (numberOfRecords %d)" % (_where(u), got, SRU.count(text)), flush=True)
    if got < want:
        raise SRU.SourceDiagnostic("short", "%d records, the range holds %d" % (got, want), u)
    return text


def _page(query, start, size, last):
    """Records start .. min(start + size - 1, last), through rungs 1 and 2 -> [(url, text)]."""
    u = LOC.url_for(query, start, size)
    try:
        return [(u, _retry61(lambda: _fetch_page(u, start, size, last)))]
    except SRU.SourceDiagnostic as e:
        if e.code not in LADDERED:
            raise
    smaller = [s for s in SIZES if s < size]
    if not smaller:
        raise LadderExhausted("%r records %d-%d: diagnostic 61 / short page at every page size"
                              % (query, start, min(start + size - 1, last)))
    print("    loc ladder: %r records %d-%d re-paged at %d" % (query, start, min(start + size - 1, last), smaller[0]),
          flush=True)
    out = []
    for s in range(start, min(start + size, last + 1), smaller[0]):
        out += _page(query, s, smaller[0], last)
    return out


# Duplicate positions -- controller ruling 2026-09-27 (amends spec §3 / R7 for LoC). The gateway
# can return one record at two positions of a result set (live: a single 36-record response of
# bath.isbn=9798855419* held one 001 twice), so "distinct == numberOfRecords" cannot hold. A LoC
# set or slice is COMPLETE when (a) every position 1..n was delivered (full pages, no failed page;
# a failed page goes down the ladder, and only a failed page ever leads to ISBN-prefix slices) and
# (b) when distinct < n, a second full read at the next page size (50) finds no record the first
# read lacked -- duplicates did not mask a missing record. If it does, the reads are unioned and a
# third full read (25) must add nothing; if it still grows, the set is incomplete (LocIncomplete ->
# the degraded rule). Verified sets are accepted through lib_sru's per-source hook (LOC.accept);
# the generic distinct == n rule stays for BnF / DNB.
VERIFIED = {}                      # query -> distinct records of a verified set with duplicates


def _dups_path():
    return os.path.join(LOC.cache, "loc-dups.json")


def _dups():
    try:
        with open(_dups_path(), encoding="utf8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _note_dups(query, entry):
    """Record (entry) or clear (None) a set's duplicate positions for build/loc-report.json."""
    d = _dups()
    if entry is None and query not in d:
        return
    if entry is None:
        d.pop(query)
    else:
        d[query] = entry
    os.makedirs(LOC.cache, exist_ok=True)
    SRU._store(_dups_path(), json.dumps(d, sort_keys=True, indent=0))


def _read(query, n, size):
    """One full read of the set at this page size (each page through rungs 1 and 2)."""
    staged = []
    for start in range(1, n + 1, size):
        staged += _page(query, start, size, n)
    return staged


def _ids(staged):
    return [i for _, t in staged for i in SRU.ID_001.findall(t)]


def _twice(ids):
    seen, out = set(), set()
    for i in ids:
        (out if i in seen else seen).add(i)
    return out


def _ladder(query):
    n = _count(query)
    staged = _read(query, n, SIZES[0])
    first = _ids(staged)
    seen, twice = set(first), _twice(first)
    VERIFIED.pop(query, None)
    if len(seen) == n:
        _note_dups(query, None)
        return n, staged
    if len(seen) > n:
        raise LocIncomplete("%r: %d distinct records, more than the %d announced" % (query, len(seen), n))
    reads = [(SIZES[0], len(seen), 0)]
    for size in SIZES[1:]:
        more = _read(query, n, size)
        ids = _ids(more)
        new = set(ids) - seen
        twice |= _twice(ids)
        staged += more
        reads.append((size, len(set(ids)), len(new)))
        print("    loc duplicates: %r announced %d; read at %d holds %d distinct, %d new" % (
            query, n, size, len(set(ids)), len(new)), flush=True)
        if not new:
            break
        if size == SIZES[-1]:
            raise LocIncomplete("%r: announced %d; reads at %s kept finding new records %s" % (
                query, n, "/".join(str(r[0]) for r in reads), [r[2] for r in reads]))
        seen |= new
        if len(seen) > n:
            raise LocIncomplete("%r: %d distinct records, more than the %d announced" % (query, len(seen), n))
    VERIFIED[query] = len(seen)
    _note_dups(query, {"n": n, "distinct": len(seen), "positions": n - len(seen),
                       "dup_ids": sorted(twice), "reads": reads})
    return n, staged


LOC.accept = lambda query, n, got: VERIFIED.get(query) == got


def slices(query):
    """Rung 3's narrower queries covering the same records ([] = cannot be sliced)."""
    m = re.fullmatch(r"bath\.isbn=(\d+)\*", query)
    if m:
        return ["bath.isbn=%s%d*" % (m.group(1), d) for d in range(10)]
    if not (YEAR_INDEX and NO_YEAR):
        return []
    y = datetime.date.today().year
    out = ["%s and %s<2000" % (query, YEAR_INDEX),
           "%s and %s>=2000 and %s<=2009" % (query, YEAR_INDEX, YEAR_INDEX)]
    out += ["%s and %s=%d" % (query, YEAR_INDEX, yr) for yr in range(2010, y + 2)]
    return out + ["%s and %s>%d" % (query, YEAR_INDEX, y + 1), NO_YEAR % query]


def pager(query, depth=0):
    """R7 for one result set -> (n, staged pages); raises LadderExhausted when even slicing fails."""
    try:
        return _ladder(query)
    except LadderExhausted as e:
        subs = slices(query) if depth < MAX_DEPTH else []
        if not subs:
            raise
        print("    loc ladder: %s -- slicing %r into %d queries (depth %d)" % (e, query, len(subs), depth + 1), flush=True)
    n = _count(query)
    staged, ids = [], set()
    for q in subs:
        if _count(q) == 0:
            continue
        sn, sp = pager(q, depth + 1)
        got = {i for _, t in sp for i in SRU.ID_001.findall(t)}
        if len(got) != VERIFIED.get(q, sn):
            raise LadderExhausted("slice %r announced %d, paged %d distinct" % (q, sn, len(got)))
        ids |= got
        staged += sp
    # The ten prefixes cover the stem by construction. With duplicate positions (ruling 2026-09-27)
    # the stem's count exceeds its distinct records, and the stem itself had a failed page, so it
    # cannot be re-read: fewer distinct than announced is accepted and reported; more is not.
    if len(ids) > n:
        raise LadderExhausted("%r: its slices hold %d distinct records, the set announces %d" % (query, len(ids), n))
    VERIFIED.pop(query, None)
    if len(ids) < n:
        VERIFIED[query] = len(ids)
        _note_dups(query, {"n": n, "distinct": len(ids), "positions": n - len(ids), "dup_ids": [],
                           "reads": "sliced: shortfall inferred from the complete slices"})
    else:
        _note_dups(query, None)
    return n, staged


def search_set(query):
    """A whole result set (refreshed when older than LOC_REFRESH_DAYS) -> (n, page texts)."""
    return LOC.search(query, refresh=True, pager=pager)


def canary():
    u = LOC.url_for(CANARY, 1, 1)
    try:
        text = _retry61(lambda: LOC.get(u, force=not LOC.offline))
    except SRU.SourceDiagnostic as e:
        raise LocCanaryFailed(str(e))
    recs = M.records(text)
    if SRU.count(text) != 1 or len(recs) != 1 or not LM.is_dlc(recs[0]):
        raise LocCanaryFailed("canary %s: expected exactly 1 DLC record, got numberOfRecords=%d, %d record(s)%s"
                              % (CANARY, SRU.count(text), len(recs),
                                 "" if not recs else ", 040 $a %r" % LM.f040a(recs[0])))


def enumerate_loc(verbose=True):
    """-> ({001: record}, report). Canary first, then every channel whole; build/loc-report.json holds
    the per-channel counts (§18: a new registrant stem shows up as a channel that stops growing)."""
    canary()
    recs, report = {}, {"channels": {}}
    for name, q in CHANNELS:
        n, pages = search_set(q)
        got = {}
        for t in pages:
            for r in M.records(t):
                got[r["cf"]["001"]] = r
        dlc = sum(1 for r in got.values() if LM.is_dlc(r))
        # duplicate positions (ruling 2026-09-27) of the channel's set and of its ISBN slices
        dups = {k: v for k, v in _dups().items()
                if k == q or (q.startswith("bath.isbn=") and k.startswith(q[:-1]) and k.endswith("*"))}
        report["channels"][name] = {"query": q, "records": n, "distinct": len(got), "dlc": dlc,
                                    "dlc_share": round(dlc / len(got), 3) if got else None,
                                    "duplicates": dups, "degraded": q in LOC.degraded_queries}
        if verbose:
            print("    loc %-14s %5d  distinct %5d  dlc %5d  (live requests so far %d)" % (
                name, n, len(got), dlc, LOC.live), flush=True)
        for k, r in got.items():
            recs.setdefault(k, r)
    report.update(distinct=len(recs), live_requests=LOC.live, degraded=LOC.degraded,
                  degraded_queries=list(LOC.degraded_queries))
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf8") as f:
        json.dump(report, f, indent=1, sort_keys=True)
    return recs, report


def probe(candidates=(("dc.date", "%s not dc.date>0"), ("bath.date", "%s not bath.date>0"), ("date", "%s not date>0"))):
    """Which year index slices a subject channel (<= 10 live requests): the channel's count, then
    per candidate the 2021 slice and the no-year remainder. A candidate that answers both without a
    diagnostic and gives 0 < count(2021) < total and count(2021) + remainder <= total is usable. The
    first usable one also gets the other relations slices() sends (<, >=, <=) -- a non-61 diagnostic
    there is not laddered, so an index that answers '=' but refuses '<' must not be set."""
    base = 'dc.subject="webcomics"'
    total = _count(base)
    print("  %s: %d" % (base, total))
    usable = []
    for idx, rest in candidates:
        try:
            y = _count("%s and %s=2021" % (base, idx))
            r = _count(rest % base)
        except SRU.SourceDiagnostic as e:
            print("  %-10s diagnostic %s (%s)" % (idx, e.code, e.message))
            continue
        ok = 0 < y < total and y + r <= total
        print("  %-10s 2021 slice %4d, no-year remainder %4d -> %s" % (idx, y, r, "usable" if ok else "NOT usable"))
        if ok:
            usable.append(idx)
    if usable:
        idx = usable[0]
        try:
            a = _count("%s and %s<2000" % (base, idx))
            b = _count("%s and %s>=2000 and %s<=2009" % (base, idx, idx))
            print("  %-10s <2000 slice %4d, 2000-2009 slice %4d -> range relations accepted" % (idx, a, b))
        except SRU.SourceDiagnostic as e:
            print("  %-10s range relations: diagnostic %s (%s) -> NOT usable" % (idx, e.code, e.message))


if __name__ == "__main__":
    if "--probe" in sys.argv:
        probe()
    else:
        recs, report = enumerate_loc()
        print("LoC enumeration: %d distinct, %d live requests, degraded=%s"
              % (report["distinct"], report["live_requests"], report["degraded"]))
