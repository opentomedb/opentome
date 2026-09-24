"""Enumerate the DNB records OpenTome ingests, through three channels (docs/dnb-design.md):

  1. `spo=jpn and bbg=A*`   print books whose 041$h original language is Japanese
                            (22,101 of them carry DDC 741.5 in the spike's count)
  2. manga imprints         `(vlg=TOKYOPOP or ...) and bbg=A* not spo=jpn` -- records the
                            spo index misses; build_dnb.py keeps only Japanese-origin ones
  3. parents                every 773$w set record not already seen, by `idn=` OR-batches

Channels 1 and 2 are sliced by publication year (`jhr`), so a result set is stable while
it is paged and a past-year slice never needs refetching; only slices that can still
change (the current year and later, the no-year remainder, and the parent batches) take
part in the opt-in freshness window (DNB_REFRESH_DAYS, tier0/dnb_sru.py).

Completeness is checked, not assumed, and the first full run (2026-09-24) showed why:
`jhr` is MULTI-valued (a record can carry several years: 25,933 slice hits for 25,270
records) and some records have none at all (7 in channel 1, 304 in channel 2). So each
channel also pages a `not jhr>0` remainder, and the DISTINCT records paged must equal the
unsliced numberOfRecords; every slice must yield as many distinct records as it announced.

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
    """(cql suffix, refresh) covering every year exactly once. Years before `fine_from`
    come in the given coarse buckets; from `fine_from` to CURRENT_YEAR+4 one slice per
    year; everything later in one open slice. Only slices reaching the current year or
    later refresh."""
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
        out.append(("jhr=%d" % y, y >= CURRENT_YEAR))
    out.append(("jhr>%d" % (CURRENT_YEAR + 4), True))
    return [("and " + q, r) for q, r in out] + [("not jhr>0", True)]   # + records with no year


CHANNELS = [
    # name, base query, fine-grained from, coarse bucket starts before that
    ("print_jpn", PRINT_JPN, 1995, (1990,)),
    ("imprints", IMPRINT_Q, 2020, (2000, 2005, 2010, 2015)),
]


def run_channel(name, base, fine_from, coarse, verbose=True):
    """-> ({idn: record}, gap): gap = unsliced total - distinct records paged (must be 0)."""
    whole = S.total(base)
    got = {}
    for suffix, refresh in year_slices(fine_from, coarse):
        q = "%s %s" % (base, suffix)
        n, pages = S.search(q, refresh=refresh)
        seen = {}
        for text in pages:
            for r in M.records(text):
                seen[M.idn(r)] = r
        if len(seen) != n:
            raise RuntimeError("DNB slice %r announced %d records but paged %d distinct" % (q, n, len(seen)))
        got.update(seen)
        if verbose and n:
            print("    %-10s %-26s %6d  (live requests so far %d)" % (name, suffix, n, S.live_requests[0]), flush=True)
    if len(got) != whole:
        # Reported, not raised here, so one run still fetches every channel; build_dnb.py
        # fails the stage on a non-zero gap.
        print("    WARNING DNB channel %s: %d distinct records paged, the unsliced query has %d"
              % (name, len(got), whole), flush=True)
    return got, whole - len(got)


def fetch_parents(have, want, verbose=True):
    """Fetch the set records in `want` that are not in `have`, 30 idns per request."""
    todo = sorted(set(want) - set(have))
    got = {}
    for i in range(0, len(todo), IDN_BATCH):
        chunk = todo[i:i + IDN_BATCH]
        n, pages = S.search(" or ".join("idn=" + x for x in chunk), refresh=True)
        for text in pages:
            for r in M.records(text):
                got[M.idn(r)] = r
    if verbose:
        print("    parents    %d wanted, %d fetched (%d not returned)" % (
            len(todo), len(got), len(set(todo) - set(got))), flush=True)
    return got


def enumerate_all(verbose=True):
    """-> ({idn: record} for channels 1+2, {idn: record} for fetched parents, tally)."""
    recs, tally = {}, {}
    for name, base, fine_from, coarse in CHANNELS:
        got, gap = run_channel(name, base, fine_from, coarse, verbose)
        tally[name] = len(got)
        tally[name + "_slice_gap"] = gap
        for k, r in got.items():
            recs.setdefault(k, r)
    want = {p for r in recs.values() if not M.is_parent(r) for p in M.parent_idns(r)}
    parents = fetch_parents(recs, want, verbose)
    tally["parents_fetched"] = len(parents)
    tally["live_requests"] = S.live_requests[0]
    return recs, parents, tally


if __name__ == "__main__":
    recs, parents, tally = enumerate_all()
    print("DNB enumeration:", tally)
