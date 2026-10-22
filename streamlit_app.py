import streamlit as st
import pandas as pd
from supabase import create_client

ISS_ID = "Iss01"

@st.cache_resource
def init_connection():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_connection()

@st.cache_data(ttl=60)
def load_issue(iss_id):
    res = (
        supabase.table("iss_collection")
        .select("*")
        .eq("iss_id", iss_id)
        .execute()
    )
    return pd.DataFrame(res.data)

def join_text(s):
    return " | ".join(s.dropna().astype(str))

st.title(f"Matrix for {ISS_ID}")

df = load_issue(ISS_ID)

if df.empty:
    st.info(f"No rows found for iss_id = {ISS_ID}, or no read policy on iss_collection.")
else:
    matrix = df.pivot_table(
        index="level",
        columns="co_factor",
        values="comment_short",
        aggfunc=join_text,
        fill_value="",
    )
    st.dataframe(matrix, use_container_width=True)
