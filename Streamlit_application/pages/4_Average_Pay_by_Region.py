"""
Page: Average Pay by Region (all regions)
"""
import streamlit as st
import plotly.express as px
from utils import load_data

st.set_page_config(page_title="Average Pay by Region", layout="wide")
df = load_data()

st.title("Average Pay by Region")

region_pay = df.groupby("region")["salary_mid"].mean().reset_index().dropna()
fig = px.bar(
    region_pay, x="region", y="salary_mid",
    labels={"salary_mid": "Average Salary ($)", "region": "Region"},
)
st.plotly_chart(fig, use_container_width=True)
