#!/bin/bash
cd /opt/stock-review
CSV_DIR=data/csv
DONE=0
FAIL=0
SKIP=0
TOTAL=$(ls $CSV_DIR/stock_daily_*.csv | wc -l)

for f in $(ls $CSV_DIR/stock_daily_*.csv | sort); do
    date=$(basename $f .csv | sed 's/stock_daily_//')
    # Check if review already has strong_pool
    if [ -f "reports/review_${date}.json" ]; then
        sp=$(python3 -c "import json; d=json.load(open('reports/review_${date}.json')); print(len(d.get('strong_pool',[])))" 2>/dev/null)
        if [ "$sp" -gt "0" ] 2>/dev/null; then
            SKIP=$((SKIP+1))
            continue
        fi
    fi
    python3 run_review.py $date --skip-download > /tmp/review_one.log 2>&1
    if [ $? -eq 0 ]; then
        DONE=$((DONE+1))
    else
        FAIL=$((FAIL+1))
        echo "FAIL $date: $(tail -1 /tmp/review_one.log)"
    fi
    total=$((DONE+FAIL+SKIP))
    if [ $((total % 50)) -eq 0 ]; then
        echo "Progress: $total/$TOTAL (done=$DONE fail=$FAIL skip=$SKIP)"
    fi
done
echo "FINAL: done=$DONE fail=$FAIL skip=$SKIP total=$((DONE+FAIL+SKIP))"
