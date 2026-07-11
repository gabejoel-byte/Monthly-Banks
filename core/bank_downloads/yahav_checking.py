"""
Generic parser for Bank Yahav "תנועות בחשבון עו״ש" checking-account xls
exports. Works for any account in this layout because the account number
and transaction rows are read dynamically from the file.
"""
from datetime import datetime

import pandas as pd

from .common import clean_text, make_txn

HEADER_MARKERS = {"אסמכתא", "תיאור פעולה"}


def sniff(df: pd.DataFrame) -> bool:
    for row in df.head(15).itertuples(index=False):
        cells = {clean_text(c) for c in row}
        if HEADER_MARKERS.issubset(cells):
            return True
    return False


def _parse_date(val) -> str | None:
    if pd.isna(val):
        return None
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    s = clean_text(val)
    for fmt in ("%d.%m.%y", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse(df: pd.DataFrame, source_file: str) -> list[dict]:
    header_row_idx = None
    for i, row in df.iterrows():
        cells = {clean_text(c) for c in row}
        if HEADER_MARKERS.issubset(cells):
            header_row_idx = i
            break
    if header_row_idx is None:
        return []

    account_number = "unknown"
    for i in range(header_row_idx):
        if clean_text(df.iat[i, 0]) == "חשבון":
            account_number = clean_text(df.iat[i, 1])
            break

    last_digits = "".join(ch for ch in account_number if ch.isdigit())[-4:] or "unknown"
    source_key = f"checking_{last_digits}"
    account_label = f"Bank Yahav Checking …{last_digits}"

    txns = []
    for i in range(header_row_idx + 1, len(df)):
        date_val = df.iat[i, 0]
        txn_date = _parse_date(date_val)
        if txn_date is None:
            continue

        value_date = _parse_date(df.iat[i, 1])
        reference = clean_text(df.iat[i, 2]) if not pd.isna(df.iat[i, 2]) else None
        description = clean_text(df.iat[i, 3])
        debit = df.iat[i, 4]
        credit = df.iat[i, 5]

        debit = 0.0 if pd.isna(debit) else float(debit)
        credit = 0.0 if pd.isna(credit) else float(credit)

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
                currency="ILS",
                txn_date=txn_date,
                post_date=value_date,
                description=description or "(no description)",
                amount=amount,
                direction=direction,
                raw_reference=reference,
                source_file=source_file,
            )
        )
    return txns
