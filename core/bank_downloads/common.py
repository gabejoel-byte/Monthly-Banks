import hashlib
import re

RTL_MARKS = re.compile("[‎‏‪-‮]")


def clean_text(val) -> str:
    if val is None:
        return ""
    s = str(val)
    s = RTL_MARKS.sub("", s)
    return s.strip()


def make_txn(
    *,
    source_key: str,
    account_label: str,
    currency: str,
    txn_date: str,
    post_date: str | None,
    description: str,
    amount: float,
    direction: str,
    raw_reference: str | None,
    source_file: str,
    category_hint: str | None = None,
) -> dict:
    amount = round(abs(float(amount)), 2)
    h = hashlib.sha256(
        f"{source_key}|{account_label}|{txn_date}|{description}|{amount}|{direction}".encode("utf-8")
    ).hexdigest()
    return {
        "dedup_hash": h,
        "source_key": source_key,
        "account_label": account_label,
        "currency": currency,
        "txn_date": txn_date,
        "post_date": post_date,
        "description": description,
        "amount": amount,
        "direction": direction,
        "raw_reference": raw_reference,
        "source_file": source_file,
        "category_hint": category_hint,
    }
