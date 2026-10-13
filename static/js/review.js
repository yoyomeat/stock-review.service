let _reviewDates = [];
let _reviewDatesLoaded = false;

async function initReviewDates() {
  if (_reviewDatesLoaded) return;
  try {
    _reviewDates = await api('/api/dates', 10000);
    _reviewDatesLoaded = true;
    const sel = $('#review-date-select');
    if (!sel) return;
    sel.innerHTML = '';
    _reviewDates.forEach(d => {
      const opt = document.createElement('option');
      opt.value = d.date;
      const year = d.date ? d.date.slice(0, 4) : '';
      const display = d.display || d.date;
      opt.textContent = year + '/' + display;
      sel.appendChild(opt);
    });
    if (_reviewDates.length) sel.value = _reviewDates[_reviewDates.length - 1].date;
  } catch (e) {
    console.error('initReviewDates failed:', e);
  }
}

async function loadReview() {
  await initReviewDates();
  const sel = $('#review-date-select');
  if (!sel) return;
  const dateStr = sel.value;
  if (!dateStr) return;
  const el = $('#review-content');
  el.innerHTML = '<div class="loading">加载中</div>';
  try {
    const data = await api('/api/review/' + dateStr, 15000);
    renderReview(el, data);
  } catch (e) {
    el.innerHTML = '<div class="card">加载失败: ' + e.message + '</div>';
  }
}

function renderReview(el, d) {
  const tp = d.trade_plan || {};
  const picks = tp.picks || [];
  const sectors = d.sector_top5 || [];
  const tracker = d.mainline_tracker || {};
  const confReasons = d.conf_reasons || [];

  el.innerHTML = `
    <div class="grid grid-4" style="margin-bottom:20px">
      <div class="card metric">
        <div class="metric-value">${fmt(d.composite)}</div>
        <div class="metric-label">综合评分</div>
      </div>
      <div class="card metric">
        <div class="metric-value">${fmt(d.sentiment_score)}</div>
        <div class="metric-label">情绪</div>
      </div>
      <div class="card metric">
        <div class="metric-value">${fmt(d.profit_score)}</div>
        <div class="metric-label">赚钱效应</div>
      </div>
      <div class="card metric">
        <div class="metric-value">${d.position || 0}%</div>
        <div class="metric-label">建议仓位</div>
      </div>
    </div>

    <div class="grid grid-2" style="margin-bottom:20px">
      <div class="card">
        <div class="card-title">市场状态</div>
        <table class="table">
          <tr><td style="width:120px;color:var(--gray-500)">日期</td><td>${d.date}</td></tr>
          <tr><td style="color:var(--gray-500)">周期</td><td>${d.cycle_label || '-'}</td></tr>
          <tr><td style="color:var(--gray-500)">风格</td><td><span class="badge badge-blue">${d.style || '-'}</span></td></tr>
          <tr><td style="color:var(--gray-500)">主线</td><td>${d.mainline || '无'}</td></tr>
          <tr><td style="color:var(--gray-500)">涨/跌</td><td>${d.up_count || 0} / ${d.down_count || 0}</td></tr>
          <tr><td style="color:var(--gray-500)">涨停/跌停</td><td>${d.zt_count || 0} / ${d.dt_count || 0}</td></tr>
          <tr><td style="color:var(--gray-500)">情绪加速度</td><td>${fmt(d.sentiment_accel, 0)}</td></tr>
          <tr><td style="color:var(--gray-500)">赚钱加速度</td><td>${fmt(d.profit_accel, 0)}</td></tr>
        </table>
      </div>
      <div class="card">
        <div class="card-title">操作计划</div>
        <div style="font-size:14px;line-height:1.8;color:var(--gray-700);margin-bottom:12px">
          ${tp.summary || '暂无操作建议'}
        </div>
        ${tp.risk ? `<div style="padding:8px;background:var(--danger-bg);border-radius:4px;font-size:13px;margin-bottom:8px">⚠️ ${tp.risk.rule || JSON.stringify(tp.risk)}</div>` : ''}
        ${d.stop_loss_text ? `<div style="padding:8px;background:var(--warning-bg);border-radius:4px;font-size:13px">🛡️ ${d.stop_loss_text}</div>` : ''}
      </div>
    </div>

    ${picks.length > 0 ? `
    <div class="card" style="margin-bottom:20px">
      <div class="card-title">选股推荐 (${picks.length}只)</div>
      <table class="table">
        <thead><tr><th>代码</th><th>名称</th><th>角色</th><th>仓位</th><th>买入价</th><th>止损</th><th>持有</th><th>策略</th></tr></thead>
        <tbody>
        ${picks.map(p => `
          <tr>
            <td style="font-family:monospace">${p.code}</td>
            <td style="font-weight:500">${p.name}</td>
            <td><span class="badge ${p.role === '主力仓' ? 'badge-blue' : 'badge-gray'}">${p.role || ''}</span></td>
            <td>${p.allocation || '-'}%</td>
            <td style="color:var(--primary)">${p.buy_price || '-'}</td>
            <td style="color:var(--danger)">${p.stop_loss || '-'}</td>
            <td>${p.hold_days || '-'}</td>
            <td><span class="badge badge-gray">${(p.strategy_tag || '').replace('_entry', '')}</span></td>
          </tr>
        `).join('')}
        </tbody>
      </table>
    </div>` : ''}

    <div class="grid grid-2" style="margin-bottom:20px">
      <div class="card">
        <div class="card-title">板块 TOP5（KPH50）</div>
        <table class="table">
          <thead><tr><th>板块</th><th>涨跌</th><th>强度</th><th>龙一/龙二/龙三</th></tr></thead>
          <tbody>
          ${sectors.map(s => {
            const leaders = (s.leaders || []).map(l => `<span style="font-weight:500">${l.name || l.code || '-'}</span>`).join(' / ');
            return `<tr>
              <td style="font-weight:500">${s.name || '-'}</td>
              <td style="color:${(s.change_pct || 0) >= 0 ? 'var(--success)' : 'var(--danger)'}; font-weight:600">${pct(s.change_pct)}</td>
              <td>${fmt(s.amount || 0, 0)}</td>
              <td style="font-size:13px">${leaders || '-'}</td>
            </tr>`;
          }).join('')}
          </tbody>
        </table>
      </div>
      <div class="card">
        <div class="card-title">主线追踪</div>
        <table class="table">
          <thead><tr><th>板块</th><th>状态</th><th>降级天</th><th>Pool</th></tr></thead>
          <tbody>
          ${Object.entries(tracker).slice(0, 8).map(([name, info]) => `
            <tr>
              <td style="font-weight:500">${name}</td>
              <td><span class="badge ${info.status === 'CONFIRMED' ? 'badge-green' : 'badge-yellow'}">${info.status || '-'}</span></td>
              <td>${info.degraded_days || 0}</td>
              <td>${(info.mainline_pool || []).length}只</td>
            </tr>
          `).join('')}
          </tbody>
        </table>
      </div>
    </div>

    ${confReasons.length > 0 ? `
    <div class="card">
      <div class="card-title">置信度因素</div>
      <div style="display:flex;flex-wrap:wrap;gap:8px">
        ${confReasons.map(r => `<span class="badge ${String(r).startsWith('+') ? 'badge-green' : String(r).startsWith('-') ? 'badge-red' : 'badge-gray'}">${r}</span>`).join('')}
      </div>
    </div>` : ''}
  `;
}
