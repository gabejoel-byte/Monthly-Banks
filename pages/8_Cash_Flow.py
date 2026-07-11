import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from bootstrap import get_ready_conn
from core import calculations, db
from ui_helpers import apply_mobile_css, require_password

st.set_page_config(page_title="Cash Flow", page_icon="\U0001F4B8", layout="wide")
apply_mobile_css()
require_password()
conn = get_ready_conn()

st.title("Cash Flow — Inflow & Outflow")
st.caption(
    "Money in vs money out each month. **Shekels** and **Dollars** are shown in their own "
    "currency; **Combined** converts dollars into shekels at that month's exchange rate, which "
    "you can calibrate right on the Combined tab."
)

months = db.months_present(conn)
if not months:
    st.info("No data yet — upload a month first.")
    st.stop()

month = st.selectbox("Month", options=list(reversed(months)), key="cashflow_month")

INFLOW_COLOR, OUTFLOW_COLOR = "#1baf7a", "#e34948"


def render_section(section: dict, symbol: str) -> None:
    c1, c2, c3 = st.columns(3)
    c1.metric("Inflow (money in)", f"{symbol}{section['inflow']:,.0f}")
    c2.metric("Outflow (money out)", f"{symbol}{abs(section['outflow']):,.0f}")
    c3.metric("Net", f"{symbol}{section['net']:,.0f}")

    rows = [
        {"category": c, "amount": a, "direction": "Inflow" if a > 0 else "Outflow"}
        for c, a in section["amounts"].items() if a
    ]
    if not rows:
        st.info("No activity recorded for this month in this currency.")
        return

    df = pd.DataFrame(rows).sort_values("amount")
    fig = px.bar(
        df, x="amount", y="category", color="direction", orientation="h",
        color_discrete_map={"Inflow": INFLOW_COLOR, "Outflow": OUTFLOW_COLOR},
        height=max(320, 26 * len(df)),
    )
    fig.update_layout(xaxis_title=f"Amount ({symbol})", yaxis_title="", legend_title="")
    st.plotly_chart(fig, width="stretch")

    col1, col2 = st.columns(2)
    inflow_df = (
        df[df["amount"] > 0][["category", "amount"]]
        .sort_values("amount", ascending=False).reset_index(drop=True)
    )
    outflow_df = (
        df[df["amount"] < 0].assign(amount=lambda d: d["amount"].abs())[["category", "amount"]]
        .sort_values("amount", ascending=False).reset_index(drop=True)
    )
    with col1:
        st.markdown("**Money in**")
        if len(inflow_df):
            st.dataframe(inflow_df.style.format({"amount": f"{symbol}{{:,.0f}}"}), width="stretch", hide_index=True)
        else:
            st.caption("None this month.")
    with col2:
        st.markdown("**Money out**")
        if len(outflow_df):
            st.dataframe(outflow_df.style.format({"amount": f"{symbol}{{:,.0f}}"}), width="stretch", hide_index=True)
        else:
            st.caption("None this month.")


cf = calculations.cashflow_for_month(conn, month)
tab_nis, tab_usd, tab_combined = st.tabs(["₪ Shekels (NIS)", "$ Dollars (USD)", "Combined (NIS-equivalent)"])

with tab_nis:
    render_section(cf["nis"], "₪")

with tab_usd:
    render_section(cf["usd"], "$")

with tab_combined:
    current_rate = db.get_fx_rate(conn, month) or 3.7
    with st.popover(f"Exchange rate: {current_rate:.4f}  (tap to change)"):
        new_rate = st.number_input(
            f"USD → NIS rate for {month}", value=float(current_rate), format="%.4f", key=f"cashflow_fx::{month}",
        )
        if st.button("Save exchange rate", key=f"cashflow_fx_save::{month}"):
            db.set_fx_rate(conn, month, new_rate)
            st.success(f"Saved USD → NIS rate {new_rate:.4f} for {month}.")
            st.rerun()

    if cf["rate"] is None:
        st.warning(
            "No exchange rate is set for this month yet, so dollars are counted as 0 in the "
            "combined view. Set one above to convert and combine."
        )
    st.caption(f"Dollars converted to shekels at {current_rate:.4f} for {month}.")
    render_section(cf["combined"], "₪")
