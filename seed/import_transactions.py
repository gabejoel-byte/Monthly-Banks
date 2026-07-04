"""One-time backfill: parses the real Assets/*.xlsx workbooks (Jan-May 2026)
into accounts/transactions, then rolls them up into `entries`. Also verifies
the rollup reproduces the already-known-good values previously imported from
the category-summary CSVs (seed/import_history.py), catching any per-account
column drift between months before the new upload flow is trusted.
Run with:  python seed/import_transactions.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from core import account_parser, accounts, categorize, db  # noqa: E402

ASSETS_DIR = Path(__file__).resolve().parent.parent / "Assets"

MONTH_FILES = {
    "2026-01": "January 2026 Banks.xlsx",
    "2026-02": "February 2026 Banks.xlsx",
    "2026-03": "March 2026 Banks.xlsx",
    "2026-04": "April 2026 Banks.xlsx",
    "2026-05": "May 2026 Banks.xlsx",
}

# account key -> substring identifying its tab in these historical workbooks
# (tab names drift slightly month to month, e.g. "Yahav Private" vs "Yahav Personal")
ACCOUNT_MATCH_NEEDLE = {
    "yahav_137501": "137501",
    "yahav_136562": "136562",
    "yahav_136570": "136570",
    "amex_5637": "5637",
    "yahav_1429": "1429",
    "mastercard_6807": "6807",
    "primary_checking_9220": "9220",
    "business_basic_3443": "3443",
    "venture_x_9902": "9902",
    "capital_one_spark_64": "Spark",
    "amex_1006": "Amex 1006",
}


def find_sheet(xls: pd.ExcelFile, needle: str) -> str | None:
    for name in xls.sheet_names:
        if needle.lower() in name.lower():
            return name
    return None


def import_month(conn, month: str, filename: str) -> None:
    path = ASSETS_DIR / filename
    xls = pd.ExcelFile(path)
    for acc in db.list_accounts(conn):
        needle = ACCOUNT_MATCH_NEEDLE[acc["key"]]
        sheet_name = find_sheet(xls, needle)
        if sheet_name is None:
            print(f"  ! no sheet found for {acc['display_name']} in {filename}")
            continue

        df = pd.read_excel(xls, sheet_name=sheet_name, header=None, dtype=str)
        layout = db.get_account_layout(conn, acc["id"])
        result = account_parser.parse_account_file(conn, df, layout)
        if result["status"] != "ok":
            print(f"  ! could not parse {acc['display_name']} / {month}: {result['status']}")
            continue

        rows = []
        for t in result["transactions"]:
            match = categorize.match_category(conn, t["category_raw"]) if t["category_raw"] else {
                "canonical": None, "method": "unmatched",
            }
            canonical = match["canonical"] or "Miscellaneous"
            rows.append({
                "txn_date": t["txn_date"], "description": t["description"], "amount": t["amount"],
                "category_raw": t["category_raw"], "category_canonical": canonical,
                "needs_review": 0 if match["method"] == "exact" else 1, "match_method": match["method"],
            })
        db.replace_transactions(conn, acc["id"], month, rows)
        print(f"  {acc['display_name']}: {len(rows)} transactions")

    db.rollup_entries_for_month_currency(conn, month, "NIS")
    db.rollup_entries_for_month_currency(conn, month, "USD")


def verify_month(conn, month: str, before: dict[tuple[str, str], float]) -> int:
    mismatches = 0
    for row in db.entries_for_month(conn, month):
        key = (row["bank_currency"], row["category_canonical"])
        old, new = before.get(key, 0.0), row["amount"]
        if abs(old - new) > 1.0:
            print(f"  MISMATCH {month} {key}: was {old:.2f}, now {new:.2f}")
            mismatches += 1
    return mismatches


def main():
    conn = db.get_conn()
    db.init_db(conn)
    categorize.ensure_seeded(conn)
    accounts.ensure_seeded(conn)

    total_mismatches = 0
    for month, filename in MONTH_FILES.items():
        print(f"Importing {month} from {filename}...")
        before = {
            (r["bank_currency"], r["category_canonical"]): r["amount"]
            for r in db.entries_for_month(conn, month)
        }
        import_month(conn, month, filename)
        total_mismatches += verify_month(conn, month, before)

    conn.close()
    if total_mismatches:
        print(f"\n{total_mismatches} mismatch(es) found -- review account layouts above.")
    else:
        print("\nAll months reconciled cleanly against existing entries.")


if __name__ == "__main__":
    main()
