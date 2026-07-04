"""End-to-end check of the parse -> categorize -> learn -> save pipeline using
a synthetic new month, including a deliberately renamed category label to prove
the fuzzy-match + alias-learning path works."""

import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import categorize, db, formats, parser  # noqa: E402

JUNE_CSV = b"""Israel Banks (NIS),June 2026
Arnona,0
Cell Phone,-95
Groceries,-200
Health,-300
Insurance,-400
Kids and School,-500
Mortgage,-9000
Transportation,-150
Chevra Income,40000
,
USA Banks USD,June 2026
Arnona,0
Groceries,-100
Health,-50
Insurance,-60
USA Income,20000
,
Private Gross Income,0
"""


def main():
    conn = db.get_conn()
    db.init_db(conn)
    categorize.ensure_seeded(conn)

    df = parser.load_raw_table(BytesIO(JUNE_CSV), "june_2026_test.csv")
    result = formats.resolve_and_parse(conn, df, "june_2026_test.csv")
    assert result["status"] == "ok", f"expected ok, got {result['status']}"
    print(f"Parsed via layout: {result['profile_label']}, {len(result['entries'])} rows")

    matches = {e["category_raw"]: categorize.match_category(conn, e["category_raw"]) for e in result["entries"]}
    for raw, m in matches.items():
        print(f"  {raw!r} -> {m['canonical']!r} ({m['method']}, confidence={m['confidence']})")

    # Near-miss spelling ("Kids and School" vs "Kids & School") should fuzzy-match automatically.
    kids_match = matches["Kids and School"]
    assert kids_match["method"] == "fuzzy" and kids_match["canonical"] == "Kids & School", (
        f"expected 'Kids and School' to fuzzy-match 'Kids & School', got {kids_match}"
    )

    # A true synonym ("Cell Phone" for "Cellular") is NOT a spelling variant -- the fuzzy
    # matcher correctly leaves it unmatched, same as the Upload page would show it for
    # manual review. Simulate the user picking the right category in that review table.
    cell_match = matches["Cell Phone"]
    assert cell_match["method"] == "unmatched", f"expected 'Cell Phone' to need manual review, got {cell_match}"
    categorize.learn_alias(conn, "Cell Phone", "Cellular")
    matches["Cell Phone"]["canonical"] = "Cellular"

    rows = [
        {"month": "2026-06", "bank_currency": e["bank_currency"], "category_raw": e["category_raw"],
         "category_canonical": matches[e["category_raw"]]["canonical"], "amount": e["amount"]}
        for e in result["entries"]
    ]
    db.upsert_entries(conn, rows)
    db.set_fx_rate(conn, "2026-06", 3.7)

    # Re-upload the *same* file shape again -- this time "Cell Phone" should resolve via
    # the learned alias, not fuzzy matching, proving the learning actually persisted.
    match_again = categorize.match_category(conn, "Cell Phone")
    assert match_again["method"] == "alias", f"expected alias match on second pass, got {match_again}"
    print(f"\nSecond pass: 'Cell Phone' -> {match_again['canonical']!r} via {match_again['method']} (learning confirmed)")

    saved = db.entries_for_month(conn, "2026-06")
    assert len(saved) == len(rows), "not all rows were saved"
    print(f"\n{len(saved)} entries saved for 2026-06. Months now in DB: {db.months_present(conn)}")

    conn.close()
    print("\nUPLOAD FLOW OK")


if __name__ == "__main__":
    main()
