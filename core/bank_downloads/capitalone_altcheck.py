"""
Parser for the other checking-account CSV export shape:
Account Number, Credit, Debit, Description, Posted Date
"""
from datetime import datetime

import pandas as pd

from .common import make_txn

REQUIRED_COLS = {"Account Number", "Credit", "Debit", "Description", "Posted Date"}


def sniff(columns: list[str]) -> bool:
    return REQUIRED_COLS.issubset(set(columns))


def _parse_date(val: str) -> str:
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(val, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return val


def parse(df: pd.DataFrame, source_file: str) -> list[dict]:
    txns = []
    for _, row in df.iterrows():
        account = str(row["Account Number"]).strip()
        source_key = f"checking_{account}"
        account_label = f"Checking …{account}"

        txn_date = _parse_date(str(row["Posted Date"]).strip())
        description = str(row["Description"]).strip()

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
                post_date=None,
                description=description or "(no description)",
                amount=amount,
                direction=direction,
                raw_reference=None,
                source_file=source_file,
            )
        )
    return txns
