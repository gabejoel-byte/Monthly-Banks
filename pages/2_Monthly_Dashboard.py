import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from bootstrap import get_ready_conn
from core import calculations, commentary, db
from ui_helpers import CATEGORY_COLORS, apply_mobile_css

st.set_page_config(page_title="Monthly Dashboard", page_icon="\U0001F4C5", layout="wide")
apply_mobile_css()
conn = get_ready_conn()

st.title("Monthly Dashboard")

months = db.months_present(conn)
if not months:
    st.info("No data yet — upload a month first.")
    st.stop()

month = st.selectbox("Month", options=list(reversed(months)))
report = calculations.month_report(conn, month)

st.markdown("### Summary")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Income", f"₪{report['totals']['income']:,.0f}")
c2.metric("Personal Expenses", f"₪{report['totals']['personal']:,.0f}")
c3.metric("Business Expenses", f"₪{report['totals']['business']:,.0f}")
c4.metric("KH/Pension", f"₪{report['totals']['pension']:,.0f}")
c5.metric("Net", f"₪{report['totals']['net']:,.0f}")

st.markdown("### Private / Chevra / USA breakdown")
entity_rows = []
for entity in ("private", "chevra", "usa"):
    e = report[entity]
    entity_rows.append({
        "Entity": entity.title(),
        "Gross": e["gross"], "Expenses": e["expenses"],
        "Pre-Tax": e.get("pretax", 0.0), "Tax": e["tax"], "VAT": e.get("vat", 0.0),
        "Net": e["net"], "Tzedaka": e["tzedaka"], "Savings": e["savings"], "Final Net": e["final_net"],
    })
st.dataframe(pd.DataFrame(entity_rows).set_index("Entity").style.format("{:,.0f}"), width='stretch')

c1, c2 = st.columns(2)
c1.metric("Israel Banks net after Personal expenses", f"₪{report['israel_net_after_personal']:,.0f}")
c2.metric("USA Final Net after Personal expenses", f"${report['usa_net_after_personal']:,.0f}")

st.markdown("### Category breakdown")
group_of = {r["canonical_name"]: r["group_name"] for r in conn.execute("SELECT canonical_name, group_name FROM categories")}
cat_df = pd.DataFrame([
    {"category": cat, "amount": amount, "group": group_of.get(cat, "personal")}
    for cat, amount in report["combined"].items() if amount != 0
]).sort_values("amount")

col1, col2 = st.columns([2, 1])
with col1:
    fig = px.bar(
        cat_df, x="amount", y="category", color="group", orientation="h", height=900,
        color_discrete_map=CATEGORY_COLORS,
    )
    st.plotly_chart(fig, width='stretch')
with col2:
    split_df = pd.DataFrame({
        "bucket": ["Personal", "Business", "Pension"],
        "amount": [abs(report["totals"]["personal"]), abs(report["totals"]["business"]), abs(report["totals"]["pension"])],
    })
    fig2 = px.pie(
        split_df, names="bucket", values="amount", title="Personal vs Business vs Pension",
        color="bucket", color_discrete_map=CATEGORY_COLORS,
    )
    st.plotly_chart(fig2, width='stretch')

st.markdown("### What changed this month")
for note in commentary.generate_commentary(conn, month):
    st.write(f"- {note}")
