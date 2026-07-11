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

## Deploying it (e.g. Streamlit Community Cloud)

This is a stateful Streamlit server, not a serverless function — it needs a
host that runs a persistent process (Streamlit Community Cloud, Render,
Railway, Fly.io, a container on Cloud Run, etc.), **not** Vercel/Netlify-style
platforms.

A deployed copy starts with an empty database (its own separate `data/banks.db`,
since the real one is gitignored) — treat your local machine as the source of
truth and the deployed copy as an on-the-go convenience, unless you deliberately
want to migrate fully.

Since a public deployment has no login by default, this app supports an
optional password gate: set a Streamlit secret named `app_password` (see
`.streamlit/secrets.toml.example`) and every page requires it before loading.
Locally, with no secret configured, there's no login screen at all.

## Pages

- **Upload** — two ways in:
    - **Import raw bank downloads (auto-detect)** — drop the banks' own export
      files (Capital One CSVs, Bank Yahav עו״ש `.xls`, Isracard/Amex `.xlsx`) and
      they're detected, categorized from each transaction's description, and
      filed to the right account automatically. A file can span several months;
      every month it covers is updated. New accounts are created on the fly for
      cards/accounts not seen before.
    - **Per-account monthly checklist** — for a chosen month (defaults to the
      current one), a checklist of every real bank/credit-card account with a
      per-account uploader for the pre-totaled monthly workbooks and a live
      NIS/USD/combined total as you go. An "Advanced" section still supports the
      older single combined category-summary CSV/XLSX upload.
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
    - `core/bank_downloads/` — format-sniffing parsers for the banks' own native
      export files (Capital One CSV, Bank Yahav `.xls`, Isracard/Amex `.xlsx`),
      merged in from the former standalone "Monthly Banks 1" app.
    - `core/txn_categorize.py` — description-based categorization for those
      files (they carry no category column), driven by a `category_rules` table
      seeded from `category_reference.json` plus a few Hebrew/English fallback
      rules.
    - `core/bank_ingest.py` — maps parsed native transactions into the app's
      account/transaction model (currency, sign, account matching, month
      bucketing) for the auto-detect Upload path.
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
