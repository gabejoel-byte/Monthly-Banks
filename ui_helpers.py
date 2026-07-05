"""Shared Streamlit widgets for the "table of rows with an editable category
dropdown" pattern used across several pages. Lives outside core/, which is
documented as Streamlit-free so it can be tested standalone.

Two distinct save semantics show up across the app -- keep them explicit
rather than one do-everything function:
  - confirm_all: every visible row is committed with whatever category is
    currently shown (accepting a suggested match counts as confirming it).
    Used for review queues, where the point of the button is "yes, all of
    these are now correct."
  - save_changed: only rows the user actually edited get written. Used for
    general ledger browsing, where most rows are already correct.
"""

import pandas as pd
import streamlit as st

from core import categorize


def require_password() -> None:
    """Gates the whole app behind a shared password, but only when one is
    configured via st.secrets["app_password"] (e.g. on a public deployment).
    Running locally with no secrets.toml skips the gate entirely, so local
    dev on your own machine/network stays frictionless. Call this once at
    the very top of every page, right after st.set_page_config."""
    try:
        expected = st.secrets.get("app_password")
    except Exception:
        expected = None
    if not expected:
        return
    if st.session_state.get("authenticated"):
        return

    st.title("Monthly Banks P&L Tracker")
    entered = st.text_input("Password", type="password", key="password_gate_input")
    if st.button("Unlock", key="password_gate_button"):
        if entered == expected:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Wrong password.")
    st.stop()


# Fixed identity colors for the charts on the dashboard pages (validated
# categorical palette -- see .streamlit/config.toml for the matching app theme).
# Mapped by entity, not by plot position, so a series keeps its color no matter
# what else is on the chart with it.
CATEGORY_COLORS = {
    "income": "#2a78d6", "Income": "#2a78d6",
    "personal": "#1baf7a", "Personal Expenses": "#1baf7a", "Personal": "#1baf7a",
    "business": "#eda100", "Business Expenses": "#eda100", "Business": "#eda100",
    "pension": "#008300", "KH/Pension": "#008300", "Pension": "#008300",
    "Net": "#4a3aa7",
}
ENTITY_COLORS = {
    "Private Final Net": "#e34948", "Chevra Final Net": "#e87ba4", "USA Final Net": "#eb6834",
}


def apply_mobile_css() -> None:
    """Tightens up the default Streamlit chrome on narrow (phone-width)
    screens: less wasted top/side padding, full-width buttons for easier
    tapping, metric text that doesn't overflow, and momentum-scrolling for
    the wide data tables that can't be made to fit without one. Call once
    near the top of every page, after st.set_page_config."""
    st.markdown(
        """
        <style>
        @media (max-width: 640px) {
            .block-container {
                padding-top: 1.5rem;
                padding-left: 0.75rem;
                padding-right: 0.75rem;
                padding-bottom: 2rem;
            }
            .stButton > button, .stDownloadButton > button {
                width: 100%;
            }
            div[data-testid="stMetricValue"] {
                font-size: 1.35rem;
            }
            div[data-testid="stExpander"] summary {
                padding-top: 0.6rem;
                padding-bottom: 0.6rem;
            }
        }
        div[data-testid="stDataFrame"], div[data-testid="stElementToolbar"] + div {
            -webkit-overflow-scrolling: touch;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_category_table(
    df: pd.DataFrame,
    category_col: str,
    category_options: list[str],
    key: str,
    disabled: list[str] | None = None,
    required: bool = True,
    hide: list[str] | None = None,
) -> pd.DataFrame:
    """Renders a data_editor where `category_col` is a dropdown of canonical
    category names and every other column is read-only by default. `hide`
    keeps columns in the underlying data (e.g. for alias-learning lookups)
    without showing them -- useful for trimming wide tables on small screens."""
    if disabled is None:
        disabled = [c for c in df.columns if c != category_col]
    column_config = {
        category_col: st.column_config.SelectboxColumn(
            category_col, options=sorted(category_options), required=required,
        ),
    }
    for col in ["id", *(hide or [])]:
        if col in df.columns:
            column_config[col] = None
    return st.data_editor(df, width="stretch", disabled=disabled, column_config=column_config, key=key)


def confirm_all(
    conn,
    original_df: pd.DataFrame,
    edited_df: pd.DataFrame,
    id_col: str,
    category_col: str,
    apply_fn,
    raw_col: str | None = None,
) -> list[tuple]:
    """Commits every row's currently-shown category (whether the user edited
    it or accepted the suggested default), teaching an alias for the raw
    label when one is given. Returns the (row_id, category) pairs applied."""
    applied = []
    for i, row in edited_df.iterrows():
        row_id = original_df.loc[i, id_col]
        new_category = row[category_col]
        if not new_category or (isinstance(new_category, float) and pd.isna(new_category)):
            continue
        apply_fn(row_id, new_category)
        if raw_col:
            raw_label = original_df.loc[i, raw_col]
            if raw_label:
                categorize.learn_alias(conn, raw_label, new_category)
        applied.append((row_id, new_category))
    return applied


def save_changed(
    original_df: pd.DataFrame,
    edited_df: pd.DataFrame,
    id_col: str,
    category_col: str,
    apply_fn,
) -> list[tuple]:
    """Commits only rows whose category actually changed from what was
    originally shown. Returns the (row_id, category) pairs applied."""
    applied = []
    for i, row in edited_df.iterrows():
        row_id = original_df.loc[i, id_col]
        old_value = original_df.loc[i, category_col]
        new_value = row[category_col]
        if new_value == old_value or not new_value or (isinstance(new_value, float) and pd.isna(new_value)):
            continue
        apply_fn(row_id, new_value)
        applied.append((row_id, new_value))
    return applied
