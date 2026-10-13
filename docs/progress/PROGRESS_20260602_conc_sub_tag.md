# 2026-06-02 CONC 信号次级板块标注

## 状态：✅ 已完成

---

## 一、背景

CONC 信号输出板块名（如"芯片"）粒度太粗，无法区分当天资金聚焦在哪个细分方向。需要在 CONC 信号后括号备注最强次级板块（如"芯片(存储)"）。

### 数据链路

```
CONC 信号触发 → plate="芯片"
    → 从 KPH 精选50 该板块股票的 sector_tag 统计
    → 评分 = 涨停数×2 + 平均涨幅
    → sub_tag="存储"
    → 报告展示: 芯片(存储)
```

---

## 二、数据源分析

### 板块数据源梳理

| 数据源 | 结构 | 二级标签 | 用途 |
|--------|------|---------|------|
| `data/kph_sectors/*.json`（每日KPH精选50） | 板块→股票 | ✅ `tags`(690个) + `sector_tag`(101个) | **基准数据源** |
| `data/kph_jingxuan_full.json` | 概念→成分股 | 原无，已补充 `tags` | 全量成分股映射 |
| `data/kph_industry_full.json` | 行业→成分股 | 无 | 行业映射 |
| `data/kaipanhong260508.json`（已废弃） | 板块→股票 | ✅ `tags`(653个) | 源数据 |
| `data/sub_plate_stocks.json`（已废弃） | tag→成分股 | ✅ `tag`+`theme`(80主题538tag) | 旧次级板块映射 |

### tags vs sector_tag

| 字段 | 含义 | 问题 |
|------|------|------|
| `tags` | 股票的所有标签（一级+二级混杂） | 会混入其他一级板块名（如芯片股带"通信"tag） |
| `sector_tag` | 股票在本板块内的细分标签 | ✅ 精准，如芯片股的 sector_tag="存储" |

**结论**：用 `sector_tag` 而非 `tags`。

---

## 三、方案设计

### 核心算法

```
评分 = 涨停数 × 2 + 平均涨幅
```

- 涨停是强信号，每1个涨停权重等效于2%平均涨幅
- 均涨拉开日常差距，涨停拉开爆发日差距
- 两个维度均衡影响

### 涨停判定

```python
is_zt = bool(limit_tag) or change_pct >= 9.9
```

### 实测效果（20260528 芯片板块）

| 子板块 | 涨停 | 均涨 | 评分 | 个股 |
|--------|:----:|-----:|-----:|------|
| 半导体设备 | 2 | +20.0% | 24.0 | XD杭可科, 光智科技 |
| 光刻胶 | 1 | +20.0% | 22.0 | 怡达股份 |
| 存储 | 4 | +12.1% | 20.1 | 深科达, 西安奕材, 汇成股份 |
| 靶材 | 2 | +11.4% | 15.4 | 阿石创, 有研新材 |

---

## 四、实施步骤

### Step 1：kph_jingxuan_full.json 补充 tags 字段

- 从 `kaipanhong260508.json` 提取 `{stock_code → tags}` 映射
- 覆盖率：58540/58923 = 99.3%
- 一次性脚本，不入库

### Step 2：anchor_monitor.py 新增 compute_sub_tag 函数

- 位置：第 363 行（`_get_plate_change` 之后，`compute_concentration` 之前）
- 输入：`plate` + `kph_data`
- 输出：最强次级 tag 字符串
- 算法：按 sector_tag 分组，评分 = 涨停数×2 + 平均涨幅

### Step 3：review_new.py 存储 sub_tag

- 位置：第 734 行（`sec['concentration']` 构建后）
- 存入 `sec['concentration']['sub_tag']`

### Step 4：report_templates.py 展示拼接

- 4 处展示逻辑：
  1. `top1_name`（洞察3主线判断）
  2. `ml_name`（主线追踪状态）
  3. `mainline_name`（一超多强主线板块）
  4. `display_name`（主题主线确认展示）
- 拼接格式：`板块名(sub_tag)`

---

## 五、修改文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `data/kph_jingxuan_full.json` | 修改 | 新增 `tags` 字段（一次性） |
| `quant/anchor_monitor.py` | 修改 | 新增 `compute_sub_tag()` 函数 |
| `quant/review_new.py` | 修改 | 存储 `sub_tag` 到 concentration |
| `quant/report_templates.py` | 修改 | 4处展示拼接 sub_tag |
| `quant/anchor_monitor.py.bak_20260602_sub_tag` | 新建 | 修改前备份 |

---

## 六、验证

| 验证项 | 结果 |
|--------|------|
| pytest test_smoke + test_core_logic | 51/51 passed |
| 20260528 单日复盘 | ✅ sub_tag=存储, 报告显示"集中度20%(存储)" |

---

## 七、后续方向

| # | 任务 | 说明 |
|---|------|------|
| 1 | CONC阈值重测（方案一） | 用2025全年主线标签回测不同阈值组合 |
| 2 | CONC+KPH混合信号（方案二） | 基于方案一结果设计 |
| 3 | 主线确认量化定义 | P0 待讨论 |

---

*工作时间: 2026-06-02 16:56 ~ 17:47*
