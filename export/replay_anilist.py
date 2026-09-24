"""Offline before/after replay of export/resolve_anilist.py -- stdlib only, zero network.

    python3 export/replay_anilist.py ARTIFACT [--base REV]

Why: a resolver rule is judged by what it does to EVERY line, not by the handful it was
written for -- a new tier that binds 14 lines and quietly moves one already-right bind is
a regression, because Mangarr pins whatever id the catalogue carries on every future add.

Every EN line of ARTIFACT (a published manga-metadata.sqlite) goes into a temporary copy
with anilist_id reset to NULL and corrections/aliases.json's removals applied (what a
fresh export carries), then is resolved twice: by resolve_anilist.py at REV (default
ca0935f, read with `git show`) and by the working tree's. Both read only .cache/anilist/;
a term with no cached page is "no result" and counted as UNCACHED -- the upper-bound side,
which only a live run settles. Nothing is ever requested.

Prints: the base replay's agreement with ARTIFACT's own ids (the replay's fidelity), then
NEW binds, CHANGED binds (a line bound by both, to different ids -- each needs a
justification), LOST binds (must be 0), and the uncached terms.
"""
import argparse, importlib.util, os, shutil, sqlite3, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.environ.setdefault("ANILIST_CACHE", os.path.join(ROOT, ".cache", "anilist"))
os.environ["ANILIST_OFFLINE"] = "1"          # backstop: search() is replaced below anyway
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tier2"))


def load_module(name, source):
    path = os.path.join(tempfile.mkdtemp(prefix="replay-"), name + ".py")
    with open(path, "w", encoding="utf8") as f:
        f.write(source)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def offline(mod, misses):
    """mod.search, cache only: a miss is an empty page, recorded as (family, term)."""
    def search(terms, novel):
        family = "novel" if novel else "manga"
        out = {}
        for t in dict.fromkeys(terms):
            page = mod._cache_get(mod._cache_path("search", family, t))
            if page is None:
                misses.add((family, t))
                page = []
            out[t] = page
        return out
    mod.search = search


def track_terms(mod):
    """Record on each line the terms it searched after the name (every retry goes through
    _search_round), so a line that touched an uncached page is reported as unmeasured."""
    real = mod._search_round

    def wrapped(todo, novel):
        for ln, t, _ in todo:
            ln.setdefault("tried", []).append(t)
        return real(todo, novel)
    mod._search_round = wrapped


def fresh_copy(artifact, tmp):
    """The artifact with every EN anilist_id NULL and the curated alias removals applied."""
    from corrections import load_alias_removals
    from to_mangarr import normalize
    path = os.path.join(tmp, "replay.sqlite")
    shutil.copyfile(artifact, path)
    db = sqlite3.connect(path)
    db.execute("UPDATE series SET anilist_id=NULL WHERE language='en'")
    removed = 0
    for line_id, alias in load_alias_removals():
        removed += db.execute("""DELETE FROM series_alias WHERE alias IN (?,?) AND gcd_series_id=
                                 (SELECT gcd_series_id FROM series WHERE tome_id=?)""",
                              (alias, normalize(alias), line_id)).rowcount
    db.commit()
    return db, removed


def run(mod, db):
    misses = set()
    offline(mod, misses)
    track_terms(mod)
    lines = mod.load_lines(db)
    mod.resolve(lines)
    for ln in lines:
        family = "novel" if ln["novel"] else "manga"
        terms = [mod.for_search(ln["name"])] + ln.get("tried", [])
        ln["uncached"] = [t for t in terms if (family, t) in misses]
    return {ln["id"]: ln for ln in lines}, misses


def relation(key, term, m):
    """How the bound candidate's titles relate to the term: '=', 'term<cand' (the term's key
    inside a title's), 'cand<term' (a title's key inside the term's) -- the substring tier's
    two directions, which are checked by hand."""
    t = m.get("title") or {}
    keys = [key(x) for x in (t.get("romaji"), t.get("english"), t.get("native"), *(m.get("synonyms") or []))]
    k = key(term)
    if k in keys:
        return "="
    if any(k in x for x in keys if x):
        return "term<cand"
    if any(x in k for x in keys if x):
        return "cand<term"
    return "?"


def desc(m):
    t = m.get("title") or {}
    return "%s %r [%s, %s vols]" % (m["id"], t.get("english") or t.get("romaji"), m.get("format"), m.get("volumes"))


def row(ln):
    return "%s (%s, %s vols)" % (ln["name"], ln["medium"], ln["volume_count"])


def main(argv):
    ap = argparse.ArgumentParser(description="offline before/after replay of resolve_anilist.py")
    ap.add_argument("artifact")
    ap.add_argument("--base", default="ca0935f", help="git revision of the stock resolver (default ca0935f)")
    a = ap.parse_args(argv)
    src = subprocess.run(["git", "-C", ROOT, "show", "%s:export/resolve_anilist.py" % a.base],
                         check=True, capture_output=True, text=True).stdout
    base = load_module("resolve_anilist_base", src)
    with open(os.path.join(HERE, "resolve_anilist.py"), encoding="utf8") as f:
        head = load_module("resolve_anilist_head", f.read())
    tmp = tempfile.mkdtemp(prefix="replay-")
    try:
        db, removed = fresh_copy(a.artifact, tmp)
        orig = sqlite3.connect("file:%s?mode=ro" % a.artifact, uri=True)
        release = dict(orig.execute("SELECT gcd_series_id, anilist_id FROM series WHERE language='en'").fetchall())
        orig.close()
        before, miss_b = run(base, db)
        after, miss_a = run(head, db)
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    pid = lambda ln: ln["pick"]["id"] if ln["pick"] else None
    rel = lambda ln: relation(head.key, ln["term"], ln["pick"])
    flag = lambda *lns: " [UNCACHED: %s]" % ", ".join(sorted({t for x in lns for t in x["uncached"]})) \
        if any(x["uncached"] for x in lns) else ""
    n = len(before)
    print("replay: %s, base %s vs working tree -- %d EN lines considered, %d alias removal row(s) applied"
          % (os.path.basename(a.artifact), a.base, n, removed))
    print("bound: base %d, working tree %d" % (sum(1 for ln in before.values() if ln["pick"]),
                                               sum(1 for ln in after.values() if ln["pick"])))
    agree = sum(1 for s, ln in before.items() if pid(ln) == release.get(s))
    print("fidelity: base replay agrees with the artifact's own anilist_id on %d / %d lines" % (agree, n))
    for s, ln in sorted(before.items(), key=lambda x: x[1]["name"]):
        if pid(ln) != release.get(s):
            print("  differs  %s: artifact %s, base replay %s" % (row(ln), release.get(s), pid(ln)))

    new = [(before[s], ln) for s, ln in after.items() if ln["pick"] and not before[s]["pick"]]
    changed = [(before[s], ln) for s, ln in after.items()
               if ln["pick"] and before[s]["pick"] and pid(ln) != pid(before[s])]
    lost = [(before[s], ln) for s, ln in after.items() if before[s]["pick"] and not ln["pick"]]
    print("\nNEW binds: %d" % len(new))
    for b, ln in sorted(new, key=lambda x: x[1]["name"]):
        print("  + %s -> %s via %s %s (term %r)%s" % (row(ln), desc(ln["pick"]), ln["via"], rel(ln), ln["term"], flag(b, ln)))
    print("\nCHANGED binds: %d" % len(changed))
    for b, ln in sorted(changed, key=lambda x: x[1]["name"]):
        print("  ~ %s: %s via %s (term %r)\n        -> %s via %s %s (term %r)%s"
              % (row(ln), desc(b["pick"]), b["via"], b["term"], desc(ln["pick"]), ln["via"], rel(ln), ln["term"], flag(b, ln)))
    print("\nLOST binds: %d" % len(lost))
    for b, ln in sorted(lost, key=lambda x: x[1]["name"]):
        print("  - %s: was %s via %s (term %r)%s" % (row(ln), desc(b["pick"]), b["via"], b["term"], flag(b, ln)))

    # against what is PUBLISHED: a corrections change (an alias removal) moves the base replay
    # too, so a bind the published artifact carries can only be seen changing here
    print("\nvs the artifact's published ids (working tree):")
    for s, ln in sorted(after.items(), key=lambda x: x[1]["name"]):
        was = release.get(s)
        if pid(ln) != was and (was, pid(ln)) != (release.get(s), pid(before[s])):
            print("  %s %s: published %s -> %s%s" % ("~" if was and ln["pick"] else "+" if ln["pick"] else "-",
                                                     row(ln), was, desc(ln["pick"]) if ln["pick"] else None, flag(ln)))
    print("  (lines where the base replay already differs from the artifact are listed under fidelity)")

    only_a = sorted(miss_a - miss_b)
    print("\nUNCACHED terms: base %d, working tree %d (%d new to the working tree -- upper bound, needs a live run)"
          % (len(miss_b), len(miss_a), len(only_a)))
    for family, t in only_a:
        print("  ? %s %r" % (family, t))
    return 1 if lost else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
