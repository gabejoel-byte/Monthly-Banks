"""Headless smoke test: runs each Streamlit page script (via AppTest) and
reports any exceptions, so we can verify rendering without a real browser."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from streamlit.testing.v1 import AppTest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def check(name: str, at: AppTest):
    at.run(timeout=30)
    if at.exception:
        print(f"[{name}] EXCEPTION(S):")
        for e in at.exception:
            print(f"   {e.value!r}")
        return False
    print(f"[{name}] OK -- {len(at.get('metric'))} metrics, {len(at.get('markdown'))} markdown blocks rendered")
    return True


ok = True
ok &= check("app.py (home)", AppTest.from_file(str(ROOT / "app.py")))
ok &= check("2_Monthly_Dashboard.py", AppTest.from_file(str(ROOT / "pages" / "2_Monthly_Dashboard.py")))
ok &= check("3_Multi_Month_Dashboard.py", AppTest.from_file(str(ROOT / "pages" / "3_Multi_Month_Dashboard.py")))
ok &= check("4_Category_Rules.py", AppTest.from_file(str(ROOT / "pages" / "4_Category_Rules.py")))
ok &= check("5_Review.py", AppTest.from_file(str(ROOT / "pages" / "5_Review.py")))
ok &= check("6_All_Transactions.py", AppTest.from_file(str(ROOT / "pages" / "6_All_Transactions.py")))
ok &= check("1_Upload.py (no file yet)", AppTest.from_file(str(ROOT / "pages" / "1_Upload.py")))

print("\nALL PAGES OK" if ok else "\nSOME PAGES FAILED")
sys.exit(0 if ok else 1)
