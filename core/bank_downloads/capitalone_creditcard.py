"""
Parser for Capital One credit-card CSV exports:
Transaction Date, Posted Date, Card No., Description, Category, Debit, Credit

The `Category` column is Capital One's own categorization - we pass it
through as a `category_hint` so the categorization engine can learn
merchant -> category mappings from it (and apply that learning to future
transactions from any source, not just this card).
"""
from datetime import datetime

import pandas as pd

from .common import make_txn

REQUIRED_COLS = {"Card No.", "Category", "Debit", "Credit"}


def sniff(columns: list[str]) -> bool:
    return REQUIRED_COLS.issubset(set(columns))


def _parse_date(val: str) -> str:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(val, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return val


def parse(df: pd.DataFrame, source_file: str) -> list[dict]:
    txns = []
    for _, row in df.iterrows():
        card_no = str(row["Card No."]).strip()
        source_key = f"creditcard_{card_no}"
        account_label = f"Capital One Card …{card_no}"

        txn_date = _parse_date(str(row["Transaction Date"]).strip())
        post_date = _parse_date(str(row["Posted Date"]).strip()) if not pd.isna(row.get("Posted Date")) else None
        description = str(row["Description"]).strip()
        category_hint = str(row["Category"]).strip() if not pd.isna(row.get("Category")) else None

        debit = row.get("Debit")
        credit = row.get("Credit")
        debit = 0.0 if pd.isna(debit) or debit == "" else float(debit)
        credit = 0.0 if pd.isna(credit) or credit == "" else float(credit)

        if debit:
            amount, direction = debit, "debit"
        elif credit:
            amount, direction = credit, "credit"
        else:
            continue

        txns.append(
            make_txn(
                source_key=source_key,
                account_label=account_label,
                currency="USD",
                txn_date=txn_date,
                post_date=post_date,
                description=description or "(no description)",
                amount=amount,
                direction=direction,
                raw_reference=None,
                source_file=source_file,
                category_hint=category_hint,
            )
        )
    return txns
