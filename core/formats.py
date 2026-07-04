"""Learns the *shape* of each uploaded file (which columns hold what, single- vs
dual-currency, how many header rows to skip) so that repeat uploads from the same
source (e.g. a specific bank's export) are recognized and parsed automatically
after the first time, without re-asking the user.
"""

import hashlib

import pandas as pd

from . import db, parser

MIN_ENTRIES_FOR_CONFIDENT_PARSE = 8


def compute_signature(df: pd.DataFrame) -> str:
    ncols = df.shape[1]
    col0_tokens = [
        str(v).strip().lower()
        for v in df.iloc[:15, 0].tolist()
        if str(v).strip() not in ("", "nan")
    ]
    basis = f"{ncols}|" + "|".join(col0_tokens)
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def resolve_and_parse(conn, df: pd.DataFrame, filename: str) -> dict:
    """Returns one of:
    - {"status": "ok", "entries": [...], "fx_rates": {...}, "signature": str, "profile_label": str}
    - {"status": "needs_mapping", "signature": str, "preview": df}
    """
    signature = compute_signature(df)
    profile = db.get_format_profile(conn, signature)

    if profile is not None:
        if profile["kind"] == "builtin_wide_multi_month":
            result = parser.parse_wide_multi_month(df)
            entries, fx_rates = result["entries"], result["fx_rates"]
        elif profile["kind"] == "builtin_single_month":
            entries, fx_rates = parser.parse_single_month(df), {}
        else:  # custom_flat
            entries = _parse_custom_flat(
                df, profile["category_col"], profile["amount_col"], profile["currency"], profile["header_rows"]
            )
            fx_rates = {}
        db.save_format_profile(
            conn, signature, profile["label"], profile["kind"],
            profile["category_col"], profile["amount_col"], profile["currency"], profile["header_rows"],
        )
        return {
            "status": "ok", "entries": entries, "fx_rates": fx_rates,
            "signature": signature, "profile_label": profile["label"],
        }

    # No known profile for this file shape yet -- try the two built-in layouts.
    fmt = parser.detect_format(df)
    if fmt == "wide_multi_month":
        result = parser.parse_wide_multi_month(df)
        if len(result["entries"]) >= MIN_ENTRIES_FOR_CONFIDENT_PARSE:
            db.save_format_profile(conn, signature, f"{filename} (multi-month)", "builtin_wide_multi_month")
            return {
                "status": "ok", "entries": result["entries"], "fx_rates": result["fx_rates"],
                "signature": signature, "profile_label": filename,
            }
    else:
        entries = parser.parse_single_month(df)
        if len(entries) >= MIN_ENTRIES_FOR_CONFIDENT_PARSE:
            db.save_format_profile(conn, signature, f"{filename} (monthly summary)", "builtin_single_month")
            return {
                "status": "ok", "entries": entries, "fx_rates": {},
                "signature": signature, "profile_label": filename,
            }

    return {"status": "needs_mapping", "signature": signature, "preview": df}


def save_custom_mapping(
    conn, signature: str, filename: str, category_col: int, amount_col: int, currency: str, header_rows: int
) -> None:
    db.save_format_profile(
        conn, signature, f"{filename} (custom)", "custom_flat", category_col, amount_col, currency, header_rows
    )


def _parse_custom_flat(
    df: pd.DataFrame, category_col: int, amount_col: int, currency: str, header_rows: int
) -> list[dict]:
    entries = []
    for _, row in df.iloc[header_rows:].iterrows():
        if category_col >= len(row) or amount_col >= len(row):
            continue
        cat = str(row.iloc[category_col]).strip()
        if cat == "" or cat.lower() == "nan":
            continue
        amount = parser.to_amount(row.iloc[amount_col])
        if amount is None:
            continue
        entries.append({"bank_currency": currency, "category_raw": cat, "amount": amount})
    return entries
