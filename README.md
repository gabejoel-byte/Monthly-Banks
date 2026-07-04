# Monthly Banks P&L Tracker

A local dashboard for tracking Private / Chevra / USA income & expenses across
Israel-NIS and USA-USD bank accounts, with automatic category matching and
month-over-month commentary.

## Running it

```
.venv\Scripts\python.exe -m pip install -r requirements.txt   # first time only
.venv\Scripts\streamlit.exe run app.py
```

Then open http://localhost:8501 in your browser.

If you haven't already loaded the 2026 history, run once:

```
.venv\Scripts\python.exe seed\import_history.py
```

**Note:** `data/`, `Assets/`, and `seed/*.csv` are gitignored — they contain real
account numbers and financial figures and are never pushed to GitHub. They stay
on your machine only; a fresh clone needs its own `Assets/*.xlsx` workbooks (or
`seed/*.csv` files) before `import_history.py`/`import_transactions.py` will
have anything to import.

## Pages

- **Upload** — for a chosen month (defaults to the current one), a checklist of
  every real bank/credit-card account with a per-account file uploader and a
  live NIS/USD/combined total as you go. An "Advanced" section still supports
  the older single combined category-summary CSV/XLSX upload.
- **Monthly Dashboard** — one month's full P&L: Private/Chevra/USA breakdown,
  category chart, and auto-generated commentary vs the prior month.
- **Multi-Month Dashboard** — trends, YTD totals, and monthly averages across
  every month on file.
- **Category Rules & Settings** — edit which P&L bucket each category feeds,
  review learned aliases and file layouts, and edit FX rates per month.
- **Review & Completeness** — what needs fixing: every flagged transaction
  across every account in one editable list, the legacy flagged-entries list,
  and a check for accounts/categories that look missing for a given month.
- **All Transactions** — browse the full transaction ledger, filterable to all
  accounts or specific ones, with a converted-to-NIS column and inline
  per-month exchange-rate calibration.

The app remembers each account's file layout and category-column position
after the first upload, and learns category-label spelling variants as you
confirm them.

## Project layout

- `core/` — parsing, categorization, calculations, and commentary logic (no
  Streamlit dependency; can be tested standalone).
- `ui_helpers.py` — shared Streamlit widgets (the "editable category table"
  pattern used on Upload/Review/All Transactions) and the chart color palette.
- `pages/` — the Streamlit UI.
- `seed/` — the historical Jan-May 2026 source files, the one-time import
  scripts (`import_history.py` for the legacy category-summary CSVs,
  `import_transactions.py` for the real per-account workbooks in `Assets/`),
  plus verification/smoke-test scripts.
- `data/banks.db` — the SQLite database (created on first run).

## Verifying the calculations

`seed/verify_calculations.py` checks computed figures against the known values
from the original monthly spreadsheets. `seed/smoke_test_pages.py` runs every
page headlessly to catch rendering errors. `seed/smoke_test_upload_flow.py` and
`seed/smoke_test_account_upload_flow.py` exercise the parse → categorize →
learn → save pipeline end to end, for the legacy and per-account upload paths
respectively.
