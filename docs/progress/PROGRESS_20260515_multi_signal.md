# 多信号并存重构 — 进度记录

日期: 2026-05-15
状态: ✅ 已完成

---

## 一、改动清单

### 1.1 config/strategy_rules.py
- 新增 `MAX_TOTAL_POSITION = 80`（多信号累加总仓位上限）
- 备份: `config/strategy_rules.py.bak_20260515_multi_signal`

### 1.2 quant/anchor_monitor.py
- 新增 `detect_all_signals()` 函数
- 支持检测所有活跃信号（主信号 + 次级板块信号）
- 不修改原 `detect_concentration_signal()` 函数签名
- 备份: `quant/anchor_monitor.py.bak_20260515_multi_signal`

### 1.3 quant/review_new.py
- 导入 `detect_all_signals`
- 在 `sec['concentration']` 存储后新增 `sec['active_signals']` 列表
- 格式: `[{plate, signal, signal_level, ratio, lianban, kph_rank}]`
- 备份: `quant/review_new.py.bak_20260515_multi_signal`

### 1.4 quant/position.py
- 在 5.4 节（EARLY cap）后新增 5.4.1 节（多信号仓位累加）
- 当 `active_signals` 数量 > 1 时，累加各信号对应仓位
- 上限为 `MAX_TOTAL_POSITION`（80%）
- 备份: `quant/position.py.bak_20260515_multi_signal`

### 1.5 quant/trade_plan.py
- 新增多板块升级逻辑（遍历 `active_signals`）
- 向 `select_stocks` 传递 `active_signals` 参数
- 备份: `quant/trade_plan.py.bak_20260515_multi_signal`

### 1.6 quant/selector.py
- 新增多板块 EARLY 路径
- 当多个 EARLY 信号并存时，遍历各板块聚合选股结果
- 去重处理避免同一股票被重复选中
- 备份: `quant/selector.py.bak_20260515_multi_signal`

---

## 二、验证结果

| 验证项 | 结果 |
|--------|------|
| pytest | 85/85 passed ✅ |
| 单日复盘 (20250108) | 成功 ✅ |
| 多信号检测 (20250108) | 2个并存信号 ✅ |
| 多信号检测 (20250109) | 2个并存信号 ✅ |

### 多信号验证详情

```
20250108:
  CONC_EARLY: 机器人概念 (rank=1, lianban=3, ratio=10%)
  CONC_EARLY: 算力 (rank=2, lianban=8, ratio=40%)

20250109:
  CONC_EARLY: 通信 (rank=1, lianban=3, ratio=22.2%)
  CONC_EARLY: 算力 (rank=3, lianban=8, ratio=33.3%)
```

---

## 三、架构原则检查

| 原则 | 检查结果 |
|------|---------|
| 单一修改点 | ✅ 6个文件各自独立改动 |
| 禁止反向依赖 | ✅ config 不 import 业务模块 |
| 策略函数只做计算 | ✅ detect_all_signals 是纯计算 |
| 修改前检查三件事 | ✅ 方案已记录 |

---

## 四、遗留项

| 项 | 说明 | 优先级 |
|---|------|--------|
| CONC_ 阈值迁移 | anchor_monitor.py 中的阈值应迁到 config/strategy_rules.py | P2 |
| 二波机制 | confirmed → 信号消失 → dormant → 重新触发，待设计 | P2 |
| 多信号回测验证 | 需构造多信号场景的完整回测 | P1 |

---

*最后更新: 2026-05-15 12:45*
