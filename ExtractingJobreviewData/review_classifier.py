"""
Invisible Labor Index - Review Classification Pipeline
=========================================================
Step-by-step script for Week 1-2 of the project: turns raw Glassdoor
review text into structured emotional-labor scores.

HOW TO RUN:
1. Put reviews.parquet, salaries.parquet, demographics.parquet in this folder
2. Update the file paths in STEP 1 below
3. Run: python classify_reviews.py
4. Output: classified_reviews.csv (one row per review, with all scores)
           occupation_region_summary.csv (aggregated - ready for Power BI/Tableau)
"""

import pandas as pd
import re
import json

# ---------------------------------------------------------------------------
# STEP 1: LOAD DATA
# ---------------------------------------------------------------------------
# Swap this block for your real parquet files:
#   reviews = pd.read_parquet("reviews.parquet")
#   salaries = pd.read_parquet("salaries.parquet")
#   demographics = pd.read_parquet("demographics.parquet")

def load_reviews(path):
    if path.endswith(".jsonl"):
        rows = [json.loads(line) for line in open(path)]
        return pd.DataFrame(rows)
    return pd.read_parquet(path)

reviews = load_reviews("reviews.parquet")  # your real Glassdoor reviews file

print(f"Loaded {len(reviews)} reviews")
print(reviews.columns.tolist())

# ---------------------------------------------------------------------------
# STEP 2: CLEAN TEXT
# ---------------------------------------------------------------------------
def clean_text(t):
    if pd.isna(t) or t is None:
        return ""
    t = str(t).lower()
    t = re.sub(r"[^a-z0-9\s'/-]", " ", t)   # strip weird punctuation, keep words
    t = re.sub(r"\s+", " ", t).strip()
    return t

reviews["pros_clean"] = reviews["pros"].apply(clean_text)
reviews["cons_clean"] = reviews["cons"].apply(clean_text)
reviews["rating"] = pd.to_numeric(reviews["rating"], errors="coerce")

# ---------------------------------------------------------------------------
# STEP 3: DEFINE CONSTRUCT LEXICONS
# ---------------------------------------------------------------------------
# Each construct = list of keyword/phrase triggers. This is intentionally
# transparent (not a black-box model) so you can defend it in your methodology
# writeup and expand it as you read more reviews.

LEXICONS = {
    "burnout_exhaustion": [
        "exhausted", "exhausting", "burnout", "burnt out", "burned out", "no break",
        "understaffed", "short staffed", "long hours", "24/7", "never off the clock",
        "overworked", "no lunch", "unsustainable", "extended school day",
        "extended school year", "excessive work", "zero work-life balance",
        "not enough employees", "sitting a lot", "on call", "getting called off",
    ],
    "compassion_fatigue": [
        "difficult students", "troubled", "behavioral issues", "trauma",
        "hard to leave it at work", "emotionally draining", "tough behaviors",
        "high needs", "disrespectful students", "lots of patients", "patient ratio",
        "acuity", "12:1",
    ],
    "management_frustration": [
        "no support", "lack of support", "poor communication", "communication is lacking",
        "micromanage", "unprofessional", "out of touch", "arbitrary decisions",
        "leadership", "administration", "no real salary schedule", "money hungry",
        "don't listen", "don't follow it", "unwelcoming",
    ],
    "fulfillment_purpose": [
        "rewarding", "love the kids", "love my job", "make a difference", "inspiring",
        "amazing", "fun to work with", "supportive team", "great environment",
        "genuinely love their job", "empowered",
    ],
    "salary_dissatisfaction": [
        "underpaid", "low pay", "paycheck", "no real salary", "hourly pay",
        "paid about", "slashed", "no pay in the summer", "pay is",
        "pay could be more competitive", "high cost for insurance",
    ],
    "turnover_instability": [
        "turnover", "revolving door", "staff turnover", "high turnover",
        "advance is difficult", "stay in their positions for a long time",
    ],
    # --- Positive constructs (balance out the negative ones above) ---
    "job_satisfaction": [
        "great place to work", "good place to work", "great job", "highly recommend",
        "would recommend", "enjoy my job", "happy here", "positive experience",
        "good company to work for",
    ],
    "team_support": [
        "supportive colleagues", "great colleagues", "team player", "we are all one big family",
        "everyone supports one another", "hardworking colleagues", "close-knit",
        "great co-workers", "helpful staff", "collaboration", "mentorship",
    ],
    "pride_recognition": [
        "proud", "appreciated", "valued", "recognized", "impact", "student growth",
        "grow professionally",
    ],
    "healthy_balance": [
        "flexible", "work life balance", "work-life balance", "summers off",
        "reasonable hours", "short days", "good hours", "time off",
        "customizable schedule", "decent pay",
    ],
}

def score_construct(text, keywords):
    """Returns (hit_count, hit_flag, matched_terms)."""
    hits = [kw for kw in keywords if kw in text]
    return len(hits), int(len(hits) > 0), hits

# ---------------------------------------------------------------------------
# STEP 4: APPLY LEXICON SCORING TO EACH REVIEW (pros + cons combined, since
# fulfillment often lives in pros and burnout in cons)
# ---------------------------------------------------------------------------
reviews["full_text"] = reviews["pros_clean"] + " " + reviews["cons_clean"]

for construct, keywords in LEXICONS.items():
    counts, flags, terms = [], [], []
    for text in reviews["full_text"]:
        c, f, t = score_construct(text, keywords)
        counts.append(c)
        flags.append(f)
        terms.append(", ".join(t))
    reviews[f"{construct}_count"] = counts
    reviews[f"{construct}_flag"] = flags
    reviews[f"{construct}_terms"] = terms

# ---------------------------------------------------------------------------
# STEP 5: SIMPLE POLARITY SENTIMENT (transparent lexicon, no model download
# needed - swap for VADER/transformer later if you want finer granularity)
# ---------------------------------------------------------------------------
POSITIVE_WORDS = {"great", "good", "amazing", "supportive", "rewarding", "love",
                   "excellent", "friendly", "helpful", "flexible", "fun", "inspiring"}
NEGATIVE_WORDS = {"bad", "poor", "unprofessional", "toxic", "hostile", "awful",
                   "difficult", "demanding", "unsustainable", "disrespectful", "lacking"}

def polarity(text):
    words = text.split()
    if not words:
        return 0.0
    pos = sum(1 for w in words if w in POSITIVE_WORDS)
    neg = sum(1 for w in words if w in NEGATIVE_WORDS)
    return (pos - neg) / len(words)

reviews["pros_sentiment"] = reviews["pros_clean"].apply(polarity)
reviews["cons_sentiment"] = reviews["cons_clean"].apply(polarity)

# ---------------------------------------------------------------------------
# STEP 6: COMPOSITE INVISIBLE LABOR SCORE PER REVIEW
# ---------------------------------------------------------------------------
# Weighted combination - document these weights in your methodology section,
# adjust once you see distributions across the full dataset.
reviews["invisible_labor_score"] = (
    reviews["burnout_exhaustion_count"] * 1.0
    + reviews["compassion_fatigue_count"] * 0.75
    + reviews["management_frustration_count"] * 0.5
    - reviews["fulfillment_purpose_count"] * 0.5
)

# Positive-side composite - job satisfaction, support, pride, healthy balance.
# Keep this separate rather than just inverting the negative score - a review
# can score high on BOTH (burnt out but still proud of the work), and that
# combination is itself an interesting finding for your report.
reviews["positive_experience_score"] = (
    reviews["job_satisfaction_count"] * 1.0
    + reviews["team_support_count"] * 0.75
    + reviews["pride_recognition_count"] * 0.75
    + reviews["healthy_balance_count"] * 0.5
    + reviews["fulfillment_purpose_count"] * 0.5
)

# ---------------------------------------------------------------------------
# STEP 7: SAVE PER-REVIEW OUTPUT
# ---------------------------------------------------------------------------
review_cols = ["company_name", "occupation", "region", "rating", "recommend",
               "pros", "cons",
               "burnout_exhaustion_flag", "burnout_exhaustion_terms",
               "compassion_fatigue_flag", "compassion_fatigue_terms",
               "management_frustration_flag", "management_frustration_terms",
               "fulfillment_purpose_flag", "fulfillment_purpose_terms",
               "salary_dissatisfaction_flag", "salary_dissatisfaction_terms",
               "turnover_instability_flag", "turnover_instability_terms",
               "job_satisfaction_flag", "job_satisfaction_terms",
               "team_support_flag", "team_support_terms",
               "pride_recognition_flag", "pride_recognition_terms",
               "healthy_balance_flag", "healthy_balance_terms",
               "pros_sentiment", "cons_sentiment",
               "invisible_labor_score", "positive_experience_score"]
reviews[review_cols].to_csv("classified_reviews.csv", index=False)
print("\nSaved classified_reviews.csv")

# ---------------------------------------------------------------------------
# STEP 8: AGGREGATE BY OCCUPATION x REGION (this is what feeds your dashboard)
# ---------------------------------------------------------------------------
summary = reviews.groupby(["occupation", "region"]).agg(
    n_reviews=("rating", "count"),
    avg_rating=("rating", "mean"),
    burnout_rate=("burnout_exhaustion_flag", "mean"),
    compassion_fatigue_rate=("compassion_fatigue_flag", "mean"),
    fulfillment_rate=("fulfillment_purpose_flag", "mean"),
    job_satisfaction_rate=("job_satisfaction_flag", "mean"),
    team_support_rate=("team_support_flag", "mean"),
    healthy_balance_rate=("healthy_balance_flag", "mean"),
    avg_invisible_labor_score=("invisible_labor_score", "mean"),
    avg_positive_experience_score=("positive_experience_score", "mean"),
).reset_index()

summary.to_csv("occupation_region_summary.csv", index=False)
print("Saved occupation_region_summary.csv")

print("\n--- PREVIEW ---")
print(reviews[review_cols].to_string())
print("\n--- SUMMARY ---")
print(summary.to_string())