"""Adapter that ingests raw native bank-download files into the Streamlit app's
account/transaction model.

Bridges core/bank_downloads (the format-sniffing parsers) to the existing
`accounts` / `account_layouts` / `transactions` / `entries` tables. Responsible
for the semantic conversions the two apps disagreed on:

  * currency     - the parsers emit ISO "ILS"/"USD"; the app uses "NIS"/"USD".
  * sign         - the parsers emit a positive magnitude + direction; the app
                   stores a signed amount (credit/deposit positive, debit/expense
                   negative), matching core/account_parser.
  * account      - a parser's source_key (e.g. "checking_9220") is matched to an
                   existing account by trailing digits + currency, or a new
                   account is created. Foreign-currency lines on an otherwise
                   single-currency card (e.g. USD charges on an Israeli Amex) are
                   split into a per-currency account so they aren't summed into
                   the wrong currency's totals.
  * category     - native files have no category column, so categorization runs
                   off the description (core/txn_categorize).

preview() is read-only (no DB writes) so the UI can show what will happen;
commit() creates any new accounts, replaces each affected account+month, and
rolls the aggregated `entries` back up.
"""
import re
import sqlite3

from . import db, txn_categorize
from .bank_downloads import UnrecognizedFileError, detect_and_parse

# The parsers emit ISO currency codes; the app's domain uses NIS for shekels.
_CURRENCY_MAP = {"ILS": "NIS", "NIS": "NIS", "USD": "USD"}


def _app_currency(parser_currency: str) -> str:
    return _CURRENCY_MAP.get(parser_currency, parser_currency)


def _digit_suffix(s: str) -> str:
    """Trailing run of digits, e.g. 'checking_7501' -> '7501'."""
    m = re.search(r"(\d+)\D*$", s or "")
    return m.group(1) if m else ""


def _signed_amount(amount: float, direction: str) -> float:
    """Credits/deposits are positive, debits/expenses negative -- the same
    convention core/account_parser produces for the workbook path."""
    return amount if direction == "credit" else -amount


def _match_existing_account(accounts: list[sqlite3.Row], source_key: str, app_currency: str):
    """Return an existing account whose key ends with the source's trailing
    digits and whose currency matches, else None."""
    suffix = _digit_suffix(source_key)
    if not suffix:
        return None
    for a in accounts:
        if a["currency"] != app_currency:
            continue
        if _digit_suffix(a["key"]).endswith(suffix) or a["key"].endswith(suffix):
            return a
    return None


def _guess_entity(app_currency: str) -> str:
    return "USA" if app_currency == "USD" else "Private"


# ---------------------------------------------------------------------------
# Parse + preview (read-only)
# ---------------------------------------------------------------------------

def parse_files(files: list[tuple[str, bytes]]) -> tuple[list[dict], list[dict]]:
    """files: (filename, content) pairs. Returns (transactions, file_summaries).
    Each file_summary reports how that file was recognized (or the error)."""
    all_txns: list[dict] = []
    summaries: list[dict] = []
    for filename, content in files:
        try:
            txns = detect_and_parse(filename, content)
        except UnrecognizedFileError as e:
            summaries.append({"filename": filename, "status": "unrecognized", "detail": str(e), "count": 0})
            continue
        except Exception as e:  # a malformed file shouldn't sink the whole batch
            summaries.append({"filename": filename, "status": "error", "detail": str(e), "count": 0})
            continue
        all_txns.extend(txns)
        if txns:
            summaries.append({
                "filename": filename, "status": "ok",
                "source_key": txns[0]["source_key"], "account_label": txns[0]["account_label"],
                "count": len(txns),
                "date_range": (min(t["txn_date"] for t in txns), max(t["txn_date"] for t in txns)),
            })
        else:
            summaries.append({"filename": filename, "status": "empty", "count": 0})
    return all_txns, summaries


def preview(conn: sqlite3.Connection, files: list[tuple[str, bytes]]) -> dict:
    """Read-only: parse, dedup, categorize, and resolve each transaction to an
    account (marking ones that would create a new account) without writing."""
    txns, summaries = parse_files(files)

    # Dedup exact repeats (the same line appearing in two overlapping monthly
    # exports of the same card) by the parser's content hash.
    seen: set[str] = set()
    deduped = []
    for t in txns:
        if t["dedup_hash"] in seen:
            continue
        seen.add(t["dedup_hash"])
        deduped.append(t)

    accounts = list(db.list_accounts(conn, active_only=False))
    categorizer = txn_categorize.Categorizer(conn)

    rows = []
    for t in deduped:
        app_cur = _app_currency(t["currency"])
        match = _match_existing_account(accounts, t["source_key"], app_cur)
        cat = categorizer.categorize(t["description"], t.get("category_hint"))
        canonical = cat["canonical"] or "Miscellaneous"
        rows.append({
            # internal (for commit)
            "source_key": t["source_key"],
            "account_label": t["account_label"],
            "app_currency": app_cur,
            "account_id": match["id"] if match else None,
            "is_new_account": match is None,
            "dedup_hash": t["dedup_hash"],
            "category_hint": t.get("category_hint"),
            "match_method": cat["method"],
            "suggested_category": canonical,
            "needs_review": 0 if cat["canonical"] else 1,
            # display / editable
            "date": t["txn_date"],
            "month": (t["txn_date"] or "")[:7],
            "account": (match["display_name"] if match else f"(new) {t['account_label']} [{app_cur}]"),
            "description": t["description"],
            "amount": _signed_amount(t["amount"], t["direction"]),
            "currency": app_cur,
            "category": canonical,
        })

    n_new_accounts = len({(r["source_key"], r["app_currency"]) for r in rows if r["is_new_account"]})
    months = sorted({r["month"] for r in rows if r["month"]})
    return {
        "rows": rows,
        "file_summaries": summaries,
        "n_transactions": len(rows),
        "n_uncategorized": sum(1 for r in rows if r["needs_review"]),
        "n_new_accounts": n_new_accounts,
        "months": months,
    }


# ---------------------------------------------------------------------------
# Commit (writes)
# ---------------------------------------------------------------------------

def _get_or_create_account(conn: sqlite3.Connection, cache: dict, source_key: str,
                           account_label: str, app_currency: str) -> int:
    suffix = _digit_suffix(source_key)
    cache_key = (suffix, app_currency)
    if cache_key in cache:
        return cache[cache_key]

    accounts = list(db.list_accounts(conn, active_only=False))
    match = _match_existing_account(accounts, source_key, app_currency)
    if match:
        cache[cache_key] = match["id"]
        return match["id"]

    # Create a new account. Ensure a unique key even if a same-numbered account
    # exists in the other currency (add_account UPSERTs on key, so a collision
    # would silently overwrite it).
    existing_keys = {a["key"] for a in accounts}
    key = source_key if source_key not in existing_keys else f"{source_key}_{app_currency.lower()}"
    label = account_label if not any(a["display_name"] == account_label for a in accounts) \
        else f"{account_label} [{app_currency}]"
    sort_order = max([a["sort_order"] for a in accounts], default=0) + 10
    account_id = db.add_account(conn, key, label, app_currency, _guess_entity(app_currency), sort_order)
    # Minimal placeholder layout so the per-account workbook Upload page (which
    # reads account_layouts) stays well-formed for this account too.
    db.save_account_layout(
        conn, account_id, amount_mode="signed_negate",
        date_col=0, desc_col=1, amount_col=4, header_rows=1,
    )
    cache[cache_key] = account_id
    return account_id


def commit(conn: sqlite3.Connection, rows: list[dict]) -> dict:
    """Persist reviewed rows. Each row needs: source_key, account_label,
    app_currency, date, month, description, amount (signed), category
    (final canonical), needs_review, match_method. Replaces each affected
    account+month wholesale, then rolls entries back up."""
    cache: dict = {}
    # Resolve/create accounts and bucket rows by (account_id, month).
    grouped: dict[tuple[int, str], list[dict]] = {}
    for r in rows:
        month = r["month"] or (r["date"] or "")[:7]
        if not month:
            continue
        account_id = r.get("account_id") or _get_or_create_account(
            conn, cache, r["source_key"], r["account_label"], r["app_currency"]
        )
        grouped.setdefault((account_id, month), []).append({
            "txn_date": r["date"],
            "description": r["description"],
            "amount": float(r["amount"]),
            "category_raw": None,
            "category_canonical": r["category"],
            "needs_review": int(r.get("needs_review", 0)),
            "match_method": r.get("match_method", "auto"),
        })

    affected_currency_months: set[tuple[str, str]] = set()
    account_currency = {a["id"]: a["currency"] for a in db.list_accounts(conn, active_only=False)}
    for (account_id, month), group in grouped.items():
        db.replace_transactions(conn, account_id, month, group)
        affected_currency_months.add((month, account_currency.get(account_id)))

    for month, currency in affected_currency_months:
        if currency:
            db.rollup_entries_for_month_currency(conn, month, currency)

    return {
        "n_transactions": sum(len(g) for g in grouped.values()),
        "n_accounts": len({aid for aid, _ in grouped}),
        "months": sorted({m for _, m in grouped}),
        "currency_months": sorted(affected_currency_months),
    }
