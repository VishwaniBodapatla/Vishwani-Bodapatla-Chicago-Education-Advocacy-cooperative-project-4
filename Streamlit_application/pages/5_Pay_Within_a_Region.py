"""
Page: Pay Variation Within a Selected Region
"""
import streamlit as st
import plotly.express as px
from utils import load_data

st.set_page_config(page_title="Pay Within a Region", layout="wide")
df = load_data()

st.title("Pay Variation Within a Selected Region")

regions_available = sorted(df["region"].dropna().unique())
selected_region = st.selectbox("Choose a region", regions_available)

region_df = df[df["region"] == selected_region]

pay_by_occ = region_df.groupby("occupation")["salary_mid"].agg(["mean", "min", "max", "count"]).reset_index()
pay_by_occ.columns = ["occupation", "avg_salary", "min_salary", "max_salary", "n"]

fig = px.bar(
    pay_by_occ, x="occupation", y="avg_salary",
    labels={"avg_salary": "Average Salary ($)", "occupation": "Occupation"},
    title=f"Average pay by occupation — {selected_region}",
    hover_data=["min_salary", "max_salary", "n"],
)
st.plotly_chart(fig, use_container_width=True)
st.caption(f"{len(region_df)} reviews in {selected_region}")
