# Architecture

```
app.py (Streamlit page)  ──calls──▶  core.py
  secrets / session_state            run_checks(urls, engines, cfgs, …)  ── ThreadPoolExecutor (workers 1–10)
  provider cards + Test                 └─ check_one(url): for each engine in order (gsc → brightdata → serpapi → serper → direct)
  links input (split_input)                   ENGINE_FUNCS[e](url, cfg, strict) → {verdict, detail, …}
  results, filters, exports                   Skip       → next engine for THIS link (e.g. not your Search Console site)
                                              EngineDown → engine stopped for the rest of the run (no credits, wrong key, blocked)
                                              Couldn't check → try the next engine; the first clear answer wins
                                           page_diagnostics(): opens the page (status, redirects, noindex, canonical) when a
                                           search did not show the exact link (not for Search Console answers)
```

## Engines (core.py)
| Engine | How | Answer |
|---|---|---|
| `check_gsc` | URL Inspection API, service-account JSON (`GSCClient`, routes each link to the matching property) | Indexed / Not indexed / another canonical, last crawl |
| `check_brightdata` | `POST api.brightdata.com/request` with a Google `site:` search URL + `brd_json=1`; reads parsed JSON, JSON wrapped in `body`, or Google HTML (`parse_google_html`); one retry on a non-search reply | search shows / does not show the link |
| `check_serpapi` | `serpapi.com/search.json`, `no_cache=true`; `serpapi_account` (free) gives the live balance | same |
| `check_serper` | `google.serper.dev/search` | same |
| `check_direct` | google.com HTML, one request at a time with a pause (`parse_google_html`) | same, often blocked |

`judge(target, items)` turns search results into a verdict: exact match (canonical_url: no www, no trailing /, no tracking
params, path case kept unless "Match capital letters" is off) → Indexed; same link other case / other page of the site /
other site → Another link shown; no results → Not found on Google.

## Data
`CheckResult` (one row): url, verdict, detail, engine, proof_link, matched_url, serp_title, last_crawl, likely_cause,
http_status, robots, page_canonical, final_url, canonical (match key), checked_at, attempts (methods tried).
Session state (app.py): `results`, `run_meta` (at, secs, used per engine, dead engines, total, partial), `tested`
(per engine: ok/fail, message, time, live balance), `dead`, `flt` (card filter), `partial` (a run in progress; kept if stopped).

## Dependencies
streamlit, pandas, requests (+urllib3 Retry), beautifulsoup4, defusedxml (sitemaps), openpyxl (Excel), google-auth (Search Console).
