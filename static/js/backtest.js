async function loadBacktest() {
  window._backtestLoaded = true;
  const el = $('#backtest-content');
  el.innerHTML = '<div class="loading">加载中（回测数据需较长时间）</div>';
  try {
    const data = await api('/api/backtest', 60000);
    renderBacktest(el, data);
  } catch (e) {
    el.innerHTML = `
      <div class="card">
        <div class="card-title">回测数据</div>
        <p style="color:var(--gray-500)">回测API响应较慢，请稍后重试</p>
        <p style="color:var(--gray-500);margin-top:8px">可通过CLI运行回测：</p>
        <pre style="background:var(--gray-100);padding:12px;border-radius:4px;font-size:13px;margin-top:8px;overflow-x:auto">python scripts/run_bt_all.py</pre>
      </div>
    `;
  }
}

function renderBacktest(el, data) {
  if (!data || !data.stats) {
    el.innerHTML = '<div class="card">暂无回测数据</div>';
    return;
  }
  const st = data.stats || {};
  const trades = data.trades || [];
  el.innerHTML = `
    <div class="grid grid-4" style="margin-bottom:20px">
      <div class="card metric">
        <div class="metric-value" style="color:${(st.total_ret || 0) >= 0 ? 'var(--success)' : 'var(--danger)'}">${pct(st.total_ret)}</div>
        <div class="metric-label">总收益</div>
      </div>
      <div class="card metric">
        <div class="metric-value">${fmt(st.max_dd)}%</div>
        <div class="metric-label">最大回撤</div>
      </div>
      <div class="card metric">
        <div class="metric-value">${fmt(st.win_rate, 0)}%</div>
        <div class="metric-label">胜率</div>
      </div>
      <div class="card metric">
        <div class="metric-value">${st.total_trades || trades.length}</div>
        <div class="metric-label">交易笔数</div>
      </div>
    </div>
    <div class="grid grid-2" style="margin-bottom:20px">
      <div class="card">
        <div class="card-title">收益统计</div>
        <table class="table">
          <tr><td style="color:var(--gray-500)">平均收益</td><td>${pct(st.avg_return)}</td></tr>
          <tr><td style="color:var(--gray-500)">平均盈利</td><td style="color:var(--success)">${pct(st.avg_win)}</td></tr>
          <tr><td style="color:var(--gray-500)">平均亏损</td><td style="color:var(--danger)">${pct(st.avg_lose)}</td></tr>
          <tr><td style="color:var(--gray-500)">基准收益</td><td>${pct(st.bench_ret)}</td></tr>
        </table>
      </div>
      <div class="card">
        <div class="card-title">NAV曲线</div>
        <div style="position:relative;height:250px;width:100%"><canvas id="nav-chart"></canvas></div>
      </div>
    </div>
    ${trades.length > 0 ? `
    <div class="card">
      <div class="card-title">交易明细 (${trades.length}笔)</div>
      <div style="max-height:400px;overflow-y:auto">
        <table class="table">
          <thead><tr><th>日期</th><th>名称</th><th>代码</th><th>买入</th><th>卖出</th><th>收益</th><th>原因</th></tr></thead>
          <tbody>
          ${trades.map(t => `
            <tr>
              <td style="font-family:monospace;font-size:12px">${t.entry_date || '-'}</td>
              <td style="font-weight:500">${t.name || '-'}</td>
              <td style="font-family:monospace;font-size:12px">${t.code || '-'}</td>
              <td>${fmt(t.entry_price, 2)}</td>
              <td>${fmt(t.exit_price, 2)}</td>
              <td style="color:${(t.ret_pct || 0) >= 0 ? 'var(--success)' : 'var(--danger)'};font-weight:600">${pct(t.ret_pct)}</td>
              <td style="font-size:12px">${t.reason || '-'}</td>
            </tr>
          `).join('')}
          </tbody>
        </table>
      </div>
    </div>` : ''}
  `;
  if ($('#nav-chart') && trades.length > 0) {
    let cumulative = 100;
    const navData = [cumulative];
    const navLabels = ['开始'];
    trades.forEach(t => {
      cumulative *= (1 + (t.ret_pct || 0) / 100);
      navData.push(cumulative);
      navLabels.push((t.exit_date || '').slice(4));
    });
    new Chart($('#nav-chart'), {
      type: 'line',
      data: { labels: navLabels, datasets: [{ label: 'NAV', data: navData, borderColor: '#4F46E5', backgroundColor: 'rgba(79,70,229,0.1)', fill: true, tension: 0.3, borderWidth: 2, pointRadius: 3 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: false } } }
    });
  }
}
