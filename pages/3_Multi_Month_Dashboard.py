import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from bootstrap import get_ready_conn
from core import calculations, db
from ui_helpers import CATEGORY_COLORS, ENTITY_COLORS, apply_mobile_css

st.set_page_config(page_title="Multi-Month Dashboard", page_icon="\U0001F4C8", layout="wide")
apply_mobile_css()
conn = get_ready_conn()

st.title("Multi-Month Dashboard")

months = db.months_present(conn)
if not months:
    st.info("No data yet — upload a month first.")
    st.stop()

reports = calculations.multi_month_reports(conn, months)

st.markdown("### Trend")
trend_df = pd.DataFrame([
    {
        "month": r["month"],
        "Income": r["totals"]["income"],
        "Personal Expenses": r["totals"]["personal"],
        "Business Expenses": r["totals"]["business"],
        "KH/Pension": r["totals"]["pension"],
        "Net": r["totals"]["net"],
    }
    for r in reports
])
fig = px.line(
    trend_df.melt(id_vars="month", var_name="series", value_name="amount"),
    x="month", y="amount", color="series", markers=True,
    color_discrete_map=CATEGORY_COLORS,
)
st.plotly_chart(fig, width='stretch')

st.markdown("### YTD totals & monthly average")
summary_df = trend_df.set_index("month").T
summary_df["YTD Total"] = summary_df.sum(axis=1)
summary_df["Month Average"] = summary_df[months].mean(axis=1)
st.dataframe(summary_df.style.format("{:,.0f}"), width='stretch')

st.markdown("### Category trend (combined, NIS-equivalent)")
cat_rows = []
for r in reports:
    for cat, amount in r["combined"].items():
        cat_rows.append({"month": r["month"], "category": cat, "amount": amount})
cat_df = pd.DataFrame(cat_rows)
pivot = cat_df.pivot_table(index="category", columns="month", values="amount", fill_value=0)
pivot["YTD Total"] = pivot[months].sum(axis=1)
pivot["Month Average"] = pivot[months].mean(axis=1)
pivot = pivot.reindex(pivot["YTD Total"].abs().sort_values(ascending=False).index)
st.dataframe(pivot.style.format("{:,.0f}"), width='stretch', height=600)

st.markdown("### Entity Final Net trend")
entity_df = pd.DataFrame([
    {
        "month": r["month"],
        "Private Final Net": r["private"]["final_net"],
        "Chevra Final Net": r["chevra"]["final_net"],
        "USA Final Net": r["usa"]["final_net"],
    }
    for r in reports
])
fig2 = px.line(
    entity_df.melt(id_vars="month", var_name="entity", value_name="final_net"),
    x="month", y="final_net", color="entity", markers=True,
    color_discrete_map=ENTITY_COLORS,
)
st.plotly_chart(fig2, width='stretch')
