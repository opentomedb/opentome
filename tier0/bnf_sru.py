"""BnF publisher channels for French manhwa / manhua (docs/krcn-design.md §3, §4). SRU 1.2,
unimarcxchange, 500 records per request (330 records came back in one 1.9 MB response in the spike).

The channels are an ALLOWLIST: adding an imprint is one line here plus a count probe -- not a
recurring manual step. `bib.subject all "manhwa"` alone is contaminated (Japanese manga), so the
subject only narrows a publisher; tier0/krcn_lines.py keeps only records with 101 $c kor / chi.

    python3 tier0/bnf_sru.py         # fetch (cached; BNF_MAX_REQUESTS caps live requests) and print
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lib_sru as SRU
import bnf_unimarc as U

BNF = SRU.Source("bnf", "https://catalogue.bnf.fr/api/SRU", "1.2", "unimarcxchange", 500,
                 "BnF bibliographic data, Licence Ouverte / Etalab", budget=60)
CHANNELS = (
    ("tokebi", 'bib.publisher all "Tokebi"'),
    ("kbooks", 'bib.publisher all "Kbooks"'),
    ("saphira", 'bib.publisher all "Saphira"'),
    ("samji", 'bib.publisher all "Samji"'),
    ("clair-de-lune", 'bib.publisher all "Clair de lune" and bib.subject all "manhwa"'),
    ("kotoon", 'bib.publisher all "Kotoon"'),
    ("ki-oon", 'bib.publisher all "Ki-oon" and bib.subject all "manhwa"'),
    ("pika", 'bib.publisher all "Pika" and bib.subject all "manhwa"'),
)


def enumerate_bnf(verbose=True):
    """-> ({ark or 001: record}, tally). Every channel whole (lib_sru.Source.search), refreshed when
    older than BNF_REFRESH_DAYS."""
    recs, tally = {}, {}
    for name, q in CHANNELS:
        n, pages = BNF.search(q, refresh=True)
        got = {}
        for t in pages:
            for r in U.records(t):
                got[U.ark(r) or r["cf"]["001"]] = r
        tally[name] = n
        if verbose:
            print("    bnf %-14s %5d  (live requests so far %d)" % (name, n, BNF.live), flush=True)
        for k, r in got.items():
            recs.setdefault(k, r)
    tally.update(distinct=len(recs), live_requests=BNF.live, degraded=BNF.degraded,
                 degraded_queries=list(BNF.degraded_queries))
    return recs, tally


if __name__ == "__main__":
    recs, tally = enumerate_bnf()
    print("BnF enumeration:", json.dumps(tally))
