import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from bootstrap import get_ready_conn
from core import categorize, db
from ui_helpers import apply_mobile_css, render_category_table, require_password, save_changed

st.set_page_config(page_title="All Transactions", page_icon="\U0001F4CB", layout="wide")
apply_mobile_css()
require_password()
conn = get_ready_conn()

st.title("All Transactions")
st.caption(
    "Every individual charge across every account, in one place, so you can review them all "
    "and confirm they're correct. NIS accounts (Yahav, Israeli cards) and USD accounts (USA "
    "banks/cards) are shown together with a converted NIS column, using each month's exchange rate below."
)

accounts_list = db.list_accounts(conn)
txn_months = sorted({s["month"] for s in conn.execute("SELECT DISTINCT month FROM transactions").fetchall()})

if not accounts_list:
    st.info("No accounts configured yet.")
    st.stop()
if not txn_months:
    st.info("No account transactions uploaded yet — use the Upload page first.")
    st.stop()

col1, col2 = st.columns([1, 2])
month = col1.selectbox("Month", options=["All months"] + list(reversed(txn_months)), key="all_txn_month")

view_mode = col2.radio(
    "Accounts", options=["All accounts", "Specific accounts"], horizontal=True, key="all_txn_view_mode",
)
if view_mode == "Specific accounts":
    account_names = st.multiselect(
        "Choose account(s)",
        options=[a["display_name"] for a in accounts_list],
        default=[accounts_list[0]["display_name"]],
        key="all_txn_accounts",
    )
    selected_ids = {a["id"] for a in accounts_list if a["display_name"] in account_names}
else:
    selected_ids = {a["id"] for a in accounts_list}

# ---------------------------------------------------------------------------
# Exchange rate calibration -- needed to make sense of NIS + USD side by side
# ---------------------------------------------------------------------------
if month == "All months":
    st.caption(
        "Amounts are shown in each account's native currency below. Pick a single month above "
        "to also calibrate its USD → NIS rate and see a converted total."
    )
else:
    current_rate = db.get_fx_rate(conn, month) or 3.7
    with st.popover(f"Exchange rate: {current_rate:.4f}"):
        new_rate = st.number_input(
            f"USD → NIS rate for {month}", value=float(current_rate), format="%.4f", key=f"all_txn_fx_rate::{month}",
        )
        if st.button("Save exchange rate", key="save_all_txn_fx_rate"):
            db.set_fx_rate(conn, month, new_rate)
            st.success(f"Saved USD → NIS rate {new_rate:.4f} for {month}.")
            st.rerun()

# ---------------------------------------------------------------------------
# The transaction list
# ---------------------------------------------------------------------------
account_by_id = {a["id"]: a for a in accounts_list}
if month == "All months":
    raw_rows = conn.execute("SELECT * FROM transactions ORDER BY month, account_id, txn_date, id").fetchall()
else:
    raw_rows = conn.execute(
        "SELECT * FROM transactions WHERE month = ? ORDER BY account_id, txn_date, id", (month,)
    ).fetchall()
raw_rows = [r for r in raw_rows if r["account_id"] in selected_ids]

st.markdown(f"#### {len(raw_rows)} transaction(s)")
if not raw_rows:
    st.info("No transactions match this filter.")
else:
    fx_cache: dict[str, float] = {}

    def to_nis(amount: float, currency: str, txn_month: str) -> float | None:
        if currency == "NIS":
            return amount
        if txn_month not in fx_cache:
            fx_cache[txn_month] = db.get_fx_rate(conn, txn_month) or 0.0
        rate = fx_cache[txn_month]
        return amount * rate if rate else None

    table_rows = []
    for t in raw_rows:
        acc = account_by_id[t["account_id"]]
        nis_amount = to_nis(t["amount"], acc["currency"], t["month"])
        table_rows.append({
            "id": t["id"],
            "month": t["month"],
            "account": acc["display_name"],
            "currency": acc["currency"],
            "date": t["txn_date"],
            "description": t["description"],
            "amount": t["amount"],
            "amount (NIS)": round(nis_amount, 2) if nis_amount is not None else None,
            "category": t["category_canonical"],
            "needs review": bool(t["needs_review"]),
        })
    txn_df = pd.DataFrame(table_rows)

    n_flagged = int(txn_df["needs review"].sum())
    if n_flagged:
        st.info(f"{n_flagged} of these still need a category check (also listed on the Review page).")
    if txn_df["amount (NIS)"].isna().any():
        st.warning("Some USD rows have no exchange rate set for their month yet — their NIS column is blank.")

    edited = render_category_table(
        txn_df, "category", categorize.canonical_names(conn),
        key=f"all_txn_editor::{month}::{view_mode}::{sorted(selected_ids)}",
        disabled=["id", "month", "account", "currency", "date", "description", "amount", "amount (NIS)", "needs review"],
        hide=["needs review"],
    )

    if st.button("Save category corrections", type="primary", key="save_all_txns"):
        by_id = {t["id"]: t for t in raw_rows}

        def apply_txn(txn_id, new_category):
            db.update_transaction_category(conn, int(txn_id), new_category)

        applied = save_changed(txn_df, edited, "id", "category", apply_txn)
        touched_month_currency = {
            (by_id[txn_id]["month"], account_by_id[by_id[txn_id]["account_id"]]["currency"])
            for txn_id, _ in applied
        }
        for touched_month, touched_currency in touched_month_currency:
            db.rollup_entries_for_month_currency(conn, touched_month, touched_currency)
        st.success(f"Updated {len(applied)} transaction(s).")
        st.rerun()
