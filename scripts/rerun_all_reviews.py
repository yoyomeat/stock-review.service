"""全量重跑review（已验证的方法）"""
import sys, os, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
root = "/opt/stock-review"
sys.path.insert(0, root)
sys.path.insert(0, os.path.join(root, "quant"))
os.chdir(root)

from quant.review_new import run_single
from types import SimpleNamespace
from pathlib import Path

args = SimpleNamespace(
    csv_dir="data/csv", report_dir="reports", force=True,
    json_output=False, no_save=False, download_only=False,
    backtest=False, backtest_start=None, backtest_capital=1000000, html=False,
    skip_download=False,
)

reports_dir = Path("reports")
review_dates = sorted([f.replace("stock_daily_", "").replace(".csv", "")
                        for f in os.listdir("data/csv")
                        if f.startswith("stock_daily_") and f.endswith(".csv")])
print(f"Total: {len(review_dates)} reviews to rerun")

old_stdout = sys.stdout
sys.stdout = io.StringIO()

success = 0
failed = 0
t0 = time.time()

for i, date_str in enumerate(review_dates):
    try:
        meta = run_single(date_str, args)
        if meta:
            success += 1
        else:
            failed += 1
    except Exception:
        failed += 1

    if (i + 1) % 10 == 0:
        elapsed = time.time() - t0
        avg = elapsed / (i + 1)
        remaining = avg * (len(review_dates) - i - 1)
        sys.stdout = old_stdout
        print(f"  {i+1}/{len(review_dates)} ({elapsed:.0f}s, ~{remaining:.0f}s remaining)")
        sys.stdout = io.StringIO()

sys.stdout = old_stdout
elapsed = time.time() - t0
print(f"\nDone: {success} success, {failed} failed ({elapsed:.0f}s, {elapsed/len(review_dates):.1f}s/review)")
