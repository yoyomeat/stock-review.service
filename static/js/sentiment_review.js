/* 情绪流赚钱效应复盘系统 — 前端框架 V2.0
 * T1 客观盘面 + 情绪周期序列 + T2/T3 复盘录入 + T4 预案 + T5 回填 + T6 规则库 + T0 口径
 * 特性：子页签导航 / 演示数据模式 / 校验规则内嵌 / 周期色带序列图
 */
const SR = {
  loaded: false,
  tab: 'seq',
  seqDays: 30,
  demo: false,
  charts: {},
  carriers: [],
  scenarios: [],
  linkedCarriers: [],
  today: '',
  tradeDate: '',
  targetDate: '',
  preopen: false,
  demoData: null,
};

/* ── 工具 ── */
function srFmt(v, d) { return v != null && !isNaN(v) ? Number(v).toFixed(d !== undefined ? d : 1) : '-'; }
function srPct(v) { return v != null && !isNaN(v) ? (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%' : '-'; }
function srDate(d) {
  if (!d || d.length < 8) return d || '';
  return d.slice(0, 4) + '-' + d.slice(4, 6) + '-' + d.slice(6, 8);
}
function srMD(d) { return d && d.length >= 8 ? d.slice(4, 6) + '-' + d.slice(6, 8) : (d || ''); }
function srTodayStr() {
  const t = new Date();
  return t.getFullYear() + String(t.getMonth() + 1).padStart(2, '0') + String(t.getDate()).padStart(2, '0');
}
/* ── 交易日历（真实节假日，/api/sentiment/trade_calendar）── */
function srLoadCal() {
  if (SR.calLoading) return SR.calLoading;
  SR.calLoading = fetch('/api/sentiment/trade_calendar', { cache: 'no-store' })
    .then(r => r.json())
    .then(j => { SR.tradeCal = new Set(j.dates || []); })
    .catch(() => { SR.calLoading = null; });
  return SR.calLoading;
}
srLoadCal();
function srIsTradeDay(d) {
  if (SR.tradeCal) return SR.tradeCal.has(d);
  const t = new Date(d.slice(0, 4), parseInt(d.slice(4, 6)) - 1, parseInt(d.slice(6, 8)));
  return t.getDay() !== 0 && t.getDay() !== 6;
}
function srNextTradeDay(d) {
  if (SR.tradeCal) {
    for (const x of [...SR.tradeCal].sort()) if (x > d) return x;
  }
  // 兜底（日历未加载）：仅跳周末
  const dt = new Date(d.slice(0, 4), parseInt(d.slice(4, 6)) - 1, parseInt(d.slice(6, 8)));
  do { dt.setDate(dt.getDate() + 1); } while (dt.getDay() === 0 || dt.getDay() === 6);
  return dt.getFullYear() + String(dt.getMonth() + 1).padStart(2, '0') + String(dt.getDate()).padStart(2, '0');
}
function srBizDaysBetween(a, b) {
  // 两个 YYYYMMDD 之间的交易日数（不含起始日，含节假日过滤）
  if (SR.tradeCal) {
    let n = 0;
    for (const x of SR.tradeCal) if (x > a && x <= b) n++;
    return n;
  }
  let n = 0;
  const dt = new Date(a.slice(0, 4), parseInt(a.slice(4, 6)) - 1, parseInt(a.slice(6, 8)));
  const end = new Date(b.slice(0, 4), parseInt(b.slice(4, 6)) - 1, parseInt(b.slice(6, 8)));
  while (dt < end) {
    dt.setDate(dt.getDate() + 1);
    if (dt.getDay() !== 0 && dt.getDay() !== 6) n++;
  }
  return n;
}

/* 周期词表 v2（2026-09-29 定稿）：5 点状态 + 8 过渡段（A-B = A 向 B 过渡） */
const SR_POINT_PHASES = ['冰点', '上升', '上升分歧', '下降', '下降中继'];
const SR_SEG_PHASES = ['冰点-上升', '上升-上升分歧', '上升分歧-上升', '上升分歧-下降',
  '下降-下降中继', '下降中继-下降', '下降中继-冰点', '下降-冰点'];
const SR_PHASE_COLORS = {
  '冰点': '#64748b', '上升': '#ef4444', '上升分歧': '#f59e0b',
  '下降': '#3b82f6', '下降中继': '#8b5cf6',
  '冰点-上升': '#ef4444', '上升-上升分歧': '#f59e0b',
  '上升分歧-上升': '#ef4444', '上升分歧-下降': '#3b82f6',
  '下降-下降中继': '#8b5cf6', '下降中继-下降': '#3b82f6',
  '下降中继-冰点': '#64748b', '下降-冰点': '#64748b'
};
function srPhaseColor(p) {
  if (SR_PHASE_COLORS[p]) return SR_PHASE_COLORS[p];
  if (p && p.includes('-')) return SR_PHASE_COLORS[p.split('-')[1]] || '#94a3b8';
  return '#94a3b8';
}
function srPhaseBg(p) {
  const hex = srPhaseColor(p).replace('#', '');
  const r = parseInt(hex.slice(0, 2), 16), g = parseInt(hex.slice(2, 4), 16), b = parseInt(hex.slice(4, 6), 16);
  return `rgba(${r},${g},${b},.10)`;
}
function srPhaseOptions() {
  return '<optgroup label="点状态">' + SR_POINT_PHASES.map(p => `<option>${p}</option>`).join('') +
    '</optgroup><optgroup label="过渡段（A-B = A 向 B 过渡）">' +
    SR_SEG_PHASES.map(p => `<option>${p}</option>`).join('') + '</optgroup>';
}
function srPhaseChip(p) {
  return p ? `<span class="sr-chip" style="background:${srPhaseBg(p)};color:${srPhaseColor(p)};border:1px solid ${srPhaseColor(p)}33;">${p}</span>` : '<span class="sr-chip">-</span>';
}
function srToast(msg, type) {
  const box = document.createElement('div');
  box.className = 'sr-toast ' + (type || 'ok');
  box.textContent = msg;
  document.body.appendChild(box);
  setTimeout(() => box.classList.add('show'), 10);
  setTimeout(() => { box.classList.remove('show'); setTimeout(() => box.remove(), 300); }, 2600);
}

/* ── 演示数据（供框架审阅用，不入库） ── */
function srBuildDemo() {
  if (SR.demoData) return SR.demoData;
  const phaseRun = ['冰点', '冰点-上升', '上升', '上升', '上升-上升分歧',
    '上升分歧', '上升分歧-下降', '下降', '下降-下降中继', '下降中继',
    '下降中继-冰点', '冰点', '冰点-上升', '上升', '上升',
    '上升-上升分歧', '上升分歧', '上升分歧-上升', '上升', '上升-上升分歧',
    '上升分歧-下降', '下降', '下降-下降中继', '下降中继', '下降中继-下降',
    '下降', '下降-冰点', '冰点', '冰点-上升', '上升'];
  const base = { '冰点': 22, '上升': 68, '上升分歧': 55, '下降': 35, '下降中继': 40 };
  const board = { '冰点': 2, '上升': 7, '上升分歧': 6, '下降': 4, '下降中继': 3 };
  const days = [];
  // 生成最近 30 个交易日（跳过周末）
  const dates = [];
  const dt = new Date(2026, 8, 29); // 2026-09-29
  while (dates.length < 30) {
    if (dt.getDay() !== 0 && dt.getDay() !== 6) {
      dates.unshift(dt.getFullYear() + String(dt.getMonth() + 1).padStart(2, '0') + String(dt.getDate()).padStart(2, '0'));
    }
    dt.setDate(dt.getDate() - 1);
  }
  const insights = {
    '冰点': '情绪降至冰点，亏钱效应扩散，等待右侧信号',
    '上升': '主线确认，连板梯队完整，赚钱效应扩散',
    '上升分歧': '高位批量炸板但未核按钮，分歧偏强，观察承接',
    '下降': '高标断板补跌，亏钱效应主导，收缩战线',
    '下降中继': '下跌暂缓但无新主线，反抽不追，等待方向选择'
  };
  for (let i = 0; i < 30; i++) {
    const p = phaseRun[i];
    const pKey = p.includes('-') ? p.split('-')[1] : p;
    const wobble = ((i * 7) % 11) - 5;
    const score = Math.max(5, Math.min(95, base[pKey] + wobble));
    const up = 1200 + ((i * 137) % 3200);
    const down = 5557 - up;
    days.push({
      trade_date: dates[i],
      sentiment_score_obj: score,
      subjective_score: Math.max(5, Math.min(95, base[pKey] + wobble + (((i * 5) % 9) - 4))),
      break_rate: Math.max(3, Math.min(60, 100 - score + (((i * 3) % 13) - 6))),
      ly_premium: ((score - 50) / 12 + (((i * 5) % 7) - 3) * 0.3),
      ly_premium_cont: ((score - 50) / 14 + (((i * 3) % 5) - 2) * 0.3),
      max_board: Math.max(2, board[pKey] + (((i * 5) % 3) - 1)),
      board2plus_count: Math.max(3, Math.round(score / 5) + ((i * 3) % 5)),
      board3plus_count: Math.max(1, Math.round(score / 12) + ((i * 2) % 3)),
      limit_up_count: Math.round(score * 0.8) + ((i * 7) % 12),
      limit_down_count: Math.round((100 - score) / 9) + ((i * 3) % 4),
      break_count: Math.round((100 - score) / 6) + ((i * 2) % 5),
      big_loss_count: Math.round((100 - score) / 8) + ((i * 5) % 6),
      turnover_yi: 9000 + ((i * 431) % 6000),
      up_count: up, down_count: down,
      sh_pct: ((score - 50) / 30 + (((i * 7) % 9) - 4) * 0.1),
      cyb_pct: ((score - 50) / 25 + (((i * 5) % 9) - 4) * 0.12),
      source_status: i === 12 ? 'partial' : 'ok',
      cycle_phase: p,
      money_effect: score >= 60 ? '强' : score >= 40 ? '中' : '弱',
      loss_effect: score >= 60 ? '弱' : score >= 40 ? '中' : '强',
      today_insight: insights[pKey],
    });
  }
  const carriers = [
    { id: 1, trade_date: dates[29], code: '600825', name: '新华传媒', carrier_role: '总龙头', board_height: 6, carrier_status: '涨停', is_anchor: 1, note: 'AI短剧+国资，空间高度锚' },
    { id: 2, trade_date: dates[29], code: '603949', name: '雪龙集团', carrier_role: '高度板', board_height: 4, carrier_status: '涨停', is_anchor: 0, note: '' },
    { id: 3, trade_date: dates[29], code: '000678', name: '襄阳轴承', carrier_role: '补涨龙', board_height: 3, carrier_status: '炸板', is_anchor: 0, note: '机器人补涨，尾盘炸板' },
    { id: 4, trade_date: dates[28], code: '600825', name: '新华传媒', carrier_role: '高度板', board_height: 5, carrier_status: '涨停', is_anchor: 1, note: '' },
    { id: 5, trade_date: dates[27], code: '601519', name: '大智慧', carrier_role: '中军', board_height: 1, carrier_status: '断板', is_anchor: 1, note: '券商中军走弱' },
  ];
  const plans = [
    {
      plan_id: 101, base_date: dates[26], target_date: dates[27], plan_direction: '看分歧',
      position_level: '1', operation_style: '空仓观望',
      must_do: '观察高标开盘承接；盯昨日炸板股修复', must_not: '不接力中位股；不追一致高开',
      falsify_condition: '高标开盘5分钟内翻绿则空仓', confidence: 3,
      scenarios: [{ if: '高标平开高走', then: '轻仓试错首板' }, { if: '批量核按钮', then: '空仓看戏' }],
    },
    {
      plan_id: 102, base_date: dates[28], target_date: dates[29], plan_direction: '看修复',
      position_level: '2', operation_style: '低位接力试错',
      must_do: '主线方向首板试错；确认量能', must_not: '不碰高位断板股',
      falsify_condition: '开盘30分钟涨停家数<15且炸板率>30%则放弃', confidence: 3,
      scenarios: [],
    },
    {
      plan_id: 103, base_date: dates[29], target_date: srNextTradeDay(dates[29]), plan_direction: '看延续',
      position_level: '2', operation_style: '产业趋势低吸',
      must_do: '主线低吸补涨；持有核心仓', must_not: '不打跟风板',
      falsify_condition: '总龙头开盘翻绿且板块高开低走则降仓至1成', confidence: 5,
      scenarios: [{ if: '总龙头加速', then: '持有不加' }],
    },
  ];
  const verifs = [
    { verify_id: 201, plan_id: 101, verify_date: dates[27], actual_phase: '分歧', plan_result: '兑现', falsify_triggered: 0, score: 1, error_type: null, lesson: '' },
    { verify_id: 202, plan_id: 102, verify_date: dates[29], actual_phase: '发酵', plan_result: '证伪', falsify_triggered: 1, score: -1, error_type: '判断对执行错', lesson: '方向对但仓位上慢了，确认信号后应果断' },
  ];
  const rules = [
    { rule_id: 1, rule_text: '冰点次日高标核按钮不修复，空仓', trigger_condition: JSON.stringify({ phase: '冰点', signal: '高标核按钮未修复' }), sample_count: 24, hit_count: 18, status: '有效', era_tag: '2026H1', source_note: '来自T5回填 plan_id=88' },
    { rule_id: 2, rule_text: '分歧日空仓观望是对的，但修复确认要等10点后', trigger_condition: JSON.stringify({ phase: '分歧', window: '10:00' }), sample_count: 12, hit_count: 7, status: '待验证', era_tag: '2026H2', source_note: '来自T5回填 plan_id=101' },
    { rule_id: 3, rule_text: '高潮次日不接力跟风板', trigger_condition: JSON.stringify({ phase: '高潮', next_day: true }), sample_count: 31, hit_count: 25, status: '有效', era_tag: '2025H2', source_note: '人工提炼' },
    { rule_id: 4, rule_text: '缩量退潮期打板胜率低于20%', trigger_condition: JSON.stringify({ phase: '退潮', turnover: '<万亿' }), sample_count: 9, hit_count: 2, status: '失效', era_tag: '2026H1', source_note: '人工提炼' },
  ];
  const metrics = [
    { metric_name: 'sentiment_score_obj', definition: '客观情绪分 = 0.30×(100-break_rate) + 0.25×clamp(ly_premium,-5,5)/5×100 + 0.25×min(max_board,10)/10×100 + 0.20×up_ratio×100', version: 'v1.0', changed_at: '2026-09-29' },
    { metric_name: 'break_rate', definition: '炸板率 = 炸板家数 / (涨停家数 + 炸板家数) × 100%', version: 'v1.0', changed_at: '2026-09-29' },
    { metric_name: 'ly_premium', definition: '昨日涨停溢价 = 昨日涨停股今日平均涨幅%', version: 'v1.0', changed_at: '2026-09-29' },
    { metric_name: 'board2plus_count', definition: '收盘时连续涨停>=2天的家数', version: 'v1.0', changed_at: '2026-09-29' },
    { metric_name: 'big_loss_count', definition: '昨日涨停股今日跌幅<=-5%的家数', version: 'v1.0', changed_at: '2026-09-29' },
    { metric_name: 'max_board', definition: '当日最高连板高度（剔除ST/新股未开板）', version: 'v1.0', changed_at: '2026-09-29' },
    { metric_name: 'source_status', definition: '数据源完整性: ok=全部命中 / partial=部分缺失 / fail=采集失败', version: 'v1.0', changed_at: '2026-09-29' },
  ];
  SR.demoData = { days, carriers, plans, verifs, rules, metrics };
  return SR.demoData;
}

/* ── API 封装（演示模式拦截） ── */
async function srGet(path) {
  if (SR.demo) return srDemoGet(path);
  return api(path, 15000);
}
async function srSend(path, body, method) {
  if (SR.demo) {
    srToast('演示模式：仅预览交互，未写入数据库', 'warn');
    return { ok: true, demo: true };
  }
  return api(path, 20000, {
    method: method || 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
}
function srDemoGet(path) {
  const D = srBuildDemo();
  if (path.startsWith('/api/sentiment/time_context')) {
    return { now: new Date().toLocaleString('sv'), effective_trade_date: SR.today,
      next_trade_date: srNextTradeDay(SR.today), is_preopen_window: false };
  }
  if (path.startsWith('/api/sentiment/snapshot')) return Object.assign({}, D.days[D.days.length - 1], { trade_date: D.days[D.days.length - 1].trade_date });
  if (path.startsWith('/api/sentiment/sequence')) {
    const n = parseInt((path.match(/days=(\d+)/) || [])[1] || 30);
    return { days: D.days.slice(-n), count: Math.min(n, D.days.length) };
  }
  if (path.startsWith('/api/sentiment/carriers/')) {
    const d = path.split('/').pop();
    return D.carriers.filter(c => c.trade_date === d);
  }
  if (path.startsWith('/api/sentiment/review/')) {
    const d = path.split('/').pop();
    return D.days.find(x => x.trade_date === d) || {};
  }
  if (path.startsWith('/api/sentiment/plans')) return D.plans;
  if (path.startsWith('/api/sentiment/verifications')) return D.verifs;
  if (path.startsWith('/api/sentiment/rules')) return D.rules;
  if (path.startsWith('/api/sentiment/metrics')) return D.metrics;
  if (path.startsWith('/api/sentiment/similar/')) {
    const d = path.split('/')[4];
    const target = D.days.find(x => x.trade_date === d) || D.days[D.days.length - 1];
    const scored = D.days.filter(x => x.trade_date !== target.trade_date).map(x => {
      const dist = Math.pow((x.break_rate - target.break_rate), 2) +
        Math.pow((x.ly_premium - target.ly_premium), 2) * 10 +
        Math.pow((x.max_board - target.max_board), 2) * 20;
      return { dist, x };
    }).sort((a, b) => a.dist - b.dist).slice(0, 5).map(o => o.x);
    return { target, similar: scored };
  }
  return {};
}

/* ── 页面骨架 ── */
async function loadSentimentReview() {
  if (SR.loaded) return;
  SR.loaded = true;
  window._srLoaded = true;
  SR.today = srTodayStr();
  const container = $('#sentiment-content');
  if (!container) return;

  container.innerHTML = `
    <div class="sr-topbar">
      <div class="sr-topbar-left">
        <span class="sr-title">情绪流赚钱效应复盘</span>
        <span class="sr-version">v2.1</span>
      </div>
      <div class="sr-topbar-right">
        <button class="btn" onclick="srCollectToday()">↻ 重新采集 T1</button>
      </div>
    </div>

    <div class="card" style="margin-bottom:14px;">
      <div class="sr-t1-head">
        <div class="card-title" style="margin:0;">今日客观盘面 · T1 <span class="sr-auto-tag">全自动</span></div>
        <div id="sr-t1-status"></div>
      </div>
      <div id="sr-t1-alert"></div>
      <div id="sr-today"></div>
    </div>

    <div class="sr-tabs" id="sr-tabs">
      <button class="sr-tab active" data-tab="seq" onclick="srSwitchTab('seq')">① 情绪周期序列</button>
      <button class="sr-tab" data-tab="review" onclick="srSwitchTab('review')">② 每日复盘 T2·T3</button>
      <button class="sr-tab" data-tab="plan" onclick="srSwitchTab('plan')">③ 明日预案 T4</button>
      <button class="sr-tab" data-tab="verify" onclick="srSwitchTab('verify')">④ 结果回填 T5</button>
      <button class="sr-tab" data-tab="rules" onclick="srSwitchTab('rules')">⑤ 规则库 T6</button>
      <button class="sr-tab" data-tab="logic" onclick="srSwitchTab('logic')">⑥ 口径 &amp; 待讨论</button>
    </div>
    <div id="sr-tab-body"></div>
  `;
  $('#sentiment-loading').style.display = 'none';
  container.style.display = 'block';

  // 侧边栏高亮修正
  document.querySelectorAll('.nav-item').forEach(n => {
    if ((n.getAttribute('onclick') || '').includes('sentiment_review')) n.classList.add('active');
  });

  await srLoadTimeCtx();
  await srRefreshT1();
  await srSwitchTab('seq');
}

/* ── 交易日时间口径：归属交易日跟随开盘边界 ── */
async function srLoadTimeCtx() {
  try {
    const c = await srGet('/api/sentiment/time_context');
    SR.tradeDate = c.effective_trade_date || SR.today;
    SR.targetDate = c.next_trade_date || srNextTradeDay(SR.tradeDate);
    SR.preopen = !!c.is_preopen_window;
  } catch (e) {
    SR.tradeDate = SR.today;
    SR.targetDate = srNextTradeDay(SR.today);
    SR.preopen = false;
  }
}

async function srToggleDemo() {
  SR.demo = !SR.demo;
  SR.demoData = null;
  $('#sr-demo-banner').style.display = SR.demo ? 'block' : 'none';
  $('#sr-demo-btn').innerHTML = SR.demo ? '■ 退出演示数据' : '▶ 切换演示数据';
  await srRefreshT1();
  await srSwitchTab(SR.tab);
}

function srSwitchTab(tab) {
  SR.tab = tab;
  document.querySelectorAll('.sr-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  const body = $('#sr-tab-body');
  body.innerHTML = '<div class="loading">加载中</div>';
  const renders = {
    seq: srTabSeq, review: srTabReview, plan: srTabPlan,
    verify: srTabVerify, rules: srTabRules, logic: srTabLogic
  };
  srLoadTimeCtx().then(() => (renders[tab] || srTabSeq)());
}

/* ── T1 今日盘面 ── */
async function srRefreshT1() {
  const el = $('#sr-today'), stEl = $('#sr-t1-status'), alEl = $('#sr-t1-alert');
  if (!el) return;
  el.innerHTML = '<div class="loading">加载中</div>';
  try {
    const d = await srGet('/api/sentiment/snapshot?date=' + (SR.tradeDate || SR.today));
    const st = d.source_status || 'ok';
    const stBadge = st === 'ok' ? '<span class="sr-badge ok">数据完整</span>'
      : st === 'partial' ? '<span class="sr-badge warn">部分缺失</span>'
      : st === 'missing' ? '<span class="sr-badge warn">未采集</span>'
      : '<span class="sr-badge err">数据缺失</span>';
    stEl.innerHTML = `<span class="sr-t1-date">${srDate(d.trade_date)}</span> ${stBadge}` +
      (SR.preopen ? ' <span class="sr-hint">⏱ 盘前补录窗口：显示归属交易日盘面</span>' : '');
    if (st === 'missing') {
      el.innerHTML = '<div class="sr-empty">该交易日 T1 尚未采集（当日收盘后由定时任务自动采集，或点右上角「重新采集 T1」）</div>';
      alEl.innerHTML = '';
      return;
    }
    // 规则6：source_status=fail 强制横幅
    alEl.innerHTML = st === 'fail'
      ? '<div class="sr-alert err">⚠️ 客观数据缺失（source_status=fail）：今日 T1 指标不可信，主观复盘可照常录入但将被标记</div>'
      : st === 'partial'
        ? '<div class="sr-alert warn">⚠️ 部分数据源缺失（source_status=partial）：口径复核时请以 raw_json 为准</div>' : '';

    const sc = d.sentiment_score_obj;
    const scColor = sc >= 60 ? '#059669' : sc >= 40 ? '#d97706' : '#dc2626';
    // 昨日对比数据（市场快照往前取一天）
    let prev = null;
    try {
      const seq2 = await srGet('/api/sentiment/sequence?days=2');
      const arr = (seq2 && seq2.days) || [];
      if (arr.length >= 2 && arr[arr.length - 1].trade_date === d.trade_date) prev = arr[arr.length - 2];
    } catch (e) { }
    const cp = (key, fn) => (prev && prev[key] != null) ? ` <span class="sr-cmp">（昨日 ${fn ? fn(prev[key]) : prev[key]}）</span>` : '';
    el.innerHTML = `
      <div class="grid grid-4">
        <div class="metric"><div class="metric-value" style="color:${scColor};">${srFmt(sc, 0)}</div><div class="metric-label">客观情绪分</div><div class="metric-change" style="color:var(--gray-400);">复盘口径 0.4/0.6${cp('sentiment_score_obj', v => srFmt(v, 0))}</div></div>
        <div class="metric"><div class="metric-value">${d.limit_up_count ?? '-'}${cp('limit_up_count')}</div><div class="metric-label">涨停</div><div class="metric-change ${(d.limit_down_count || 0) > 15 ? 'down' : 'up'}">跌停 ${d.limit_down_count ?? '-'}${cp('limit_down_count')}</div></div>
        <div class="metric"><div class="metric-value">${srFmt(d.break_rate, 1)}%${cp('break_rate', v => srFmt(v, 1) + '%')}</div><div class="metric-label">炸板率</div><div class="metric-change" style="color:var(--gray-400);">炸板 ${d.break_count ?? '-'}${cp('break_count')}</div></div>
        <div class="metric"><div class="metric-value">${d.max_board ?? '-'} 板${cp('max_board', v => v + ' 板')}</div><div class="metric-label">最高连板</div><div class="metric-change" style="color:var(--gray-400);">2板+ ${d.board2plus_count ?? '-'}${cp('board2plus_count')} · 3板+ ${d.board3plus_count ?? '-'}${cp('board3plus_count')}</div></div>
      </div>
      <div class="grid grid-4" style="margin-top:6px;">
        <div class="metric"><div class="metric-value" style="font-size:20px;">${srPct(d.ly_premium)}</div><div class="metric-label">昨日涨停溢价</div><div class="metric-change" style="color:var(--gray-400);">连板 ${srPct(d.ly_premium_cont)}</div></div>
        <div class="metric"><div class="metric-value" style="font-size:20px;">${d.big_loss_count ?? '-'}${cp('big_loss_count')}</div><div class="metric-label">大面家数</div><div class="metric-change" style="color:var(--gray-400);">昨涨停今≤-5%</div></div>
        <div class="metric"><div class="metric-value" style="font-size:20px;">${srFmt(d.turnover_yi, 0)} 亿${cp('turnover_yi', v => srFmt(v, 0) + ' 亿')}</div><div class="metric-label">两市成交额</div></div>
        <div class="metric"><div class="metric-value" style="font-size:20px;">${d.up_count ?? '-'} / ${d.down_count ?? '-'}${cp('up_count')}</div><div class="metric-label">上涨 / 下跌</div><div class="metric-change" style="color:var(--gray-400);">${srPct(d.sh_pct)} 上证${cp('sh_pct', srPct)} · ${srPct(d.cyb_pct)} 创业板${cp('cyb_pct', srPct)}</div></div>
      </div>
    `;
  } catch (e) {
    stEl.innerHTML = '';
    el.innerHTML = `<div class="loading">T1 加载失败: ${e.message}</div>`;
  }
}

async function srCollectToday() {
  if (SR.preopen) {
    srToast('盘前补录窗口：归属交易日 ' + srDate(SR.tradeDate) + ' 的 T1 已于收盘后采集，无需重采', 'warn');
    return;
  }
  const el = $('#sr-today');
  if (el) el.innerHTML = '<div class="loading">采集中，请稍候（约30秒）…</div>';
  try {
    await srSend('/api/sentiment/snapshot/collect', {}, 'POST');
    await srRefreshT1();
    if (SR.tab === 'seq') await srTabSeq();
    srToast('T1 采集完成');
  } catch (e) {
    if (el) el.innerHTML = `<div class="loading">采集失败: ${e.message}</div>`;
  }
}

/* ── ① 情绪周期序列 ── */
async function srTabSeq() {
  const body = $('#sr-tab-body');
  body.innerHTML = `
    <div class="card" style="margin-bottom:14px;">
      <div class="sr-row-between">
        <div class="card-title" style="margin:0;">情绪周期序列 <span class="sr-auto-tag">客观分曲线 × 周期色带</span></div>
        <div class="sr-chip-row">
          ${[30, 60, 90].map(n => `<button class="sr-chip-btn ${SR.seqDays === n ? 'active' : ''}" onclick="srSeqDays(${n})">${n}日</button>`).join('')}
          <span class="sr-divider"></span>
          <button class="sr-chip-btn active" data-ind="max_board" onclick="srToggleInd(this)">最高连板</button>
          <button class="sr-chip-btn active" data-ind="break_rate" onclick="srToggleInd(this)">炸板率</button>
          <button class="sr-chip-btn" data-ind="ly_premium" onclick="srToggleInd(this)">涨停溢价</button>
        </div>
      </div>
      <div id="sr-seq-box" style="height:320px;position:relative;margin-top:10px;"><canvas id="sr-seq-chart"></canvas></div>
      <div id="sr-seq-legend" class="sr-legend"></div>
      <div id="sr-seq-hint"></div>
    </div>

    <div class="card">
      <div class="sr-row-between">
        <div class="card-title" style="margin:0;">相似日检索 <span class="sr-auto-tag">T1 指向量欧氏距离</span></div>
        <div class="sr-chip-row">
          <input id="sr-similar-date" type="date" class="sr-input" style="width:150px;">
          <button class="btn" style="padding:5px 14px;font-size:12px;" onclick="srLoadSimilar()">检索</button>
        </div>
      </div>
      <div id="sr-similar" style="margin-top:10px;"></div>
    </div>
  `;
  const ds = $('#sr-similar-date');
  if (ds) ds.value = srDate(SR.today);
  await srDrawSeq();
  await srLoadSimilar();
}

function srSeqDays(n) { SR.seqDays = n; srTabSeq(); }
function srToggleInd(btn) {
  btn.classList.toggle('active');
  srDrawSeq();
}

async function srDrawSeq() {
  const el = $('#sr-seq-chart');
  if (!el) return;
  try {
    const data = await srGet(`/api/sentiment/sequence?days=${SR.seqDays}`);
    const days = data.days || [];
    const oldEmpty = $('#sr-seq-empty');
    if (oldEmpty) oldEmpty.remove();
    if (days.length < 2) {
      el.style.display = 'none';
      el.parentElement.insertAdjacentHTML('beforeend',
        '<div class="sr-empty" id="sr-seq-empty">序列数据不足（需 ≥2 个交易日）。T1 自动采集每日 15:30 落库，或切换右上角「演示数据」预览效果。</div>');
      $('#sr-seq-legend').innerHTML = '';
      $('#sr-seq-hint').innerHTML = '';
      return;
    }
    el.style.display = 'block';
    const labels = days.map(d => srMD(d.trade_date));
    const show = {};
    document.querySelectorAll('[data-ind]').forEach(b => show[b.dataset.ind] = b.classList.contains('active'));

    const datasets = [
      { label: '客观情绪分', data: days.map(d => d.sentiment_score_obj ?? null), borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,.10)', fill: true, tension: .3, pointRadius: 2.5, yAxisID: 'y', borderWidth: 2 },
      { label: '主观分', data: days.map(d => d.subjective_score ?? null), borderColor: '#8b5cf6', backgroundColor: 'transparent', borderDash: [3, 3], tension: .3, pointRadius: 0, yAxisID: 'y', borderWidth: 1.5 },
    ];
    if (show.max_board) datasets.push({ label: '最高连板', data: days.map(d => d.max_board ?? null), borderColor: '#ef4444', backgroundColor: 'transparent', tension: .3, pointRadius: 2, yAxisID: 'y1', borderWidth: 1.5 });
    if (show.break_rate) datasets.push({ label: '炸板率%', data: days.map(d => d.break_rate ?? null), borderColor: '#f59e0b', backgroundColor: 'transparent', borderDash: [5, 4], tension: .3, pointRadius: 2, yAxisID: 'y2', borderWidth: 1.5 });
    if (show.ly_premium) datasets.push({ label: '涨停溢价%', data: days.map(d => d.ly_premium ?? null), borderColor: '#10b981', backgroundColor: 'transparent', tension: .3, pointRadius: 2, yAxisID: 'y2', borderWidth: 1.5 });

    if (SR.charts.seq) { SR.charts.seq.destroy(); SR.charts.seq = null; }
    SR.charts.seq = new Chart(el, {
      type: 'line',
      data: { labels, datasets },
      plugins: [{
        id: 'srBands',
        beforeDatasetsDraw(chart) {
          const { ctx, chartArea, scales } = chart;
          if (!chartArea) return;
          const x = scales.x;
          const half = (x.width / days.length) / 2;
          let i = 0;
          while (i < days.length) {
            const p = days[i].cycle_phase;
            if (!p) { i++; continue; }
            let j = i;
            while (j + 1 < days.length && days[j + 1].cycle_phase === p) j++;
            const x1 = x.getPixelForValue(i) - half;
            const x2 = x.getPixelForValue(j) + half;
            ctx.save();
            ctx.fillStyle = srPhaseBg(p);
            ctx.fillRect(x1, chartArea.top, x2 - x1, chartArea.bottom - chartArea.top);
            if (j - i >= 1) {
              ctx.fillStyle = srPhaseColor(p);
              ctx.font = '10px sans-serif';
              ctx.textAlign = 'center';
              ctx.globalAlpha = .75;
              ctx.fillText(p, (x1 + x2) / 2, chartArea.top + 12);
            }
            ctx.restore();
            i = j + 1;
          }
        }
      }],
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'top', labels: { boxWidth: 14, padding: 10, font: { size: 11 } } },
          tooltip: {
            callbacks: {
              afterBody(items) {
                const i = items[0] && items[0].dataIndex;
                if (i == null || !days[i]) return '';
                const d = days[i];
                let s = '周期: ' + (d.cycle_phase || '-') + '  赚钱: ' + (d.money_effect || '-') + '  亏钱: ' + (d.loss_effect || '-') + '\n';
                if (d.today_insight) s += '判断: ' + d.today_insight;
                return s;
              }
            }
          }
        },
        scales: {
          x: { ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 16, font: { size: 10 } } },
          y: { position: 'left', title: { display: true, text: '情绪分', font: { size: 10 } }, min: 0, max: 100 },
          y1: { position: 'right', title: { display: true, text: '连板', font: { size: 10 } }, min: 0, max: 12, grid: { drawOnChartArea: false } },
          y2: { position: 'right', title: { display: true, text: '%', font: { size: 10 } }, min: -10, max: 100, grid: { drawOnChartArea: false } },
        }
      }
    });

    // 图例 + 连续同阶段提示（规则5）
    const phases = [...new Set(days.filter(d => d.cycle_phase).map(d => d.cycle_phase))];
    $('#sr-seq-legend').innerHTML = '<span class="sr-legend-label">周期色带:</span>' + phases.map(p =>
      `<span class="sr-chip" style="background:${srPhaseBg(p)};color:${srPhaseColor(p)};border:1px solid ${srPhaseColor(p)}33;">${p}</span>`
    ).join('');

    let streak = 1, last = null, hint = '';
    for (let i = days.length - 1; i >= 0; i--) {
      const p = days[i].cycle_phase;
      if (!p) break;
      if (last === null) { last = p; streak = 1; }
      else if (p === last) streak++;
      else break;
    }
    if (streak >= 3) hint = `<div class="sr-alert warn">⚠️ 校验提示（规则5）：「${last}」已连续 ${streak} 日 —— 是否已进入新阶段？请在今日复盘中确认。</div>`;
    $('#sr-seq-hint').innerHTML = hint;
  } catch (e) {
    el.innerHTML = `<div class="sr-empty">加载失败: ${e.message}</div>`;
  }
}

async function srLoadSimilar() {
  const el = $('#sr-similar');
  if (!el) return;
  const input = $('#sr-similar-date');
  let d = (input && input.value || '').replace(/-/g, '');
  if (!d) d = SR.today;
  try {
    const r = await srGet(`/api/sentiment/similar/${d}?top_n=5`);
    if (!r.similar || !r.similar.length) {
      el.innerHTML = '<div class="sr-empty">暂无相似日（需积累 ≥2 个交易日数据；历史回填后此处立即可用）</div>';
      return;
    }
    el.innerHTML = `
      <div class="sr-note">以 <b>${srDate(d)}</b>（客观分 ${srFmt(r.target && r.target.sentiment_score_obj, 0)}）为基准，历史最相似 5 日 —— 点击行查看当日复盘 / 预案 / 结果：</div>
      <table class="table">
        <tr><th>日期</th><th>客观分</th><th>炸板率</th><th>涨停溢价</th><th>最高板</th><th>周期</th><th>当日判断</th></tr>
        ${r.similar.map(s => `
          <tr style="cursor:pointer;" onclick="srSimilarDetail('${s.trade_date}')">
            <td><b>${srDate(s.trade_date)}</b></td>
            <td style="font-weight:600;">${srFmt(s.sentiment_score_obj, 0)}</td>
            <td>${srFmt(s.break_rate, 1)}%</td>
            <td>${srPct(s.ly_premium)}</td>
            <td>${s.max_board ?? '-'}</td>
            <td>${srPhaseChip(s.cycle_phase)}</td>
            <td style="max-width:220px;font-size:12px;color:var(--gray-500);">${s.today_insight || '-'}</td>
          </tr>`).join('')}
      </table>
      <div id="sr-similar-detail"></div>`;
  } catch (e) {
    el.innerHTML = `<div class="sr-empty">检索失败: ${e.message}</div>`;
  }
}

async function srSimilarDetail(date) {
  const el = $('#sr-similar-detail');
  if (!el) return;
  try {
    const [review, plans] = await Promise.all([srGet(`/api/sentiment/review/${date}`), srGet('/api/sentiment/plans')]);
    const dayPlans = (plans || []).filter(p => p.base_date === date);
    const verifs = await srGet('/api/sentiment/verifications');
    el.innerHTML = `
      <div class="sr-detail-box">
        <div class="sr-detail-title">${srDate(date)} 当日详情</div>
        <div class="sr-note">复盘: ${review.today_insight || '-'}${review.cycle_phase ? '（' + review.cycle_phase + '）' : ''}</div>
        ${dayPlans.length ? dayPlans.map(p => {
          const v = (verifs || []).find(v => v.plan_id === p.plan_id);
          return `<div class="sr-note">预案: ${p.plan_direction} · 仓位${p.position_level}${p.plan_text ? ' · 「' + p.plan_text + '」' : ''} · 证伪条件「${p.falsify_condition}」
            → ${v ? `<b style="color:${v.plan_result === '兑现' ? '#059669' : v.plan_result === '证伪' ? '#dc2626' : '#d97706'};">${v.plan_result}</b>（${v.score >= 0 ? '+' : ''}${v.score}分）` : '<span style="color:var(--gray-400);">未回填</span>'}</div>`;
        }).join('') : '<div class="sr-note" style="color:var(--gray-400);">当日无预案记录</div>'}
      </div>`;
  } catch (e) {
    el.innerHTML = `<div class="sr-empty">加载失败: ${e.message}</div>`;
  }
}

/* ── ② 每日复盘 T2·T3 ── */
async function srTabReview() {
  const body = $('#sr-tab-body');
  const today = SR.tradeDate || SR.today;
  SR.reviewDate = SR.reviewDate || today;
  body.innerHTML = `
    <div class="sr-grid-2">
      <div class="card">
        <div class="card-title">主观复盘 · T2 <span class="sr-manual-tag">人工 3 分钟</span></div>
        <div class="sr-row-between" style="margin:-6px 0 8px;">
          <div class="sr-hint">⏱ 归属交易日 <b style="color:var(--primary,#4f46e5);">${srDate(today)}</b>${SR.preopen ? '（盘前补录窗口）' : ''} · 补填历史请改右边日期</div>
          <div class="sr-chip-row">
            <input id="sr-review-date" type="date" class="sr-input" style="width:158px;"
              value="${srDate(SR.reviewDate)}" max="${srDate(SR.today)}" onchange="srSwitchReviewDate(this.value)">
          </div>
        </div>
        <div id="sr-review-date-note" class="sr-hint" style="margin:-2px 0 8px;"></div>
        <div class="sr-form">
          <div class="sr-form-grid">
            <div class="sr-field"><label>周期阶段 <b class="req">*</b></label>
              <select id="sr-cycle" class="sr-input">${srPhaseOptions()}</select></div>
            <div class="sr-field"><label>判定置信度 <b class="req">*</b></label>
              <select id="sr-conf" class="sr-input"><option value="1">1 拿不准</option><option value="3" selected>3 一般</option><option value="5">5 极确定</option></select></div>
            <div class="sr-field"><label>赚钱效应 <b class="req">*</b></label>
              <select id="sr-money" class="sr-input">${['强', '中', '弱'].map(v => `<option ${v === '中' ? 'selected' : ''}>${v}</option>`).join('')}</select></div>
            <div class="sr-field"><label>亏钱效应 <b class="req">*</b></label>
              <select id="sr-loss" class="sr-input">${['强', '中', '弱'].map(v => `<option ${v === '中' ? 'selected' : ''}>${v}</option>`).join('')}</select></div>
            <div class="sr-field"><label>自我状态 <b class="req">*</b></label>
              <select id="sr-self" class="sr-input">${['冷静', '上头', '踏空焦虑', '恐慌', '报复性交易冲动'].map(s => `<option>${s}</option>`).join('')}</select></div>
            <div class="sr-field"><label>主观情绪分（选填）</label>
              <input id="sr-subj" type="number" min="0" max="100" placeholder="0-100" class="sr-input"></div>
          </div>
          <div class="sr-field"><label>赚钱效应在哪 <b class="req">*</b></label>
            <input id="sr-money-where" class="sr-input" placeholder="如：AI算力PCB补涨梯队、固态电池设备（字数不限）"></div>
          <div class="sr-field"><label>亏钱效应在哪 <b class="req">*</b></label>
            <input id="sr-loss-where" class="sr-input" placeholder="如：高位断板股、老题材反核失败（字数不限）"></div>
          <div class="sr-field"><label>今日核心判断 <b class="req">*</b></label>
            <textarea id="sr-insight" rows="3" class="sr-input" placeholder="说清今天最重要的一件事（字数不限）"></textarea></div>
          <div class="sr-field"><label>最意外的事（选填）</label>
            <textarea id="sr-unexpected" rows="2" class="sr-input"></textarea></div>
          <div class="sr-field"><label>主客观背离说明（选填）</label>
            <textarea id="sr-divergence" rows="1" class="sr-input" placeholder="客观分与主观感受不一致时注明"></textarea></div>

          <div class="sr-rules-box">
            <div class="sr-rules-title">校验规则（保存时执行）</div>
            <div>· 规则2：置信度5 且 赚钱/亏钱效应同为「强」→ 矛盾提示，需二次确认</div>
            <div>· 规则3：当日无情绪载体 → 须在核心判断中注明（缺载体日）</div>
            <div>· 规则6：T1 source_status=fail 当日 → 本条复盘将带「客观数据缺失」标记</div>
          </div>
          <button class="btn sr-btn-main" onclick="srSaveReview('${today}')">保存主观复盘</button>
          <div id="sr-review-msg" class="sr-msg"></div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">情绪载体 · T3 <span class="sr-manual-tag">1~多条/日</span></div>
        <div class="sr-form">
          <div class="sr-form-grid">
            <div class="sr-field"><label>代码</label><input id="sr-c-code" class="sr-input" placeholder="如 600825"></div>
            <div class="sr-field"><label>名称</label><input id="sr-c-name" class="sr-input" placeholder="如 新华传媒"></div>
            <div class="sr-field"><label>载体角色</label>
              <select id="sr-c-role" class="sr-input">${['总龙头', '高度板', '补涨龙', '卡位股', '中军', '空间板', '权重龙头', '情绪先锋'].map(r => `<option>${r}</option>`).join('')}</select></div>
            <div class="sr-field"><label>载体状态</label>
              <select id="sr-c-status" class="sr-input">${['涨停', '大涨', '炸板', '大面', '核按钮', '断板'].map(s => `<option>${s}</option>`).join('')}</select></div>
            <div class="sr-field"><label>连板高度</label><input id="sr-c-board" type="number" min="0" class="sr-input" placeholder="0"></div>
            <div class="sr-field"><label>备注（选填）</label><input id="sr-c-note" class="sr-input"></div>
          </div>
          <label class="sr-check"><input id="sr-c-anchor" type="checkbox"> 设为当日情绪锚（每日仅 1 个，自动替换）</label>
          <button class="btn sr-btn-main" onclick="srAddCarrier()">添加载体</button>
          <div id="sr-carrier-msg" class="sr-msg"></div>
          <div id="sr-carrier-list" style="margin-top:12px;"></div>
          <div id="sr-calib-box" style="margin-top:14px;"></div>
        </div>
      </div>
    </div>
  `;
  // 字数计数
  const bind = (id, cntId, max) => {
    const t = $(id); if (!t) return;
    t.addEventListener('input', () => { $(cntId).textContent = t.value.length + '/' + max; });
  };
  bind('#sr-insight', '#sr-insight-cnt', 40);
  bind('#sr-unexpected', '#sr-unexp-cnt', 50);
  bind('#sr-money-where', '#sr-mw-cnt', 30);
  bind('#sr-loss-where', '#sr-lw-cnt', 30);
  await srLoadCarriers();
  await srPrefillReview();
  srLoadCalibration();
}

/* 切换复盘日期（支持补填/修改历史） */
function srSwitchReviewDate(val) {
  const d = (val || '').replace(/-/g, '');
  if (!d) return;
  SR.reviewDate = d;
  srLoadCarriers();
  srPrefillReview();
}

/* 加载所选日期已有的复盘并预填表单 */
async function srPrefillReview() {
  const note = $('#sr-review-date-note');
  const msg = $('#sr-review-msg');
  if (msg) msg.innerHTML = '';
  const d = SR.reviewDate || SR.today;
  const wk = new Date(d.slice(0, 4), parseInt(d.slice(4, 6)) - 1, parseInt(d.slice(6, 8))).getDay();
  const wkWarn = srIsTradeDay(d) ? '' : ' ⚠️ 所选日期不是交易日（周末/节假日）';
  try {
    const r = await srGet('/api/sentiment/review/' + d) || {};
    const set = (id, v) => { const el = $(id); if (el && v != null) el.value = v; };
    const clear = (id) => { const el = $(id); if (el) el.value = ''; };
    ['#sr-cycle', '#sr-conf', '#sr-money', '#sr-loss', '#sr-self', '#sr-subj',
      '#sr-insight', '#sr-unexpected', '#sr-divergence', '#sr-money-where', '#sr-loss-where'].forEach(clear);
    if (r.trade_date) {
      set('#sr-cycle', r.cycle_phase); set('#sr-conf', r.phase_confidence);
      set('#sr-money', r.money_effect); set('#sr-loss', r.loss_effect);
      set('#sr-self', r.self_state); set('#sr-subj', r.subjective_score);
      set('#sr-insight', r.today_insight); set('#sr-unexpected', r.unexpected);
      set('#sr-divergence', r.divergence_note);
      set('#sr-money-where', r.money_effect_where); set('#sr-loss-where', r.loss_effect_where);
      if (note) note.innerHTML = `✅ 已加载 <b>${srDate(d)}</b> 的历史复盘 —— 修改后保存将覆盖原记录${wkWarn}`;
    } else {
      if (note) note.innerHTML = `📝 <b>${srDate(d)}</b> 暂无复盘记录，可在此补填${wkWarn}`;
    }
    // 刷新字数计数
    [['#sr-insight', '#sr-insight-cnt', 40], ['#sr-unexpected', '#sr-unexp-cnt', 50],
    ['#sr-money-where', '#sr-mw-cnt', 30], ['#sr-loss-where', '#sr-lw-cnt', 30]].forEach(([i, c, m]) => {
      const t = $(i), cnt = $(c);
      if (t && cnt) cnt.textContent = (t.value || '').length + '/' + m;
    });
  } catch (e) {
    if (note) note.innerHTML = `<span style="color:#dc2626;">历史复盘加载失败: ${e.message}</span>`;
  }
}

async function srLoadCarriers() {
  const el = $('#sr-carrier-list');
  if (!el) return;
  try {
    const list = await srGet(`/api/sentiment/carriers/${SR.reviewDate || SR.tradeDate || SR.today}`);
    SR.carriers = list || [];
    if (!SR.carriers.length) {
      el.innerHTML = '<div class="sr-empty">今日暂无载体记录</div>';
      return;
    }
    el.innerHTML = `
      <table class="table">
        <tr><th>情绪锚</th><th>代码</th><th>名称</th><th>角色</th><th>高度</th><th>状态</th><th></th></tr>
        ${SR.carriers.map(c => `
          <tr>
            <td>${c.is_anchor ? '⭐' : ''}</td>
            <td>${c.code}</td><td><b>${c.name}</b></td>
            <td>${srPhaseChip(c.carrier_role)}</td>
            <td>${c.board_height ?? '-'} 板</td>
            <td>${c.carrier_status}</td>
            <td><button class="sr-link-btn" onclick="srDelCarrier(${c.id})">删除</button></td>
          </tr>`).join('')}
      </table>`;
  } catch (e) {
    el.innerHTML = `<div class="sr-empty">加载失败: ${e.message}</div>`;
  }
}

async function srAddCarrier() {
  const msg = $('#sr-carrier-msg');
  const code = $('#sr-c-code').value.trim(), name = $('#sr-c-name').value.trim();
  if (!code || !name) { msg.innerHTML = '<span style="color:#dc2626;">代码与名称必填</span>'; return; }
  try {
    await srSend('/api/sentiment/carrier', {
      trade_date: SR.reviewDate || SR.tradeDate || SR.today, code, name,
      carrier_role: $('#sr-c-role').value,
      board_height: parseInt($('#sr-c-board').value || 0),
      carrier_status: $('#sr-c-status').value,
      is_anchor: $('#sr-c-anchor').checked,
      note: $('#sr-c-note').value
    });
    msg.innerHTML = '<span style="color:#059669;">已添加 ✓ 已同步加入实时监测重点关注（盘中异动将自动提醒）</span>';
    await srLoadCarriers();
  } catch (e) {
    msg.innerHTML = `<span style="color:#dc2626;">失败: ${e.message}</span>`;
  }
}

async function srDelCarrier(id) {
  try {
    await srSend(`/api/sentiment/carrier/${id}`, {}, 'DELETE');
    await srLoadCarriers();
  } catch (e) { srToast('删除失败: ' + e.message, 'err'); }
}

let srReviewConfirmOnce = false;
async function srSaveReview(today) {
  const msg = $('#sr-review-msg');
  const insight = $('#sr-insight').value.trim();
  if (!insight) { msg.innerHTML = '<span style="color:#dc2626;">今日核心判断必填</span>'; return; }
  const conf = parseInt($('#sr-conf').value);
  const money = $('#sr-money').value, loss = $('#sr-loss').value;
  const mWhere = $('#sr-money-where').value.trim(), lWhere = $('#sr-loss-where').value.trim();
  if (!mWhere || !lWhere) {
    msg.innerHTML = '<span style="color:#dc2626;">赚钱效应在哪 / 亏钱效应在哪 必填（每日需定位到具体方向）</span>';
    return;
  }
  if (conf === 5 && money === '强' && loss === '强') {
    if (!srReviewConfirmOnce) {
      srReviewConfirmOnce = true;
      msg.innerHTML = '<span style="color:#d97706;">⚠️ 规则2 矛盾提示：置信度 5 但赚钱/亏钱效应同为「强」。确认无误请再点一次保存。</span>';
      return;
    }
    srReviewConfirmOnce = false;
  }
  // 规则3：无载体软提醒
  if (!SR.carriers.length && !insight.includes('无载体') && !insight.includes('缺载体')) {
    msg.innerHTML = '<span style="color:#d97706;">⚠️ 规则3 提示：今日暂无载体记录，请在核心判断中注明（或先在右侧添加载体）。确认后再次点击保存。</span>';
    SR.carriers = [{ _warned: true }];
    return;
  }
  try {
    await srSend('/api/sentiment/review', {
      trade_date: SR.reviewDate || today, cycle_phase: $('#sr-cycle').value, phase_confidence: conf,
      money_effect: money, loss_effect: loss,
      money_effect_where: mWhere, loss_effect_where: lWhere,
      self_state: $('#sr-self').value,
      today_insight: insight, unexpected: $('#sr-unexpected').value,
      subjective_score: $('#sr-subj').value ? parseInt($('#sr-subj').value) : null,
      divergence_note: $('#sr-divergence').value
    });
    msg.innerHTML = '<span style="color:#059669;">复盘已保存 ✓（' + srDate(SR.reviewDate || today) + '）</span>';
  } catch (e) {
    msg.innerHTML = `<span style="color:#dc2626;">保存失败: ${e.message}</span>`;
  }
}

/* ── ③ 明日预案 T4 ── */
async function srTabPlan() {
  const body = $('#sr-tab-body');
  const base = SR.reviewDate || SR.tradeDate || SR.today;
  SR.scenarios = [];
  let target = SR.targetDate;
  try {
    const c = await srGet('/api/sentiment/time_context?base_date=' + base);
    if (c && c.next_trade_date) target = c.next_trade_date;
  } catch (e) { }
  body.innerHTML = `
    <div class="sr-grid-2">
      <div class="card">
        <div class="card-title">明日预案 · T4 <span class="sr-manual-tag">每日必写</span></div>
        <div class="sr-form">
          <div class="sr-form-grid">
            <div class="sr-field"><label>基于复盘日 <span class="sr-hint">可选历史日期补填</span></label><input id="sr-p-base" type="date" class="sr-input" value="${srDate(base)}" max="${srDate(SR.today)}" onchange="srSwitchPlanBase(this.value)"></div>
            <div class="sr-field"><label>适用交易日</label><input id="sr-p-target" class="sr-input" value="${srDate(target)}"><div class="sr-hint">按交易日历推算（含节假日），可手动修改</div></div>
            <div class="sr-field"><label>预判方向 <b class="req">*</b></label>
              <select id="sr-p-dir" class="sr-input">${['看修复', '看延续', '看分歧', '看退潮'].map(d => `<option>${d}</option>`).join('')}</select></div>
            <div class="sr-field"><label>仓位档 <b class="req">*</b></label>
              <select id="sr-p-pos" class="sr-input">
                <option value="0">0 空仓</option><option value="1">1 轻仓(≤2成)</option>
                <option value="2" selected>2 半仓(3~5成)</option><option value="3">3 重仓(&gt;5成)</option>
              </select></div>
            <div class="sr-field"><label>出手风格 <b class="req">*</b></label>
              <select id="sr-p-style" class="sr-input">${['高位投机接力', '低位接力试错', '产业趋势低吸', '空仓观望'].map(s => `<option>${s}</option>`).join('')}</select></div>
            <div class="sr-field"><label>置信度 <b class="req">*</b></label>
              <select id="sr-p-conf" class="sr-input"><option value="1">1 拿不准</option><option value="3" selected>3 一般</option><option value="5">5 极确定</option></select></div>
          </div>
          <div class="sr-field"><label>明日预案 <span class="sr-must-tag">开盘前的计划（字数不限）</span></label>
            <textarea id="sr-p-plan" rows="4" class="sr-input" placeholder="记录明日开盘前的计划：观察什么、准备怎么出手、仓位打算、注意事项……（字数不限）"></textarea></div>
          <div class="sr-field">
            <label><b class="req">*</b> 证伪条件 <span class="sr-must-tag">必填，空则拒存</span></label>
            <textarea id="sr-p-falsify" rows="2" class="sr-input" placeholder="用【开盘30分钟内可判断】的语言写，如：高标开盘5分钟内翻绿则空仓"></textarea>
          </div>

          <div class="sr-field">
            <label>分支推演（0~3条） <button class="sr-link-btn" onclick="srAddScenario()">+ 添加分支</button></label>
            <div id="sr-scenarios"></div>
          <div class="sr-field" style="margin-top:10px">
            <label>📚 历史规则参谋 <button type="button" class="sr-link-btn" onclick="srLoadRuleSuggest()">匹配历史规则</button></label>
            <div id="sr-rule-suggest" class="sr-hint">按当前周期/方向/预案文本，检索你回填沉淀过的规则——写预案时让历史教训自己跳出来</div>
          </div>
          </div>

          <div class="sr-rules-box">
            <div class="sr-rules-title">校验规则（保存时执行）</div>
            <div>· 规则1（硬性）：证伪条件为空 → 拒绝保存</div>
            <div>· 规则4：预案超 2 交易日未回填 → 标红提醒；连续 5 日未回填 → 该周数据作废标记</div>
          </div>
          <button class="btn sr-btn-main" onclick="srSavePlan()">保存预案</button>
          <div id="sr-plan-msg" class="sr-msg"></div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">预案列表（近 30 条）</div>
        <div id="sr-plan-list"></div>
      </div>
    </div>
  `;
  await srLoadPlanList();
  srLoadRuleSuggest();
}

/* 预案基准日切换：适用交易日按交易日历重算 */
async function srSwitchPlanBase(val) {
  const base = (val || '').replace(/-/g, '');
  if (!base) return;
  try {
    const c = await srGet('/api/sentiment/time_context?base_date=' + base);
    if (c && c.next_trade_date && $('#sr-p-target')) $('#sr-p-target').value = srDate(c.next_trade_date);
  } catch (e) { }
}

function srAddScenario() {
  if (SR.scenarios.length >= 3) { srToast('分支推演最多 3 条', 'warn'); return; }
  SR.scenarios.push({ if: '', then: '' });
  srRenderScenarios();
}
function srDelScenario(i) { SR.scenarios.splice(i, 1); srRenderScenarios(); }
function srRenderScenarios() {
  const el = $('#sr-scenarios');
  if (!el) return;
  el.innerHTML = SR.scenarios.map((s, i) => `
    <div class="sr-scenario-row">
      <input class="sr-input" placeholder="如果…（如：高标平开高走）" value="${s.if}" oninput="SR.scenarios[${i}].if=this.value">
      <span class="sr-arrow">→</span>
      <input class="sr-input" placeholder="那么…（如：轻仓试错首板）" value="${s.then}" oninput="SR.scenarios[${i}].then=this.value">
      <button class="sr-link-btn" onclick="srDelScenario(${i})">✕</button>
    </div>`).join('') || '<div class="sr-hint">暂无分支。分支推演是可选项，但建议关键分歧日必写。</div>';
}

async function srSavePlan() {
  const msg = $('#sr-plan-msg');
  const falsify = $('#sr-p-falsify').value.trim();
  if (!falsify) { msg.innerHTML = '<span style="color:#dc2626;">规则1：证伪条件必填，预案拒绝保存</span>'; return; }
  const target = ($('#sr-p-target').value || '').replace(/-/g, '');
  try {
    const r = await srSend('/api/sentiment/plan', {
      base_date: ($('#sr-p-base').value || '').replace(/-/g, '') || SR.tradeDate || SR.today,
      target_date: target || SR.targetDate || srNextTradeDay(SR.tradeDate || SR.today),
      plan_direction: $('#sr-p-dir').value,
      position_level: $('#sr-p-pos').value,
      operation_style: $('#sr-p-style').value,
      plan_text: ($('#sr-p-plan') ? $('#sr-p-plan').value : ''),
      falsify_condition: falsify,
      scenarios: SR.scenarios.filter(s => (s.if || s.then)),
      confidence: parseInt($('#sr-p-conf').value),
      linked_carrier_ids: SR.carriers.filter(c => c.is_anchor).map(c => c.id)
    });
    msg.innerHTML = r.ok !== false ? '<span style="color:#059669;">预案已保存 ✓</span>' : `<span style="color:#dc2626;">${r.error || '保存失败'}</span>`;
    await srLoadPlanList();
  } catch (e) {
    msg.innerHTML = `<span style="color:#dc2626;">保存失败: ${e.message}</span>`;
  }
}

async function srLoadPlanList() {
  const el = $('#sr-plan-list');
  if (!el) return;
  try {
    const plans = await srGet('/api/sentiment/plans');
    const verifs = await srGet('/api/sentiment/verifications');
    if (!plans || !plans.length) {
      el.innerHTML = '<div class="sr-empty">暂无预案记录</div>';
      return;
    }
    const vmap = {};
    (verifs || []).forEach(v => { if (!vmap[v.plan_id]) vmap[v.plan_id] = v; });
    el.innerHTML = plans.map(p => {
      const v = vmap[p.plan_id];
      const waitDays = srBizDaysBetween(p.target_date || p.base_date, SR.today);
      const overdue = !v && waitDays >= 2;
      const voidWeek = !v && waitDays >= 5;
      const scen = (() => { try { return JSON.parse(p.scenarios || '[]'); } catch (e) { return []; } })();
      return `
      <div class="sr-plan-item ${overdue ? 'overdue' : ''}">
        <div class="sr-plan-head">
          <b>${srDate(p.base_date)}</b> <span class="sr-arrow">→</span> ${srDate(p.target_date)}
          <span style="margin-left:8px;">${srPhaseChip(p.plan_direction)}</span>
          <span class="sr-chip">仓位 ${p.position_level}</span>
          <span class="sr-chip">${p.operation_style}</span>
          <span class="sr-chip">置信 ${p.confidence}</span>
          ${v ? `<span class="sr-badge ${v.plan_result === '兑现' ? 'ok' : v.plan_result === '证伪' ? 'err' : 'warn'}" style="margin-left:auto;">${v.plan_result} ${v.score >= 0 ? '+' : ''}${v.score}</span>`
          : `<span class="sr-badge ${overdue ? 'err' : 'warn'}" style="margin-left:auto;">${overdue ? `未回填 ${waitDays} 个交易日` : '待回填'}</span>`}
        </div>
        <div class="sr-plan-body">
          <div><span class="sr-label">证伪条件:</span> ${p.falsify_condition}</div>
          ${p.must_do ? `<div><span class="sr-label">必做:</span> ${p.must_do}</div>` : ''}
          ${p.must_not ? `<div><span class="sr-label">必不做:</span> ${p.must_not}</div>` : ''}
          ${scen.length ? `<div><span class="sr-label">分支:</span> ${scen.map(s => `如果${s.if}→${s.then}`).join('；')}</div>` : ''}
          ${voidWeek ? '<div class="sr-alert err" style="margin-top:6px;">⚠️ 规则4：连续 5 个交易日未回填 —— 该周数据作废标记</div>' : ''}
          ${v && v.lesson ? `<div style="margin-top:4px;color:#059669;">教训: ${v.lesson}</div>` : ''}
        </div>
      </div>`;
    }).join('');
  } catch (e) {
    el.innerHTML = `<div class="sr-empty">加载失败: ${e.message}</div>`;
  }
}

/* ── ④ 结果回填 T5 ── */
async function srTabVerify() {
  const body = $('#sr-tab-body');
  body.innerHTML = `
    <div class="card">
      <div class="card-title">结果回填 · T5 <span class="sr-manual-tag">次日收盘后 1 分钟</span>
        <span class="sr-hint" style="margin-left:12px;">按预案逐条回填；规则4 的超期标红在卡片右侧</span>
      </div>
      <div id="sr-verify-list"></div>
    </div>
  `;
  await srLoadVerifyList();
}

async function srLoadVerifyList() {
  const el = $('#sr-verify-list');
  if (!el) return;
  try {
    const plans = await srGet('/api/sentiment/plans');
    const verifs = await srGet('/api/sentiment/verifications');
    if (!plans || !plans.length) {
      el.innerHTML = '<div class="sr-empty">暂无预案可回填。先在 ③ 明日预案 中创建预案。</div>';
      return;
    }
    const vmap = {};
    (verifs || []).forEach(v => { if (!vmap[v.plan_id]) vmap[v.plan_id] = v; });
    el.innerHTML = plans.map(p => {
      const v = vmap[p.plan_id];
      const waitDays = srBizDaysBetween(p.target_date || p.base_date, SR.today);
      const overdue = !v && waitDays >= 2;
      if (v) {
        return `
        <div class="sr-plan-item">
          <div class="sr-plan-head">
            <b>${srDate(p.base_date)}</b> → ${p.plan_direction} · 「${p.falsify_condition}」
            <span class="sr-badge ${v.plan_result === '兑现' ? 'ok' : v.plan_result === '证伪' ? 'err' : 'warn'}" style="margin-left:auto;">${v.plan_result} · ${v.score >= 0 ? '+' : ''}${v.score}分</span>
          </div>
          <div class="sr-plan-body">
            <div class="sr-note">实际阶段: ${srPhaseChip(v.actual_phase)} · 证伪触发: ${v.falsify_triggered ? '是' : '否'} ${v.error_type ? ' · 错因: ' + v.error_type : ''}</div>
            ${v.lesson ? `<div class="sr-note" style="color:#059669;">教训: ${v.lesson}</div>` : ''}
          </div>
        </div>`;
      }
      return `
        <div class="sr-plan-item ${overdue ? 'overdue' : ''}">
          <div class="sr-plan-head">
            <b>${srDate(p.base_date)}</b> → ${p.plan_direction} · 「${p.falsify_condition}」
            <span class="sr-badge ${overdue ? 'err' : 'warn'}" style="margin-left:auto;">${overdue ? `超 ${waitDays} 个交易日未回填` : '待回填'}</span>
          </div>
          <div class="sr-verify-form">
            <div class="sr-form-grid">
              <div class="sr-field"><label>实际周期阶段</label>
                <select id="sr-v-phase-${p.plan_id}" class="sr-input">${srPhaseOptions()}</select></div>
              <div class="sr-field"><label>预案结果 <b class="req">*</b></label>
                <select id="sr-v-result-${p.plan_id}" class="sr-input"><option>兑现</option><option>证伪</option><option>无法判断</option></select></div>
              <div class="sr-field"><label>打分 <b class="req">*</b></label>
                <div class="sr-score-btns" id="sr-v-score-${p.plan_id}">
                  ${[-2, -1, 0, 1, 2].map(s => `<button type="button" class="sr-score-btn ${s === 0 ? 'active' : ''}" data-v="${s}" onclick="srPickScore(this)">${s > 0 ? '+' + s : s}</button>`).join('')}
                </div></div>
              <div class="sr-field"><label>错因（判断对则留空）</label>
                <select id="sr-v-err-${p.plan_id}" class="sr-input">
                  <option value="">—</option>
                  ${['方向错', '仓位错', '时机错', '执行错', '情绪干扰', '判断对执行错'].map(e => `<option>${e}</option>`).join('')}
                </select></div>
            </div>
            <div class="sr-field"><label>一句话教训 <span class="sr-counter">回填后自动沉淀入 T6 规则库</span></label>
              <input id="sr-v-lesson-${p.plan_id}" class="sr-input" placeholder="如：分歧日空仓观望是对的，修复确认要等10点后"></div>
            <div class="sr-field"><label>预案复盘（主观）<span class="sr-counter">有没有按计划执行 · 效果如何 · 为什么没执行</span></label>
              <textarea id="sr-v-preview-${p.plan_id}" rows="3" class="sr-input" placeholder="如：按计划执行了减仓，效果不错；电池那笔没按计划追高了，因为上头……（字数不限）"></textarea></div>
            <label class="sr-check"><input id="sr-v-falsify-${p.plan_id}" type="checkbox"> 证伪条件已触发（工具初判 + 人工确认）</label>
            <button class="btn sr-btn-main" onclick="srSaveVerify(${p.plan_id})">提交回填</button>
          </div>
        </div>`;
    }).join('');
  } catch (e) {
    el.innerHTML = `<div class="sr-empty">加载失败: ${e.message}</div>`;
  }
}

function srPickScore(btn) {
  btn.parentElement.querySelectorAll('.sr-score-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}

async function srSaveVerify(planId) {
  const scoreBtn = document.querySelector(`#sr-v-score-${planId} .sr-score-btn.active`);
  try {
    await srSend('/api/sentiment/verify', {
      plan_id: planId, verify_date: SR.tradeDate || SR.today,
      actual_phase: $(`#sr-v-phase-${planId}`).value,
      plan_result: $(`#sr-v-result-${planId}`).value,
      falsify_triggered: $(`#sr-v-falsify-${planId}`).checked,
      score: scoreBtn ? parseInt(scoreBtn.dataset.v) : 0,
      error_type: $(`#sr-v-err-${planId}`).value || null,
      lesson: $(`#sr-v-lesson-${planId}`).value,
      plan_review: ($(`#sr-v-preview-${planId}`) ? $(`#sr-v-preview-${planId}`).value : '')
    });
    srToast('回填成功，教训已沉淀至规则库');
    await srLoadVerifyList();
  } catch (e) {
    srToast('回填失败: ' + e.message, 'err');
  }
}

/* ── ⑤ 规则库 T6 ── */
async function srTabRules() {
  const body = $('#sr-tab-body');
  body.innerHTML = `
    <div class="card" style="margin-bottom:14px;">
      <div class="sr-row-between">
        <div class="card-title" style="margin:0;">规则库 · T6 <span class="sr-auto-tag">T5 回填自动沉淀</span></div>
        <div class="sr-chip-row" id="sr-rule-filters">
          <button class="sr-chip-btn active" data-st="" onclick="srFilterRules(this)">全部</button>
          <button class="sr-chip-btn" data-st="待验证" onclick="srFilterRules(this)">待验证</button>
          <button class="sr-chip-btn" data-st="有效" onclick="srFilterRules(this)">有效</button>
          <button class="sr-chip-btn" data-st="失效" onclick="srFilterRules(this)">失效</button>
        </div>
      </div>
      <div class="sr-hint" style="margin:8px 0;">状态流转：待验证（&lt;20 样本）→ 有效 / 失效（按命中率人工判定）· era_tag 时段标签防规则漂移</div>
      <div id="sr-rule-list"></div>
    </div>
    <div class="card">
      <div class="card-title">错因聚合 <span class="sr-auto-tag">error_type × 周期阶段</span></div>
      <div class="sr-hint" style="margin-bottom:10px;">比自由文本规则更早见效的视角：哪个阶段最容易犯哪类错</div>
      <div id="sr-error-agg"></div>
    </div>
  `;
  await srLoadRules();
  await srLoadErrorAgg();
}

function srFilterRules(btn) {
  document.querySelectorAll('#sr-rule-filters .sr-chip-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  srLoadRules();
}

async function srLoadRules() {
  const el = $('#sr-rule-list');
  if (!el) return;
  try {
    let rules = await srGet('/api/sentiment/rules');
    const active = document.querySelector('#sr-rule-filters .sr-chip-btn.active');
    const st = active ? active.dataset.st : '';
    if (st) rules = rules.filter(r => r.status === st);
    if (!rules || !rules.length) {
      el.innerHTML = '<div class="sr-empty">规则库为空。T5 回填时填写「教训」会自动沉淀为待验证规则。</div>';
      return;
    }
    el.innerHTML = rules.map(r => {
      const rate = r.sample_count > 0 ? Math.round(r.hit_count / r.sample_count * 100) : 0;
      const stCls = r.status === '有效' ? 'ok' : r.status === '失效' ? 'err' : 'warn';
      let trig = r.trigger_condition;
      try { trig = JSON.stringify(JSON.parse(trig)); } catch (e) { }
      return `
      <div class="sr-plan-item">
        <div class="sr-plan-head">
          <span class="sr-badge ${stCls}">${r.status}</span>
          <b style="margin-left:8px;">${r.rule_text}</b>
          <span class="sr-chip" style="margin-left:auto;">${r.era_tag || '-'}</span>
        </div>
        <div class="sr-plan-body">
          <div class="sr-note">触发条件: ${trig || '-'}</div>
          <div class="sr-hitbar-row">
            <div class="sr-hitbar"><div class="sr-hitbar-fill ${stCls}" style="width:${rate}%;"></div></div>
            <span class="sr-note">命中 ${r.hit_count}/${r.sample_count}（${rate}%）</span>
            <span class="sr-note" style="margin-left:auto;color:var(--gray-400);">${r.source_note || ''}</span>
          </div>
        </div>
      </div>`;
    }).join('');
  } catch (e) {
    el.innerHTML = `<div class="sr-empty">加载失败: ${e.message}</div>`;
  }
}

async function srLoadErrorAgg() {
  const el = $('#sr-error-agg');
  if (!el) return;
  try {
    const verifs = await srGet('/api/sentiment/verifications');
    const plans = await srGet('/api/sentiment/plans');
    const phaseOf = {};
    (plans || []).forEach(p => { phaseOf[p.plan_id] = p.plan_direction; });
    const errors = (verifs || []).filter(v => v.error_type);
    if (!errors.length) {
      el.innerHTML = '<div class="sr-empty">暂无错因数据（T5 回填中选择错因后自动聚合）</div>';
      return;
    }
    const agg = {};
    errors.forEach(v => {
      const k = (v.actual_phase || phaseOf[v.plan_id] || '未标');
      agg[k] = agg[k] || {};
      agg[k][v.error_type] = (agg[k][v.error_type] || 0) + 1;
    });
    const errTypes = [...new Set(errors.map(v => v.error_type))];
    el.innerHTML = `
      <table class="table">
        <tr><th>阶段 \\ 错因</th>${errTypes.map(e => `<th>${e}</th>`).join('')}</tr>
        ${Object.keys(agg).map(ph => `
          <tr><td>${srPhaseChip(ph)}</td>${errTypes.map(e => `<td style="font-weight:600;">${agg[ph][e] || '<span style="color:var(--gray-300);">·</span>'}</td>`).join('')}</tr>
        `).join('')}
      </table>`;
  } catch (e) {
    el.innerHTML = `<div class="sr-empty">加载失败: ${e.message}</div>`;
  }
}

/* ── ⑥ 口径 & 待讨论 ── */
async function srTabLogic() {
  const body = $('#sr-tab-body');
  body.innerHTML = `
    <div class="card" style="margin-bottom:14px;">
      <div class="card-title">客观情绪分公式 · v2.0 <span class="sr-auto-tag">2026-09-29 已定稿</span></div>
      <div class="sr-formula">
        客观情绪分 = 每日复盘情绪分 × 0.4 + 赚钱效应分 × 0.6
      </div>
      <div class="sr-alert warn" style="margin-top:10px;">
        <b>口径说明：</b>情绪分 / 赚钱效应分取自每日复盘流水线（review_*.json）；15:30 采集时复盘报告未生成则用实时监控分析值，两者同引擎。复盘分双缺失时退化为 v1.0 客观合成并在 raw_json 标记 score_source。旧公式三项问题（死市满分 / up_ratio 口径 / big_loss 未入公式）随公式替换自动消除。
      </div>
    </div>

    <div class="card" style="margin-bottom:14px;">
      <div class="card-title">口径字典 · T0 <span class="sr-auto-tag">metrics_version 追踪</span></div>
      <div id="sr-metrics"></div>
    </div>

    <div class="card">
      <div class="card-title">📋 待讨论清单 <span class="sr-manual-tag">把逻辑讨论清楚再动工</span></div>
      <div class="sr-hint" style="margin-bottom:12px;">以下是框架图上尚未定稿 / 需要你拍板的逻辑点。逐条过一遍，确定后我再写数据层。</div>
      <div id="sr-todo-list"></div>
    </div>
  `;
  // T0 口径字典
  try {
    const metrics = await srGet('/api/sentiment/metrics');
    $('#sr-metrics').innerHTML = (metrics && metrics.length) ? `
      <table class="table">
        <tr><th>指标</th><th>口径定义</th><th>版本</th><th>变更时间</th></tr>
        ${metrics.map(m => `<tr><td><b>${m.metric_name}</b></td><td style="font-size:12px;color:var(--gray-500);">${m.definition}</td><td>${m.version}</td><td>${m.changed_at}</td></tr>`).join('')}
      </table>` : '<div class="sr-empty">口径字典为空</div>';
  } catch (e) {
    $('#sr-metrics').innerHTML = `<div class="sr-empty">加载失败: ${e.message}</div>`;
  }

  // 待讨论清单
  const todos = [
    { id: 1, t: '客观情绪分公式三项修正', d: '死市满分漏洞 / up_ratio 口径 / big_loss 入公式（负项）。趁数据少先修，raw_json 支持事后回算。', s: '建议全改，权重等历史数据够了再校准' },
    { id: 2, t: 'T2 自动预填映射', d: '现有每日自动复盘的 cycle_label（冰点期/下降期…）→ 6 态 cycle_phase 的映射表如何定？预填后人工确认 vs 纯手选。', s: '建议预填+确认，映射表进 T0 口径字典' },
    { id: 3, t: '机器计划对照字段', d: 'quant/trade_plan.py 每天自动生成交易计划。T4 加「采纳/修改/否定机器计划」字段可统计机器 vs 人工胜率。', s: '建议加，字段暂不入库，先并行记录 2 周看价值' },
    { id: 4, t: 'T5 与 /track 战绩追踪口径对齐', d: '已有 /track 记录「前日推荐→次日表现」（收益率口径），T5 是 -2~+2 主观打分。两套验证要不要统一？', s: '建议保留双口径但互相关联：T5 主观分 + /track 客观收益' },
    { id: 5, t: 'T6 沉淀方式', d: '当前简化版：lesson 非空即入库，会得到自由文本规则堆积。', s: '建议 v1 只做案例聚合（错因×阶段），规则等 ≥20 样本人工提炼' },
    { id: 6, t: 'T1 是否加 mainline 字段', d: '相似日检索目前只有情绪指标向量。加「主线板块」维度，「主线相同的相似日」比纯数字相似更硬核。', s: '建议加，review_*.json 已有历史 mainline 数据可回填' },
    { id: 7, t: '历史回填 21 个月', d: '425 份 review_*.json（2025-01 至今）+ ths_api 历史接口可补齐 T1/T2。序列视图和相似日检索的真正瓶颈。', s: '建议作为 P0 先行，夜间限速跑，防 429' },
    { id: 8, t: '未填提醒闭环', d: '校验规则 4 只是事后惩罚。要不要把「今日未录入 T2」挂进 17:30 send_share.sh 推送？', s: '建议挂，成本最低的习惯闭环' },
    { id: 9, t: '预案书写时点', d: 'T4 是「盘后写次日预案」还是「盘前写当日预案」？时点影响可证伪性（防事后合理化）。', s: '建议：当日盘后写次日预案，系统记录 created_at 时间戳防倒填' },
    { id: 10, t: '交易日历', d: 'target_date 目前跳过周末简单推算，节假日会错。', s: '建议接入交易日历（data/ 已有 holidays.json）' },
    { id: 11, t: '录入入口', d: '手机上能不能 3 分钟填完？现在表单是桌面布局。', s: '建议框架确认后做移动端适配（或走 Flutter Web）' },
    { id: 12, t: '演示数据开关的去留', d: '右上角演示模式目前是框架审阅用。', s: '建议保留为「示例」按钮 + 帮助页，新手引导也有用' },
  ];
  $('#sr-todo-list').innerHTML = todos.map(t => `
    <div class="sr-todo-item">
      <div class="sr-todo-head"><span class="sr-todo-id">#${t.id}</span> <b>${t.t}</b></div>
      <div class="sr-todo-desc">${t.d}</div>
      <div class="sr-todo-sug">💡 ${t.s}</div>
    </div>`).join('');
}

/* ── api() POST/DELETE 支持 shim（app.js 的 api 仅 GET） ── */
(function () {
  const _origApi = window.api;
  if (!_origApi) return;
  window.api = function (path, timeout, options) {
    if (!options) return _origApi(path, timeout);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeout || 30000);
    const h = Object.assign({ 'Content-Type': 'application/json', 'X-API-Key': (window.APP_API_KEY || '') }, options.headers || {});
    return fetch((window.API_BASE || '') + path, {
      method: options.method || 'POST',
      headers: h,
      body: options.body,
      signal: ctrl.signal,
      cache: 'no-store'
    }).then(r => {
      clearTimeout(timer);
      if (!r.ok) throw new Error('API error: ' + r.status);
      return r.json();
    }).catch(e => {
      clearTimeout(timer);
      if (e.name === 'AbortError') throw new Error('请求超时，请稍后重试');
      throw e;
    });
  };
})();


/* ── 闭环一：历史规则参谋（写预案时检索规则库） ── */
async function srLoadRuleSuggest() {
  const el = $('#sr-rule-suggest');
  if (!el) return;
  el.innerHTML = '<div class="sr-hint">匹配中…</div>';
  const phase = $('#sr-cycle') ? $('#sr-cycle').value : '';
  const dir = $('#sr-p-dir') ? $('#sr-p-dir').value : '';
  const text = (($('#sr-p-plan') ? $('#sr-p-plan').value : '') + ' ' +
    ($('#sr-p-falsify') ? $('#sr-p-falsify').value : '')).trim();
  try {
    const rules = await srGet('/api/sentiment/rules/suggest?phase=' + encodeURIComponent(phase) +
      '&direction=' + encodeURIComponent(dir) + '&text=' + encodeURIComponent(text));
    if (!rules || !rules.length) {
      el.innerHTML = '<div class="sr-hint">暂无匹配的历史规则。规则库会随你的回填教训慢慢长出来。</div>';
      return;
    }
    el.innerHTML = rules.map(r => `
      <div class="sr-note" style="border-left:3px solid #8b5cf6;padding-left:8px;margin:6px 0">
        <b>${r.rule_text}</b>
        <div style="font-size:11px;color:var(--gray-500)">匹配度 ${r.match_score} · 样本 ${r.sample_count || 0} 次${r.hit_rate != null ? ' · 命中率 ' + (r.hit_rate * 100).toFixed(0) + '%' : ''} · ${r.status}${r.era_tag ? ' · ' + r.era_tag : ''}</div>
      </div>`).join('');
  } catch (e) {
    el.innerHTML = `<div class="sr-hint">匹配失败: ${e.message}</div>`;
  }
}

/* ── 闭环三：周期×载体一致性校准（背离=校准信号） ── */
async function srLoadCalibration() {
  const el = $('#sr-calib-box');
  if (!el) return;
  try {
    const d = await srGet('/api/sentiment/consistency?days=30');
    const rows = (d && d.rows) || [], st = (d && d.stats) || {};
    const divs = rows.filter(r => !r.consistent);
    el.innerHTML = `
      <div style="border-top:1px dashed var(--border);padding-top:10px">
        <b style="font-size:13px">🎯 周期×载体校准</b>
        <span class="sr-counter">周期判断与载体反馈互为对照器 · 背离=校准信号</span>
        <div style="font-size:12px;color:var(--gray-600);margin-top:6px">
          近 ${st.days || 0} 条复盘：背离 <b>${st.divergences || 0}</b> 次，已裁定 ${st.adjudicated || 0} 次
          ——周期判断对 <b>${st.cycle_right || 0}</b> / 载体对 <b>${st.carrier_right || 0}</b>
        </div>
        ${divs.length ? divs.slice(0, 5).map(r => `
          <div class="sr-note" style="margin:6px 0">
            ${srDate(r.date)}：判 <b>${r.cycle_phase}</b> 但载体反馈 <b>${r.feedback_score > 0 ? '+' : ''}${r.feedback_score}</b>
            → ${r.divergence_type}${r.verdict ? ' · 裁定：<b>' + r.verdict + '</b>' : ' · 待 T+1 裁定'}
            ${r.next_day_market_pct != null ? '（次日大盘 ' + (r.next_day_market_pct > 0 ? '+' : '') + r.next_day_market_pct + '%）' : ''}
          </div>`).join('') : '<div class="sr-hint" style="margin-top:6px">暂无背离记录——周期与载体判断一致</div>'}
      </div>`;
  } catch (e) {
    el.innerHTML = `<div class="sr-hint">校准加载失败: ${e.message}</div>`;
  }
}
