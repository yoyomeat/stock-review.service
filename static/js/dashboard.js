async function loadDashboard() {
  window._dashboardLoaded = true;
  const el = $('#dashboard-content');
  const loading = $('#dashboard-loading');
  try {
    const data = await api('/api/dashboard', 20000);
    loading.style.display = 'none';
    el.style.display = 'block';
    renderDashboard(el, data);
    loadTodayModules(el);
    // 异步加载量化画像卡片
    loadQuantProfileCard(el);
    // 异步加载明日预测卡片
    loadPredictionCard(el);
  } catch (e) {
    loading.innerHTML = '加载失败: ' + e.message + '<br><button onclick="window._dashboardLoaded=false;loadDashboard()" style="margin-top:8px;padding:4px 12px;cursor:pointer">重试</button>';
  }
}

function renderDashboard(el, data) {
  const latest = data.latest || {};
  const dsDict = data.date_sentiments || {};
  const lianbanData = data.lianban || {};
  const kphSectors = data.kph_sectors || [];
  const sectors = kphSectors.sort((a, b) => parseFloat(b.amount || 0) - parseFloat(a.amount || 0)).slice(0, 5);

  const composite = latest.composite || 0;
  const sentiment = latest.sentiment_score || 0;
  const profit = latest.profit_score || 0;
  const position = latest.position || 0;
  const cycle = latest.cycle_label || '未知';
  const style = latest.style || '未知';
  const mainline = latest.mainline || '无';
  const dateStr = latest.date || '';

  let signalType = 'yellow', signalText = '观望';
  if (latest.action && latest.action.includes('多头')) { signalType = 'green'; signalText = '多头共振'; }
  else if (latest.position === 0) { signalType = 'red'; signalText = '空仓'; }
  else if (position >= 80) { signalType = 'green'; signalText = '重仓操作'; }
  else if (position >= 50) { signalType = 'yellow'; signalText = '半仓参与'; }

  el.innerHTML = `
    <div class="signal-banner signal-${signalType}">
      <div>
        <div style="font-size:16px;font-weight:600">${signalText} · ${cycle} · ${style}</div>
        <div style="font-size:12px;opacity:0.8">${dateStr} · 主线: ${mainline} · 置信度 ${fmt(latest.confidence, 0)}%</div>
      </div>
    </div>

    <div class="grid grid-4" style="margin-bottom:20px">
      <div class="card metric"><div class="metric-value">${fmt(composite)}</div><div class="metric-label">综合评分</div><div class="metric-change ${signalClass(composite)}">${composite >= 50 ? '偏强' : '偏弱'}</div></div>
      <div class="card metric"><div class="metric-value" style="color:${sentiment >= 50 ? 'var(--success)' : 'var(--danger)'}">${fmt(sentiment)}</div><div class="metric-label">情绪评分</div><div class="metric-change">${latest.sentiment_level || ''}</div></div>
      <div class="card metric"><div class="metric-value" style="color:${profit >= 50 ? 'var(--success)' : 'var(--danger)'}">${fmt(profit)}</div><div class="metric-label">赚钱效应</div><div class="metric-change">${latest.profit_level || ''}</div></div>
      <div class="card metric"><div class="metric-value">${position}%</div><div class="metric-label">建议仓位</div><div class="metric-change">${latest.position_label || ''}</div></div>
    </div>

    <div class="grid grid-2" style="margin-bottom:20px">
      <div class="card">
        <div class="card-title">市场状态</div>
        <table class="table">
          <tr><td style="width:120px;color:var(--gray-500)">周期</td><td>${cycle}</td></tr>
          <tr><td style="color:var(--gray-500)">风格</td><td><span class="badge badge-blue">${style}</span></td></tr>
          <tr><td style="color:var(--gray-500)">主线</td><td>${mainline}</td></tr>
          <tr><td style="color:var(--gray-500)">涨停/跌停</td><td>${latest.zt_count || 0} / ${latest.dt_count || 0}</td></tr>
          <tr><td style="color:var(--gray-500)">涨/跌家数</td><td>${latest.up_count || 0} / ${latest.down_count || 0}</td></tr>
          <tr><td style="color:var(--gray-500)">炸板率</td><td>${fmt(latest.zb_rate, 1)}%</td></tr>
          <tr><td style="color:var(--gray-500)">成交量</td><td>${fmt((latest.amt_total || 0) / 1e8, 0)}亿</td></tr>
        </table>
      </div>
      <div class="card">
        <div class="card-title">板块 TOP5（KPH50）</div>
        <table class="table">
          <thead><tr><th>板块</th><th>涨跌</th><th>强度</th><th>龙一/龙二/龙三</th></tr></thead>
          <tbody>${sectors.map(s => {
            const leaders = (s.leaders || []).map(l => (l.rank_tag || '') + (l.name || '')).join(' / ');
            return `<tr><td style="font-weight:500">${s.plate_name || '-'}</td><td style="color:${(s.change_pct || 0) >= 0 ? 'var(--success)' : 'var(--danger)'}">${pct(s.change_pct)}</td><td>${fmt(s.amount || 0, 0)}</td><td style="font-size:12px">${leaders || '-'}</td></tr>`;
          }).join('')}</tbody>
        </table>
      </div>
    </div>

    <div class="grid grid-2" style="margin-bottom:20px">
      <div class="card">
        <div class="card-title">操作计划</div>
        ${renderOperationPlan(latest)}
      </div>
      <div class="card">
        <div class="card-title">情绪趋势 (近30天)</div>
        <div style="position:relative;height:200px;width:100%"><canvas id="trend-mini-chart"></canvas></div>
      </div>
      <div class="card">
        <div class="card-title">涨跌/涨停趋势 (近30天)</div>
        <div style="position:relative;height:200px;width:100%"><canvas id="market-mini-chart"></canvas></div>
      </div>
    </div>

    ${renderLianban(lianbanData)}
  `;

  // Render trend chart - date_sentiments is a dict {date: {sentiment, profit, up_count, down_count, zt_count}}
  const dsKeys = Object.keys(dsDict).sort();
  if (dsKeys.length > 0) {
    const recent = dsKeys.slice(-30);
    const ctx = document.getElementById('trend-mini-chart');
    if (ctx) {
      new Chart(ctx, {
        type: 'line',
        data: {
          labels: recent.map(d => d.slice(4)),
          datasets: [
            { label: '情绪', data: recent.map(d => dsDict[d]?.sentiment || 0), borderColor: '#4F46E5', backgroundColor: 'rgba(79,70,229,0.1)', fill: true, tension: 0.3, borderWidth: 2 },
            { label: '赚钱', data: recent.map(d => dsDict[d]?.profit || 0), borderColor: '#10B981', backgroundColor: 'rgba(16,185,129,0.1)', fill: true, tension: 0.3, borderWidth: 2 },
          ]
        },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'top', labels: { usePointStyle: true, padding: 16 } } }, scales: { y: { beginAtZero: true, max: 100 } } }
      });
    }
  }

  // Render market trend chart (up/down count + zt count)
  if (dsKeys.length > 0) {
    const recent = dsKeys.slice(-30);
    const ctx2 = document.getElementById('market-mini-chart');
    if (ctx2) {
      const upData = recent.map(d => dsDict[d]?.up_count || 0);
      const downData = recent.map(d => dsDict[d]?.down_count || 0);
      const ztData = recent.map(d => dsDict[d]?.zt_count || 0);
      new Chart(ctx2, {
        type: 'line',
        data: {
          labels: recent.map(d => d.slice(4)),
          datasets: [
            { label: '上涨', data: upData, borderColor: '#10B981', tension: 0.3, borderWidth: 2, yAxisID: 'y' },
            { label: '下跌', data: downData, borderColor: '#EF4444', tension: 0.3, borderWidth: 2, yAxisID: 'y' },
            { label: '涨停', data: ztData, borderColor: '#F59E0B', borderDash: [5,5], tension: 0.3, borderWidth: 2, yAxisID: 'y1' },
          ]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { position: 'top', labels: { usePointStyle: true, padding: 16 } } },
          scales: {
            y: { beginAtZero: true, position: 'left', title: { display: true, text: '涨跌家数' } },
            y1: { beginAtZero: true, position: 'right', title: { display: true, text: '涨停数' }, grid: { drawOnChartArea: false } }
          }
        }
      });
    }
  }
}

function renderOperationPlan(d) {
  const tp = d.trade_plan || {};
  const tracker = d.mainline_tracker || {};
  const picks = tp.picks || [];
  const action = tp.action || d.action || '观望';
  const position = tp.total_position || d.position || 0;
  const mainline = tp.mainline || d.mainline || '无';

  let html = '';

  // 顶部：行动指令
  const actionColor = action.includes('加仓') ? 'var(--success)' : (action.includes('观望') ? 'var(--warning)' : 'var(--primary)');
  html += `<div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;flex-wrap:wrap">`;
  html += `<span style="font-size:16px;font-weight:700;color:${actionColor}">${action}</span>`;
  html += `<span class="badge badge-blue" style="font-size:13px">仓位 ${position}%</span>`;
  html += `</div>`;

  // 分策略展示
  const trackerKeys = Object.keys(tracker);

  // ── Confirm策略（CONFIRMED_TREND / CONFIRMED_SIGNAL）──
  const confirmSectors = trackerKeys.filter(k => {
    const s = tracker[k].status || '';
    return s === 'CONFIRMED_TREND' || s === 'CONFIRMED_SIGNAL' || s === 'CONFIRMED';
  });
  const confirmPicks = picks.filter(p => (p.strategy_tag || '').includes('confirmed'));
  const catchupPicks = picks.filter(p => (p.strategy_tag || '').includes('catchup'));

  html += `<div style="margin-bottom:14px">`;
  html += `<div style="font-size:13px;font-weight:600;color:var(--gray-700);margin-bottom:6px">📌 Confirm策略</div>`;

  if (confirmSectors.length > 0) {
    for (const sector of confirmSectors) {
      const t = tracker[sector];
      const status = t.status || 'NONE';
      const isTrend = status === 'CONFIRMED_TREND';
      const statusColor = isTrend ? '#10B981' : '#3B82F6';
      const statusLabel = isTrend ? '确认趋势' : '确认信号';
      const pool = t.mainline_pool || [];

      html += `<div style="display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid var(--gray-100)">`;
      html += `<span style="font-weight:600;font-size:13px">${sector}</span>`;
      html += `<span class="badge" style="background:${statusColor}20;color:${statusColor};border:1px solid ${statusColor}40;font-size:11px">${statusLabel}</span>`;
      if (pool.length > 0) {
        const topStocks = pool.slice(0, 3).map(s => {
          const ret = s.cum_ret || 0;
          const retColor = ret >= 0 ? 'var(--success)' : 'var(--danger)';
          return `<span style="font-size:12px">${s.name || s.code} <span style="color:${retColor}">${ret > 0 ? '+' : ''}${fmt(ret, 0)}%</span></span>`;
        }).join(' / ');
        html += `<span style="font-size:12px;color:var(--gray-500)">池${pool.length}: ${topStocks}`;
        if (pool.length > 3) html += ` <span style="color:var(--gray-400)">+${pool.length - 3}</span>`;
        html += `</span>`;
      }
      html += `</div>`;
    }
  } else {
    html += `<div style="font-size:12px;color:var(--gray-400);padding:4px 0">无确认板块</div>`;
  }

  // Confirm picks
  if (confirmPicks.length > 0) {
    html += `<div style="margin-top:6px">`;
    for (const p of confirmPicks) {
      const tag = (p.strategy_tag || '').replace('_entry', '');
      const tagColor = tag === 'catchup' ? '#8B5CF6' : '#3B82F6';
      html += `<div style="display:flex;align-items:center;gap:6px;padding:2px 0">`;
      html += `<span class="badge" style="background:${tagColor}15;color:${tagColor};border:1px solid ${tagColor}30;font-size:10px">${tag === 'catchup' ? '补涨' : '追强'}</span>`;
      html += `<span style="font-size:13px;font-weight:500">${p.name || p.code}</span>`;
      if (p.buy_price) html += `<span style="font-size:11px;color:var(--gray-500)">¥${p.buy_price}</span>`;
      if (p.allocation) html += `<span style="font-size:11px;color:var(--gray-500)">${p.allocation}%</span>`;
      html += `</div>`;
    }
    html += `</div>`;
  } else if (confirmSectors.length > 0) {
    html += `<div style="font-size:11px;color:var(--gray-400);padding:2px 0">无选股信号</div>`;
  }
  html += `</div>`;

  // ── Trend策略 ──
  const trendPicks = picks.filter(p => (p.strategy_tag || '').includes('trend'));
  html += `<div style="margin-bottom:14px">`;
  html += `<div style="font-size:13px;font-weight:600;color:var(--gray-700);margin-bottom:6px">📈 Trend策略</div>`;

  // 显示所有trend相关的tracker
  const trendSectors = trackerKeys.filter(k => {
    const s = tracker[k].status || '';
    return !s.startsWith('CONFIRMED') && s !== 'NONE' && s !== 'CANDIDATE';
  });
  if (trendSectors.length > 0 || trendPicks.length > 0) {
    for (const sector of trendSectors) {
      const t = tracker[sector];
      const pool = t.mainline_pool || [];
      html += `<div style="font-size:12px;padding:2px 0">`;
      html += `<span style="font-weight:500">${sector}</span>`;
      if (pool.length > 0) {
        html += ` <span style="color:var(--gray-500)">池${pool.length}只</span>`;
      }
      html += `</div>`;
    }
    if (trendPicks.length > 0) {
      for (const p of trendPicks) {
        html += `<div style="display:flex;align-items:center;gap:6px;padding:2px 0">`;
        html += `<span class="badge" style="background:#8B5CF615;color:#8B5CF6;border:1px solid #8B5CF630;font-size:10px">趋势</span>`;
        html += `<span style="font-size:13px;font-weight:500">${p.name || p.code}</span>`;
        if (p.buy_price) html += `<span style="font-size:11px;color:var(--gray-500)">¥${p.buy_price}</span>`;
        html += `</div>`;
      }
    }
  } else {
    html += `<div style="font-size:12px;color:var(--gray-400);padding:2px 0">无趋势信号</div>`;
  }
  html += `</div>`;

  // 风险提示
  if (d.stop_loss_text) {
    html += `<div style="padding:8px;background:var(--danger-bg);border-radius:4px;font-size:12px">🛡️ ${d.stop_loss_text}</div>`;
  }
  if (d.take_profit_text) {
    html += `<div style="padding:8px;background:var(--success-bg,#f0fdf4);border-radius:4px;font-size:12px;margin-top:4px">🎯 ${d.take_profit_text}</div>`;
  }

  return html || '<div style="font-size:14px;color:var(--gray-500)">暂无操作建议</div>';
}

function renderLianban(lb) {
  if (!lb || !lb.tiers) return '';
  const tiers = lb.tiers || [];
  if (!tiers.length) return '';
  const total = lb.total_zt || 0;
  const highest = lb.highest_board || 0;
  let html = '<div class="card" style="margin-bottom:20px"><div class="card-title">连板梯队 <span style="font-size:12px;font-weight:400;color:var(--gray-500)">涨停' + total + '只 | 最高' + highest + '板</span></div>';
  for (const tier of tiers) {
    const stocks = tier.stocks || [];
    const lvl = tier.level || 1;
    const bgColor = lvl >= 5 ? '#dc2626' : lvl >= 3 ? '#f59e0b' : lvl >= 2 ? '#3b82f6' : 'var(--gray-600)';
    const label = lvl >= 5 ? '妖板' : lvl >= 3 ? '高板' : lvl >= 2 ? '连板' : '首板';
    html += '<div style="margin-bottom:8px">';
    html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">';
    html += '<span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:700;color:#fff;background:' + bgColor + '">' + lvl + '板</span>';
    html += '<span style="font-size:11px;color:var(--gray-500)">' + tier.count + '只 · ' + label + '</span>';
    html += '</div>';
    html += '<div style="display:flex;flex-wrap:wrap;gap:4px">';
    const show = lvl === 1 ? stocks.slice(0, 5) : stocks;
    for (const s of show) {
      const pct = s.pct || 0;
      html += '<span class="badge badge-gray" style="font-size:12px">' + s.name + ' <span style="color:var(--success)">' + (pct >= 0 ? '+' : '') + fmt(pct, 1) + '%</span></span>';
    }
    if (lvl === 1 && stocks.length > 5) html += '<span class="badge badge-gray" style="font-size:11px">+' + (stocks.length - 5) + '只</span>';
    html += '</div></div>';
  }
  html += '</div>';
  return html;
}

/* ── 量化画像卡片 ── */
async function loadQuantProfileCard(dashboardEl) {
  try {
    const data = await api('/api/quant_profile', 15000);
    if (!data || !data.quant_stocks || data.quant_stocks.length === 0) return;
    const card = document.createElement('div');
    card.className = 'card';
    card.style.marginBottom = '20px';
    card.innerHTML = renderQuantProfile(data);
    dashboardEl.appendChild(card);
  } catch (e) {
    // 画像数据不可用时静默忽略
  }
}

function renderQuantProfile(data) {
  const stocks = data.quant_stocks || [];
  const ctx = data.market_context || {};

  let html = `<div class="card-title">量化画像 — ${data.date || ''}</div>`;
  html += `<div style="font-size:12px;color:var(--gray-500);margin-bottom:12px">`;
  html += `大单: ${ctx.big_buy_count || 0}笔买 / ${ctx.big_sell_count || 0}笔卖`;
  html += ` · 总成交额: ${ctx.total_amount_yi || 0}亿`;
  html += `</div>`;

  // 表格
  html += '<table class="table" style="font-size:13px">';
  html += '<thead><tr>';
  html += '<th>股票</th><th>轨道</th><th>强度</th><th>CV</th><th>尾盘%</th><th>VWAP力</th><th>形状</th><th>标签</th>';
  html += '</tr></thead><tbody>';

  for (const s of stocks) {
    const p = s.profile || {};
    const score = s.quant_score || 0;
    const scoreColor = score > 60 ? 'var(--success)' : score > 35 ? 'var(--gray-400)' : 'var(--danger)';
    const cv = p.minute_cv || 0;
    const cvColor = cv < 0.5 ? 'var(--primary)' : cv < 1.5 ? 'var(--gray-400)' : 'var(--danger)';
    const tail = p.tail_concentration || 0;
    const force = p.vwap_force_excess || p.vwap_force || 0;
    const forceColor = force > 0 ? 'var(--success)' : force < 0 ? 'var(--danger)' : 'var(--gray-400)';
    const shape = p.shape_score || 0;
    const tpl = p.shape_template || '';
    const tags = s.tags || [];
    const trackBadge = s.track === 'A'
      ? '<span class="badge badge-blue" style="font-size:10px">大单</span>'
      : '<span class="badge badge-gray" style="font-size:10px">结构</span>';

    html += '<tr>';
    html += `<td style="font-weight:500">${s.name || s.code}</td>`;
    html += `<td>${trackBadge}</td>`;
    html += `<td style="color:${scoreColor};font-weight:700">${fmt(score, 0)}</td>`;
    html += `<td style="color:${cvColor}">${cv < 999 ? fmt(cv, 2) : '-'}</td>`;
    html += `<td>${tail > 0 ? fmt(tail, 1) + '%' : '-'}</td>`;
    html += `<td style="color:${forceColor}">${force !== 0 ? (force > 0 ? '+' : '') + fmt(force, 3) : '-'}</td>`;
    html += `<td>${shape > 0 ? fmt(shape, 2) + ' <span style="color:var(--gray-500);font-size:10px">' + tpl + '</span>' : '-'}</td>`;
    html += `<td>${tags.map(t => '<span class="badge badge-gray" style="font-size:10px">' + t + '</span>').join(' ')}</td>`;
    html += '</tr>';
  }

  html += '</tbody></table>';
  return html;
}

/* ── 明日预测卡片 ── */
async function loadPredictionCard(dashboardEl) {
  try {
    const data = await api('/api/prediction', 15000);
    if (!data || !data.prediction) return;
    const card = document.createElement('div');
    card.className = 'card';
    card.style.marginBottom = '20px';
    card.innerHTML = renderPrediction(data);
    dashboardEl.appendChild(card);
  } catch (e) {
    // 预测数据不可用时静默忽略
  }
}

function renderPrediction(data) {
  const pred = data.prediction || {};
  const wr = data.win_rate || {};
  const f = pred.factors || {};
  const sent = pred.sentiment || {};
  const style = pred.style || {};

  // 方向图标和颜色
  const dirIcon = sent.direction === 'up' ? '📈' : sent.direction === 'down' ? '📉' : '➡️';
  const dirColor = sent.direction === 'up' ? 'var(--success)' : sent.direction === 'down' ? 'var(--danger)' : 'var(--gray-400)';
  const dirText = sent.direction === 'up' ? '偏涨' : sent.direction === 'down' ? '偏跌' : '持平';

  // 风格图标
  const styleIcon = style.result === 'switch' ? '🔄' : '➡️';
  const styleText = style.result === 'switch' ? '切换' : '延续';

  let html = `<div class="card-title">明日预测 — ${pred.date || ''}</div>`;

  // 核心预测
  const er = sent.expected_range || {};
  const rangeText = er.low !== undefined ? `预期 ${er.low}-${er.high} (中位${er.target})` : '';
  html += `<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px">`;
  html += `<div style="padding:12px;background:var(--bg);border-radius:var(--radius-sm);text-align:center">`;
  html += `<div style="font-size:28px;font-weight:800;color:${dirColor}">${dirIcon} ${dirText}</div>`;
  html += `<div style="font-size:11px;color:var(--gray-500);margin-top:4px">${sent.confidence}%置信 · ${sent.rule}</div>`;
  if (rangeText) html += `<div style="font-size:12px;color:var(--gray-400);margin-top:2px;font-weight:500">${rangeText}</div>`;
  html += `<div style="font-size:11px;color:var(--gray-500);margin-top:2px">${sent.reason}</div>`;
  html += `</div>`;
  html += `<div style="padding:12px;background:var(--bg);border-radius:var(--radius-sm);text-align:center">`;
  html += `<div style="font-size:28px;font-weight:800;color:var(--gray-300)">${styleIcon} ${styleText}</div>`;
  html += `<div style="font-size:12px;color:var(--gray-500);margin-top:4px">${style.confidence}%置信 | ${style.reason}</div>`;
  html += `</div>`;
  html += `</div>`;

  // 仓位建议
  const pos = pred.position || 50;
  const posColor = pos >= 60 ? 'var(--success)' : pos >= 40 ? 'var(--gray-400)' : 'var(--danger)';
  html += `<div style="padding:10px 12px;background:var(--bg);border-radius:var(--radius-sm);margin-bottom:12px;display:flex;align-items:center;gap:12px">`;
  html += `<span style="font-size:20px;font-weight:700;color:${posColor}">${pos}%</span>`;
  html += `<span style="font-size:12px;color:var(--gray-500)">建议仓位</span>`;
  html += `</div>`;

  // 量化画像参考
  if (pred.quant_reference) {
    html += `<div style="padding:8px 12px;background:var(--bg);border-radius:var(--radius-sm);margin-bottom:12px;font-size:12px;color:var(--gray-400)">📊 量化画像参考: ${pred.quant_reference}</div>`;
  }

  // 因子状态（带描述）
  const fd = pred.factor_descs || {};
  html += `<div style="margin-bottom:12px">`;
  html += `<div style="font-size:12px;font-weight:600;color:var(--gray-400);margin-bottom:6px">因子状态</div>`;
  const factorItems = [
    { name: '情绪水平', val: f.composite, desc: fd.composite, icon: f.composite < 25 ? '🥶' : f.composite > 75 ? '🔥' : '' },
    { name: '成交量', val: f.vol_ratio, desc: fd.vol_ratio, icon: f.vol_ratio > 1.2 ? '📈' : f.vol_ratio < 0.8 ? '📉' : '', fmt: v => v.toFixed(2) },
    { name: '板块集中度', val: f.concentration, desc: fd.concentration, icon: f.concentration > 60 ? '🎯' : f.concentration < 30 ? '🌫️' : '', fmt: v => v.toFixed(0) + '%' },
    { name: '池结构', val: f.pool_composite, desc: fd.pool_composite, icon: f.pool_composite > 70 ? '💪' : f.pool_composite < 30 ? '⚠️' : '' },
    { name: '预期差', val: f.exp_gap, desc: fd.exp_gap, icon: f.exp_gap > 15 ? '📈' : f.exp_gap < -15 ? '📉' : '', fmt: v => (v >= 0 ? '+' : '') + v.toFixed(1) },
  ];
  for (const fi of factorItems) {
    const val = fi.fmt ? fi.fmt(fi.val) : fi.val;
    html += `<div style="font-size:12px;margin-bottom:3px;display:flex;align-items:center;gap:4px">`;
    html += `<span style="color:var(--gray-500);width:70px;flex-shrink:0">${fi.icon} ${fi.name}</span>`;
    html += `<span style="font-weight:600;min-width:50px">${val}</span>`;
    html += `<span style="color:var(--gray-400);font-size:11px">${fi.desc || ''}</span>`;
    html += `</div>`;
  }
  html += `</div>`;

  // 滚动胜率
  if (wr.total_predictions > 0) {
    html += `<div style="padding:10px 12px;background:var(--bg);border-radius:var(--radius-sm)">`;
    html += `<div style="font-size:12px;font-weight:600;color:var(--gray-400);margin-bottom:6px">📈 滚动胜率 (近${wr.window_days || 30}天)</div>`;
    html += `<div style="font-size:13px;margin-bottom:4px">整体: <b>${wr.overall_win_rate}%</b> (${wr.correct}/${wr.total_predictions})</div>`;
    // 规则胜率
    const ruleStats = wr.rule_stats || {};
    const topRules = Object.entries(ruleStats).sort((a, b) => b[1].win_rate - a[1].win_rate).slice(0, 5);
    for (const [rule, stats] of topRules) {
      const rateColor = stats.win_rate >= 60 ? 'var(--success)' : stats.win_rate >= 50 ? 'var(--gray-400)' : 'var(--danger)';
      html += `<div style="font-size:11px;color:var(--gray-500)">`;
      html += `${rule}: <span style="color:${rateColor}">${stats.win_rate}%</span> (${stats.correct}/${stats.total})`;
      html += `</div>`;
    }
    html += `</div>`;
  }

  return html;
}
