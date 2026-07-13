r"""
get_demographics.py  (.env driven, Company column)
==================================================
Scrapes the "Ratings by demographic groups" section from a Glassdoor company
Culture/DEI page and writes it to its OWN Excel file (demographic_ratings.xlsx).
Every row carries the company name.

It walks every demographic tab - Race/Ethnicity, Gender, Sexual orientation,
Disability, Parent or family caregiver, Veteran status, and any others behind
the ">" chevron - and records each group's rating and ratings count.

Settings come from a .env file next to this script:
    COMPANY_NAME=HealthTrust Workforce Solutions
    DEMOGRAPHIC_URL=https://www.glassdoor.com/Culture/...DEI-E2502893.htm
(This must be the Culture/DEI page - that's where the demographic section lives.)

Same setup as the other scripts: attaches to your already-logged-in Chrome, so
keep that Chrome (launched with --remote-debugging-port=9222) open.

Needs:
    pip install openpyxl python-dotenv

Run:
    python get_demographics.py
    python get_demographics.py --debug    # dumps the section HTML if needed
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from openpyxl import Workbook

# ---------------------------------------------------------------------------
load_dotenv(Path(__file__).parent / ".env")
COMPANY_NAME = os.getenv("COMPANY_NAME", "").strip()
DEI_URL = os.getenv("DEMOGRAPHIC_URL", "").strip()

CDP_URL = "http://localhost:9222"
OUT_XLSX = Path(__file__).parent / "demographic_ratings.xlsx"
OUT_PARQUET = Path(__file__).parent / "demographics.parquet"

# columns in the cumulative store, and the key that identifies one group row
FIELDS = ["company_name", "category", "group", "rating", "num_ratings"]
DEDUP_SUBSET = ["company_name", "category", "group"]
# ---------------------------------------------------------------------------

# Shared JS helpers, prepended to each evaluate() call below.
HELPERS = r"""
  // smallest ancestor of the heading that also contains the tab row
  const demoSection = () => {
    const h = [...document.querySelectorAll('h1,h2,h3,h4,div,span,p')].find(
      n => /Ratings by demographic groups/i.test(n.textContent) && n.children.length < 3);
    if (!h) return null;
    let el = h;
    for (let i = 0; i < 8 && el; i++) {
      if (/Race\s*\/\s*Ethnicity/i.test(el.textContent) && /Gender/i.test(el.textContent)) return el;
      el = el.parentElement;
    }
    return h.closest('section,div') || h.parentElement || document.body;
  };

  // page-nav labels we must NOT click (they navigate away)
  const NAV = /^(About|Reviews|Pay|Jobs|Interviews|Salaries|Benefits|Photos|Diversity|Overview|Follow)\b/i;
  const DEMO = /^(Race|Gender|Sexual|Disability|Parent|Veteran|Age|Religion|Caregiver|Transgender|Neuro|Ethnic)/i;

  // only the demographic tabs, scoped inside the section
  const getTabs = () => {
    const sec = demoSection();
    if (!sec) return [];
    let tabs = [...sec.querySelectorAll('[role="tab"]')];
    if (!tabs.length) tabs = [...sec.querySelectorAll('button,a')];
    return tabs.filter(t => {
      const x = (t.textContent || '').trim();
      return x && !NAV.test(x) && DEMO.test(x);
    });
  };
"""

LIST_TABS_JS = "() => {" + HELPERS + " return getTabs().map(t => t.textContent.trim()); }"

CLICK_TAB_JS = ("(i) => {" + HELPERS +
                " const tabs = getTabs();"
                " if (tabs[i]) { tabs[i].scrollIntoView(); tabs[i].click(); return true; }"
                " return false; }")

EXTRACT_CARDS_JS = "() => {" + HELPERS + r"""
  const panel = demoSection() || document.body;

  // each card is anchored by its "N ratings" / "No ratings" line
  const countNodes = [...panel.querySelectorAll('*')].filter(
    n => n.children.length === 0 &&
         /^(No ratings|[\d,]+\s+ratings?)$/i.test((n.textContent || '').trim()));

  const out = [];
  countNodes.forEach(cn => {
    let card = cn.parentElement;
    for (let i = 0; i < 4 && card; i++) {
      const L = (card.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
      if (L.length >= 3) break;
      card = card.parentElement;
    }
    if (!card) return;
    const L = (card.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
    if (L.length < 2) return;

    const count = L[L.length - 1];
    const rating = /^[0-5]\.\d$/.test(L[0]) ? L[0] : null;   // "-" -> null
    let name = L.slice(1, L.length - 1).join(' ').trim();
    if (!name) name = L[0];   // safety

    // un-truncate names like "Indigenous American or..."
    if (/[.\u2026]{1,3}$/.test(name)) {
      const titled = card.querySelector('[title]');
      if (titled && titled.getAttribute('title')) name = titled.getAttribute('title').trim();
    }

    const numM = count.match(/([\d,]+)/);
    out.push({
      group: name,
      rating: rating,
      num_ratings: numM ? parseInt(numM[1].replace(/,/g, '')) : 0,
    });
  });

  const seen = new Set();
  return out.filter(r => r.group && !DEMO.test(r.group) && !seen.has(r.group) && seen.add(r.group));
}
"""


def append_to_parquet(rows):
    """Append this run's groups to demographics.parquet, de-duped by
    company + category + group (re-runs refresh rating/count). Creates the
    file if it doesn't exist."""
    recs = [{
        "company_name": COMPANY_NAME,
        "category": r["category"],
        "group": r["group"],
        "rating": r["rating"],
        "num_ratings": r["num_ratings"],
    } for r in rows]
    new_df = pd.DataFrame(recs, columns=FIELDS)

    if OUT_PARQUET.exists():
        try:
            old_df = pd.read_parquet(OUT_PARQUET)
        except Exception as e:
            print(f"  (could not read existing parquet, starting fresh: {e})")
            old_df = pd.DataFrame(columns=FIELDS)
        combined = pd.concat([old_df, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=DEDUP_SUBSET, keep="last").reset_index(drop=True)
        added = len(combined) - len(old_df)
        print(f"  parquet: had {len(old_df)}, +{max(added,0)} new "
              f"(re-runs refresh existing) -> {len(combined)} total")
    else:
        combined = new_df
        print(f"  parquet: created with {len(combined)} rows")

    combined.to_parquet(OUT_PARQUET, index=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    if not DEI_URL:
        print("No DEMOGRAPHIC_URL found in .env (next to this script).")
        print("Add a line like:")
        print("  DEMOGRAPHIC_URL=https://www.glassdoor.com/Culture/Company-DEI-E######.htm")
        print("(must be the Culture/DEI page; no quotes, whole URL on one line)")
        return 1
    if not COMPANY_NAME:
        print("Note: COMPANY_NAME is empty in .env - the Company column will be blank.")

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print("Could not attach to Chrome on", CDP_URL,
                  "- is it still open with --remote-debugging-port=9222?")
            print("Details:", e)
            return 1

        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(DEI_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        body = page.evaluate("() => document.body.innerText.toLowerCase()")
        if "are you a human" in body or "verify you are" in body:
            print("Human-check page is showing. Solve it in Chrome, then re-run.")
            return 0

        if args.debug:
            html = page.evaluate("() => {" + HELPERS +
                                 " const s = demoSection(); return s ? s.outerHTML : 'SECTION NOT FOUND'; }")
            Path(Path(__file__).parent / "demographics_section.html").write_text(html, encoding="utf-8")
            print("Wrote demographics_section.html - paste it back if extraction looks wrong.")
            return 0

        tabs = page.evaluate(LIST_TABS_JS)
        if not tabs:
            print("Found no demographic tabs. Try --debug and send me the HTML.")
            return 1
        print("Demographic tabs found:", tabs)

        rows = []
        for i, label in enumerate(tabs):
            ok = page.evaluate(CLICK_TAB_JS, i)
            if not ok:
                print(f"  [{label}] could not click")
                continue
            page.wait_for_timeout(1500)
            cards = page.evaluate(EXTRACT_CARDS_JS)
            for c in cards:
                c["category"] = label
            rows.extend(cards)
            print(f"  [{label}] {len(cards)} groups")

    wb = Workbook()
    ws = wb.active
    ws.title = "Demographic ratings"
    ws.append(["Company", "Category", "Group", "Rating", "Num ratings"])
    for r in rows:
        ws.append([COMPANY_NAME, r["category"], r["group"], r["rating"], r["num_ratings"]])
    for col, w in zip("ABCDE", (28, 24, 36, 10, 12)):
        ws.column_dimensions[col].width = w
    wb.save(OUT_XLSX)

    if rows:
        append_to_parquet(rows)

    print(f"\nDone. {len(rows)} rows for '{COMPANY_NAME}' this run.")
    print(f"  snapshot   -> {OUT_XLSX.name}")
    print(f"  cumulative -> {OUT_PARQUET.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())