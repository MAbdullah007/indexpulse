"""Real-browser check (Playwright + Chromium): layout at 1366 / 768 / 390 px with no sideways scroll, the full flow,
clicking a row opens its details, the CSV download works. Fake engines, invented links. Skipped if Playwright is missing.
Run: pytest -q tests/ui/test_browser.py   (screenshots in tests/ui/_out/)"""
import csv
import io
import os
import socket
import subprocess
import sys
import time

import pytest

pw = pytest.importorskip("playwright.sync_api")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(HERE, "_out")
LINKS = "\n".join(["https://shop-a.example/", "https://shop-a.example/about/", "https://dir-one.example/listing/shop-a-dental",
                   "https://dir-two.example/profile/shop-a", "https://dir-three.example/shop-a", "https://dir-four.example/biz/shop-a",
                   "dir-five.example/x", "not a link"])


@pytest.fixture(scope="module")
def server():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    p = subprocess.Popen([sys.executable, "-m", "streamlit", "run", os.path.join(HERE, "harness_app.py"), "--server.port", str(port),
                          "--server.headless", "true", "--browser.gatherUsageStats", "false"], cwd=ROOT,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            break
        except OSError:
            time.sleep(0.5)
    time.sleep(2)
    yield f"http://127.0.0.1:{port}/"
    p.terminate()


@pytest.mark.parametrize("w", [1366, 768, 390])
def test_flow_and_layout(server, w):
    os.makedirs(OUT, exist_ok=True)
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": w, "height": 5200 if w < 500 else 3800}, accept_downloads=True)
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(server)
        pg.get_by_text("Choose how to check").first.wait_for(timeout=30000)
        assert pg.locator(".ip-nav a").count() == 5
        ta = pg.locator("textarea").first
        ta.fill(LINKS); ta.press("Control+Enter")
        pg.get_by_text("7 links ready").wait_for(timeout=15000)
        pg.get_by_role("button", name="Check 7 links").click()
        pg.get_by_text("could not be checked", exact=False).first.wait_for(timeout=30000)
        assert pg.get_by_text("Index rate").count() == 1
        sw = pg.evaluate("[document.documentElement.scrollWidth, innerWidth]")
        assert sw[0] <= sw[1], f"sideways scroll at {w}px: {sw}"
        pg.screenshot(path=os.path.join(OUT, f"results-{w}.png"), full_page=True)
        if w == 1366:
            pg.locator(".st-key-card_2 button").first.click()
            pg.get_by_text("Showing 2 of 7 links", exact=False).wait_for(timeout=15000)
            with pg.expect_download() as d:
                pg.get_by_role("button", name="📄  CSV").click()
            rows = list(csv.reader(io.StringIO(open(d.value.path(), encoding="utf-8-sig").read())))
            assert rows[0][0] == "Link" and len(rows) == 3 and "Result (words)" in rows[0]
            # click a row in the table -> details
            box = pg.locator("[data-testid='stDataFrame']").first.bounding_box()
            pg.mouse.click(box["x"] + 20, box["y"] + 36 + 18)
            pg.wait_for_timeout(1500)
            pg.screenshot(path=os.path.join(OUT, "row-click.png"))
            pg.get_by_text("Usually it is not indexed", exact=False).first.wait_for(timeout=15000)
        b.close()
        assert not errors, errors
