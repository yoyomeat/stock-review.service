# -*- coding: utf-8 -*-
"""patch16b: 前端 ipo.js —— 阈值表同步后端 + off-by-one 修正 + D1 三段式对齐"""
import pathlib, sys

ROOT = pathlib.Path('/opt/stock-review')

def edit(relpath, pairs):
    p = ROOT / relpath
    s = p.read_text(encoding='utf-8')
    for old, new in pairs:
        n = s.count(old)
        if n != 1:
            print('!! [%s] expect 1, got %d: %r' % (relpath, n, old[:70]))
            sys.exit(1)
        s = s.replace(old, new)
        print('ok [%s] %r' % (relpath, old[:55]))
    p.write_text(s, encoding='utf-8')

edit('static/js/ipo.js', [
    # A. 阈值表与后端 TURNOVER_THRESHOLDS_BY_DAY 完全一致（原表 D3+ 数值漂移）
    ('''const DAY_THRESHOLDS = {
  0: { tp_10min_high:32.8, tp_10min_super:38.2, tp_30min_high:46.1, tp_60min_high:57.8, tp_120min_high:65.5, tp_close_high:81.2 },
  1: { tp_10min_high:19.4, tp_10min_super:20.2, tp_30min_high:28.3, tp_60min_high:35.1, tp_120min_high:42.4, tp_close_high:61.4 },
  2: { tp_10min_high:8.7, tp_10min_super:10.5, tp_30min_high:15.6, tp_60min_high:20.9, tp_120min_high:28.4, tp_close_high:46.7 },
  3: { tp_10min_high:9.5, tp_30min_high:16.8, tp_60min_high:22.5, tp_120min_high:30.1, tp_close_high:48.9 },
  4: { tp_10min_high:13.0, tp_30min_high:20.1, tp_60min_high:26.8, tp_120min_high:34.5, tp_close_high:52.3 },
  5: { tp_10min_high:12.8, tp_30min_high:19.5, tp_60min_high:25.9, tp_120min_high:33.2, tp_close_high:51.0 },
  6: { tp_10min_high:7.9, tp_30min_high:14.2, tp_60min_high:19.8, tp_120min_high:26.5, tp_close_high:44.2 },
  7: { tp_10min_high:7.3, tp_30min_high:13.5, tp_60min_high:18.9, tp_120min_high:25.3, tp_close_high:42.8 },
  8: { tp_10min_high:6.0, tp_30min_high:11.8, tp_60min_high:16.9, tp_120min_high:23.0, tp_close_high:40.1 },
  9: { tp_10min_high:5.6, tp_30min_high:11.2, tp_60min_high:16.1, tp_120min_high:22.0, tp_close_high:38.9 },
  10:{ tp_10min_high:4.7, tp_30min_high:9.8, tp_60min_high:14.5, tp_120min_high:20.1, tp_close_high:36.5 },
};''',
     '''/* 兜底阈值表（以后端下发的 turnover_thresholds 为准，此表保持与后端 TURNOVER_THRESHOLDS_BY_DAY 一致） */
const DAY_THRESHOLDS = {
  0: { tp_10min_high:32.8, tp_10min_super:38.2, tp_30min_high:46.1, tp_30min_super:0, tp_60min_high:57.8, tp_120min_high:65.5, tp_close_high:81.2 },
  1: { tp_10min_high:19.4, tp_10min_super:20.2, tp_30min_high:28.3, tp_60min_high:35.1, tp_120min_high:42.4, tp_close_high:61.4 },
  2: { tp_10min_high:8.7, tp_10min_super:10.5, tp_30min_high:15.6, tp_60min_high:20.9, tp_120min_high:28.4, tp_close_high:46.7 },
  3: { tp_10min_high:9.5, tp_10min_super:14.8, tp_30min_high:18.8, tp_60min_high:24.0, tp_120min_high:36.0, tp_close_high:54.8 },
  4: { tp_10min_high:13.0, tp_10min_super:18.1, tp_30min_high:25.2, tp_60min_high:33.5, tp_120min_high:39.2, tp_close_high:51.9 },
  5: { tp_10min_high:12.8, tp_10min_super:13.4, tp_30min_high:18.7, tp_60min_high:22.6, tp_120min_high:29.4, tp_close_high:46.2 },
  6: { tp_10min_high:7.9, tp_10min_super:8.1, tp_30min_high:16.2, tp_60min_high:20.1, tp_120min_high:27.8, tp_close_high:38.2 },
  7: { tp_10min_high:7.3, tp_10min_super:11.8, tp_30min_high:13.6, tp_60min_high:22.1, tp_120min_high:29.1, tp_close_high:45.2 },
  8: { tp_10min_high:6.0, tp_10min_super:14.5, tp_30min_high:11.8, tp_60min_high:16.3, tp_120min_high:21.2, tp_close_high:30.4 },
  9: { tp_10min_high:5.6, tp_10min_super:8.0, tp_30min_high:7.6, tp_60min_high:12.0, tp_120min_high:14.6, tp_close_high:20.6 },
  10:{ tp_10min_high:4.7, tp_10min_super:6.1, tp_30min_high:9.1, tp_60min_high:15.9, tp_120min_high:18.9, tp_close_high:24.9 },
};'''),

    # B. off-by-one：后端按 day_index-1 取表（1-based→0-based），前端原来直接用 dayIndex
    ('''function getThresholds(dayIndex) {
  return DAY_THRESHOLDS[Math.min(dayIndex, 10)] || DAY_THRESHOLDS[0];
}''',
     '''function getThresholds(dayIndex) {
  /* dayIndex 为 1-based（D1=首日）；表键为 0-based，与后端 get_thresholds 一致 */
  return DAY_THRESHOLDS[Math.min(Math.max(dayIndex - 1, 0), 10)] || DAY_THRESHOLDS[0];
}'''),

    # C. D1 四段式 → 与后端 DAY1_TURNOVER_SCORE 一致的三段式（同分同区段）
    ('''var DAY1_TURNOVER_ZONES = {
  '10分钟':  [[10,20,1,2],[20,30,2,3],[30,39,3,7],[39,45,7,10]],
  '30分钟':  [[20,30,1,2],[30,45,2,3],[45,53,3,7],[53,60,7,10]],
  '60分钟':  [[30,40,1,2],[40,55,2,3],[55,64,3,7],[64,70,7,10]],
  '120分钟': [[40,50,1,2],[50,65,2,3],[65,70,3,7],[70,75,7,10]],
  '收盘':    [[60,70,1,2],[70,78,2,3],[78,86,3,7],[86,88,7,10]],
};
var DAY1_ZONE_LABELS = ['冷淡','压缩','加分','强势'];
var DAY1_ZONE_COLORS = ['var(--gray-400)','#5b9bd5','#f0ad4e','var(--danger)'];''',
     '''var DAY1_TURNOVER_ZONES = {
  '10分钟':  [[10,20,2.8,3.8],[20,39,3.8,6.4],[39,45,6.4,10]],
  '30分钟':  [[20,30,2.8,3.8],[30,53,3.8,6.4],[53,60,6.4,10]],
  '60分钟':  [[30,40,2.8,3.8],[40,64,3.8,6.4],[64,70,6.4,10]],
  '120分钟': [[40,50,2.8,3.8],[50,70,3.8,6.4],[70,75,6.4,10]],
  '收盘':    [[60,70,2.8,3.8],[70,80,3.8,6.4],[80,88,6.4,10]],
};
var DAY1_ZONE_LABELS = ['冷淡','加分','强势'];
var DAY1_ZONE_COLORS = ['var(--gray-400)','#f0ad4e','var(--danger)'];'''),

    ('''  if (val < zones[0][0]) return {score: 0, zone: '冷淡', color: DAY1_ZONE_COLORS[0]};
  if (val >= zones[3][1]) return {score: 100, zone: '强势', color: DAY1_ZONE_COLORS[3]};
  for (var i = 0; i < zones.length; i++) {''',
     '''  if (val < zones[0][0]) return {score: 0, zone: '冷淡', color: DAY1_ZONE_COLORS[0]};
  if (val >= zones[zones.length - 1][1]) return {score: 100, zone: '强势', color: DAY1_ZONE_COLORS[2]};
  for (var i = 0; i < zones.length; i++) {'''),

    # D. 阈值优先用后端下发（消除两套阈值漂移）
    ('''function renderTurnoverTimepoints(tps, dayIndex) {
  if (!tps || typeof tps !== 'object' || Object.keys(tps).length === 0) {
    return '<div style="margin-top:8px;font-size:11px;color:var(--gray-500)">量能数据采集中（交易时间自动更新）</div>';
  }
  const thresholds = getThresholds(dayIndex);''',
     '''function renderTurnoverTimepoints(tps, dayIndex, thOverride) {
  if (!tps || typeof tps !== 'object' || Object.keys(tps).length === 0) {
    return '<div style="margin-top:8px;font-size:11px;color:var(--gray-500)">量能数据采集中（交易时间自动更新）</div>';
  }
  const thresholds = thOverride || getThresholds(dayIndex);'''),

    ("    const turnoverHtml = renderTurnoverTimepoints(s.turnover_timepoints, dayIdx);",
     "    const turnoverHtml = renderTurnoverTimepoints(s.turnover_timepoints, dayIdx, s.turnover_thresholds);"),
])

edit('static/index.html', [
    ('<script src="/static/js/ipo.js?v=1"></script>',
     '<script src="/static/js/ipo.js?v=2"></script>'),
])

print('patch16b done')
