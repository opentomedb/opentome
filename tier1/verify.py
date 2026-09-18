"""Tier 1: cross-verify tier-0 Wikipedia records against independent sources.

Measures AGREEMENT, which is the calibration signal the product rests on.
Tier-0 gave completeness; this gives correctness.

  JP ISBNs -> openBD   (year-month precision -> compare at month)
  EN ISBNs -> Google Books (day precision -> compare exactly)

Everything is disk-cached so re-runs cost zero network and zero quota.
"""
import hashlib, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

import os


def _build(name):
    """Default build-output path. Never /tmp: macOS cleaned it and destroyed a
    fully-built catalogue. Outputs belong beside the cache, inside the repo."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(root, "build")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


UA = "manga-metadata-research/0.1 (non-commercial catalogue evaluation)"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
_last = [0.0]


def _throttle(interval):
    w = interval - (time.time() - _last[0])
    if w > 0:
        time.sleep(w)
    _last[0] = time.time()


def _fetch(url, interval=0.35, retries=3):
    os.makedirs(CACHE, exist_ok=True)
    key = os.path.join(CACHE, hashlib.sha256(url.encode()).hexdigest()[:32] + ".json")
    if os.path.exists(key):
        with open(key, encoding="utf8") as f:
            return json.load(f)
    delay = 2.0
    for a in range(retries):
        _throttle(interval)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.load(r)
            with open(key, "w", encoding="utf8") as f:
                json.dump(d, f, ensure_ascii=False)
            return d
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and a < retries - 1:
                time.sleep(delay); delay *= 2; continue
            return {"_http_error": e.code}
        except Exception as e:
            return {"_error": str(e)[:80]}
    return {"_error": "retries exhausted"}


def isbn13_valid(s):
    s = "".join(c for c in s if c.isdigit())
    if len(s) != 13:
        return None
    chk = sum((1 if i % 2 == 0 else 3) * int(c) for i, c in enumerate(s[:12]))
    return (10 - chk % 10) % 10 == int(s[12])


def openbd_batch(isbns, size=80):
    """openBD accepts comma-separated ISBNs -- batch to keep it polite."""
    out = {}
    for i in range(0, len(isbns), size):
        chunk = isbns[i:i + size]
        url = "https://api.openbd.jp/v1/get?isbn=" + ",".join(chunk)
        d = _fetch(url, interval=0.5)
        if isinstance(d, dict):
            continue
        for isbn, rec in zip(chunk, d):
            if not rec:
                continue
            iso = parse_openbd_pubdate((rec.get("summary") or {}).get("pubdate"))
            if iso:
                out[isbn] = iso
    return out


def parse_openbd_pubdate(pd):
    """openBD pubdate shapes seen in the cache: '201003', '20100317',
    '2010-03-17', '2010-3', '2014-5 (第9刷)', '2011-6-30', '2012-7-'.

    The old code stripped every non-digit and cut at 6, so '2014-5 (第9刷)'
    became '2014-59' -- 53 such month-57-to-94 dates WON resolution -- and
    3,568 day-precision dates were thrown away as year-month. Parse the shape
    explicitly, keep the day when it exists, and refuse invalid months/days.
    """
    import datetime
    s = re.sub(r"[（(].*?[)）]", "", pd or "").strip()      # drop reprint notes
    m = re.match(r"^(\d{4})[-/.]?(\d{1,2})?[-/.]?(\d{1,2})?", s)
    if not m or not m.group(1):
        return None
    y = int(m.group(1))
    if not 1900 <= y <= 2100:
        return None
    mo = int(m.group(2)) if m.group(2) else None
    d = int(m.group(3)) if m.group(3) else None
    if mo is not None and not 1 <= mo <= 12:
        return None
    if d is not None:
        try:
            datetime.date(y, mo, d)
            return f"{y:04d}-{mo:02d}-{d:02d}"
        except (ValueError, TypeError):
            d = None
    if mo is not None:
        return f"{y:04d}-{mo:02d}"
    return f"{y:04d}"


def gbooks(isbn, key):
    url = ("https://www.googleapis.com/books/v1/volumes?q=isbn:" + isbn +
           ("&key=" + key if key else ""))
    d = _fetch(url, interval=0.35)
    if not isinstance(d, dict) or d.get("totalItems", 0) == 0 or "items" not in d:
        return None
    return (d["items"][0].get("volumeInfo") or {}).get("publishedDate")


def main():
    key = os.environ.get("GOOGLE_BOOKS_API_KEY", "")
    data = json.load(open(sys.argv[1] if len(sys.argv) > 1 else _build("tier0_16.json")))
    vols = [v for r in data.values() for v in r.get("volumes", [])]

    # records nest per-market data under `markets` since the release-line split
    def M(v, role):
        return (v.get("markets") or {}).get(role) or {}
    for v in vols:                       # flatten for this module's local use
        for role, pre in (("original", "original"), ("licensed", "licensed")):
            m = M(v, role)
            if m.get("date"):
                v[pre + "_date"] = m["date"]
            if m.get("isbn13"):
                v[pre + "_isbn"] = m["isbn13"]
    jp = [v for v in vols if v.get("original_isbn") and v.get("original_date")]
    en = [v for v in vols if v.get("licensed_isbn") and v.get("licensed_date")]
    print(f"records: {len(vols)}  |  JP verifiable: {len(jp)}  EN verifiable: {len(en)}")

    # --- ISBN checksum (free correctness signal) ---
    for label, rows, fld in (("JP", jp, "original_isbn"), ("EN", en, "licensed_isbn")):
        res = [isbn13_valid(v[fld]) for v in rows]
        ok = sum(1 for x in res if x is True); bad = sum(1 for x in res if x is False)
        print(f"  {label} ISBN-13 checksum: {ok} valid, {bad} INVALID, {len(res)-ok-bad} not-13")

    # --- JP vs openBD, compared at month precision ---
    print("\n=== JP: Wikipedia vs openBD (month precision) ===")
    got = openbd_batch(sorted({v["original_isbn"] for v in jp}))
    agree = disagree = missing = 0
    jp_bad = []
    for v in jp:
        o = got.get(v["original_isbn"])
        if not o:
            missing += 1; continue
        if len(o) == 4:
            ok = v["original_date"][:4] == o
        else:
            ok = v["original_date"][:7] == o
        if ok: agree += 1
        else:
            disagree += 1
            jp_bad.append((v.get("article","")[:34], v["volume"], v["original_date"], o))
    tot = agree + disagree
    print(f"  found in openBD: {tot}/{len(jp)}  (not found: {missing})")
    if tot:
        print(f"  AGREE {agree} ({agree/tot*100:.1f}%)   DISAGREE {disagree} ({disagree/tot*100:.1f}%)")
    for r in jp_bad[:12]:
        print(f"    ! {r[0]:<34} v{r[1]:<4} wiki={r[2]}  openBD={r[3]}")

    # --- EN vs Google Books, day precision ---
    print("\n=== EN: Wikipedia vs Google Books (day precision) ===")
    if not key:
        print("  (no GOOGLE_BOOKS_API_KEY set -- skipped)"); return
    ex = near = off = miss = coarse = 0
    en_bad = []
    for i, v in enumerate(en):
        g = gbooks(v["licensed_isbn"], key)
        if not g:
            miss += 1; continue
        if len(g) < 10:
            coarse += 1
            continue
        if g == v["licensed_date"]:
            ex += 1
        else:
            from datetime import date
            try:
                a = date(*map(int, v["licensed_date"].split("-")))
                b = date(*map(int, g.split("-")))
                d = abs((a - b).days)
            except Exception:
                d = 9999
            if d <= 7: near += 1
            else:
                off += 1
                en_bad.append((v.get("article","")[:34], v["volume"], v["licensed_date"], g, d))
        if i % 60 == 0 and i:
            print(f"    ...{i}/{len(en)}")
    tot = ex + near + off
    print(f"  found w/ day precision: {tot}/{len(en)}  (coarse date: {coarse}, not found: {miss})")
    if tot:
        print(f"  EXACT {ex} ({ex/tot*100:.1f}%)  WITHIN-7d {near} ({near/tot*100:.1f}%)  OFF {off} ({off/tot*100:.1f}%)")
    for r in en_bad[:12]:
        print(f"    ! {r[0]:<34} v{r[1]:<4} wiki={r[2]}  gbooks={r[3]}  ({r[4]}d)")


if __name__ == "__main__":
    main()
