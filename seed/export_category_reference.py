"""Exports a reference file for building auto-categorization into another
program: the category taxonomy (canonical names + P&L group) plus a
description -> category lookup built from every confirmed real transaction
seen so far. Re-run this periodically (e.g. after uploading new months) to
keep the transaction reference current.
Run with:  python seed/export_category_reference.py
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import categorize, db  # noqa: E402

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "category_reference.json"


def build_transaction_lookup(conn) -> list[dict]:
    """One entry per distinct description seen in a *confirmed* (needs_review=0)
    transaction. `category` is the most common category assigned to it;
    `confidence` is that category's share of all occurrences (1.0 = always
    the same category). `all_categories` lists every category ever seen for
    this description when there's more than one, so an ambiguous description
    (e.g. a payment processor used for several purposes) isn't silently
    treated as a sure match."""
    rows = conn.execute(
        """
        SELECT description, category_canonical
        FROM transactions
        WHERE needs_review = 0 AND description IS NOT NULL AND description != ''
        """
    ).fetchall()

    by_description: dict[str, Counter] = {}
    for r in rows:
        by_description.setdefault(r["description"], Counter())[r["category_canonical"]] += 1

    lookup = []
    for description, counts in sorted(by_description.items()):
        total = sum(counts.values())
        top_category, top_count = counts.most_common(1)[0]
        entry = {
            "description": description,
            "category": top_category,
            "confidence": round(top_count / total, 3),
            "times_seen": total,
        }
        if len(counts) > 1:
            entry["all_categories"] = [
                {"category": cat, "times_seen": n} for cat, n in counts.most_common()
            ]
        lookup.append(entry)
    return lookup


def main():
    conn = db.get_conn()
    db.init_db(conn)
    categorize.ensure_seeded(conn)

    rows = conn.execute(
        "SELECT canonical_name, group_name FROM categories ORDER BY group_name, canonical_name"
    ).fetchall()
    categories = [{"name": r["canonical_name"], "group": r["group_name"]} for r in rows]

    transaction_lookup = build_transaction_lookup(conn)
    ambiguous = sum(1 for e in transaction_lookup if "all_categories" in e)

    data = {"categories": categories, "transaction_lookup": transaction_lookup}
    OUTPUT_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    conn.close()
    print(f"Wrote {len(categories)} categories and {len(transaction_lookup)} description->category "
          f"entries ({ambiguous} ambiguous) to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
