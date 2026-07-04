import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from bootstrap import get_ready_conn
from core import categorize, db
from ui_helpers import apply_mobile_css, confirm_all, render_category_table

st.set_page_config(page_title="Review & Completeness", page_icon="\U0001F50D", layout="wide")
apply_mobile_css()
conn = get_ready_conn()

st.title("Review & Completeness")
st.caption("What needs fixing before you trust a month's numbers. To browse the full ledger instead, use All Transactions.")

# ---------------------------------------------------------------------------
# One flat list of every flagged transaction, across every account
# ---------------------------------------------------------------------------
st.markdown("## Flagged transactions across all accounts")
st.caption(
    "Every transaction that still needs a category check, from every account, in one list — "
    "fix them here instead of hunting account by account. Saving confirms every row shown "
    "(whether you changed it or left the suggested category), and teaches the app that label for next time."
)

flag_txn_months = sorted({s["month"] for s in conn.execute("SELECT DISTINCT month FROM transactions").fetchall()})
if not flag_txn_months:
    st.info("No account transactions uploaded yet — use the Upload page first.")
else:
    flag_txn_month_filter = st.selectbox(
        "Month", options=["All months"] + list(reversed(flag_txn_months)), key="flag_txn_month_filter"
    )
    flagged_txns = db.flagged_transactions(
        conn, None if flag_txn_month_filter == "All months" else flag_txn_month_filter
    )

    if not flagged_txns:
        st.success("No flagged transactions — everything uploaded is cleanly categorized.")
    else:
        st.warning(f"{len(flagged_txns)} transaction(s) need a look.")
        flagged_txn_df = pd.DataFrame([{
            "id": t["id"],
            "month": t["month"],
            "account": t["account_name"],
            "date": t["txn_date"],
            "description": t["description"],
            "amount": t["amount"],
            "raw category": t["category_raw"],
            "category": t["category_canonical"],
        } for t in flagged_txns])

        edited_flagged_txns = render_category_table(
            flagged_txn_df, "category", categorize.canonical_names(conn),
            key=f"flagged_txn_editor::{flag_txn_month_filter}",
            hide=["raw category"],
        )

        if st.button("Save all categorized rows above", type="primary", key="save_flagged_txns"):
            by_id = {t["id"]: t for t in flagged_txns}

            def apply_txn(txn_id, new_category):
                db.update_transaction_category(conn, int(txn_id), new_category)

            applied = confirm_all(
                conn, flagged_txn_df, edited_flagged_txns, "id", "category", apply_txn, raw_col="raw category",
            )
            touched_month_currency = {
                (by_id[txn_id]["month"], by_id[txn_id]["account_currency"]) for txn_id, _ in applied
            }
            for touched_month, touched_currency in touched_month_currency:
                db.rollup_entries_for_month_currency(conn, touched_month, touched_currency)
            st.success(f"Updated {len(applied)} transaction(s) across {len(touched_month_currency)} month/currency total(s).")
            st.rerun()

st.markdown("---")

months = db.months_present(conn)
if not months:
    st.info("No data yet — upload a month first.")
    st.stop()

# ---------------------------------------------------------------------------
# Uncategorized / flagged lines (legacy combined-file upload path)
# ---------------------------------------------------------------------------
st.markdown("## Uncategorized lines")
st.caption(
    "From the legacy combined-file upload path (Category Rules & Settings' 'Known file layouts' shows "
    "which months came in this way). Rows saved via alias/fuzzy match, or left unresolved at upload time, "
    "stay flagged here until you confirm the right category. Confirming also teaches the app that label for next time."
)

month_filter = st.selectbox("Month", options=["All months"] + list(reversed(months)), key="flag_month_filter")
flagged = db.flagged_entries(conn, None if month_filter == "All months" else month_filter)

if not flagged:
    st.success("No flagged lines — everything on file is cleanly categorized.")
else:
    st.warning(f"{len(flagged)} line(s) need a look.")
    flagged_df = pd.DataFrame([{
        "id": r["id"],
        "month": r["month"],
        "currency": r["bank_currency"],
        "raw label": r["category_raw"],
        "amount": r["amount"],
        "category": r["category_canonical"],
        "matched via": r["match_method"],
    } for r in flagged])

    edited_flags = render_category_table(
        flagged_df, "category", categorize.canonical_names(conn), key="flagged_editor",
        hide=["matched via"],
    )

    if st.button("Confirm all rows above", type="primary"):
        def apply_entry(entry_id, new_category):
            db.confirm_entry(conn, int(entry_id), new_category)

        applied = confirm_all(conn, flagged_df, edited_flags, "id", "category", apply_entry, raw_col="raw label")
        st.success(f"Confirmed {len(applied)} row(s).")
        st.rerun()

st.markdown("---")

# ---------------------------------------------------------------------------
# Missing categories / accounts per month
# ---------------------------------------------------------------------------
st.markdown("## Missing accounts & categories")
st.caption("Checks whether a month's upload looks complete before you trust its totals.")

check_month = st.selectbox("Month to check", options=list(reversed(months)), key="completeness_month")
all_categories = set(categorize.canonical_names(conn))
present_currencies = db.currencies_present_for_month(conn, check_month)

expected_currencies = {"NIS", "USD"}
missing_currencies = expected_currencies - present_currencies
if missing_currencies:
    st.error(
        f"No {'/'.join(sorted(missing_currencies))} entries at all for {check_month} — "
        "looks like that bank's export wasn't uploaded for this month."
    )
else:
    st.success("Both Israel-NIS and USA-USD sections are present for this month.")

months_before = [m for m in months if m < check_month]
prev_month = months_before[-1] if months_before else None

for currency in sorted(present_currencies):
    present = db.categories_present_for_month(conn, check_month, currency)
    missing = sorted(all_categories - present)
    st.markdown(f"**{currency}: {len(present)}/{len(all_categories)} categories present**")
    if missing:
        with st.expander(f"{len(missing)} categor{'y' if len(missing)==1 else 'ies'} not uploaded at all for {currency} this month"):
            st.write(", ".join(missing))

    if prev_month:
        prev_present = db.categories_present_for_month(conn, prev_month, currency)
        regressed = sorted(prev_present - present)
        if regressed:
            st.warning(
                f"These {currency} categories were reported in {prev_month} but are missing from "
                f"{check_month} — worth double-checking they weren't accidentally dropped: {', '.join(regressed)}"
            )
