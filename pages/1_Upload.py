import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from bootstrap import get_ready_conn
from core import account_parser, bank_ingest, categorize, db, formats, parser, txn_categorize
from ui_helpers import apply_mobile_css, render_category_table, require_password

st.set_page_config(page_title="Upload", page_icon="\U0001F4E4", layout="wide")
apply_mobile_css()
require_password()
conn = get_ready_conn()


def _next_month(month: str) -> str:
    year, mon = map(int, month.split("-"))
    mon += 1
    if mon > 12:
        mon = 1
        year += 1
    return f"{year:04d}-{mon:02d}"


st.title("Monthly Upload Checklist")
st.caption(
    "Pick a month, then upload each account's export below. An account only counts as "
    "uploaded once its file has been parsed and saved here."
)

default_month = date.today().strftime("%Y-%m")
month = st.text_input("Month (YYYY-MM)", value=default_month, key="upload_month")

status = db.accounts_status_for_month(conn, month)
n_uploaded = sum(1 for s in status if s["uploaded"])
n_total = len(status)

if n_total == 0:
    st.info("No accounts configured yet.")
    st.stop()

if n_uploaded == n_total:
    st.success(f"All {n_total} accounts uploaded for {month}. ✅")
else:
    st.warning(f"{n_uploaded} of {n_total} accounts uploaded for {month} — {n_total - n_uploaded} still needed.")
st.progress(n_uploaded / n_total)

# ---------------------------------------------------------------------------
# Exchange rate + running NIS/USD/combined totals for this month
# ---------------------------------------------------------------------------
current_rate = db.get_fx_rate(conn, month) or 3.7

nis_col, usd_col, combined_col, rate_col = st.columns([1, 1, 1, 0.7])
with rate_col:
    st.markdown("&nbsp;")  # align the popover button with the metrics beside it
    with st.popover(f"Rate: {current_rate:.4f}"):
        new_rate = st.number_input(
            f"USD → NIS rate for {month}", value=float(current_rate), format="%.4f", key=f"upload_fx_rate::{month}",
        )
        if st.button("Save exchange rate", key="save_upload_fx_rate"):
            db.set_fx_rate(conn, month, new_rate)
            st.success(f"Saved USD → NIS rate {new_rate:.4f} for {month}.")
            st.rerun()

month_entries = db.entries_for_month(conn, month)
nis_total = sum(r["amount"] for r in month_entries if r["bank_currency"] == "NIS")
usd_total = sum(r["amount"] for r in month_entries if r["bank_currency"] == "USD")
combined_total = nis_total + usd_total * current_rate

nis_col.metric("Total so far — NIS accounts", f"₪{nis_total:,.0f}")
usd_col.metric("Total so far — USD accounts", f"${usd_total:,.0f}")
combined_col.metric("Combined (converted to NIS)", f"₪{combined_total:,.0f}")
st.caption(
    "These update as you upload/edit accounts below — the NIS and USD totals are each account's "
    "own currency added up separately, then combined using the rate (tap \"Rate\" to change it). "
    "This reflects only accounts uploaded so far, not the whole month until every account above is checked off."
)


def render_account_upload(acc_row: dict, month: str) -> None:
    account_id = acc_row["id"]
    uploaded = st.file_uploader(
        f"File for {acc_row['display_name']}", type=["csv", "xlsx", "xls"],
        key=f"acc_upload_{account_id}_{month}",
    )
    if uploaded is None:
        return

    state_key = f"acc_parsed::{account_id}::{month}::{uploaded.name}::{uploaded.size}"
    if state_key not in st.session_state:
        df = parser.load_raw_table(uploaded, uploaded.name)
        layout = db.get_account_layout(conn, account_id)
        result = account_parser.parse_account_file(conn, df, layout)
        st.session_state[state_key] = {"df": df, "result": result}

    result = st.session_state[state_key]["result"]

    if result["status"] == "no_category_column":
        st.warning(
            "Couldn't automatically find a column of category names in this file. "
            "Preview of the raw file:"
        )
        st.dataframe(st.session_state[state_key]["df"].head(20), width="stretch")
        return

    transactions = result["transactions"]
    if not transactions:
        st.warning("No transaction rows found in this file.")
        return

    review_rows = []
    original_methods = []
    for t in transactions:
        match = (
            categorize.match_category(conn, t["category_raw"])
            if t["category_raw"] else {"canonical": None, "confidence": 0, "method": "unmatched"}
        )
        original_methods.append(match["method"])
        review_rows.append({
            "date": t["txn_date"], "description": t["description"], "amount": t["amount"],
            "raw category": t["category_raw"], "matched category": match["canonical"],
        })
    review_df = pd.DataFrame(review_rows)

    n_needs_review = sum(1 for m in original_methods if m != "exact")
    st.success(f"Parsed {len(transactions)} transaction(s).")
    if n_needs_review:
        st.info(f"{n_needs_review} row(s) need a category check below — pick one or save as-is (falls back to Miscellaneous, flagged for review).")

    edited = render_category_table(
        review_df, "matched category", categorize.canonical_names(conn),
        key=f"acc_editor::{state_key}",
        disabled=["date", "description", "amount", "raw category"],
        required=False,
    )

    if st.button(f"Save {acc_row['display_name']} for {month}", key=f"acc_save::{state_key}", type="primary"):
        rows = []
        for i, t in enumerate(transactions):
            canonical = edited.loc[i, "matched category"]
            if not canonical or (isinstance(canonical, float) and pd.isna(canonical)):
                canonical = "Miscellaneous"
            needs_review = 1 if original_methods[i] != "exact" else 0
            if canonical != review_rows[i]["matched category"]:
                categorize.learn_alias(conn, t["category_raw"], canonical)
                needs_review = 0
            rows.append({
                "txn_date": t["txn_date"], "description": t["description"], "amount": t["amount"],
                "category_raw": t["category_raw"], "category_canonical": canonical,
                "needs_review": needs_review, "match_method": original_methods[i],
            })
        db.replace_transactions(conn, account_id, month, rows)
        db.rollup_entries_for_month_currency(conn, month, acc_row["currency"])
        st.success(f"Saved {len(rows)} transaction(s) for {acc_row['display_name']} / {month}.")
        del st.session_state[state_key]
        st.rerun()


def render_native_import(conn) -> None:
    """Auto-detecting import path for the banks' own native download files
    (Capital One CSV, Bank Yahav .xls, Isracard/Amex .xlsx). Unlike the
    per-account workbook path above, one file can span several months and its
    account is detected from the file itself."""
    st.caption(
        "Drop the banks' own export files here — Capital One CSVs, Bank Yahav "
        "עו\"ש .xls, and Isracard / Amex .xlsx. Each file is detected, categorized "
        "from the transaction descriptions, and filed to the right account "
        "automatically. A file can cover several months; every month it spans is "
        "updated. This is the fastest way in — the per-account checklist below is "
        "the alternative for the pre-totaled monthly workbooks."
    )
    uploaded = st.file_uploader(
        "Bank download files (CSV / XLS / XLSX) — you can drop several at once",
        type=["csv", "xlsx", "xls"], accept_multiple_files=True,
        key="native_import_files",
    )
    if not uploaded:
        return

    sig = "::".join(f"{f.name}:{f.size}" for f in uploaded)
    state_key = f"native_preview::{sig}"
    if state_key not in st.session_state:
        files = [(f.name, f.getvalue()) for f in uploaded]
        st.session_state[state_key] = bank_ingest.preview(conn, files)
    pv = st.session_state[state_key]

    for s in pv["file_summaries"]:
        if s["status"] == "ok":
            lo, hi = s["date_range"]
            st.write(f"✅ **{s['filename']}** → {s['account_label']} · {s['count']} txns · {lo} → {hi}")
        elif s["status"] == "empty":
            st.write(f"➖ **{s['filename']}** → recognized but no transaction rows found")
        else:
            st.write(f"⚠️ **{s['filename']}** → {s['status']}: {s.get('detail', '')}")

    if pv["n_transactions"] == 0:
        st.warning("Nothing to import from these files.")
        return

    months = pv["months"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Transactions", pv["n_transactions"])
    c2.metric("Need a category", pv["n_uncategorized"])
    c3.metric("Months covered", f"{months[0]} → {months[-1]}" if months else "—")

    if pv["n_new_accounts"]:
        new_labels = sorted({r["account"] for r in pv["rows"] if r["is_new_account"]})
        st.info(
            f"{pv['n_new_accounts']} new account(s) will be created from these files:\n\n"
            + "\n".join(f"- {lbl}" for lbl in new_labels)
        )
    st.warning(
        "Importing **replaces** each covered account's existing data for every "
        "month these files span, so re-importing is safe and never double-counts. "
        "Any month you've already finalized from the monthly workbooks will be "
        "overwritten with this per-transaction data."
    )

    # Let the user fix the un-categorized rows before import; confident matches
    # import as-is and are still correctable later on the Review page.
    flagged_idx = [i for i, r in enumerate(pv["rows"]) if r["needs_review"]]
    edits: dict[int, str] = {}
    if flagged_idx:
        st.markdown(
            f"**{len(flagged_idx)} transaction(s) couldn't be auto-categorized** — "
            "set a category below (or leave them as Miscellaneous, flagged for review):"
        )
        flagged_df = pd.DataFrame([{
            "date": pv["rows"][i]["date"],
            "account": pv["rows"][i]["account"],
            "description": pv["rows"][i]["description"],
            "amount": pv["rows"][i]["amount"],
            "category": pv["rows"][i]["category"],
        } for i in flagged_idx])
        edited = render_category_table(
            flagged_df, "category", categorize.canonical_names(conn),
            key=f"native_editor::{state_key}",
            disabled=["date", "account", "description", "amount"],
            required=False,
        )
        for pos, i in enumerate(flagged_idx):
            val = edited.loc[pos, "category"]
            if val and not (isinstance(val, float) and pd.isna(val)):
                edits[i] = val

    if st.button("Import all transactions", type="primary", key=f"native_import_btn::{state_key}"):
        rows = [dict(r) for r in pv["rows"]]
        for i, val in edits.items():
            if val != rows[i]["suggested_category"]:
                # user chose a category for an unmatched row -- trust it and
                # remember it for future imports of the same merchant.
                txn_categorize.learn_merchant_rule(conn, rows[i]["description"], val, priority=1)
                rows[i]["needs_review"] = 0
                rows[i]["match_method"] = "manual"
            rows[i]["category"] = val
        summary = bank_ingest.commit(conn, rows)
        st.success(
            f"Imported {summary['n_transactions']} transactions across "
            f"{summary['n_accounts']} account(s), months {summary['months'][0]}–{summary['months'][-1]}. "
            "See the Monthly Dashboard, or the Review page for anything still flagged."
        )
        del st.session_state[state_key]
        st.rerun()


st.markdown("### ⚡ Import raw bank downloads (auto-detect)")
with st.expander("Upload the banks' own CSV / XLS / XLSX export files", expanded=False):
    render_native_import(conn)

st.markdown("---")
st.markdown("### 📋 Per-account monthly checklist")

for currency, label in (("NIS", "Israel / NIS accounts"), ("USD", "USA / USD accounts")):
    st.markdown(f"### {label}")
    for s in status:
        acc = s["account"]
        if acc["currency"] != currency:
            continue
        icon = "✅" if s["uploaded"] else "⬜"
        header = f"{icon} {acc['display_name']}"
        header += f" — {s['n_transactions']} transaction(s)" if s["uploaded"] else " — needed"
        with st.expander(header, expanded=not s["uploaded"]):
            render_account_upload(acc, month)

st.markdown("---")

with st.expander("Advanced: upload one combined category-summary file instead"):
    st.caption(
        "Legacy path: drop in a monthly category-summary CSV/Excel export (one row per "
        "category, already totaled across accounts) instead of uploading per-account files above."
    )
    legacy_uploaded = st.file_uploader("CSV or Excel file", type=["csv", "xlsx", "xls"], key="legacy_upload")

    if legacy_uploaded is not None:
        state_key = f"parsed::{legacy_uploaded.name}::{legacy_uploaded.size}"
        if state_key not in st.session_state:
            df = parser.load_raw_table(legacy_uploaded, legacy_uploaded.name)
            st.session_state[state_key] = {"df": df, "result": formats.resolve_and_parse(conn, df, legacy_uploaded.name)}

        df = st.session_state[state_key]["df"]
        result = st.session_state[state_key]["result"]

        if result["status"] == "needs_mapping":
            st.warning(
                "This file's layout wasn't recognized. Tell us once where the data lives — "
                "I'll remember this exact layout for next time."
            )
            st.dataframe(df.head(20), width='stretch')
            with st.form("mapping_form"):
                ncols = df.shape[1]
                category_col = st.number_input("Column index with category names (0-based)", 0, ncols - 1, 0)
                amount_col = st.number_input("Column index with amounts (0-based)", 0, ncols - 1, 1)
                currency = st.selectbox("Currency for this file", ["NIS", "USD"])
                header_rows = st.number_input("Header rows to skip", 0, 10, 1)
                label = st.text_input("A short label for this source (e.g. bank name)", value=legacy_uploaded.name)
                submitted = st.form_submit_button("Save this layout and parse")
            if submitted:
                formats.save_custom_mapping(conn, result["signature"], label, category_col, amount_col, currency, header_rows)
                new_result = formats.resolve_and_parse(conn, df, legacy_uploaded.name)
                st.session_state[state_key]["result"] = new_result
                st.rerun()

        else:
            entries = result["entries"]
            fx_rates = result.get("fx_rates", {})
            st.success(f"Parsed {len(entries)} category rows using layout: {result['profile_label']}")

            has_month = entries and "month" in entries[0]

            if not has_month:
                latest = db.latest_month(conn)
                legacy_default_month = _next_month(latest) if latest else "2026-01"
                col1, col2 = st.columns(2)
                target_month = col1.text_input("Month for this upload (YYYY-MM)", value=legacy_default_month)
                default_rate = db.get_fx_rate(conn, target_month) or 3.7
                fx_rate = col2.number_input("USD→NIS exchange rate for this month", value=float(default_rate), format="%.4f")
                for e in entries:
                    e["month"] = target_month
                fx_rates = {target_month: fx_rate}

            review_rows = []
            original_methods = []
            for e in entries:
                match = categorize.match_category(conn, e["category_raw"])
                original_methods.append(match["method"])
                review_rows.append({
                    "month": e["month"],
                    "currency": e["bank_currency"],
                    "raw label": e["category_raw"],
                    "amount": e["amount"],
                    "matched category": match["canonical"],
                    "confidence": match["confidence"],
                    "method": match["method"],
                })
            review_df = pd.DataFrame(review_rows)

            n_needs_review = (review_df["method"] != "exact").sum()
            if n_needs_review:
                st.info(
                    f"{n_needs_review} row(s) matched by alias/fuzzy match or need manual review — "
                    "check the 'matched category' column below. Anything left unconfirmed here is still "
                    "saved, but stays flagged on the Review page until you confirm it."
                )

            edited = render_category_table(
                review_df, "matched category", categorize.canonical_names(conn),
                key=f"editor::{state_key}",
                disabled=["month", "currency", "raw label", "amount", "confidence", "method"],
                required=False,
            )

            unresolved = edited["matched category"].isna() | (edited["matched category"] == "")
            if unresolved.any():
                st.warning(
                    f"{int(unresolved.sum())} row(s) have no category picked yet: "
                    f"{', '.join(edited.loc[unresolved, 'raw label'])}. "
                    "Pick one for each before saving (or save anyway and they'll fall back to "
                    "'Miscellaneous', flagged for review)."
                )

            if st.button("Confirm and save this month", type="primary"):
                rows = []
                for i, e in enumerate(entries):
                    canonical = edited.loc[i, "matched category"]
                    if not canonical or (isinstance(canonical, float) and pd.isna(canonical)):
                        canonical = "Miscellaneous"
                    needs_review = 1 if original_methods[i] != "exact" else 0
                    if canonical != review_rows[i]["matched category"]:
                        # user overrode the suggestion (or picked one where none existed) -- trust it
                        categorize.learn_alias(conn, e["category_raw"], canonical)
                        needs_review = 0
                    rows.append({
                        "month": e["month"],
                        "bank_currency": e["bank_currency"],
                        "category_raw": e["category_raw"],
                        "category_canonical": canonical,
                        "amount": e["amount"],
                        "needs_review": needs_review,
                        "match_method": original_methods[i],
                    })
                db.upsert_entries(conn, rows)
                for month_key, rate in fx_rates.items():
                    db.set_fx_rate(conn, month_key, rate)
                flagged = sum(r["needs_review"] for r in rows)
                st.success(f"Saved {len(rows)} entries." + (f" {flagged} flagged for review." if flagged else ""))
                del st.session_state[state_key]
                st.balloons()
