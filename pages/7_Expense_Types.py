import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from bootstrap import get_ready_conn
from core import calculations, categorize, db
from ui_helpers import apply_mobile_css, require_password

st.set_page_config(page_title="Fixed / Variable Expenses", page_icon="\U0001F9EE", layout="wide")
apply_mobile_css()
require_password()
conn = get_ready_conn()

st.title("Fixed / Variable / Semivariable Expenses")
st.caption(
    "Each month's spending split by cost behavior — **fixed** (same every month, e.g. mortgage, "
    "insurance), **variable** (fluctuates with your choices, e.g. groceries, entertainment), and "
    "**semivariable** (a fixed base plus usage, e.g. utilities, cellular). NIS and USD accounts are "
    "combined (USD converted at each month's exchange rate). Income and transfers are excluded. "
    "Change which category counts as what on the **Category Rules & Settings** page."
)

months = db.months_present(conn)
if not months:
    st.info("No data yet — upload a month first.")
    st.stop()

report = calculations.expense_type_report(conn, months)

TYPES = ["fixed", "variable", "semivariable"]
TYPE_LABEL = {"fixed": "Fixed", "variable": "Variable", "semivariable": "Semivariable"}
TYPE_COLORS = {"Fixed": "#2a78d6", "Variable": "#1baf7a", "Semivariable": "#eda100"}

no_rate_months = [r["month"] for r in report if r["rate"] == 0]
if no_rate_months:
    st.warning(
        "No USD→NIS exchange rate is set for: " + ", ".join(no_rate_months) +
        ". USD spending in those months is counted as 0 until you set a rate "
        "(on the Category Rules or All Transactions page)."
    )

# ---------------------------------------------------------------------------
# Monthly trend — stacked bar of the three cost types
# ---------------------------------------------------------------------------
st.markdown("### Monthly spend by type")
trend_rows = [
    {"month": r["month"], "type": TYPE_LABEL[t], "amount": round(r["buckets"][t], 2)}
    for r in report for t in TYPES
]
trend_df = pd.DataFrame(trend_rows)
fig = px.bar(
    trend_df, x="month", y="amount", color="type", barmode="stack",
    color_discrete_map=TYPE_COLORS, category_orders={"type": ["Fixed", "Semivariable", "Variable"]},
)
fig.update_layout(yaxis_title="Spend (NIS-equivalent)", xaxis_title="", legend_title="")
st.plotly_chart(fig, width="stretch")

# ---------------------------------------------------------------------------
# Totals table + monthly average
# ---------------------------------------------------------------------------
st.markdown("### Totals & monthly average")
summary = pd.DataFrame([{
    "month": r["month"],
    "Fixed": r["buckets"]["fixed"],
    "Variable": r["buckets"]["variable"],
    "Semivariable": r["buckets"]["semivariable"],
    "Total": r["buckets"]["total"],
} for r in report]).set_index("month").T
summary["Average"] = summary.mean(axis=1)
st.dataframe(summary.style.format("{:,.0f}"), width="stretch")

# ---------------------------------------------------------------------------
# Single-month category breakdown
# ---------------------------------------------------------------------------
st.markdown("### Category breakdown for one month")
sel = st.selectbox("Month", options=list(reversed(months)), key="etype_month")
row = next(r for r in report if r["month"] == sel)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Fixed", f"₪{row['buckets']['fixed']:,.0f}")
c2.metric("Variable", f"₪{row['buckets']['variable']:,.0f}")
c3.metric("Semivariable", f"₪{row['buckets']['semivariable']:,.0f}")
c4.metric("Total", f"₪{row['buckets']['total']:,.0f}")

detail_rows = [
    {"type": TYPE_LABEL[t], "category": cat, "amount (NIS)": round(amt, 2)}
    for t in TYPES
    for cat, amt in sorted(row["by_category"][t].items(), key=lambda x: -x[1])
]
if detail_rows:
    st.dataframe(pd.DataFrame(detail_rows), width="stretch", hide_index=True)
else:
    st.info(
        "No classified expenses for this month. If you expected some, check that the relevant "
        "categories have an expense_type set on the Category Rules page."
    )
