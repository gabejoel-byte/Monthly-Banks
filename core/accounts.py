"""The bank/credit-card accounts tracked each month, and how to parse each
one's transaction export. Column positions were derived and cross-checked
against Assets/March 2026 Banks.xlsx: reconstructing every NIS/USD category
total from these 11 tabs using the rules below reproduced seed/mar_2026.csv
exactly (see plan). amount_mode meanings:
  debit_credit -> amount = credit_col - debit_col
  type_amount  -> amount = +amount_col if type_col == 'Credit' else -amount_col
  signed_negate -> amount = -amount_col (a single "charge" column; a purchase
                   is an expense)
"""

import sqlite3

from . import db

# (key, display_name, currency, entity, sort_order,
#  amount_mode, date_col, desc_col, debit_col, credit_col, amount_col, type_col, header_rows)
DEFAULT_ACCOUNTS = [
    ("yahav_137501", "Yahav Chevra - 137501", "NIS", "Chevra", 10,
     "debit_credit", 0, 3, 4, 5, None, None, 1),
    ("yahav_136562", "Yahav Private - 136562", "NIS", "Private", 20,
     "debit_credit", 0, 3, 4, 5, None, None, 1),
    ("yahav_136570", "Yahav 136570 - Private/Osek", "NIS", "Private", 30,
     "debit_credit", 0, 3, 4, 5, None, None, 1),
    ("amex_5637", "Amex 5637 -783 - Chevra", "NIS", "Chevra", 40,
     "signed_negate", 0, 1, None, None, 4, None, 1),
    ("yahav_1429", "Yahav 1429 - 791 - Private", "NIS", "Private", 50,
     "signed_negate", 0, 1, None, None, 4, None, 1),
    ("mastercard_6807", "Mastercard 6807 -783 - Chevra", "NIS", "Chevra", 60,
     "signed_negate", 0, 1, None, None, 4, None, 1),
    ("primary_checking_9220", "Primary Checking - 9220", "USD", "USA", 70,
     "type_amount", 2, 1, None, None, 4, 3, 1),
    ("business_basic_3443", "Business Basic Checking - 3443", "USD", "USA Business", 80,
     "debit_credit", 4, 3, 2, 1, None, None, 1),
    ("venture_x_9902", "Venture X - 9902", "USD", "USA Business", 90,
     "debit_credit", 0, 3, 5, 6, None, None, 1),
    ("capital_one_spark_64", "Capital One Spark - 64", "USD", "USA Business", 100,
     "debit_credit", 0, 3, 5, 6, None, None, 1),
    ("amex_1006", "Amex 1006", "USD", "USA Business", 110,
     "signed_negate", 0, 2, None, None, 3, None, 1),
]


def ensure_seeded(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()
    if row["n"] > 0:
        return
    for (key, name, currency, entity, sort_order, amount_mode,
         date_col, desc_col, debit_col, credit_col, amount_col, type_col, header_rows) in DEFAULT_ACCOUNTS:
        account_id = db.add_account(conn, key, name, currency, entity, sort_order)
        db.save_account_layout(
            conn, account_id, amount_mode,
            date_col=date_col, desc_col=desc_col, debit_col=debit_col,
            credit_col=credit_col, amount_col=amount_col, type_col=type_col,
            header_rows=header_rows,
        )
