# Known limitations

## Free allowances (checked 21 Oct 2026, from each provider's own page)
| Method | Allowance | Kind | Renewal / expiry | Source |
|---|---|---|---|---|
| Google Search Console | 2,000 URL inspections per day per site, 600 per minute (project: 10,000,000/day) | daily | every day | https://developers.google.com/webmaster-tools/limits |
| Bright Data | 5,000 free credits per month, shared with its other products; 1 SERP request = 1 credit | monthly | resets on the 1st, no roll-over; not on paid pre-commit plans; unfunded accounts max 1,000 requests/min | https://docs.brightdata.com/general/account/billing-and-pricing/free-tier |
| SerpApi | Free plan: 250 searches per month, 50 per hour | monthly | the pricing page does not state the reset day; the Test button shows the live balance | https://serpapi.com/pricing |
| Serper | 2,500 free queries on sign-up | sign-up credit | serper.dev does not say if they renew or expire (third-party sites say one-time; paid credits last 6 months) | https://serper.dev |
| Direct Google | none | — | blocked quickly (CAPTCHA), almost at once on cloud hosting | — |

These are published numbers, not live balances (except SerpApi). Providers change them: re-check and update
`core.ENGINES` + `QUOTA_CHECKED` + this table.

## Accuracy
- A search API runs `site:<link>` on Google. Not seeing the link does **not** prove it is not indexed (country, time,
  Google's own choices). Shown as **Not found on Google**, never **Not indexed**.
- Search Console is Google's answer for sites the service account can see; it can be a few days behind live search.
- "Another link shown" can mean a different capital-letter version, another page of the same site, or other sites only (see Why).
- Page diagnostics open the page from the server: some sites block datacenters, so "Page status" can differ from a browser.

## Fixed after review (21 Oct 2026)
Stopping a check now cancels the links not started (no more credits spent); a stopped Re-check keeps every earlier row;
a search whose words contain "recaptcha" is no longer read as a CAPTCHA; a method whose every reply was "Couldn't check" no
longer turns green; an empty Search Console reply is "Couldn't check", not "Not indexed"; the password works in any language;
control characters no longer break the Excel export; GSC_JSON works as pasted text with line breaks or as a TOML table;
the row details follow the filtered table; commas inside links are kept.

## Open
- Bright Data: in a real run (Oct 2026) some replies were "not search results". Now read as JSON, wrapped JSON or Google HTML,
  retried once, and the message says what came back; if it stays, check the zone is a **SERP API** zone.
- A check runs inside the page: closing or changing the page stops it (finished links are kept and shown as "Not complete").
- No history between sessions (Streamlit Cloud has no storage here): download the Excel to keep results.
