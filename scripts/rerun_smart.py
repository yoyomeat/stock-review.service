import subprocess, os, sys, time

CSV_DIR = '/opt/stock-review/data/csv'

csv_dates = sorted([f.replace('stock_daily_', '').replace('.csv', '') for f in os.listdir(CSV_DIR) if f.startswith('stock_daily_') and not f.endswith('.bak')])

to_run = [d for d in csv_dates if d >= '20250603']
print('Total dates to rerun: %d' % len(to_run))

errors = 0
for i, date in enumerate(to_run):
    print('[%d/%d] %s' % (i + 1, len(to_run), date), flush=True)
    try:
        result = subprocess.run(
            [sys.executable, 'run_review.py', date],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            errors += 1
            print('  ERROR', flush=True)
    except subprocess.TimeoutExpired:
        errors += 1
        print('  TIMEOUT', flush=True)
    time.sleep(0.3)

print('\nDone. %d reviews, %d errors.' % (len(to_run), errors))
