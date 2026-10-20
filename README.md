# 🛡️ IndexPulse — Live Google Index Checker

Links paste karein, tool har link ke liye **live** batata hai ke Google ke paas woh **exact** link hai ya nahi.

| Color | Matlab |
|---|---|
| 🟢 **Indexed** | Google ke paas yehi exact link hai |
| 🟡 **Not indexed — Google shows another link** | Google koi milta-julta page dikha raha hai, yeh exact link nahi |
| 🔴 **Not indexed** | Google ke paas yeh link nahi hai |
| ⚪ **Couldn't check** | Check fail hua (block, credits khatam, internet). **Re-check** dabayein |

Har result ke saath **Proof ↗** link hota hai — click karke khud Google (ya Search Console) mein dekh lein.

---

## Free checking methods (upar se neeche try hote hain)

| # | Method | Free | Kab use hota hai |
|---|---|---|---|
| 1 | **Google Search Console** | 2,000 / din per site | Sirf aapki apni verified sites. Sabse accurate + last crawl date |
| 2 | **Bright Data SERP API** | 5,000 / mahina (har 1 tareekh renew) | Backlinks — sab se best free option |
| 3 | **SerpApi** | 250 / mahina | Backup (cache off — hamesha fresh) |
| 4 | **Serper** | 2,500 (ek baar) | Backup |
| 5 | **Direct Google** | Free, no key | Sirf apne computer par. Cloud par Google foran block karta hai |

Agar ek method ke credits khatam ho jayein, ya key ghalat ho, toh tool **khud** agle method par chala jata hai.

### "Purana status" wala masla kyun nahi aata?
- Har link **Check** dabate waqt live Google se poocha jata hai — pichli run ka koi result dobara use nahi hota.
- SerpApi ka cache band hai (`no_cache=true`).
- Google Custom Search API use **nahi** ki gayi — us ka index google.com se alag/purana hota hai, aur woh API naye users ke liye band ho chuki hai (1 Jan 2027 ko poori band).
- Search Console batata hai Google ne page **kab** last crawl kiya.

---

## Online chalayein (free) — GitHub + Streamlit Community Cloud

1. **GitHub** par account banayein → **New repository** → naam rakhein (jaise `indexpulse`) → **Private** chunein.
2. Yeh files upload karein (**Add file → Upload files**):
   ```
   app.py
   core.py
   requirements.txt
   README.md
   .gitignore
   .streamlit/config.toml
   tests/test_core.py
   ```
   ⚠️ `secrets.toml` ya Google ki JSON key **kabhi** GitHub par upload na karein.
3. **https://share.streamlit.io** kholein → **GitHub se sign in** karein.
4. **Create app** → apni repository chunein → Branch: `main` → Main file: `app.py`.
5. **Advanced settings → Secrets** mein `.streamlit/secrets.toml.example` ka content paste karein aur apni keys bhar dein.
   **`APP_PASSWORD` zaroor rakhein** — warna jis ke paas link hoga woh aapke free credits use kar sakta hai.
6. **Deploy** dabayein. 2–3 minute mein aapka link mil jayega, jaise `https://indexpulse.streamlit.app`.

> Free hosting par app kuch der use na ho toh "so" jati hai. Link kholne par bas **wake up** dabayein, 30 second mein chal padti hai.

Keys baad mein badalni hon: Streamlit Cloud → apni app → **Settings → Secrets**.

---

## Apne computer par chalayein

```bash
pip install -r requirements.txt
streamlit run app.py
```
Keys har baar paste na karni hon toh `.streamlit/secrets.toml.example` ko copy karke `.streamlit/secrets.toml` bana lein aur keys bhar dein.

---

## Keys kaise lein

**Bright Data (5,000/mahina):** brightdata.com par free sign up → *Proxies & Scraping → Add → SERP API* → zone ka naam (jaise `serp_api1`) → *Account settings* se API key copy karein.

**SerpApi (250/mahina):** serpapi.com par sign up → dashboard se *Private API Key* copy karein.

**Serper (2,500 ek baar):** serper.dev par sign up → *API Key* copy karein.

**Google Search Console (free):**
1. console.cloud.google.com → naya project → **Google Search Console API** enable karein.
2. *IAM & Admin → Service Accounts → Create* → *Keys → Add key → JSON* (file download hogi).
3. Search Console → apni site → *Settings → Users and permissions → Add user* → service account ka email → **Full**.
4. JSON file app mein upload karein, ya poori file Notepad mein khol kar copy karein aur Secrets mein `GSC_JSON = '''` aur `'''` ke beech paste kar dein.

Har method ke box mein **Test this method** button hai — key sahi hai ya nahi, foran pata chal jata hai.
(SerpApi aur Search Console ka test free hai; Bright Data/Serper ka test 1 free check use karta hai.)

---

## Tests

```bash
pip install pytest
pytest -q
```
Tests fake API replies use karte hain — koi credit kharch nahi hota, internet ki zaroorat nahi.
