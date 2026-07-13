"""
Page: Correlation Heatmap - what correlates with the Invisible Labor Score
"""
import streamlit as st
import plotly.express as px
from utils import load_data

st.set_page_config(page_title="Correlation Heatmap", layout="wide")
df = load_data()

st.title("What Correlates with the Invisible Labor Score")

CONSTRUCT_COLS = [
    "burnout_and_exhaustion_score",
    "compassion_fatigue_from_difficult_clients_or_students_score",
    "frustration_with_management_or_leadership_score",
    "dissatisfaction_with_pay_score",
    "high_staff_turnover_and_instability_score",
    "overall_job_satisfaction_score",
    "supportive_coworkers_and_teamwork_score",
    "pride_and_sense_of_purpose_score",
    "healthy_work-life_balance_score",
]
available_constructs = [c for c in CONSTRUCT_COLS if c in df.columns]

corr_cols = available_constructs + ["invisible_labor_score", "positive_experience_score", "rating", "salary_mid"]
corr_cols = [c for c in corr_cols if c in df.columns]
corr_matrix = df[corr_cols].corr()

fig = px.imshow(
    corr_matrix, text_auto=".2f", color_continuous_scale="RdBu_r",
    zmin=-1, zmax=1, aspect="auto",
)
fig.update_layout(height=700)
st.plotly_chart(fig, use_container_width=True)

st.caption(
    "Correlations near +1 (red) or -1 (blue) indicate a strong relationship. "
    "Correlation is not causation."
)
