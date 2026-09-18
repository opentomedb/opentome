"""Integrity checks -- catch SILENT losses, the failure class that has bitten
this project twice (wrong-series binding, index-pairing drift).

Every check answers "did anything vanish or get mis-attributed without error?"
"""
import re, sys
from wikipedia_volumes import wikitext, _templates, parse_volumes, DIALECTS
import release_lines as RL


def check(page, work, lang="en"):
    w = wikitext(page, lang)
    if not w:
        return {"page": page, "error": "no wikitext"}
    tpl = DIALECTS[lang]["template"]
    allt = list(_templates(w, tpl))
    headers = [b for _, b in allt if "/" in b[:len(tpl) + 6]]
    rows = len(allt) - len(headers)
    recs = parse_volumes(w, page, lang)
    sp = RL.split(w, page, work, recs)

    issues = []
    # 1. every volume row must become a record
    if rows != len(recs):
        issues.append(f"LOSS: {rows} rows -> {len(recs)} records")
    # 2. every record must land in exactly one line
    if any(not r.get("line") for r in sp):
        issues.append("unattributed records")
    # 3. line volume counts must sum to the record count
    tot = sum(n for _, n in RL.summarise(sp))
    if tot != len(recs):
        issues.append(f"attribution sum {tot} != {len(recs)}")
    # 4. duplicate volume numbers WITHIN one line = a bad split
    from collections import Counter
    for (med, line), _ in RL.summarise(sp):
        nums = [r["volume"] for r in sp if (r["medium"], r["line"]) == (med, line)]
        dup = [v for v, c in Counter(nums).items() if c > 1]
        if dup:
            issues.append(f"dup vol {dup[:4]} in {line!r}")
    # 5. offsets must be strictly increasing (proves no reordering)
    offs = [r.get("_offset", -1) for r in recs]
    if offs != sorted(offs):
        issues.append("record order != document order")
    return {"page": page, "rows": rows, "records": len(recs),
            "lines": len(RL.summarise(sp)), "issues": issues}


if __name__ == "__main__":
    import json
    targets = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else []
    bad = 0
    print(f"{'work':<22}{'rows':>6}{'recs':>6}{'lines':>7}  issues")
    print("-" * 78)
    for work, page, lang in targets:
        r = check(page, work, lang)
        if r.get("error"):
            print(f"{work:<22}{'':>19}  {r['error']}"); bad += 1; continue
        flag = "; ".join(r["issues"]) if r["issues"] else "ok"
        if r["issues"]:
            bad += 1
        print(f"{work:<22}{r['rows']:>6}{r['records']:>6}{r['lines']:>7}  {flag}")
    print("-" * 78)
    print(f"{'':<22}{'':>19}  {bad} with issues / {len(targets)} checked")
