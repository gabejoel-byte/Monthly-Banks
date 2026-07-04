import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import categorize, db  # noqa: E402

conn = db.get_conn()
db.init_db(conn)
categorize.ensure_seeded(conn)

months = db.months_present(conn)
print(f"Months on file: {months}\n")

flagged = db.flagged_entries(conn)
print(f"Flagged/uncategorized lines: {len(flagged)}")
for r in flagged:
    print(f"  {r['month']} {r['bank_currency']} {r['category_raw']!r} -> {r['category_canonical']!r} ({r['match_method']})")

all_cats = set(categorize.canonical_names(conn))
print(f"\nCanonical categories: {len(all_cats)}\n")

for month in months:
    currencies = db.currencies_present_for_month(conn, month)
    print(f"{month}: currencies present = {sorted(currencies)}")
    for cur in sorted(currencies):
        present = db.categories_present_for_month(conn, month, cur)
        missing = all_cats - present
        print(f"   {cur}: {len(present)}/{len(all_cats)} categories present" + (f" -- MISSING: {sorted(missing)}" if missing else ""))
    missing_currencies = {"NIS", "USD"} - currencies
    if missing_currencies:
        print(f"   MISSING CURRENCY SECTION(S): {sorted(missing_currencies)}")
