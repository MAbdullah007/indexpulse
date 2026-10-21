"""
IndexPulse core logic — no Streamlit imports, so everything here can be unit-tested.

Engines (all have a free tier), tried top-to-bottom with automatic fallback:
  1. Google Search Console URL Inspection API — 2,000/day per site, only YOUR verified sites
  2. Bright Data SERP API                      — 5,000 free credits/month (shared with other Bright Data products)
  3. SerpApi                                   — Free plan: 250 searches/month, 50/hour
  4. Serper                                    — 2,500 free queries on sign-up
  5. Direct Google scraping                    — free, local computer only, often blocked
Quotas: see ENGINES (each has the official source and the date it was checked). docs/KNOWN_LIMITATIONS.md.

Verdicts are honest about what each method can prove:
  Search Console answers "indexed / not indexed" for your own sites (the final word).
  A search API can only say "Google search shows / does not show this exact link" — absence is NOT proof.
"""

from __future__ import annotations

import gzip
import io
import json
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from urllib.parse import parse_qs, parse_qsl, quote_plus, unquote, urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from defusedxml import ElementTree
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2 import service_account

    HAS_GOOGLE_AUTH = True
except ImportError:  # pragma: no cover
    HAS_GOOGLE_AUTH = False


# =====================================================================
# VERDICTS
# =====================================================================
class V:
    INDEXED = "🟢 Indexed"
    OTHER = "🟡 Another link shown"
    NOTFOUND = "🟠 Not found on Google"
    NOT = "🔴 Not indexed"
    UNKNOWN = "⚪ Couldn't check"


ALL_VERDICTS = [V.INDEXED, V.OTHER, V.NOTFOUND, V.NOT, V.UNKNOWN]
VERIFIED = {V.INDEXED, V.OTHER, V.NOTFOUND, V.NOT}   # Google answered (everything except "Couldn't check")

# (background, text, border) per verdict — used by the UI and the Excel export
VERDICT_COLORS = {
    V.INDEXED: ("#dcfce7", "#166534", "#86efac"),
    V.OTHER: ("#fef9c3", "#854d0e", "#fde047"),
    V.NOTFOUND: ("#ffedd5", "#9a3412", "#fdba74"),
    V.NOT: ("#fee2e2", "#991b1b", "#fca5a5"),
    V.UNKNOWN: ("#f1f5f9", "#475569", "#cbd5e1"),
}

VERDICT_MEANING = {
    V.INDEXED: "Google has this exact link (Search Console says indexed, or a Google search shows it).",
    V.OTHER: "Google shows a different link (another page, version or capital letters), not this exact one. Usually this one is not indexed.",
    V.NOTFOUND: "A Google search for this exact link showed nothing. Usually it is not indexed, but a search can miss a page: "
                "for your own sites, Search Console is the final word.",
    V.NOT: "Search Console says Google has not indexed this page (your own sites only).",
    V.UNKNOWN: "The check failed (blocked, no credits, network). Never counted as not indexed. Press Re-check.",
}
# short words for cards, filters and exports
VERDICT_SHORT = {V.INDEXED: "Indexed", V.OTHER: "Another link shown", V.NOTFOUND: "Not found on Google",
                 V.NOT: "Not indexed", V.UNKNOWN: "Couldn't check"}


class EngineDown(Exception):
    """This engine can't be used for the rest of the run (no credits, wrong key, blocked)."""


class Skip(Exception):
    """This engine can't check THIS link (e.g. not your Search Console site). Try the next engine."""


# =====================================================================
# ENGINE INFO
# =====================================================================
QUOTA_CHECKED = "21 Oct 2026"   # the date the quotas below were checked against each provider's own page


@dataclass(frozen=True)
class EngineInfo:
    key: str
    name: str
    free: str          # the free allowance, as the provider states it
    kind: str          # daily / monthly / sign-up credit / none
    renew: str         # what the provider says about renewal and expiry (or that it does not say)
    note: str          # what kind of answer it gives and when to use it
    signup: str
    source: str        # the official page the allowance comes from
    proves: str        # what a result from this method can and cannot prove


ENGINES: dict[str, EngineInfo] = {
    "gsc": EngineInfo(
        "gsc", "Google Search Console", "2,000 checks per day for each website (600 per minute)", "Daily allowance",
        "Starts again every day.",
        "Google's own answer: indexed or not, why, and the last crawl date. Only for websites this account can see "
        "in Search Console; other links go to the next method.",
        "https://search.google.com/search-console", "https://developers.google.com/webmaster-tools/limits",
        "The final word for your own sites.",
    ),
    "brightdata": EngineInfo(
        "brightdata", "Bright Data", "5,000 free credits per month (1 check = 1 credit)", "Monthly allowance",
        "Resets on the 1st of each month; unused credits do not roll over. Shared with Bright Data's other products. "
        "Not given on paid pre-commit plans.",
        "Live Google search results. Best free option for backlinks on other people's sites.",
        "https://brightdata.com/products/serp-api", "https://docs.brightdata.com/general/account/billing-and-pricing/free-tier",
        "Shows whether Google search returns this exact link. Not finding it is not proof that it is not indexed.",
    ),
    "serpapi": EngineInfo(
        "serpapi", "SerpApi", "250 searches per month, at most 50 per hour (Free plan)", "Monthly allowance",
        "Listed per month on the pricing page; the page does not state the reset day. The Test button shows the live balance.",
        "Live Google search results (cache turned off, so answers are never old).",
        "https://serpapi.com/users/sign_up", "https://serpapi.com/pricing",
        "Shows whether Google search returns this exact link. Not finding it is not proof that it is not indexed.",
    ),
    "serper": EngineInfo(
        "serper", "Serper", "2,500 free queries when you sign up", "Sign-up credit",
        "serper.dev does not say whether the free queries renew or expire: treat them as one-time.",
        "Live Google search results. Very fast.",
        "https://serper.dev", "https://serper.dev",
        "Shows whether Google search returns this exact link. Not finding it is not proof that it is not indexed.",
    ),
    "direct": EngineInfo(
        "direct", "Direct Google (no key)", "No allowance, no key", "None",
        "Google blocks automated searches quickly (CAPTCHA); on cloud hosting almost at once.",
        "Only on your own computer, as the last backup.",
        "", "",
        "Same as a search API, and often blocked.",
    ),
}
ENGINE_ORDER = list(ENGINES)

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
TRACKING_PARAMS = re.compile(
    r"^(utm_[a-z_]+|gclid|gbraid|wbraid|fbclid|msclkid|yclid|dclid|srsltid|"
    r"mc_cid|mc_eid|_ga|_gl|igshid|ref_src)$",
    re.I,
)


# =====================================================================
# RESULT
# =====================================================================
@dataclass
class CheckResult:
    url: str
    verdict: str
    detail: str
    engine: str = ""
    proof_link: str = ""
    matched_url: str = ""
    serp_title: str = ""
    last_crawl: str = ""
    likely_cause: str = ""
    http_status: str = ""
    robots: str = ""
    page_canonical: str = ""
    final_url: str = ""
    canonical: str = ""
    checked_at: str = ""
    attempts: str = ""


_RESULT_FIELDS = {f.name for f in fields(CheckResult)}


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def unknown(detail: str) -> dict:
    return {"verdict": V.UNKNOWN, "detail": detail}


# =====================================================================
# URL HELPERS
# =====================================================================
def with_scheme(url: str) -> str:
    url = url.strip()
    return url if re.match(r"^https?://", url, re.I) else "https://" + url


def bare(url: str) -> str:
    return re.sub(r"^https?://", "", url.strip(), flags=re.I)


def host_of(url: str) -> str:
    try:
        h = (urlparse(with_scheme(url)).hostname or "").lower()
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


def canonical_url(url: str, case_sensitive_path: bool = True) -> str:
    """
    Comparable identity of a URL:
      - scheme, www., default port and #fragment removed
      - host lower-cased; path decoded (%40 -> @), // collapsed, trailing / removed
      - tracking params (utm_*, gclid, srsltid...) removed; real params KEPT and sorted
      - path letter-case kept by default (Google treats /Page and /page as different links)
    """
    if not url or not url.strip():
        return ""
    try:
        p = urlparse(with_scheme(url))
        port = p.port
    except ValueError:
        return url.strip().lower()
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if port and port not in (80, 443):
        host = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", unquote(p.path)).rstrip("/")
    if not case_sensitive_path:
        path = path.lower()
    params = sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not TRACKING_PARAMS.match(k))
    return f"{host}{path}" + ("?" + urlencode(params) if params else "")


def is_valid_url(url: str) -> bool:
    h = host_of(url)
    return bool(h) and "." in h and " " not in url.strip()


_HOST_OK = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$", re.I)


def _looks_like_link(tok: str) -> bool:
    t = tok.strip().strip("\"'<>,;")
    if re.match(r"^(https?://|www\.)", t, re.I):
        return True
    return bool(_HOST_OK.match(host_of(t) or "")) and " " not in t


def split_input(text: str) -> list[str]:
    """Pasted text -> entries. One link per line; several links on one line (spaces, tabs, or a comma / semicolon right
    before the next link) give each link. Commas INSIDE a link are kept (…/Washington,_D.C. or ?ids=1,2).
    A line without any link stays ONE entry, so it is reported once as "not a link" (not word by word)."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        toks = []
        for t in line.split():
            toks += [x for x in re.split(r"[,;](?=\s*(?:https?://|www\.))", t) if x]
        links = [t.strip().strip("\"'<>,;") for t in toks if _looks_like_link(t)]
        out.extend(links if links else [line])
    return out


def prepare_urls(raw: list[str], strict_case: bool = True):
    """Clean, validate and remove duplicates. Returns (valid, invalid, duplicate_count)."""
    valid, invalid, seen, dupes = [], [], set(), 0
    for u in raw:
        u = u.strip().strip("\"'<>,;")
        if not u or u.startswith("#"):
            continue
        if not is_valid_url(u):
            invalid.append(u)
            continue
        key = canonical_url(u, strict_case)
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        valid.append(u)
    return valid, invalid, dupes


def google_proof_link(url: str) -> str:
    """A Google search anyone can open to see the evidence themselves."""
    return f"https://www.google.com/search?q={quote_plus('site:' + bare(url))}&pws=0"


# =====================================================================
# HTTP (one session per thread, retries on 5xx)
# =====================================================================
_local = threading.local()


def http() -> requests.Session:
    if not hasattr(_local, "session"):
        s = requests.Session()
        retry = Retry(total=2, connect=2, read=2, backoff_factor=1.0,
                      status_forcelist=(500, 502, 503, 504), allowed_methods=None)
        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        _local.session = s
    return _local.session


def _json(r) -> dict:
    try:
        data = r.json()
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


# =====================================================================
# SITEMAP
# =====================================================================
def _tag(el) -> str:
    return el.tag.rsplit("}", 1)[-1].lower() if isinstance(el.tag, str) else ""


def fetch_sitemap(url: str, max_urls: int = 5000, max_depth: int = 3):
    """Handles sitemap indexes, .xml.gz and missing namespaces; ignores image/video locs."""
    urls, errors, seen = [], [], set()

    def walk(sm_url: str, depth: int):
        if sm_url in seen or depth > max_depth or len(urls) >= max_urls:
            return
        seen.add(sm_url)
        try:
            r = http().get(sm_url, headers={"User-Agent": BROWSER_UA}, timeout=20)
            r.raise_for_status()
            content = r.content
            if content[:2] == b"\x1f\x8b":
                content = gzip.decompress(content)
            root = ElementTree.fromstring(content)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{sm_url} → {e.__class__.__name__}: {str(e)[:120]}")
            return
        if _tag(root) == "sitemapindex":
            for child in root:
                if _tag(child) == "sitemap":
                    for g in child:
                        if _tag(g) == "loc" and g.text:
                            walk(g.text.strip(), depth + 1)
        else:
            for child in root:
                if _tag(child) == "url":
                    for g in child:
                        if _tag(g) == "loc" and g.text:
                            urls.append(g.text.strip())
                            break
                if len(urls) >= max_urls:
                    break

    walk(url.strip(), 0)
    return urls, errors


# =====================================================================
# SERP JUDGEMENT (shared by every search-based engine)
# =====================================================================
def judge(target_url: str, items: list[tuple[str, str]], strict_case: bool = True) -> dict:
    """items = [(link, title), ...] that Google returned for `site:<target>`."""
    target = canonical_url(target_url, strict_case)
    for link, title in items:
        if canonical_url(link, strict_case) == target:
            return {"verdict": V.INDEXED, "detail": "Google has this exact link", "matched_url": link, "serp_title": title}

    if not items:
        return {"verdict": V.NOTFOUND, "detail": "A Google search for this exact link showed no results"}

    loose = canonical_url(target_url, False)
    for link, title in items:
        if canonical_url(link, False) == loose:
            return {"verdict": V.OTHER, "detail": "Google has this link with different capital letters, not this exact one",
                    "matched_url": link, "serp_title": title}

    th = host_of(target_url)
    same_site = [(l, t) for l, t in items if host_of(l) == th]
    if same_site:
        link, title = same_site[0]
        return {"verdict": V.OTHER, "detail": f"Google shows {len(items)} other page(s) from this site, but not this exact link",
                "matched_url": link, "serp_title": title}
    link, title = items[0]
    return {"verdict": V.OTHER, "detail": "Google only shows other websites for this link", "matched_url": link, "serp_title": title}


def parse_google_html(html: str):
    """A Google results page (HTML) -> (kind, items). kind: results / no_results / blocked / unreadable."""
    low = (html or "").lower()
    if "did not match any documents" in low or "no results found for" in low or "کسی دستاویز سے مماثلت نہیں رکھتی" in (html or ""):
        return "no_results", []
    soup = BeautifulSoup(html or "", "html.parser")
    items, seen = [], set()
    for a in soup.find_all("a", href=True):
        href, dest = a["href"], ""
        if href.startswith("/url?"):
            qs = parse_qs(urlparse(href).query)
            dest = (qs.get("q") or qs.get("url") or [""])[0]
        elif href.startswith("http"):
            dest = href
        if not dest.startswith("http") or dest in seen or _is_google_host((urlparse(dest).hostname or "").lower()):
            continue
        seen.add(dest)
        h3 = a.find("h3")
        items.append((dest, h3.get_text(" ", strip=True) if h3 else ""))
    if items:
        return "results", items
    # a real CAPTCHA page (only when nothing could be read: the query itself can contain words like "recaptcha")
    if any(m in low for m in ('action="/sorry/index"', "id=\"captcha-form\"", "g-recaptcha", "our systems have detected unusual traffic")):
        return "blocked", []
    # No "0 results" message AND no links = a JS wall or a new layout. Saying "not found" would be a lie.
    return "unreadable", []


def _google_search_url(url: str, extra: str = "") -> str:
    return f"https://www.google.com/search?q={quote_plus('site:' + bare(url))}&hl=en&gl=us&num=10&pws=0{extra}"


# =====================================================================
# ENGINE: SERPER
# =====================================================================
def check_serper(url: str, cfg: dict, strict: bool) -> dict:
    try:
        r = http().post(
            "https://google.serper.dev/search",
            json={"q": f"site:{bare(url)}", "num": 10, "gl": "us", "hl": "en"},
            headers={"X-API-KEY": cfg["key"], "Content-Type": "application/json"},
            timeout=30,
        )
    except requests.RequestException as e:
        return unknown(f"Serper: network problem ({e.__class__.__name__})")
    body = r.text[:400].lower()
    if r.status_code >= 400 and "credit" in body:
        raise EngineDown("Free credits are used up")
    if r.status_code in (401, 403):
        raise EngineDown("API key is wrong")
    if r.status_code == 429:
        raise EngineDown("Too many requests — lower the speed")
    if r.status_code != 200:
        return unknown(f"Serper: error {r.status_code}")
    data = _json(r)
    if not data:
        return unknown("Serper: unreadable reply")
    items = [(o.get("link", ""), o.get("title", "")) for o in data.get("organic", []) if o.get("link")]
    return judge(url, items, strict)


# =====================================================================
# ENGINE: SERPAPI
# =====================================================================
def serpapi_account(key: str) -> dict:
    """Free call — does not use a search credit."""
    r = http().get("https://serpapi.com/account.json", params={"api_key": key}, timeout=20)
    if r.status_code == 401:
        raise EngineDown("API key is wrong")
    r.raise_for_status()
    return _json(r)


def check_serpapi(url: str, cfg: dict, strict: bool) -> dict:
    params = {
        "engine": "google", "q": f"site:{bare(url)}", "api_key": cfg["key"],
        "hl": "en", "gl": "us", "num": 10,
        "no_cache": "true",  # always ask Google fresh — never a stored (old) answer
    }
    try:
        r = http().get("https://serpapi.com/search.json", params=params, timeout=60)
    except requests.RequestException as e:
        return unknown(f"SerpApi: network problem ({e.__class__.__name__})")
    data = _json(r)
    err = str(data.get("error", ""))
    if r.status_code == 401:
        raise EngineDown("API key is wrong")
    if r.status_code == 429:
        if "run out" in err.lower():
            raise EngineDown("Free searches used up for this month")
        raise EngineDown("Hourly limit reached — try again later")
    if "hasn't returned any results" in err.lower():
        return judge(url, [], strict)
    if err:
        return unknown(f"SerpApi: {err[:90]}")
    if r.status_code != 200 or not data:
        return unknown(f"SerpApi: error {r.status_code}")
    items = [(o.get("link", ""), o.get("title", "")) for o in data.get("organic_results", []) if o.get("link")]
    return judge(url, items, strict)


# =====================================================================
# ENGINE: BRIGHT DATA
# =====================================================================
def _brightdata_read(r):
    """A Bright Data reply -> ("items", [...]) / ("none", []) / ("blocked", why) / ("other", what it was).
    Handles parsed JSON (brd_json=1), JSON wrapped in {"body": ...}, and plain Google HTML."""
    data = _json(r)
    body = data.get("body") if isinstance(data.get("body"), str) else None
    if body is not None:                                   # some zones wrap the page: {"status_code":..,"body":"..."}
        try:
            data = json.loads(body)
            data = data if isinstance(data, dict) else {}
        except ValueError:
            data, text = {}, body
        else:
            text = ""
    else:
        text = "" if data else (r.text or "")
    if data and ({"organic", "general", "input"} & set(data)):
        items = [((o.get("link") or o.get("url") or ""), o.get("title", "")) for o in (data.get("organic") or []) if isinstance(o, dict)]
        items = [(l, t) for l, t in items if l]
        if items:
            return "items", items
        # "nothing found" only when the reply says so: an empty organic list, or Google's own count of 0
        gen = data.get("general") if isinstance(data.get("general"), dict) else {}
        if isinstance(data.get("organic"), list) or gen.get("results_cnt") in (0, "0"):
            return "none", []
        return "other", "search data without results (maybe a consent or CAPTCHA page)"
    if data:
        err = data.get("error") or data.get("message") or ""
        return "other", (f"an error: {str(err)[:80]}" if err else "JSON without search results (keys: " + ", ".join(list(data)[:5]) + ")")
    if text.strip():
        kind, items = parse_google_html(text)
        if kind == "results":
            return "items", items
        if kind == "no_results":
            return "none", []
        if kind == "blocked":
            return "blocked", "Google showed a CAPTCHA page"
        return "other", "a web page without readable results"
    return "other", "an empty reply"


def check_brightdata(url: str, cfg: dict, strict: bool) -> dict:
    payload = {"zone": cfg["zone"], "url": _google_search_url(url, "&brd_json=1"), "format": "raw"}
    headers = {"Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json"}
    what = ""
    for attempt in range(2):                               # one more try: Bright Data sometimes returns a non-search reply
        try:
            r = http().post("https://api.brightdata.com/request", json=payload, headers=headers, timeout=90)
        except requests.RequestException as e:
            if attempt == 0:
                continue
            return unknown(f"Bright Data: network problem ({e.__class__.__name__})")
        body = r.text[:500].lower()
        if r.status_code == 429 and attempt == 0:
            time.sleep(3)
            continue
        if r.status_code in (401, 403) and any(w in body for w in ("balance", "credit", "quota", "limit")):
            raise EngineDown("Free credits are used up for this month")
        if r.status_code in (401, 403):
            raise EngineDown("API key or zone name is wrong")
        if r.status_code == 402 or (r.status_code >= 400 and any(w in body for w in ("balance", "credit", "quota"))):
            raise EngineDown("Free credits are used up for this month")
        if r.status_code == 429:
            raise EngineDown("Too many requests — lower the speed")
        if r.status_code != 200:
            what = f"error {r.status_code}"
            continue
        kind, val = _brightdata_read(r)
        if kind == "items":
            return judge(url, val, strict)
        if kind == "none":
            return judge(url, [], strict)
        what = val
    if what.startswith("JSON without") or what.startswith("a web page"):
        what += " — is the zone a SERP API zone?"
    return unknown(f"Bright Data: the reply was {what} (tried twice)" if not what.startswith("error") else f"Bright Data: {what} (tried twice)")


# =====================================================================
# ENGINE: DIRECT GOOGLE (local use only)
# =====================================================================
_direct_lock = threading.Lock()
_direct_last = [0.0]


def _is_google_host(h: str) -> bool:
    """google.com, www.google.co.uk, maps.google.de … (a whole label "google"), not lovegoogle.com."""
    return bool(re.search(r"(^|\.)google\.[a-z]{2,3}(\.[a-z]{2})?$", h)) or h.endswith(("gstatic.com", "googleusercontent.com", "googleadservices.com"))


def check_direct(url: str, cfg: dict, strict: bool) -> dict:
    delay = float(cfg.get("delay", 5.0))
    with _direct_lock:  # one request at a time, with a pause, even if many workers run
        wait = delay - (time.time() - _direct_last[0])
        if wait > 0:
            time.sleep(wait + random.uniform(0, 1.2))
        try:
            r = http().get(
                _google_search_url(url, "&gbv=1"),
                headers={"User-Agent": BROWSER_UA, "Accept": "text/html", "Accept-Language": "en-US,en;q=0.9"},
                timeout=15,
            )
        except requests.RequestException as e:
            return unknown(f"Direct Google: network problem ({e.__class__.__name__})")
        finally:
            _direct_last[0] = time.time()

    low = r.text.lower()
    if r.status_code in (403, 429) or "/sorry/" in r.url or "unusual traffic" in low:
        raise EngineDown("Google blocked this computer (CAPTCHA)")
    if "consent.google" in r.url:
        return unknown("Direct Google: showed a cookie-consent page")
    kind, items = parse_google_html(r.text)
    if kind == "blocked" or (kind != "results" and "/sorry/" in r.url):
        raise EngineDown("Google blocked this computer (CAPTCHA)")
    if kind == "no_results":
        return judge(url, [], strict)
    if kind == "unreadable":
        return unknown("Direct Google: page had no readable results")
    return judge(url, items, strict)


# =====================================================================
# ENGINE: GOOGLE SEARCH CONSOLE (URL Inspection API)
# =====================================================================
GSC_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
GSC_INSPECT = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
GSC_SITES = "https://www.googleapis.com/webmasters/v3/sites"


class GSCClient:
    """Logs in with a service-account JSON key. Add its email as a user in Search Console."""

    def __init__(self, info: dict):
        if not HAS_GOOGLE_AUTH:
            raise RuntimeError("Package 'google-auth' is not installed")
        if not info.get("client_email") or not info.get("private_key"):
            raise ValueError("This is not a service-account JSON key")
        self.email = info["client_email"]
        self._creds = service_account.Credentials.from_service_account_info(info, scopes=GSC_SCOPES)
        self._lock = threading.Lock()
        self.sites: list[str] | None = None
        self.exhausted: set[str] = set()

    def token(self) -> str:
        with self._lock:
            if not self._creds.valid:
                try:
                    self._creds.refresh(GoogleAuthRequest())
                except Exception as e:  # noqa: BLE001
                    raise EngineDown(f"Google login failed ({e.__class__.__name__}) — check the JSON key") from e
            return self._creds.token

    def list_sites(self) -> list[str]:
        r = http().get(GSC_SITES, headers={"Authorization": f"Bearer {self.token()}"}, timeout=30)
        if r.status_code in (401, 403):
            raise EngineDown("Search Console API is not enabled, or the key is wrong")
        r.raise_for_status()
        self.sites = [s["siteUrl"] for s in _json(r).get("siteEntry", [])
                      if s.get("permissionLevel") != "siteUnverifiedUser" and s.get("siteUrl")]
        return self.sites

    def property_for(self, url: str) -> str | None:
        u = with_scheme(url)
        host = (urlparse(u).hostname or "").lower()
        probe = u.lower().rstrip("/") + "/"
        best = None
        for s in self.sites or []:
            if s.startswith("sc-domain:"):
                d = s[len("sc-domain:"):].lower()
                if (host == d or host.endswith("." + d)) and best is None:
                    best = s
            elif probe.startswith(s.lower()):
                if best is None or best.startswith("sc-domain:") or len(s) > len(best):
                    best = s
        return best


def _fmt_crawl(ts: str) -> str:
    if not ts:
        return "Never crawled"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return ts
    days = (datetime.now(timezone.utc) - dt).days
    ago = "today" if days <= 0 else ("1 day ago" if days == 1 else f"{days} days ago")
    return f"{dt.strftime('%Y-%m-%d %H:%M')} UTC ({ago})"


def _gsc_cause(idx: dict) -> str:
    hints = []
    if idx.get("robotsTxtState") == "DISALLOWED":
        hints.append("Blocked by robots.txt")
    if str(idx.get("indexingState", "")).startswith("BLOCKED"):
        hints.append("Page has a noindex tag")
    pfs = idx.get("pageFetchState", "")
    if pfs and pfs not in ("SUCCESSFUL", "PAGE_FETCH_STATE_UNSPECIFIED"):
        hints.append("Google couldn't load the page: " + pfs.replace("_", " ").lower())
    if not idx.get("lastCrawlTime"):
        hints.append("Google has never crawled this page")
    return " · ".join(hints)


def check_gsc(url: str, client: GSCClient, strict: bool) -> dict:
    prop = client.property_for(url)
    if not prop:
        raise Skip("not one of your Search Console sites")
    if prop in client.exhausted:
        raise Skip("today's 2,000 limit is used for this site")
    try:
        r = http().post(
            GSC_INSPECT,
            json={"inspectionUrl": with_scheme(url), "siteUrl": prop, "languageCode": "en-US"},
            headers={"Authorization": f"Bearer {client.token()}"},
            timeout=60,
        )
    except requests.RequestException as e:
        return unknown(f"Search Console: network problem ({e.__class__.__name__})")
    if r.status_code == 429:
        client.exhausted.add(prop)
        raise Skip("today's 2,000 limit is used for this site")
    if r.status_code == 401:
        raise EngineDown("Google login failed — check the JSON key")
    if r.status_code == 403:
        raise Skip("the service account has no access to this site")
    if r.status_code != 200:
        msg = _json(r).get("error", {}).get("message", "") if _json(r) else ""
        return unknown(f"Search Console: error {r.status_code} {msg[:60]}".strip())

    res = _json(r).get("inspectionResult", {})
    idx = res.get("indexStatusResult", {})
    if not idx:                                   # an empty reply is not "not indexed"
        return unknown("Search Console: the reply had no index status")
    cs = idx.get("coverageState") or "Unknown status"
    cs_l = cs.lower()
    gc = idx.get("googleCanonical", "")
    out = {
        "proof_link": res.get("inspectionResultLink", ""),
        "last_crawl": _fmt_crawl(idx.get("lastCrawlTime", "")),
        "page_canonical": idx.get("userCanonical", ""),
        "robots": " / ".join(x for x in (idx.get("robotsTxtState", ""), idx.get("indexingState", "")) if x),
        "http_status": idx.get("pageFetchState", ""),
    }
    indexed = idx.get("verdict") == "PASS" or ("indexed" in cs_l and "not indexed" not in cs_l)
    if indexed:
        out.update(verdict=V.INDEXED, detail=f"Search Console: {cs}")
    elif gc and canonical_url(gc, strict) != canonical_url(url, strict):
        out.update(verdict=V.OTHER, detail=f"Search Console: {cs} — Google picked another link", matched_url=gc)
        out["likely_cause"] = "Google treats another link as the main version"
    else:
        out.update(verdict=V.NOT, detail=f"Search Console: {cs}")
        out["likely_cause"] = _gsc_cause(idx) or "Google knows the page but hasn't indexed it yet"
    return out


ENGINE_FUNCS = {
    "gsc": check_gsc,
    "brightdata": check_brightdata,
    "serpapi": check_serpapi,
    "serper": check_serper,
    "direct": check_direct,
}


# =====================================================================
# PAGE DIAGNOSTICS (why isn't it indexed?)
# =====================================================================
def page_diagnostics(res: CheckResult) -> None:
    try:
        r = http().get(with_scheme(res.url), headers={"User-Agent": BROWSER_UA}, timeout=15, allow_redirects=True)
    except requests.RequestException as e:
        res.http_status = f"Could not open ({e.__class__.__name__})"
        res.likely_cause = "The page could not be opened"
        return
    res.http_status = " → ".join([str(h.status_code) for h in r.history] + [str(r.status_code)])
    if r.history:
        res.final_url = r.url
    robots = [r.headers.get("X-Robots-Tag", "")]
    if "html" in r.headers.get("Content-Type", "").lower():
        soup = BeautifulSoup(r.text[:600_000], "html.parser")
        for m in soup.find_all("meta", attrs={"name": re.compile(r"^(robots|googlebot)$", re.I)}):
            robots.append(m.get("content", ""))
        link = soup.find("link", rel="canonical")
        if link and link.get("href"):
            res.page_canonical = urljoin(r.url, link["href"].strip())
    res.robots = ", ".join(x for x in robots if x)

    hints = []
    if "noindex" in res.robots.lower():
        hints.append("Page has a noindex tag")
    if r.status_code >= 400:
        hints.append(f"Page returns error {r.status_code}")
    if res.final_url and canonical_url(res.final_url) != canonical_url(res.url):
        hints.append("Page redirects to another link")
    if res.page_canonical and canonical_url(res.page_canonical) != canonical_url(res.final_url or res.url):
        hints.append("Page's canonical points to another link")
    res.likely_cause = " · ".join(hints) if hints else "Page looks OK — Google probably hasn't indexed it yet"


# =====================================================================
# RUNNER WITH AUTOMATIC FALLBACK
# =====================================================================
class RunState:
    """Shared between worker threads: which engines are stopped and how many checks each did."""

    def __init__(self, engines: list[str]):
        self.engines = engines
        self.dead: dict[str, str] = {}
        self.used: dict[str, int] = {e: 0 for e in engines}       # calls made (credits spent)
        self.answered: dict[str, int] = {e: 0 for e in engines}   # calls that gave a clear answer (proves it works)
        self._lock = threading.Lock()

    def is_dead(self, e: str) -> bool:
        with self._lock:
            return e in self.dead

    def kill(self, e: str, reason: str) -> None:
        with self._lock:
            self.dead.setdefault(e, reason)

    def count(self, e: str, answered: bool = True) -> None:
        with self._lock:
            self.used[e] += 1
            if answered:
                self.answered[e] += 1


def check_one(url: str, state: RunState, cfgs: dict, strict: bool = True, diagnose: bool = True) -> CheckResult:
    attempts: list[str] = []
    chosen = None
    for e in state.engines:
        if state.is_dead(e):
            continue
        name = ENGINES[e].name
        try:
            out = ENGINE_FUNCS[e](url, cfgs.get(e), strict)
        except Skip as s:
            attempts.append(f"{name}: skipped — {s}")
            continue
        except EngineDown as d:
            state.kill(e, str(d))
            attempts.append(f"{name}: stopped — {d}")
            continue
        except Exception as ex:  # noqa: BLE001
            out = unknown(f"{name}: unexpected error ({ex.__class__.__name__})")
        state.count(e, out["verdict"] != V.UNKNOWN)
        if out["verdict"] == V.UNKNOWN:
            attempts.append(out["detail"])
            continue  # try the next engine instead of giving up
        chosen = (e, out)
        break

    if chosen:
        e, out = chosen
        res = CheckResult(url=url, engine=ENGINES[e].name, **{k: v for k, v in out.items() if k in _RESULT_FIELDS})
    else:
        reason = attempts[-1] if attempts else "No checking method is turned on"
        res = CheckResult(url=url, verdict=V.UNKNOWN, detail=reason)

    res.canonical = canonical_url(url, strict)
    res.checked_at = now_utc()
    res.attempts = " | ".join(attempts)
    if not res.proof_link:
        res.proof_link = google_proof_link(url)
    if diagnose and res.verdict in (V.NOTFOUND, V.OTHER) and not (chosen and chosen[0] == "gsc"):
        page_diagnostics(res)
    return res


def run_checks(urls, engines, cfgs, strict=True, diagnose=True, workers=5, on_progress=None, on_result=None):
    """Checks every URL live. Returns (results in input order, RunState).
    on_result(url, result) is called as each link finishes, so a run that is stopped half-way keeps what it has."""
    state = RunState(engines)
    results: dict[str, CheckResult] = {}
    ex = ThreadPoolExecutor(max_workers=max(1, int(workers)))
    try:
        futures = {ex.submit(check_one, u, state, cfgs, strict, diagnose): u for u in urls}
        for i, f in enumerate(as_completed(futures), start=1):
            u = futures[f]
            try:
                results[u] = f.result()
            except Exception as e:  # noqa: BLE001
                results[u] = CheckResult(url=u, verdict=V.UNKNOWN, detail=f"Internal error ({e.__class__.__name__})",
                                         checked_at=now_utc(), proof_link=google_proof_link(u))
            if on_result:
                on_result(u, results[u])
            if on_progress:
                on_progress(i, len(urls), u, state)
    except BaseException:
        # stopped (Streamlit stops a run by raising inside on_progress): cancel the links not started yet, so no more
        # credits are spent and the page does not wait for the whole list
        ex.shutdown(wait=False, cancel_futures=True)
        raise
    ex.shutdown(wait=True)
    return [results[u] for u in urls], state


# =====================================================================
# EXPORTS (CSV / tab text / Excel)
# =====================================================================
_FORMULA = re.compile(r"^[=+\-@\t\r]")


def cell_safe(v) -> str:
    """A cell starting with = + - @ would run as a formula in Excel / Google Sheets: keep it text (leading ')."""
    s = "" if v is None else str(v)
    return "'" + s if _FORMULA.match(s) and not re.match(r"^[+-]?[\d\s().,-]+$", s) else s


def _safe_df(df):
    return df.astype(str).replace({"nan": "", "None": ""}).apply(lambda col: col.map(cell_safe))


def to_csv(df) -> bytes:
    """UTF-8 with BOM (Excel opens accents and emoji correctly); commas, quotes and line breaks are quoted."""
    return _safe_df(df).to_csv(index=False).encode("utf-8-sig")


def to_tsv(df) -> str:
    """Tab-separated text for pasting into Google Sheets (tabs / line breaks inside a cell become spaces)."""
    return _safe_df(df).replace(r"[\t\r\n]+", " ", regex=True).to_csv(sep="\t", index=False)



def to_excel(df, summary: dict, verdict_col: str = "Result") -> bytes:
    import pandas as pd
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    from openpyxl.styles import Alignment, Font, PatternFill

    # control characters (they can come from page titles or meta tags) are not allowed in .xlsx: drop them
    df = df.apply(lambda col: col.map(lambda v: ILLEGAL_CHARACTERS_RE.sub("", v) if isinstance(v, str) else v))
    summary = {k: ILLEGAL_CHARACTERS_RE.sub("", v) if isinstance(v, str) else v for k, v in summary.items()}
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Index Check")
        pd.DataFrame(list(summary.items()), columns=["Item", "Value"]).to_excel(w, index=False, sheet_name="Summary")
        for name in ("Index Check", "Summary"):
            ws = w.sheets[name]
            for c in ws[1]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = PatternFill("solid", fgColor="1E1B4B")
                c.alignment = Alignment(vertical="center")
            ws.freeze_panes = "A2"
            for col in ws.columns:
                width = max((len(str(c.value)) if c.value is not None else 0) for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 60)
        ws = w.sheets["Index Check"]
        ws.auto_filter.ref = ws.dimensions
        for row in ws.iter_rows(min_row=2):          # text that starts with "=" must stay text, never a formula
            for c in row:
                if c.data_type == "f":
                    c.data_type = "s"
        if verdict_col in df.columns:
            vcol = df.columns.get_loc(verdict_col) + 1
            for row in ws.iter_rows(min_row=2, min_col=vcol, max_col=vcol):
                for c in row:
                    colors = VERDICT_COLORS.get(c.value)
                    if colors:
                        c.fill = PatternFill("solid", fgColor=colors[0].lstrip("#"))
                        c.font = Font(bold=True, color=colors[1].lstrip("#"))
    return buf.getvalue()
