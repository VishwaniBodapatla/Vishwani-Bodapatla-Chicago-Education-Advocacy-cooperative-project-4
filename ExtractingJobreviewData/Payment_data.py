r"""
get_salaries.py  (.env driven, Company column)
==============================================
Scrapes the "Pay & benefits" (Salaries) page of a Glassdoor company - every job
title with its salary range and number of submitted salaries - paginating like a
human until the last page, and writes it to its OWN Excel file (salaries.xlsx).
Every row carries the company name.

Settings come from a .env file next to this script:
    COMPANY_NAME=HealthTrust Workforce Solutions
    PAYMENT_URL=https://www.glassdoor.com/Salary/...Salaries-E2502893.htm?filter.jobTitleExact=Registered+Nurse&jobTitleId=50005
- Filtered to ONE role via filter.jobTitleExact=... (as above), OR
- Leave the query off the URL to scrape ALL job titles.
Any _P<n> page number in the URL is ignored - the script pages through on its own.

Same setup as before: attaches to your already-logged-in Chrome, so keep that
Chrome (launched with --remote-debugging-port=9222) open and signed in.

Needs:
    pip install openpyxl python-dotenv

Run:
    python get_salaries.py
    python get_salaries.py --debug    # dumps the first salary row's HTML

Output columns: Company | Page | Job title | Pay range | Min | Max | Per | Salaries submitted
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from openpyxl import Workbook

# ---------------------------------------------------------------------------
load_dotenv(Path(__file__).parent / ".env")
COMPANY_NAME = os.getenv("COMPANY_NAME", "").strip()
PAYMENT_URL = os.getenv("PAYMENT_URL", "").strip()

CDP_URL = "http://localhost:9222"
PAGE_DELAY = 20.0          # seconds between pages (only matters if multi-page)
MAX_PAGES = 40             # safety cap; loop stops earlier on its own
OUT_XLSX = Path(__file__).parent / "salaries.xlsx"
OUT_PARQUET = Path(__file__).parent / "salaries.parquet"

# columns in the cumulative store, and the key that identifies one salary row
FIELDS = ["company_name", "page", "job_title", "pay_range",
          "min", "max", "per", "num_salaries"]
DEDUP_SUBSET = ["company_name", "job_title"]
# ---------------------------------------------------------------------------


def split_salary_url(url: str):
    """'.../Salaries-E2502893_P2.htm?filter...' -> ('.../Salaries-E2502893', '?filter...')"""
    parts = urlsplit(url)
    path = re.sub(r"_P\d+\.htm$", "", parts.path)   # drop _P<n>.htm
    path = re.sub(r"\.htm$", "", path)              # or plain .htm
    base = urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    query = ("?" + parts.query) if parts.query else ""
    return base, query


BASE, QUERY = split_salary_url(PAYMENT_URL) if PAYMENT_URL else ("", "")


def page_url(n: int) -> str:
    return f"{BASE}.htm{QUERY}" if n <= 1 else f"{BASE}_P{n}.htm{QUERY}"


EXTRACT_JS = r"""
() => {
  // each salary row is anchored by its "N Salaries submitted" line
  const counts = [...document.querySelectorAll('*')].filter(
    n => n.children.length === 0 && /\bSalaries?\s+submitted\b/i.test(n.textContent || ''));

  const out = [];
  counts.forEach(cn => {
    // climb until the row also shows a "$" salary figure
    let row = cn.parentElement;
    for (let i = 0; i < 6 && row; i++) {
      const L = (row.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
      if (L.some(x => x.includes('$')) && L.length >= 2) break;
      row = row.parentElement;
    }
    if (!row) return;
    const L = (row.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);

    const countLine = L.find(x => /Salaries?\s+submitted/i.test(x)) || '';
    const rangeLine = L.find(x => x.includes('$')) || '';
    const title = L.find(x => x !== countLine && x !== rangeLine &&
                              !/Salaries?\s+submitted/i.test(x) && !x.includes('$')) || L[0];

    const numM = countLine.match(/([\d,]+)/);
    out.push({
      job_title: title,
      pay_range: rangeLine,
      num_salaries: numM ? parseInt(numM[1].replace(/,/g, '')) : null,
    });
  });

  // keep only genuine salary rows: a SHORT real job title + a clean "$.. - $.." range
  const JUNK = /skip to content|pay faq|faqs?\b|frequently asked|average .*salary|^see\b|insights|sort by|viewing|job titles?/i;
  const RANGE = /^\$[\d.,]+\s*[KkMm]?\s*[-\u2013]\s*\$[\d.,]+/;

  const clean = out.filter(r =>
    r.job_title &&
    r.job_title.length <= 50 &&
    !JUNK.test(r.job_title) &&
    RANGE.test((r.pay_range || '').trim())
  );

  // de-dupe by job title, preserve order
  const seen = new Set();
  const rows = clean.filter(r => !seen.has(r.job_title) && seen.add(r.job_title));

  const totalM = document.body.innerText.match(/([\d,]+)\s+job titles/i);
  return { rows, total: totalM ? parseInt(totalM[1].replace(/,/g, '')) : null };
}
"""


def looks_like_challenge(page) -> bool:
    body = page.evaluate("() => document.body.innerText.toLowerCase()")
    return any(k in body for k in
               ("are you a human", "verify you are", "unusual traffic", "press & hold"))


def parse_pay(s: str):
    """'$76K - $95K /yr' -> (76000, 95000, 'yr')"""
    def to_num(val, suf):
        n = float(val)
        if suf.lower() == "k":
            n *= 1_000
        elif suf.lower() == "m":
            n *= 1_000_000
        return int(n)

    nums = re.findall(r"\$\s*([\d.]+)\s*([KMkm]?)", s)
    lo = to_num(*nums[0]) if len(nums) >= 1 else None
    hi = to_num(*nums[1]) if len(nums) >= 2 else (lo if nums else None)
    per = None
    m = re.search(r"/\s*(yr|hr|mo|wk|day)", s, re.I)
    if m:
        per = m.group(1).lower()
    return lo, hi, per


def append_to_parquet(rows):
    """Append this run's job titles to salaries.parquet, de-duped by
    company + job_title (re-runs refresh pay/count). Creates if missing."""
    recs = []
    for r in rows:
        lo, hi, per = parse_pay(r["pay_range"])
        recs.append({
            "company_name": COMPANY_NAME,
            "page": r["page"],
            "job_title": r["job_title"],
            "pay_range": r["pay_range"],
            "min": lo, "max": hi, "per": per,
            "num_salaries": r["num_salaries"],
        })
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

    if not PAYMENT_URL:
        print("No PAYMENT_URL found in .env (next to this script).")
        print("Add a line like:")
        print("  PAYMENT_URL=https://www.glassdoor.com/Salary/Company-Salaries-E######.htm?filter.jobTitleExact=Registered+Nurse&jobTitleId=50005")
        print("(or leave the query off to scrape all roles; no quotes, whole URL on one line)")
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
        page.goto(page_url(1), wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        if looks_like_challenge(page):
            print("Human-check page is showing. Solve it in Chrome, then re-run.")
            return 0

        if args.debug:
            html = page.evaluate(
                r"""() => {
                  const cn=[...document.querySelectorAll('*')].find(
                    n=>n.children.length===0 && /Salaries?\s+submitted/i.test(n.textContent||''));
                  if(!cn) return 'NO SALARY ROW FOUND';
                  let row=cn.parentElement;
                  for(let i=0;i<6&&row;i++){const t=row.innerText||'';
                    if(t.includes('$')) break; row=row.parentElement;}
                  return (row||cn.parentElement).outerHTML;
                }""")
            Path(Path(__file__).parent / "first_salary_row.html").write_text(html, encoding="utf-8")
            print("Wrote first_salary_row.html - paste it back if extraction looks off.")
            return 0

        all_rows, seen, total = [], set(), None
        n = 1
        while n <= MAX_PAGES:
            url = page_url(n)
            print(f"[page {n}] {url}")
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)

            if looks_like_challenge(page):
                print("  ! Human-check appeared. Stopping; solve it in Chrome and re-run later.")
                break

            result = page.evaluate(EXTRACT_JS)
            rows, total = result["rows"], result["total"] or total

            new = [r for r in rows if r["job_title"] not in seen]
            if not new:
                print("  (no new job titles - reached the last page)")
                break

            for r in new:
                r["page"] = n
                seen.add(r["job_title"])
            all_rows.extend(new)
            print(f"  + {len(new)} new (running total {len(all_rows)}"
                  + (f" of {total}" if total else "") + ")")

            if total and len(all_rows) >= total:
                print("  (collected all reported job titles)")
                break

            print(f"  ...waiting {int(PAGE_DELAY)} s before next page")
            time.sleep(PAGE_DELAY)
            n += 1

    # write Excel
    wb = Workbook()
    ws = wb.active
    ws.title = "Salaries"
    ws.append(["Company", "Page", "Job title", "Pay range", "Min", "Max", "Per", "Salaries submitted"])
    for r in all_rows:
        lo, hi, per = parse_pay(r["pay_range"])
        ws.append([COMPANY_NAME, r["page"], r["job_title"], r["pay_range"], lo, hi, per, r["num_salaries"]])
    for col, w in zip("ABCDEFGH", (28, 6, 34, 18, 10, 10, 6, 16)):
        ws.column_dimensions[col].width = w
    wb.save(OUT_XLSX)

    if all_rows:
        append_to_parquet(all_rows)

    print(f"\nDone. {len(all_rows)} job titles for '{COMPANY_NAME}' this run.")
    print(f"  snapshot   -> {OUT_XLSX.name}")
    print(f"  cumulative -> {OUT_PARQUET.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())