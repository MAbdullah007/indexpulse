# Testing

```bash
pip install -r requirements.txt pytest playwright   # Chromium: python -m playwright install chromium (once)
pytest -q                                           # everything: no keys, no credits, no internet
pytest -q tests/test_core.py                        # logic only (fast)
pytest -q tests/ui/test_app.py                      # page flows (Streamlit AppTest)
pytest -q tests/ui/test_browser.py                  # real browser, 1366 / 768 / 390 px, screenshots in tests/ui/_out/
streamlit run tests/ui/harness_app.py               # click through the page yourself with fake engines
```

| File | Covers |
|---|---|
| `tests/test_core.py` | URL rules, input splitting, every engine with fake replies (indexed, not found, wrong key, no credits, rate limit), Bright Data HTML / wrapped JSON / retry / CAPTCHA, Search Console routing, fallback order, sitemap, verdict honesty, quotas have sources |
| `tests/ui/test_app.py` | first screen is honest (nothing "working" before a test), links → Check → cards → card filter on/off, status turns green after a real answer, a stopped run keeps its results, CSV / tab / Excel are formula-safe |
| `tests/ui/test_browser.py` | no sideways scroll at 3 widths, full flow, card filter, CSV download contents, clicking a row opens its details, no page errors |

Fake engines live in `tests/ui/harness_app.py` (invented `.example` links). When a real provider changes its reply format,
add the new reply as a fake in `tests/test_core.py` first, then fix `core.py`.

Before a release: `pytest -q` green, then open the live app → Test each method once (1 credit each for Bright Data / Serper).
