# 2026-06-08 MainlineTracker CONC_EARLY 维持 CONFIRMED 机制修复 + 数据驱动补充

## 状态：✅ 已修复，全量复盘进行中

---

## 一、问题发现

回测结果（修复前）：NAV -6.33%，238笔交易中 219笔为 mainline_confirmed。

**根因分析**：
- CONC_EARLY 信号出现 319/344天（92.7%），覆盖所有板块
- `_transition()` 中 `CONFIRMED + EARLY → CONFIRMED`，导致 CONFIRMED 成为"永久状态"
- CONFIRMED 连续最长 26天（机器人概念），平均 6.6天
- 41.6% 的 CONFIRMED 状态最后信号仅 CONC_EARLY（弱信号）

**问题**：不同板块的 CONC_EARLY 不应该维持 CONFIRMED 状态。

---

## 二、修复方案

### Fix 1: EARLY 不再维持 CONFIRMED（mainline_tracker.py）

```python
# 修复前：
elif signal in EARLY_SIGNALS:
    if current == CONFIRMED:
        return CONFIRMED  # ← CONC_EARLY 也维持 CONFIRMED
    return CANDIDATE

# 修复后：
else:
    return current  # EARLY 不改变任何状态
```

### Fix 2: degraded_days 计数逻辑（mainline_tracker.py）

```python
# 修复前：
degraded_days=0,  # 有信号就归零

# 修复后：
degraded_days=(
    0 if sig.signal in CONFIRMED_SIGNALS
    else (0 if _calc_pool_avg_ret(prev.mainline_pool, today_prices or {}) is not None
          and _calc_pool_avg_ret(prev.mainline_pool, today_prices or {}) > DEGRADED_AVG_RET_THRESHOLD
          else prev.degraded_days + 1)
),
```

### Fix 3: 数据驱动机制补充（mainline_tracker.py + review_new.py）

新增 `_calc_pool_avg_ret()` 函数，计算主线池平均涨幅：
- pool 均涨 > 3%（DEGRADED_AVG_RET_THRESHOLD）→ degraded_days 重置
- pool 均涨 ≤ 3% → degraded_days++
- 与 `scripts/pure_mainline_v4.py` 回测脚本逻辑对齐

**review_new.py**：构建 `_today_prices` 字典传入 tracker.update()。

---

## 三、修改文件

| 文件 | 改动 | 备份 |
|------|------|------|
| `quant/mainline_tracker.py` | Fix 1 + Fix 2 + Fix 3 | `.bak_20260608_early_fix` + `.bak_20260608_pool_ret` |
| `quant/review_new.py` | 传入 today_prices | `.bak_20260608_pool_ret` |

---

## 四、验证

| 测试 | 结果 |
|------|------|
| pytest (51/51) | ✅ 全部通过 |
| 黄金集 validate (26/26) | ✅ 全部通过，0 差异 |

### 修复前差异（仅 Fix 1，无 pool ret）：
- 20250124: total_pos 72→54（人工智能 CONC_EARLY 不再维持 CONFIRMED）
- 20250127: total_pos 27→18（同上）

### 修复后（Fix 1 + Fix 2）：
- 26/26 全部一致，pool ret 机制补充了 EARLY 的降级空白

---

## 五、V4 一致性验证

| V4 状态转移 | 实现 | 状态 |
|------------|------|------|
| CANDIDATE + CONFIRMED信号 → CONFIRMED | ✅ | |
| CANDIDATE + EARLY → CANDIDATE | ✅ | |
| CANDIDATE + 无信号 → 退出 | ✅ | |
| CONFIRMED + CONFIRMED信号 → reset degraded_days | ✅ | |
| CONFIRMED + EARLY → degraded_days++（pool ret 检查） | ✅ | 新增 |
| CONFIRMED + 无信号≤3天 → CONFIRMED | ✅ | |
| CONFIRMED + 无信号>3天 → DEGRADED | ✅ | |
| DEGRADED + CONFIRMED信号 → CONFIRMED（复活） | ✅ | |
| DEGRADED + EARLY → DEGRADED（不复活） | ✅ | |

---

## 六、待办

| # | 任务 | 状态 |
|---|------|------|
| 1 | 全量复盘（344天） | 🔄 后台运行中 |
| 2 | 回测验证修复效果 | 待复盘完成 |
| 3 | 更新 CHANGELOG.md | 待完成 |

---

*记录时间: 2026-06-08 18:40*
*验证: pytest 51/51 passed, golden 26/26 passed*
