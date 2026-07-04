import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db  # noqa: E402

conn = db.get_conn()
conn.execute("DELETE FROM entries WHERE month = '2026-06'")
conn.execute("DELETE FROM fx_rates WHERE month = '2026-06'")
conn.execute("DELETE FROM category_aliases WHERE raw_label = 'cell phone'")
conn.execute("DELETE FROM format_profiles WHERE label LIKE '%june_2026_test%'")
conn.execute("DELETE FROM transactions WHERE month = '2026-06'")
conn.commit()
print("months now:", db.months_present(conn))
