"""Shared app bootstrap: one cached DB connection for the whole Streamlit session."""

import os

import streamlit as st

from core import accounts, categorize, db, txn_categorize


def _bridge_database_secret() -> None:
    """On a deployment, the hosted-database connection string comes in as a
    Streamlit secret; copy it into the environment so core/db.py (which is
    Streamlit-free) can see it. No secret configured => stays on local SQLite."""
    if os.environ.get("DATABASE_URL"):
        return
    try:
        url = st.secrets.get("database_url")
    except Exception:
        url = None
    if url:
        os.environ["DATABASE_URL"] = str(url)


@st.cache_resource
def get_ready_conn():
    _bridge_database_secret()
    conn = db.get_conn()
    db.init_db(conn)
    categorize.ensure_seeded(conn)
    categorize.ensure_expense_types_seeded(conn)
    accounts.ensure_seeded(conn)
    txn_categorize.seed_reference_rules(conn)
    return conn
