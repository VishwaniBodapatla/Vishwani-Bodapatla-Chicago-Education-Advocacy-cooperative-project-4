"""
Chart function: Invisible Labor Score vs. Salary.
"""
import streamlit as st
import plotly.express as px


def render_salary_chart(df):
    st.subheader("Invisible Labor Score vs. Salary")

    if "salary_mid" not in df.columns:
        st.warning("salary_mid column not found - check that min/max salary columns exist in your data.")
        return

    scatter_data = df.dropna(subset=["salary_mid", "invisible_labor_score"])
    fig = px.scatter(
        scatter_data, x="salary_mid", y="invisible_labor_score", color="occupation",
        hover_data=["company_name", "job_title", "rating"],
        labels={"salary_mid": "Salary (midpoint, $)", "invisible_labor_score": "Invisible Labor Score"},
        trendline="ols" if len(scatter_data) > 5 else None,
    )
    st.plotly_chart(fig, use_container_width=True)
