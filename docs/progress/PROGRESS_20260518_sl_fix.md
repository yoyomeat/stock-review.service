# 2026-05-18 止损Bug修复 + 旧Style清除

日期: 2026-05-18
状态: 代码修改完成，测试通过，待全量回测验证

---

## 一、止损Bug修复

### 1.1 根因

`sl_type` 和 `sl_param` 在整条链路中**从未传递**：

```
ExitEngine.compute() → 输出 sl_type/sl_param ✅
    ↓
pipeline.py → 直接传递 exit_plan dict ✅（无需修改）
    ↓
trade_plan.py plan_to_pick() → 没写入 pick ❌
    ↓
pick dict → sl_type=None, sl_param=None ❌
    ↓
backtest_engine.py _bt_recompute_exit() → 只对 sl_type="stop_entry_pct" 重算
    ↓
结果：全部交易 sl_type=None，止损永远不基于actual_buy重算
```

### 1.2 影响

- 止损价基于预期买入价（如20.2）计算，不随实际买入价（如24.02）调整
- 实际止损幅度从设计的-5%变成-20%
- 四方达案例：-21%亏损本应在D+1就以-5%止损出场

### 1.3 修复方案（2个文件）

**文件1: `quant/trade_plan.py`**

4处修改：
1. pick初始化增加 `sl_type=''`, `sl_param=None`
2. plan_to_pick 中从 exit_plan 读取 sl_type/sl_param 写入 pick
3. recompute 后同步 sl_type/sl_param
4. _add_pick 中从 _pipeline_pick 拷贝 sl_type/sl_param

**文件2: `quant/exit_engine.py`**

recompute_for_buy_price 增加兜底逻辑：
- sl_type 为空但 stop_loss_pct 存在时，用 stop_loss_pct 重算
- 保证所有百分比类止损都能基于 actual_buy 重算

### 1.4 验证结果

| 检查项 | 结果 |
|--------|------|
| pytest | 48/48 passed ✅ |
| ExitEngine.compute 输出 sl_type | stop_entry_pct ✅ |
| plan_to_pick 传递 sl_type/sl_param | 正确传递 ✅ |
| recompute_for_buy_price 重算(actual=24.02) | stop_loss=22.82 (-5.0%) ✅ |
| 修复前（bug） | stop_loss=19.19 (-20.1%) ❌ |

**链路验证：**
```
ExitEngine.compute  → sl_type=stop_entry_pct, sl_param=-5
plan_to_pick        → pick.sl_type=stop_entry_pct, pick.sl_param=-5
recompute(actual=24.02) → stop_loss=22.82 (-5.0%) ✅
```

---

## 二、旧Style清除

### 2.1 迁移内容

| 旧值 (market_style) | 新值 (invest_style) | 天数 |
|---------------------|---------------------|------|
| 主升 | 主升 | 161 |
| 退潮 | 低迷 | 86 |
| 抱团 | 抱团 | 22 |
| 轮动 | 散乱 | 59 |

### 2.2 修改文件

**文件1: `config/strategy_rules.py`**

- 24处 `ctx.market_style` → `ctx.invest_style`
- 2处 `'退潮'` → `'低迷'`
- 2处 `'轮动'` → `'散乱'`

**文件2: `quant/context.py`**

- MarketContext 增加 `invest_style: str = ''` 字段

**文件3: `quant/trade_plan.py`**

- `_build_context` 函数增加 `invest_style` 参数
- MarketContext 创建时传入 `invest_style`
- 调用处增加 `invest_style = sty.get('invest_style', '')` 变量定义

### 2.3 验证结果

| 检查项 | 结果 |
|--------|------|
| pytest | 48/48 passed ✅ |
| strategy_rules.py 无 market_style 引用 | 0处 ✅ |
| MarketContext 有 invest_style 字段 | ✅ |
| _build_context 传递 invest_style | ✅ |

---

## 三、文件变更清单

| 文件 | 操作 | 备份 |
|------|------|------|
| quant/trade_plan.py | 修改：sl_type/sl_param传递 + invest_style参数 | .bak_20260518_sl_fix |
| quant/exit_engine.py | 修改：recompute_for_buy_price 兜底逻辑 | .bak_20260518_sl_fix |
| quant/context.py | 修改：增加 invest_style 字段 | — |
| config/strategy_rules.py | 修改：market_style → invest_style | .bak_20260518_style |
| quant/style.py | 无修改（invest_style 已在 calc_style 中计算） | .bak_20260518_style |

---

## 四、待办

| 步骤 | 内容 | 状态 |
|------|------|------|
| 1 | 止损bug修复 | ✅ 完成 |
| 2 | pytest 测试 | ✅ 48/48 passed |
| 3 | Style迁移 | ✅ 完成 |
| 4 | pytest 测试 | ✅ 48/48 passed |
| 5 | 清理回测缓存 | ✅ 已清理 |
| 6 | 全量回测对比 | ⏳ 待执行 |
| 7 | 更新 CHANGELOG | ⏳ 待执行 |

---

*更新时间: 2026-05-18 13:07*
