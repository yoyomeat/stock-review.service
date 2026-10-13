#!/bin/bash
set -uo pipefail
SKILL_DIR="/opt/stock-review"
LOG="/var/log/stock-review-golden.log"
BASELINE_DIR="$SKILL_DIR/data/golden_baseline"
cd "$SKILL_DIR"

GOLDEN_DATES=(
    20250103 20250106 20250107 20250108 20250109 20250110
    20250122 20250123 20250124 20250127
    20250207 20250211 20250213
    20250226 20250227
    20250305 20250306 20250307
    20250820 20250822 20250825
    20251010 20251013
    20260602 20260604 20260607
)

usage() {
    cat <<EOF
用法: bash run_golden.sh <mode>

模式:
  run        跑黄金集（--force 重算），报告失败
  validate   跑黄金集并对比基线，报告差异
  baseline   将当前 review 保存为基线（validate 的对比基准）
  list       列出黄金日期
  count      显示覆盖统计

覆盖:
  冰点期:3  下降期:8  反弹确认:2  上升期:9  上升分歧:2  确认震荡:2
  CONC_EARLY:11  CONC_EARLY_CONFIRMED:4  CONC_CONFIRM:3  CONC_STRONG:3  none:5
  ml_early:11  ml_confirmed:10  ml_none:5  picks:20/26
EOF
}

MODE="${1:-run}"

if [[ "$MODE" == "list" ]]; then
    echo "Golden dates (${#GOLDEN_DATES[@]}):"
    for d in "${GOLDEN_DATES[@]}"; do echo "  $d"; done
    exit 0
fi

if [[ "$MODE" == "count" ]]; then
    python3 -c "
import json, glob
from collections import Counter
golden = [$(printf '"%s",' "${GOLDEN_DATES[@]}" | sed 's/,$//')]
cc, conc_c, ml_c = Counter(), Counter(), Counter()
picks_yes = 0
for date in golden:
    d = json.load(open(f'reports/review_{date}.json'))
    cl = d.get('cycle_label','')
    base = cl.split('第')[0] if '第' in cl else cl
    cc[base] += 1
    conc_c[d.get('concentration',{}).get('signal','none') or 'none'] += 1
    ml_c[d.get('mainline_state',{}).get('status','none') or 'none'] += 1
    if d.get('trade_plan',{}).get('picks',[]): picks_yes += 1
print(f'Total: {len(golden)} | Picks: {picks_yes}/{len(golden)}')
print(f'Cycle: {dict(cc)}')
print(f'CONC:  {dict(conc_c)}')
print(f'ML:    {dict(ml_c)}')
"
    exit 0
fi

# ── baseline 模式 ──
if [[ "$MODE" == "baseline" ]]; then
    mkdir -p "$BASELINE_DIR"
    SAVED=0; MISSING=0
    for DATE in "${GOLDEN_DATES[@]}"; do
        SRC="reports/review_${DATE}.json"
        if [[ -f "$SRC" ]]; then
            cp "$SRC" "$BASELINE_DIR/review_${DATE}.json"
            SAVED=$((SAVED+1))
        else
            echo "  ⚠ $DATE: review 不存在，跳过"
            MISSING=$((MISSING+1))
        fi
    done
    echo "基线已保存: $SAVED 个, 跳过 $MISSING 个 → $BASELINE_DIR/"
    exit 0
fi

# ── run / validate 模式 ──
echo "[$(date)] === Golden set 开始 (${#GOLDEN_DATES[@]} dates, mode=$MODE) ===" | tee -a "$LOG"

OK=0; FAIL=0; TOTAL=${#GOLDEN_DATES[@]}; COUNT=0; ERRORS=()

for DATE in "${GOLDEN_DATES[@]}"; do
    COUNT=$((COUNT+1))
    
    if [[ "$MODE" == "validate" && -f "$BASELINE_DIR/review_${DATE}.json" ]]; then
        # 跑 review
        if python3 run_review.py "$DATE" --force --skip-download >> "$LOG" 2>&1; then
            # 对比基线
            DIFF=$(python3 << PYEOF
import json
old = json.load(open("$BASELINE_DIR/review_${DATE}.json"))
new = json.load(open("reports/review_${DATE}.json"))
issues = []
if old.get("cycle_label") != new.get("cycle_label"):
    issues.append(f"cycle: {old.get('cycle_label')} → {new.get('cycle_label')}")
op = len(old.get("trade_plan",{}).get("picks",[]))
np_ = len(new.get("trade_plan",{}).get("picks",[]))
if op != np_:
    issues.append(f"picks: {op} → {np_}")
os = set(p.get("strategy","") for p in old.get("trade_plan",{}).get("picks",[]))
ns = set(p.get("strategy","") for p in new.get("trade_plan",{}).get("picks",[]))
if os != ns:
    issues.append(f"strategies: {os} → {ns}")
# total_position
ot = old.get("trade_plan",{}).get("total_position",0)
nt = new.get("trade_plan",{}).get("total_position",0)
if ot != nt:
    issues.append(f"total_pos: {ot} → {nt}")
print("; ".join(issues) if issues else "OK")
PYEOF
)
            if [[ "$DIFF" == "OK" ]]; then
                echo "  [$COUNT/$TOTAL] $DATE ✓"
            else
                echo "  [$COUNT/$TOTAL] $DATE ⚠ $DIFF"
                ERRORS+=("$DATE: $DIFF")
            fi
            OK=$((OK+1))
        else
            echo "  [$COUNT/$TOTAL] $DATE ✗ FAIL"
            ERRORS+=("$DATE: run_review failed")
            FAIL=$((FAIL+1))
        fi
    else
        # 普通 run 模式（或 validate 无基线时）
        if python3 run_review.py "$DATE" --force --skip-download >> "$LOG" 2>&1; then
            echo "  [$COUNT/$TOTAL] $DATE ✓"
            OK=$((OK+1))
        else
            echo "  [$COUNT/$TOTAL] $DATE ✗ FAIL"
            ERRORS+=("$DATE: run_review failed")
            FAIL=$((FAIL+1))
        fi
    fi
done

echo ""
echo "[$(date)] === 完成: ok=$OK fail=$FAIL total=$TOTAL ===" | tee -a "$LOG"

if [[ ${#ERRORS[@]} -gt 0 ]]; then
    echo ""
    echo "问题列表:"
    for e in "${ERRORS[@]}"; do echo "  - $e"; done
    exit 1
fi
exit 0
