"""
Generic parser for Israeli credit-card statement exports (Isracard-issued
Mastercard/Amex/Visa "פירוט עסקאות" xlsx layout). Works for any card in this
same layout because the card number, currency and transaction rows are all
read dynamically from the file rather than hardcoded per card.
"""
import re
from datetime import datetime

import pandas as pd

from .common import clean_text, make_txn

HEADER_MARKER = "תאריך רכישה"
CARD_LABEL_RE = re.compile(r"-\s*(\d{3,6})\s*$")


def sniff(df: pd.DataFrame) -> bool:
    for row in df.head(20).itertuples(index=False):
        if clean_text(row[0]) == HEADER_MARKER:
            return True
    return False


def _parse_date(val) -> str | None:
    if pd.isna(val):
        return None
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    s = clean_text(val)
    for fmt in ("%d.%m.%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse(df: pd.DataFrame, source_file: str) -> list[dict]:
    header_row_idx = None
    for i, row in df.iterrows():
        if clean_text(row[0]) == HEADER_MARKER:
            header_row_idx = i
            break
    if header_row_idx is None:
        return []

    card_label = "Unknown Card"
    card_number = "unknown"
    for i in range(header_row_idx):
        text = clean_text(df.iat[i, 0])
        m = CARD_LABEL_RE.search(text)
        if m:
            card_number = m.group(1)
            card_label = text[: m.start()].strip(" -")
            break

    source_key = f"creditcard_{card_number}"
    account_label = f"{card_label} …{card_number}"

    txns = []
    for i in range(header_row_idx + 1, len(df)):
        date_val = df.iat[i, 0]
        txn_date = _parse_date(date_val)
        if txn_date is None:
            break  # reached the totals/footer section

        merchant = clean_text(df.iat[i, 1])
        charge_amount = df.iat[i, 4]
        charge_currency = clean_text(df.iat[i, 5])
        voucher = clean_text(df.iat[i, 6]) if not pd.isna(df.iat[i, 6]) else None

        if pd.isna(charge_amount):
            continue
        amount = float(charge_amount)
        direction = "credit" if amount < 0 else "debit"
        currency = "USD" if charge_currency == "$" else "ILS"

        txns.append(
            make_txn(
                source_key=source_key,
                account_label=account_label,
                currency=currency,
                txn_date=txn_date,
                post_date=None,
                description=merchant or "(no description)",
                amount=amount,
                direction=direction,
                raw_reference=voucher,
                source_file=source_file,
            )
        )
    return txns
