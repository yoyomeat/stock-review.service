let _trendData = null;

async function loadTrend() {
  window._trendLoaded = true;
  const el = $('#trend-content');
  el.innerHTML = '<div class="loading">加载中</div>';
  try {
    _trendData = await api('/api/dashboard', 20000);
    renderTrend(el, _trendData, 20);
  } catch (e) {
    el.innerHTML = '<div class="card">加载失败: ' + e.message + '</div>';
  }
}

function renderTrend(el, data, days) {
  const dsDict = data.date_sentiments || {};
  const allKeys = Object.keys(dsDict).sort();
  if (!allKeys.length) { el.innerHTML = '<div class="card">暂无数据</div>'; return; }

  const dsKeys = allKeys.slice(-days);
  const avgSent = dsKeys.reduce((s, k) => s + (dsDict[k]?.sentiment || 0), 0) / dsKeys.length;
  const avgProfit = dsKeys.reduce((s, k) => s + (dsDict[k]?.profit || 0), 0) / dsKeys.length;

  el.innerHTML = `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:20px;flex-wrap:wrap">
      ${[5,10,20,60].map(d => `<button onclick="rerenderTrend(${d})" style="padding:6px 16px;border:1px solid ${d===days?'var(--primary)':'var(--border)'};border-radius:var(--radius-sm);background:${d===days?'var(--primary-bg)':'var(--card)'};cursor:pointer;font-size:13px;font-weight:${d===days?'600':'400'};color:${d===days?'var(--primary)':'var(--gray-600)'}">近${d}日</button>`).join('')}
    </div>
    <div class="grid grid-4" style="margin-bottom:20px">
      <div class="card metric"><div class="metric-value">${fmt(avgSent)}</div><div class="metric-label">平均情绪</div></div>
      <div class="card metric"><div class="metric-value">${fmt(avgProfit)}</div><div class="metric-label">平均赚钱效应</div></div>
      <div class="card metric"><div class="metric-value">${dsKeys.length}</div><div class="metric-label">总天数</div></div>
      <div class="card metric"><div class="metric-value">${dsKeys[dsKeys.length-1]}</div><div class="metric-label">最新日期</div></div>
    </div>
    <div class="card" style="margin-bottom:20px">
      <div class="card-title">情绪 & 赚钱效应趋势</div>
      <div style="position:relative;height:350px;width:100%"><canvas id="trend-full-chart"></canvas></div>
    </div>
    <div class="grid grid-2" style="margin-bottom:20px">
      <div class="card">
        <div class="card-title">涨跌家数趋势</div>
        <div style="position:relative;height:250px;width:100%"><canvas id="updown-chart"></canvas></div>
      </div>
      <div class="card">
        <div class="card-title">涨停数趋势</div>
        <div style="position:relative;height:250px;width:100%"><canvas id="zt-chart"></canvas></div>
      </div>
    </div>
  `;

  const labels = dsKeys.map(d => d.slice(4));
  const sentData = dsKeys.map(k => dsDict[k]?.sentiment || 0);
  const profitData = dsKeys.map(k => dsDict[k]?.profit || 0);

  new Chart($('#trend-full-chart'), {
    type: 'line',
    data: { labels, datasets: [
      { label: '情绪', data: sentData, borderColor: '#4F46E5', backgroundColor: 'rgba(79,70,229,0.08)', fill: true, tension: 0.3, borderWidth: 2, pointRadius: 2 },
      { label: '赚钱效应', data: profitData, borderColor: '#10B981', backgroundColor: 'rgba(16,185,129,0.08)', fill: true, tension: 0.3, borderWidth: 2, pointRadius: 2 },
    ]},
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'top', labels: { usePointStyle: true } } }, scales: { y: { beginAtZero: true, max: 100 } } }
  });

  const upData = dsKeys.map(k => dsDict[k]?.up_count || 0);
  const downData = dsKeys.map(k => dsDict[k]?.down_count || 0);
  new Chart($('#updown-chart'), {
    type: 'line',
    data: { labels, datasets: [
      { label: '上涨', data: upData, borderColor: '#10B981', tension: 0.3, borderWidth: 2, pointRadius: 1 },
      { label: '下跌', data: downData, borderColor: '#EF4444', tension: 0.3, borderWidth: 2, pointRadius: 1 },
    ]},
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'top', labels: { usePointStyle: true } } }, scales: { y: { beginAtZero: true } } }
  });

  const ztData = dsKeys.map(k => dsDict[k]?.zt_count || 0);
  new Chart($('#zt-chart'), {
    type: 'line',
    data: { labels, datasets: [
      { label: '涨停数', data: ztData, borderColor: '#F59E0B', backgroundColor: 'rgba(245,158,11,0.08)', fill: true, tension: 0.3, borderWidth: 2, pointRadius: 2 },
    ]},
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'top', labels: { usePointStyle: true } } }, scales: { y: { beginAtZero: true } } }
  });
}

function rerenderTrend(days) {
  if (_trendData) renderTrend($('#trend-content'), _trendData, days);
}
