import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "banks.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    canonical_name TEXT PRIMARY KEY,
    group_name TEXT NOT NULL CHECK(group_name IN ('income','personal','business','pension','excluded','charity')),
    -- cost behavior for the Fixed/Variable/Semivariable expense dashboard:
    -- 'fixed' (same each month), 'variable' (discretionary/usage-driven),
    -- 'semivariable' (a fixed base plus a usage part), or 'none' (not an expense
    -- tracked in that dashboard, e.g. income/transfers).
    expense_type TEXT NOT NULL DEFAULT 'none'
);

CREATE TABLE IF NOT EXISTS category_aliases (
    raw_label TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL REFERENCES categories(canonical_name)
);

CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    month TEXT NOT NULL,
    bank_currency TEXT NOT NULL CHECK(bank_currency IN ('NIS','USD')),
    category_raw TEXT NOT NULL,
    category_canonical TEXT NOT NULL REFERENCES categories(canonical_name),
    amount REAL NOT NULL,
    needs_review INTEGER NOT NULL DEFAULT 0,
    match_method TEXT NOT NULL DEFAULT 'manual',
    UNIQUE(month, bank_currency, category_canonical)
);

CREATE TABLE IF NOT EXISTS fx_rates (
    month TEXT PRIMARY KEY,
    rate REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS format_profiles (
    signature TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('builtin_single_month','builtin_wide_multi_month','custom_flat')),
    category_col INTEGER,
    amount_col INTEGER,
    currency TEXT CHECK(currency IN ('NIS','USD') OR currency IS NULL),
    header_rows INTEGER NOT NULL DEFAULT 0,
    seen_count INTEGER NOT NULL DEFAULT 1,
    last_used TEXT
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    currency TEXT NOT NULL CHECK(currency IN ('NIS','USD')),
    entity TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS account_layouts (
    account_id INTEGER PRIMARY KEY REFERENCES accounts(id),
    date_col INTEGER,
    desc_col INTEGER,
    amount_mode TEXT NOT NULL CHECK(amount_mode IN ('debit_credit','signed_negate','type_amount')),
    debit_col INTEGER,
    credit_col INTEGER,
    amount_col INTEGER,
    type_col INTEGER,
    header_rows INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    month TEXT NOT NULL,
    txn_date TEXT,
    description TEXT,
    amount REAL NOT NULL,
    category_raw TEXT,
    category_canonical TEXT NOT NULL REFERENCES categories(canonical_name),
    needs_review INTEGER NOT NULL DEFAULT 0,
    match_method TEXT NOT NULL DEFAULT 'manual'
);
CREATE INDEX IF NOT EXISTS idx_transactions_account_month ON transactions(account_id, month);

-- Description -> category rules for the raw bank-download import path
-- (core/txn_categorize.py). Native download files carry no category column, so
-- categorization is driven by the transaction description instead of a workbook
-- category label. priority: 1 = manual override, 10 = reference (the user's own
-- prior categorizations), 50 = learned from a Capital One category hint.
CREATE TABLE IF NOT EXISTS category_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL REFERENCES categories(canonical_name),
    priority INTEGER NOT NULL DEFAULT 100,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_category_rules_priority ON category_rules(priority);
"""


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a database already existed on disk."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(entries)")}
    if "needs_review" not in existing:
        conn.execute("ALTER TABLE entries ADD COLUMN needs_review INTEGER NOT NULL DEFAULT 0")
    if "match_method" not in existing:
        conn.execute("ALTER TABLE entries ADD COLUMN match_method TEXT NOT NULL DEFAULT 'manual'")
    cat_cols = {row["name"] for row in conn.execute("PRAGMA table_info(categories)")}
    if "expense_type" not in cat_cols:
        conn.execute("ALTER TABLE categories ADD COLUMN expense_type TEXT NOT NULL DEFAULT 'none'")


def months_present(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT month FROM entries ORDER BY month").fetchall()
    return [r["month"] for r in rows]


def latest_month(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT MAX(month) AS m FROM entries").fetchone()
    return row["m"] if row and row["m"] else None


def upsert_entries(conn: sqlite3.Connection, rows: list[dict]) -> None:
    """Each row may optionally include 'needs_review' (0/1) and 'match_method'
    ('exact'|'alias'|'fuzzy'|'unmatched'|'manual'); both default sensibly."""
    for row in rows:
        row.setdefault("needs_review", 0)
        row.setdefault("match_method", "manual")
    conn.executemany(
        """
        INSERT INTO entries (month, bank_currency, category_raw, category_canonical, amount, needs_review, match_method)
        VALUES (:month, :bank_currency, :category_raw, :category_canonical, :amount, :needs_review, :match_method)
        ON CONFLICT(month, bank_currency, category_canonical)
        DO UPDATE SET category_raw = excluded.category_raw, amount = excluded.amount,
                      needs_review = excluded.needs_review, match_method = excluded.match_method
        """,
        rows,
    )
    conn.commit()


def flagged_entries(conn: sqlite3.Connection, month: str | None = None) -> list[sqlite3.Row]:
    if month:
        return conn.execute(
            "SELECT * FROM entries WHERE needs_review = 1 AND month = ? ORDER BY month, bank_currency", (month,)
        ).fetchall()
    return conn.execute(
        "SELECT * FROM entries WHERE needs_review = 1 ORDER BY month, bank_currency"
    ).fetchall()


def confirm_entry(conn: sqlite3.Connection, entry_id: int, canonical_name: str) -> None:
    conn.execute(
        "UPDATE entries SET category_canonical = ?, needs_review = 0, match_method = 'manual' WHERE id = ?",
        (canonical_name, entry_id),
    )
    conn.commit()


def currencies_present_for_month(conn: sqlite3.Connection, month: str) -> set[str]:
    rows = conn.execute("SELECT DISTINCT bank_currency FROM entries WHERE month = ?", (month,)).fetchall()
    return {r["bank_currency"] for r in rows}


def categories_present_for_month(conn: sqlite3.Connection, month: str, currency: str) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT category_canonical FROM entries WHERE month = ? AND bank_currency = ?", (month, currency)
    ).fetchall()
    return {r["category_canonical"] for r in rows}


def set_fx_rate(conn: sqlite3.Connection, month: str, rate: float) -> None:
    conn.execute(
        """
        INSERT INTO fx_rates (month, rate) VALUES (?, ?)
        ON CONFLICT(month) DO UPDATE SET rate = excluded.rate
        """,
        (month, rate),
    )
    conn.commit()


def get_fx_rate(conn: sqlite3.Connection, month: str) -> float | None:
    row = conn.execute("SELECT rate FROM fx_rates WHERE month = ?", (month,)).fetchone()
    if row:
        return row["rate"]
    # fall back to the most recent known rate before this month
    row = conn.execute(
        "SELECT rate FROM fx_rates WHERE month < ? ORDER BY month DESC LIMIT 1", (month,)
    ).fetchone()
    return row["rate"] if row else None


def entries_for_month(conn: sqlite3.Connection, month: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM entries WHERE month = ? ORDER BY bank_currency, category_canonical", (month,)
    ).fetchall()


def all_entries(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM entries ORDER BY month, bank_currency, category_canonical").fetchall()


def get_format_profile(conn: sqlite3.Connection, signature: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM format_profiles WHERE signature = ?", (signature,)
    ).fetchone()


def save_format_profile(
    conn: sqlite3.Connection,
    signature: str,
    label: str,
    kind: str,
    category_col: int | None = None,
    amount_col: int | None = None,
    currency: str | None = None,
    header_rows: int = 0,
) -> None:
    conn.execute(
        """
        INSERT INTO format_profiles
            (signature, label, kind, category_col, amount_col, currency, header_rows, seen_count, last_used)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, datetime('now'))
        ON CONFLICT(signature) DO UPDATE SET
            seen_count = format_profiles.seen_count + 1,
            last_used = datetime('now')
        """,
        (signature, label, kind, category_col, amount_col, currency, header_rows),
    )
    conn.commit()


def list_format_profiles(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM format_profiles ORDER BY last_used DESC").fetchall()


# ---------------------------------------------------------------------------
# Accounts / per-account transactions
# ---------------------------------------------------------------------------

def list_accounts(conn: sqlite3.Connection, active_only: bool = True) -> list[sqlite3.Row]:
    q = "SELECT * FROM accounts"
    if active_only:
        q += " WHERE active = 1"
    q += " ORDER BY sort_order, id"
    return conn.execute(q).fetchall()


def get_account(conn: sqlite3.Connection, account_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()


def add_account(
    conn: sqlite3.Connection, key: str, display_name: str, currency: str, entity: str, sort_order: int
) -> int:
    conn.execute(
        """
        INSERT INTO accounts (key, display_name, currency, entity, sort_order) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET display_name = excluded.display_name, currency = excluded.currency,
                                        entity = excluded.entity, sort_order = excluded.sort_order
        """,
        (key, display_name, currency, entity, sort_order),
    )
    conn.commit()
    return conn.execute("SELECT id FROM accounts WHERE key = ?", (key,)).fetchone()["id"]


def get_account_layout(conn: sqlite3.Connection, account_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM account_layouts WHERE account_id = ?", (account_id,)).fetchone()


def save_account_layout(
    conn: sqlite3.Connection,
    account_id: int,
    amount_mode: str,
    date_col: int | None = None,
    desc_col: int | None = None,
    debit_col: int | None = None,
    credit_col: int | None = None,
    amount_col: int | None = None,
    type_col: int | None = None,
    header_rows: int = 1,
) -> None:
    conn.execute(
        """
        INSERT INTO account_layouts
            (account_id, date_col, desc_col, amount_mode, debit_col, credit_col, amount_col, type_col, header_rows)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_id) DO UPDATE SET
            date_col = excluded.date_col, desc_col = excluded.desc_col, amount_mode = excluded.amount_mode,
            debit_col = excluded.debit_col, credit_col = excluded.credit_col, amount_col = excluded.amount_col,
            type_col = excluded.type_col, header_rows = excluded.header_rows
        """,
        (account_id, date_col, desc_col, amount_mode, debit_col, credit_col, amount_col, type_col, header_rows),
    )
    conn.commit()


def replace_transactions(conn: sqlite3.Connection, account_id: int, month: str, rows: list[dict]) -> None:
    """Each row: txn_date, description, amount, category_raw, category_canonical,
    needs_review, match_method. Replaces all existing transactions for this
    account+month so re-uploads/corrections don't leave stale rows behind."""
    conn.execute("DELETE FROM transactions WHERE account_id = ? AND month = ?", (account_id, month))
    for row in rows:
        row.setdefault("needs_review", 0)
        row.setdefault("match_method", "manual")
        row["account_id"] = account_id
        row["month"] = month
    conn.executemany(
        """
        INSERT INTO transactions
            (account_id, month, txn_date, description, amount, category_raw, category_canonical, needs_review, match_method)
        VALUES (:account_id, :month, :txn_date, :description, :amount, :category_raw, :category_canonical, :needs_review, :match_method)
        """,
        rows,
    )
    conn.commit()


def transactions_for_account_month(conn: sqlite3.Connection, account_id: int, month: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM transactions WHERE account_id = ? AND month = ? ORDER BY txn_date, id",
        (account_id, month),
    ).fetchall()


def update_transaction_category(conn: sqlite3.Connection, txn_id: int, canonical_name: str) -> None:
    conn.execute(
        "UPDATE transactions SET category_canonical = ?, needs_review = 0, match_method = 'manual' WHERE id = ?",
        (canonical_name, txn_id),
    )
    conn.commit()


def flagged_transactions(conn: sqlite3.Connection, month: str | None = None) -> list[sqlite3.Row]:
    """Every needs_review transaction across every account, for one flat cleanup list."""
    q = """
        SELECT t.*, a.display_name AS account_name, a.currency AS account_currency
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE t.needs_review = 1
    """
    params: tuple = ()
    if month:
        q += " AND t.month = ?"
        params = (month,)
    q += " ORDER BY t.month, a.sort_order, t.txn_date, t.id"
    return conn.execute(q, params).fetchall()


def accounts_status_for_month(conn: sqlite3.Connection, month: str) -> list[dict]:
    """For every active account, whether it has any uploaded transactions for this month."""
    counts = {
        r["account_id"]: r["n"]
        for r in conn.execute(
            "SELECT account_id, COUNT(*) AS n FROM transactions WHERE month = ? GROUP BY account_id", (month,)
        ).fetchall()
    }
    return [
        {"account": acc, "n_transactions": counts.get(acc["id"], 0), "uploaded": acc["id"] in counts}
        for acc in list_accounts(conn)
    ]


def rollup_entries_for_month_currency(conn: sqlite3.Connection, month: str, currency: str) -> None:
    """Recompute the aggregated `entries` rows for (month, currency) from every
    account's transactions, so existing calculations/dashboards (which read
    from `entries`) reflect the latest per-transaction data. Writes every known
    category (defaulting to 0), matching the legacy CSV-import behavior and
    avoiding stale leftovers from categories that no longer have transactions."""
    account_ids = [r["id"] for r in list_accounts(conn) if r["currency"] == currency]
    if not account_ids:
        return
    placeholders = ",".join("?" for _ in account_ids)
    rows = conn.execute(
        f"""
        SELECT category_canonical, SUM(amount) AS total
        FROM transactions
        WHERE month = ? AND account_id IN ({placeholders})
        GROUP BY category_canonical
        """,
        (month, *account_ids),
    ).fetchall()
    totals = {r["category_canonical"]: r["total"] for r in rows}
    all_categories = [r["canonical_name"] for r in conn.execute("SELECT canonical_name FROM categories")]
    upsert_entries(conn, [
        {"month": month, "bank_currency": currency, "category_raw": cat,
         "category_canonical": cat, "amount": totals.get(cat, 0.0),
         "needs_review": 0, "match_method": "rollup"}
        for cat in all_categories
    ])


# ---------------------------------------------------------------------------
# Description -> category rules (raw bank-download import path)
# ---------------------------------------------------------------------------

def list_category_rules(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM category_rules ORDER BY priority ASC, id ASC"
    ).fetchall()


def upsert_category_rule(conn: sqlite3.Connection, pattern: str, category: str, priority: int) -> None:
    """Insert or update one description->category rule. Lower priority wins."""
    pattern = pattern.strip().lower()
    if not pattern:
        return
    conn.execute(
        """
        INSERT INTO category_rules (pattern, category, priority) VALUES (?, ?, ?)
        ON CONFLICT(pattern) DO UPDATE SET category = excluded.category, priority = excluded.priority
        """,
        (pattern, category, priority),
    )
    conn.commit()


def delete_category_rule(conn: sqlite3.Connection, rule_id: int) -> None:
    conn.execute("DELETE FROM category_rules WHERE id = ?", (rule_id,))
    conn.commit()
