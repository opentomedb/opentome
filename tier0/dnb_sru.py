"""DNB SRU client: serial, throttled across processes, disk-cached, polite.

The Deutsche Nationalbibliothek's bibliographic data is CC0 1.0
(https://www.dnb.de/businessmodel.html, 17.12.2024). This module only fetches;
tier0/dnb_marc.py parses and tier0/build_dnb.py builds lines from what it returns.

Politeness (docs/dnb-design.md "Access"): DNB documents no rate limit, but the
2026-09-24 spike was answered with HTTP 429 after ~46 requests at ~1.7 s spacing
(one pair < 1 s apart across two processes). So:

  * >= 3 s between requests ACROSS PROCESSES -- the time of the last request lives
    in a lock-guarded stamp file, so two scripts started back to back cannot burst;
  * one 429/503 is answered by waiting out Retry-After (or 60 s); a SECOND one in
    the same run stops the run (DnbThrottled) instead of backing off for an hour --
    repeated refusals are DNB telling us to go away, and a human decides what next;
  * every live request is appended to build/dnb-netlog.tsv, so the request budget
    of a run is auditable after the fact;
  * responses are cached in .cache/ under the repo-wide sha256(url)[:32] + '.xml'
    key (tier1/enrich_more._fetch_xml), so a rerun costs zero requests.

DNB_OFFLINE=1 makes a cache miss an error instead of a request (tests, and proving a
rebuild is offline). DNB_REFRESH_DAYS=N is the opt-in freshness window: callers pass
`refresh=True` for slices that can still change (last year and later, the no-year
remainder), and those are refetched when their cached set is older than N days. Default
off: a rebuild is reproducible from the cache. A result set is cached whole or not at all
(search()); see DEGRADED below for what a refresh run does when DNB fails.
"""
import fcntl, hashlib, os, re, time, urllib.error, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
STAMP = os.path.join(CACHE, ".dnb-last-request")
NETLOG = os.path.join(ROOT, "build", "dnb-netlog.tsv")
BASE = "https://services.dnb.de/sru/dnb"
UA = ("OpenTome/0.1 (open manga/light-novel catalogue; CC0 DNB bibliographic data; "
      "serial, >=3s between requests; https://github.com/DrAwesome441/opentome)")
# Never below 3 s, whatever the environment says.
INTERVAL = max(3.0, float(os.environ.get("DNB_INTERVAL", "3.0") or 3.0))
OFFLINE = os.environ.get("DNB_OFFLINE", "0") == "1"
REFRESH_DAYS = float(os.environ.get("DNB_REFRESH_DAYS", "0") or 0)
MAX_RETRY_AFTER = 600          # a Retry-After beyond 10 minutes stops the run instead
PAGE = 100                     # DNB's maximumRecords ceiling


class DnbOfflineMiss(RuntimeError):
    pass


class DnbThrottled(RuntimeError):
    pass


class DnbDiagnostic(RuntimeError):
    """SRU answered with a diagnostic (bad query) -- never cached."""


class DnbIncomplete(RuntimeError):
    """DNB failed and there is no complete earlier page set of this result set to fall back
    on (a first run, an unseeded cache, a new slice) -- the build must stop, loudly."""


# A REFRESH run (DNB_REFRESH_DAYS set, the scheduled build) does not fail the catalogue over a
# DNB outage it can ride out: on a second 429/503, a 5xx, a network error, a diagnostic or a
# paging mismatch, a result set whose previous COMPLETE page set is cached keeps that set,
# whole (DEGRADED; the affected queries in DEGRADED_QUERIES). A result set with no complete
# earlier set fails the run (DnbIncomplete) -- a first run and an unseeded cache stay strict,
# refresh window or not. A degraded build is recorded in meta and never published
# (export/publish.sh refuses it).
DEGRADED = [None]            # the reason, once degraded
DEGRADED_QUERIES = []        # result sets that kept their previous page set


_refusals = [0]                # 429/503 answers seen by this process
live_requests = [0]            # requests that went to the network in this process


def url_for(query, start=1, maximum=PAGE):
    return BASE + "?" + urllib.parse.urlencode({
        "version": "1.1", "operation": "searchRetrieve", "query": query,
        "recordSchema": "MARC21-xml", "maximumRecords": str(maximum), "startRecord": str(start)})


def cache_path(url):
    return os.path.join(CACHE, hashlib.sha256(url.encode()).hexdigest()[:32] + ".xml")


def _throttle():
    """Sleep until INTERVAL has passed since the last request by ANY process, then
    stamp. The stamp's mtime is the clock; the lock makes read-sleep-stamp atomic."""
    os.makedirs(CACHE, exist_ok=True)
    with open(STAMP, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            last = os.path.getmtime(STAMP)
            wait = INTERVAL - (time.time() - last)
            if wait > 0:
                time.sleep(wait)
            now = time.time()
            os.utime(STAMP, (now, now))
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _log(t0, status, size, url):
    """One line per live request: START time (ms), status, seconds, bytes, url."""
    os.makedirs(os.path.dirname(NETLOG), exist_ok=True)
    start = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0)) + ".%03d" % (t0 % 1 * 1000)
    with open(NETLOG, "a", encoding="utf8") as f:
        f.write("%s\t%s\t%.2f\t%s\t%s\n" % (start, status, time.time() - t0, size, url))


def _check(text, url):
    if "searchRetrieveResponse" not in text:
        raise DnbDiagnostic("not an SRU response: %s" % url)
    if re.search(r"<(?:\w+:)?diagnostic\b", text):
        m = re.search(r"<(?:\w+:)?message>([^<]*)<", text)
        raise DnbDiagnostic("SRU diagnostic %r for %s" % (m.group(1) if m else "?", url))


def get(url, refresh=False, force=False):
    """One response (a numberOfRecords count): from the cache, else one polite live request.
    refresh: refetch a copy older than DNB_REFRESH_DAYS; force: refetch whatever its age.
    Offline -- or once a refresh run has degraded -- a cached copy is served, stale or not."""
    key = cache_path(url)
    have = os.path.exists(key)
    if have:
        stale = force or (refresh and REFRESH_DAYS and
                          time.time() - os.path.getmtime(key) > REFRESH_DAYS * 86400)
        if not stale or OFFLINE or DEGRADED[0]:
            with open(key, encoding="utf8") as f:
                return f.read()
    if OFFLINE:
        raise DnbOfflineMiss("DNB_OFFLINE=1 and no cached response for " + url)
    if DEGRADED[0]:
        raise DnbIncomplete("DNB is failing this run (%s) and %s is not cached" % (DEGRADED[0], url))
    try:
        text = _live(url)
    except (DnbThrottled, DnbDiagnostic, urllib.error.HTTPError, urllib.error.URLError,
            TimeoutError, ConnectionError, RuntimeError) as e:
        if not (REFRESH_DAYS and have):
            raise
        DEGRADED[0] = "%s: %s" % (type(e).__name__, str(e)[:160])
        print("    WARNING DNB refresh failed (%s) -- the cached count is kept" % DEGRADED[0], flush=True)
        with open(key, encoding="utf8") as f:
            return f.read()
    _store(key, text)
    return text


def _live(url):
    """One polite live request -> the response text (checked, NOT cached: callers store)."""
    for attempt in range(3):
        _throttle()
        t0 = time.time()
        live_requests[0] += 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                text = r.read().decode("utf8", "replace")
        except urllib.error.HTTPError as e:
            _log(t0, "HTTP%d" % e.code, 0, url)
            if e.code not in (429, 503):
                raise
            _refusals[0] += 1
            ra = e.headers.get("Retry-After")
            wait = int(ra) if ra and ra.strip().isdigit() else 60
            if _refusals[0] > 1 or wait > MAX_RETRY_AFTER:
                raise DnbThrottled("DNB answered HTTP %d (%d refusals this run, Retry-After=%s) -- "
                                   "stopping; see build/dnb-netlog.tsv" % (e.code, _refusals[0], ra))
            print("    DNB HTTP %d, Retry-After=%s -> waiting %ds" % (e.code, ra, wait), flush=True)
            time.sleep(wait)
            continue
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            _log(t0, "ERR", 0, url)
            if attempt == 2:
                raise
            time.sleep(30)
            continue
        _log(t0, "200", len(text), url)
        _check(text, url)
        return text
    raise RuntimeError("DNB: retries exhausted for " + url)


def count(text):
    m = re.search(r"numberOfRecords>\s*(\d+)\s*<", text)
    return int(m.group(1)) if m else 0


def _cached_set(query):
    """The complete cached page set of a result set, or None: page 1 and every page its
    numberOfRecords implies must be cached."""
    k1 = cache_path(url_for(query, 1))
    if not os.path.exists(k1):
        return None
    with open(k1, encoding="utf8") as f:
        first = f.read()
    n = count(first)
    pages = [first]
    for start in range(1 + PAGE, n + 1, PAGE):
        k = cache_path(url_for(query, start))
        if not os.path.exists(k):
            return None
        with open(k, encoding="utf8") as f:
            pages.append(f.read())
    return n, pages, os.path.getmtime(k1)


def _distinct(pages):
    return len({m for t in pages for m in re.findall(r'tag="001">([^<]+)<', t)})


def search(query, refresh=False, force=False):
    """Every record of a CQL query, paged 100 at a time -> (numberOfRecords, response texts).

    A result set is fetched and cached as a WHOLE: a live refetch is staged in memory and
    written to the cache only when every page arrived and the pages hold as many distinct
    records as announced. So the cache only ever holds complete sets, and a refresh that fails
    halfway keeps the previous set intact. A result set must stay below DNB's 99,000 paging
    ceiling; callers slice by jhr."""
    have = _cached_set(query)
    if have:
        n, pages, mtime = have
        stale = force or (refresh and REFRESH_DAYS and time.time() - mtime > REFRESH_DAYS * 86400)
        if not stale or OFFLINE or DEGRADED[0]:
            if stale and DEGRADED[0] and query not in DEGRADED_QUERIES:
                DEGRADED_QUERIES.append(query)
            return n, pages
    if OFFLINE:
        raise DnbOfflineMiss("DNB_OFFLINE=1 and no complete cached result set for " + query)
    if DEGRADED[0]:
        raise DnbIncomplete("DNB is failing this run (%s) and %r has no complete cached result set"
                            % (DEGRADED[0], query))
    try:
        first = _live(url_for(query, 1))
        n = count(first)
        if n > 99000:
            raise ValueError("DNB result set too large to page (%d): %s" % (n, query))
        staged = [(url_for(query, 1), first)]
        for start in range(1 + PAGE, n + 1, PAGE):
            u = url_for(query, start)
            staged.append((u, _live(u)))
        got = _distinct([t for _, t in staged])
        if got != n:
            raise DnbDiagnostic("DNB result set %r announced %d records, paged %d distinct" % (query, n, got))
    except (DnbThrottled, DnbDiagnostic, urllib.error.HTTPError, urllib.error.URLError,
            TimeoutError, ConnectionError, RuntimeError) as e:
        if not have:
            raise DnbIncomplete("%s: %s -- no complete earlier result set of %r to fall back on"
                                % (type(e).__name__, e, query)) from e
        if not REFRESH_DAYS:
            raise
        DEGRADED[0] = "%s: %s" % (type(e).__name__, str(e)[:160])
        DEGRADED_QUERIES.append(query)
        print("    WARNING DNB refresh failed (%s) -- %r keeps its previous complete page set, and "
              "every later refresh this run is skipped" % (DEGRADED[0], query), flush=True)
        return have[0], have[1]
    for u, t in staged:
        _store(cache_path(u), t)
    return n, [t for _, t in staged]


def _store(key, text):
    tmp = key + ".part"
    with open(tmp, "w", encoding="utf8") as f:
        f.write(text)
    os.replace(tmp, key)


def total(query, force=False):
    """numberOfRecords only (one maximumRecords=1 request, cached)."""
    return count(get(url_for(query, 1, 1), force=force))
