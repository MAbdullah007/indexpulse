"""
IndexPulse — Live Google Index Checker (Streamlit UI)
Run locally:  streamlit run app.py
"""

import hmac
import json
import re
import time
from dataclasses import asdict

import pandas as pd
import streamlit as st

import core
from core import ENGINE_ORDER, ENGINES, V

st.set_page_config(
    page_title="IndexPulse — Google Index Checker",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

GREEN, YELLOW, RED, GRAY = (core.VERDICT_COLORS[v] for v in (V.INDEXED, V.OTHER, V.NOT, V.UNKNOWN))

# =====================================================================
# STYLES (scoped — a global `*` font rule would break Streamlit's icons)
# =====================================================================
st.markdown(
    f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
html, body, p, h1, h2, h3, h4, label, input, textarea, button, li,
[data-testid="stMarkdownContainer"], [data-testid="stCaptionContainer"] {{
    font-family: 'Plus Jakarta Sans', sans-serif;
}}
.block-container {{ padding-top: 1.6rem; max-width: 1300px; }}
.hero {{
    background: linear-gradient(135deg, #0b1120 0%, #1e1b4b 100%);
    padding: 1.7rem 2rem; border-radius: 18px; color: #fff; margin-bottom: 1rem;
}}
.hero h1 {{ margin: 0; font-size: 28px; font-weight: 800; color: #fff; letter-spacing: -.4px; }}
.hero p {{ margin: 6px 0 0; color: #c7d2fe; font-size: 15px; }}
.fresh {{
    background: {GREEN[0]}; color: {GREEN[1]}; border: 1px solid {GREEN[2]};
    border-radius: 12px; padding: .7rem 1rem; font-size: 14px; margin-bottom: 1.2rem;
}}
.step {{ font-size: 13px; font-weight: 800; letter-spacing: .6px; text-transform: uppercase; color: #4f46e5; }}
.step-h {{ font-size: 20px; font-weight: 800; color: #0f172a; margin: 0 0 2px; }}
.pill {{
    display: inline-block; padding: 4px 11px; border-radius: 999px; font-size: 13px; font-weight: 700;
    border: 1px solid; margin: 0 6px 6px 0;
}}
.pill.green {{ background: {GREEN[0]}; color: {GREEN[1]}; border-color: {GREEN[2]}; }}
.pill.yellow {{ background: {YELLOW[0]}; color: {YELLOW[1]}; border-color: {YELLOW[2]}; }}
.pill.red {{ background: {RED[0]}; color: {RED[1]}; border-color: {RED[2]}; }}
.pill.gray {{ background: {GRAY[0]}; color: {GRAY[1]}; border-color: {GRAY[2]}; }}
.kpi {{
    border-radius: 14px; padding: 1rem 1.1rem; border: 1px solid var(--bd); background: var(--bg); height: 100%;
}}
.kpi .lbl {{ font-size: 13px; font-weight: 700; color: var(--fg); opacity: .9; }}
.kpi .val {{ font-size: 32px; font-weight: 800; color: var(--fg); line-height: 1.15; }}
.kpi .sub {{ font-size: 12px; color: var(--fg); opacity: .75; }}
.legend {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: .8rem 1rem; margin: .4rem 0 1rem; }}
.legend div {{ margin: 3px 0; font-size: 14px; color: #334155; }}
.howto {{ font-size: 13.5px; color: #334155; background: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 10px; padding: .6rem .9rem; }}
.howto ol {{ margin: .2rem 0 0 1.1rem; padding: 0; }}
</style>
""",
    unsafe_allow_html=True,
)


def pill(text: str, color: str) -> str:
    return f'<span class="pill {color}">{text}</span>'


def kpi(col, label, value, sub, colors):
    bg, fg, bd = colors
    col.markdown(
        f'<div class="kpi" style="--bg:{bg};--fg:{fg};--bd:{bd}"><div class="lbl">{label}</div>'
        f'<div class="val">{value}</div><div class="sub">{sub}</div></div>',
        unsafe_allow_html=True,
    )


# =====================================================================
# SECRETS / SETTINGS
# =====================================================================
def secret(name: str, default=""):
    try:
        return st.secrets.get(name, default)
    except Exception:  # noqa: BLE001 — no secrets file is fine
        return default


DEFAULTS = {
    "brd_key": secret("BRIGHTDATA_API_KEY"),
    "brd_zone": secret("BRIGHTDATA_ZONE"),
    "serpapi_key": secret("SERPAPI_KEY"),
    "serper_key": secret("SERPER_API_KEY"),
    "direct_delay": 5.0,
    "use_gsc": True, "use_brightdata": True, "use_serpapi": True, "use_serper": True, "use_direct": False,
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
    st.markdown('<div class="hero"><h1>🛡️ IndexPulse</h1><p>This tool is private. Enter the password.</p></div>',
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


def engine_status(e: str):
    """Returns (dot, text, color)."""
    if not st.session_state.get(f"use_{e}"):
        return "⚪", "Off", "gray"
    dead = st.session_state.get("dead", {}).get(e)
    if dead:
        return "🔴", f"Stopped last run: {dead}", "red"
    if not has_creds(e):
        return "🟡", "Add your key to use it", "yellow"
    return "🟢", "Ready", "green"


def ready_engines() -> list[str]:
    return [e for e in ENGINE_ORDER if st.session_state.get(f"use_{e}") and has_creds(e)]


# =====================================================================
# KEY TEST BUTTONS
# =====================================================================
def test_engine(e: str):
    cfgs = build_cfgs()
    try:
        if e == "serpapi":
            acct = core.serpapi_account(cfgs["serpapi"]["key"])
            left = acct.get("total_searches_left", acct.get("plan_searches_left", "?"))
            return "success", f"Works! You have {left} free searches left. (This test is free.)"
        if e == "gsc":
            c = cfgs["gsc"]
            sites = c.list_sites()
            if not sites:
                return "warning", (f"Logged in, but no sites found. In Search Console open your site → Settings → "
                                   f"Users and permissions → Add user → paste **{c.email}** → Full.")
            shown = ", ".join(sites[:5]) + (" …" if len(sites) > 5 else "")
            return "success", f"Works! Connected to {len(sites)} site(s): {shown}"
        out = core.ENGINE_FUNCS[e]("https://www.google.com/", cfgs[e], True)
        if out["verdict"] == V.UNKNOWN:
            return "error", out["detail"]
        return "success", "Works! (This test used 1 free check.)"
    except core.EngineDown as d:
        return "error", f"Not working: {d}"
    except Exception as ex:  # noqa: BLE001
        return "error", f"Not working: {ex.__class__.__name__}: {str(ex)[:120]}"


HOWTO = {
    "gsc": [
        "Open <a href='https://console.cloud.google.com/' target='_blank'>Google Cloud Console</a> → create a project → "
        "search <b>Google Search Console API</b> → Enable.",
        "Go to <b>IAM &amp; Admin → Service Accounts → Create</b>. Open it → <b>Keys → Add key → JSON</b>. A file downloads.",
        "In <a href='https://search.google.com/search-console' target='_blank'>Search Console</a>: your site → "
        "<b>Settings → Users and permissions → Add user</b> → paste the service-account email → <b>Full</b>.",
        "Upload the JSON file below. Done — it's free forever.",
    ],
    "brightdata": [
        "Sign up free at <a href='https://brightdata.com/products/serp-api' target='_blank'>brightdata.com</a> (no card needed).",
        "Go to <b>Proxies &amp; Scraping → Add → SERP API</b>. Give the zone a name, e.g. <code>serp_api1</code>.",
        "Copy the <b>zone name</b> and your <b>API key</b> (Account settings → API key) into the boxes below.",
    ],
    "serpapi": [
        "Sign up free at <a href='https://serpapi.com/users/sign_up' target='_blank'>serpapi.com</a>.",
        "Open your dashboard and copy <b>Your Private API Key</b> into the box below.",
    ],
    "serper": [
        "Sign up free at <a href='https://serper.dev' target='_blank'>serper.dev</a>.",
        "Open <b>API Key</b> and copy it into the box below.",
    ],
    "direct": [
        "No key needed. Google blocks this quickly, so keep it as the <b>last</b> backup.",
        "Works only when you run the tool on your own computer — not on cloud hosting.",
    ],
}


def engine_box(i: int, e: str):
    info = ENGINES[e]
    dot, text, _ = engine_status(e)
    with st.expander(f"{dot}  {i}. **{info.name}** — {info.free}  ·  {text}", expanded=False):
        st.markdown(f"**{info.note}**")
        st.caption(f"Free plan: {info.free} · {info.renew}")
        st.toggle("Use this method", key=f"use_{e}")

        steps = "".join(f"<li>{s}</li>" for s in HOWTO[e])
        st.markdown(f'<div class="howto"><b>How to get it (2 minutes):</b><ol>{steps}</ol></div>', unsafe_allow_html=True)
        st.write("")

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
                st.markdown(pill(f"Logged in as {c.email}", "green"), unsafe_allow_html=True)
            elif st.session_state.get("gsc_error") and gsc_info():
                st.error(st.session_state["gsc_error"])
        elif e == "brightdata":
            a, b = st.columns(2)
            a.text_input("API key", key="brd_key", type="password")
            b.text_input("Zone name", key="brd_zone", placeholder="serp_api1")
        elif e == "serpapi":
            st.text_input("API key", key="serpapi_key", type="password")
        elif e == "serper":
            st.text_input("API key", key="serper_key", type="password")
        elif e == "direct":
            st.slider("Pause between checks (seconds)", 3.0, 20.0, key="direct_delay", step=0.5)

        if st.button("Test this method", key=f"test_btn_{e}", disabled=not has_creds(e)):
            with st.spinner("Testing…"):
                st.session_state[f"test_{e}"] = test_engine(e)
            if st.session_state[f"test_{e}"][0] == "success":
                st.session_state.get("dead", {}).pop(e, None)
        res = st.session_state.get(f"test_{e}")
        if res:
            getattr(st, res[0])(res[1])


# =====================================================================
# HEADER
# =====================================================================
st.markdown(
    """
<div class="hero">
  <h1>🛡️ IndexPulse — Google Index Checker</h1>
  <p>Paste your links. For each one, you'll see if Google has that <b>exact</b> link — checked live, right now.</p>
</div>
<div class="fresh">✅ <b>Always fresh:</b> every link is checked against Google the moment you press <b>Check</b>.
Nothing is reused from earlier runs, and SerpApi's cache is turned off. Search Console also shows the date Google last crawled the page.</div>
""",
    unsafe_allow_html=True,
)

# =====================================================================
# STEP 1 — METHODS
# =====================================================================
st.markdown('<div class="step">Step 1</div><div class="step-h">Choose how to check</div>', unsafe_allow_html=True)
st.caption("All methods below are free. Turn on the ones you have keys for. They are tried from top to bottom — "
           "if one runs out of free credits, the next one takes over automatically.")

for i, e in enumerate(ENGINE_ORDER, start=1):
    engine_box(i, e)

ready = ready_engines()
chips = "".join(pill(f"{ENGINES[e].name}: ready", "green") for e in ready) or pill("No method ready yet", "red")
st.markdown(f"<div style='margin-top:.5rem'>{chips}</div>", unsafe_allow_html=True)
st.write("")

# =====================================================================
# STEP 2 — LINKS
# =====================================================================
st.markdown('<div class="step">Step 2</div><div class="step-h">Add your links</div>', unsafe_allow_html=True)
with st.container(border=True):
    source = st.radio("Where are your links?", ["Paste links", "From a sitemap"], horizontal=True)
    with st.expander("More options"):
        o1, o2, o3 = st.columns(3)
        strict_case = o1.toggle("Match capital letters exactly", value=True,
                                help="Google treats /Page and /page as two different links.")
        diagnose = o2.toggle("Find out why a link is not indexed", value=True,
                             help="Opens each non-indexed page and checks for errors, noindex, redirects and canonical.")
        workers = o3.slider("Checks at the same time", 1, 10, 5, help="Higher = faster. Lower it if you see 'Too many requests'.")
        max_sm = st.number_input("Max links to read from a sitemap", 100, 50_000, 5000, 100)

    raw_urls: list[str] = []
    if source == "Paste links":
        text = st.text_area(
            "One link per line",
            height=170,
            placeholder="https://www.trustindex.io/reviews/www.meyerlandfamilydentist.com\n"
                        "https://velog.io/@stories/How-to-Choose-the-Right-Dentist-in-Leander-TX",
        )
        raw_urls = re.split(r"\s+", text) if text else []
    else:
        c_in, c_btn = st.columns([4, 1])
        sm_url = c_in.text_input("Sitemap link", placeholder="https://example.com/sitemap.xml")
        c_btn.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        if c_btn.button("Read sitemap", width="stretch", disabled=not sm_url):
            with st.spinner("Reading sitemap…"):
                fetched, sm_errors = core.fetch_sitemap(sm_url, max_urls=int(max_sm))
            st.session_state["sm_links"], st.session_state["sm_errors"] = fetched, sm_errors
        raw_urls = st.session_state.get("sm_links", [])
        if st.session_state.get("sm_errors"):
            with st.expander(f"⚠️ {len(st.session_state['sm_errors'])} sitemap file(s) could not be read"):
                st.code("\n".join(st.session_state["sm_errors"]), language=None)

    urls, invalid, dupes = core.prepare_urls(raw_urls, strict_case)
    if raw_urls:
        info = pill(f"✓ {len(urls)} links ready", "green")
        if dupes:
            info += pill(f"{dupes} duplicates removed", "yellow")
        if invalid:
            info += pill(f"{len(invalid)} not valid links", "red")
        st.markdown(info, unsafe_allow_html=True)
        if invalid:
            with st.expander("Show the lines that are not valid links"):
                st.code("\n".join(invalid[:200]), language=None)

# =====================================================================
# STEP 3 — RUN
# =====================================================================
st.markdown('<div class="step">Step 3</div><div class="step-h">Check</div>', unsafe_allow_html=True)


def prepare_engines(engines: list[str]) -> list[str]:
    """Search Console needs its site list before it can route links."""
    if "gsc" in engines:
        c = gsc_client()
        try:
            if c.sites is None:
                c.list_sites()
            if not c.sites:
                st.warning(f"Search Console: no sites found for {c.email}. Add it as a user in Search Console. "
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
    bar = st.progress(0.0, text="Starting…")
    started = time.time()

    def on_progress(i, n, u, state):
        bar.progress(i / n, text=f"Checked {i} of {n}  ·  {u[:70]}")

    results, state = core.run_checks(link_list, engines, build_cfgs(), strict_case, diagnose, workers, on_progress)
    bar.empty()
    st.session_state["dead"] = dict(state.dead)
    return results, state, round(time.time() - started, 1)


reason = ""
if not urls:
    reason = "Add at least one link in Step 2."
elif not ready:
    reason = "Turn on at least one method and add its key in Step 1."
if reason:
    st.markdown(pill(reason, "yellow"), unsafe_allow_html=True)

if st.button(f"▶  Check {len(urls)} link{'s' if len(urls) != 1 else ''}", type="primary",
             width="stretch", disabled=bool(reason)):
    out = do_run(urls)
    if out:
        results, state, secs = out
        st.session_state["results"] = results
        st.session_state["run_meta"] = {"secs": secs, "used": dict(state.used), "dead": dict(state.dead),
                                        "at": core.now_utc()}

# =====================================================================
# RESULTS
# =====================================================================
results = st.session_state.get("results", [])
if results:
    meta = st.session_state.get("run_meta", {})
    st.write("")
    st.markdown('<div class="step-h">Results</div>', unsafe_allow_html=True)
    st.caption(f"Checked live on {meta.get('at', '')} · took {meta.get('secs', 0)} seconds")

    for e, why in meta.get("dead", {}).items():
        st.warning(f"**{ENGINES[e].name} stopped:** {why}. The next method took over for the remaining links.", icon="⚠️")

    n = {v: sum(r.verdict == v for r in results) for v in core.ALL_VERDICTS}
    checked = len(results) - n[V.UNKNOWN]
    rate = round(n[V.INDEXED] / checked * 100, 1) if checked else 0.0
    rate_colors = GREEN if rate >= 80 else YELLOW if rate >= 50 else RED

    k = st.columns(5)
    kpi(k[0], "Index rate", f"{rate}%", f"of {checked} links checked", rate_colors)
    kpi(k[1], "🟢 Indexed", n[V.INDEXED], "Google has the exact link", GREEN)
    kpi(k[2], "🟡 Another link shown", n[V.OTHER], "close, but not this exact link", YELLOW)
    kpi(k[3], "🔴 Not indexed", n[V.NOT], "Google doesn't have it", RED)
    kpi(k[4], "⚪ Couldn't check", n[V.UNKNOWN], "press Re-check below", GRAY)

    legend = "".join(f"<div><b>{v}</b> — {core.VERDICT_MEANING[v]}</div>" for v in core.ALL_VERDICTS)
    st.markdown(f'<div class="legend"><b>What the colors mean</b>{legend}</div>', unsafe_allow_html=True)

    used = meta.get("used", {})
    usage = "".join(
        pill(f"{ENGINES[e].name}: {c} check{'s' if c != 1 else ''}" + (" · stopped" if e in meta.get("dead", {}) else ""),
             "red" if e in meta.get("dead", {}) else "green")
        for e, c in used.items() if c or e in meta.get("dead", {})
    )
    if usage:
        st.markdown(f"<b>Methods used:</b> {usage}", unsafe_allow_html=True)

    f1, f2, f3 = st.columns([2.2, 2, 1.3])
    present = [v for v in core.ALL_VERDICTS if n[v]]
    chosen = f1.multiselect("Show", present, default=present)
    search = f2.text_input("Search links", placeholder="Type part of a link…")
    show_tech = f3.toggle("Show technical columns", value=False)

    unknown_urls = [r.url for r in results if r.verdict == V.UNKNOWN]
    if unknown_urls:
        if st.button(f"🔁  Re-check the {len(unknown_urls)} ⚪ link(s) that couldn't be checked", disabled=not ready):
            out = do_run(unknown_urls)
            if out:
                new, state, _ = out
                by_url = {r.url: r for r in new}
                st.session_state["results"] = [by_url.get(r.url, r) for r in results]
                st.session_state["run_meta"]["dead"] = dict(state.dead)
                for e, c in state.used.items():
                    st.session_state["run_meta"]["used"][e] = st.session_state["run_meta"]["used"].get(e, 0) + c
                st.rerun()

    COLS = {
        "url": "Link", "verdict": "Result", "detail": "Why", "likely_cause": "Likely cause",
        "engine": "Checked with", "proof_link": "Proof", "matched_url": "Google shows this link",
        "last_crawl": "Last crawled by Google", "checked_at": "Checked at",
        "serp_title": "Google title", "http_status": "Page status", "robots": "Robots / indexing",
        "page_canonical": "Page canonical", "final_url": "Redirects to", "canonical": "Match key",
        "attempts": "Fallback log",
    }
    BASIC = list(COLS.values())[:9]

    df = pd.DataFrame([asdict(r) for r in results]).rename(columns=COLS)[list(COLS.values())]
    view = df[df["Result"].isin(chosen)]
    if search:
        view = view[view["Link"].str.contains(search, case=False, regex=False)]
    shown = view if show_tech else view[BASIC]

    def color_result(v):
        c = core.VERDICT_COLORS.get(v)
        return f"background-color:{c[0]};color:{c[1]};font-weight:700" if c else ""

    styler = shown.style
    styler = styler.map(color_result, subset=["Result"]) if hasattr(styler, "map") else styler.applymap(color_result, subset=["Result"])

    st.dataframe(
        styler,
        width="stretch",
        hide_index=True,
        height=min(36 * (len(shown) + 1) + 6, 620),
        column_config={
            "Link": st.column_config.LinkColumn(width="large"),
            "Result": st.column_config.TextColumn(width="medium"),
            "Why": st.column_config.TextColumn(width="large"),
            "Proof": st.column_config.LinkColumn(display_text="Open ↗", width="small",
                                                 help="Open Google (or Search Console) and see it yourself"),
            "Google shows this link": st.column_config.LinkColumn(width="medium"),
            "Page canonical": st.column_config.LinkColumn(width="medium"),
            "Redirects to": st.column_config.LinkColumn(width="medium"),
        },
    )
    st.caption(f"Showing {len(view)} of {len(df)} links. Click **Open ↗** in the Proof column to see the evidence yourself.")

    # ---------- EXPORT ----------
    st.markdown('<div class="step-h" style="margin-top:1rem">Download</div>', unsafe_allow_html=True)
    summary = {
        "Total links": len(results), "Indexed": n[V.INDEXED], "Google shows another link": n[V.OTHER],
        "Not indexed": n[V.NOT], "Couldn't check": n[V.UNKNOWN], "Index rate": f"{rate}%",
        "Checked at": meta.get("at", ""),
        "Methods used": ", ".join(f"{ENGINES[e].name} ({c})" for e, c in used.items() if c),
    }
    stamp = time.strftime("%Y%m%d_%H%M")
    d1, d2 = st.columns(2)
    d1.download_button("📊  Excel file (colored, with summary)", data=core.to_excel(df, summary),
                       file_name=f"index_check_{stamp}.xlsx", width="stretch",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    d2.download_button("📄  CSV file", data=df.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"index_check_{stamp}.csv", mime="text/csv", width="stretch")
    with st.expander("📋  Copy into Google Sheets"):
        st.caption("Click the copy icon (top-right of the box), then paste into Google Sheets.")
        st.code(shown.to_csv(sep="\t", index=False), language=None)
