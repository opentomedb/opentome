"""Round C display names (spec 2026-10-02 §3.1): the name the artifact writes for a line.
Pure functions; the export applies them after every name-based decision (which keep the pipeline name)."""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tier0"))
from release_lines import _ROUND_A, HEADING_MEDIUM_HINTS  # noqa: E402

_KIND = (r"(?:novel series|light novel|novel|literary series|manga series|manga|webcomic|"
         r"(?:[A-Z][a-z]+ )?TV series|anime|film|video game|webtoon|manhwa|manhua|comics|franchise|"
         r"roman|bande dessin[ée]e|s[ée]rie t[ée]l[ée]vis[ée]e|s[ée]rie|jeu vid[ée]o)")
# optional leading year or one capitalised author/studio word; optional trailing ", <year>"
DISAMBIG = re.compile(r"\s+\((?:(?:1[89]|20)\d{2}\s+|[A-Z][\w'-]+\s+)?" + _KIND + r"(?:,\s*(?:1[89]|20)\d{2})?\)$", re.I)


def strip_work_disambiguator(name, work_title):
    """Rule D: only when the work title itself ends in a listed disambiguator and the line name starts
    with that exact work title; the disambiguator is removed from that prefix only."""
    if not name or not work_title:
        return name
    m = DISAMBIG.search(work_title)
    if not m or not name.startswith(work_title):
        return name
    return work_title[:m.start()] + name[len(work_title):]


_TRAIL = re.compile(r"^(?P<b>.+?)\s+\((?P<q>[^()]+)\)$")
_ROUND_A_RE = re.compile(r"^(?:" + _ROUND_A + r")$", re.I)
_SEP = (":", " ", "-", "–", "!", "?")


def self_named(name, base_title):
    """Rule S: "<B> (<R>)" -> R when R starts with B followed by a separator or nothing."""
    m = _TRAIL.match(name or "")
    if not m or m.group("b") != base_title:
        return name
    r, b = m.group("q").strip(), base_title.strip()
    if r.lower().startswith(b.lower()) and (len(r) == len(b) or r[len(b)] in _SEP):
        return r
    return name


def strip_round_a_word(name, medium):
    """Rule W/M: drop a trailing round-A class 1/2 word; a class-2 word retags a manga line."""
    m = _TRAIL.match(name or "")
    if not m or not _ROUND_A_RE.match(m.group("q").strip()):
        return name, medium, None
    word = m.group("q").strip()
    if medium == "manga":
        for target, pat in HEADING_MEDIUM_HINTS:
            if pat.match(word) and target != "manga":
                return m.group("b"), target, "M"
    return m.group("b"), medium, "W"


def display(name, work_title, medium):
    rules, out = [], name
    d = strip_work_disambiguator(out, work_title)
    if d != out:
        rules.append("D"); out = d
    base = DISAMBIG.sub("", work_title or "")
    s = self_named(out, base)
    if s != out:
        rules.append("S"); out = s
    w, medium2, rw = strip_round_a_word(out, medium)
    if rw:
        rules.append(rw); out = w
    return out, medium2, rules


# ---- guards (spec §3.1): a rename is held back when it would create a clash -------------------------
def _family(medium):
    return "comic" if medium in ("manga", "manhwa", "manhua") else medium


def _hold(l, held):
    return {"name": l["name"], "medium": l["medium"], "rules": [], "held": held}


def _changed(l, r):
    return (r["name"], r["medium"]) != (l["name"], l["medium"])


def _isbn_guard(lines, res, isbns):
    proposed = {t: r["medium"] for t, r in res.items()}  # snapshot: the result must not depend on input order
    held = []
    for l in lines:
        a = isbns.get(l["tome_id"]) or set()
        if "M" not in res[l["tome_id"]]["rules"] or not a:
            continue
        for o in lines:
            if o is l or (o["work_id"], o["market"]) != (l["work_id"], l["market"]):
                continue
            b = isbns.get(o["tome_id"]) or set()
            if (proposed[o["tome_id"]] == proposed[l["tome_id"]] and len(a & b) * 2 > len(a)) or \
               (o["medium"] == l["medium"] and a == b):
                held.append(l)
                break
    for l in held:
        res[l["tome_id"]] = _hold(l, "held-isbn")


def _within_work_guard(lines, res):
    groups = {}
    for l in lines:
        r = res[l["tome_id"]]
        groups.setdefault((l["work_id"], l["market"], r["medium"], r["name"].lower()), []).append(l)
    for g in groups.values():
        if len(g) > 1:
            for l in g:
                if _changed(l, res[l["tome_id"]]):
                    res[l["tome_id"]] = _hold(l, "held-clash")


def _cross_work_guard(lines, res, carry_pairs):
    works = {}
    for l in lines:
        r = res[l["tome_id"]]
        works.setdefault((l["market"], _family(r["medium"]), r["name"].lower()), set()).add(l["work_id"])
    for l in lines:
        r = res[l["tome_id"]]
        key = (l["market"], _family(r["medium"]), r["name"].lower())
        if "D" in r["rules"] and len(works[key]) > 1 and key not in carry_pairs:
            name, medium, rw = strip_round_a_word(l["name"], l["medium"])
            if rw == "M":  # never retag here: this path has no ISBN check, so keep the pipeline name and medium
                name, medium, rw = l["name"], l["medium"], None
            res[l["tome_id"]] = {"name": name, "medium": medium, "rules": [rw] if rw else [], "held": "held-cross"}


def plan_names(lines, carry_pairs, isbns):
    """tome_id -> {"name", "medium", "rules", "held"}; pure. Born lines are never renamed."""
    res = {}
    for l in lines:
        if l["born"]:
            res[l["tome_id"]] = {"name": l["name"], "medium": l["medium"], "rules": [], "held": None}
        else:
            n, m, rules = display(l["name"], l["work_title"], l["medium"])
            res[l["tome_id"]] = {"name": n, "medium": m, "rules": rules, "held": None}
    _isbn_guard(lines, res, isbns)
    _within_work_guard(lines, res)
    _cross_work_guard(lines, res, carry_pairs)
    _within_work_guard(lines, res)  # a cross-work revert can create a within-work clash
    return res
