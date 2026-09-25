"""Enumerate the DNB records OpenTome ingests, through three channels (docs/dnb-design.md):

  1. `spo=jpn and bbg=A*`   print books whose 041$h original language is Japanese
                            (22,101 of them carry DDC 741.5 in the spike's count)
  2. manga imprints         `(vlg=TOKYOPOP or ...) and bbg=A* not spo=jpn` -- records the
                            spo index misses; build_dnb.py keeps only Japanese-origin ones
  3. parents                every 773$w set record not already seen, by `idn=` OR-batches

Channels 1 and 2 are sliced by publication year (`jhr`), so a result set is stable while
it is paged. Slices that can still change take part in the opt-in freshness window
(DNB_REFRESH_DAYS, tier0/dnb_sru.py): last year (legal deposit lags a median 120 days,
p90 293), the current year and later, the no-year remainder, and the parent batches.

Completeness is checked, not assumed, and the first full run (2026-09-24) showed why:
`jhr` is MULTI-valued (a record can carry several years: 25,933 slice hits for 25,270
records) and some records have none at all (7 in channel 1, 304 in channel 2). So each
channel also pages a `not jhr>0` remainder, and the DISTINCT records paged must equal the
unsliced numberOfRecords; every slice must yield as many distinct records as it announced.
On a refresh run the total is refetched too; a gap there means an older, frozen slice gained
a late record, and only the frozen slices whose count changed are re-paged.

    python3 tier0/dnb_enumerate.py            # fetch (cached) and print the tally
"""
import datetime, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dnb_sru as S
import dnb_marc as M

CURRENT_YEAR = datetime.date.today().year
PRINT_JPN = "spo=jpn and bbg=A*"
IMPRINTS = ("TOKYOPOP", "altraverse", '"Egmont Manga"', '"Carlsen Manga"', '"Panini Manga"',
            '"Planet Manga"')
IMPRINT_Q = "(%s) and bbg=A* not spo=jpn" % " or ".join("vlg=" + v for v in IMPRINTS)
IDN_BATCH = 30


def year_slices(fine_from, coarse):
    """(cql suffix, refresh) covering every year. Years before `fine_from` come in the
    given coarse buckets; from `fine_from` to CURRENT_YEAR+4 one slice per year; everything
    later in one open slice; then the records with no year. Last year and later refresh."""
    out = []
    lo = None
    for hi in coarse:                       # coarse: ascending bucket starts, last < fine_from
        if lo is None:
            out.append(("jhr<%d" % hi, False))
        else:
            out.append(("jhr>=%d and jhr<=%d" % (lo, hi - 1), False))
        lo = hi
    if lo is not None and lo < fine_from:
        out.append(("jhr>=%d and jhr<=%d" % (lo, fine_from - 1), False))
    elif lo is None:
        out.append(("jhr<%d" % fine_from, False))
    for y in range(fine_from, CURRENT_YEAR + 5):
        out.append(("jhr=%d" % y, y >= CURRENT_YEAR - 1))
    out.append(("jhr>%d" % (CURRENT_YEAR + 4), True))
    return [("and " + q, r) for q, r in out] + [("not jhr>0", True)]   # + records with no year


CHANNELS = [
    # name, base query, fine-grained from, coarse bucket starts before that
    ("print_jpn", PRINT_JPN, 1995, (1990,)),
    ("imprints", IMPRINT_Q, 2020, (2000, 2005, 2010, 2015)),
]


def _page(q, refresh=False, force=False):
    """A slice, whole: S.search() returns a complete page set (fresh, or the previous complete
    one when a refresh run degraded) or raises -- a slice is never partly there."""
    n, pages = S.search(q, refresh=refresh, force=force)
    seen = {}
    for text in pages:
        for r in M.records(text):
            seen[M.idn(r)] = r
    if len(seen) != n:
        raise RuntimeError("DNB slice %r announced %d records but paged %d distinct" % (q, n, len(seen)))
    return n, seen


def run_channel(name, base, fine_from, coarse, verbose=True):
    """-> ({idn: record}, gap, refreshed): gap = unsliced total - distinct records paged."""
    whole = S.total(base)
    live0 = S.live_requests[0]
    slices = [("%s %s" % (base, suffix), suffix, refresh) for suffix, refresh in year_slices(fine_from, coarse)]
    by_slice = {}
    for q, suffix, refresh in slices:
        n, by_slice[q] = _page(q, refresh=refresh)
        if verbose and n:
            print("    %-10s %-26s %6d  (live requests so far %d)" % (name, suffix, n, S.live_requests[0]), flush=True)
    # A refresh run re-reads the total too -- the cached one belongs to the older slices. If
    # it then disagrees, a FROZEN (older) slice gained a late record: re-count each frozen
    # slice (one small request each) and re-page only the ones that changed, so the cache is
    # consistent again for every later run. (A year rollover adds new slice URLs but moves no
    # record out of the union, so a plain run keeps the cached total and stays consistent.)
    refreshed = bool(S.REFRESH_DAYS) and S.live_requests[0] > live0
    got = {k: r for seen in by_slice.values() for k, r in seen.items()}
    if refreshed and not S.DEGRADED[0]:     # a degraded run recounts nothing: DNB is failing
        whole = S.total(base, force=True)
        if len(got) != whole:
            for q, suffix, refresh in slices:
                if not refresh and S.total(q, force=True) != len(by_slice[q]):
                    _, by_slice[q] = _page(q, force=True)
                    print("    %-10s %-26s re-paged (late records)" % (name, suffix), flush=True)
            got = {k: r for seen in by_slice.values() for k, r in seen.items()}
    if len(got) != whole:
        # Reported, not raised here, so one run still fetches every channel; build_dnb.py
        # fails the stage on a non-zero gap.
        print("    WARNING DNB channel %s: %d distinct records paged, the unsliced query has %d"
              % (name, len(got), whole), flush=True)
    return got, whole - len(got), refreshed


PARENT_INDEX = os.path.join(S.CACHE, "dnb-parents.json")


def fetch_parents(have, want, verbose=True):
    """The set records in `want` that are not in `have`. A parent is fetched ONCE: an index in
    the cache (.cache/dnb-parents.json, idn -> the batch query that returned it) keeps each
    batch's url stable, so a new parent costs one request for itself instead of shifting every
    later batch of a sorted list. Parents are not refreshed -- a set record's title and
    publisher do not change. The first run with the index adopts the batches already cached."""
    import json
    todo = sorted(set(want) - set(have))
    try:
        with open(PARENT_INDEX, encoding="utf8") as f:
            index = json.load(f)
    except (OSError, ValueError):
        index = {}
    cached = lambda q: os.path.exists(S.cache_path(S.url_for(q, 1)))
    # adopt the legacy sorted-chunk batches that are already in the cache
    for i in range(0, len(todo), IDN_BATCH):
        q = " or ".join("idn=" + x for x in todo[i:i + IDN_BATCH])
        if cached(q):
            for x in todo[i:i + IDN_BATCH]:
                index.setdefault(x, q)
    missing = [x for x in todo if x not in index or not cached(index[x])]
    for i in range(0, len(missing), IDN_BATCH):
        q = " or ".join("idn=" + x for x in missing[i:i + IDN_BATCH])
        try:
            S.search(q)
        except S.DnbIncomplete if S.REFRESH_DAYS else ():
            # a NEW parent batch in a refresh run DNB is failing: the parent's volumes still
            # cluster under its IDN, only its title is missing. The run is marked degraded, so
            # it is built and gated but never published.
            S.DEGRADED[0] = S.DEGRADED[0] or "parent batch unavailable"
            S.DEGRADED_QUERIES.append("parents: " + q[:60])
            continue
        for x in missing[i:i + IDN_BATCH]:
            index[x] = q
    got = {}
    for q in sorted({index[x] for x in todo if x in index}):
        try:
            n, pages = S.search(q)
        except (S.DnbIncomplete, S.DnbOfflineMiss) if S.REFRESH_DAYS else ():
            continue                     # the degraded parent batch above (or its offline re-read)
        for text in pages:
            for r in M.records(text):
                if M.idn(r) in want:
                    got[M.idn(r)] = r
    old = None
    try:
        with open(PARENT_INDEX, encoding="utf8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        pass
    if index != old:                      # written only when it changed (not a network response)
        os.makedirs(S.CACHE, exist_ok=True)
        tmp = PARENT_INDEX + ".part"
        with open(tmp, "w", encoding="utf8") as f:
            json.dump(index, f, sort_keys=True)
        os.replace(tmp, PARENT_INDEX)
    if verbose:
        print("    parents    %d wanted, %d found (%d not returned)" % (
            len(todo), len(got), len(set(todo) - set(got))), flush=True)
    return got


def enumerate_all(verbose=True):
    """-> ({idn: record} for channels 1+2, {idn: record} for fetched parents, tally)."""
    recs, tally = {}, {}
    for name, base, fine_from, coarse in CHANNELS:
        got, gap, refreshed = run_channel(name, base, fine_from, coarse, verbose)
        tally[name] = len(got)
        tally[name + "_slice_gap"] = gap
        for k, r in got.items():
            recs.setdefault(k, r)
    want = {p for r in recs.values() if not M.is_parent(r) for p in M.parent_idns(r)}
    parents = fetch_parents(recs, want, verbose)
    tally["parents_fetched"] = len(parents)
    tally["live_requests"] = S.live_requests[0]
    tally["degraded"] = S.DEGRADED[0]
    tally["degraded_queries"] = list(S.DEGRADED_QUERIES)
    return recs, parents, tally


if __name__ == "__main__":
    recs, parents, tally = enumerate_all()
    print("DNB enumeration:", tally)
