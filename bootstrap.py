"""Shared app bootstrap: one cached DB connection for the whole Streamlit session."""

import streamlit as st

from core import accounts, categorize, db


@st.cache_resource
def get_ready_conn():
    conn = db.get_conn()
    db.init_db(conn)
    categorize.ensure_seeded(conn)
    accounts.ensure_seeded(conn)
    return conn
