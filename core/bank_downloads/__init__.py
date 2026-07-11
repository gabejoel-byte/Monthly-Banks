"""Format-sniffing parsers for *raw native bank-download files* (Capital One
CSV exports, Israeli Yahav checking .xls, Isracard credit-card .xlsx).

Ported from the standalone FastAPI "Monthly Banks 1" app during the merge. These
differ from core/account_parser.py: that one parses the pre-formatted monthly
"* Banks.xlsx" workbooks (which already carry a category column) using a
per-account learned column layout; the parsers here read the banks' own native
export files, which have no category column, so categorization happens
afterwards from the transaction description (see core/txn_categorize.py).

`detect_and_parse(filename, content)` sniffs the file and returns a list of
transaction dicts (see common.make_txn for the shape). Each dict's `amount` is a
positive magnitude paired with a `direction` of "debit"/"credit"; the ingest
adapter (core/bank_ingest.py) converts that to the app's signed convention.
"""
import io

import pandas as pd

from . import capitalone_altcheck, capitalone_checking, capitalone_creditcard, isracard_amex, yahav_checking


class UnrecognizedFileError(ValueError):
    pass


def detect_and_parse(filename: str, content: bytes) -> list[dict]:
    lower = filename.lower()

    if lower.endswith(".xlsx"):
        df = pd.read_excel(io.BytesIO(content), header=None, engine="openpyxl")
        if isracard_amex.sniff(df):
            return isracard_amex.parse(df, filename)
        raise UnrecognizedFileError(f"Unrecognized xlsx layout in {filename}")

    if lower.endswith(".xls"):
        df = pd.read_excel(io.BytesIO(content), header=None, engine="xlrd")
        if yahav_checking.sniff(df):
            return yahav_checking.parse(df, filename)
        raise UnrecognizedFileError(f"Unrecognized xls layout in {filename}")

    if lower.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(content), encoding="utf-8-sig")
        columns = list(df.columns)
        if capitalone_checking.sniff(columns):
            return capitalone_checking.parse(df, filename)
        if capitalone_creditcard.sniff(columns):
            return capitalone_creditcard.parse(df, filename)
        if capitalone_altcheck.sniff(columns):
            return capitalone_altcheck.parse(df, filename)
        raise UnrecognizedFileError(f"Unrecognized csv columns in {filename}: {columns}")

    raise UnrecognizedFileError(f"Unsupported file type: {filename}")
