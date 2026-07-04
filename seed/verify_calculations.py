"""Regression check: computed P&L must match the known derived figures from
the source spreadsheets exactly (within float rounding)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import calculations, db  # noqa: E402

EXPECTED = {
    "2026-01": {
        ("private", "net"): -2926.42, ("private", "final_net"): -4096.988,
        ("chevra", "net"): 20058.058, ("chevra", "final_net"): 12034.8348,
        ("usa", "net"): 12435.311, ("usa", "final_net"): 7461.1866,
        "personal_nis": -17771.168 + 1111.79,  # clean formula = buggy sheet value minus the double-counted Health
        "personal_usd": None,
        "israel_net_after_personal": None,
    },
    "2026-02": {
        ("private", "net"): 17740, ("private", "final_net"): 24836,
        ("chevra", "net"): 18350, ("chevra", "final_net"): 11010,
        ("usa", "net"): 14769, ("usa", "final_net"): 8861,
    },
    "2026-03": {
        ("private", "net"): -1161, ("private", "final_net"): -1625,
        ("chevra", "net"): 23652, ("chevra", "final_net"): 14191,
        ("usa", "net"): 3433, ("usa", "final_net"): 2060,
        "personal_nis": -15447 + 552,  # clean formula = buggy sheet value minus the double-counted Health
        "personal_usd": -4699,
    },
    "2026-04": {
        ("private", "net"): -2496, ("private", "final_net"): -3494,
        ("chevra", "net"): 69228, ("chevra", "final_net"): 41537,
        ("usa", "net"): 16578, ("usa", "final_net"): 9947,
    },
}


def close(a, b, tol=1.0):
    return a is not None and b is not None and abs(a - b) <= tol


def main():
    conn = db.get_conn()
    failures = 0
    for month, expected in EXPECTED.items():
        report = calculations.month_report(conn, month)
        print(f"\n== {month} ==")
        for key, exp_val in expected.items():
            if isinstance(key, tuple):
                entity, field = key
                got = report[entity][field]
                ok = close(got, exp_val)
                status = "OK" if ok else "MISMATCH"
                print(f"  {entity}.{field}: got={got:.3f} expected={exp_val:.3f}  [{status}]")
                if not ok:
                    failures += 1
            elif key == "personal_nis" and exp_val is not None:
                got = report["personal_expenses"]["nis"]
                ok = close(got, exp_val)
                print(f"  personal_expenses.nis: got={got:.3f} expected={exp_val:.3f}  [{'OK' if ok else 'MISMATCH'}]")
                if not ok:
                    failures += 1
            elif key == "personal_usd" and exp_val is not None:
                got = report["personal_expenses"]["usd"]
                ok = close(got, exp_val)
                print(f"  personal_expenses.usd: got={got:.3f} expected={exp_val:.3f}  [{'OK' if ok else 'MISMATCH'}]")
                if not ok:
                    failures += 1

    conn.close()
    print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} MISMATCHES'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
