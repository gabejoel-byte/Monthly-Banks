"""One-time script: loads the Jan-May 2026 historical monthly files into the
database, and derives each month's FX rate from the wide multi-month sheet.
Run with:  python seed/import_history.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import calculations, categorize, db, parser  # noqa: E402

SEED_DIR = Path(__file__).resolve().parent

MONTH_FILES = {
    "2026-01": "jan_2026.csv",
    "2026-02": "feb_2026.csv",
    "2026-03": "mar_2026.csv",
    "2026-04": "apr_2026.csv",
    "2026-05": "may_2026.csv",
}


def import_month(conn, month: str, filename: str) -> int:
    path = SEED_DIR / filename
    df = parser.load_raw_table(str(path), filename)
    raw_entries = parser.parse_single_month(df)

    rows = []
    for e in raw_entries:
        match = categorize.match_category(conn, e["category_raw"])
        canonical = match["canonical"] or e["category_raw"]
        if match["method"] == "unmatched":
            print(f"  ! unmatched category in {filename}: {e['category_raw']!r} -- adding as-is")
            categorize.add_category(conn, canonical, "personal")
        rows.append({
            "month": month,
            "bank_currency": e["bank_currency"],
            "category_raw": e["category_raw"],
            "category_canonical": canonical,
            "amount": e["amount"],
        })
    db.upsert_entries(conn, rows)
    return len(rows)


def import_fx_rates(conn) -> dict[str, float]:
    path = SEED_DIR / "multi_month_seed.csv"
    df = parser.load_raw_table(str(path), "multi_month_seed.csv")
    result = parser.parse_wide_multi_month(df)
    for month, rate in result["fx_rates"].items():
        db.set_fx_rate(conn, month, rate)
    return result["fx_rates"]


def main():
    conn = db.get_conn()
    db.init_db(conn)
    categorize.ensure_seeded(conn)

    print("Deriving FX rates from multi-month sheet...")
    rates = import_fx_rates(conn)
    for month, rate in sorted(rates.items()):
        print(f"  {month}: {rate:.4f}")

    for month, filename in MONTH_FILES.items():
        n = import_month(conn, month, filename)
        print(f"Imported {n} entries for {month} from {filename}")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
