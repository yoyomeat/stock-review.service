/* 新股评分页面 V3 — V2四维度评分 + day_index + 动态阈值 */
let _ipoLoaded = false;

/* 不同day的5时间点换手率阈值（与后端TURNOVER_THRESHOLDS_BY_DAY一致） */
/* 兜底阈值表（以后端下发的 turnover_thresholds 为准，此表保持与后端 TURNOVER_THRESHOLDS_BY_DAY 一致） */
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
};

function getThresholds(dayIndex) {
  /* dayIndex 为 1-based（D1=首日）；表键为 0-based，与后端 get_thresholds 一致 */
  return DAY_THRESHOLDS[Math.min(Math.max(dayIndex - 1, 0), 10)] || DAY_THRESHOLDS[0];
}

async function loadIpoPage() {
  window._ipoLoaded = true;
  _ipoLoaded = true;
  const el = $('#ipo-content');
  el.innerHTML = '<div class="loading">加载新股评分...</div>';
  try {
    const data = await api('/api/ipo_score', 30000);
    renderIpoPage(el, data);
  } catch (e) {
    el.innerHTML = '<div class="card">加载失败: ' + e.message +
      '<br><button onclick="loadIpoPage()" style="margin-top:8px;padding:4px 12px;cursor:pointer">重试</button></div>';
  }
}

/* ── DAY1四段式换手率评分配置（与后端一致）── */
var DAY1_TURNOVER_ZONES = {
  '10分钟':  [[10,20,2.8,3.8],[20,39,3.8,6.4],[39,45,6.4,10]],
  '30分钟':  [[20,30,2.8,3.8],[30,53,3.8,6.4],[53,60,6.4,10]],
  '60分钟':  [[30,40,2.8,3.8],[40,64,3.8,6.4],[64,70,6.4,10]],
  '120分钟': [[40,50,2.8,3.8],[50,70,3.8,6.4],[70,75,6.4,10]],
  '收盘':    [[60,70,2.8,3.8],[70,80,3.8,6.4],[80,88,6.4,10]],
};
var DAY1_ZONE_LABELS = ['冷淡','加分','强势'];
var DAY1_ZONE_COLORS = ['var(--gray-400)','#f0ad4e','var(--danger)'];

function scoreDay1Turnover(label, val) {
  if (!val || val <= 0) return {score: 50, zone: '-', color: 'var(--gray-500)'};
  var zones = DAY1_TURNOVER_ZONES[label];
  if (!zones) return {score: 50, zone: '-', color: 'var(--gray-500)'};
  if (val < zones[0][0]) return {score: 0, zone: '冷淡', color: DAY1_ZONE_COLORS[0]};
  if (val >= zones[zones.length - 1][1]) return {score: 100, zone: '强势', color: DAY1_ZONE_COLORS[2]};
  for (var i = 0; i < zones.length; i++) {
    var hLow = zones[i][0], hHigh = zones[i][1], sLow = zones[i][2], sHigh = zones[i][3];
    if (val >= hLow && val < hHigh) {
      var s10 = sLow + (val - hLow) / (hHigh - hLow) * (sHigh - sLow);
      var score = Math.round((s10 - 1) / 9 * 100);
      return {score: score, zone: DAY1_ZONE_LABELS[i], color: DAY1_ZONE_COLORS[i]};
    }
  }
  return {score: 50, zone: '-', color: 'var(--gray-500)'};
}

/* ── 量能时间点渲染（V2 dict格式 + 动态阈值）── */
function renderTurnoverTimepoints(tps, dayIndex, thOverride) {
  if (!tps || typeof tps !== 'object' || Object.keys(tps).length === 0) {
    return '<div style="margin-top:8px;font-size:11px;color:var(--gray-500)">量能数据采集中（交易时间自动更新）</div>';
  }
  const thresholds = thOverride || getThresholds(dayIndex);
  const labels = ['10分钟', '30分钟', '60分钟', '120分钟', '收盘'];
  const thKeys = ['tp_10min', 'tp_30min', 'tp_60min', 'tp_120min', 'tp_close'];

  const isDay1 = dayIndex === 1;
  const items = labels.map(function(label, i) {
    const val = tps[label] || 0;
    const pct = val > 0 ? val.toFixed(1) : '-';
    if (isDay1) {
      // DAY1：四段式评分+区段标签
      const r = scoreDay1Turnover(label, val);
      return '<div style="flex:1;text-align:center;padding:4px 2px">' +
        '<div style="font-size:10px;color:var(--gray-500);margin-bottom:2px">' + label + '</div>' +
        '<div style="font-size:14px;font-weight:700;color:' + r.color + '">' + pct + '%</div>' +
        '<div style="font-size:9px;color:' + r.color + ';margin-top:1px;font-weight:600">' + r.score + '分 · ' + r.zone + '</div>' +
      '</div>';
    }
    // DAY2+：旧逻辑（高/超高）
    const highTh = thresholds[thKeys[i] + '_high'] || 0;
    const superTh = thresholds[thKeys[i] + '_super'] || highTh * 1.2;
    let color = 'var(--gray-400)';
    let tag = '';
    if (val >= superTh) {
      color = 'var(--danger)';
      tag = '超高';
    } else if (val >= highTh) {
      color = '#f0ad4e';
      tag = '高';
    } else if (val > 0) {
      color = 'var(--gray-300)';
    } else {
      color = 'var(--gray-600)';
    }
    return '<div style="flex:1;text-align:center;padding:4px 2px">' +
      '<div style="font-size:10px;color:var(--gray-500);margin-bottom:2px">' + label + '</div>' +
      '<div style="font-size:14px;font-weight:700;color:' + color + '">' + pct + '%</div>' +
      (tag ? '<div style="font-size:9px;color:' + color + ';margin-top:1px">' + tag + '</div>' :
       '<div style="font-size:9px;color:var(--gray-600);margin-top:1px">阈值' + highTh.toFixed(0) + '%</div>') +
    '</div>';
  }).join('');

  return '<div style="margin-top:10px;padding:8px 6px;background:var(--bg);border-radius:var(--radius-sm);border:1px solid var(--border)">' +
    '<div style="font-size:11px;font-weight:600;color:var(--gray-400);margin-bottom:4px">量能时间点（累计换手率 · D' + dayIndex + '阈值）</div>' +
    '<div style="display:flex;gap:2px">' + items + '</div>' +
  '</div>';
}

/* ── 预测卡渲染 ── */
function renderPredictionCard(ps, actualOpen, actualChange) {
  if (!ps) return '';
  const qi = ps.quality_index || 0;
  const hi = ps.hype_index || 0;
  const predOpen = ps.pred_open_price || 0;
  const qiColor = qi >= 4 ? 'var(--success)' : qi >= 3 ? '#f0ad4e' : 'var(--danger)';
  const hiColor = hi >= 4 ? 'var(--danger)' : hi >= 3 ? '#f0ad4e' : 'var(--gray-400)';

  let openCompare = '';
  if (actualOpen && predOpen) {
    const diff = ((actualOpen - predOpen) / predOpen * 100).toFixed(1);
    const diffColor = Math.abs(diff) <= 10 ? 'var(--success)' : 'var(--danger)';
    openCompare = '<span style="font-size:11px;color:' + diffColor + ';margin-left:4px">实际' + actualOpen + '(' + (diff > 0 ? '+' : '') + diff + '%)</span>';
  }

  const zones = [
    { label: '低风险', val: ps.pred_low_zone, color: 'var(--success)' },
    { label: '博弈', val: (ps.pred_game_low || 0) + '-' + (ps.pred_game_high || 0), color: 'var(--primary)' },
    { label: '高风险', val: ps.pred_high_zone, color: 'var(--danger)' },
    { label: '中长线', val: ps.pred_midlong_target, color: 'var(--purple)' },
  ];
  const zoneHtml = zones.map(function(z) {
    return '<span style="font-size:10px;color:' + z.color + ';margin-right:8px">' + z.label + z.val + '</span>';
  }).join('');

  const themes = (ps.theme_concept || '').split(/[,，、]/).filter(function(t) { return t.trim(); }).slice(0, 5)
    .map(function(t) { return '<span style="font-size:10px;padding:1px 5px;border-radius:3px;background:rgba(240,173,78,0.12);color:#f0ad4e;margin-right:3px">' + t.trim() + '</span>'; }).join('');

  return '<div style="margin-top:10px;padding:10px;background:var(--bg);border-radius:var(--radius-sm);border:1px solid var(--border)">' +
    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">' +
      '<span style="font-size:11px;font-weight:600;color:var(--gray-400)">上市前预测</span>' +
      '<span style="font-size:10px;color:var(--gray-600)">' + (ps.list_date || '') + '上市</span>' +
    '</div>' +
    '<div style="display:flex;gap:16px;margin-bottom:6px">' +
      '<div><span style="font-size:11px;color:var(--gray-500)">优质</span> <span style="font-size:16px;font-weight:700;color:' + qiColor + '">' + qi + '</span></div>' +
      '<div><span style="font-size:11px;color:var(--gray-500)">炒作</span> <span style="font-size:16px;font-weight:700;color:' + hiColor + '">' + hi + '</span></div>' +
      '<div><span style="font-size:11px;color:var(--gray-500)">预测开</span> <span style="font-size:16px;font-weight:700;color:var(--primary)">' + predOpen + '</span>' + openCompare + '</div>' +
      '<div><span style="font-size:11px;color:var(--gray-500)">合理市值</span> <span style="font-size:14px;font-weight:600">' + ps.pred_reasonable_mcap + '亿</span></div>' +
    '</div>' +
    '<div style="margin-bottom:4px">' + zoneHtml + '</div>' +
    (themes ? '<div style="margin-top:4px">' + themes + '</div>' : '') +
  '</div>';
}

function renderIpoPage(el, data) {
  const scores = (data.scores || []).slice().sort(function(a, b) {
    return (b.total_score || 0) - (a.total_score || 0);
  });
  const date = data.date || '';

  if (scores.length === 0) {
    el.innerHTML =
      '<div class="card" style="text-align:center;padding:40px 20px">' +
        '<div style="font-size:48px;margin-bottom:16px;opacity:0.3">新股</div>' +
        '<div style="font-size:16px;color:var(--gray-300);margin-bottom:8px">今日无新股</div>' +
        '<div style="font-size:13px;color:var(--gray-500)">高分股跟踪10天，低分股5天退池</div>' +
        '<button onclick="loadIpoPage()" style="margin-top:16px;padding:6px 16px;font-size:13px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--card);cursor:pointer">刷新</button>' +
      '</div>';
    return;
  }

  const signalColors = {
    'strong': 'var(--success)',
    'attention': '#f0ad4e',
    'neutral': 'var(--gray-400)',
    'caution': '#e08e3c',
    'avoid': 'var(--danger)',
  };
  const signalLabels = {
    'strong': '强势关注',
    'attention': '重点关注',
    'neutral': '中性观察',
    'caution': '谨慎观望',
    'avoid': '回避',
  };

  const strongCount = scores.filter(function(s) { return s.signal === 'strong'; }).length;
  const attentionCount = scores.filter(function(s) { return s.signal === 'attention'; }).length;
  const avgScore = scores.reduce(function(a, b) { return a + (b.total_score || 0); }, 0) / scores.length;

  // 新股情绪周期横幅
  const sentiment = data.sentiment || null;
  let sentimentHtml = '';
  if (sentiment && sentiment.score !== undefined && sentiment.score !== null) {
    const sColors = { '亢奋': 'var(--danger)', '回暖': 'var(--success)', '中性': 'var(--gray-400)', '低迷': '#e08e3c', '冰点': 'var(--danger)' };
    const sColor = sColors[sentiment.label] || 'var(--gray-400)';
    const st = sentiment.stats || {};
    sentimentHtml =
      '<div style="display:flex;align-items:center;gap:16px;padding:10px 14px;margin-bottom:14px;border-radius:var(--radius-sm);background:rgba(0,0,0,0.15);border-left:3px solid ' + sColor + '">' +
        '<div style="font-size:12px;color:var(--gray-500)">新股情绪</div>' +
        '<div style="font-size:20px;font-weight:700;color:' + sColor + '">' + sentiment.score.toFixed(1) + '</div>' +
        '<div style="font-size:14px;font-weight:600;color:' + sColor + '">' + (sentiment.label || '') + '</div>' +
        '<div style="font-size:12px;color:var(--gray-500)">预测校准系数 ×' + (sentiment.coef || 1).toFixed(2) + '</div>' +
        '<div style="font-size:12px;color:var(--gray-500)">样本' + (st.sample_count || 0) + '只 · 次日闷杀' + (st.d1_avg !== undefined ? st.d1_avg.toFixed(1) : '-') + '% · 收盘/最高' + (st.tail_ratio !== undefined ? (st.tail_ratio * 100).toFixed(0) : '-') + '% · 赚钱效应' + (st.pos_ratio !== undefined ? (st.pos_ratio * 100).toFixed(0) : '-') + '%</div>' +
        '<div style="font-size:12px;color:var(--gray-500);flex:1;text-align:right">' + (sentiment.note || '') + '</div>' +
      '</div>';
  }

  const summaryHtml =
    '<div class="card" style="margin-bottom:20px">' +
      sentimentHtml +
      '<div style="display:flex;justify-content:space-between;align-items:center">' +
        '<div style="font-size:14px;color:var(--gray-500)">' + scores.length + '只新股（沪深）· ' + date + ' · 按评分降序 · V2四维度</div>' +
        '<div style="display:flex;gap:8px">' +
          '<a href="/ipo_research" style="padding:4px 12px;font-size:12px;border:1px solid var(--primary);border-radius:var(--radius-sm);background:var(--card);color:var(--primary);cursor:pointer;text-decoration:none">历史复盘</a>' +
          '<button onclick="loadIpoPage()" style="padding:4px 12px;font-size:12px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--card);cursor:pointer">刷新</button>' +
        '</div>' +
      '</div>' +
      '<div style="display:flex;gap:20px;margin-top:12px">' +
        '<div style="text-align:center"><div style="font-size:28px;font-weight:700;color:var(--primary)">' + avgScore.toFixed(0) + '</div><div style="font-size:12px;color:var(--gray-500)">平均分</div></div>' +
        '<div style="text-align:center"><div style="font-size:28px;font-weight:700;color:var(--success)">' + strongCount + '</div><div style="font-size:12px;color:var(--gray-500)">强势关注</div></div>' +
        '<div style="text-align:center"><div style="font-size:28px;font-weight:700;color:#f0ad4e">' + attentionCount + '</div><div style="font-size:12px;color:var(--gray-500)">重点关注</div></div>' +
      '</div>' +
    '</div>';

  const cardsHtml = scores.map(function(s) {
    const color = signalColors[s.signal] || 'var(--gray-400)';
    const label = signalLabels[s.signal] || s.signal_label || s.signal;
    const chgPct = s.change_pct || 0;
    const chgColor = chgPct > 0 ? 'var(--success)' : chgPct < 0 ? 'var(--danger)' : 'var(--gray-400)';
    const dayIdx = s.day_index || 0;
    const trackDays = s.track_days || 5;
    const dayColor = dayIdx === 0 ? 'var(--danger)' : dayIdx <= 2 ? '#f0ad4e' : 'var(--gray-400)';

    /* V2四维度 */
    const dims = [
      { k: '资金关注度', v: s.dim1_attention, w: '30%' },
      { k: '走势形态', v: s.dim2_pattern, w: '25%' },
      { k: '筹码稳定性', v: s.dim3_chip, w: '20%' },
      { k: '基本面质地', v: s.dim4_fundamental, w: '25%' },
    ];

    const dimHtml = dims.map(function(d) {
      const score = d.v && typeof d.v === 'object' ? (d.v.score || 0) : (d.v || 0);
      const pct = Math.round(score);
      const barColor = pct >= 70 ? 'var(--success)' : pct >= 50 ? 'var(--gray-400)' : 'var(--danger)';
      return '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">' +
        '<span style="width:72px;font-size:13px;color:var(--gray-300)">' + d.k + '</span>' +
        '<div style="flex:1;height:8px;background:var(--bg);border-radius:4px;overflow:hidden">' +
          '<div style="height:100%;width:' + pct + '%;background:' + barColor + ';border-radius:4px;transition:width 0.3s"></div>' +
        '</div>' +
        '<span style="width:32px;text-align:right;font-size:13px;font-weight:600;color:' + barColor + '">' + pct + '</span>' +
        '<span style="width:28px;font-size:11px;color:var(--gray-500)">' + d.w + '</span>' +
      '</div>';
    }).join('');

    /* 子指标详情 */
    const subItemsHtml = dims.map(function(d) {
      if (!d.v || typeof d.v !== 'object' || !d.v.sub_items) return '';
      return d.v.sub_items.map(function(si) {
        return '<span style="font-size:10px;color:var(--gray-500)">' + si.name + ':' + si.raw_value + '</span>';
      }).join('<span style="color:var(--border);margin:0 3px">|</span>');
    }).filter(function(h) { return h; }).join('<br>');

    const turnoverHtml = renderTurnoverTimepoints(s.turnover_timepoints, dayIdx, s.turnover_thresholds);
    const predHtml = renderPredictionCard(s.prediction_summary, s.price, chgPct);

    return '<div class="card" style="margin-bottom:16px">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">' +
        '<div>' +
          '<span style="font-size:18px;font-weight:700">' + (s.name || s.code) + '</span>' +
          '<span style="font-size:13px;color:var(--gray-500);margin-left:8px">' + s.code + '</span>' +
          '<span style="font-size:11px;margin-left:8px;padding:2px 8px;border-radius:8px;background:' + dayColor + '18;color:' + dayColor + ';font-weight:600">D' + dayIdx + '</span>' +
          '<span style="font-size:11px;color:var(--gray-600);margin-left:4px">跟踪' + trackDays + '天</span>' +
          '<span style="font-size:14px;margin-left:12px;color:' + chgColor + ';font-weight:600">' +
            (chgPct > 0 ? '+' : '') + chgPct.toFixed(2) + '%</span>' +
        '</div>' +
        '<div style="display:flex;align-items:center;gap:10px">' +
          '<span style="font-size:28px;font-weight:700;color:' + color + '">' + (s.total_score || 0).toFixed(0) + '</span>' +
          '<span style="font-size:12px;padding:3px 10px;border-radius:12px;background:' + color + '15;color:' + color + ';font-weight:600">' + label + '</span>' +
        '</div>' +
      '</div>' +
      dimHtml +
      (subItemsHtml ? '<div style="margin-top:6px;line-height:1.8">' + subItemsHtml + '</div>' : '') +
      predHtml +
      turnoverHtml +
    '</div>';
  }).join('');

  el.innerHTML = summaryHtml + cardsHtml;
}

/* ── 实时监控页的新股卡片（V2兼容）── */
async function loadIpoScores() {
  const el = $('#rt-ipo');
  if (!el) return;
  try {
    const data = await api('/api/ipo_score', 30000);
    renderIpoScores(el, data);
  } catch (e) {
    el.innerHTML = '<p style="color:var(--gray-400);font-size:13px">加载失败</p>';
  }
}

function renderIpoScores(el, data) {
  const scores = (data.scores || []).slice().sort(function(a, b) {
    return (b.total_score || 0) - (a.total_score || 0);
  });
  if (scores.length === 0) {
    el.innerHTML = '<p style="color:var(--gray-400);font-size:13px;padding:8px 0">今日无新股</p>';
    return;
  }
  const signalColors = { strong:'var(--success)', attention:'#f0ad4e', neutral:'var(--gray-400)', caution:'#e08e3c', avoid:'var(--danger)' };
  const signalLabels = { strong:'强势', attention:'关注', neutral:'中性', caution:'谨慎', avoid:'回避' };

  const rows = scores.map(function(s) {
    const color = signalColors[s.signal] || 'var(--gray-400)';
    const label = signalLabels[s.signal] || s.signal;
    const chgPct = s.change_pct || 0;
    const chgColor = chgPct > 0 ? 'var(--success)' : chgPct < 0 ? 'var(--danger)' : 'var(--gray-400)';
    return '<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--border)">' +
      '<div>' +
        '<span style="font-size:14px;font-weight:600">' + (s.name || s.code) + '</span>' +
        '<span style="font-size:12px;color:var(--gray-500);margin-left:6px">' + s.code + '</span>' +
        '<span style="font-size:10px;margin-left:6px;padding:1px 6px;border-radius:6px;background:var(--bg);color:var(--gray-500)">D' + (s.day_index || 0) + '</span>' +
        '<span style="font-size:12px;margin-left:8px;color:' + chgColor + '">' + (chgPct > 0 ? '+' : '') + chgPct.toFixed(2) + '%</span>' +
      '</div>' +
      '<div style="display:flex;align-items:center;gap:8px">' +
        '<span style="font-size:16px;font-weight:700;color:' + color + '">' + (s.total_score || 0).toFixed(0) + '</span>' +
        '<span style="font-size:11px;padding:2px 8px;border-radius:10px;background:' + color + '22;color:' + color + '">' + label + '</span>' +
      '</div>' +
    '</div>';
  }).join('');

  el.innerHTML = '<div style="font-size:12px;color:var(--gray-500);margin-bottom:6px">' + scores.length + '只新股（V2评分）</div>' + rows;
}
