import streamlit as st
import pandas as pd
from supabase import create_client

# Lookup tables: table name and the column holding the values
LEVEL_TABLE, LEVEL_COL = "level_list", "level"
COFACTOR_TABLE, COFACTOR_COL = "co_factors_list", "co_factor"

@st.cache_resource
def init_connection():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_connection()

@st.cache_data(ttl=300)
def load_options(table, col):
    res = supabase.table(table).select("*").execute()
    df = pd.DataFrame(res.data)
    if col not in df.columns:
        raise KeyError(
            f"Column '{col}' not found in {table}. "
            f"Available columns: {list(df.columns)}"
        )
    return df[col].dropna().astype(str).drop_duplicates().tolist()

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

st.title("Issue matrix")

iss_id = st.text_input("Issue ID", value="Iss01").strip()

# ---------- Entry form ----------
st.subheader("Add an entry")

try:
    levels = load_options(LEVEL_TABLE, LEVEL_COL)
    cofactors = load_options(COFACTOR_TABLE, COFACTOR_COL)
except Exception as e:
    st.error(str(e))
    st.stop()

with st.form("add_entry", clear_on_submit=True):
    level = st.selectbox("Level", levels)
    co_factor = st.selectbox("Co-factor", cofactors)
    comment = st.text_area("Short comment", max_chars=500)
    submitted = st.form_submit_button("Add")

if submitted:
    if not iss_id:
        st.warning("Please enter an Issue ID.")
    elif not comment.strip():
        st.warning("Please enter a comment.")
    else:
        try:
            supabase.table("iss_collection").insert({
                "iss_id": iss_id,
                "level": level,
                "co_factor": co_factor,
                "comment_short": comment.strip(),
            }).execute()
            load_issue.clear()
            st.success("Entry added.")
        except Exception as e:
            st.error(f"Could not save: {e}")

# ---------- Matrix ----------
st.subheader(f"Matrix for {iss_id}")

df = load_issue(iss_id)

if df.empty:
    st.info("No rows for this Issue ID yet, or no read policy on iss_collection.")
else:
    matrix = df.pivot_table(
        index="level",
        columns="co_factor",
        values="comment_short",
        aggfunc=join_text,
        fill_value="",
    )
    # keep the order of the lookup tables, extra values at the end
    rows = [l for l in levels if l in matrix.index] + \
           [l for l in matrix.index if l not in levels]
    cols = [c for c in cofactors if c in matrix.columns] + \
           [c for c in matrix.columns if c not in cofactors]
    st.dataframe(matrix.loc[rows, cols], use_container_width=True)
