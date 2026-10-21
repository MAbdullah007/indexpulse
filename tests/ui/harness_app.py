"""Test harness: runs the real app.py with fake search engines (no keys, no credits, no internet).
Used by tests/ui/test_browser.py:  streamlit run tests/ui/harness_app.py
Invented links only."""
import os, runpy, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import streamlit as st  # noqa: E402
import core  # noqa: E402

INDEXED = {"https://shop-a.example/", "https://shop-a.example/about/", "https://dir-one.example/listing/shop-a-dental"}
OTHER = {"https://dir-two.example/profile/shop-a": "https://dir-two.example/profile/"}
BROKEN = {"https://dir-four.example/biz/shop-a"}


def fake_serper(url, cfg, strict):
    u = core.with_scheme(url)
    if u in BROKEN:
        return core.unknown("Serper: error 500")
    if u in INDEXED:
        return core.judge(url, [(u, "Shop A")], strict)
    if u in OTHER:
        return core.judge(url, [(OTHER[u], "Directory home")], strict)
    return core.judge(url, [], strict)


def fake_page(res):  # no internet in tests
    res.http_status, res.likely_cause = "200", "Page looks OK — Google probably hasn't indexed it yet"


core.ENGINE_FUNCS["serper"] = fake_serper
core.page_diagnostics = fake_page
st.session_state.setdefault("serper_key", "test-key")
for e in ("gsc", "brightdata", "serpapi", "direct"):
    st.session_state.setdefault(f"use_{e}", False)
runpy.run_path(os.path.join(ROOT, "app.py"), run_name="__main__")
