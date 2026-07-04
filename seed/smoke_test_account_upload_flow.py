"""End-to-end check of the per-account upload pipeline: parse a synthetic
account export -> auto-detect its category column -> categorize each row ->
save transactions -> roll up into `entries`, mirroring what pages/1_Upload.py
does for a real per-account file."""

import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import account_parser, accounts, categorize, db, parser  # noqa: E402

# date, value_date, ref, description, debit, credit, balance -- same shape as the
# real Yahav bank-format tabs, category typed in an extra column further along.
# Category column needs >= MIN_CATEGORY_HITS real matches for auto-detection to kick in.
JUNE_ACCOUNT_CSV = b""",,,,,,,,,,
1/1/2026,1/1/2026,ref1,Salary,0,5000,5000,,,Chevra Income
2/1/2026,2/1/2026,ref2,Groceries run,120,0,4880,,,Groceries
3/1/2026,3/1/2026,ref3,Doctor visit,60,0,4820,,,Health
4/1/2026,4/1/2026,ref4,Phone bill,95,0,4725,,,Telephone Charges
5/1/2026,5/1/2026,ref5,Random shop,40,0,4685,,,
"""


def main():
    conn = db.get_conn()
    db.init_db(conn)
    categorize.ensure_seeded(conn)
    accounts.ensure_seeded(conn)

    acc = db.list_accounts(conn)[0]
    layout = db.get_account_layout(conn, acc["id"])

    df = parser.load_raw_table(BytesIO(JUNE_ACCOUNT_CSV), "june_test_account.csv")
    result = account_parser.parse_account_file(conn, df, layout)
    assert result["status"] == "ok", f"expected ok, got {result}"
    transactions = result["transactions"]
    assert len(transactions) == 5, f"expected 5 transactions, got {len(transactions)}"
    print(f"Parsed {len(transactions)} transaction(s) for {acc['display_name']}")

    rows = []
    for t in transactions:
        match = (
            categorize.match_category(conn, t["category_raw"])
            if t["category_raw"] else {"canonical": None, "method": "unmatched"}
        )
        canonical = match["canonical"] or "Miscellaneous"
        print(f"  {t['description']!r} ({t['category_raw']!r}) -> {canonical!r} via {match['method']}")
        rows.append({
            "txn_date": t["txn_date"], "description": t["description"], "amount": t["amount"],
            "category_raw": t["category_raw"], "category_canonical": canonical,
            "needs_review": 0 if match["method"] == "exact" else 1, "match_method": match["method"],
        })

    # "Telephone Charges" is a true synonym, not a spelling variant -- should need manual
    # review (falls back to Miscellaneous), same as the legacy upload flow's unmatched path.
    phone_row = next(r for r in rows if r["description"] == "Phone bill")
    assert phone_row["match_method"] == "unmatched" and phone_row["category_canonical"] == "Miscellaneous", phone_row

    # Blank category -> also falls back to Miscellaneous, flagged for review.
    blank_row = next(r for r in rows if r["description"] == "Random shop")
    assert blank_row["category_canonical"] == "Miscellaneous" and blank_row["needs_review"] == 1

    db.replace_transactions(conn, acc["id"], "2026-06", rows)
    db.rollup_entries_for_month_currency(conn, "2026-06", acc["currency"])

    saved = db.transactions_for_account_month(conn, acc["id"], "2026-06")
    assert len(saved) == 5, "not all transactions were saved"

    status = db.accounts_status_for_month(conn, "2026-06")
    this_acc_status = next(s for s in status if s["account"]["id"] == acc["id"])
    assert this_acc_status["uploaded"] and this_acc_status["n_transactions"] == 5

    entries = {r["category_canonical"]: r["amount"] for r in db.entries_for_month(conn, "2026-06") if r["bank_currency"] == acc["currency"]}
    assert entries["Chevra Income"] == 5000, entries
    assert entries["Groceries"] == -120, entries
    assert entries["Health"] == -60, entries
    assert entries["Miscellaneous"] == -135, entries  # phone bill (-95) + random shop (-40)

    # Correcting both unmatched rows on "re-upload" should replace, not duplicate, and the
    # rollup should reflect the corrections.
    for r in rows:
        if r["description"] in ("Phone bill", "Random shop"):
            r["category_canonical"] = "Groceries"
            r["needs_review"] = 0
    db.replace_transactions(conn, acc["id"], "2026-06", rows)
    db.rollup_entries_for_month_currency(conn, "2026-06", acc["currency"])
    saved_again = db.transactions_for_account_month(conn, acc["id"], "2026-06")
    assert len(saved_again) == 5, "re-upload should replace, not duplicate"
    entries_after = {r["category_canonical"]: r["amount"] for r in db.entries_for_month(conn, "2026-06") if r["bank_currency"] == acc["currency"]}
    assert entries_after["Groceries"] == -255, entries_after  # -120 - 95 - 40
    assert entries_after["Miscellaneous"] == 0, entries_after

    conn.close()
    print(f"\n{len(saved)} transactions saved for 2026-06 / {acc['display_name']}; rollup + re-upload replace both verified.")
    print("\nACCOUNT UPLOAD FLOW OK")


if __name__ == "__main__":
    main()
