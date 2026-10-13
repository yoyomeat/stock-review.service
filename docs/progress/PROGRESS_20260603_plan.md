# 2026-06-03 工作进度记录（下午续 — 主线确认机制修改方案）

## 状态：方案待确认

---

## 一、工作目标

基于EARLY+龙头池D+1反馈的确认方案，设计主线确认机制代码修改方案。

---

## 二、现有主线确认机制分析

### 2.1 信号检测（`detect_concentration_signal`，anchor_monitor.py:474）

优先级从高到低：

| 优先级 | 信号 | 条件 | 确认状态 |
|:---:|------|------|---------|
| 1 | CONC_CONTRARIAN | ratio≥50% + 板块跌 + sent<50 | confirmed |
| 2 | CONC_STRONG | ratio≥60% + KPH#1 | confirmed |
| 3 | CONC_CONFIRM | ratio≥50% + KPH#1 + 连板≥4 | confirmed |
| 4 | EARLY→WATCH升级 | 前日EARLY + 今日ratio≥30% + 连板≥3 | candidate |
| 5 | CONC_EARLY | KPH#1 + 连板≥3（无ratio要求） | early |
| 6 | WATCH→CONFIRM晋级 | 前日WATCH + (ratio≥50% 或 ratio↑10%) + KPH#1 | confirmed |
| 7 | CONC_WATCH | ratio≥40% + KPH TOP3 + 连板≥1 | candidate |

### 2.2 状态映射（`build_mainline_info`，anchor_monitor.py:1175）

| 信号 | status | signal_text | signal_level |
|------|--------|-------------|-------------|
| CONFIRM | confirmed | ✅ 主线确认：{plate}（集中度 TOP1 连板） | ok |
| STRONG | confirmed | ✅ 主线强确认：{plate}（集中度 TOP1） | ok |
| CONTRARIAN | confirmed | ✅ 冰点抱团确认：{plate}（集中度 逆势） | ok |
| EARLY | early | ⚡ 题材启动：{plate}（连板 TOP1） | early |
| WATCH | candidate | 🔍 主线候选：{plate}（集中度 观察中） | observe |
| 无信号+前日confirmed | divergence | ⚠️ 主线分歧：{plate}（集中度降至） | warn |
| 无信号+前日candidate | none | ❌ 散乱行情 | — |

### 2.3 ConcentrationState 数据结构（anchor_monitor.py:169）

```python
@dataclass
class ConcentrationState:
    plate: str = ''             # 板块名
    ratio: float = 0            # 集中度
    kph_rank: int = 999         # KPH排名
    lianban: int = 0            # 板块内连板股数
    signal: str = ''            # CONC_WATCH / CONC_CONFIRM / CONC_STRONG / CONC_CONTRARIAN / CONC_EARLY
    watch_date: str = ''        # WATCH 触发日期
    watch_ratio: float = 0      # WATCH 时的集中度
    plate_change: float = 0     # 板块当日涨跌幅
    plate_stocks: dict          # {plate_name: [code1, code2, ...]} 强势池板块分布
```

### 2.4 核心问题（数据分析验证）

| 问题 | 数据证据 |
|------|---------|
| CONC_STRONG/CONFIRM/CONTRARIAN是滞后信号 | TOP2≥+5%比例88%/67%，板块已爆发到中段 |
| CONC_EARLY只标记不验证 | status='early'，无D+1反馈机制 |
| 缺少"用钱投票"的确认路径 | EARLY触发后直接等下一天信号，不看龙头池实际表现 |
| mainline_state无记忆 | confirmed被挤掉后回来从early重来 |

---

## 三、数据分析结果

### 3.1 数据规模

- review文件：338天（2025-01-02 ~ 2026-05-29）
- KPH文件：337天（2025-01-02 ~ 2026-05-28）
- CONC_EARLY信号：150个（有KPH龙头池数据）

### 3.2 龙头池构建方法

```
D日CONC_EARLY触发
  → plate_stocks[plate]（KPH板块成分股，来自CONC的plate_map）
  ∩ strong_pool（全市场5日涨幅TOP10）
  = 龙头池
```

### 3.3 D+1确认阈值（150个EARLY信号，D+1+D+2累计表现）

#### 单指标

| D+1 TOP2阈值 | N | 占比 | D+1+D+2均值 | 胜率 |
|:---:|:---:|:---:|:---:|:---:|
| ≥0% | 109 | 73% | +5.92% | 72% |
| ≥5% | 70 | 47% | +8.41% | 79% |
| **≥7%** | **52** | **35%** | **+10.52%** | **90%** |
| ≥10% | 35 | 23% | +11.29% | 91% |

| D+1中位数阈值 | N | 占比 | D+1+D+2均值 | 胜率 |
|:---:|:---:|:---:|:---:|:---:|
| ≥0% | 73 | 49% | +8.18% | 79% |
| ≥3% | 57 | 38% | +9.75% | 84% |
| **≥5%** | **43** | **29%** | **+11.47%** | **88%** |
| **≥7%** | **34** | **23%** | **+12.63%** | **91%** |

#### 双重确认：中位数 + 均值

| 中位数 | 均值 | N | 占比 | D+1+D+2均值 | TOP2均值 | 胜率 |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| ≥+0% | ≥+7% | 37 | 25% | +11.96% | +14.16% | 92% |
| ≥+3% | ≥+7% | 36 | 24% | +12.16% | +14.42% | 92% |
| **≥+5%** | **≥+7%** | **34** | **23%** | **+12.68%** | **+14.79%** | **91%** |
| **≥+7%** | **≥+7%** | **29** | **19%** | **+13.62%** | **+15.82%** | **93%** |
| ≥+10% | ≥+7% | 21 | 14% | +13.75% | +16.42% | 95% |

### 3.4 结论

**推荐阈值：D+1龙头池中位数≥+7% 且 均值≥+7%**
- 覆盖率：19%（29/150个EARLY触发）
- 胜率：93%（D+1+D+2累计正收益）
- 均值：+13.62%（D+1+D+2累计）
- 含义：板块内大部分票都在涨，且涨幅不低 = "用钱投票"的验证

---

## 四、修改方案

### 4.1 核心思路

新增 **`CONC_EARLY_CONFIRMED`** 信号：EARLY触发后的D+1龙头池反馈验证通过 → 直接confirmed。

这是**主确认信号**，区别于STRONG/CONFIRM/CONTRARIAN的**升级信号**定位。

### 4.2 新信号定义

```
CONC_EARLY_CONFIRMED:
  前置条件：D日触发 CONC_EARLY
  验证条件：D+1龙头池中位数≥+7% 且 均值≥+7%
  确认状态：confirmed
  确认方法：early_feedback
```

### 4.3 信号优先级调整

| 优先级 | 信号 | 确认状态 | 角色 |
|:---:|------|---------|------|
| 1 | CONC_CONTRARIAN | confirmed | 升级信号 |
| 2 | CONC_STRONG | confirmed | 升级信号 |
| **3** | **CONC_EARLY_CONFIRMED** | **confirmed** | **主确认信号** |
| 4 | CONC_CONFIRM | confirmed | 升级信号 |
| 5 | EARLY→WATCH升级 | candidate | 观察 |
| 6 | CONC_EARLY | early | 候选 |
| 7 | WATCH→CONFIRM晋级 | confirmed | 确认 |
| 8 | CONC_WATCH | candidate | 观察 |

### 4.4 需要修改的文件

#### 文件1：`config/strategy_rules.py`

新增配置常量：
```python
# CONC_EARLY 龙头池确认阈值
EARLY_CONFIRM_MED_THRESHOLD = 7    # D+1龙头池中位数阈值（%）
EARLY_CONFIRM_AVG_THRESHOLD = 7    # D+1龙头池均值阈值（%）
```

#### 文件2：`quant/anchor_monitor.py`

**修改1：ConcentrationState 新增字段**
```python
@dataclass
class ConcentrationState:
    # ... 现有字段 ...
    leader_pool: list = field(default_factory=list)  # 龙头池代码列表（EARLY确认用）
```

**修改2：detect_concentration_signal 新增验证逻辑**

在CONC_EARLY信号返回前，记录龙头池：
```python
# CONC_EARLY 返回时，构建龙头池并记录
leader_pool = _build_leader_pool(plate, plate_map, pool)
return ConcentrationState(
    # ... 现有字段 ...
    leader_pool=leader_pool,
)
```

**修改3：新增 verify_early_feedback 函数**
```python
def verify_early_feedback(
    prev_conc: ConcentrationState,
    d1_csv_rets: dict[str, float],  # {code: change_pct}
    med_threshold: float = 7,
    avg_threshold: float = 7,
) -> bool:
    """
    验证D日EARLY信号的D+1龙头池反馈
    
    Args:
        prev_conc: D日的ConcentrationState（含leader_pool）
        d1_csv_rets: D+1的个股涨跌幅 {code: pct}
        med_threshold: 中位数阈值（%）
        avg_threshold: 均值阈值（%）
    
    Returns:
        True = 验证通过，可确认主线
    """
    if not prev_conc.leader_pool:
        return False
    
    rets = [d1_csv_rets[c] for c in prev_conc.leader_pool if c in d1_csv_rets]
    if not rets:
        return False
    
    rets_sorted = sorted(rets, reverse=True)
    median = rets_sorted[len(rets_sorted) // 2]
    avg = sum(rets) / len(rets)
    
    return median >= med_threshold and avg >= avg_threshold
```

**修改4：新增 build_leader_pool 函数**
```python
def build_leader_pool(
    plate: str,
    plate_stocks: dict[str, list[str]],
    pool: list[PoolStock],
) -> list[str]:
    """
    从strong_pool中筛选属于CONC板块的个股，构建龙头池
    
    Args:
        plate: CONC板块名
        plate_stocks: {plate_name: [code1, code2, ...]}
        pool: 强势股池
    
    Returns:
        龙头池代码列表
    """
    plate_codes = set(plate_stocks.get(plate, []))
    sp_codes = set(s.code for s in pool)
    return list(plate_codes & sp_codes)
```

**修改5：build_mainline_info 新增 CONC_EARLY_CONFIRMED 处理**
```python
def build_mainline_info(conc_state, kph_data, prev_meta, date_str):
    # ... 现有逻辑 ...
    
    # 新增：CONC_EARLY_CONFIRMED 处理
    if conc_state.signal == 'CONC_EARLY_CONFIRMED':
        status = 'confirmed'
        confirm_date = date_str
        consecutive_top5 = 1
        confirm_method = 'early_feedback'
        signal_text = f'✅ 龙头确认：{plate}（D+1龙头池验证通过）'
        signal_level = 'ok'
```

#### 文件3：`quant/review_new.py`

concentration dict 新增字段：
```python
'leader_pool': conc_state.leader_pool,  # 龙头池代码列表
```

### 4.5 数据流

```
D日:
  detect_concentration_signal()
    → CONC_EARLY
    → build_leader_pool(plate, plate_stocks, strong_pool)
    → 存入 ConcentrationState.leader_pool
    → 写入 review JSON: concentration.leader_pool

D+1日:
  主流程加载D日review → 读取 prev_conc
  加载D+1 CSV → d1_csv_rets
  verify_early_feedback(prev_conc, d1_csv_rets)
    → 中位数≥7% 且 均值≥7%？
    → 是 → 返回 CONC_EARLY_CONFIRMED → confirmed
    → 否 → 返回 None → 继续正常 detect_concentration_signal 流程
```

### 4.6 验证方式

1. `python3 -m pytest tests/test_smoke.py tests/test_core_logic.py` — 确保不破坏现有逻辑
2. 重跑5天review验证新信号正确触发
3. 全量复盘验证确认率和收益

---

## 五、待确认项

| # | 问题 | 当前方案 |
|---|------|---------|
| 1 | 确认阈值 med≥+7, avg≥+7 | 数据支持，19%覆盖率，93%胜率 |
| 2 | 龙头池N只有1只时怎么处理 | 1只票的中位数=均值，仍按阈值判断 |
| 3 | CONC_EARLY_CONFIRMED优先级位置 | 放在STRONG之后、CONFIRM之前（第3位） |
| 4 | STRONG/CONFIRM作为升级信号的具体规则 | 待讨论 |
| 5 | 维持/回归/退出规则 | 沿用上午讨论的方案 |
| 6 | 全量复盘验证 | 待代码实现后执行 |

---

## 六、待办

| # | 任务 | 优先级 | 状态 |
|---|------|:---:|------|
| 1 | 确认阈值和方案定稿 | P0 | 待用户确认 |
| 2 | 代码实现（anchor_monitor.py + strategy_rules.py + review_new.py） | P0 | 待方案定稿 |
| 3 | pytest验证 | P0 | 待代码实现 |
| 4 | 重跑5天review验证 | P0 | 待pytest通过 |
| 5 | 全量复盘验证（338天） | P1 | 待重跑验证 |
| 6 | 维持/回归/退出规则设计 | P1 | 沿用上午方案 |
| 7 | STRONG/CONFIRM升级信号规则 | P1 | 待讨论 |

---

*记录时间: 2026-06-03 11:02 ~ 11:08*
