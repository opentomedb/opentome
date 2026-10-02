"""Round C merge candidates and verdicts (spec §3.2). Pure functions, no I/O."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from release_lines import _OPEN_END, _ROUND_A

_W2 = "^(?:" + _ROUND_A + ")$"


def _num(n):
    try:
        return int(n)
    except (TypeError, ValueError):
        return str(n)


def _norm(vols):
    return {_num(n): isbn for n, isbn in vols.items()}


def verdict(cand_vols, target_vols):
    """'extend' | 'duplicate' | 'kept' for a candidate line against its target line."""
    if not cand_vols:
        return "kept"
    c, t = _norm(cand_vols), _norm(target_vols)
    common = set(c) & set(t)
    if not common and t:
        cn, tn = list(c), list(t)
        if all(isinstance(x, int) for x in cn + tn) and min(cn) > max(tn):
            return "extend"
    if not common:
        return "kept"
    if all(n in t and (c[n] is None or c[n] == t[n]) for n in c):
        return "duplicate"
    return "kept"


def candidates(lines):
    """[(cand_id, target_id, kind)] sorted; kind 'T' (open-end tail) or 'W2' (round-A word)."""
    by_name = {}
    for l in lines:
        by_name.setdefault((l["work_id"], l["market"], l["medium"], l["name"]), l["id"])
    out = []
    for l in lines:
        name = l["name"]
        if l.get("arc_split") or not name.endswith(")") or " (" not in name:
            continue
        target, q = name[:-1].rsplit(" (", 1)
        if target != l["work_title"]:
            continue
        if re.match(_OPEN_END, q, re.I):
            kind = "T"
        elif re.match(_W2, q, re.I):
            kind = "W2"
        else:
            continue
        tid = by_name.get((l["work_id"], l["market"], l["medium"], target))
        if tid is not None and tid != l["id"]:
            out.append((l["id"], tid, kind))
    return sorted(out)
