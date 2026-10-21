# IndexPulse — start here (for Claude / developers)

A Streamlit app that checks whether links are on Google (owner: Abdullah; answer him in Roman Urdu, short and clear).
Live on Streamlit Community Cloud from `main` (redeploys by itself after a push). Also shown inside the SEO Ops tool
(MAbdullah007/seo-operations-platform → "Backlink Indexing" page) in a frame.

## Files
- `core.py` — all logic, no Streamlit: engines, verdicts, URL rules, sitemap, page diagnostics, runner, exports. Unit-tested.
- `app.py` — the page only (layout, state, buttons). Order: header → 1 methods → 2 links → 3 check → 4 results → download → help.
- `tests/test_core.py` (engines with fake replies), `tests/ui/test_app.py` (Streamlit AppTest), `tests/ui/test_browser.py`
  (Playwright, 1366/768/390 px), `tests/ui/harness_app.py` (runs the real app.py with fake engines, no keys).
- `docs/`: ARCHITECTURE, FEATURES, TESTING, UI_GUIDELINES, KNOWN_LIMITATIONS. Read the one for your task.

## Commands
- Run: `streamlit run app.py` (keys: copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`).
- Tests: `pip install pytest playwright && pytest -q` (no keys, no credits, no internet). Without Playwright the browser test is skipped.
- Try the UI without keys: `streamlit run tests/ui/harness_app.py`.

## Rules that never change
- Never claim more than a method can prove: a search API that shows nothing = **Not found on Google** (orange), never
  "Not indexed". Only Search Console can say **Not indexed** (red). A failed check = **Couldn't check** (grey), never counted.
- A method is **green** only after a real success (Test button, or it answered in a check). A typed key = yellow "Not tested yet".
- Quotas come from the provider's own page with the date checked (`QUOTA_CHECKED`, `EngineInfo.source`). Never invent
  balances or expiry dates; only SerpApi's Test returns a live balance.
- No secrets in the repo, exports or logs. `APP_PASSWORD` protects the credits.
- No arbitrary voting between methods: the first clear answer is used, the others are listed in "Methods tried".
- Exports: CSV UTF-8 with BOM; cells starting with = + - @ stay text (`cell_safe`); Excel never writes formulas.
- After a change: run `pytest -q`, update the doc that describes what you changed.
