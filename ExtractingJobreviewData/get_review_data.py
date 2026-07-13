r"""
get_review_data.py  (v4 - .env driven, company_name column, append to Parquet)
==============================================================================
Reads a Glassdoor company reviews page filtered by ONE job title, paginating
like a human (20 s between pages) until the LAST page. Every row carries the
company name.

Outputs (all next to this script):
  reviews.parquet  <- APPENDED to on each run (deduped by review content)
  reviews.csv      <- snapshot of THIS run only (overwritten)
  reviews.json     <- snapshot of THIS run only (overwritten)

Settings come from a .env file next to this script:
    COMPANY_NAME=HealthTrust Workforce Solutions
    REVIEW_URL=https://www.glassdoor.com/Reviews/...Reviews-E2502893.htm?filter.jobTitleFTS=Registered+Nurse
Any _P<n> page number in REVIEW_URL is ignored - the script pages through on its own.

SETUP
=====
  pip install playwright python-dotenv pandas pyarrow
  (browser binary not needed in CDP mode)

STEP 1 - launch your real Chrome with a debug port (PowerShell), close all
Chrome first:
  & "C:\Program Files\Google\Chrome\Application\chrome.exe" `
      --remote-debugging-port=9222 `
      --user-data-dir="C:\Users\vishw\gd-chrome-profile"
  Sign in to Glassdoor with Google in that window (one time).

STEP 2 - leave that Chrome open and run:
  python get_review_data.py
  python get_review_data.py --debug   # dump first card HTML

Be decent: 20 s between pages, single window, stops on any human-check page.
This does not bypass CAPTCHAs.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------------------
# CONFIG - URLs and company name come from .env (see header above).
# ---------------------------------------------------------------------------
load_dotenv(Path(__file__).parent / ".env")
COMPANY_NAME = os.getenv("COMPANY_NAME", "").strip()
DEPARTMENT = (os.getenv("DEPARTMENT") or os.getenv("Department") or "").strip()
OCCUPATION = (os.getenv("OCCUPATION") or os.getenv("Occupation") or "").strip()
REVIEW_URL = os.getenv("REVIEW_URL", "").strip()

CDP_URL = "http://localhost:9222"   # must match --remote-debugging-port
PAGE_DELAY = 20.0                   # seconds between pages - human pace
MAX_PAGES = 60                      # hard safety cap; loop normally stops earlier
# ---------------------------------------------------------------------------

OUT_PARQUET = Path(__file__).parent / "reviews.parquet"
OUT_JSON = Path(__file__).parent / "reviews.json"
OUT_CSV = Path(__file__).parent / "reviews.csv"

# company_name/department/occupation lead the columns (from .env).
# review_url is captured internally (for paging + dedup) but NOT written out.
FIELDS = [
    "company_name", "department", "occupation", "page", "rating", "date",
    "title", "job_title", "employment_status", "location", "recommend",
    "ceo_approval", "business_outlook", "pros", "cons",
]

# Cross-run duplicates are matched on the review's content - every column
# except 'page' (page can shift as newer reviews push older ones down).
DEDUP_SUBSET = [f for f in FIELDS if f != "page"]


def split_review_url(url: str):
    """'.../Reviews-E2502893_P2.htm?filter...' -> ('.../Reviews-E2502893', '?filter...')"""
    parts = urlsplit(url)
    path = re.sub(r"_P\d+\.htm$", "", parts.path)   # drop _P<n>.htm
    path = re.sub(r"\.htm$", "", path)              # or plain .htm
    base = urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    query = ("?" + parts.query) if parts.query else ""
    return base, query


BASE, QUERY = split_review_url(REVIEW_URL) if REVIEW_URL else ("", "")


def page_url(n: int) -> str:
    return f"{BASE}.htm{QUERY}" if n <= 1 else f"{BASE}_P{n}.htm{QUERY}"


EXTRACT_JS = r"""
() => {
  const titleLinks = [...document.querySelectorAll('a[href*="Employee-Review-"][href*="RVW"]')];

  // Climb to the LARGEST ancestor that still wraps exactly ONE review link.
  // That captures the full card (rating + date header included) without
  // merging into the next review.
  const cardFor = a => {
    let el = a, best = a;
    for (let i = 0; i < 12 && el; i++) {
      const links = el.querySelectorAll('a[href*="Employee-Review-"][href*="RVW"]');
      if (links.length === 1) best = el;
      else if (links.length > 1) break;
      el = el.parentElement;
    }
    return best;
  };

  const afterLabel = (card, label) => {
    for (const n of card.querySelectorAll('*')) {
      if (n.children.length === 0 && n.textContent.trim() === label) {
        let sib = n.nextElementSibling;
        while (sib && !sib.textContent.trim()) sib = sib.nextElementSibling;
        if (sib) return sib.textContent.trim().replace(/\s+/g, ' ');
        if (n.parentElement && n.parentElement.nextElementSibling)
          return n.parentElement.nextElementSibling.textContent.trim().replace(/\s+/g, ' ');
      }
    }
    return null;
  };

  const indicator = (card, label) => {
    // Find the <span> with this label, climb to its ExperienceRating_container,
    // and read the state from the container's class name. Real classes seen:
    //   ExperienceRating_positive__  -> green check (yes)
    //   ExperienceRating_negative__  -> x (no)
    //   ExperienceRating_neutral__   -> dash
    //   ExperienceRating_noData__    -> empty circle (no response)
    const span = [...card.querySelectorAll('span')].find(
      n => n.textContent.trim() === label);
    if (!span) return null;
    let box = span;
    for (let i = 0; i < 4 && box; i++) {
      const cls = box.className || '';
      if (/ExperienceRating_(positive|negative|neutral|noData)/.test(cls)) {
        if (/positive/.test(cls)) return 'positive';
        if (/negative/.test(cls)) return 'negative';
        if (/neutral/.test(cls))  return 'neutral';
        return null;   // noData -> no response given
      }
      box = box.parentElement;
    }
    return null;
  };

  const rows = titleLinks.map(a => {
    const card = cardFor(a);
    // innerText keeps the visible line breaks between fields; textContent does
    // NOT, which is why everything used to run together. This is the key fix.
    const lines = (card.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);

    let rating = null;
    const starEl = card.querySelector('[aria-label*="star" i], [aria-label*="rating" i]');
    if (starEl) {
      const m = (starEl.getAttribute('aria-label') || '').match(/([0-5](?:\.\d)?)/);
      if (m) rating = m[1];
    }
    if (!rating) {
      for (const l of lines) { const m = l.match(/^([0-5]\.\d)\b/); if (m) { rating = m[1]; break; } }
    }

    const dateLine = lines.find(l => /^[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}/.test(l));
    const empLine  = lines.find(l => /^(Current|Former)\s+employee/i.test(l));

    const lineAfter = lbl => {
      const i = lines.indexOf(lbl);
      return (i >= 0 && i + 1 < lines.length) ? lines[i + 1] : null;
    };

    // Job title sits in the "avatar" block, exposed two stable ways:
    //   <a data-test="content-avatar-label">Registered nurse, bsn</a>
    //   <div ... aria-label="Registered nurse, bsn">
    // Use those hooks (role-agnostic) rather than guessing URL patterns.
    let job_title = null;
    const jobA = card.querySelector('[data-test="content-avatar-label"]');
    if (jobA && jobA.textContent.trim()) {
      job_title = jobA.textContent.trim();
    } else {
      const av = card.querySelector('[data-test="content-avatar-container"] [aria-label]');
      if (av) job_title = (av.getAttribute('aria-label') || '').trim() || null;
    }
    const locA = card.querySelector('a[href*="_IL."], a[href*="_IC"]');

    return {
      rating: rating,
      date: dateLine || null,
      title: a.textContent.trim(),
      review_url: a.href,
      job_title: job_title,
      employment_status: empLine || null,
      location: locA ? locA.textContent.trim() : null,
      recommend: indicator(card, 'Recommend'),
      ceo_approval: indicator(card, 'CEO approval'),
      business_outlook: indicator(card, 'Business Outlook'),
      pros: lineAfter('Pros') || afterLabel(card, 'Pros'),
      cons: lineAfter('Cons') || afterLabel(card, 'Cons'),
    };
  });

  const totalM = document.body.innerText.match(/of\s+([\d,]+)\s+Reviews/i);
  return { rows, total: totalM ? parseInt(totalM[1].replace(/,/g, '')) : null };
}
"""


def expand_truncated(page):
    try:
        for btn in page.get_by_text(re.compile(r"^Show more$")).all():
            try:
                btn.click(timeout=1000)
            except Exception:
                pass
    except Exception:
        pass


def looks_like_challenge(page) -> bool:
    body = page.evaluate("() => document.body.innerText.toLowerCase()")
    return any(k in body for k in
               ("are you a human", "verify you are", "unusual traffic",
                "help us protect", "press & hold"))


def append_to_parquet(new_rows):
    """Append this run rows to reviews.parquet, de-duped by review content.
    Creates the file if it doesn't exist."""
    new_df = pd.DataFrame(new_rows, columns=FIELDS)

    if OUT_PARQUET.exists():
        try:
            old_df = pd.read_parquet(OUT_PARQUET)
        except Exception as e:
            print(f"  (could not read existing parquet, starting fresh: {e})")
            old_df = pd.DataFrame(columns=FIELDS)
        combined = pd.concat([old_df, new_df], ignore_index=True)
        before = len(combined)
        combined = combined.drop_duplicates(subset=DEDUP_SUBSET, keep="last").reset_index(drop=True)
        added = len(combined) - len(old_df)
        dupes = before - len(combined)
        print(f"  parquet: had {len(old_df)}, +{added} new, "
              f"{dupes} already present -> {len(combined)} total")
    else:
        combined = new_df
        print(f"  parquet: created with {len(combined)} rows")

    combined.to_parquet(OUT_PARQUET, index=False)


def safe_goto(page, url, tries=3):
    """Navigate to url, tolerating Glassdoor's mid-load redirects (e.g. to
    /Job/index.htm) and transient interruptions. Returns True on success.
    Waits longer between retries to ease off any throttling."""
    for attempt in range(1, tries + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # if Glassdoor bounced us somewhere else, treat as a miss and retry
            if "/Reviews/" not in page.url:
                raise RuntimeError(f"redirected to {page.url}")
            return True
        except Exception as e:
            wait = 10 * attempt
            print(f"  ! navigation issue (try {attempt}/{tries}): "
                  f"{str(e).splitlines()[0][:120]}")
            if attempt < tries:
                print(f"    waiting {wait}s then retrying the same page...")
                page.wait_for_timeout(wait * 1000)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", action="store_true",
                    help="dump first review card HTML and exit")
    args = ap.parse_args()

    if not REVIEW_URL:
        print("No REVIEW_URL found in .env (next to this script).")
        print("Add a line like:")
        print("  REVIEW_URL=https://www.glassdoor.com/Reviews/Company-Reviews-E######.htm?filter.jobTitleFTS=Registered+Nurse")
        print("(no quotes, no spaces around '=', whole URL on one line)")
        return 1
    if not COMPANY_NAME:
        print("Note: COMPANY_NAME is empty in .env - the company_name column will be blank.")

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print("Could not attach to Chrome on", CDP_URL)
            print("Did you launch Chrome with --remote-debugging-port=9222 ?")
            print("Details:", e)
            return 1

        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        if not safe_goto(page, page_url(1)):
            print("Could not load page 1 (Glassdoor redirect/throttle). "
                  "Try again in a few minutes.")
            return 0
        page.wait_for_timeout(2000)

        if looks_like_challenge(page):
            print("A human-check page is showing. Solve it yourself in Chrome, "
                  "then re-run. Stopping.")
            return 0

        if args.debug:
            html = page.evaluate(
                r"""() => {
                  const a=document.querySelector('a[href*="Employee-Review-"][href*="RVW"]');
                  if(!a) return 'NO REVIEW CARD FOUND - are you logged in & on the reviews page?';
                  let el=a;
                  for(let i=0;i<8&&el;i++){const t=el.textContent||'';
                    if(t.includes('Pros')&&t.includes('Cons'))return el.outerHTML;
                    el=el.parentElement;}
                  return (a.closest('li')||a.parentElement).outerHTML;
                }""")
            Path(Path(__file__).parent / "first_card.html").write_text(html, encoding="utf-8")
            print("Wrote first_card.html - paste it back to finalize the 3 indicators.")
            return 0

        all_rows, seen, total = [], set(), None
        stopped_reason = "finished normally"
        n = 1
        try:
            while n <= MAX_PAGES:
                url = page_url(n)
                print(f"[page {n}] {url}")
                if not safe_goto(page, url):
                    print("  ! Could not load this page after retries (Glassdoor "
                          "redirect/throttle). Saving what we have and stopping.")
                    stopped_reason = "stopped: page load failed (throttle/redirect)"
                    break
                page.wait_for_timeout(1500)

                if looks_like_challenge(page):
                    print("  ! Human-check appeared. Stopping; solve it in Chrome and re-run later.")
                    stopped_reason = "stopped: human-check page"
                    break

                expand_truncated(page)
                page.wait_for_timeout(500)

                result = page.evaluate(EXTRACT_JS)
                rows, total = result["rows"], result["total"] or total

                new = [r for r in rows if r["review_url"] not in seen]
                if not new:
                    print("  (no new reviews - reached the last page)")
                    break

                for r in new:
                    r["company_name"] = COMPANY_NAME   # same value on every row
                    r["department"] = DEPARTMENT
                    r["occupation"] = OCCUPATION
                    r["page"] = n
                    seen.add(r["review_url"])
                all_rows.extend(new)
                print(f"  + {len(new)} new (running total {len(all_rows)}"
                      + (f" of {total}" if total else "") + ")")

                if total and len(all_rows) >= total:
                    print("  (collected all reported reviews)")
                    break

                print(f"  ...waiting {int(PAGE_DELAY)} s before next page")
                time.sleep(PAGE_DELAY)
                n += 1
        except KeyboardInterrupt:
            stopped_reason = "stopped: interrupted with Ctrl+C"
            print("\n  ! Ctrl+C received - saving what was collected so far...")
        except Exception as e:
            stopped_reason = f"stopped: error ({type(e).__name__})"
            print(f"\n  ! Error during scrape: {e}\n  Saving what was collected so far...")
        finally:
            # This ALWAYS runs - normal finish, Ctrl+C, throttle, or error -
            # so an interrupted long run never loses the pages it already got.
            if all_rows:
                # snapshot of THIS run; projected to FIELDS so review_url is
                # excluded from JSON just like CSV/Parquet.
                snapshot = [{k: r.get(k) for k in FIELDS} for r in all_rows]
                OUT_JSON.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False),
                                    encoding="utf-8")
                with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
                    w = csv.DictWriter(f, fieldnames=FIELDS)
                    w.writeheader()
                    for r in all_rows:
                        w.writerow({k: r.get(k) for k in FIELDS})
                append_to_parquet(all_rows)
            else:
                print("  (nothing collected - nothing to save)")

            print(f"\nDone ({stopped_reason}). "
                  f"{len(all_rows)} reviews for '{COMPANY_NAME}' this run.")
            if all_rows:
                print(f"  snapshot -> {OUT_CSV.name}, {OUT_JSON.name}")
                print(f"  cumulative -> {OUT_PARQUET.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())