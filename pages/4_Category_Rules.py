import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from bootstrap import get_ready_conn
from core import categorize, db
from ui_helpers import apply_mobile_css, require_password

st.set_page_config(page_title="Category Rules & Settings", page_icon="\U0001F6E0\U0000FE0F", layout="wide")
apply_mobile_css()
require_password()
conn = get_ready_conn()

st.title("Category Rules & Settings")

st.markdown("### Category classification")
st.caption(
    "Every category feeds one P&L bucket. 'excluded' means transfers/settlements "
    "left out of all totals; 'charity' is tracked separately from the automatic Tzedaka calc."
)
cats = conn.execute("SELECT canonical_name, group_name FROM categories ORDER BY canonical_name").fetchall()
cats_df = pd.DataFrame([dict(r) for r in cats])
edited_cats = st.data_editor(
    cats_df,
    width='stretch',
    disabled=["canonical_name"],
    column_config={
        "group_name": st.column_config.SelectboxColumn(
            "group_name", options=["income", "personal", "business", "pension", "charity", "excluded"], required=True,
        )
    },
    key="categories_editor",
)
if st.button("Save category classification"):
    for _, row in edited_cats.iterrows():
        categorize.add_category(conn, row["canonical_name"], row["group_name"])
    st.success("Saved.")

with st.expander("Add a new category"):
    with st.form("new_category_form"):
        name = st.text_input("Category name")
        group = st.selectbox("Group", ["income", "personal", "business", "pension", "charity", "excluded"])
        if st.form_submit_button("Add") and name:
            categorize.add_category(conn, name, group)
            st.success(f"Added {name}.")
            st.rerun()

st.markdown("### Learned category aliases")
st.caption("Raw labels from uploads that were mapped to a canonical category, either automatically or by your confirmation.")
aliases = conn.execute("SELECT raw_label, canonical_name FROM category_aliases ORDER BY canonical_name").fetchall()
if aliases:
    st.dataframe(pd.DataFrame([dict(r) for r in aliases]), width='stretch')
else:
    st.write("No learned aliases yet.")

st.markdown("### FX rates (USD → NIS)")
rates = conn.execute("SELECT month, rate FROM fx_rates ORDER BY month").fetchall()
rates_df = pd.DataFrame([dict(r) for r in rates]) if rates else pd.DataFrame(columns=["month", "rate"])
edited_rates = st.data_editor(rates_df, width='stretch', num_rows="dynamic", key="rates_editor")
if st.button("Save FX rates"):
    for _, row in edited_rates.iterrows():
        if row["month"] and row["rate"]:
            db.set_fx_rate(conn, row["month"], float(row["rate"]))
    st.success("Saved.")

st.markdown("### Known file layouts")
st.caption("Each distinct upload shape gets remembered here so future files from the same source auto-parse.")
profiles = db.list_format_profiles(conn)
if profiles:
    st.dataframe(pd.DataFrame([dict(r) for r in profiles]), width='stretch')
else:
    st.write("No file layouts learned yet.")
