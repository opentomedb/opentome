"""Collapse licensed-market rows that describe ONE physical omnibus volume.

English 2-in-1 and 3-in-1 editions are represented on Wikipedia by repeating
the licensed ISBN and date on consecutive Japanese rows -- Vinland Saga's
table lists 29 Japanese tankōbon and puts Kodansha's hardcover volume 1
(978-1-61262-420-4, 2013-10-13) on rows 1 AND 2. Emitting one English volume
per row therefore produced 29 English volumes where 15 exist, with volume 2
carrying volume 1's ISBN and date, and fifteen phantom "missing" volumes for a
consumer to search for forever.

Rule (measured on the corpus, docs/cleanup-v2.md):
  within one release line, a run of CONSECUTIVE integer-numbered rows whose
  licensed ISBN is identical and whose licensed dates are identical or absent
  is one licensed volume. The run's first row keeps the entry and records the
  Japanese numbers it contains as a `contains` list -- the volume composition
  the schema was designed for. Licensed numbering is then sequential within
  the line, because a publisher numbers its own units, not the originals.

Guards, each answering a real false positive found in the data:
  * only the licensed role is ever collapsed -- Japanese rows sharing an ISBN
    are zero-padding duplicates ('01' vs '1', now canonicalised upstream) or
    ISBN mis-attributions, never omnibus editions;
  * dates must agree (or be absent) -- 242 JP-side runs with different dates
    are attribution errors, not composition;
  * numbers must be consecutive integers -- a label row ('9 RE:', 'SP')
    never joins a run;
  * a line with no run at all is left exactly as it was.
"""


ROLES = ("licensed", "original")


def _lic(rec, role="licensed"):
    m = (rec.get("markets") or {}).get(role)
    # the original slot is collapsible only when it is NOT Japanese: a Korean or
    # US original listed there behaves like a licensed edition, whereas Japanese
    # rows sharing an ISBN are zero-padding duplicates or mis-attributions
    if role == "original" and (m or {}).get("market", "JP") == "JP":
        return None
    return m


def _key(m):
    return m.get("isbn13"), m.get("date")


def collapse_licensed(records):
    """records: output of release_lines.split() for ONE article. Returns a new
    list with licensed entries collapsed per (medium, line)."""
    groups = {}
    for i, r in enumerate(records):
        groups.setdefault((r.get("medium"), r.get("line")), []).append(i)

    out = [dict(r, markets={k: dict(v) for k, v in (r.get("markets") or {}).items()})
           for r in records]

    for _, idxs in groups.items():
        idxs.sort(key=lambda i: records[i].get("_offset", i))
        for role in ROLES:
            _collapse_role(out, idxs, role)
    return out


def _collapse_role(out, idxs, role):
    runs, cur = [], []
    for i in idxs:
        m = _lic(out[i], role)
        r = out[i]
        is_int = not r.get("special") and str(r.get("volume", "")).isdigit()
        if not (m and m.get("isbn13") and is_int):
            if len(cur) > 1:
                runs.append(cur)
            cur = []
            continue
        if cur:
            prev = out[cur[-1]]
            pm = _lic(prev, role)
            same_isbn = pm.get("isbn13") == m.get("isbn13")
            dates = {pm.get("date"), m.get("date")} - {None}
            consecutive = int(r["volume"]) == int(prev["volume"]) + 1
            if same_isbn and len(dates) <= 1 and consecutive:
                cur.append(i)
                continue
            if len(cur) > 1:
                runs.append(cur)
        cur = [i]
    if len(cur) > 1:
        runs.append(cur)
    if not runs:
        return

    # collapse: first row of each run keeps the entry + composition
    for run in runs:
        first = out[run[0]]
        m = _lic(first, role)
        m["contains"] = [int(out[i]["volume"]) for i in run]
        # a date on a later row of the run is the same volume's date
        if not m.get("date"):
            for i in run[1:]:
                if _lic(out[i], role).get("date"):
                    m["date"] = _lic(out[i], role)["date"]
                    m["date_precision"] = _lic(out[i], role).get("date_precision")
                    break
        for i in run[1:]:
            del out[i]["markets"][role]

    # renumber the line's integer volumes for this role sequentially. Every row
    # of a renumbered line records the original it maps to -- the single volume
    # after a run of 2-in-1s (Erased's English 5 = Japanese 9) is part of the
    # cross-market mapping too, and without it "reached the last original
    # volume" falls one short on every such line.
    n = 0
    for i in idxs:
        m = _lic(out[i], role)
        r = out[i]
        if m and not r.get("special") and str(r.get("volume", "")).isdigit():
            n += 1
            m["number"] = str(n)
            m.setdefault("contains", [int(r["volume"])])
