"""P&L formulas reverse-engineered from the user's historical spreadsheets and
verified exactly against Jan/Feb/Mar/Apr/May 2026 figures (see plan doc for the
derivation). Key design points confirmed from the data:

- Private/Chevra entity figures draw ONLY from the Israel-NIS section; the USA
  entity draws ONLY from the USA-USD section (cross-currency noise in the "wrong"
  section, e.g. a stray USD-side "Private Israel Income" entry, is ignored --
  confirmed by April 2026 data, where including it would have broken the match).
- Money Transfer, Credit Card Payments, and the 3 Charity categories are excluded
  from every P&L total (transfers/settlements and separately-tracked charity).
- Tzedaka and Savings are each -20% of |Net|; Final Net = Net + Tzedaka + Savings.
- The combined ("Global") multi-currency totals convert USD to NIS at that
  month's FX rate before summing.
"""

from . import db

PRIVATE_INCOME_CATS = ["Private Israel Income"]
PRIVATE_EXPENSE_CATS = ["Private Business Expenses", "Private Bank Fees"]
CHEVRA_EXPENSE_CATS = ["Chevra Expenses", "Chevra Bank Fees"]


def _amounts_by_category(conn, month: str, currency: str) -> dict[str, float]:
    rows = db.entries_for_month(conn, month)
    return {r["category_canonical"]: r["amount"] for r in rows if r["bank_currency"] == currency}


def _sum_cats(amounts: dict[str, float], cats: list[str]) -> float:
    return sum(amounts.get(c, 0.0) for c in cats)


def _tzedaka_savings_final(net: float) -> dict[str, float]:
    """Chevra & USA: Tzedaka/Savings are always a 20% deduction, regardless of
    whether Net is a profit or a loss (confirmed: Chevra Net is positive in
    every sample month, yet Chevra Tzedaka is consistently negative)."""
    tzedaka = -0.2 * abs(net)
    savings = -0.2 * abs(net)
    return {"tzedaka": tzedaka, "savings": savings, "final_net": net + tzedaka + savings}


def _tzedaka_savings_final_signed(net: float) -> dict[str, float]:
    """Private: Tzedaka/Savings follow Net's own sign (20% of Net, not |Net|) --
    confirmed by Feb 2026, the only sample month where Private Net is positive:
    Tzedaka was reported as +3548, not -3548. Final Net = Net * 1.4 always."""
    tzedaka = 0.2 * net
    savings = 0.2 * net
    return {"tzedaka": tzedaka, "savings": savings, "final_net": net + tzedaka + savings}


def private_pl(nis: dict[str, float]) -> dict[str, float]:
    gross = _sum_cats(nis, PRIVATE_INCOME_CATS)
    expenses = _sum_cats(nis, PRIVATE_EXPENSE_CATS)
    pretax = nis.get("Bituach Leumi Private", 0.0) + nis.get("Pension KH Private", 0.0)
    tax = nis.get("Private Taxes", 0.0)
    vat = nis.get("Private VAT", 0.0)
    net = gross + expenses + pretax + tax + vat
    result = {"gross": gross, "expenses": expenses, "pretax": pretax, "tax": tax, "vat": vat, "net": net}
    result.update(_tzedaka_savings_final_signed(net))
    return result


def chevra_pl(nis: dict[str, float]) -> dict[str, float]:
    gross = nis.get("Chevra Income", 0.0)
    expenses = _sum_cats(nis, CHEVRA_EXPENSE_CATS)
    pretax = nis.get("Bituach Leumi Chevra", 0.0) + nis.get("Pension KH Chevra", 0.0)
    tax = nis.get("Chevra Taxes", 0.0)
    vat = nis.get("Chevra VAT", 0.0)
    net = gross + expenses + pretax + tax + vat
    result = {"gross": gross, "expenses": expenses, "pretax": pretax, "tax": tax, "vat": vat, "net": net}
    result.update(_tzedaka_savings_final(net))
    return result


def usa_pl(usd: dict[str, float]) -> dict[str, float]:
    gross = usd.get("USA Income", 0.0)
    expenses = usd.get("USA Business Expense", 0.0)
    tax = -0.30 * (gross + expenses)
    net = gross + expenses + tax
    result = {"gross": gross, "expenses": expenses, "tax": tax, "net": net}
    result.update(_tzedaka_savings_final(net))
    return result


def personal_expenses(conn, nis: dict[str, float], usd: dict[str, float]) -> dict[str, float]:
    personal_cats = [
        name for name, group in
        ((r["canonical_name"], r["group_name"]) for r in conn.execute(
            "SELECT canonical_name, group_name FROM categories"
        ))
        if group == "personal"
    ]
    return {
        "nis": _sum_cats(nis, personal_cats),
        "usd": _sum_cats(usd, personal_cats),
    }


def combined_amounts(nis: dict[str, float], usd: dict[str, float], rate: float | None) -> dict[str, float]:
    rate = rate or 0.0
    cats = set(nis) | set(usd)
    return {c: nis.get(c, 0.0) + usd.get(c, 0.0) * rate for c in cats}


def group_totals(conn, combined: dict[str, float]) -> dict[str, float]:
    group_of = {r["canonical_name"]: r["group_name"] for r in conn.execute("SELECT canonical_name, group_name FROM categories")}
    totals = {"income": 0.0, "personal": 0.0, "business": 0.0, "pension": 0.0}
    for cat, amount in combined.items():
        g = group_of.get(cat)
        if g in totals:
            totals[g] += amount
    totals["total_expenses"] = totals["personal"] + totals["business"] + totals["pension"]
    totals["net"] = totals["income"] + totals["total_expenses"]
    return totals


def month_report(conn, month: str) -> dict:
    nis = _amounts_by_category(conn, month, "NIS")
    usd = _amounts_by_category(conn, month, "USD")
    rate = db.get_fx_rate(conn, month)

    private = private_pl(nis)
    chevra = chevra_pl(nis)
    usa = usa_pl(usd)
    personal = personal_expenses(conn, nis, usd)

    israel_net_after_personal = private["final_net"] + chevra["final_net"] + personal["nis"]
    usa_net_after_personal = usa["final_net"] + personal["usd"]

    combined = combined_amounts(nis, usd, rate)
    totals = group_totals(conn, combined)

    return {
        "month": month,
        "fx_rate": rate,
        "nis": nis,
        "usd": usd,
        "private": private,
        "chevra": chevra,
        "usa": usa,
        "personal_expenses": personal,
        "israel_net_after_personal": israel_net_after_personal,
        "usa_net_after_personal": usa_net_after_personal,
        "combined": combined,
        "totals": totals,
    }


def multi_month_reports(conn, months: list[str] | None = None) -> list[dict]:
    months = months or db.months_present(conn)
    return [month_report(conn, m) for m in months]


def _inflow_outflow(amounts: dict[str, float]) -> dict[str, float]:
    """Split a category->amount map into gross money-in (positive entries) and
    money-out (negative entries), plus their net."""
    inflow = sum(a for a in amounts.values() if a > 0)
    outflow = sum(a for a in amounts.values() if a < 0)
    return {"inflow": inflow, "outflow": outflow, "net": inflow + outflow}


def cashflow_for_month(conn, month: str) -> dict:
    """Inflow / outflow / net for one month, per currency and combined.

    NIS and USD are each summed in their own currency; 'combined' converts USD to
    NIS at the month's FX rate before summing (rate is calibratable per month).
    Each section also carries its category->amount map for a breakdown."""
    nis = _amounts_by_category(conn, month, "NIS")
    usd = _amounts_by_category(conn, month, "USD")
    rate = db.get_fx_rate(conn, month)
    combined = combined_amounts(nis, usd, rate or 0.0)
    return {
        "month": month,
        "rate": rate,
        "nis": {"amounts": nis, **_inflow_outflow(nis)},
        "usd": {"amounts": usd, **_inflow_outflow(usd)},
        "combined": {"amounts": combined, **_inflow_outflow(combined)},
    }


def expense_type_report(conn, months: list[str] | None = None) -> list[dict]:
    """Per-month spend split into fixed / variable / semivariable, combined and
    converted to NIS at each month's FX rate. Expenses are stored as negative
    amounts, so they're flipped to positive spend magnitudes here. Categories
    whose expense_type is 'none' (income, transfers, unclassified) are excluded.
    Each row: {month, rate, buckets:{fixed,variable,semivariable,total},
               by_category:{fixed:{cat:amt},...}}."""
    months = months or db.months_present(conn)
    etypes = {
        r["canonical_name"]: r["expense_type"]
        for r in conn.execute("SELECT canonical_name, expense_type FROM categories")
    }
    tracked = ("fixed", "variable", "semivariable")
    out = []
    for m in months:
        nis = _amounts_by_category(conn, m, "NIS")
        usd = _amounts_by_category(conn, m, "USD")
        rate = db.get_fx_rate(conn, m) or 0.0
        combined = combined_amounts(nis, usd, rate)
        buckets = {t: 0.0 for t in tracked}
        by_category: dict[str, dict[str, float]] = {t: {} for t in tracked}
        for cat, amount in combined.items():
            et = etypes.get(cat, "none")
            if et not in tracked:
                continue
            spend = -amount  # expenses are stored negative; show as positive spend
            buckets[et] += spend
            by_category[et][cat] = by_category[et].get(cat, 0.0) + spend
        buckets["total"] = sum(buckets[t] for t in tracked)
        out.append({"month": m, "rate": rate, "buckets": buckets, "by_category": by_category})
    return out
