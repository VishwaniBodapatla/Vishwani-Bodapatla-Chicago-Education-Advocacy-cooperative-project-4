"""
Chart function: Invisible Labor Score by Occupation.
This file is NOT in pages/, so Streamlit won't treat it as its own page -
it's imported and called from a page file instead.
"""
import streamlit as st
import plotly.express as px


def render_occupation_chart(df):
    st.subheader("Invisible Labor Score by Occupation")

    occupations = sorted(df["occupation"].dropna().unique())
    selected = st.multiselect("Occupation", occupations, default=occupations, key="occ_filter")
    filtered = df[df["occupation"].isin(selected)]

    occ_summary = filtered.groupby("occupation").agg(
        avg_ili=("invisible_labor_score", "mean"),
        avg_positive=("positive_experience_score", "mean"),
        n=("invisible_labor_score", "count"),
    ).reset_index()

    fig = px.bar(
        occ_summary, x="occupation", y=["avg_ili", "avg_positive"], barmode="group",
        labels={"value": "Score", "variable": "Metric", "occupation": "Occupation"},
        hover_data=["n"],
    )
    st.plotly_chart(fig, use_container_width=True)
