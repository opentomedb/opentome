"""Resolve competing claims into one value per field, with a confidence.

This is the feature that distinguishes the catalogue from a scrape. A consumer
(Mangarr, Kavita) must be able to auto-accept above a threshold and queue the
rest -- which is the direct fix for the silent-wrong-match class of bug.

The calibration rule is EMPIRICAL, from tier-1 cross-verification (docs/):
49 of 50 cross-source date disagreements were exact multiples of 7 days, 45 in
the same direction. Those are two sources answering different questions
(publication date vs retail on-sale date), not one being wrong. A magnitude
bound is required though: two different *editions* both shipping on a Tuesday
also differ by a multiple of 7, so large week-multiples mean wrong edition or
wrong release line, not date semantics.
"""
import re, sqlite3, sys
from datetime import date

import os


def _build(name):
    """Default build-output path. Never /tmp: macOS cleaned it and destroyed a
    fully-built catalogue. Outputs belong beside the cache, inside the repo."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(root, "build")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


# who to believe when sources genuinely conflict
PRECEDENCE = ["override", "publisher", "dnb", "bnf", "openbd", "wikipedia", "gbooks"]
RANK = {s: i for i, s in enumerate(PRECEDENCE)}

SEMANTIC_MAX_DAYS = 42          # 6 weeks; beyond this a week-multiple is an edition gap
MINOR_MAX_DAYS    = 7           # sub-week disagreement: near-agreement we cannot explain


def _d(s):
    try:
        y, m, dd = (int(x) for x in s.split("-")[:3])
        return date(y, m, dd)
    except Exception:
        return None


def _compatible(values):
    """Do these dates agree at the coarsest precision present?

    openBD returns year-month ('2010-03'); Wikipedia returns day
    ('2010-03-17'). Those AGREE -- one is simply less precise. Treating them
    as a conflict would manufacture disagreement out of precision.
    """
    prefixes = {len(v) for v in values}
    n = min(prefixes)
    return len({v[:n] for v in values}) == 1


def classify_dates(values):
    """-> (basis, confidence) for a set of differing date strings."""
    if _compatible(values):
        return "agreed_coarse", 0.90
    ds = [x for x in (_d(v) for v in values) if x]
    if len(ds) < 2:
        return "single_source", 0.70
    offs = {abs((a - b).days) for a in ds for b in ds if a != b}
    if not offs:
        return "agreed", 0.97
    week = all(o % 7 == 0 for o in offs)
    big = max(offs)
    if week and big <= SEMANTIC_MAX_DAYS:
        # different milestone (publication vs on-sale) -- both are right
        return "semantic_variance", 0.88
    if week:
        # week-aligned but far apart: different edition / wrong release line
        return "escalated", 0.40
    if big <= MINOR_MAX_DAYS:
        # Sub-week gap that is NOT a week multiple. The week-multiple rule
        # encodes US Tuesday street dates; markets without that weekly grid
        # (France notably) produce 1-6 day gaps instead -- 46% of all French
        # conflicts. Calling those "conflict" blames the data for the rule not
        # fitting; calling them "semantic_variance" claims an explanation we do
        # not have. They are near-agreement of unknown cause, and get their own
        # honest label and a middling confidence.
        return "minor_variance", 0.65
    return "conflict", 0.30


def resolve(db, verbose=False):
    c = db.cursor()
    c.execute("DELETE FROM resolution")
    rows = c.execute("""SELECT entity, entity_id, field, value, source
                        FROM claim ORDER BY entity, entity_id, field""").fetchall()
    groups = {}
    for e, eid, f, v, s in rows:
        groups.setdefault((e, eid, f), []).append((v, s))

    # manual overrides trump everything
    ov = {(e, eid, f): v for e, eid, f, v in
          c.execute("SELECT entity, entity_id, field, value FROM override")}

    out, stats = [], {}
    for (e, eid, f), claims in groups.items():
        if (e, eid, f) in ov:
            out.append((e, eid, f, ov[(e, eid, f)], 1.0, "manual_override", 1, 1, None))
            stats["manual_override"] = stats.get("manual_override", 0) + 1
            continue
        vals = {v for v, _ in claims}
        best = min(claims, key=lambda vs: RANK.get(vs[1], 99))
        n_src = len({s for _, s in claims})
        if len(vals) == 1:
            basis, conf = ("agreed", 0.97) if n_src > 1 else ("single_source", 0.70)
            n_agree = len(claims)
            note = None
        elif f.endswith("date") or f == "release_date":
            basis, conf = classify_dates(vals)
            if basis == "agreed_coarse":
                # The sources AGREE; one is merely less precise. Publish the
                # most precise value, not the highest-ranked source's coarse
                # one: precedence used to hand out openBD's '2023-02' over a
                # corroborated '2023-02-25' on 42,985 fields.
                best = max(claims, key=lambda vs: (len(vs[0]), -RANK.get(vs[1], 99)))
            elif best[1] == "dnb" and len(best[0]) == 4 and any(len(v) > 4 for v, _ in claims):
                # DNB's bare 008 year disagrees with a finer date exactly where it is least
                # reliable: a late-December release catalogued under the next year. DNB ranks
                # high for what it is (the legal-deposit record), not for its precision -- the
                # finer claim wins (docs/dnb-design.md). DNB only: generalised to every
                # bare year it moved 6 Wikipedia years to Open Library dates two years off.
                best = min((vs for vs in claims if len(vs[0]) > 4), key=lambda vs: RANK.get(vs[1], 99))
            n_agree = sum(1 for v, _ in claims if v == best[0])
            note = " | ".join(f"{s}={v}" for v, s in
                              sorted(claims, key=lambda x: RANK.get(x[1], 99)))
        else:
            basis, conf = "conflict", 0.50
            n_agree = sum(1 for v, _ in claims if v == best[0])
            note = " | ".join(f"{s}={v}" for v, s in claims)
        out.append((e, eid, f, best[0], conf, basis, n_agree, n_src, note))
        stats[basis] = stats.get(basis, 0) + 1

    c.executemany("""INSERT OR REPLACE INTO resolution
        (entity,entity_id,field,value,confidence,basis,n_agree,n_sources,notes)
        VALUES(?,?,?,?,?,?,?,?,?)""", out)
    db.commit()
    return stats


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else _build("opentome.db")
    db = sqlite3.connect(p)
    st = resolve(db)
    tot = sum(st.values())
    print(f"resolved {tot:,} fields from claims\n")
    for basis, n in sorted(st.items(), key=lambda kv: -kv[1]):
        print(f"   {basis:<20} {n:>7,}  ({n/tot*100:5.1f}%)")
    hi = db.execute("SELECT COUNT(*) FROM resolution WHERE confidence>=0.85").fetchone()[0]
    lo = db.execute("SELECT COUNT(*) FROM resolution WHERE confidence<0.5").fetchone()[0]
    print(f"\n   auto-acceptable (>=0.85): {hi:,} ({hi/tot*100:.1f}%)")
    print(f"   needs review     (<0.50): {lo:,} ({lo/tot*100:.1f}%)")
