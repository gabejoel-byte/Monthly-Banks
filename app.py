from datetime import date

import streamlit as st

from bootstrap import get_ready_conn
from core import calculations, commentary, db
from ui_helpers import apply_mobile_css

st.set_page_config(page_title="Monthly Banks P&L Tracker", page_icon="\U0001F4CA", layout="wide")
apply_mobile_css()

conn = get_ready_conn()

st.title("Monthly Banks P&L Tracker")

# ---------------------------------------------------------------------------
# What do I need to do? -- the most common reason to open this app.
# ---------------------------------------------------------------------------
current_month = date.today().strftime("%Y-%m")
status = db.accounts_status_for_month(conn, current_month)
n_total = len(status)

if n_total:
    n_uploaded = sum(1 for s in status if s["uploaded"])
    st.markdown(f"### This month ({current_month})")
    if n_uploaded == n_total:
        st.success(f"All {n_total} accounts uploaded for {current_month}. ✅")
    else:
        st.warning(f"{n_uploaded} of {n_total} accounts uploaded for {current_month} — {n_total - n_uploaded} still needed.")
        st.progress(n_uploaded / n_total)
    st.page_link("pages/1_Upload.py", label="Go to Upload", icon="\U0001F4E4")

    n_flagged_txns = len(db.flagged_transactions(conn))
    n_flagged_entries = len(db.flagged_entries(conn))
    n_flagged = n_flagged_txns + n_flagged_entries
    if n_flagged:
        st.warning(f"⚠ {n_flagged} line(s) across all months still need a category check.")
        st.page_link("pages/5_Review.py", label="Go to Review & Completeness", icon="\U0001F50D")

    with st.expander("How this app works"):
        st.markdown(
            "1. **Upload** — each month, drop in every account's export; the checklist tracks "
            "which ones are still missing.\n"
            "2. **Review & Completeness** — fix anything flagged for a category check, and catch "
            "accounts/categories that look missing.\n"
            "3. **Dashboards** — once a month is complete, see its P&L and how it compares over time."
        )

    st.markdown("---")

months = db.months_present(conn)

if not months:
    st.info(
        "No data yet. Run `python seed/import_history.py` once to load the 2026 "
        "history, or use **Upload** below to add a month."
    )
else:
    latest = months[-1]
    report = calculations.month_report(conn, latest)
    st.markdown(f"### Latest complete month on file: {latest}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Income", f"₪{report['totals']['income']:,.0f}")
    c2.metric("Personal Expenses", f"₪{report['totals']['personal']:,.0f}")
    c3.metric("Business Expenses", f"₪{report['totals']['business']:,.0f}")
    c4.metric("Net", f"₪{report['totals']['net']:,.0f}")

    st.markdown("#### What changed this month")
    for note in commentary.generate_commentary(conn, latest):
        st.write(f"- {note}")

st.markdown("---")
st.page_link("pages/1_Upload.py", label="Upload a new month", icon="\U0001F4E4")
st.page_link("pages/2_Monthly_Dashboard.py", label="Monthly Dashboard", icon="\U0001F4C5")
st.page_link("pages/3_Multi_Month_Dashboard.py", label="Multi-Month Dashboard", icon="\U0001F4C8")
st.page_link("pages/4_Category_Rules.py", label="Category Rules & Settings", icon="\U0001F6E0\U0000FE0F")
st.page_link("pages/5_Review.py", label="Review & Completeness", icon="\U0001F50D")
st.page_link("pages/6_All_Transactions.py", label="All Transactions", icon="\U0001F4CB")
