# 集中度数据修复 — KPH 数据时序问题

日期: 2026-05-18
状态: 修复中（全量复盘后台运行中）

---

## 一、问题发现

分析 2025 年 2 月亏损原因时，发现 review JSON 中的 `concentration` 字段在多个日期为空（signal="", ratio=0%, plate=""），但实际上这些日期的 KPH 精选 50 板块数据是完整的，强势池映射率也在 70%+。

## 二、根因

**Review 生成时间 vs KPH 数据回填时间存在时序差。**

| 时间点 | 事件 |
|--------|------|
| 2026-05-12 15:50 | 全量复盘生成所有 review JSON（327 天） |
| 2026-05-13 19:03 | KPH 历史数据回填（325 个文件，20250102~20260512） |

Review 生成时 KPH 数据还不存在，`_load_kph_data()` 返回 None，集中度信号全部跳过。
KPH 数据回填后 review 没有重跑，导致 review JSON 里的 concentration 数据为空。

## 三、验证

用当前 KPH 数据重算 2025-02-06 的集中度：44%（人工智能），但 review 记录为 0%。
确认是数据时序问题而非代码逻辑问题。

### 新 review 验证（带 prev_state 链）

对 20250910~20251015 共 20 个工作日进行验证，使用正确的 `prev_state` 链调用 `detect_concentration_signal()`，结果 20/20 全部匹配：

| 日期 | 信号 | 板块 | 集中度 |
|------|------|------|--------|
| 09/10 | CONC_EARLY | 通信 | 0% |
| 09/11 | CONC_WATCH | 通信 | 40% |
| 09/12 | CONC_EARLY | 芯片 | 30% |
| 09/15 | CONC_EARLY | 机器人概念 | 11% |
| 09/18 | CONC_CONTRARIAN | 机器人概念 | 50% |
| 09/23 | CONC_CONTRARIAN | 芯片 | 75% |
| 09/24 | CONC_STRONG | 芯片 | 67% |
| 10/09 | CONC_WATCH | 芯片 | 57% |
| 10/13 | CONC_WATCH | 核电 | 30% |

信号类型、板块名、集中度比例全部正确。

## 四、修复方案

重跑全量复盘，使用最新 KPH 数据重新计算集中度信号。

```bash
cd /opt/stock-review && nohup bash rerun_full_review.sh --skip-download --force --html > /var/log/stock-review-rerun.log 2>&1 &
```

参数说明：
- `--skip-download`: 跳过 CSV 下载，用已有数据
- `--force`: 强制重算，忽略 meta 缓存
- `--html`: 生成 HTML 图表报告

## 五、注意事项

1. `detect_concentration_signal()` 依赖 `prev_state` 参数（前日信号状态），用于 WATCH→CONFIRM 晋级判断。单日重算时需提供正确的前日状态链
2. KPH 数据覆盖 50 个板块 × 50 只个股 = 1031 只唯一股票，强势池映射率平均 82%
3. CONC_EARLY 信号不依赖集中度，直接取 KPH #1 板块检查连板高度
4. 全量复盘耗时约 60-90 分钟，flock 锁防止重复运行

---

*创建时间: 2026-05-18 00:41*
