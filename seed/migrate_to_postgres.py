"""One-time copy of the local SQLite database (data/banks.db) up to a hosted
Postgres database, for the always-online deployment.

Usage (from the project folder, with your Neon/Postgres connection string):

    # PowerShell:
    $env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"
    .venv\\Scripts\\python.exe seed\\migrate_to_postgres.py

    # bash:
    DATABASE_URL="postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require" \\
        .venv/Scripts/python.exe seed/migrate_to_postgres.py

Safe to re-run: rows that already exist are skipped (ON CONFLICT DO NOTHING).
Your local SQLite file is only read, never modified.
"""
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db  # noqa: E402

# Copy order respects foreign keys (parents before children).
TABLES = [
    "categories",
    "category_aliases",
    "entries",
    "fx_rates",
    "format_profiles",
    "accounts",
    "account_layouts",
    "transactions",
    "category_rules",
]
# SERIAL tables whose id sequence must be advanced past the copied ids.
SEQUENCES = {
    "entries": "entries_id_seq",
    "accounts": "accounts_id_seq",
    "transactions": "transactions_id_seq",
    "category_rules": "category_rules_id_seq",
}


def main() -> int:
    url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not url:
        print("ERROR: set DATABASE_URL to your Postgres connection string first "
              "(see the comment at the top of this file).")
        return 1
    if not db.DB_PATH.exists():
        print(f"ERROR: no local database found at {db.DB_PATH}. Nothing to migrate.")
        return 1

    print(f"Local SQLite : {db.DB_PATH}")
    print(f"Target Postgres host: {url.split('@')[-1].split('/')[0] if '@' in url else '?'}")

    slite = sqlite3.connect(db.DB_PATH)
    slite.row_factory = sqlite3.Row

    import psycopg2
    pg = psycopg2.connect(url)
    pg.autocommit = True

    # 1) create the schema on Postgres
    db.get_conn  # ensure module import side effects are fine
    pgwrap = db._PGConn(pg)
    db.init_db(pgwrap)
    print("Postgres schema ready.")

    # 2) copy each table
    cur = pg.cursor()
    for table in TABLES:
        cols = [r["name"] for r in slite.execute(f"PRAGMA table_info({table})")]
        if not cols:
            print(f"  {table:18} (no such local table, skipped)")
            continue
        rows = slite.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
        if not rows:
            print(f"  {table:18} 0 rows")
            continue
        collist = ", ".join(cols)
        placeholders = ", ".join(["%s"] * len(cols))
        sql = f"INSERT INTO {table} ({collist}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
        cur.executemany(sql, [tuple(r) for r in rows])
        # verify
        got = None
        with pg.cursor() as c2:
            c2.execute(f"SELECT COUNT(*) FROM {table}")
            got = c2.fetchone()[0]
        print(f"  {table:18} {len(rows)} local -> {got} in Postgres")

    # 3) advance id sequences past the copied rows
    for table, seq in SEQUENCES.items():
        cur.execute(
            f"SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM {table}), 1), "
            f"(SELECT COUNT(*) FROM {table}) > 0)"
        )
    print("Sequences reset. Migration complete. ✅")
    slite.close()
    pg.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
