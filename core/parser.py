import re
from datetime import datetime
from io import BytesIO
from typing import IO

import pandas as pd

NIS_SECTION_RE = re.compile(r"israel\s*banks", re.IGNORECASE)
USD_SECTION_RE = re.compile(r"usa\s*banks", re.IGNORECASE)
GLOBAL_SECTION_RE = re.compile(r"global\s*banks", re.IGNORECASE)
DATE_COL_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")


def load_raw_table(source: IO[bytes] | str, filename: str) -> pd.DataFrame:
    """Read an uploaded CSV/XLSX as a raw, headerless grid of strings."""
    is_excel = filename.lower().endswith((".xlsx", ".xls"))
    if is_excel:
        df = pd.read_excel(source, header=None, dtype=str)
    else:
        data = source.read() if hasattr(source, "read") else open(source, "rb").read()
        df = pd.read_csv(BytesIO(data), header=None, dtype=str, keep_default_na=False)
    return df


def to_amount(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        if isinstance(val, float) and val != val:  # NaN != NaN
            return None
        return float(val)
    s = str(val).strip()
    if s == "" or s.lower() == "nan":
        return None
    s = s.replace(",", "").replace("$", "")
    try:
        return float(s)
    except ValueError:
        return None


def _is_blank_row(row: pd.Series) -> bool:
    first = str(row.iloc[0]).strip() if len(row) else ""
    return first == "" or first.lower() == "nan"


def detect_format(df: pd.DataFrame) -> str:
    """Returns 'single_month' or 'wide_multi_month'."""
    header_row = df.iloc[0].astype(str).tolist()
    date_like_cols = [c for c in header_row if DATE_COL_RE.match(c.strip())]
    if len(date_like_cols) >= 2:
        return "wide_multi_month"
    return "single_month"


def parse_single_month(df: pd.DataFrame) -> list[dict]:
    """Category,Value pairs under 'Israel Banks (NIS)' / 'USA Banks USD' section headers.
    Stops each section at the first blank row; ignores the derived-metrics block that follows.
    """
    entries: list[dict] = []
    current_currency: str | None = None
    sections_seen = 0

    for _, row in df.iterrows():
        col0 = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
        col1 = row.iloc[1] if len(row) > 1 else None

        if NIS_SECTION_RE.search(col0):
            current_currency = "NIS"
            sections_seen += 1
            continue
        if USD_SECTION_RE.search(col0):
            current_currency = "USD"
            sections_seen += 1
            continue

        if _is_blank_row(row):
            if sections_seen >= 2:
                break  # end of the USD section -> derived-metrics block follows, stop
            current_currency = None
            continue

        if current_currency is None:
            continue

        amount = to_amount(col1)
        if amount is None:
            continue
        entries.append({"bank_currency": current_currency, "category_raw": col0, "amount": amount})

    return entries


def parse_wide_multi_month(df: pd.DataFrame) -> dict:
    """Wide format: dated columns across, 'Israel Banks NIS' / 'USA Banks USD' / 'Global banks NIS'
    section blocks down. Returns {"entries": [...], "fx_rates": {month: rate}}.
    """
    header = df.iloc[0].astype(str).tolist()
    month_cols: dict[int, str] = {}
    for idx, val in enumerate(header):
        v = val.strip()
        if DATE_COL_RE.match(v):
            dt = datetime.strptime(v, "%m/%d/%Y")
            month_cols[idx] = dt.strftime("%Y-%m")

    sections: dict[str, dict[str, dict[str, float]]] = {"NIS": {}, "USD": {}, "GLOBAL": {}}
    current: str | None = None

    for _, row in df.iloc[1:].iterrows():
        col0 = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""

        if NIS_SECTION_RE.search(col0) and "global" not in col0.lower():
            current = "NIS"
            continue
        if USD_SECTION_RE.search(col0):
            current = "USD"
            continue
        if GLOBAL_SECTION_RE.search(col0):
            current = "GLOBAL"
            continue
        if col0 == "" or col0.lower() == "nan":
            continue
        if current is None:
            continue
        # Stop the GLOBAL section (and thus the whole parse) once we hit the
        # summary rows (Income/Personal Expenses/.../Net) below it.
        if current == "GLOBAL" and col0 in (
            "Income", "Personal Expenses", "Business Expenses", "KH/Pension", "Total", "Net",
        ):
            break

        category = col0
        for idx, month in month_cols.items():
            amount = to_amount(row.iloc[idx]) if idx < len(row) else None
            if amount is None:
                continue
            sections[current].setdefault(category, {})[month] = amount

    entries: list[dict] = []
    for currency, key in (("NIS", "NIS"), ("USD", "USD")):
        for category, by_month in sections[key].items():
            for month, amount in by_month.items():
                entries.append({"month": month, "bank_currency": currency, "category_raw": category, "amount": amount})

    fx_rates = _derive_fx_rates(sections, month_cols.values())

    return {"entries": entries, "fx_rates": fx_rates}


def _derive_fx_rates(sections: dict, months) -> dict[str, float]:
    """Global = NIS + USD * rate. Solve per month using 'USA Income' (NIS side is
    always 0 in the source data, making this the cleanest signal); fall back to
    'Groceries' if that's unavailable for a given month.
    """
    rates: dict[str, float] = {}
    for month in months:
        rate = _solve_rate_for(sections, month, "USA Income")
        if rate is None:
            rate = _solve_rate_for(sections, month, "Groceries")
        if rate is not None:
            rates[month] = rate
    return rates


def _solve_rate_for(sections: dict, month: str, category: str) -> float | None:
    nis = sections["NIS"].get(category, {}).get(month)
    usd = sections["USD"].get(category, {}).get(month)
    glob = sections["GLOBAL"].get(category, {}).get(month)
    if usd in (None, 0) or glob is None:
        return None
    nis = nis or 0.0
    return (glob - nis) / usd
