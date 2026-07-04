"""Parses one bank/credit-card account's monthly transaction export into
individual transaction rows, using that account's learned column layout
(core/accounts.py seeds the validated defaults; core/db.py stores overrides).

The category column position is *not* trusted from the stored layout -- it's
been observed to drift by a couple of columns between otherwise-identical
account tabs in the same source workbook. Instead it's detected per-file by
finding the column whose values best match known category names/aliases.
"""

import sqlite3

import pandas as pd

from . import categorize, parser

MIN_CATEGORY_HITS = 3


def _category_lookup(conn: sqlite3.Connection) -> set[str]:
    names = {categorize.normalize(n) for n in categorize.canonical_names(conn)}
    aliases = {r["raw_label"] for r in conn.execute("SELECT raw_label FROM category_aliases")}
    return names | aliases


def detect_category_column(conn: sqlite3.Connection, df: pd.DataFrame, header_rows: int) -> int | None:
    lookup = _category_lookup(conn)
    body = df.iloc[header_rows:]
    best_col, best_hits = None, 0
    for col in body.columns:
        hits = sum(1 for v in body[col] if isinstance(v, str) and categorize.normalize(v) in lookup)
        if hits > best_hits:
            best_col, best_hits = col, hits
    return best_col if best_hits >= MIN_CATEGORY_HITS else None


def _cell(row: pd.Series, col: int | None):
    if col is None or col >= len(row):
        return None
    return row.iloc[col]


def _row_amount(row: pd.Series, layout: sqlite3.Row) -> float | None:
    mode = layout["amount_mode"]
    if mode == "debit_credit":
        debit = parser.to_amount(_cell(row, layout["debit_col"]))
        credit = parser.to_amount(_cell(row, layout["credit_col"]))
        if debit is None and credit is None:
            return None
        return (credit or 0.0) - (debit or 0.0)
    if mode == "signed_negate":
        amt = parser.to_amount(_cell(row, layout["amount_col"]))
        return -amt if amt is not None else None
    if mode == "type_amount":
        amt = parser.to_amount(_cell(row, layout["amount_col"]))
        if amt is None:
            return None
        typ = str(_cell(row, layout["type_col"]) or "").strip().lower()
        return amt if typ == "credit" else -amt
    raise ValueError(f"unknown amount_mode: {mode}")


def _fmt_date(val) -> str | None:
    if val is None:
        return None
    try:
        ts = pd.Timestamp(val)
    except (ValueError, TypeError):
        s = str(val).strip()
        return s or None
    if pd.isna(ts):
        return None
    return ts.strftime("%Y-%m-%d")


def _is_blank(val) -> bool:
    return val is None or (isinstance(val, float) and val != val) or str(val).strip() in ("", "nan", "NaT")


def parse_account_file(conn: sqlite3.Connection, df: pd.DataFrame, layout: sqlite3.Row) -> dict:
    """Returns {"status": "ok", "transactions": [...]} or {"status": "no_category_column"}.
    Each transaction: txn_date, description, amount, category_raw."""
    header_rows = layout["header_rows"]
    cat_col = detect_category_column(conn, df, header_rows)
    if cat_col is None:
        return {"status": "no_category_column"}

    transactions = []
    for _, row in df.iloc[header_rows:].iterrows():
        amount = _row_amount(row, layout)
        if amount is None:
            continue
        date_val = _cell(row, layout["date_col"])
        desc_val = _cell(row, layout["desc_col"])
        if _is_blank(date_val) and _is_blank(desc_val):
            continue  # decorative/blank row, not a real transaction

        category_raw = _cell(row, cat_col)
        transactions.append({
            "txn_date": _fmt_date(date_val),
            "description": "" if _is_blank(desc_val) else str(desc_val).strip(),
            "amount": amount,
            "category_raw": "" if _is_blank(category_raw) else str(category_raw).strip(),
        })
    return {"status": "ok", "transactions": transactions}
