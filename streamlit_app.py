import streamlit as st
import pandas as pd
from supabase import create_client

TABLES = [
    "iss_description",
    "iss_collection",
    "level_list",
    "co_factors_list",
    "tab_y",
    "tab_x",
]

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
    try:
        df = load(t)
        if df.empty:
            st.info("No rows, or no read policy for this table yet.")
        else:
            st.dataframe(df, use_container_width=True)
    except Exception as e:
        st.error(f"Could not load {t}: {e}")
