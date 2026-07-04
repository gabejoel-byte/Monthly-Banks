"""Rule-based month-over-month commentary. No LLM calls -- everything here is
a deterministic comparison against prior months' stored data."""

from . import calculations, db

BIG_CATEGORY_MOVE_THRESHOLD = 200  # NIS-equivalent
BIG_CATEGORY_MOVE_FLOOR = 50  # ignore categories that were negligible both months
TREND_PCT_THRESHOLD = 15
TRAILING_PCT_THRESHOLD = 20
ENTITY_FINAL_NET_THRESHOLD = 1000


def generate_commentary(conn, month: str) -> list[str]:
    months = db.months_present(conn)
    prior_months = [m for m in months if m < month]
    if not prior_months:
        return ["This is the first month of data — no month-over-month comparison available yet."]

    prev_month = prior_months[-1]
    current = calculations.month_report(conn, month)
    previous = calculations.month_report(conn, prev_month)

    notes: list[str] = []
    notes.extend(_net_note(current, previous, prev_month))
    notes.extend(_totals_trend_notes(current, previous))
    notes.extend(_trailing_average_notes(conn, current, prior_months))
    notes.extend(_entity_final_net_notes(current, previous))
    notes.extend(_category_mover_notes(current, previous))
    return notes


def _net_note(current: dict, previous: dict, prev_month: str) -> list[str]:
    cur_net = current["totals"]["net"]
    prev_net = previous["totals"]["net"]
    if prev_net < 0 <= cur_net:
        return [f"Net flipped positive this month (₪{cur_net:,.0f}) after a negative Net in {prev_month} (₪{prev_net:,.0f})."]
    if cur_net < 0 <= prev_net:
        return [f"Net flipped negative this month (₪{cur_net:,.0f}) after a positive Net in {prev_month} (₪{prev_net:,.0f})."]
    delta = cur_net - prev_net
    pct = f" ({delta / abs(prev_net) * 100:+.0f}%)" if prev_net else ""
    direction = "up" if delta > 0 else "down"
    return [f"Net is {direction} ₪{abs(delta):,.0f} vs {prev_month}{pct} (now ₪{cur_net:,.0f})."]


def _totals_trend_notes(current: dict, previous: dict) -> list[str]:
    notes = []
    for label, key in [("Income", "income"), ("Personal Expenses", "personal"), ("Business Expenses", "business")]:
        cur_v, prev_v = current["totals"][key], previous["totals"][key]
        if not prev_v:
            continue
        pct = (cur_v - prev_v) / abs(prev_v) * 100
        if abs(pct) >= TREND_PCT_THRESHOLD:
            direction = "up" if cur_v > prev_v else "down"
            notes.append(f"{label} {direction} {abs(pct):.0f}% vs last month.")
    return notes


def _trailing_average_notes(conn, current: dict, prior_months: list[str]) -> list[str]:
    if len(prior_months) < 2:
        return []
    window = prior_months[-3:]
    trailing = calculations.multi_month_reports(conn, window)
    avg_net = sum(r["totals"]["net"] for r in trailing) / len(trailing)
    if not avg_net:
        return []
    cur_net = current["totals"]["net"]
    pct = (cur_net - avg_net) / abs(avg_net) * 100
    if abs(pct) >= TRAILING_PCT_THRESHOLD:
        direction = "above" if cur_net > avg_net else "below"
        return [f"Net is {abs(pct):.0f}% {direction} your trailing {len(trailing)}-month average (₪{avg_net:,.0f})."]
    return []


def _entity_final_net_notes(current: dict, previous: dict) -> list[str]:
    notes = []
    for entity in ("private", "chevra", "usa"):
        cur_fn = current[entity]["final_net"]
        prev_fn = previous[entity]["final_net"]
        delta = cur_fn - prev_fn
        if abs(delta) >= ENTITY_FINAL_NET_THRESHOLD:
            notes.append(f"{entity.title()} Final Net moved {delta:+,.0f} vs last month (now {cur_fn:,.0f}).")
    return notes


def _category_mover_notes(current: dict, previous: dict, top_n: int = 3) -> list[str]:
    cur_combined, prev_combined = current["combined"], previous["combined"]
    movers = []
    for cat in set(cur_combined) | set(prev_combined):
        cv, pv = cur_combined.get(cat, 0.0), prev_combined.get(cat, 0.0)
        if abs(cv) < BIG_CATEGORY_MOVE_FLOOR and abs(pv) < BIG_CATEGORY_MOVE_FLOOR:
            continue
        delta = cv - pv
        if abs(delta) >= BIG_CATEGORY_MOVE_THRESHOLD:
            movers.append((abs(delta), cat, pv, cv, delta))
    movers.sort(reverse=True)
    return [
        f"{cat}: ₪{pv:,.0f} → ₪{cv:,.0f} ({delta:+,.0f})"
        for _, cat, pv, cv, delta in movers[:top_n]
    ]
