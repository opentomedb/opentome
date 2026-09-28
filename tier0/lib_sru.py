"""A polite SRU source: tier0/dnb_sru.py's rules for the KR/CN round's new sources, LoC and BnF
(docs/krcn-design.md §3).

  * >= 3 s between requests ACROSS PROCESSES (a lock-guarded stamp file per source);
  * a descriptive User-Agent (dnb_sru.UA's shape);
  * one 429/503 is answered by waiting out Retry-After (or 60 s); a SECOND one stops the run
    (sticky). With Source.transport_stops (LoC) a transport error -- a dropped connection, a
    timeout -- counts as one too; without it (BnF, DNB) each request gets 3 attempts 30 s apart;
  * every live request is appended to build/<name>-netlog.tsv;
  * responses are cached in .cache/ as sha256(url)[:32] + '.xml', the repo-wide key;
  * <NAME>_OFFLINE=1: a cache miss is an error; <NAME>_REFRESH_DAYS=N: a result set whose manifest
    is older than N days is refetched; <NAME>_MAX_REQUESTS=N: at most N live requests per process
    (SourceBudget) -- a runaway pager stops instead of hammering a gateway;
  * a RESULT SET is cached whole or not at all. Its page urls vary (LoC pages at 100 / 50 / 25 and
    slices), so .cache/<name>-sets.json records query -> {n, urls, fetched_at}, written only after
    every page is stored and the distinct records paged equal numberOfRecords. A set is cached only
    when its manifest entry and every page file exist;
  * a live refetch that fails keeps the previous COMPLETE set (degraded: the run is marked, the
    build never publishes); a set with no complete earlier copy fails the stage (SourceIncomplete).
"""
import fcntl, hashlib, http.client, json, os, re, time, urllib.error, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
UA = ("OpenTome/0.1 (open manga/manhwa catalogue; %s; serial, >=3s between requests; "
      "https://github.com/opentomedb/opentome)")
ID_001 = re.compile(r'tag="001">([^<]+)<')
MAX_RETRY_AFTER = 600


class SourceOfflineMiss(RuntimeError):
    pass


class SourceThrottled(RuntimeError):
    pass


class SourceIncomplete(RuntimeError):
    pass


class SourceBudget(RuntimeError):
    pass


class SourceDiagnostic(RuntimeError):
    """An SRU diagnostic (HTTP 200 carrying <diag:diagnostic>), never cached. .code is its number:
    '61' = "First record position out of range" (LoC's R7 case)."""

    def __init__(self, code, message, url, n=None):
        RuntimeError.__init__(self, "SRU diagnostic %s %r for %s" % (code, message, url))
        self.code, self.message, self.url = code, message, url
        self.n = n                         # the diagnostic body's numberOfRecords, None when absent


def count(text):
    m = re.search(r"numberOfRecords>\s*(\d+)\s*<", text or "")
    return int(m.group(1)) if m else 0


def _store(path, text):
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf8") as f:
        f.write(text)
    os.replace(tmp, path)


FAIL = (SourceThrottled, SourceDiagnostic, SourceBudget, urllib.error.HTTPError, urllib.error.URLError,
        TimeoutError, ConnectionError, RuntimeError)


class Source:
    def __init__(self, name, base, version, schema, page, licence_note, budget):
        self.name, self.base, self.version, self.schema, self.page = name, base, version, schema, page
        up = name.upper()
        self.offline = os.environ.get(up + "_OFFLINE", "0") == "1"
        self.refresh_days = float(os.environ.get(up + "_REFRESH_DAYS", "0") or 0)
        self.interval = max(3.0, float(os.environ.get(up + "_INTERVAL", "3.0") or 3.0))
        self.budget = int(os.environ.get(up + "_MAX_REQUESTS", str(budget)) or 0)
        self.ua = UA % licence_note
        self.relocate(CACHE, os.path.join(ROOT, "build"))
        self.degraded, self.degraded_queries = None, []
        self.stale_queries = []            # offline: cached sets served past their refresh window (loc:offline)
        self.live, self.refusals = 0, 0
        self.sleep, self.now, self.urlopen = time.sleep, time.time, None      # test hooks
        # Completeness hook, None = the generic rule (distinct records == numberOfRecords). LoC sets
        # it: accept(query, n, distinct) -> True when its pager verified a set with duplicate
        # positions (controller ruling 2026-09-27). BnF / DNB keep the generic rule.
        self.accept = None
        # True (LoC): a transport error (dropped connection, timeout) counts as a refusal, so the
        # second transport error or refusal anywhere in a run is the sticky stop. False keeps the
        # generic rule (3 attempts per request, 30 s apart) -- BnF / DNB.
        self.transport_stops = False

    def relocate(self, cache, build):
        self.cache = cache
        self.stamp = os.path.join(cache, ".%s-last-request" % self.name)
        self.sets_path = os.path.join(cache, "%s-sets.json" % self.name)
        self.netlog = os.path.join(build, "%s-netlog.tsv" % self.name)

    def url_for(self, query, start=1, maximum=None):
        return self.base + "?" + urllib.parse.urlencode({
            "version": self.version, "operation": "searchRetrieve", "query": query,
            "recordSchema": self.schema, "maximumRecords": str(maximum or self.page), "startRecord": str(start)})

    def cache_path(self, url):
        return os.path.join(self.cache, hashlib.sha256(url.encode()).hexdigest()[:32] + ".xml")

    # ---- one request ------------------------------------------------------------------------------
    def _throttle(self):
        os.makedirs(self.cache, exist_ok=True)
        with open(self.stamp, "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                # min(): a future-dated stamp (clock skew, a copied cache) must not freeze the run
                wait = min(self.interval - (self.now() - os.path.getmtime(self.stamp)), self.interval)
                if wait > 0:
                    self.sleep(wait)
                t = self.now()
                os.utime(self.stamp, (t, t))
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _log(self, t0, status, size, url):
        os.makedirs(os.path.dirname(self.netlog), exist_ok=True)
        start = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0)) + ".%03d" % (t0 % 1 * 1000)
        with open(self.netlog, "a", encoding="utf8") as f:
            f.write("%s\t%s\t%.2f\t%s\t%s\n" % (start, status, self.now() - t0, size, url))

    def _check(self, text, url):
        if "searchRetrieveResponse" not in text:
            raise SourceDiagnostic("not-sru", "not an SRU response", url)
        if re.search(r"<(?:\w+:)?diagnostic\b", text):
            code = re.search(r"info:srw/diagnostic/1/(\d+)", text)
            msg = re.search(r"<(?:\w+:)?message>([^<]*)<", text)
            n = count(text) if re.search(r"numberOfRecords>\s*\d+\s*<", text) else None
            raise SourceDiagnostic(code.group(1) if code else "?", msg.group(1) if msg else "?", url, n)

    def fetch(self, url):
        """One polite live request -> the checked response text (NOT cached: callers store)."""
        for attempt in range(3):
            if self.refusals > 1:          # the stop is sticky: nothing more is sent this run
                raise SourceThrottled("%s: stopped earlier this run after %d refusals -- see %s"
                                      % (self.name, self.refusals, self.netlog))
            if self.budget and self.live >= self.budget:
                raise SourceBudget("%s: %d live requests this run -- the %s_MAX_REQUESTS cap"
                                   % (self.name, self.live, self.name.upper()))
            self._throttle()
            t0 = self.now()
            self.live += 1
            try:
                req = urllib.request.Request(url, headers={"User-Agent": self.ua})
                with (self.urlopen or urllib.request.urlopen)(req, timeout=90) as r:
                    text = r.read().decode("utf8", "replace")
            except urllib.error.HTTPError as e:
                self._log(t0, "HTTP%d" % e.code, 0, url)
                if e.code not in (429, 503):
                    raise
                self.refusals += 1
                ra = e.headers.get("Retry-After") if e.headers else None
                wait = int(ra) if ra and ra.strip().isdigit() else 60
                if self.refusals > 1 or wait > MAX_RETRY_AFTER:
                    raise SourceThrottled("%s answered HTTP %d (%d refusals this run, Retry-After=%s) -- stopping; "
                                          "see %s" % (self.name, e.code, self.refusals, ra, self.netlog))
                print("    %s HTTP %d, Retry-After=%s -> waiting %ds" % (self.name, e.code, ra, wait), flush=True)
                self.sleep(wait)
                continue
            except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
                # socket.timeout (not a TimeoutError before 3.10) and http.client.IncompleteRead
                # land here too; the last attempt re-raises as URLError, which FAIL covers
                self._log(t0, "ERR", 0, url)
                if self.transport_stops:
                    self.refusals += 1
                    if self.refusals > 1:
                        raise SourceThrottled("%s: transport error %r (%d refusals / transport errors this run) "
                                              "-- stopping; see %s" % (self.name, e, self.refusals, self.netlog))
                if attempt == 2:
                    if isinstance(e, urllib.error.URLError):
                        raise
                    raise urllib.error.URLError(e) from e
                self.sleep(30)
                continue
            self._log(t0, "200", len(text), url)
            self._check(text, url)
            return text
        raise RuntimeError("%s: retries exhausted for %s" % (self.name, url))

    def get(self, url, refresh=False, force=False):
        """One response (a count probe, the canary): from the cache, else one live request.
        Once the source is degraded this run, a miss (or a force) raises instead of going live; a
        force is never answered from a stale copy while degraded (the canary must be fresh)."""
        key = self.cache_path(url)
        if os.path.exists(key):
            stale = force or (refresh and self.refresh_days and
                              self.now() - os.path.getmtime(key) > self.refresh_days * 86400)
            if not stale or self.offline or (self.degraded and not force):
                with open(key, encoding="utf8") as f:
                    return f.read()
        if self.offline:
            raise SourceOfflineMiss("%s_OFFLINE=1 and no cached response for %s" % (self.name.upper(), url))
        if self.degraded:
            raise SourceIncomplete("%s is failing this run (%s) and %s cannot be answered from the cache"
                                   % (self.name, self.degraded, url))
        text = self.fetch(url)
        _store(key, text)
        return text

    # ---- whole result sets --------------------------------------------------------------------------
    def _sets(self):
        try:
            with open(self.sets_path, encoding="utf8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def cached_set(self, query):
        e = self._sets().get(query)
        if not e:
            return None
        pages = []
        for u in e["urls"]:
            p = self.cache_path(u)
            if not os.path.exists(p):
                return None
            with open(p, encoding="utf8") as f:
                pages.append(f.read())
        if self.distinct(pages) != e.get("distinct", e["n"]):
            return None                    # a page file changed under the manifest: not a whole set
        return e["n"], pages, e["fetched_at"]

    def store_set(self, query, n, staged, distinct=None):
        """distinct: set only when a source's accept() hook took distinct != n (LoC duplicates)."""
        for u, t in staged:
            _store(self.cache_path(u), t)
        sets = self._sets()
        sets[query] = {"n": n, "urls": [u for u, _ in staged], "fetched_at": self.now()}
        if distinct is not None:
            sets[query]["distinct"] = distinct
        os.makedirs(self.cache, exist_ok=True)
        _store(self.sets_path, json.dumps(sets, sort_keys=True, indent=0))

    def distinct(self, pages):
        return len({m for t in pages for m in ID_001.findall(t)})

    def page_plain(self, query, retries=3, wait=10):
        """Page a set self.page records per request; each page gets a bounded retry (`retries`
        attempts, `wait` s apart) on a diagnostic or a 5xx (BnF: plan ruling P15). -> (n, staged)."""
        def one(start):
            u = self.url_for(query, start)
            for attempt in range(retries):
                try:
                    return u, self.fetch(u)
                except (SourceDiagnostic, urllib.error.HTTPError) as e:
                    if isinstance(e, urllib.error.HTTPError) and e.code < 500:
                        raise
                    if attempt == retries - 1:
                        raise
                    self.sleep(wait)
        first = one(1)
        n = count(first[1])
        staged = [first]
        for start in range(1 + self.page, n + 1, self.page):
            staged.append(one(start))
        return n, staged

    def search(self, query, refresh=False, force=False, pager=None):
        """Every record of a query -> (numberOfRecords, page texts), cached whole or not at all.
        pager(query) -> (n, [(url, text)]) pages it live (default page_plain; LoC passes its ladder)."""
        have = self.cached_set(query)
        if have:
            n, pages, t = have
            stale = force or (refresh and self.refresh_days and self.now() - t > self.refresh_days * 86400)
            if not stale or self.offline or self.degraded:
                if stale and self.degraded and query not in self.degraded_queries:
                    self.degraded_queries.append(query)
                if stale and self.offline and query not in self.stale_queries:
                    self.stale_queries.append(query)
                return n, pages
        if self.offline:
            raise SourceOfflineMiss("%s_OFFLINE=1 and no complete cached result set for %r"
                                    % (self.name.upper(), query))
        if self.degraded:
            raise SourceIncomplete("%s is failing this run (%s) and %r has no complete cached set"
                                   % (self.name, self.degraded, query))
        try:
            n, staged = (pager or self.page_plain)(query)
            if have and n == 0 < have[0]:
                raise SourceDiagnostic("empty", "announced 0 records, the cached set holds %d" % have[0], query)
            got = self.distinct([t for _, t in staged])
            if got != n and not (self.accept and self.accept(query, n, got)):
                raise SourceDiagnostic("paging", "announced %d records, paged %d distinct" % (n, got), query)
        except FAIL as e:
            if not have:
                raise SourceIncomplete("%s: %s -- no complete earlier result set of %r to fall back on"
                                       % (type(e).__name__, e, query)) from e
            self.degraded = "%s: %s" % (type(e).__name__, str(e)[:160])
            self.degraded_queries.append(query)
            print("    WARNING %s refresh failed (%s) -- %r keeps its previous complete set; later "
                  "refreshes this run are skipped" % (self.name, self.degraded, query), flush=True)
            return have[0], have[1]
        self.store_set(query, n, staged, None if got == n else got)
        return n, [t for _, t in staged]
