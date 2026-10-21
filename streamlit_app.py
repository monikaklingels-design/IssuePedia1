import streamlit as st
import pandas as pd
from supabase import create_client

TABLES = ["TabX", "TabY", "Iss_Description"]

@st.cache_resource
def init_connection():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_connection()

@st.cache_data(ttl=60)
def load(table):
    res = supabase.table(table).select("*").execute()
    return pd.DataFrame(res.data)

st.title("My data")

for t in TABLES:
    st.subheader(t)
    st.dataframe(load(t))
