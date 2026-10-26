# =====================================================================
# Issue Collection with Matrix View
# Streamlit (the web page) + Supabase (the database)
#
# How a Streamlit app works, in one sentence:
# every time you click or type something, Streamlit runs this WHOLE
# file again from top to bottom. That is why we use caching below,
# so we don't ask the database the same question on every rerun.
# =====================================================================

import streamlit as st          # builds the web page
import pandas as pd             # tables ("DataFrames") and pivoting
import html                     # html.escape() makes text safe to put inside HTML
from supabase import create_client   # connection to the database

# ---------------------------------------------------------------------
# SETTINGS: names of tables and columns in one place.
# If you ever rename something in Supabase, change it here only.
# ---------------------------------------------------------------------
# (table name, column with the text, column with the id used for sorting)
LEVEL_TABLE, LEVEL_COL, LEVEL_ID_COL = "level_list", "level", "level_id"
COFACTOR_TABLE, COFACTOR_COL, COFACTOR_ID_COL = "co_factors_list", "co_factor", "co_factor_id"

# The issue pulldown shows the full description, but iss_collection
# stores the short id. ASSUMPTION: iss_description has a column "iss_id".
DESC_TABLE, DESC_COL, DESC_ID_COL = "iss_description", "iss_full_desc", "iss_id"


# ---------------------------------------------------------------------
# DATABASE CONNECTION
# @st.cache_resource = "create this once and keep it", so the
# connection is not rebuilt on every rerun.
# st.secrets reads your URL and key from .streamlit/secrets.toml
# ---------------------------------------------------------------------
@st.cache_resource
def init_connection():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


supabase = init_connection()


# ---------------------------------------------------------------------
# LOADING DATA
# ---------------------------------------------------------------------
def sorted_lookup(table, col, id_col):
    """Read a whole lookup table and sort it by its id column."""
    res = supabase.table(table).select("*").execute()   # SELECT * FROM table
    df = pd.DataFrame(res.data)                         # list of dicts -> table

    # Fail early with a helpful message if a column name is wrong
    for c in (col, id_col):
        if c not in df.columns:
            raise KeyError(
                f"Column '{c}' not found in {table}. "
                f"Available columns: {list(df.columns)}"
            )

    # Sort by id. If all ids are numbers, sort as numbers (so 2 comes before 10);
    # otherwise sort as text.
    ids = pd.to_numeric(df[id_col], errors="coerce")    # non-numbers become NaN
    if ids.notna().all():
        df = df.assign(_key=ids).sort_values("_key")
    else:
        df = df.sort_values(id_col)
    return df


# @st.cache_data = "remember the result for ttl seconds".
# Lookup lists rarely change, so 300 seconds (5 minutes) is fine.
@st.cache_data(ttl=300)
def load_options(table, col, id_col):
    """Return the values of a lookup table as a plain Python list."""
    df = sorted_lookup(table, col, id_col)
    return df[col].dropna().astype(str).drop_duplicates().tolist()


@st.cache_data(ttl=300)
def load_descriptions():
    """Return a dict {full description: iss_id}, in sorted order."""
    df = sorted_lookup(DESC_TABLE, DESC_COL, DESC_ID_COL)
    df = df.dropna(subset=[DESC_COL, DESC_ID_COL])      # skip incomplete rows
    return {str(r[DESC_COL]): str(r[DESC_ID_COL]) for _, r in df.iterrows()}


# Entries change often, so only cache for 60 seconds. After saving we also
# call load_issue.clear() to throw the cache away immediately.
@st.cache_data(ttl=60)
def load_issue(iss_id):
    """Return all entries of ONE issue as a table, ordered by rec_no."""
    res = (
        supabase.table("iss_collection")
        .select("*")
        .eq("iss_id", iss_id)       # WHERE iss_id = ...
        .order("rec_no")            # ORDER BY rec_no
        .execute()
    )
    return pd.DataFrame(res.data)


# ---------------------------------------------------------------------
# SMALL HELPER FUNCTIONS
# ---------------------------------------------------------------------
def with_current(options, value):
    """If a saved value is no longer in the pulldown list, add it at the end
    so that editing an old entry does not silently change its value."""
    return options if value in options else options + [value]


def make_cell(row):
    """Build the HTML for ONE entry in the matrix.

    - Without a long comment: just the short comment as text.
    - With a long comment: the short comment wrapped in a <span> whose
      'title' attribute holds the long comment. The browser shows the
      title text as a pop-up when you hover over the span.
    """
    short = row.get("comment_short")
    if short is None or pd.isna(short):
        return ""
    # html.escape turns < > & " into safe codes, so user text can never
    # break the page or inject HTML.
    short = html.escape(str(short))

    long_text = row.get("comment_long")
    if long_text is None or pd.isna(long_text) or not str(long_text).strip():
        return short                                    # nothing to show on hover

    tip = html.escape(str(long_text).strip(), quote=True)
    # A real line break inside the text could end the HTML block early
    # (Markdown treats empty lines specially), so we write line breaks as
    # &#10; which the browser displays as a new line inside the pop-up.
    tip = tip.replace("\r\n", "&#10;").replace("\n", "&#10;")
    return f'<span class="has-tip" title="{tip}">{short}</span>'


def join_cells(s):
    """Several entries can sit in the same matrix cell (same level AND
    co-factor). Put them under each other, separated by <br> (line break)."""
    return "<br>".join(x for x in s if x)


# =====================================================================
# THE PAGE
# =====================================================================
st.title("Input form for Issue Collection with Matrix View")

# ---------- Load the lists for the pulldowns ----------
# try/except: if loading fails, show the error on the page and stop,
# instead of crashing with a long technical message.
try:
    levels = load_options(LEVEL_TABLE, LEVEL_COL, LEVEL_ID_COL)
    cofactors = load_options(COFACTOR_TABLE, COFACTOR_COL, COFACTOR_ID_COL)
    descriptions = load_descriptions()
except Exception as e:
    st.error(str(e))
    st.stop()                       # nothing below this line runs

if not descriptions:
    st.warning("No rows found in iss_description (or no read policy).")
    st.stop()

# ---------- Choose the issue ----------
# The user sees the long description, we look up the matching id.
selected_desc = st.selectbox("Issue", list(descriptions.keys()))
iss_id = descriptions[selected_desc]
st.caption(f"Issue ID: {iss_id}")

df = load_issue(iss_id)             # all entries of this issue

# ---------- Entry form: add OR update ----------
st.subheader("Add or update an entry")

mode = st.radio("Mode", ["Add new entry", "Update existing entry"], horizontal=True)
is_update = mode == "Update existing entry"

rec_no = None
# Start values for the form fields (empty when adding a new entry)
current = {"comment_short": "", "comment_long": "", "level": None, "co_factor": None}

if is_update:
    if df.empty:
        st.info("No entries for this issue yet, so there is nothing to update.")
        st.stop()

    # Dict {rec_no: whole row}, so we can find an entry by its number
    records = {int(r["rec_no"]): r for r in df.to_dict("records")}

    def label(n):
        """Text shown for each entry in the pulldown."""
        r = records[n]
        return f"#{n} | {r.get('level')} | {r.get('co_factor')} | {r.get('comment_short')}"

    # format_func tells Streamlit how to display each rec_no
    rec_no = st.selectbox("Entry to update", list(records.keys()), format_func=label)
    rec = records[rec_no]
    # "or ''" turns an empty database value (None) into an empty text
    current = {
        "comment_short": rec.get("comment_short") or "",
        "comment_long": rec.get("comment_long") or "",
        "level": rec.get("level"),
        "co_factor": rec.get("co_factor"),
    }

level_opts = with_current(levels, current["level"]) if current["level"] else levels
cof_opts = with_current(cofactors, current["co_factor"]) if current["co_factor"] else cofactors

# Streamlit remembers what is typed into a field by its "key". If the key
# contains the record number, the fields get fresh values whenever you pick
# a different entry (a new key = a new field).
k = f"{'u' if is_update else 'a'}_{rec_no}"

# st.form collects all fields and only sends them when the button is pressed
# (without a form, every keystroke would rerun the whole file).
# clear_on_submit empties the fields after adding, but not after updating.
with st.form(f"entry_form_{k}", clear_on_submit=not is_update):
    comment = st.text_input(
        "Short comment (max. 80 characters)",
        value=current["comment_short"],
        max_chars=80,
        key=f"short_{k}",
    )
    comment_long = st.text_area(
        "Long comment (shown as pop-up in the matrix)",
        value=current["comment_long"],
        height=150,
        key=f"long_{k}",
    )
    level = st.selectbox(
        "Level",
        level_opts,
        # index = which item is preselected (counting from 0)
        index=level_opts.index(current["level"]) if current["level"] else 0,
        key=f"level_{k}",
    )
    co_factor = st.selectbox(
        "Co-factor",
        cof_opts,
        index=cof_opts.index(current["co_factor"]) if current["co_factor"] else 0,
        key=f"cof_{k}",
    )
    submitted = st.form_submit_button("Update" if is_update else "Add")

# ---------- Save when the button was pressed ----------
if submitted:
    if not comment.strip():                 # .strip() removes spaces at both ends
        st.warning("Please enter a short comment.")
    else:
        # The data we send to the database: column name -> value.
        # user_id is NOT sent; the database fills it in via its default.
        payload = {
            "iss_id": iss_id,
            "level": level,
            "co_factor": co_factor,
            "comment_short": comment.strip(),
            "comment_long": comment_long.strip(),
        }
        try:
            if is_update:
                # UPDATE iss_collection SET ... WHERE rec_no = <chosen entry>
                res = (
                    supabase.table("iss_collection")
                    .update(payload)
                    .eq("rec_no", rec_no)
                    .execute()
                )
                # Without an UPDATE policy Supabase changes nothing and
                # raises no error. An empty result tells us that happened.
                if not res.data:
                    st.warning(
                        "Nothing was updated. Check that an UPDATE policy "
                        "exists on iss_collection."
                    )
                else:
                    load_issue.clear()      # forget the cached entries
                    st.success(f"Entry #{rec_no} updated.")
            else:
                # INSERT INTO iss_collection ...
                supabase.table("iss_collection").insert(payload).execute()
                load_issue.clear()
                st.success("Entry added.")
        except Exception as e:
            st.error(f"Could not save: {e}")

# ---------- Matrix ----------
st.subheader(f"Matrix for {selected_desc}")

df = load_issue(iss_id)         # load again, so the new entry is included

if df.empty:
    st.info("No rows for this issue yet, or no read policy on iss_collection.")
else:
    # Step 1: build the HTML of every entry (short comment + hover text)
    # and store it in a new column. apply(..., axis=1) calls make_cell
    # once for every row.
    df = df.assign(cell_html=df.apply(make_cell, axis=1))

    # Step 2: pivot. Rows = level, columns = co-factor, cell content =
    # all cell_html pieces that belong together, joined by join_cells.
    matrix = df.pivot_table(
        index="level",
        columns="co_factor",
        values="cell_html",
        aggfunc=join_cells,
        fill_value="",              # empty cells stay empty
    )

    # Step 3: bring rows and columns into the order of the lookup tables.
    # Values that are not in the lookup tables (old data) go at the end.
    rows = [l for l in levels if l in matrix.index] + \
           [l for l in matrix.index if l not in levels]
    cols = [c for c in cofactors if c in matrix.columns] + \
           [c for c in matrix.columns if c not in cofactors]
    matrix = matrix.loc[rows, cols]

    # Step 4: make the row/column labels safe for HTML and remove the
    # small axis names in the top-left corner.
    matrix = matrix.rename(index=html.escape, columns=html.escape)
    matrix.index.name = None
    matrix.columns.name = None

    # Step 5: CSS = the styling of the table. .has-tip is the underlined
    # text that has a pop-up; cursor: help shows a question-mark cursor.
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
        .matrix .has-tip {
            border-bottom: 1px dotted currentColor;
            cursor: help;
        }
        </style>
        """,
        unsafe_allow_html=True,     # allow our own HTML/CSS in st.markdown
    )

    # Step 6: show the table. to_html(escape=False) keeps our <span> and
    # <br> tags (we already escaped all user text in make_cell).
    st.markdown(
        f'<div class="matrix" style="overflow-x:auto">'
        f'{matrix.to_html(escape=False, border=0)}</div>',
        unsafe_allow_html=True,
    )

    # ---------- Details table with long comments ----------
    # An expander is a collapsible section. Useful to find rec_no values
    # and to read long comments on a phone, where there is no hover.
    with st.expander("All entries with long comments"):
        show_cols = [c for c in
                     ["rec_no", "level", "co_factor", "comment_short", "comment_long"]
                     if c in df.columns]
        st.dataframe(df[show_cols], use_container_width=True, hide_index=True)
