# UI guidelines

- **One flow, numbered:** 1 Choose how to check → 2 Add links → 3 Check → 4 Results, then Download and Help & accuracy.
  A sticky step bar links to each. Each step title has one line: what it does / what to enter / what happens next.
- **Colours mean one thing everywhere.**
  Results: green Indexed · yellow Another link shown · orange Not found on Google · red Not indexed (Search Console) · grey Couldn't check.
  Method status: green working (proven) · yellow setup incomplete / not tested · orange limited (few searches left) · red error · grey off.
  Never colour alone: every pill and card also says it in words.
- **Words:** plain and short. Buttons say what happens ("Check 7 links", "Re-check the 2 links that could not be checked",
  "Test Serper (uses 1 check)"). Messages say the outcome ("Results are ready", "Not complete: 4 of 9 links checked").
  Never "No action needed" unless the evidence says so; never present a search's silence as proof.
- **Progressive disclosure:** setup steps, keys, options, extra columns and help live in expanders; the default table has
  7 columns (Result first, so phones see it), "More columns" shows the rest, a row click shows everything for one link.
- **Layout:** max width 1180 px; cards in 3 columns (Streamlit stacks them on phones); no sideways page scroll at 390 px
  (the table scrolls inside itself). Font Plus Jakarta Sans; radius 10–14 px; borders #e2e8f0; brand #4f46e5.
- **CSS:** scoped selectors only (a global `*` font rule breaks Streamlit icons). Result cards are buttons styled through
  `st.container(key="card_i")` → `.st-key-card_i`.
