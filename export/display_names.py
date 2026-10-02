"""Round C display names (spec 2026-10-02 §3.1): the name the artifact writes for a line.
Pure functions; the export applies them after every name-based decision (which keep the pipeline name)."""
import re

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
