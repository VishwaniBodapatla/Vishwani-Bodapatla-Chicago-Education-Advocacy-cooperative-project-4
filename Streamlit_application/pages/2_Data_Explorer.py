"""
Page: Data Explorer - pick ANY column combination, not locked to the
Invisible Labor Index columns. Useful for exploring recommend, ceo_approval,
business_outlook, employment_status, demographic ratings, salary, etc.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
from utils import load_data

st.set_page_config(page_title="Data Explorer", layout="wide")
df = load_data()

st.title("Data Explorer")
st.caption("Pick any two columns to compare - not limited to the Invisible Labor Index scores.")

# ---------------------------------------------------------------------------
# COLUMN PICKERS
# ---------------------------------------------------------------------------
# Categorical: anything non-numeric, non-datetime with a manageable number
# of unique values. Checks by EXCLUSION (not numeric, not datetime) rather
# than checking for dtype == "object", since newer pandas versions may use
# a "str" dtype instead of the classic "object" dtype for text columns.
categorical_candidates = [
    c for c in df.columns
    if not pd.api.types.is_numeric_dtype(df[c])
    and not pd.api.types.is_datetime64_any_dtype(df[c])
    and df[c].nunique(dropna=True) <= 50
]
# Numeric: anything that's actually numbers (scores, ratings, salary)
numeric_candidates = [
    c for c in df.columns
    if pd.api.types.is_numeric_dtype(df[c]) and c not in ["page", "num_salaries", "n_real_ratings"]
]

col_a, col_b = st.columns(2)
with col_a:
    group_col = st.selectbox(
        "Group by (categorical)",
        sorted(categorical_candidates),
        index=sorted(categorical_candidates).index("occupation") if "occupation" in categorical_candidates else 0,
    )
with col_b:
    measure_col = st.selectbox(
        "Measure (numeric)",
        sorted(numeric_candidates),
        index=sorted(numeric_candidates).index("invisible_labor_score") if "invisible_labor_score" in numeric_candidates else 0,
    )

st.divider()

# ---------------------------------------------------------------------------
# CHART 1: AVERAGE OF measure_col BY group_col
# ---------------------------------------------------------------------------
st.subheader(f"Average {measure_col} by {group_col}")

summary = df.groupby(group_col).agg(
    avg_value=(measure_col, "mean"),
    n=(measure_col, "count"),
).reset_index().sort_values("avg_value", ascending=False)

# Cap to top 30 groups if there are a lot (e.g. company_name) to keep the chart readable
if len(summary) > 30:
    st.caption(f"{group_col} has {len(summary)} distinct values - showing top 30 by average {measure_col}.")
    summary = summary.head(30)

fig_bar = px.bar(
    summary, x=group_col, y="avg_value",
    labels={"avg_value": f"Avg {measure_col}", group_col: group_col},
    hover_data=["n"],
)
fig_bar.update_xaxes(tickangle=45)
st.plotly_chart(fig_bar, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# CHART 2: DISTRIBUTION OF measure_col (overall)
# ---------------------------------------------------------------------------
st.subheader(f"Distribution of {measure_col}")
fig_hist = px.histogram(df, x=measure_col, nbins=30, color=group_col if df[group_col].nunique() <= 8 else None)
st.plotly_chart(fig_hist, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# EVIDENCE TABLE
# ---------------------------------------------------------------------------
with st.expander("View underlying rows"):
    display_cols = [c for c in [
        "company_name", "occupation", group_col, measure_col, "pros", "cons",
    ] if c in df.columns]
    # de-dupe in case group_col or measure_col already in the list
    display_cols = list(dict.fromkeys(display_cols))
    st.dataframe(df[display_cols], use_container_width=True)
