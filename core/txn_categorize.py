"""Description-based categorization for the raw bank-download import path.

Ported from the standalone "Monthly Banks 1" FastAPI app and adapted to the
Streamlit app's schema. Native download files (Capital One / Yahav / Isracard)
carry no category column, so categorization is driven by the transaction
*description* rather than by a workbook category label (which is what
core/categorize.py handles for the "* Banks.xlsx" per-account workbooks).

Priority tiers (lower number wins), stored in the `category_rules` table:
  1  manual      - the user explicitly recategorized this exact merchant
  10 reference   - exact merchant match against the user's own prior
                   categorizations (category_reference.json's transaction_lookup)
  50 learned     - merchant->category learned from Capital One's own `Category`
                   column the first time a merchant appears

Falls back to a small set of Hebrew/English regex SUPPLEMENTARY_RULES for gaps
the reference lookup doesn't cover, then to the Capital One category hint mapped
into the taxonomy, and finally to None (the caller records it as Miscellaneous,
flagged for review). Every category referenced here is one of the app's own
canonical categories - nothing invented.
"""
import json
import re
import sqlite3
from pathlib import Path

_REFERENCE_PATH = Path(__file__).resolve().parent.parent / "category_reference.json"


def _load_reference_lookup() -> dict[str, str]:
    """description (normalized) -> category, from the user's own history.
    category_reference.json is gitignored (real financial data), so a fresh
    clone won't have it -- degrade gracefully to an empty lookup instead of
    crashing on import."""
    try:
        data = json.loads(_REFERENCE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {
        entry["description"].strip().lower(): entry["category"]
        for entry in data.get("transaction_lookup", [])
        if entry.get("description") and entry.get("category")
    }


REFERENCE_LOOKUP: dict[str, str] = _load_reference_lookup()

# Capital One's own categories, mapped into the app taxonomy. Capital One
# accounts are all USD/USA, so entity-specific categories use the USA variant.
CO_CATEGORY_MAP = {
    "airfare": "Personal Travel",
    "dining": "Entertainment",
    "entertainment": "Entertainment",
    "fee/interest charge": "USA Bank Fees",
    "gas/automotive": "Gas",
    "health care": "Health",
    "insurance": "Insurance",
    "internet": "Internet",
    "merchandise": "Miscellaneous",
    "other": "Miscellaneous",
    "other services": "Professional Services",
    "other travel": "Personal Travel",
    "payment/credit": "Credit Card Payments",
    "phone/cable": "Cellular",
    "professional services": "Professional Services",
}

# Regex substring rules (case-insensitive) filling gaps the reference lookup
# doesn't cover - notably the Hebrew bank-checking exports. Only consulted when
# nothing more specific already matched. Genuinely ambiguous patterns (e.g.
# which account is "Chevra" vs "Private") are deliberately left for manual
# review rather than guessed.
SUPPLEMENTARY_RULES: list[tuple[str, str]] = [
    (r"בנק יהב-אשראי|ישראכרט בע\"מ|פרימיום אקספרס", "Credit Card Payments"),
    (r"capital one.*(pmt|payment|pymt)|amex epayment|amex.*pmt", "Credit Card Payments"),
    (r"\bbit\b|zelle|mobile deposit|transfer deposit|transfer withdrawal", "Money Transfer"),
    (r"ביטוח לאומי|בטוח לאומי", "Bituach Leumi Private"),
    (r"עמלות תקופתיות|עמלה מפעולות בערוץ ישיר|דמי ניהול חשבון|קיזוז מטח או שח/עמלות|^ריבית$", "Private Bank Fees"),
    (r"מע\"מ", "Private VAT"),
    (r"ת\"ת |תלמוד תורה", "Kids & School"),
    (r"שירותי בריאות", "Health"),
    (r"למשכנתאות|\bmortgage\b", "Mortgage"),
    (r"הפניקס|מנורה", "Insurance"),
    (r"קצבת ילדים", "Private Israel Income"),
    # --- Israeli merchant / utility patterns added during the merge to cut down
    #     manual review of Hebrew descriptions. Salary (משכורת) and pension are
    #     deliberately excluded: which entity (Chevra vs Private) they belong to
    #     depends on the account, not the description, so they stay manual.
    (r"הפקדה לפקדון|משיכה מפקדון|פקדון מתחדש|העברה עצמית", "Money Transfer"),
    (r"ארנונה|עיריית", "Arnona"),
    (r"חברת החשמל|חשמל למגורים", "Other Utilities"),
    (r"תאגיד המים|מי שמש|מיתב|הגיחון|מים וביוב", "Water Bill"),
    (r"סלקום|פרטנר תקשורת|פלאפון|הוט מובייל|גולן טלקום|רמי לוי תקשורת", "Cellular"),
    (r"שופרסל|רמי לוי|יינות ביתן|אושר עד|טיב טעם|ויקטורי|יוחננוף|מחסני השוק", "Groceries"),
    (r"סונול|דור אלון|תחנת דלק|פז יבוא", "Gas"),
]


def _valid_categories(conn: sqlite3.Connection) -> set[str]:
    return {r["canonical_name"] for r in conn.execute("SELECT canonical_name FROM categories")}


def seed_reference_rules(conn: sqlite3.Connection) -> int:
    """One-time seed of the reference lookup into `category_rules` at priority 10.
    Only seeds patterns whose category is a real canonical category, and never
    overwrites an existing (possibly user-edited) rule. Returns rows inserted."""
    valid = _valid_categories(conn)
    existing = {r["pattern"] for r in conn.execute("SELECT pattern FROM category_rules")}
    to_insert = [
        (pattern, category, 10)
        for pattern, category in REFERENCE_LOOKUP.items()
        if pattern not in existing and category in valid
    ]
    if to_insert:
        conn.executemany(
            "INSERT OR IGNORE INTO category_rules (pattern, category, priority) VALUES (?, ?, ?)",
            to_insert,
        )
        conn.commit()
    return len(to_insert)


def _compile(pattern: str) -> re.Pattern:
    # Rule patterns are literal merchant text (never hand-written regex), so
    # always escape -- a raw "*" or "." in a description matches literally.
    return re.compile(re.escape(pattern), re.IGNORECASE)


class Categorizer:
    """Loads the rule table once, then categorizes many descriptions in-memory
    (the import preview categorizes ~1k rows, so per-row DB queries are avoided).
    """

    def __init__(self, conn: sqlite3.Connection):
        rules = list(conn.execute(
            "SELECT pattern, category, priority FROM category_rules ORDER BY priority ASC, id ASC"
        ).fetchall())
        # priority<=1 manual and priority 10 reference are matched as substrings;
        # reference is the bulk, so also index it for a fast exact lookup first.
        self._exact: dict[str, str] = {}
        self._substr: list[tuple[str, str, int]] = []
        for r in rules:
            self._exact.setdefault(r["pattern"], r["category"])
            self._substr.append((r["pattern"], r["category"], r["priority"]))
        self._supp = [(re.compile(p, re.IGNORECASE), c) for p, c in SUPPLEMENTARY_RULES]

    def categorize(self, description: str, category_hint: str | None = None) -> dict:
        """Returns {"canonical": str|None, "method": str}. `canonical` is None
        only when nothing matched (caller falls back to Miscellaneous)."""
        norm = (description or "").strip().lower()
        if not norm:
            return {"canonical": None, "method": "unmatched"}

        # tier 1-2: exact match against manual/reference rules (fast path).
        if norm in self._exact:
            # find the winning (lowest-priority) rule for this exact pattern
            method = "reference"
            for pattern, category, priority in self._substr:
                if pattern == norm:
                    method = "manual" if priority <= 1 else ("reference" if priority <= 10 else "learned")
                    return {"canonical": category, "method": method}
            return {"canonical": self._exact[norm], "method": method}

        # substring match for manual/reference/learned rules that appear inside
        # a longer description (mirrors the original engine's behavior).
        for pattern, category, priority in self._substr:
            if pattern and pattern in norm:
                method = "manual" if priority <= 1 else ("reference" if priority <= 10 else "learned")
                return {"canonical": category, "method": method}

        # tier 3: supplementary regex rules for gaps the reference doesn't cover.
        for rx, category in self._supp:
            if rx.search(norm):
                return {"canonical": category, "method": "supplementary"}

        # tier 4: Capital One's own category hint, mapped into the taxonomy.
        if category_hint:
            mapped = CO_CATEGORY_MAP.get(category_hint.strip().lower())
            if mapped:
                return {"canonical": mapped, "method": "hint"}

        return {"canonical": None, "method": "unmatched"}


def learn_merchant_rule(conn: sqlite3.Connection, description: str, category: str, priority: int = 50) -> None:
    """Remember a merchant->category mapping for future imports. priority 50 for
    a hint-learned rule; pass 1 for a user's explicit manual override."""
    pattern = (description or "").strip().lower()
    if not pattern or category not in _valid_categories(conn):
        return
    if priority <= 1:
        # a manual override always wins and replaces any weaker rule
        db_upsert = "INSERT INTO category_rules (pattern, category, priority) VALUES (?, ?, 1) " \
                    "ON CONFLICT(pattern) DO UPDATE SET category = excluded.category, priority = 1"
        conn.execute(db_upsert, (pattern, category))
    else:
        conn.execute(
            "INSERT OR IGNORE INTO category_rules (pattern, category, priority) VALUES (?, ?, ?)",
            (pattern, category, priority),
        )
    conn.commit()
