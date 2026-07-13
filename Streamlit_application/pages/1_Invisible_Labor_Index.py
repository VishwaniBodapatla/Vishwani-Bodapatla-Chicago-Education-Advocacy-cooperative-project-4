"""
Page: Invisible Labor Index - combines occupation, gender, and salary charts
on ONE page. Each chart still lives in its own file under charts/ - this
page just calls them in sequence.
"""
import streamlit as st
from utils import load_data
from charts.occupation_chart import render_occupation_chart
from charts.gender_chart import render_gender_chart
from charts.salary_chart import render_salary_chart

st.set_page_config(page_title="Invisible Labor Index", layout="wide")

df = load_data()

st.title("Invisible Labor Index")

render_occupation_chart(df)
st.divider()
render_gender_chart(df)
st.divider()
render_salary_chart(df)
