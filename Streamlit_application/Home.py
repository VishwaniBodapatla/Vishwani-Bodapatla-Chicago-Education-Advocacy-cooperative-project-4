"""
Home - Invisible Labor Index overview (KPIs only)
"""
import streamlit as st
from utils import load_data

st.set_page_config(page_title="Invisible Labor Index", layout="wide")

df = load_data()

st.title("Invisible Labor Index")
st.write("Use the sidebar to navigate to each page.")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Avg Invisible Labor Score", f"{df['invisible_labor_score'].mean():.2f}")
col2.metric("Avg Positive Experience Score", f"{df['positive_experience_score'].mean():.2f}")
col3.metric("Avg Star Rating", f"{df['rating'].mean():.2f}")
col4.metric("Reviews", f"{len(df):,}")
