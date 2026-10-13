# 2026-06-10 工作进度记录（Tracker降级逻辑修复）

## 状态：第一步完成，第二步待执行

---

## 一、背景

全量复盘跑完后，检查2025年1月回测发现 tracker 降级逻辑有误：
- 算力板块01/09失去CONC信号后，tracker仍然保持CONFIRMED到01/14才降级
- 期间01/10买入华塑科技、海得控制，均SL-5%止损亏损

## 二、根因分析

### 问题代码（mainline_tracker.py）

两个分支处理不一致：

- 分支A（有信号）：检查信号类型 + 池子表现
- 分支B（无信号）：直接 degraded_days+1，不检查池子表现

### 问题本质

分支B只看有没有信号，不看池子涨跌，变成了纯计时器。
正确逻辑：CONFIRMED之后，无论有没有信号，都看昨日池子在今日的表现。

### 对照组

pure_mainline_v4.py（回测脚本）已有正确逻辑：
- calc_pool_avg_ret() 用昨日收盘价和今日收盘价算日收益
- DEGRADED_EXIT_DAYS = 2

---

## 三、修复方案（第一步：2个文件）

### 文件1：quant/mainline_tracker.py

改动1：新增 _get_prev_date 辅助函数
改动2：修复 _calc_pool_avg_ret 函数
  - 原来：用 cum_ret（强股池的5日累计收益）
  - 修复后：用 prev_prices 和 today_prices 计算日收益

改动3：统一CONFIRMED降级逻辑
  - 不再区分有信号/无信号两个分支
  - 统一用池子反馈判断
  - 池子均涨>3%: degraded_days=0
  - 池子均涨<=3%: degraded_days+1
  - 超过MAINLINE_EXIT_DAYS: 降级DEGRADED

### 文件2：config/strategy_rules.py

MAINLINE_EXIT_DAYS: 3 改为 2

---

## 四、验证

### pytest
136/136 passed

### 2025年1月回测（pure_mainline_v4.py）
结果不变（+13.07%），因为回测脚本本身已有正确逻辑。
改动只影响 review JSON 生成，不影响回测。

### 算力示例（修复后预期）

- 01/08: 池子均涨+8.5%, degraded=0, CONFIRMED, 买
- 01/09: 池子均涨-2.1%, degraded=1, CONFIRMED, 不买（第二步）
- 01/10: 池子均涨-7.9%, degraded=2, DEGRADED, 不买
- 01/13: 已删除

---

## 五、待执行：第二步（买入过滤）

### 改动文件：pure_mainline_v4.py + trade_plan.py

在CONFIRMED/CANDIDATE买入前加判断：
  有degraded_days计数（>0）不买该板块

### 效果
- degraded_days > 0 时，不买入该板块的任何股票
- 避免在板块走弱时还追高买入

---

## 六、修改文件清单

| 文件 | 改动类型 | 备份 |
|------|---------|------|
| quant/mainline_tracker.py | 降级逻辑修复 | mainline_tracker.py.bak_20260610_pool_fix |
| config/strategy_rules.py | MAINLINE_EXIT_DAYS 3改2 | strategy_rules.py.bak_20260610_pool_fix |

---

## 七、全量复盘状态

- 最后一次全量复盘：6月9日 23:35 完成
- 结果：346天，成功267，失败79（SyntaxError，已修复）
- 失败日期：1月2日到5月28日散布（代码清理期间引入的bug）
- 待重跑：需要等tracker修复后重跑全量

---

*记录时间: 2026-06-10 08:37*
*pytest: 136/136 passed*
*回测: +13.07%（不变，回测脚本逻辑本身正确）*

## 八、全量重跑（后台）

- 启动时间：2026-06-10 08:44
- 原因：上次重跑79天失败（SyntaxError），代码已修复后重跑
- 预计完成：10:00~11:00
- 状态：进行中
