# 2026-05-20 sector_score.py 数据源迁移到 KPH精选50

日期: 2026-05-20
状态: **完成，测试通过**

---

## 一、问题

sector_score.py 的三个底层函数读取 kaipanhong260508.json（旧数据），违反板块数据源铁律：
> 所有涉及板块的数据分析，必须以每日KPH精选50为唯一基准数据源
> 旧板块数据（kaipanhong260508.json等）→ 已废弃 → 严禁引用

影响链路：
kaipanhong260508.json → _load_plate_stocks() → aggregate_to_themes() → score_themes() → sector_v5.theme_top/resonance_top → 主线判断

## 二、修改范围

修改文件: 1个
- quant/sector_score.py
  - _load_plate_stocks()    ← 改读 KPH精选50
  - _load_stock_plates()    ← 改读 KPH精选50（逻辑不变，改注释）
  - _load_stock_to_themes() ← 改读 KPH精选50 + stock.tags + plate_to_theme

不修改:
- config/theme_mapping_v2.json（映射不变）
- quant/pipeline.py / trade_plan.py / backtest_engine.py（消费端不变）

## 三、改动详情

### _load_plate_stocks()
- 旧: 读 kaipanhong260508.json 的 plates[].stocks[].code + sub_plate_stocks.json
- 新: 读 data/kph_sectors/*.json 的 sectors[].stocks[].code
- 跨日聚合去重，每个板块合并所有日期的成分股

### _load_stock_to_themes()
- 旧: kaipanhong 板块名 → plate_to_theme → 主题
- 新: KPH板块名 → plate_to_theme → 主题 + stock.tags → plate_to_theme → 主题（补充）

### aggregate_to_themes()
- 注释更新，逻辑不变（自动使用新的底层函数）

## 四、验证结果

- tests/test_smoke.py: passed
- tests/test_core_logic.py: 48 passed
- sector_v5 输出对比（20260515）:
  - 旧 Top 1: 氟化工(95.0) → 新 Top 1: 北交专用设备(110.0)
  - 氟化工在两边都是 Top 级别，核心逻辑正确
  - 部分板块名因 plate_to_theme 缺失映射而以原名出现（如浙江）

## 五、数据对比

| | 旧（kaipanhong） | 新（KPH精选50） |
|---|---|---|
| 板块数 | 679 | 290 |
| 股票数 | 5,825 | 6,248 |
| 数据时间 | 2026-05-08 快照 | 每日更新 |

## 六、备份

- quant/sector_score.py.bak_20260520_kph_migration

---

*更新时间: 2026-05-20 12:10*
