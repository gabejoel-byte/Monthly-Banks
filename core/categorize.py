import re
import sqlite3

from rapidfuzz import fuzz, process

# The 45 canonical categories, classified into P&L groups. Verified against
# 3+ months of the user's historical spreadsheets (see plan doc) rather than guessed:
#   income    -> feeds the "Income" total
#   pension   -> feeds "KH/Pension"
#   business  -> feeds "Business Expenses" (Private/Chevra business-side costs)
#   personal  -> feeds "Personal Expenses" (household spend)
#   charity   -> ad-hoc charity payments, excluded from Personal/Business totals
#                (kept separate from the automatic 20% Tzedaka calculation)
#   excluded  -> transfers/settlements, excluded from all P&L totals entirely
DEFAULT_CATEGORIES: dict[str, str] = {
    "Chevra Income": "income",
    "Private Israel Income": "income",
    "USA Income": "income",
    "Pension KH Chevra": "pension",
    "Pension KH Private": "pension",
    "Bituach Leumi Chevra": "business",
    "Bituach Leumi Private": "business",
    "Chevra Bank Fees": "business",
    "Chevra Expenses": "business",
    "Chevra Taxes": "business",
    "Chevra VAT": "business",
    "Chevra Investments": "business",
    "Private Bank Fees": "business",
    "Private Business Expenses": "business",
    "Private Investments": "business",
    "Private Taxes": "business",
    "Private VAT": "business",
    "Professional Services": "business",
    "USA Bank Fees": "business",
    "USA Business Expense": "business",
    "USA Taxes": "business",
    "Money Transfer": "excluded",
    "Credit Card Payments": "excluded",
    "Charity Community": "charity",
    "Charity Poor": "charity",
    "Charity Torah": "charity",
    "Arnona": "personal",
    "Cellular": "personal",
    "Clothing": "personal",
    "Entertainment": "personal",
    "Gas": "personal",
    "Gifts": "personal",
    "Groceries": "personal",
    "Health": "personal",
    "Hobbies": "personal",
    "Home Improvement": "personal",
    "House Gas Bill": "personal",
    "Insurance": "personal",
    "Internet": "personal",
    "Kids & School": "personal",
    "Miscellaneous": "personal",
    "Mortgage": "personal",
    "Other Utilities": "personal",
    "Personal Travel": "personal",
    "Transportation": "personal",
    "Water Bill": "personal",
}

FUZZY_THRESHOLD = 85


def normalize(label: str) -> str:
    return re.sub(r"\s+", " ", label.strip().lower())


def ensure_seeded(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT COUNT(*) AS n FROM categories").fetchone()
    if row["n"] > 0:
        return
    conn.executemany(
        "INSERT INTO categories (canonical_name, group_name) VALUES (?, ?)",
        list(DEFAULT_CATEGORIES.items()),
    )
    conn.commit()


def canonical_names(conn: sqlite3.Connection) -> list[str]:
    return [r["canonical_name"] for r in conn.execute("SELECT canonical_name FROM categories")]


def category_group(conn: sqlite3.Connection, canonical_name: str) -> str | None:
    row = conn.execute(
        "SELECT group_name FROM categories WHERE canonical_name = ?", (canonical_name,)
    ).fetchone()
    return row["group_name"] if row else None


def match_category(conn: sqlite3.Connection, raw_label: str) -> dict:
    """Resolve a raw category label from an upload to a canonical category.

    Returns {"canonical": str|None, "confidence": int, "method": "exact"|"alias"|"fuzzy"|"unmatched"}.
    """
    norm = normalize(raw_label)
    names = canonical_names(conn)
    name_by_norm = {normalize(n): n for n in names}

    if norm in name_by_norm:
        return {"canonical": name_by_norm[norm], "confidence": 100, "method": "exact"}

    alias_row = conn.execute(
        "SELECT canonical_name FROM category_aliases WHERE raw_label = ?", (norm,)
    ).fetchone()
    if alias_row:
        return {"canonical": alias_row["canonical_name"], "confidence": 100, "method": "alias"}

    alias_rows = conn.execute("SELECT raw_label, canonical_name FROM category_aliases").fetchall()
    candidates = {**name_by_norm, **{r["raw_label"]: r["canonical_name"] for r in alias_rows}}
    if candidates:
        best = process.extractOne(norm, candidates.keys(), scorer=fuzz.WRatio)
        if best and best[1] >= FUZZY_THRESHOLD:
            matched_key = best[0]
            return {
                "canonical": candidates[matched_key],
                "confidence": round(best[1]),
                "method": "fuzzy",
            }

    return {"canonical": None, "confidence": 0, "method": "unmatched"}


def learn_alias(conn: sqlite3.Connection, raw_label: str, canonical_name: str) -> None:
    norm = normalize(raw_label)
    if not norm or norm == normalize(canonical_name):
        return
    conn.execute(
        """
        INSERT INTO category_aliases (raw_label, canonical_name) VALUES (?, ?)
        ON CONFLICT(raw_label) DO UPDATE SET canonical_name = excluded.canonical_name
        """,
        (norm, canonical_name),
    )
    conn.commit()


def add_category(conn: sqlite3.Connection, canonical_name: str, group_name: str) -> None:
    conn.execute(
        """
        INSERT INTO categories (canonical_name, group_name) VALUES (?, ?)
        ON CONFLICT(canonical_name) DO UPDATE SET group_name = excluded.group_name
        """,
        (canonical_name, group_name),
    )
    conn.commit()
