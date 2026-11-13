 # streamlit_app.py
# Issue matrix app.
# Users add entries through a form. The matrix shows all comments of one
# issue, with the levels as rows and the dimensions as columns.

import html                          # makes user text safe for HTML display
import streamlit as st               # the web app framework
import pandas as pd                  # tables: loading, sorting, pivoting
from supabase import create_client   # connection to the Supabase database

# ------------------------------------------------------------------
# SETTINGS
# Each lookup table feeds one dropdown. For each of them we need:
#   - the table name in Supabase
#   - the column with the value that is shown (and saved)
#   - the id column, which decides the sort order
# If you rename something in the database again, change it here only.
# ------------------------------------------------------------------
LEVEL_TABLE, LEVEL_COL, LEVEL_ID_COL = "level_list", "level", "level_id"
DIMENSION_TABLE, DIMENSION_COL, DIMENSION_ID_COL = (
    "dimension_list", "dimension", "dimension_id"
)

# ------------------------------------------------------------------
# DATABASE CONNECTION
# The address (URL) and the key are read from Streamlit's secrets, so
# they never appear in the code on GitHub.
# @st.cache_resource keeps one connection alive for the whole app,
# instead of creating a new one every time the page reruns.
# ------------------------------------------------------------------
@st.cache_resource
def init_connection():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_connection()

# ------------------------------------------------------------------
# LOAD THE VALUES FOR A DROPDOWN
# Reads a lookup table and returns its values as a list, sorted
# ascending by the id column.
# @st.cache_data remembers the result for 300 seconds (5 minutes), so
# the database is not asked again on every click. Note: after a change
# in a lookup table it can take up to 5 minutes until the app shows it.
# ------------------------------------------------------------------
@st.cache_data(ttl=300)
def load_options(table, col, id_col):
    # select("*") asks for all columns; execute() sends the request
    res = supabase.table(table).select("*").execute()
    # res.data is a list of rows; pandas turns it into a table (DataFrame)
    df = pd.DataFrame(res.data)

    # Safety check: if a column name is wrong, say so with a clear
    # message that lists the columns that really exist
    for c in (col, id_col):
        if c not in df.columns:
            raise KeyError(
                f"Column '{c}' not found in {table}. "
                f"Available columns: {list(df.columns)}"
            )

    # Sort by the id column. If all ids are numbers, sort numerically
    # (so 2 comes before 10), otherwise sort them as text.
    ids = pd.to_numeric(df[id_col], errors="coerce")  # non-numbers become NaN
    if ids.notna().all():
        df = df.assign(_key=ids).sort_values("_key")
    else:
        df = df.sort_values(id_col)

    # Return only the value column as a plain Python list,
    # without empty values (dropna) and without duplicates
    return df[col].dropna().astype(str).drop_duplicates().tolist()

# ------------------------------------------------------------------
# LOAD ALL ENTRIES OF ONE ISSUE
# .eq("iss_id", iss_id) means "where iss_id = the given value".
# The database does the filtering, so only matching rows are sent.
# The cache lasts 60 seconds; after saving a new entry we clear it by
# hand, so the new entry shows up immediately.
# ------------------------------------------------------------------
@st.cache_data(ttl=60)
def load_issue(iss_id):
    res = (
        supabase.table("iss_collection")
        .select("*")
        .eq("iss_id", iss_id)
        .execute()
    )
    return pd.DataFrame(res.data)

# ------------------------------------------------------------------
# JOIN SEVERAL COMMENTS INTO ONE CELL
# Used by the pivot table below. It receives all comments that belong
# in the same cell, and returns them as one text with a line break
# (<br>) between them.
# html.escape turns characters like < and > into harmless text, so
# nobody can inject HTML code into your page through a comment.
# ------------------------------------------------------------------
def join_html(s):
    return "<br>".join(html.escape(str(x)) for x in s.dropna())

# ==================================================================
# THE PAGE (everything below runs from top to bottom on every click)
# ==================================================================
st.title("Issue matrix")

# The issue that is shown in the matrix and used for new entries.
# .strip() removes spaces before and after the text.
iss_id = st.text_input("Issue ID", value="Iss01").strip()

# ---------- ENTRY FORM ----------
st.subheader("Add an entry")

# Load the values for both dropdowns. If this fails (for example
# because a table or column was renamed), show the reason and stop.
try:
    levels = load_options(LEVEL_TABLE, LEVEL_COL, LEVEL_ID_COL)
    dimensions = load_options(DIMENSION_TABLE, DIMENSION_COL, DIMENSION_ID_COL)
except Exception as e:
    st.error(str(e))
    st.stop()

# A form sends all its fields together when the button is clicked.
# clear_on_submit=True empties the fields after saving.
with st.form("add_entry", clear_on_submit=True):
    # max_chars=80 stops typing after 80 characters
    comment = st.text_input("Short comment (max. 80 characters)", max_chars=80)
    level = st.selectbox("Level", levels)            # dropdown of levels
    dimension = st.selectbox("Dimension", dimensions)  # dropdown of dimensions
    submitted = st.form_submit_button("Add")         # True after a click

# What happens after the button was clicked
if submitted:
    if not iss_id:
        st.warning("Please enter an Issue ID.")
    elif not comment.strip():
        st.warning("Please enter a comment.")
    else:
        try:
            # Add one new row to the table iss_collection.
            # The keys on the left are the column names in the database.
            supabase.table("iss_collection").insert({
                "iss_id": iss_id,
                "level": level,
                "dimension": dimension,
                "comment_short": comment.strip(),
            }).execute()
            load_issue.clear()   # forget old data so the matrix is fresh
            st.success("Entry added.")
        except Exception as e:
            # Typical causes: missing permission (policy), a value that
            # does not match a lookup table, or a comment that is too long
            st.error(f"Could not save: {e}")

# ---------- MATRIX ----------
st.subheader(f"Matrix for {iss_id}")

df = load_issue(iss_id)

if df.empty:
    st.info("No rows for this Issue ID yet, or no read policy on iss_collection.")
else:
    # PIVOT: levels become the rows, dimensions become the columns,
    # and all comments that fall in the same cell are joined together
    # by join_html. Empty cells stay empty (fill_value="").
    matrix = df.pivot_table(
        index="level",
        columns="dimension",
        values="comment_short",
        aggfunc=join_html,
        fill_value="",
    )

    # ORDER: pivot_table sorts alphabetically. We want the order of the
    # lookup tables instead (sorted by id). Values that are not in the
    # lookup tables (for example old data) are placed at the end.
    rows = [l for l in levels if l in matrix.index] + \
           [l for l in matrix.index if l not in levels]
    cols = [d for d in dimensions if d in matrix.columns] + \
           [d for d in matrix.columns if d not in dimensions]
    matrix = matrix.loc[rows, cols]

    # Make the row and column labels safe for HTML, and remove the axis
    # names so the top-left corner of the table stays empty
    matrix = matrix.rename(index=html.escape, columns=html.escape)
    matrix.index.name = None
    matrix.columns.name = None

    # STYLE: borders, padding, and text that wraps inside the cells.
    # The colours are semi-transparent (rgba), so the table looks fine
    # in both the light and the dark theme.
    st.markdown(
        """
        <style>
        .matrix table {border-collapse: collapse; width: 100%;}
        .matrix th, .matrix td {
            border: 1px solid rgba(128,128,128,0.4);
            padding: 6px 8px;
            vertical-align: top;
            text-align: left;
            white-space: normal;
            overflow-wrap: anywhere;
            min-width: 120px;
        }
        .matrix th {background: rgba(128,128,128,0.15);}
        </style>
        """,
        unsafe_allow_html=True,
    )

    # SHOW the matrix as an HTML table. The surrounding div adds a
    # horizontal scrollbar if the table is wider than the page.
    st.markdown(
        f'<div class="matrix" style="overflow-x:auto">'
        f'{matrix.to_html(escape=False, border=0)}</div>',
        unsafe_allow_html=True,
    )
