async function loadPosition() {
  window._positionLoaded = true;
  const el = $('#position-content');
  el.innerHTML = '<div class="loading">加载中</div>';
  try {
    const posRisk = await api('/api/position_risk', 60000);
    renderPosition(el, posRisk);
  } catch (e) {
    el.innerHTML = '<div class="card">加载失败: ' + e.message + '</div>';
  }
}

function renderPosition(el, posRisk) {
  const riskPositions = posRisk?.positions || [];
  const riskSummary = posRisk?.portfolio || {};
  const recentClosed = posRisk?.recent_closed || [];

  const totalPnl = riskPositions.reduce((s, p) => s + (p.unreal_pnl || 0), 0);
  const holdingDays = riskPositions.length > 0 ? Math.round(riskPositions.reduce((s, p) => s + (p.held_days || 0), 0) / riskPositions.length) : 0;

  el.innerHTML = `
    <div class="grid grid-3" style="margin-bottom:20px">
      <div class="card metric">
        <div class="metric-value">${riskPositions.length}</div>
        <div class="metric-label">当前持仓数</div>
      </div>
      <div class="card metric">
        <div class="metric-value" style="color:${totalPnl >= 0 ? 'var(--success)' : 'var(--danger)'}">${totalPnl >= 0 ? '+' : ''}${fmt(totalPnl, 0)}</div>
        <div class="metric-label">持仓总盈亏</div>
      </div>
      <div class="card metric">
        <div class="metric-value">${holdingDays}天</div>
        <div class="metric-label">平均持有天数</div>
      </div>
    </div>

    ${riskPositions.length > 0 ? `
    <div class="card" style="margin-bottom:20px">
      <div class="card-title">当前持仓</div>
      <div style="max-height:400px;overflow-y:auto">
        <table class="table">
          <thead><tr><th>代码</th><th>名称</th><th>入场价</th><th>现价</th><th>今日</th><th>盈亏</th><th>仓位</th><th>持有天</th><th>策略</th><th>风险</th></tr></thead>
          <tbody>
          ${riskPositions.map(p => {
            const dp = p.daily_pct || 0;
            const dpColor = dp >= 0 ? 'var(--success)' : 'var(--danger)';
            const tag = p.strategy_tag || '-';
            return `<tr>
              <td style="font-family:monospace">${p.code || '-'}</td>
              <td style="font-weight:500">${p.name || '-'}</td>
              <td>${fmt(p.entry, 2)}</td>
              <td>${fmt(p.mark, 2)}</td>
              <td style="color:${dpColor};font-weight:600">${dp >= 0 ? '+' : ''}${fmt(dp, 2)}%</td>
              <td style="color:${(p.unreal_pct || 0) >= 0 ? 'var(--success)' : 'var(--danger)'};font-weight:600">${pct(p.unreal_pct)}</td>
              <td>${fmt(p.alloc, 0)}%</td>
              <td>${p.held_days || 0}/${p.max_days || '?'}</td>
              <td style="font-size:12px">${tag}</td>
              <td><span class="badge ${p.risk_level === 'high' ? 'badge-red' : p.risk_level === 'medium' ? 'badge-yellow' : 'badge-green'}">${p.risk_level || '-'}</span></td>
            </tr>`;
          }).join('')}
          </tbody>
        </table>
      </div>
    </div>` : '<div class="card"><div class="card-title">持仓数据</div><p style="color:var(--gray-400)">当前无持仓</p></div>'}

    ${recentClosed.length > 0 ? `
    <div class="card">
      <div class="card-title">最近平仓记录</div>
      <div style="max-height:400px;overflow-y:auto">
        <table class="table">
          <thead><tr><th>日期</th><th>名称</th><th>代码</th><th>入场</th><th>出场</th><th>收益</th><th>原因</th></tr></thead>
          <tbody>
          ${recentClosed.map(c => `
            <tr>
              <td style="font-family:monospace;font-size:12px">${(c.date || '').slice(4)}</td>
              <td style="font-weight:500">${c.name || '-'}</td>
              <td style="font-family:monospace;font-size:12px">${c.code || '-'}</td>
              <td>${fmt(c.entry, 2)}</td>
              <td>${fmt(c.exit, 2)}</td>
              <td style="color:${(c.ret_pct || 0) >= 0 ? 'var(--success)' : 'var(--danger)'};font-weight:600">${pct(c.ret_pct)}</td>
              <td style="font-size:12px">${(c.reason || '-').substring(0, 30)}</td>
            </tr>
          `).join('')}
          </tbody>
        </table>
      </div>
    </div>` : ''}
  `;
}
