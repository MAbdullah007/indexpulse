# Features

| Feature | You give | You get | Code | Limits |
|---|---|---|---|---|
| Password gate | `APP_PASSWORD` secret | the app opens | app.py top | one shared password |
| Provider cards (step 1) | toggle, key, **Test** | status: grey Off · yellow Key missing / Not tested yet · green Working · orange Only N left (SerpApi) · red Test failed / Stopped | `provider_card`, `engine_status`, `test_engine` | Test costs 1 check for Bright Data / Serper; free for SerpApi and Search Console |
| Links (step 2) | pasted text or a sitemap link | N ready · duplicates removed · lines that are not links (listed) | `core.split_input`, `prepare_urls`, `fetch_sitemap` | sitemap: index files, .gz, max N links (option); a sitemap is not always every page |
| Options | match capital letters, find out why, checks at the same time, max sitemap links | | session keys `strict_case`, `diagnose`, `workers`, `max_sm` | |
| Check (step 3) | the button "Check N links" | progress "Checking i of N", results; a stopped run keeps the finished links | `do_run`, `core.run_checks(on_result=…)` | SerpApi free: 50/hour |
| Results (step 4) | | message (ready / N couldn't be checked / not complete), index rate, 5 cards (click = filter), methods used, Re-check, table (search, method filter, sort by column, More columns), click a row = all details | | |
| Download | shown rows or all | Excel (coloured result, filter, frozen header, Summary sheet), CSV (UTF-8 BOM), copy for Google Sheets | `core.to_excel`, `to_csv`, `to_tsv` | |
| Help & accuracy | | result meanings, why methods differ, free allowances with sources, input rules | bottom of app.py | |

Results: 🟢 Indexed · 🟡 Another link shown · 🟠 Not found on Google (search) · 🔴 Not indexed (Search Console only) · ⚪ Couldn't check.
