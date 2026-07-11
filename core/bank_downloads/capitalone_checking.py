"""
Parser for the Capital One "Primary Checking Account" CSV export:
Account Number, Transaction Description, Transaction Date, Transaction Type, Transaction Amount, Balance
"""
from datetime import datetime

import pandas as pd

from .common import make_txn

REQUIRED_COLS = {"Transaction Description", "Transaction Type", "Transaction Amount", "Balance"}


def sniff(columns: list[str]) -> bool:
    return REQUIRED_COLS.issubset(set(columns))


def _parse_date(val: str) -> str:
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
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
        account_label = f"Capital One Checking …{account}"

        txn_date = _parse_date(str(row["Transaction Date"]).strip())
        description = str(row["Transaction Description"]).strip()
        amount = float(row["Transaction Amount"])
        direction = "debit" if str(row["Transaction Type"]).strip().lower() == "debit" else "credit"

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
