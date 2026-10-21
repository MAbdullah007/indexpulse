"""
Run:  pytest -q
These tests use fake API replies, so they cost no credits and need no internet.
"""

import gzip
import time as time_mod
import json
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core  # noqa: E402
from core import V  # noqa: E402

TARGET = "https://velog.io/@stories/How-to-Choose"


# ---------------------------------------------------------------- fakes
class FakeResp:
    def __init__(self, status=200, data=None, text=None, url="https://x.test/", headers=None, content=None, history=None):
        self.status_code = status
        self._data = data
        self.text = text if text is not None else (json.dumps(data) if data is not None else "")
        self.url = url
        self.headers = headers or {}
        self.content = content if content is not None else self.text.encode()
        self.history = history or []

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return self.handler("GET", url, kw)

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return self.handler("POST", url, kw)


@pytest.fixture
def fake(monkeypatch):
    def install(handler):
        s = FakeSession(handler)
        monkeypatch.setattr(core, "http", lambda: s)
        return s
    return install


# ---------------------------------------------------------------- URL matching
def test_canonical_rules():
    c = core.canonical_url
    assert c("https://www.Example.com/A//b/?utm_source=x&id=2#top") == "example.com/A/b?id=2"
    assert c("example.com/a/") == c("http://www.example.com/a")
    assert c("site.com/p?id=1") != c("site.com/p?id=2")
    assert c("https://velog.io/%40stories/X") == "velog.io/@stories/X"
    assert c("https://a.com/x?srsltid=abc") == "a.com/x"


def test_judge_cases():
    assert core.judge(TARGET, [(TARGET + "/?srsltid=1", "t")])["verdict"] == V.INDEXED
    assert core.judge(TARGET, [(TARGET.lower(), "t")])["verdict"] == V.OTHER
    assert core.judge(TARGET, [("https://velog.io/@stories", "t")])["verdict"] == V.OTHER
    assert core.judge(TARGET, [])["verdict"] == V.NOTFOUND   # a search can only say "not found"


def test_prepare_urls():
    valid, invalid, dupes = core.prepare_urls(["a.com/x", "https://www.a.com/x/", "nonsense", "", "# comment"])
    assert valid == ["a.com/x"] and invalid == ["nonsense"] and dupes == 1


# ---------------------------------------------------------------- engines
def test_serper_indexed_and_errors(fake):
    fake(lambda m, u, kw: FakeResp(200, {"organic": [{"link": TARGET, "title": "T"}]}))
    assert core.check_serper(TARGET, {"key": "k"}, True)["verdict"] == V.INDEXED

    fake(lambda m, u, kw: FakeResp(403, {"message": "Unauthorized"}))
    with pytest.raises(core.EngineDown, match="key"):
        core.check_serper(TARGET, {"key": "k"}, True)

    fake(lambda m, u, kw: FakeResp(400, {"message": "Not enough credits"}))
    with pytest.raises(core.EngineDown, match="credits"):
        core.check_serper(TARGET, {"key": "k"}, True)


def test_serpapi_no_cache_and_states(fake):
    s = fake(lambda m, u, kw: FakeResp(200, {"organic_results": [{"link": TARGET, "title": "T"}]}))
    assert core.check_serpapi(TARGET, {"key": "k"}, True)["verdict"] == V.INDEXED
    assert s.calls[0][2]["params"]["no_cache"] == "true"  # fresh results, never cached

    fake(lambda m, u, kw: FakeResp(200, {"error": "Google hasn't returned any results for this query."}))
    assert core.check_serpapi(TARGET, {"key": "k"}, True)["verdict"] == V.NOTFOUND

    fake(lambda m, u, kw: FakeResp(429, {"error": "Your account has run out of searches."}))
    with pytest.raises(core.EngineDown, match="used up"):
        core.check_serpapi(TARGET, {"key": "k"}, True)

    fake(lambda m, u, kw: FakeResp(401, {"error": "Invalid API key."}))
    with pytest.raises(core.EngineDown, match="wrong"):
        core.check_serpapi(TARGET, {"key": "k"}, True)


def test_brightdata(fake):
    s = fake(lambda m, u, kw: FakeResp(200, {"general": {}, "organic": [{"link": TARGET, "title": "T"}]}))
    assert core.check_brightdata(TARGET, {"key": "k", "zone": "z"}, True)["verdict"] == V.INDEXED
    sent = s.calls[0][2]["json"]
    assert sent["zone"] == "z" and "brd_json=1" in sent["url"] and "site%3A" in sent["url"]

    fake(lambda m, u, kw: FakeResp(200, {"general": {"results_cnt": 0}}))
    assert core.check_brightdata(TARGET, {"key": "k", "zone": "z"}, True)["verdict"] == V.NOTFOUND

    fake(lambda m, u, kw: FakeResp(200, text="<html>not json</html>"))
    assert core.check_brightdata(TARGET, {"key": "k", "zone": "z"}, True)["verdict"] == V.UNKNOWN

    fake(lambda m, u, kw: FakeResp(401, text="Invalid token"))
    with pytest.raises(core.EngineDown, match="wrong"):
        core.check_brightdata(TARGET, {"key": "k", "zone": "z"}, True)


def test_direct_block_and_js_wall(fake):
    fake(lambda m, u, kw: FakeResp(429, text="unusual traffic", url="https://www.google.com/sorry/index"))
    with pytest.raises(core.EngineDown):
        core.check_direct(TARGET, {"delay": 0}, True)

    fake(lambda m, u, kw: FakeResp(200, text="<html><noscript>enable js</noscript></html>"))
    assert core.check_direct(TARGET, {"delay": 0}, True)["verdict"] == V.UNKNOWN  # never a fake "Not indexed"

    html = f'<a href="/url?q={TARGET}&sa=U"><h3>Title</h3></a><a href="https://support.google.com/x">help</a>'
    fake(lambda m, u, kw: FakeResp(200, text=html))
    assert core.check_direct(TARGET, {"delay": 0}, True)["verdict"] == V.INDEXED


# ---------------------------------------------------------------- Search Console
class FakeGSC(core.GSCClient):
    def __init__(self, sites):
        self.email = "bot@proj.iam.gserviceaccount.com"
        self.sites = sites
        self.exhausted = set()

    def token(self):
        return "tok"


def test_gsc_property_matching():
    c = FakeGSC(["sc-domain:example.com", "https://shop.other.com/"])
    assert c.property_for("https://www.example.com/page") == "sc-domain:example.com"
    assert c.property_for("https://shop.other.com/p/1") == "https://shop.other.com/"
    assert c.property_for("https://other.com/") is None
    assert c.property_for(TARGET) is None


def _gsc_reply(coverage, verdict="NEUTRAL", **extra):
    idx = {"verdict": verdict, "coverageState": coverage, **extra}
    return FakeResp(200, {"inspectionResult": {"indexStatusResult": idx, "inspectionResultLink": "https://sc/link"}})


def test_gsc_verdicts(fake):
    c = FakeGSC(["sc-domain:example.com"])
    url = "https://example.com/a"

    fake(lambda m, u, kw: _gsc_reply("Submitted and indexed", "PASS", lastCrawlTime="2026-10-18T10:00:00Z"))
    out = core.check_gsc(url, c, True)
    assert out["verdict"] == V.INDEXED and out["proof_link"] == "https://sc/link" and "2026-10-18" in out["last_crawl"]

    fake(lambda m, u, kw: _gsc_reply("Crawled - currently not indexed", lastCrawlTime="2026-10-01T10:00:00Z"))
    assert core.check_gsc(url, c, True)["verdict"] == V.NOT

    fake(lambda m, u, kw: _gsc_reply("URL is unknown to Google"))
    out = core.check_gsc(url, c, True)
    assert out["verdict"] == V.NOT and "never crawled" in out["likely_cause"]

    fake(lambda m, u, kw: _gsc_reply("Duplicate, Google chose different canonical than user",
                                     googleCanonical="https://example.com/b"))
    assert core.check_gsc(url, c, True)["verdict"] == V.OTHER

    fake(lambda m, u, kw: FakeResp(429, {"error": {"message": "Quota exceeded"}}))
    with pytest.raises(core.Skip):
        core.check_gsc(url, c, True)
    assert "sc-domain:example.com" in c.exhausted

    with pytest.raises(core.Skip):
        core.check_gsc(TARGET, c, True)  # not your site → next engine


# ---------------------------------------------------------------- fallback
def test_fallback_when_engine_runs_out(fake):
    def handler(m, u, kw):
        if "serpapi.com" in u:
            return FakeResp(429, {"error": "Your account has run out of searches."})
        if "serper.dev" in u:
            return FakeResp(200, {"organic": [{"link": TARGET, "title": "T"}]})
        return FakeResp(200, text="<html></html>", headers={"Content-Type": "text/html"})

    fake(handler)
    cfgs = {"serpapi": {"key": "a"}, "serper": {"key": "b"}}
    results, state = core.run_checks([TARGET, TARGET + "-2"], ["serpapi", "serper"], cfgs, diagnose=False, workers=1)
    assert "serpapi" in state.dead
    assert results[0].verdict == V.INDEXED and results[0].engine == "Serper"
    assert results[1].verdict == V.OTHER  # Serper showed a different link
    assert state.used["serper"] == 2


def test_gsc_first_then_serp(fake):
    def handler(m, u, kw):
        if "searchconsole" in u:
            return _gsc_reply("Submitted and indexed", "PASS")
        return FakeResp(200, {"organic": []})

    fake(handler)
    cfgs = {"gsc": FakeGSC(["sc-domain:example.com"]), "serper": {"key": "b"}}
    results, _ = core.run_checks(["https://example.com/a", TARGET], ["gsc", "serper"], cfgs, diagnose=False, workers=2)
    assert results[0].engine == "Google Search Console" and results[0].verdict == V.INDEXED
    assert results[1].engine == "Serper" and results[1].verdict == V.NOTFOUND
    assert "skipped" in results[1].attempts


def test_unknown_when_all_engines_fail(fake):
    fake(lambda m, u, kw: FakeResp(403, text="Unauthorized"))
    results, state = core.run_checks([TARGET], ["serper"], {"serper": {"key": "x"}}, diagnose=False)
    assert results[0].verdict == V.UNKNOWN and "serper" in state.dead


def test_diagnostics_noindex(fake):
    page = '<html><head><meta name="robots" content="noindex"><link rel="canonical" href="/other"></head></html>'

    def handler(m, u, kw):
        if "serper.dev" in u:
            return FakeResp(200, {"organic": []})
        return FakeResp(200, text=page, url="https://example.com/a", headers={"Content-Type": "text/html"})

    fake(handler)
    results, _ = core.run_checks(["https://example.com/a"], ["serper"], {"serper": {"key": "b"}}, diagnose=True)
    assert "noindex" in results[0].likely_cause and "canonical" in results[0].likely_cause


# ---------------------------------------------------------------- sitemap + export
def test_sitemap_gzip_ignores_images(fake):
    xml = (b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
           b'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1"><url><loc>https://a.com/1</loc>'
           b'<image:image><image:loc>https://a.com/i.jpg</image:loc></image:image></url>'
           b'<url><loc>https://a.com/2</loc></url></urlset>')
    fake(lambda m, u, kw: FakeResp(200, content=gzip.compress(xml), text="x"))
    urls, errors = core.fetch_sitemap("https://a.com/sitemap.xml.gz")
    assert urls == ["https://a.com/1", "https://a.com/2"] and not errors


def test_excel_export():
    df = pd.DataFrame({"Link": ["a"], "Result": [V.INDEXED]})
    data = core.to_excel(df, {"Total": 1})
    assert data[:2] == b"PK"


# ---------------------------------------------------------------- added 2026-10-21
def test_split_input_lines_not_words():
    got = core.split_input("https://a.example/x\nnot a link\nwww.b.example/y, https://c.example/z\n# note\n\nb.example/p")
    assert got == ["https://a.example/x", "not a link", "www.b.example/y", "https://c.example/z", "b.example/p"]
    valid, invalid, dupes = core.prepare_urls(got)
    assert invalid == ["not a link"] and len(valid) == 4   # one bad line = one invalid entry


def test_brightdata_html_reply_is_read(fake):
    html = '<html><body><a href="/url?q=' + TARGET + '&sa=U"><h3>T</h3></a></body></html>'
    fake(lambda m, u, kw: FakeResp(200, text=html))
    assert core.check_brightdata(TARGET, {"key": "k", "zone": "z"}, True)["verdict"] == V.INDEXED
    fake(lambda m, u, kw: FakeResp(200, text="<html>Your search did not match any documents.</html>"))
    assert core.check_brightdata(TARGET, {"key": "k", "zone": "z"}, True)["verdict"] == V.NOTFOUND
    fake(lambda m, u, kw: FakeResp(200, {"status_code": 200, "body": json.dumps({"organic": [{"link": TARGET, "title": "T"}]})}))
    assert core.check_brightdata(TARGET, {"key": "k", "zone": "z"}, True)["verdict"] == V.INDEXED


def test_brightdata_retries_once_then_says_what_came_back(fake):
    replies = [FakeResp(200, text="<html>weird page</html>"), FakeResp(200, {"organic": [{"link": TARGET, "title": "T"}]})]
    s = fake(lambda m, u, kw: replies.pop(0))
    assert core.check_brightdata(TARGET, {"key": "k", "zone": "z"}, True)["verdict"] == V.INDEXED and len(s.calls) == 2
    fake(lambda m, u, kw: FakeResp(200, {"error": "zone not active"}))
    out = core.check_brightdata(TARGET, {"key": "k", "zone": "z"}, True)
    assert out["verdict"] == V.UNKNOWN and "zone not active" in out["detail"] and "tried twice" in out["detail"]
    fake(lambda m, u, kw: FakeResp(200, text="<html>Our systems have detected unusual traffic</html>"))
    assert "CAPTCHA" in core.check_brightdata(TARGET, {"key": "k", "zone": "z"}, True)["detail"]


def test_verdicts_are_honest():
    assert core.VERDICT_SHORT[V.NOTFOUND] == "Not found on Google" and V.NOTFOUND in core.VERIFIED and V.UNKNOWN not in core.VERIFIED
    assert "not proof" in core.ENGINES["serper"].proves and "final word" in core.ENGINES["gsc"].proves
    for e in core.ENGINES.values():   # every allowance names its kind; paid search engines name their official page
        assert e.kind and e.renew and (e.source or e.key == "direct")


# ---------------------------------------------------------------- review fixes (2026-10-21)
def test_split_input_keeps_commas_inside_links():
    got = core.split_input("https://en.wikipedia.org/wiki/Washington,_D.C.\nhttps://a.example/p?ids=1,2\n"
                           "example.com, https://a.example/x;https://b.example/y\nsee e.g. this")
    assert got == ["https://en.wikipedia.org/wiki/Washington,_D.C.", "https://a.example/p?ids=1,2",
                   "example.com", "https://a.example/x", "https://b.example/y", "see e.g. this"]


def test_query_words_are_not_a_captcha():
    page = '<html><title>site:blog.example/recaptcha-setup unusual-traffic</title><a href="/url?q=https://blog.example/recaptcha-setup"><h3>T</h3></a></html>'
    assert core.parse_google_html(page)[0] == "results"
    assert core.parse_google_html('<form action="/sorry/index"><div class="g-recaptcha"></div></form>')[0] == "blocked"
    assert not core._is_google_host("lovegoogle.com") and core._is_google_host("www.google.co.uk") and core._is_google_host("google.com")


def test_gsc_empty_reply_is_couldnt_check(fake):
    c = core.GSCClient.__new__(core.GSCClient)
    c.sites, c.exhausted, c.email = ["sc-domain:velog.io"], set(), "x"
    c.token = lambda: "t"
    fake(lambda m, u, kw: FakeResp(200, {"inspectionResult": {}}))
    assert core.check_gsc(TARGET, c, True)["verdict"] == V.UNKNOWN


def test_couldnt_check_does_not_prove_a_method_works():
    st = core.RunState(["serper"])
    core.ENGINE_FUNCS["_t"] = None
    orig = core.ENGINE_FUNCS["serper"]
    core.ENGINE_FUNCS["serper"] = lambda u, cfg, s: core.unknown("Serper: error 500")
    try:
        core.check_one(TARGET, st, {}, True, False)
    finally:
        core.ENGINE_FUNCS["serper"] = orig
        core.ENGINE_FUNCS.pop("_t", None)
    assert st.used["serper"] == 1 and st.answered["serper"] == 0


def test_stopped_run_cancels_the_rest():
    import threading
    calls = []
    lock = threading.Lock()

    def slow(u, cfg, s):
        with lock:
            calls.append(u)
        time_mod.sleep(0.2)
        return core.judge(u, [], s)

    orig = core.ENGINE_FUNCS["serper"]
    core.ENGINE_FUNCS["serper"] = slow

    def stop(i, n, u, state):
        raise KeyboardInterrupt  # like Streamlit stopping the script

    try:
        with pytest.raises(KeyboardInterrupt):
            core.run_checks([f"https://s{i}.example/p" for i in range(10)], ["serper"], {}, True, False, workers=2, on_progress=stop)
    finally:
        core.ENGINE_FUNCS["serper"] = orig
    time_mod.sleep(0.6)
    assert len(calls) < 10, f"{len(calls)} of 10 links still ran after the stop"


def test_excel_drops_control_characters():
    import io as _io
    from openpyxl import load_workbook
    df = pd.DataFrame({"Link": ["https://a.example/"], "Google title": ["Bad\x0btitle\x1b"], "Result": [V.INDEXED]})
    wb = load_workbook(_io.BytesIO(core.to_excel(df, {"x": "y\x0b"})))
    assert wb["Index Check"]["B2"].value == "Badtitle"
