"""
IndexPulse — Google Index Checker (Streamlit UI). All checking logic lives in core.py (unit-tested).
Run locally:  streamlit run app.py          Tests: pytest -q   (UI: tests/ui/, see docs/TESTING.md)
Page order: header → 1 Choose how to check → 2 Add links → 3 Check → 4 Results → Download → Help & accuracy.
"""

import hmac
import json
import time
from dataclasses import asdict
from datetime import datetime

import pandas as pd
import streamlit as st

import core
from core import ENGINE_ORDER, ENGINES, V

st.set_page_config(page_title="IndexPulse — Google Index Checker", page_icon="🛡️", layout="wide",
                   initial_sidebar_state="collapsed")

C = core.VERDICT_COLORS
SHORT = core.VERDICT_SHORT
# status colours (one meaning everywhere): green working · yellow setup incomplete / not tested · orange limited ·
# red confirmed error · grey off / not configured
STATUS = {"green": ("#dcfce7", "#166534", "#86efac"), "yellow": ("#fef9c3", "#854d0e", "#fde047"),
          "orange": ("#ffedd5", "#9a3412", "#fdba74"), "red": ("#fee2e2", "#991b1b", "#fca5a5"),
          "gray": ("#f1f5f9", "#475569", "#cbd5e1")}

# =====================================================================
# DESIGN SYSTEM (scoped CSS; a global `*` font rule would break Streamlit's icons)
# =====================================================================
card_css = "".join(
    f""".st-key-card_{i} button {{ background:{bg}; color:{fg}; border:1px solid {bd}; border-left:5px solid {fg}; }}
.st-key-card_{i} button:hover {{ border-color:{fg}; color:{fg}; }}
.st-key-card_{i}.on button {{ outline:3px solid #4f46e5; outline-offset:1px; }}"""
    for i, (bg, fg, bd) in enumerate([C[v] for v in core.ALL_VERDICTS]))
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
html, body, p, h1, h2, h3, h4, label, input, textarea, button, li,
[data-testid="stMarkdownContainer"], [data-testid="stCaptionContainer"] {{ font-family:'Plus Jakarta Sans',sans-serif; }}
.block-container {{ padding-top:1rem; max-width:1180px; }}
:root {{ --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --brand:#4f46e5; }}
/* header */
.ip-head {{ display:flex; flex-wrap:wrap; gap:10px 18px; align-items:center; justify-content:space-between;
  background:#0f172a; color:#fff; border-radius:14px; padding:14px 18px; }}
.ip-head h1 {{ margin:0; font-size:22px; font-weight:800; color:#fff; letter-spacing:-.3px; }}
.ip-head p {{ margin:2px 0 0; color:#c7d2fe; font-size:13.5px; }}
.ip-head .chips {{ display:flex; flex-wrap:wrap; gap:6px; }}
/* sticky step navigation */
div[data-testid="stElementContainer"]:has(.ip-nav) {{ position:sticky; top:0; z-index:50; }}
.ip-nav {{ display:flex; flex-wrap:wrap; gap:4px 14px; align-items:center; background:rgba(248,250,252,.96);
  backdrop-filter:blur(6px); border-bottom:1px solid var(--line); padding:8px 2px; font-size:13px; }}
.ip-nav a {{ color:#334155; text-decoration:none; font-weight:600; }}
.ip-nav a:hover {{ color:var(--brand); }}
.ip-nav b {{ display:inline-grid; place-items:center; width:20px; height:20px; border-radius:50%; background:#e0e7ff;
  color:#3730a3; font-size:11.5px; margin-right:5px; }}
/* section titles */
.ip-step {{ margin:18px 0 2px; display:flex; gap:10px; align-items:center; }}
.ip-step .n {{ flex:none; width:28px; height:28px; border-radius:8px; background:var(--brand); color:#fff; display:grid;
  place-items:center; font-weight:800; font-size:14px; }}
.ip-step h2 {{ margin:0; font-size:19px; font-weight:800; color:var(--ink); padding:0; }}
.ip-sub {{ color:var(--muted); font-size:13.5px; margin:0 0 8px 38px; }}
/* pills */
.pill {{ display:inline-block; padding:2px 10px; border-radius:999px; font-size:12.5px; font-weight:700; border:1px solid;
  margin:0 6px 4px 0; white-space:nowrap; }}
{"".join(f".pill.{k} {{ background:{v[0]}; color:{v[1]}; border-color:{v[2]}; }}" for k, v in STATUS.items())}
/* provider cards */
.pv-top {{ display:flex; justify-content:space-between; gap:8px; align-items:flex-start; }}
.pv-name {{ font-weight:800; font-size:15px; color:var(--ink); }}
.pv-n {{ color:var(--muted); font-weight:700; margin-right:4px; }}
.pv-line {{ font-size:13px; color:#334155; margin:6px 0 0; }}
.pv-line .k {{ display:inline-block; font-size:11px; font-weight:800; letter-spacing:.3px; text-transform:uppercase;
  color:#4338ca; background:#eef2ff; border-radius:5px; padding:1px 6px; margin-right:6px; }}
.pv-small {{ font-size:12px; color:var(--muted); margin-top:4px; }}
.howto {{ font-size:13px; color:#334155; background:#f8fafc; border:1px dashed #cbd5e1; border-radius:10px; padding:.55rem .85rem; }}
.howto ol {{ margin:.2rem 0 0 1.1rem; padding:0; }}
/* result cards (buttons styled as cards) */
[class*="st-key-card_"] button {{ width:100%; min-height:92px; border-radius:12px; text-align:left; justify-content:flex-start;
  padding:10px 12px; white-space:pre-line; line-height:1.25; font-weight:600; }}
[class*="st-key-card_"] button p {{ font-size:13px; text-align:left; }}
[class*="st-key-card_"] button p strong {{ font-size:26px; font-weight:800; }}
{card_css}
.rate {{ border-radius:12px; padding:10px 12px; border:1px solid var(--line); background:#fff; min-height:92px; }}
.rate .v {{ font-size:26px; font-weight:800; line-height:1.2; }}
.rate .l {{ font-size:13px; font-weight:700; color:#334155; }}
.rate .s {{ font-size:12px; color:var(--muted); }}
/* help tables */
.ip-table {{ width:100%; border-collapse:collapse; font-size:13px; }}
.ip-table th {{ text-align:left; background:#f8fafc; color:#475569; font-size:11.5px; text-transform:uppercase; letter-spacing:.4px; }}
.ip-table th, .ip-table td {{ border-bottom:1px solid var(--line); padding:7px 8px; vertical-align:top; }}
.detail-k {{ color:var(--muted); font-size:12px; }}
@media (max-width:640px) {{ .ip-head h1 {{ font-size:19px; }} .ip-sub {{ margin-left:0; }} .ip-nav {{ font-size:12px; gap:4px 10px; }} }}
</style>
""", unsafe_allow_html=True)


def pill(text: str, color: str) -> str:
    return f'<span class="pill {color}">{text}</span>'


def step(n, anchor: str, title: str, sub: str = ""):
    st.markdown(f'<div class="ip-step" id="{anchor}"><span class="n">{n}</span><h2>{title}</h2></div>'
                + (f'<p class="ip-sub">{sub}</p>' if sub else ""), unsafe_allow_html=True)


def esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


# =====================================================================
# SECRETS / SETTINGS
# =====================================================================
def secret(name: str, default=""):
    try:
        return st.secrets.get(name, default)
    except Exception:  # noqa: BLE001 — no secrets file is fine
        return default


DEFAULTS = {
    "brd_key": secret("BRIGHTDATA_API_KEY"), "brd_zone": secret("BRIGHTDATA_ZONE"),
    "serpapi_key": secret("SERPAPI_KEY"), "serper_key": secret("SERPER_API_KEY"), "direct_delay": 5.0,
    "use_gsc": True, "use_brightdata": True, "use_serpapi": True, "use_serper": True, "use_direct": False,
    "tested": {}, "dead": {},
}
for k, v in DEFAULTS.items():
    st.session_state.setdefault(k, v)


def val(key: str) -> str:
    return str(st.session_state.get(key) or "").strip()


# =====================================================================
# PASSWORD GATE (protects your free credits when the app is online)
# =====================================================================
APP_PASSWORD = secret("APP_PASSWORD")
if APP_PASSWORD and not st.session_state.get("authed"):
    st.markdown('<div class="ip-head"><div><h1>🛡️ IndexPulse</h1><p>This tool is private. Enter the password.</p></div></div>',
                unsafe_allow_html=True)
    pw = st.text_input("Password", type="password")
    if pw:
        if hmac.compare_digest(pw, str(APP_PASSWORD)):
            st.session_state["authed"] = True
            st.rerun()
        st.error("Wrong password.")
    st.stop()


# =====================================================================
# SEARCH CONSOLE CREDENTIALS
# =====================================================================
def gsc_info():
    if st.session_state.get("gsc_info"):
        return st.session_state["gsc_info"]
    raw = secret("GSC_JSON", "")  # whole JSON file pasted as one secret (easiest)
    if raw:
        try:
            return json.loads(raw)
        except ValueError:
            st.session_state["gsc_error"] = "GSC_JSON in Secrets is not valid JSON — paste the whole file again."
    s = secret("gsc_service_account", None)
    return dict(s) if s else None


def gsc_client():
    info = gsc_info()
    if not info:
        return None
    key = info.get("client_email", "") + info.get("private_key_id", "")
    if st.session_state.get("_gsc_key") != key:
        try:
            st.session_state["_gsc_client"] = core.GSCClient(info)
        except Exception as e:  # noqa: BLE001
            st.session_state["_gsc_client"] = None
            st.session_state["gsc_error"] = str(e)
        st.session_state["_gsc_key"] = key
    return st.session_state.get("_gsc_client")


def has_creds(e: str) -> bool:
    return {
        "gsc": lambda: gsc_client() is not None,
        "brightdata": lambda: bool(val("brd_key") and val("brd_zone")),
        "serpapi": lambda: bool(val("serpapi_key")),
        "serper": lambda: bool(val("serper_key")),
        "direct": lambda: True,
    }[e]()


def build_cfgs() -> dict:
    return {
        "gsc": gsc_client(),
        "brightdata": {"key": val("brd_key"), "zone": val("brd_zone")},
        "serpapi": {"key": val("serpapi_key")},
        "serper": {"key": val("serper_key")},
        "direct": {"delay": float(st.session_state.get("direct_delay", 5.0))},
    }


def hhmm() -> str:
    return datetime.now().strftime("%I:%M %p").lstrip("0")


def engine_status(e: str):
    """(color, short text). Green only after a real success (Test button, or it answered in the last check)."""
    if not st.session_state.get(f"use_{e}"):
        return "gray", "Off"
    dead = st.session_state["dead"].get(e)
    if dead:
        return "red", f"Stopped: {dead}"
    if e != "direct" and not has_creds(e):
        return "yellow", "Key missing"
    t = st.session_state["tested"].get(e)
    if t and t[0] == "fail":
        return "red", "Test failed"
    if t and t[0] == "ok":
        left = t[3] if len(t) > 3 else None
        if isinstance(left, int) and left < 25:
            return "orange", f"Only {left} left"
        return "green", f"Working · {t[2]}"
    return "yellow", "Not tested yet"


def ready_engines() -> list[str]:
    return [e for e in ENGINE_ORDER if st.session_state.get(f"use_{e}") and has_creds(e)]


# =====================================================================
# TEST BUTTONS (a real call — never "Ready" just because a key was typed)
# =====================================================================
def test_engine(e: str):
    """Returns (ok|fail, message, time, live_balance_or_None)."""
    cfgs = build_cfgs()
    try:
        if e == "serpapi":
            acct = core.serpapi_account(cfgs["serpapi"]["key"])
            left = acct.get("total_searches_left", acct.get("plan_searches_left"))
            left = int(left) if isinstance(left, (int, float)) else None
            return ("ok", f"Works. {left if left is not None else 'Unknown number of'} searches left (live from SerpApi; this test is free).",
                    hhmm(), left)
        if e == "gsc":
            c = cfgs["gsc"]
            sites = c.list_sites()
            if not sites:
                return ("fail", f"Logged in, but no websites found. In Search Console open your site → Settings → Users and "
                                f"permissions → Add user → paste **{c.email}** → Full.", hhmm(), None)
            shown = ", ".join(sites[:5]) + (" …" if len(sites) > 5 else "")
            return "ok", f"Works. Connected to {len(sites)} website(s): {shown}", hhmm(), None
        out = core.ENGINE_FUNCS[e]("https://www.google.com/", cfgs[e], True)
        if out["verdict"] == V.UNKNOWN:
            return "fail", out["detail"], hhmm(), None
        return "ok", "Works. (This test used 1 check.)", hhmm(), None
    except core.EngineDown as d:
        return "fail", f"Not working: {d}", hhmm(), None
    except Exception as ex:  # noqa: BLE001
        return "fail", f"Not working: {ex.__class__.__name__}: {str(ex)[:120]}", hhmm(), None


HOWTO = {
    "gsc": [
        "Open <a href='https://console.cloud.google.com/' target='_blank'>Google Cloud Console</a> → create a project → "
        "search <b>Google Search Console API</b> → Enable.",
        "<b>IAM &amp; Admin → Service Accounts → Create</b>. Open it → <b>Keys → Add key → JSON</b>. A file downloads.",
        "In <a href='https://search.google.com/search-console' target='_blank'>Search Console</a>: your site → "
        "<b>Settings → Users and permissions → Add user</b> → paste the service-account email → <b>Full</b>.",
        "Upload the JSON file below (or paste it into the app's Secrets as GSC_JSON).",
    ],
    "brightdata": [
        "Sign up at <a href='https://brightdata.com/products/serp-api' target='_blank'>brightdata.com</a>.",
        "<b>Proxies &amp; Scraping → Add → SERP API</b>. Name the zone, e.g. <code>serp_api1</code>.",
        "Copy the <b>zone name</b> and your <b>API key</b> (Account settings → API key) below.",
    ],
    "serpapi": [
        "Sign up at <a href='https://serpapi.com/users/sign_up' target='_blank'>serpapi.com</a>.",
        "Copy <b>Your Private API Key</b> from the dashboard below.",
    ],
    "serper": [
        "Sign up at <a href='https://serper.dev' target='_blank'>serper.dev</a>.",
        "Open <b>API Key</b> and copy it below.",
    ],
    "direct": [
        "No key needed. Google blocks it quickly, so keep it as the <b>last</b> backup.",
        "Works only when you run the tool on your own computer — not on cloud hosting.",
    ],
}


def provider_card(i: int, e: str):
    info = ENGINES[e]
    color, text = engine_status(e)
    with st.container(border=True):
        st.markdown(
            f'<div class="pv-top"><div class="pv-name"><span class="pv-n">{i}</span>{info.name}</div>{pill(esc(text), color)}</div>'
            f'<div class="pv-line"><span class="k">{info.kind}</span>{info.free}</div>'
            f'<div class="pv-small">{info.note}</div>',
            unsafe_allow_html=True)
        st.toggle("Use this method", key=f"use_{e}")
        with st.expander("Set up & test" if e != "direct" else "Settings"):
            steps = "".join(f"<li>{s}</li>" for s in HOWTO[e])
            st.markdown(f'<div class="howto"><b>How to get it:</b><ol>{steps}</ol></div>', unsafe_allow_html=True)
            if e == "gsc":
                if not core.HAS_GOOGLE_AUTH:
                    st.error("Package `google-auth` is missing. Run: pip install google-auth")
                up = st.file_uploader("Service-account JSON key", type="json", key="gsc_file")
                if up is not None:
                    try:
                        data = json.loads(up.getvalue().decode("utf-8"))
                        if not data.get("client_email") or not data.get("private_key"):
                            raise ValueError
                        st.session_state["gsc_info"] = data
                    except Exception:  # noqa: BLE001
                        st.error("This file is not a service-account JSON key.")
                c = gsc_client()
                if c:
                    st.markdown(pill(f"Logged in as {esc(c.email)}", "green"), unsafe_allow_html=True)
                elif st.session_state.get("gsc_error") and gsc_info():
                    st.error(st.session_state["gsc_error"])
            elif e == "brightdata":
                st.text_input("API key", key="brd_key", type="password")
                st.text_input("Zone name", key="brd_zone", placeholder="serp_api1")
            elif e == "serpapi":
                st.text_input("API key", key="serpapi_key", type="password")
            elif e == "serper":
                st.text_input("API key", key="serper_key", type="password")
            elif e == "direct":
                st.slider("Pause between checks (seconds)", 3.0, 20.0, key="direct_delay", step=0.5)
            st.caption(f"**Renews:** {info.renew}  \n**What it can prove:** {info.proves}"
                       + (f"  \nAllowance from [the official page]({info.source}), checked {core.QUOTA_CHECKED}." if info.source else ""))
            if e != "direct":
                cost = "free" if e in ("serpapi", "gsc") else "uses 1 check"
                if st.button(f"Test {info.name} ({cost})", key=f"test_btn_{e}", disabled=not has_creds(e), width="stretch"):
                    with st.spinner("Testing…"):
                        st.session_state["tested"][e] = test_engine(e)
                    if st.session_state["tested"][e][0] == "ok":
                        st.session_state["dead"].pop(e, None)
                    st.rerun()
                t = st.session_state["tested"].get(e)
                if t:
                    (st.success if t[0] == "ok" else st.error)(f"{t[1]}  \n*Tested at {t[2]}.*")


# =====================================================================
# HEADER + STEP NAVIGATION
# =====================================================================
ready = ready_engines()
working = [e for e in ready if engine_status(e)[0] in ("green", "orange")]
head_chips = (pill(f"{len(working)} method{'s' if len(working) != 1 else ''} working", "green") if working
              else pill("No method tested yet", "yellow"))
if st.session_state.get("run_meta"):
    head_chips += pill(f"Last check: {st.session_state['run_meta'].get('at', '')}", "gray")
st.markdown(f"""
<div class="ip-head"><div><h1>🛡️ IndexPulse</h1>
<p>Is this exact link on Google? Paste links, press Check — every link is asked live, nothing old is reused.</p></div>
<div class="chips">{head_chips}</div></div>""", unsafe_allow_html=True)
st.markdown("""<nav class="ip-nav" aria-label="Steps"><a href="#methods"><b>1</b>Choose how to check</a><a href="#links"><b>2</b>Add links</a>
<a href="#check"><b>3</b>Check</a><a href="#results"><b>4</b>Results</a><a href="#help">ⓘ Help &amp; accuracy</a></nav>""",
            unsafe_allow_html=True)

# =====================================================================
# STEP 1 — METHODS
# =====================================================================
step(1, "methods", "Choose how to check",
     "Turn on the methods you have keys for and press Test once. They are tried in this order (1 → 5): when one has no "
     "credits left or cannot check a link, the next one takes over by itself.")
for row in (ENGINE_ORDER[:3], ENGINE_ORDER[3:]):
    cols = st.columns(3)
    for col, e in zip(cols, row):
        with col:
            provider_card(ENGINE_ORDER.index(e) + 1, e)
st.caption(f"Free allowances as each provider states them, checked {core.QUOTA_CHECKED}. "
           "Only SerpApi's Test shows a live balance; the others are the provider's published numbers, not a live count.")

# =====================================================================
# STEP 2 — LINKS
# =====================================================================
step(2, "links", "Add your links", "Paste links (one per line), or read them from a sitemap.")
with st.container(border=True):
    source = st.radio("Where are your links?", ["Paste links", "From a sitemap"], horizontal=True, label_visibility="collapsed")
    raw_urls: list[str] = []
    if source == "Paste links":
        text = st.text_area(
            "Links", height=160, label_visibility="collapsed",
            placeholder="https://www.example-directory.com/listing/your-business\nexample-blog.com/post/your-article",
            help="One link per line (several on one line also work, separated by spaces or commas). "
                 "https:// is optional. Duplicates are removed; lines that are not links are listed below — nothing is dropped silently.")
        raw_urls = core.split_input(text)
    else:
        c_in, c_btn = st.columns([4, 1], vertical_alignment="bottom")
        sm_url = c_in.text_input("Sitemap link", placeholder="https://example.com/sitemap.xml")
        if c_btn.button("Read sitemap", width="stretch", disabled=not sm_url):
            with st.spinner("Reading the sitemap…"):
                fetched, sm_errors = core.fetch_sitemap(sm_url, max_urls=int(st.session_state.get("max_sm", 5000)))
            st.session_state["sm_links"], st.session_state["sm_errors"] = fetched, sm_errors
        raw_urls = st.session_state.get("sm_links", [])
        if st.session_state.get("sm_errors"):
            with st.expander(f"⚠️ {len(st.session_state['sm_errors'])} sitemap file(s) could not be read"):
                st.code("\n".join(st.session_state["sm_errors"]), language=None)
                st.caption("Check the link opens in your browser. Many sites use /sitemap_index.xml or /wp-sitemap.xml. "
                           "You can also paste the links instead.")
        if raw_urls:
            with st.expander(f"Review the {len(raw_urls)} links read from the sitemap"):
                st.code("\n".join(raw_urls[:2000]) + ("\n…" if len(raw_urls) > 2000 else ""), language=None)
            st.caption("A sitemap lists the pages the website chooses to list; it is not always every page.")
    with st.expander("More options"):
        o1, o2, o3 = st.columns(3)
        o1.toggle("Match capital letters exactly", value=True, key="strict_case",
                  help="Google treats /Page and /page as two different links.")
        o2.toggle("Find out why a link is not on Google", value=True, key="diagnose",
                  help="Opens each page Google does not show and checks for errors, noindex, redirects and canonical.")
        o3.slider("Checks at the same time", 1, 10, 5, key="workers", help="Higher = faster. Lower it if you see 'Too many requests'.")
        st.number_input("Max links to read from a sitemap", 100, 50_000, 5000, 100, key="max_sm")

    strict_case = st.session_state.get("strict_case", True)
    urls, invalid, dupes = core.prepare_urls(raw_urls, strict_case)
    if raw_urls:
        info = pill(f"✓ {len(urls)} link{'s' if len(urls) != 1 else ''} ready", "green")
        if dupes:
            info += pill(f"{dupes} duplicate{'s' if dupes != 1 else ''} removed", "yellow")
        if invalid:
            info += pill(f"{len(invalid)} line{'s' if len(invalid) != 1 else ''} not a link", "red")
        st.markdown(info, unsafe_allow_html=True)
        if invalid:
            with st.expander("Show the lines that are not links"):
                st.code("\n".join(invalid[:200]), language=None)


# =====================================================================
# STEP 3 — CHECK
# =====================================================================
def prepare_engines(engines: list[str]) -> list[str]:
    """Search Console needs its site list before it can route links."""
    if "gsc" in engines:
        c = gsc_client()
        try:
            if c.sites is None:
                c.list_sites()
            if not c.sites:
                st.warning(f"Search Console: no websites found for {c.email}. Add it as a user in Search Console. "
                           "Using the other methods instead.")
                engines = [e for e in engines if e != "gsc"]
        except Exception as ex:  # noqa: BLE001
            st.warning(f"Search Console could not log in ({ex}). Using the other methods instead.")
            engines = [e for e in engines if e != "gsc"]
    return engines


def do_run(link_list: list[str]):
    engines = prepare_engines(ready_engines())
    if not engines:
        st.error("No checking method is ready.")
        return None
    bar = st.progress(0.0, text=f"Checking 0 of {len(link_list)} links…")
    started = time.time()
    partial = st.session_state["partial"] = {"total": len(link_list), "results": {}, "at": core.now_utc()}

    def on_result(u, res):  # kept even if the run is stopped half-way
        partial["results"][u] = res

    def on_progress(i, n, u, state):
        bar.progress(i / n, text=f"Checking {i} of {n} links…  {u[:60]}")

    results, state = core.run_checks(link_list, engines, build_cfgs(), strict_case, st.session_state.get("diagnose", True),
                                     st.session_state.get("workers", 5), on_progress, on_result)
    bar.empty()
    st.session_state.pop("partial", None)
    st.session_state["dead"] = dict(state.dead)
    for e, n in state.used.items():  # an engine that answered in this check is proven to work
        if n and e not in state.dead and st.session_state["tested"].get(e, ("",))[0] != "ok":
            st.session_state["tested"][e] = ("ok", "Answered in the last check.", hhmm(), None)
    return results, state, round(time.time() - started, 1)


step(3, "check", "Check", "Every link is asked live. Big lists take a while: keep this tab open.")
reason = ""
if not urls:
    reason = "Add at least one link in step 2."
elif not ready:
    reason = "Turn on at least one method and add its key in step 1."
if reason:
    st.markdown(pill(reason, "yellow"), unsafe_allow_html=True)
elif not working:
    st.markdown(pill("No method has been tested yet. It will still run; press Test in step 1 to be sure.", "yellow"),
                unsafe_allow_html=True)
if "serpapi" in ready and len(ready) == 1 and len(urls) > 50:
    st.info("SerpApi's free plan allows 50 searches per hour: links after the 50th will stop until the next hour.")

if st.button(f"▶  Check {len(urls)} link{'s' if len(urls) != 1 else ''}", type="primary", width="stretch", disabled=bool(reason)):
    out = do_run(urls)
    if out:
        results, state, secs = out
        st.session_state["results"] = results
        st.session_state["run_meta"] = {"secs": secs, "used": dict(state.used), "dead": dict(state.dead), "at": core.now_utc(),
                                        "total": len(urls)}
        st.session_state["flt"] = None
        st.rerun()

# a check that was stopped half-way (the page was changed or reloaded while it ran): keep what it found
part = st.session_state.get("partial")
if part and part["results"]:
    got = list(part["results"].values())
    st.warning(f"The last check stopped after {len(got)} of {part['total']} links (the page was changed while it ran). "
               "The finished links are shown below; press Check again for the rest.")
    st.session_state["results"] = got
    st.session_state["run_meta"] = {"secs": 0, "used": {}, "dead": dict(st.session_state["dead"]), "at": part["at"],
                                    "total": part["total"], "partial": True}
    st.session_state.pop("partial", None)

# =====================================================================
# STEP 4 — RESULTS
# =====================================================================
results = st.session_state.get("results", [])
if results:
    meta = st.session_state.get("run_meta", {})
    step(4, "results", "Results")
    n = {v: sum(r.verdict == v for r in results) for v in core.ALL_VERDICTS}
    answered = len(results) - n[V.UNKNOWN]
    rate = round(n[V.INDEXED] / answered * 100, 1) if answered else None
    done_txt = f"{len(results)} of {meta.get('total', len(results))} links checked · {meta.get('at', '')}" + (
        f" · took {meta.get('secs')} s" if meta.get("secs") else "")
    if meta.get("partial"):
        st.warning(f"Not complete: {done_txt}.")
    elif n[V.UNKNOWN]:
        st.warning(f"Results are ready, but {n[V.UNKNOWN]} link{'s' if n[V.UNKNOWN] != 1 else ''} could not be checked "
                   f"({done_txt}). Re-check them below.")
    else:
        st.success(f"Results are ready: {done_txt}.")
    for e, why in meta.get("dead", {}).items():
        st.warning(f"**{ENGINES[e].name} stopped:** {why}. The next method took over for the remaining links.", icon="⚠️")

    # summary cards: click one to show only those links (click again for all)
    flt = st.session_state.get("flt")
    cols = st.columns(6)
    with cols[0]:
        tone = "#166534" if rate is not None and rate >= 80 else "#854d0e" if rate is not None and rate >= 50 else "#991b1b"
        st.markdown(f'<div class="rate"><div class="l">Index rate</div><div class="v" style="color:{tone}">'
                    f'{"–" if rate is None else str(rate) + "%"}</div><div class="s">indexed of {answered} answered</div></div>',
                    unsafe_allow_html=True)
    HINT = {V.INDEXED: "Google has this exact link", V.OTHER: "a different link shows", V.NOTFOUND: "search showed nothing",
            V.NOT: "Search Console: not indexed", V.UNKNOWN: "not counted · re-check"}
    for i, v in enumerate(core.ALL_VERDICTS):
        with cols[i + 1]:
            with st.container(key=f"card_{i}"):
                if st.button(f"**{n[v]}**\n{SHORT[v]}\n{HINT[v]}", key=f"cardbtn_{i}", width="stretch",
                             help=core.VERDICT_MEANING[v], type="secondary"):
                    st.session_state["flt"] = None if flt == v else v
                    st.rerun()
    if flt:
        st.markdown(f'<style>.st-key-card_{core.ALL_VERDICTS.index(flt)} button {{ outline:3px solid #4f46e5; outline-offset:1px; }}</style>',
                    unsafe_allow_html=True)

    used = meta.get("used", {})
    usage = "".join(pill(f"{ENGINES[e].name}: {c} check{'s' if c != 1 else ''}", "gray") for e, c in used.items() if c)
    if usage:
        st.markdown(f"<span style='font-size:13px;color:#475569'>Checked with:</span> {usage}", unsafe_allow_html=True)

    unknown_urls = [r.url for r in results if r.verdict == V.UNKNOWN]
    if unknown_urls and st.button(f"🔁  Re-check the {len(unknown_urls)} link{'s' if len(unknown_urls) != 1 else ''} that could not be checked",
                                  disabled=not ready):
        out = do_run(unknown_urls)
        if out:
            new, state, _ = out
            by_url = {r.url: r for r in new}
            st.session_state["results"] = [by_url.get(r.url, r) for r in results]
            st.session_state["run_meta"]["dead"] = dict(state.dead)
            for e, c in state.used.items():
                st.session_state["run_meta"].setdefault("used", {})[e] = st.session_state["run_meta"]["used"].get(e, 0) + c
            st.rerun()

    COLS = {
        "url": "Link", "verdict": "Result", "detail": "Why", "likely_cause": "Likely cause", "engine": "Checked with",
        "last_crawl": "Last crawled by Google", "proof_link": "Proof", "matched_url": "Google shows this link",
        "checked_at": "Checked at", "serp_title": "Google title", "http_status": "Page status", "robots": "Robots / indexing",
        "page_canonical": "Page canonical", "final_url": "Redirects to", "canonical": "Match key", "attempts": "Methods tried",
    }
    BASIC = ["Result", "Link", "Why", "Likely cause", "Checked with", "Last crawled by Google", "Proof"]   # Result first: visible on phones
    df = pd.DataFrame([asdict(r) for r in results]).rename(columns=COLS)[list(COLS.values())]

    f1, f2, f3 = st.columns([2.4, 1.6, 1])
    search = f1.text_input("Search", placeholder="Search link or domain…", label_visibility="collapsed")
    methods = sorted(m for m in df["Checked with"].unique() if m)
    pick_m = f2.multiselect("Checked with", methods, placeholder="Every method", label_visibility="collapsed")
    show_tech = f3.toggle("More columns", value=False)
    view = df
    if flt:
        view = view[view["Result"] == flt]
    if search:
        view = view[view["Link"].str.contains(search, case=False, regex=False)]
    if pick_m:
        view = view[view["Checked with"].isin(pick_m)]
    shown = view if show_tech else view[BASIC]

    def color_result(v):
        c = C.get(v)
        return f"background-color:{c[0]};color:{c[1]};font-weight:700" if c else ""

    styler = shown.style
    styler = styler.map(color_result, subset=["Result"]) if hasattr(styler, "map") else styler.applymap(color_result, subset=["Result"])
    st.caption(f"Showing {len(view)} of {len(df)} links" + (f" · only **{SHORT[flt]}** (click the card again for all)" if flt else "")
               + ". Click a column name to sort · click a row to see all its details.")
    if len(view):
        sel = st.dataframe(
            styler, width="stretch", hide_index=True, height=min(36 * (len(shown) + 1) + 6, 560),
            on_select="rerun", selection_mode="single-row", key="table",
            column_config={
                "Link": st.column_config.LinkColumn(width="medium"),
                "Result": st.column_config.TextColumn(width="medium"),
                "Why": st.column_config.TextColumn(width="medium"),
                "Proof": st.column_config.LinkColumn(display_text="Open ↗", width="small",
                                                     help="Open Google (or Search Console) and see it yourself"),
                "Google shows this link": st.column_config.LinkColumn(width="medium"),
                "Page canonical": st.column_config.LinkColumn(width="medium"),
                "Redirects to": st.column_config.LinkColumn(width="medium"),
            },
        )
        rows = (sel.selection.rows if sel and hasattr(sel, "selection") else []) or []
        if rows and rows[0] < len(view):
            r = view.iloc[rows[0]]
            with st.container(border=True):
                st.markdown(f"**{esc(r['Link'])}**  \n{esc(r['Result'])} — {esc(core.VERDICT_MEANING.get(r['Result'], ''))}",
                            unsafe_allow_html=True)
                facts = [(k, r[k]) for k in COLS.values() if k not in ("Link", "Result") and str(r[k]).strip()]
                st.markdown('<table class="ip-table">' + "".join(
                    f'<tr><td class="detail-k" style="width:30%">{esc(k)}</td><td>'
                    + (f'<a href="{esc(v)}" target="_blank" rel="noopener">{esc(v)}</a>' if str(v).startswith("http") else esc(v))
                    + "</td></tr>" for k, v in facts) + "</table>",
                    unsafe_allow_html=True)
    else:
        st.info("No link matches these filters.")

    # ---------- EXPORT ----------
    st.markdown('<div class="ip-step" id="download"><h2 style="font-size:16px">Download</h2></div>', unsafe_allow_html=True)
    which = st.radio("Rows", [f"What is shown ({len(view)})", f"All links ({len(df)})"], horizontal=True, label_visibility="collapsed")
    out_df = view if which.startswith("What") else df
    out_df = out_df.assign(**{"Result (words)": out_df["Result"].map(SHORT), "Meaning": out_df["Result"].map(core.VERDICT_MEANING)})
    summary = {
        "Links checked": len(results), "Of": meta.get("total", len(results)), "Complete": "No" if meta.get("partial") else "Yes",
        **{SHORT[v]: n[v] for v in core.ALL_VERDICTS}, "Index rate": "–" if rate is None else f"{rate}%",
        "Index rate means": "Indexed ÷ links Google answered for (Couldn't check is left out)",
        "Checked at": meta.get("at", ""), "Methods used": ", ".join(f"{ENGINES[e].name} ({c})" for e, c in used.items() if c),
        "Rows in this file": "Filtered: " + which if which.startswith("What") else "All links",
    }
    stamp = time.strftime("%Y%m%d_%H%M")
    d1, d2 = st.columns(2)
    d1.download_button("📊  Excel (coloured, with a summary sheet)", data=core.to_excel(out_df, summary),
                       file_name=f"index_check_{stamp}.xlsx", width="stretch",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    d2.download_button("📄  CSV", data=core.to_csv(out_df), file_name=f"index_check_{stamp}.csv", mime="text/csv", width="stretch")
    with st.expander("📋  Copy into Google Sheets"):
        st.caption("Click the copy icon (top right of the box), then paste into cell A1 of a Google Sheet.")
        st.code(core.to_tsv(out_df), language=None)

# =====================================================================
# HELP & ACCURACY
# =====================================================================
st.markdown('<div class="ip-step" id="help"><span class="n">ⓘ</span><h2>Help &amp; accuracy</h2></div>', unsafe_allow_html=True)
h1, h2 = st.columns(2)
with h1:
    with st.expander("What each result means"):
        st.markdown('<table class="ip-table"><tr><th>Result</th><th>Meaning</th></tr>' + "".join(
            f'<tr><td>{pill(SHORT[v], ["green", "yellow", "orange", "red", "gray"][i])}</td><td>{esc(core.VERDICT_MEANING[v])}</td></tr>'
            for i, v in enumerate(core.ALL_VERDICTS)) + "</table>", unsafe_allow_html=True)
    with st.expander("Why two methods can give different answers"):
        st.markdown("- **Search Console** reads Google's index for your own websites. Its answer can be a few days behind live search.\n"
                    "- **Search APIs** (Bright Data, SerpApi, Serper) run a real Google search for `site:` + the link. Search results "
                    "change with time, country and Google's own choices, so a page can be indexed and still not show.\n"
                    "- Each row says which method answered (**Checked with**). The tool never mixes answers into a vote: the first "
                    "method that gives a clear answer is used, and **Methods tried** shows the others.")
with h2:
    with st.expander(f"Free allowances (checked {core.QUOTA_CHECKED})"):
        st.markdown('<table class="ip-table"><tr><th>Method</th><th>Allowance</th><th>Renews / expires</th></tr>' + "".join(
            f'<tr><td><b>{esc(i.name)}</b><div class="detail-k">{esc(i.kind)}</div></td><td>{esc(i.free)}</td>'
            f'<td>{esc(i.renew)}{f" <a href={chr(39)}{i.source}{chr(39)} target={chr(39)}_blank{chr(39)}>Source</a>" if i.source else ""}</td></tr>'
            for i in ENGINES.values()) + "</table>", unsafe_allow_html=True)
        st.caption("Published numbers, not a live balance (except SerpApi's Test button). Providers can change them; check the source.")
    with st.expander("What you can paste"):
        st.markdown("- Full links (`https://…`) or without `https://`. One per line; several on one line separated by spaces or commas also work.\n"
                    "- Duplicates are removed (same link with or without www, a trailing / or tracking tags like utm_).\n"
                    "- Lines that are not links are listed, never dropped silently.\n"
                    "- When a method runs out of credits, the next method takes over; if none is left, those links show **Couldn't check**.")
