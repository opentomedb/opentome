"""Link a DNB German release line to an existing OpenTome work -- by title and author only.

ISBNs are deliberately NOT a linking feature: German ISBNs appear nowhere else in the
catalogue except the ~35 German Wikipedia lines, and those are the linker's ground truth
(tier0/build_dnb.py measures the linker against them without ISBNs).

Keys (fold()): case, diacritics, macrons, ou/oo/uu, the particle wo -> o, DNB's non-sort
markers, and -- on the DNB side only -- a trailing volume number; each DNB title is
keyed both stripped and unstripped.

    DNB side      original titles (240, 246, 245$b '= ...'), the German title proper
                  (245$a), series statements WITH a $v (490/830; a 490 without $v is an
                  imprint collection: "Action", "Romance")
    OpenTome side primary_title; work_title official/romanized (incl. the German official
                  title); ja_romaji / ja_kanji claims; Wikipedia line_name claims (a line of
                  a work -- "Goblin Slayer: Year One" -- links to that work); aliases only as
                  a low tier (the alias table holds character and place names)

Tiers -- only high and medium are exported (decision 1, docs/dnb-design.md):

    high       an official key matches, and exactly one of the matching works shares an author
    medium     an official key matches exactly one work, no author evidence either way;
               or (prefix) an ORIGINAL title's key of 10+ characters is the START of exactly
               one work's official key and that work shares an author (a truncated romaji).
               German and series titles never take the prefix path: "Detektiv Conan" is the
               start of every Conan spin-off's title
    low        alias-only matches, or an official key that is the start of the DNB key
               (the spin-off shape: "Goblin Slayer! Year one" -> Goblin Slayer) -- review.
               A spin-off whose series statement names the parent franchise ("Bungo Stray
               Dogs: dead apple") still links to the parent at high/medium: a German subtitle
               looks the same ("Hell Mode. Unterforderter Hardcore-Gamer ..."), and capping
               that shape sent three correct lines to review for none caught (2026-09-24)
    ambiguous  several works and nothing to choose between them -- review. When several
               works answer, the one whose title IS the line's own title proper is chosen
               (own-title): high with author evidence, else medium
    none       nothing matched
"""
import collections, json, re, unicodedata

MIN_KEY = 3
MIN_PREFIX = 10
LIST_PREFIX = re.compile(r"^(List of|Liste des|Liste der) .*? (chapters|volumes|chapitres|tomes|light novels|"
                         r"Bände|Kapitel) (of|de|du|des|d'|von) ", re.I)


def fold(s, strip_vol=True):
    s = (s or "").replace("\x98", "").replace("\x9c", "")
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("×", "x").replace("&", " and ")
    s = "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))
    s = s.lower()
    if strip_vol:
        s = re.sub(r"\b(vol(ume)?|band|bd|tome|nr)\.?\s*\d+.*$", "", s)
        s = re.sub(r"[\s,.:;\-–]*\d{1,3}\.?\s*$", "", s)
    s = re.sub(r"\bwo\b", "o", s)
    s = s.replace("ou", "o").replace("oo", "o").replace("uu", "u")
    s = re.sub(r"\(.*?\)", " ", s)
    return re.sub(r"[^0-9a-z぀-ヿ一-鿿]+", "", s)


def keys(titles):
    """Every DNB-side key: stripped and unstripped."""
    return {k for t in titles for k in (fold(t), fold(t, False)) if len(k) >= MIN_KEY}


def name_key(n):
    """'Oda, Eiichirō' / 'Eiichiro Oda' -> frozenset({'eiichiro', 'oda'}); a pen name of one
    token counts when it has 4+ letters ('Okayado'); shorter single tokens say too little."""
    n = (n or "").replace("\x98", "").replace("\x9c", "")
    n = re.sub(r"\(.*?\)", " ", n)
    if "," in n:
        last, first_ = n.split(",", 1)
        n = first_ + " " + last
    s = "".join(c for c in unicodedata.normalize("NFD", n) if not unicodedata.combining(c)).lower()
    s = s.replace("ou", "o").replace("uu", "u")
    toks = [t for t in re.split(r"[^a-z]+", s) if t]
    if len(toks) >= 2 or (len(toks) == 1 and len(toks[0]) >= 4):
        return frozenset(toks)
    return None


class Index:
    """The OpenTome side, read once from the catalogue being built (Wikipedia-sourced
    lines only: a DNB line never links through another DNB line's name)."""

    def __init__(self, db):
        self.official = collections.defaultdict(set)
        self.alias = collections.defaultdict(set)
        self.authors = collections.defaultdict(set)
        self.name = {}
        for wid, t in db.execute("SELECT id, primary_title FROM work"):
            self.name[wid] = t
            self._add(self.official, t, wid)
        for wid, t, kind in db.execute("SELECT work_id, title, kind FROM work_title"):
            self._add(self.alias if kind == "alias" else self.official, LIST_PREFIX.sub("", t), wid)
        for wid, field, v in db.execute("""SELECT entity_id, field, value FROM claim WHERE entity='work'
                                           AND field IN ('ja_romaji','ja_kanji','author','illustrator')"""):
            if field in ("author", "illustrator"):
                try:
                    vals = json.loads(v)
                except ValueError:
                    vals = [v]
                for a in vals if isinstance(vals, list) else [vals]:
                    nk = name_key(str(a))
                    if nk:
                        self.authors[wid].add(nk)
            else:
                self._add(self.official, v, wid)
        for wid, v in db.execute("""SELECT rl.work_id, c.value FROM claim c JOIN release_line rl
                                    ON rl.id=c.entity_id WHERE c.entity='release_line'
                                    AND c.field='line_name' AND c.source='wikipedia'"""):
            self._add(self.official, LIST_PREFIX.sub("", v), wid)
        self.official_keys = sorted(self.official)

    @staticmethod
    def _add(table, title, wid):
        k = fold(title, False)
        if len(k) >= MIN_KEY:
            table[k].add(wid)


def _author_match(idx, works, auth):
    """The works sharing the MOST creators with the line (a spin-off novel credits the
    original author once and its own writers twice: One Piece: Heroines, not One Piece)."""
    score = {w: len(idx.authors.get(w, set()) & auth) for w in works}
    best = max(score.values(), default=0)
    return {w for w, n in score.items() if n and n == best}


def _prefixed(idx, k):
    """Works with an official key that STARTS with k (k itself excluded)."""
    import bisect
    out = set()
    i = bisect.bisect_left(idx.official_keys, k)
    while i < len(idx.official_keys) and idx.official_keys[i].startswith(k):
        if idx.official_keys[i] != k:
            out |= idx.official[idx.official_keys[i]]
        i += 1
    return out


def link(idx, titles, authors, orig=(), name=None):
    """titles: every DNB-side title string of the line; orig: its original titles (240, 246,
    245$b '='), a subset of titles; name: the line's own title proper; authors: raw
    creator names.
    -> (tier, work_id | None, candidates (sorted list), via)"""
    auth = {nk for nk in (name_key(a) for a in authors) if nk}
    ks = keys(titles)
    off = set().union(*[idx.official.get(k, set()) for k in ks]) if ks else set()
    ali = set().union(*[idx.alias.get(k, set()) for k in ks]) if ks else set()
    if off:
        wa = _author_match(idx, off, auth)
        # Several works answer: the one whose title IS the line's own title proper wins -- a
        # series statement or original title names the franchise ("Shaman King", credited
        # to the same creator) while the title proper names the spin-off ("Shaman king the
        # super star"). High when the author backs it too, else medium.
        if len(off) > 1 and name:
            for k in (fold(name, False), fold(name)):
                exact = off & idx.official.get(k, set())
                if len(exact) == 1:
                    w = next(iter(exact))
                    return ("high" if w in wa else "medium"), w, sorted(off), "own-title"
                if exact:
                    break
        if len(wa) == 1:
            return "high", next(iter(wa)), sorted(off), "title+author"
        if len(off) == 1:
            return "medium", next(iter(off)), sorted(off), "title"
        pool = wa or off
        return "ambiguous", None, sorted(pool), "title+author" if wa else "title"
    # a truncated original title (a long romaji the DNB record cuts short), author required
    pre = set()
    for k in keys(orig):
        if len(k) >= MIN_PREFIX:
            pre |= _prefixed(idx, k)
    wa = _author_match(idx, pre, auth)
    if len(wa) == 1:
        return "medium", next(iter(wa)), sorted(pre), "prefix+author"
    ali -= off
    if ali:
        wa = _author_match(idx, ali, auth)
        pick = wa if wa else ali
        if len(pick) == 1:
            return "low", next(iter(pick)), sorted(ali), "alias" + ("+author" if wa else "")
        return "ambiguous", None, sorted(pick), "alias"
    # an official title that is the start of the DNB title: a spin-off or a sub-series
    rev = set()
    for k in ks:
        for n in range(len(k) - 1, MIN_PREFIX - 1, -1):
            rev |= idx.official.get(k[:n], set())
    wa = _author_match(idx, rev, auth)
    if len(wa) == 1:
        return "low", next(iter(wa)), sorted(rev), "spinoff+author"
    return "none", None, [], None
