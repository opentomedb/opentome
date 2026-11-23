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
from datetime import date, timedelta

import os


def _build(name):
    """Default build-output path. Never /tmp: macOS cleaned it and destroyed a
    fully-built catalogue. Outputs belong beside the cache, inside the repo."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(root, "build")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


# who to believe when sources genuinely conflict
PRECEDENCE = ["override", "publisher", "dnb", "bnf", "loc", "openbd", "wikipedia", "gbooks"]
# the libraries whose bare year never beats a finer date it disagrees with (the date branch below)
LIBRARY_YEAR_SOURCES = ("dnb", "loc", "bnf")
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
        return "conflict", 0.50      # a day against a month or year that disagrees at the coarser precision
                                     # (labelled single_source until the corrections round: it never was one)
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


DATE_VALUE = re.compile(r"\d{4}(-\d{2}(-\d{2})?)?")


def dated_by_now(val, projected, today=None):
    """Is a resolved release_date value a real date by now (F6, 2026-10-01)? A well-formed YYYY[-MM[-DD]] that is on or
    before today at its own precision; a bare year counts when it is before this year, or this year and the
    volume's projected month (`projected`, 'YYYY-MM') is already past -- a current-year bare year says nothing
    about a month still to come. export/test_artifact.py PROJECTED_OUTRANKED mirrors this in SQL."""
    today = today or date.today().isoformat()
    if not val or not DATE_VALUE.fullmatch(val):
        return False
    if len(val) == 4:
        return val < today[:4] or (val == today[:4] and (projected or "") <= today[:7])
    return val <= today[:len(val)]


def apply_resolved_dates(db):
    """A projected date never outranks a real one (the KR/CN lift, 2026-10-01): a volume born with a planned month
    (release_date_type 'projected': an announced LoC / BnF / DNB record) that has a resolved release_date takes it,
    with its own precision, as 'published' -- but only a PLAUSIBLE one: on or before today at its own precision and
    within one year of the projected month's year (Open Library imports retailer pre-order dates, and a wrong
    edition's date must not become a published date; such a volume stays projected and the audit rule
    "projected volumes that also have a release_date claim" flags a past one). Reads `resolution`, so it is
    idempotent and can run again after stage 7b moves claim / resolution rows between volume ids
    (tier2/resolve.py --dates). -> volumes converted."""
    today, n = date.today().isoformat(), 0
    rows = db.execute("""SELECT r.entity_id, r.value, v.release_date FROM resolution r JOIN volume v ON v.id=r.entity_id
                         WHERE r.entity='volume' AND r.field='release_date' AND v.release_date_type='projected'
                           AND v.release_date IS NOT NULL""").fetchall()
    for vid, val, proj in rows:
        if not dated_by_now(val, proj, today) or abs(int(val[:4]) - int(proj[:4])) > 1:
            continue
        n += db.execute("""UPDATE volume SET release_date=?, release_date_precision=?, release_date_type='published'
                           WHERE id=? AND release_date_type='projected'""",
                        (val, {4: "year", 7: "month", 10: "day"}[len(val)], vid)).rowcount
    return n


# The corrections round (2026-11-23). Among claims of one source rank the value more claims carry wins (two
# articles against one), then the article the volume's own market reads best: measured on 1,702 Japanese volumes
# where the English and French articles disagreed and openBD held the month, the English article agreed with openBD
# 1,138 times, the French 563. A day date that no coarse month backs while a month claim of another source sits
# MONTH_GAP months or more away is the typo (Mr. Tonegawa vol 5: "June 6, 2016" against openBD's 2017-06), so the
# month wins; a day an adjacent month disagrees with keeps winning (a late-June release catalogued under July).
VIA_ORDER = {"en": 0, "ja": 1, "fr": 2, "de": 3, "": 4}
MONTH_GAP = 2


def _months(v):
    return int(v[:4]) * 12 + int(v[5:7])


def pick(claims):
    """The winning (value, source, via): source precedence, then the value more claims of that rank carry, then
    the article order, then the source name (deterministic)."""
    best_rank = min(RANK.get(s, 99) for _, s, _ in claims)
    top = [cl for cl in claims if RANK.get(cl[1], 99) == best_rank]
    count = {}
    for v, _, _ in top:
        count[v] = count.get(v, 0) + 1
    return min(top, key=lambda cl: (-count[cl[0]], VIA_ORDER.get(cl[2], 9), cl[1]))


def pick_date(claims):
    """-> (claim, rule): the day / month rules when both precisions are present from different sources --
    'month_backed' (the days disagree and a coarse month agrees with some: those win), 'coarse_outranks' (no day
    is backed and every coarse month is MONTH_GAP months or more away: the month wins), 'adjacent_month' (no day
    is backed but a month is next door: the day stands); rule None otherwise (the caller's rules)."""
    days = [cl for cl in claims if len(cl[0]) == 10]
    day_sources = {cl[1] for cl in days}
    months = [cl for cl in claims if len(cl[0]) == 7 and cl[1] not in day_sources]
    if days and months:
        backed = [d for d in days if any(d[0][:7] == m[0] for m in months)]
        if backed and len(backed) < len(days):
            return pick(backed), "month_backed"       # the days disagree; the month settles it
        if backed:
            return None, None                          # every day is backed: plain agreement (agreed_coarse)
        counts = {}
        for d in days:
            counts[d[0]] = counts.get(d[0], 0) + 1
        top = max(counts.values())
        if top >= 2:
            # two claims agree on the day: not a lone typo. The month is a reprint (Dragon Ball vol 1: three claims
            # on 1985-09-10 against openBD's 1992-11) or the colophon (Black Butler vol 1: two articles on
            # 2007-02-27 against 2007-03); falling through handed both to precedence, i.e. to openBD's month
            return pick([d for d in days if counts[d[0]] == top]), "day_majority"
        if min(abs(_months(d[0]) - _months(m[0])) for d in days for m in months) >= MONTH_GAP:
            return pick(months), "coarse_outranks"
        return pick(days), "adjacent_month"            # a late-June release catalogued under July: the day stands
    if len(days) >= 2 and not months:
        # two day dates of different sources a year or more apart, week-aligned: an edition and its reissue
        # (Given vol 1: the list's 2026-11-10 against Open Library's 2020-02-11); the first printing is the date
        vals = sorted({d[0] for d in days})
        if len(vals) > 1 and len({d[1] for d in days}) > 1:
            first, last = _d(vals[0]), _d(vals[-1])
            if first and last and (last - first).days >= 365 and (last - first).days % 7 == 0:
                return pick([d for d in days if d[0] == vals[0]]), "first_printing"
    return None, None


def write_back(db):
    """Resolution -> the volume row, for release_date (with its precision) and isbn13: the export reads the row.
    Until the corrections round the row kept the FIRST article's value and the claim the last's (schema/load.py).
    A projected volume is apply_resolved_dates's (a planned month holds until a plausible real date resolves);
    clean's rules travel with the value (a Jan-1 day is a bare year; a date past two years out is no date; an
    ISBN is 13 digits or nothing). -> (dates written, ISBNs written)."""
    cutoff = (date.today() + timedelta(days=730)).isoformat()
    nd = ni = 0
    for vid, val, cur, prec, typ in db.execute("""SELECT r.entity_id, r.value, v.release_date, v.release_date_precision,
                                                        v.release_date_type FROM resolution r JOIN volume v ON v.id=r.entity_id
                                                 WHERE r.entity='volume' AND r.field='release_date'""").fetchall():
        if typ == "projected" or not DATE_VALUE.fullmatch(val):
            continue
        if cur and len(cur) > len(val) and cur.startswith(val):
            continue        # the row is finer and not contradicted (a LoC month converted to published): it stands
        new, p = val, {4: "year", 7: "month", 10: "day"}[len(val)]
        if len(val) == 10 and val.endswith("-01-01"):
            new, p = val[:4], "year"
        if new > cutoff:
            new, p = None, None
        if (new, p) != (cur, prec):
            db.execute("UPDATE volume SET release_date=?, release_date_precision=? WHERE id=?", (new, p, vid))
            nd += 1
    for vid, val, cur in db.execute("""SELECT r.entity_id, r.value, v.isbn13 FROM resolution r JOIN volume v ON v.id=r.entity_id
                                       WHERE r.entity='volume' AND r.field='isbn13'""").fetchall():
        digits = re.sub(r"[- ]", "", val or "")
        if len(digits) != 13 or not digits.isdigit() or digits == cur:
            continue
        db.execute("UPDATE volume SET isbn13=? WHERE id=?", (digits, vid))
        ni += 1
    return nd, ni


def resolve(db, verbose=False):
    c = db.cursor()
    c.execute("DELETE FROM resolution")
    rows = c.execute("""SELECT entity, entity_id, field, value, source, via
                        FROM claim ORDER BY entity, entity_id, field""").fetchall()
    groups = {}
    for e, eid, f, v, s, via in rows:
        groups.setdefault((e, eid, f), []).append((v, s, via))

    # manual overrides trump everything
    ov = {(e, eid, f): v for e, eid, f, v in
          c.execute("SELECT entity, entity_id, field, value FROM override")}

    def label(cl):
        return cl[1] + ("@" + cl[2] if cl[2] else "")

    out, stats = [], {}
    for (e, eid, f), claims in groups.items():
        if (e, eid, f) in ov:
            out.append((e, eid, f, ov[(e, eid, f)], 1.0, "manual_override", 1, 1, None))
            stats["manual_override"] = stats.get("manual_override", 0) + 1
            continue
        vals = {v for v, _, _ in claims}
        best = pick(claims)
        n_src = len({(s, via) for _, s, via in claims})
        if len(vals) == 1:
            basis, conf = ("agreed", 0.97) if n_src > 1 else ("single_source", 0.70)
            n_agree = len(claims)
            note = None
        elif f.endswith("date") or f == "release_date":
            basis, conf = classify_dates(vals)
            ruled, rule = pick_date(claims)
            if rule:
                best = ruled
                basis, conf = rule, {"month_backed": 0.85, "coarse_outranks": 0.60, "adjacent_month": 0.55,
                                     "first_printing": 0.50, "day_majority": 0.80}[rule]
            elif basis == "agreed_coarse":
                # The sources AGREE; one is merely less precise. Publish the
                # most precise value, not the highest-ranked source's coarse
                # one: precedence used to hand out openBD's '2023-02' over a
                # corroborated '2023-02-25' on 42,985 fields.
                best = max(claims, key=lambda cl: (len(cl[0]), -RANK.get(cl[1], 99), -VIA_ORDER.get(cl[2], 9)))
            elif best[1] in LIBRARY_YEAR_SOURCES and len(best[0]) == 4 and any(len(v) > 4 for v, _, _ in claims):
                # DNB's bare 008 year disagrees with a finer date exactly where it is least
                # reliable: a late-December release catalogued under the next year. DNB ranks
                # high for what it is (the legal-deposit record), not for its precision -- the
                # finer claim wins (docs/dnb-design.md). DNB only: generalised to every
                # bare year it moved 6 Wikipedia years to Open Library dates two years off.
                # (krcn-design §12: LoC and BnF years follow the same rule; enrich_bnf writes no
                # dates, so no existing French resolution moves)
                best = pick([cl for cl in claims if len(cl[0]) > 4])
            n_agree = sum(1 for v, _, _ in claims if v == best[0])
            if rule is None and n_agree > 1 and basis in ("conflict", "escalated", "minor_variance") \
                    and n_agree > max(sum(1 for v, _, _ in claims if v == o) for o in vals if o != best[0]):
                basis, conf = "majority", 0.75      # two articles against one
            note = " | ".join(f"{label(cl)}={cl[0]}" for cl in
                              sorted(claims, key=lambda x: (RANK.get(x[1], 99), VIA_ORDER.get(x[2], 9))))
        else:
            n_agree = sum(1 for v, _, _ in claims if v == best[0])
            others = [sum(1 for v, _, _ in claims if v == o) for o in vals if o != best[0]]
            basis, conf = ("majority", 0.75) if n_agree > 1 and n_agree > max(others) else ("conflict", 0.50)
            note = " | ".join(f"{label(cl)}={cl[0]}" for cl in claims)
        out.append((e, eid, f, best[0], conf, basis, n_agree, n_src, note))
        stats[basis] = stats.get(basis, 0) + 1
    c.executemany("""INSERT OR REPLACE INTO resolution
        (entity,entity_id,field,value,confidence,basis,n_agree,n_sources,notes)
        VALUES(?,?,?,?,?,?,?,?,?)""", out)
    n = apply_resolved_dates(db)
    if n:
        print(f"  resolve: {n} projected volume date(s) replaced by a resolved real date")
    nd, ni = write_back(db)
    print(f"  resolve: {nd:,} volume date(s) and {ni:,} ISBN(s) written back from the resolution")
    db.commit()
    return stats


if __name__ == "__main__":
    p = next((a for a in sys.argv[1:] if not a.startswith("--")), _build("opentome.db"))
    db = sqlite3.connect(p)
    if "--dates" in sys.argv:       # after stage 7b's claim moves: convert again, resolve nothing
        print(f"  resolve --dates: {apply_resolved_dates(db)} projected volume date(s) replaced")
        print(f"  resolve --dates: {write_back(db)} (dates, ISBNs) written back")
        db.commit()
        sys.exit(0)
    st = resolve(db)
    tot = sum(st.values())
    print(f"resolved {tot:,} fields from claims\n")
    for basis, n in sorted(st.items(), key=lambda kv: -kv[1]):
        print(f"   {basis:<20} {n:>7,}  ({n/tot*100:5.1f}%)")
    hi = db.execute("SELECT COUNT(*) FROM resolution WHERE confidence>=0.85").fetchone()[0]
    lo = db.execute("SELECT COUNT(*) FROM resolution WHERE confidence<0.5").fetchone()[0]
    print(f"\n   auto-acceptable (>=0.85): {hi:,} ({hi/tot*100:.1f}%)")
    print(f"   needs review     (<0.50): {lo:,} ({lo/tot*100:.1f}%)")
