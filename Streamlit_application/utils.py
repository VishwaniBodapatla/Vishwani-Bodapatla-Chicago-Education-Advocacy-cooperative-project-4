"""
Shared data-loading and cleaning utilities for the Invisible Labor Index app.
Imported by Home.py and every page in pages/ - keep all shared transforms here
so we don't duplicate logic as more pages get added.
"""
import pandas as pd
import streamlit as st

DATA_PATH = r"C:\Users\vishw\OneDrive\Documents\final_data.csv"

REGION_MAP = {
    "CT": "Northeast", "ME": "Northeast", "MA": "Northeast", "NH": "Northeast",
    "RI": "Northeast", "VT": "Northeast", "NJ": "Northeast", "NY": "Northeast", "PA": "Northeast",

    "IL": "Midwest", "IN": "Midwest", "MI": "Midwest", "OH": "Midwest", "WI": "Midwest",
    "IA": "Midwest", "KS": "Midwest", "MN": "Midwest", "MO": "Midwest", "NE": "Midwest",
    "ND": "Midwest", "SD": "Midwest",

    "DE": "South", "FL": "South", "GA": "South", "MD": "South", "NC": "South",
    "SC": "South", "VA": "South", "DC": "South", "WV": "South", "AL": "South",
    "KY": "South", "MS": "South", "TN": "South", "AR": "South", "LA": "South",
    "OK": "South", "TX": "South",

    "AZ": "West", "CO": "West", "ID": "West", "MT": "West", "NV": "West",
    "NM": "West", "UT": "West", "WY": "West", "AK": "West", "CA": "West",
    "HI": "West", "OR": "West", "WA": "West",
}


def fix_mojibake(val):
    if not isinstance(val, str):
        return val
    try:
        return val.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return val


@st.cache_data
def load_data(path=DATA_PATH):
    df = pd.read_csv(path)

    # Fix mojibake in text columns
    for col in ["pros", "cons", "title", "company_name", "job_title"]:
        if col in df.columns:
            df[col] = df[col].apply(fix_mojibake)

    # Salary midpoint
    if "min" in df.columns and "max" in df.columns:
        df["salary_mid"] = (df["min"] + df["max"]) / 2

    # Region from location's state - derived via REGION_MAP, NOT the
    # region column that may already exist in the source data (if you had
    # one before, this overwrites it - state-based mapping is the source
    # of truth going forward per your snippet).
    if "state" in df.columns:
        df["region"] = df["state"].str.strip().map(REGION_MAP)
    elif "location" in df.columns:
        # fallback: try to extract state from a combined "City, ST" location string
        extracted_state = df["location"].str.extract(r",\s*([A-Z]{2})\s*$")[0]
        df["region"] = extracted_state.str.strip().map(REGION_MAP)

    # Gender comparison bucket (company-level rating, see caveat in app)
    if "men_rating" in df.columns and "women_rating" in df.columns:
        def gender_bucket(row):
            if pd.isna(row["men_rating"]) or pd.isna(row["women_rating"]):
                return "Unknown"
            diff = row["women_rating"] - row["men_rating"]
            if diff > 0.15:
                return "Women rate higher"
            elif diff < -0.15:
                return "Men rate higher"
            else:
                return "Roughly equal"
        df["gender_rating_gap"] = df["women_rating"] - df["men_rating"]
        df["gender_comparison"] = df.apply(gender_bucket, axis=1)

    # Parse the date column - handles either format:
    #   - Real date strings like "Jan 14, 2026" (most common)
    #   - Excel serial numbers like 46036 (if the source export used that format)
    # IMPORTANT: check dtype BEFORE parsing - pandas silently misinterprets
    # raw integers as nanosecond timestamps (giving bogus 1970 dates) rather
    # than failing, so we can't detect "wrong format" after the fact.
    if "date" in df.columns:
        if pd.api.types.is_numeric_dtype(df["date"]):
            df["date_parsed"] = pd.to_datetime(df["date"], unit="D", origin="1899-12-30", errors="coerce")
        else:
            df["date_parsed"] = pd.to_datetime(df["date"], errors="coerce")

    return df