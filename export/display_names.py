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
