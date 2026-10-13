# 2026-05-25 Strength Screener 编码进度

日期: 2026-05-25
状态: **编码进行中，G3 已验证通过，G1/G2 待修复**

---

## 一、已完成

### 1.1 文件修改清单

| 文件 | 操作 | 状态 |
|------|------|------|
| `config/strategy_rules.py` | 修改 | ✅ 新增 `STRENGTH_SCREENER` 配置块 |
| `config/strategy_rules.py` | 修改 | ✅ 新增 `strength_screener` 退出规则 (`stop_none, hold=1`) |
| `quant/strategies/screeners/strength.py` | **新建** | ✅ G1/G2/G3 screener 实现 |
| `quant/strategies/screeners/__init__.py` | 修改 | ✅ 注册 `select_strength` 到 `SCREENER_REGISTRY` |
| `quant/strategies/strength.py` | **重写** | ✅ EntryGen 支持 path 分支 (open买 vs 涨停追入) |

### 1.2 测试结果

| 测试 | 结果 |
|------|------|
| `pytest tests/test_smoke.py` | ✅ 10/10 通过 |
| G3 (20260108 Day9) | ✅ 返回 3 只候选 |
| G1 (20260407 Day1) | ⚠️ 返回 0 只（原因已确认，见下） |
| G2 (20250910 Day4) | ⚠️ 返回 0 只（原因已确认，见下） |

---

## 二、问题分析

### 2.1 G1 返回 0 只

**原因**: Day 1 时 conc_plate 为空或 CONC 板块内 2连板 + TO<3% 的股票极少。

数据验证（20260407 Day1, conc=医药）:
- CONC 板块 10cm 涨停: 14 只
- 其中 2连板: 仅 2 只（600488 TO=16.1%, 002980 TO=20.5%）
- 2连板 + TO<3%: 0 只

**结论**: Day 1 的 2连板 + TO<3% 确实非常稀缺。G1 分析中 26 只候选大部分来自 Day 2。Screener 逻辑正确，无需修改。

### 2.2 G2 返回 0 只

**原因**: CONC 板块（通信）内的 10cm 涨停股都是首板（LB=1），2连板在其他 KPH 板块里。

数据验证（20250910 Day4, conc=通信）:
- CONC 板块 10cm 涨停: 11 只，全部 LB=1
- 全 KPH 2连板 + TO<5: 11 只，但都不在 CONC 板块
- KPH 精选50 只取 TOP50，2连板股可能不在其中

**结论**: Screener 的 `conc_codes` 过滤范围太窄。需要扩大搜索范围——不仅搜索 CONC 板块，还要搜索其他 KPH 板块中符合条件的股票。

### 2.3 G3 验证通过

G3 (20260108 Day9, conc=商业航天):
- 返回 3 只候选: 600783(LB3), 600869(LB3), 601106(LB2)
- 买入方式: D+1 open
- 持有天数: 1 天

---

## 三、待修复

### 3.1 G2 搜索范围扩大

当前逻辑: 只搜索 CONC 板块成分股（conc_codes）

修复方案: 如果 CONC 板块无候选，扩大到 KPH 全板块搜索 2连板 + TO<5 的股票

```
_select_g2():
  1. 先搜索 CONC 板块 → 有候选则返回
  2. 无候选 → 搜索全 KPH 板块中 2连板 + TO<5 的股票
  3. 排除 ST、20cm、EXCLUDED_PLATES
```

### 3.2 G1 搜索范围扩大

同理: 如果 CONC 板块无 2连板 + TO<3% 的股票，扩大到全 KPH 搜索

### 3.3 搜索范围扩大的风险

- 可能选到非主线板块的股票（alpha 来源不同）
- 需要验证扩大后的收益是否仍然正向
- 建议: 先验证再决定

---

## 四、下一步

| 优先级 | 任务 | 状态 |
|--------|------|------|
| P0 | 修复 G2 搜索范围 | 待执行 |
| P0 | 修复 G1 搜索范围 | 待执行 |
| P1 | 全量回测验证 | 待执行 |
| P2 | 更新 ARCHITECTURE.md | 待执行 |

---

*更新时间: 2026-05-25 20:33*

---

## 四、修复记录 (2026-05-25 20:45)

### 4.1 问题诊断

G1/G2 返回 0 候选的根本原因：**搜索范围局限于 CONC 板块**。

当 CONC 板块内没有符合条件的 2连板 股时，screener 直接返回空。但架构文档的板块分析口径要求：
- 板块分析统一用 KPH
- 个股归属从 KPH 取
- CONC 无候选时应扩大搜索范围

### 4.2 数据验证

| 梯度 | 修复前 0候选 | 修复后 0候选 | 改善 |
|------|:---------:|:---------:|------|
| G1 (Day 1-2) | 28/51 (55%) | **8/51 (16%)** | -71% |
| G2 (Day 3-6) | 11/50 (22%) | **6/50 (12%)** | -45% |
| G3 (Day 7+) | — | 3/23 (13%) | — |

剩余 0 候选均为 `plate=''`（CONC 板块为空），属数据层面正常空缺。

### 4.3 修改内容

文件: `quant/strategies/screeners/strength.py`

1. **新增 `_get_all_kph_codes(d_kph)` 辅助函数**：获取 KPH 全板块所有股票代码集合
2. **所有 `_select_g*` 函数增加 `d_kph` 参数**：修复 `_get_stock_name(code, None)` 导致 name 为空的 bug
3. **`select_strength()` 增加全 KPH fallback 逻辑**：CONC 无候选时自动扩大到全 KPH 搜索

搜索优先级：
```
CONC 板块 → 有候选返回
         → 无候选 → 全 KPH 板块 → 有候选返回
                              → 无候选 → 进入下一级梯度（G2打板/G3候补）
```

### 4.4 测试结果

| 测试 | 结果 |
|------|------|
| `pytest tests/test_smoke.py` | ✅ 10/10 通过 |
| `pytest tests/test_core_logic.py` | ✅ 38/38 通过 |
| G1 (20260407 Day1) | ✅ 1只（修复前 0只） |
| G2 (20250910 Day4) | ✅ 3只（修复前 0只） |
| G3 (20260108 Day9) | ✅ 3只（未变） |

### 4.5 备份

原文件备份: `quant/strategies/screeners/strength.py.bak_20260525`

---

*更新时间: 2026-05-25 20:45*
