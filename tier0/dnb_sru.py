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
`refresh=True` for slices that can still change (current / future years, parent
batches), and those are refetched when their cached copy is older than N days.
Default off: a rebuild is reproducible from the cache.
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


class DnbUnavailable(RuntimeError):
    """A refresh run fell back to the cache after a DNB failure, and this url is not cached."""


# A REFRESH run (DNB_REFRESH_DAYS set, the scheduled build) must never fail the catalogue over
# DNB: on a second 429/503, a 5xx, a network error or a diagnostic it falls back to the stale
# cache for the rest of the run (DEGRADED) and says so. Offline and first runs stay strict.
DEGRADED = [None]            # the reason, once degraded


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
    """The response text for url: from the cache, else one polite live request. refresh:
    refetch a copy older than DNB_REFRESH_DAYS; force: refetch whatever its age. Offline, a
    cached copy is always served, stale or not."""
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
        raise DnbUnavailable(url)
    try:
        return _live(url, key)
    except (DnbThrottled, DnbDiagnostic, urllib.error.HTTPError, urllib.error.URLError,
            TimeoutError, ConnectionError, RuntimeError) as e:
        if not REFRESH_DAYS:
            raise
        DEGRADED[0] = "%s: %s" % (type(e).__name__, str(e)[:160])
        print("    WARNING DNB refresh failed (%s) -- falling back to the cached responses for the "
              "rest of this run" % DEGRADED[0], flush=True)
        if have:
            with open(key, encoding="utf8") as f:
                return f.read()
        raise DnbUnavailable(url)


def _live(url, key):
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
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            _log(t0, "ERR", 0, url)
            if attempt == 2:
                raise
            time.sleep(30)
            continue
        _log(t0, "200", len(text), url)
        _check(text, url)
        tmp = key + ".part"
        with open(tmp, "w", encoding="utf8") as f:
            f.write(text)
        os.replace(tmp, key)
        return text
    raise RuntimeError("DNB: retries exhausted for " + url)


def count(text):
    m = re.search(r"numberOfRecords>\s*(\d+)\s*<", text)
    return int(m.group(1)) if m else 0


def search(query, refresh=False, force=False):
    """Every record of a CQL query, paged 100 at a time -> list of response texts.
    A result set must stay below DNB's 99,000 paging ceiling; callers slice by jhr."""
    first = get(url_for(query, 1), refresh, force)
    n = count(first)
    if n > 99000:
        raise ValueError("DNB result set too large to page (%d): %s" % (n, query))
    pages = [first]
    for start in range(1 + PAGE, n + 1, PAGE):
        pages.append(get(url_for(query, start), refresh, force))
    return n, pages


def total(query, force=False):
    """numberOfRecords only (one maximumRecords=1 request, cached)."""
    return count(get(url_for(query, 1, 1), force=force))
