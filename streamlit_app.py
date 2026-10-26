import streamlit as st
import pandas as pd
import html
from supabase import create_client

# Lookup tables: table name, value column, id column used for sorting
LEVEL_TABLE, LEVEL_COL, LEVEL_ID_COL = "level_list", "level", "level_id"
COFACTOR_TABLE, COFACTOR_COL, COFACTOR_ID_COL = "co_factors_list", "co_factor", "co_factor_id"

# Issue descriptions: the pulldown shows the full description,
# iss_collection stores the matching id in its iss_id column.
# ASSUMPTION: iss_description has an "iss_id" column. Change if yours differs.
DESC_TABLE, DESC_COL, DESC_ID_COL = "iss_description", "iss_full_desc", "iss_id"


@st.cache_resource
def init_connection():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


supabase = init_connection()


def sorted_lookup(table, col, id_col):
    res = supabase.table(table).select("*").execute()
    df = pd.DataFrame(res.data)
    for c in (col, id_col):
        if c not in df.columns:
            raise KeyError(
                f"Column '{c}' not found in {table}. "
                f"Available columns: {list(df.columns)}"
            )
    # sort ascending by the id column (numerically if all ids are numbers)
    ids = pd.to_numeric(df[id_col], errors="coerce")
    if ids.notna().all():
        df = df.assign(_key=ids).sort_values("_key")
    else:
        df = df.sort_values(id_col)
    return df


@st.cache_data(ttl=300)
def load_options(table, col, id_col):
    df = sorted_lookup(table, col, id_col)
    return df[col].dropna().astype(str).drop_duplicates().tolist()


@st.cache_data(ttl=300)
def load_descriptions():
    """Returns an ordered dict {full description: iss_id}."""
    df = sorted_lookup(DESC_TABLE, DESC_COL, DESC_ID_COL)
    df = df.dropna(subset=[DESC_COL, DESC_ID_COL])
    return {str(r[DESC_COL]): str(r[DESC_ID_COL]) for _, r in df.iterrows()}


@st.cache_data(ttl=60)
def load_issue(iss_id):
    res = (
        supabase.table("iss_collection")
        .select("*")
        .eq("iss_id", iss_id)
        .order("rec_no")
        .execute()
    )
    return pd.DataFrame(res.data)


def join_html(s):
    return "<br>".join(html.escape(str(x)) for x in s.dropna())


def with_current(options, value):
    """Make sure a stored value that is no longer in the list can still be shown."""
    return options if value in options else options + [value]


st.title("Input form for Issue Collection with Matrix View")

# ---------- Load lookups ----------
try:
    levels = load_options(LEVEL_TABLE, LEVEL_COL, LEVEL_ID_COL)
    cofactors = load_options(COFACTOR_TABLE, COFACTOR_COL, COFACTOR_ID_COL)
    descriptions = load_descriptions()
except Exception as e:
    st.error(str(e))
    st.stop()

if not descriptions:
    st.warning("No rows found in iss_description (or no read policy).")
    st.stop()

# ---------- Issue selection ----------
selected_desc = st.selectbox("Issue", list(descriptions.keys()))
iss_id = descriptions[selected_desc]
st.caption(f"Issue ID: {iss_id}")

df = load_issue(iss_id)

# ---------- Entry form ----------
st.subheader("Add or update an entry")

mode = st.radio("Mode", ["Add new entry", "Update existing entry"], horizontal=True)
is_update = mode == "Update existing entry"

rec_no = None
current = {"comment_short": "", "comment_long": "", "level": None, "co_factor": None}

if is_update:
    if df.empty:
        st.info("No entries for this issue yet, so there is nothing to update.")
        st.stop()
    records = {int(r["rec_no"]): r for r in df.to_dict("records")}

    def label(n):
        r = records[n]
        return f"#{n} | {r.get('level')} | {r.get('co_factor')} | {r.get('comment_short')}"

    rec_no = st.selectbox("Entry to update", list(records.keys()), format_func=label)
    rec = records[rec_no]
    current = {
        "comment_short": rec.get("comment_short") or "",
        "comment_long": rec.get("comment_long") or "",
        "level": rec.get("level"),
        "co_factor": rec.get("co_factor"),
    }

level_opts = with_current(levels, current["level"]) if current["level"] else levels
cof_opts = with_current(cofactors, current["co_factor"]) if current["co_factor"] else cofactors

# keys include the record number, so the fields refresh when another entry is picked
k = f"{'u' if is_update else 'a'}_{rec_no}"

with st.form(f"entry_form_{k}", clear_on_submit=not is_update):
    comment = st.text_input(
        "Short comment (max. 80 characters)",
        value=current["comment_short"],
        max_chars=80,
        key=f"short_{k}",
    )
    comment_long = st.text_area(
        "Long comment",
        value=current["comment_long"],
        height=150,
        key=f"long_{k}",
    )
    level = st.selectbox(
        "Level",
        level_opts,
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

if submitted:
    if not comment.strip():
        st.warning("Please enter a short comment.")
    else:
        payload = {
            "iss_id": iss_id,
            "level": level,
            "co_factor": co_factor,
            "comment_short": comment.strip(),
            "comment_long": comment_long.strip(),
        }
        try:
            if is_update:
                res = (
                    supabase.table("iss_collection")
                    .update(payload)
                    .eq("rec_no", rec_no)
                    .execute()
                )
                if not res.data:
                    st.warning(
                        "Nothing was updated. Check that an UPDATE policy "
                        "exists on iss_collection."
                    )
                else:
                    load_issue.clear()
                    st.success(f"Entry #{rec_no} updated.")
            else:
                supabase.table("iss_collection").insert(payload).execute()
                load_issue.clear()
                st.success("Entry added.")
        except Exception as e:
            st.error(f"Could not save: {e}")

# ---------- Matrix ----------
st.subheader(f"Matrix for {selected_desc}")

df = load_issue(iss_id)

if df.empty:
    st.info("No rows for this issue yet, or no read policy on iss_collection.")
else:
    matrix = df.pivot_table(
        index="level",
        columns="co_factor",
        values="comment_short",
        aggfunc=join_html,
        fill_value="",
    )
    # follow the sort order of the lookup tables, unknown values at the end
    rows = [l for l in levels if l in matrix.index] + \
           [l for l in matrix.index if l not in levels]
    cols = [c for c in cofactors if c in matrix.columns] + \
           [c for c in matrix.columns if c not in cofactors]
    matrix = matrix.loc[rows, cols]

    # make the labels safe for HTML and tidy the corner
    matrix = matrix.rename(index=html.escape, columns=html.escape)
    matrix.index.name = None
    matrix.columns.name = None

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
    st.markdown(
        f'<div class="matrix" style="overflow-x:auto">'
        f'{matrix.to_html(escape=False, border=0)}</div>',
        unsafe_allow_html=True,
    )

    # ---------- Details table with long comments ----------
    with st.expander("All entries with long comments"):
        show_cols = [c for c in
                     ["rec_no", "level", "co_factor", "comment_short", "comment_long"]
                     if c in df.columns]
        st.dataframe(df[show_cols], use_container_width=True, hide_index=True)
