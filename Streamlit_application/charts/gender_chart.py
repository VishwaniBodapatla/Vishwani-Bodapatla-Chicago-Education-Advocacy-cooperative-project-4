"""
Chart function: Invisible Labor Score by Company Gender-Rating Gap.
"""
import streamlit as st
import plotly.express as px


def render_gender_chart(df):
    st.subheader("Invisible Labor Score by Company Gender-Rating Gap")
    st.caption(
        "men_rating / women_rating are company-level Glassdoor demographic ratings, "
        "not per-reviewer gender. This groups COMPANIES by whether women or men rate "
        "that employer higher, then compares review-derived scores across those groups."
    )

    if "gender_comparison" not in df.columns:
        st.warning("gender_comparison column not found - check that men_rating/women_rating exist in your data.")
        return

    gender_summary = df.groupby("gender_comparison").agg(
        avg_ili=("invisible_labor_score", "mean"), n=("invisible_labor_score", "count"),
    ).reset_index()

    fig = px.bar(
        gender_summary, x="gender_comparison", y="avg_ili", color="gender_comparison",
        labels={"avg_ili": "Avg Invisible Labor Score", "gender_comparison": ""}, hover_data=["n"],
    )
    st.plotly_chart(fig, use_container_width=True)
