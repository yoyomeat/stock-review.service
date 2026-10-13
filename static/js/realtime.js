/* 实时监控页面 */
let _realtimeTimer = null;
let _realtimeLoaded = false;

async function loadRealtime() {
  window._realtimeLoaded = true;
  _realtimeLoaded = true;
  const el = $('#realtime-content');
  el.innerHTML = '<div class="loading">连接行情服务器...</div>';
  try {
    const data = await api('/api/realtime/snapshot', 15000);
    renderRealtime(el, data);
    startRealtimePolling();
    // 加载盘中分析
    loadAnalysis();
  } catch (e) {
    el.innerHTML = '<div class="card">加载失败: ' + e.message +
      '<br><button onclick="loadRealtime()" style="margin-top:8px;padding:4px 12px;cursor:pointer">重试</button></div>';
  }
}

function startRealtimePolling() {
  stopRealtimePolling();
  _realtimeTimer = setInterval(async () => {
    if (!$('#page-realtime')?.classList.contains('active')) return;
    try {
      const data = await api('/api/realtime/snapshot', 10000);
      updateRealtimeData(data);
    } catch (e) {}
  }, 5000);
}

function stopRealtimePolling() {
  if (_realtimeTimer) { clearInterval(_realtimeTimer); _realtimeTimer = null; }
}

/* ── 首次渲染 ── */
function renderRealtime(el, data) {
  const indices = data.indices || [];
  const sectors = data.sectors || [];
  const stocks = data.stocks || [];
  const ts = data.timestamp || '-';
  const isTrade = data.is_trade_time;

  el.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
      <span id="rt-timestamp" style="font-size:14px;color:var(--gray-500)">最后更新: ${ts}</span>
      <span id="rt-trade-badge" class="badge ${isTrade ? 'badge-green' : 'badge-gray'}" style="font-size:12px">
        ${isTrade ? '● 交易中' : '○ 已收盘'}
      </span>
    </div>

    <div class="card" style="margin-bottom:20px">
      <div class="card-title">📈 主要指数</div>
      <div id="rt-indices" class="grid grid-3" style="gap:12px">
        ${renderIndicesHTML(indices)}
      </div>
    </div>

    <div class="card" style="margin-bottom:20px">
      <div class="card-title">📊 盘中分析</div>
      <div id="rt-analysis"><p style="color:var(--gray-400);font-size:13px">加载中...</p></div>
    </div>

    <div class="grid grid-2" style="margin-bottom:20px">
      <div class="card">
        <div class="card-title" style="display:flex;justify-content:space-between;align-items:center">
          <span>🏷️ 自选板块</span>
          <button onclick="toggleSectorAdd()" style="padding:4px 10px;font-size:12px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--card);cursor:pointer">+ 添加</button>
        </div>
        <div id="sector-add-box" style="display:none;margin-bottom:12px;padding:12px;background:var(--bg);border-radius:var(--radius-sm)">
          <div style="display:flex;gap:8px">
            <input id="sector-search-input" type="text" placeholder="输入板块名称搜索（如 机器人）" onkeydown="if(event.key==='Enter')searchSector()" style="flex:1;padding:6px 10px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:13px">
            <button onclick="searchSector()" style="padding:6px 12px;font-size:12px;background:var(--primary);color:#fff;border:none;border-radius:var(--radius-sm);cursor:pointer">搜索</button>
          </div>
          <div id="sector-search-results" style="margin-top:8px;display:flex;flex-wrap:wrap;gap:4px"></div>
        </div>
        <div id="rt-sectors">${renderSectorsHTML(sectors)}</div>
      </div>

      <div class="card">
        <div class="card-title" style="display:flex;justify-content:space-between;align-items:center">
          <span>📋 自选股</span>
          <button onclick="toggleStockAdd()" style="padding:4px 10px;font-size:12px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--card);cursor:pointer">+ 添加</button>
        </div>
        <div id="stock-add-box" style="display:none;margin-bottom:12px;padding:12px;background:var(--bg);border-radius:var(--radius-sm)">
          <div style="font-size:13px;color:var(--gray-500);margin-bottom:8px">输入股票代码，名称自动匹配</div>
          <div style="display:flex;gap:8px">
            <input id="stock-code-input" type="text" placeholder="股票代码 如 600519" onkeydown="if(event.key==='Enter')addStockByCode()" style="flex:1;padding:6px 10px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:13px">
            <button onclick="addStockByCode()" style="padding:6px 12px;font-size:12px;background:var(--primary);color:#fff;border:none;border-radius:var(--radius-sm);cursor:pointer">添加</button>
          </div>
        </div>
        <div id="rt-stocks">${renderStocksHTML(stocks)}</div>
      </div>
    </div>

    <!-- 自选股盘口深度分析 -->
    <div id="rt-depth-panel" style="display:none">
      <div class="card" style="margin-bottom:20px">
        <div class="card-title" style="display:flex;justify-content:space-between;align-items:center">
          <span id="depth-title">盘口深度</span>
          <button onclick="closeDepthPanel()" style="font-size:12px;color:var(--gray-400);background:none;border:none;cursor:pointer">✕ 关闭</button>
        </div>
        <div id="depth-content"><p style="color:var(--gray-400);font-size:13px">加载中...</p></div>
      </div>
    </div>
  `;
}

/* ── 轮询时只更新数据 ── */
let _suppressStocksUpdate = false;

function updateRealtimeData(data) {
  const tsEl = $('#rt-timestamp');
  if (tsEl) tsEl.textContent = '最后更新: ' + (data.timestamp || '-');
  const idxEl = $('#rt-indices');
  if (idxEl) idxEl.innerHTML = renderIndicesHTML(data.indices || []);
  const secEl = $('#rt-sectors');
  if (secEl) secEl.innerHTML = renderSectorsHTML(data.sectors || []);
  // 增删操作后抑制一轮stocks刷新，防止乐观更新被旧数据覆盖
  if (_suppressStocksUpdate) {
    _suppressStocksUpdate = false;
  } else {
    const stkEl = $('#rt-stocks');
    if (stkEl) stkEl.innerHTML = renderStocksHTML(data.stocks || []);
  }
}

/* ── HTML 模板 ── */
function renderIndicesHTML(indices) {
  return indices.map(idx => {
    const chg = idx.change_pct || 0;
    const color = chg >= 0 ? 'var(--success)' : 'var(--danger)';
    return `<div style="padding:14px;background:var(--bg);border-radius:var(--radius-sm);border:1px solid var(--border)">
      <div style="font-size:12px;color:var(--gray-500);margin-bottom:4px">${idx.name}</div>
      <div style="font-size:22px;font-weight:700;color:${color}">${fmt(idx.price || idx.close, 2)}</div>
      <div style="font-size:13px;color:${color};font-weight:600">${chg>=0?'▲':'▼'} ${chg>=0?'+':''}${fmt(chg,2)}%</div>
    </div>`;
  }).join('');
}

function renderSectorsHTML(sectors) {
  if (sectors.length === 0) return '<p style="color:var(--gray-400);font-size:13px;padding:8px 0">暂无自选板块</p>';
  return `<table class="table"><thead><tr><th>板块</th><th>涨跌</th><th>成交</th><th>龙头</th><th></th></tr></thead><tbody>
  ${sectors.map(s => {
    const chg = s.change_pct || 0;
    const color = chg >= 0 ? 'var(--success)' : 'var(--danger)';
    return `<tr>
      <td style="font-weight:500">${s.name}</td>
      <td style="color:${color};font-weight:600">${chg>=0?'+':''}${fmt(chg,2)}%</td>
      <td>${fmt(s.amount,1)}</td>
      <td style="font-size:12px">${s.leader||'-'} <span style="color:${(s.leader_pct||0)>=0?'var(--success)':'var(--danger)'}">${fmt(s.leader_pct,1)}%</span></td>
      <td><button onclick="removeSector('${s.code}')" style="font-size:11px;color:var(--danger);background:none;border:none;cursor:pointer">✕</button></td>
    </tr>`;
  }).join('')}
  </tbody></table>`;
}

function renderStocksHTML(stocks) {
  if (stocks.length === 0) return '<p style="color:var(--gray-400);font-size:13px;padding:8px 0">暂无自选股</p>';
  return `<table class="table"><thead><tr><th>代码</th><th>名称</th><th>现价</th><th>涨跌</th><th></th></tr></thead><tbody>
  ${stocks.map(s => {
    const chg = s.change_pct || 0;
    const color = chg >= 0 ? 'var(--success)' : 'var(--danger)';
    return `<tr style="cursor:pointer" onclick="toggleStockDetail('${s.code}','${s.name}')">
      <td style="font-family:monospace;font-size:12px">${s.code}</td>
      <td style="font-weight:500">${s.name}</td>
      <td style="color:${color};font-weight:600">${fmt(s.price,2)}</td>
      <td style="color:${color};font-weight:600">${chg>=0?'+':''}${fmt(chg,2)}%</td>
      <td><button onclick="event.stopPropagation();removeStock('${s.code}')" style="font-size:11px;color:var(--danger);background:none;border:none;cursor:pointer">✕</button></td>
    </tr>`;
  }).join('')}
  </tbody></table>`;
}

/* ── 板块：名称搜索 ── */
function toggleSectorAdd() {
  const box = $('#sector-add-box');
  box.style.display = box.style.display === 'none' ? 'block' : 'none';
  if (box.style.display === 'block') $('#sector-search-input').focus();
}

async function searchSector() {
  const q = $('#sector-search-input').value.trim();
  const el = $('#sector-search-results');
  if (!q) { el.innerHTML = ''; return; }
  el.innerHTML = '<span style="font-size:12px;color:var(--gray-400)">搜索中...</span>';
  try {
    const data = await api('/api/realtime/search?q=' + encodeURIComponent(q), 10000);
    const results = data.results || [];
    if (results.length === 0) {
      el.innerHTML = '<span style="font-size:12px;color:var(--gray-400)">未找到</span>';
      return;
    }
    el.innerHTML = results.map(r =>
      `<span onclick="addSectorByName('${r.name.replace(/'/g, "\\'")}')" style="display:inline-block;padding:4px 10px;font-size:12px;background:var(--primary-bg);color:var(--primary);border-radius:12px;cursor:pointer">${r.name}</span>`
    ).join('');
  } catch (e) {
    el.innerHTML = '<span style="font-size:12px;color:var(--danger)">搜索失败</span>';
  }
}

async function addSectorByName(name) {
  $('#sector-search-input').value = '';
  $('#sector-search-results').innerHTML = '';
  // 乐观更新：先清输入框，POST后台执行
  apiPost('/api/realtime/sector', {name}).then(async () => {
    const snap = await api('/api/realtime/snapshot', 10000);
    if (snap.sectors) { const el = $('#rt-sectors'); if (el) el.innerHTML = renderSectorsHTML(snap.sectors); }
  }).catch(() => {}); // 静默，下次轮询会刷新
}

async function removeSector(code) {
  // 乐观更新：立即从DOM移除
  const secEl = $('#rt-sectors');
  if (secEl) {
    const rows = secEl.querySelectorAll('tr');
    rows.forEach(r => { if (r.textContent.includes(code)) r.style.opacity = '0.3'; });
  }
  fetch('/api/realtime/sector/' + encodeURIComponent(code), {method: 'DELETE', headers: {'X-API-Key': (window.APP_API_KEY || '')}}).then(async () => {
    const snap = await api('/api/realtime/snapshot', 10000);
    if (snap.sectors && secEl) secEl.innerHTML = renderSectorsHTML(snap.sectors);
  }).catch(() => {});
}

/* ── 个股 ── */
function toggleStockAdd() {
  const box = $('#stock-add-box');
  box.style.display = box.style.display === 'none' ? 'block' : 'none';
  if (box.style.display === 'block') $('#stock-code-input').focus();
}

async function addStockByCode() {
  const code = $('#stock-code-input').value.trim();
  if (!code) return;
  $('#stock-code-input').value = '';
  _suppressStocksUpdate = true;
  // 乐观更新：立即在表格中显示"加载中"
  const stkEl = $('#rt-stocks');
  if (stkEl) {
    const table = stkEl.querySelector('tbody');
    if (table) {
      const tr = document.createElement('tr');
      tr.innerHTML = '<td style="font-family:monospace;font-size:12px">' + code + '</td><td colspan="3" style="color:var(--gray-400)">加载中...</td><td></td>';
      tr.id = 'stock-loading-' + code;
      table.appendChild(tr);
    }
  }
  // 后台POST
  fetch('/api/realtime/stock', {
    method: 'POST', headers: {'Content-Type': 'application/json', 'X-API-Key': (window.APP_API_KEY || '')},
    body: JSON.stringify({code})
  }).then(r => r.json()).then(result => {
    // 用服务端返回的完整列表刷新
    if (result.stocks && stkEl) stkEl.innerHTML = renderStocksHTML(result.stocks);
    if (result.error) alert(result.error);
  }).catch(() => {
    // 失败也移除loading行
    const loading = document.getElementById('stock-loading-' + code);
    if (loading) loading.remove();
  });
}

async function removeStock(code) {
  _suppressStocksUpdate = true;
  // 乐观更新：立即隐藏行
  const stkEl = $('#rt-stocks');
  if (stkEl) {
    const rows = stkEl.querySelectorAll('tr');
    rows.forEach(r => { if (r.querySelector && r.querySelector(`button[onclick*="${code}"]`)) r.style.opacity = '0.3'; });
  }
  fetch('/api/realtime/stock/' + code, {method: 'DELETE', headers: {'X-API-Key': (window.APP_API_KEY || '')}}).then(r => r.json()).then(result => {
    if (result.stocks && stkEl) stkEl.innerHTML = renderStocksHTML(result.stocks);
  }).catch(() => {});
}

/* ── 个股 ── */
function toggleStockAdd() {
  const box = $('#stock-add-box');
  box.style.display = box.style.display === 'none' ? 'block' : 'none';
  if (box.style.display === 'block') $('#stock-code-input').focus();
}

/* ── POST ── */
async function apiPost(path, body, timeout) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout || 30000);
  try {
    const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json','X-API-Key':(window.APP_API_KEY || '')}, body:JSON.stringify(body), signal:ctrl.signal});
    if (!r.ok) throw new Error('API error: ' + r.status);
    return r.json();
  } catch (e) {
    if (e.name === 'AbortError') throw new Error('请求超时');
    throw e;
  } finally { clearTimeout(timer); }
}

/* ── 盘中分析（替代 intraday_monitor） ── */
let _analysisTimer = null;

async function loadAnalysis() {
  const el = $('#rt-analysis');
  if (!el) return;
  el.innerHTML = '<div class="loading">加载盘中分析...</div>';
  try {
    const data = await api('/api/realtime/analysis', 60000);
    renderAnalysis(el, data);
    startAnalysisPolling();
  } catch (e) {
    el.innerHTML = '<p style="color:var(--gray-400);font-size:13px">分析加载失败: ' + e.message + '</p>';
  }
}

function startAnalysisPolling() {
  if (_analysisTimer) clearInterval(_analysisTimer);
  _analysisTimer = setInterval(async () => {
    if (!$('#page-realtime')?.classList.contains('active')) return;
    const el = $('#rt-analysis');
    if (!el) return;
    try {
      const data = await api('/api/realtime/analysis', 60000);
      renderAnalysis(el, data);
    } catch (e) {}
  }, 60000); // 每60秒刷新分析
}

function renderAnalysis(el, d) {
  if (d.error) { el.innerHTML = '<p style="color:var(--gray-400)">' + d.error + '</p>'; return; }

  const sent = d.sentiment_score || 0;
  const mood = d.mood || '';
  const profit = d.profit_score;
  const profitLv = d.profit_level || '';

  // 情绪分 + 赚钱效应（大卡片并排）
  const sentColor = sent >= 60 ? 'var(--success)' : sent <= 40 ? 'var(--danger)' : 'var(--gray-400)';
  const profColor = profit >= 60 ? 'var(--success)' : profit <= 40 ? 'var(--danger)' : 'var(--gray-400)';
  const scoreHtml = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px">
      <div style="padding:16px;background:var(--bg);border-radius:var(--radius);border:1px solid var(--border)">
        <div style="font-size:12px;color:var(--gray-500);margin-bottom:4px">🌡️ 情绪分</div>
        <div style="font-size:36px;font-weight:800;color:${sentColor};line-height:1">${sent}</div>
        <div style="font-size:13px;margin-top:4px;color:${sentColor}">${mood}</div>
      </div>
      <div style="padding:16px;background:var(--bg);border-radius:var(--radius);border:1px solid var(--border)">
        <div style="font-size:12px;color:var(--gray-500);margin-bottom:4px">💰 赚钱效应</div>
        <div style="font-size:36px;font-weight:800;color:${profColor};line-height:1">${profit!=null?profit:'-'}</div>
        <div style="font-size:13px;margin-top:4px;color:${profColor}">${profitLv}</div>
      </div>
    </div>`;

  // 涨跌停统计（大数字卡片）
  const zt = d.limit_up_count || 0;
  const dt = d.limit_down_count || 0;
  const zb = d.broken_count || 0;
  const zbRate = d.broken_rate || 0;
  const up = d.total_up || 0;
  const down = d.total_down || 0;
  const amt = d.total_amount_yi || 0;
  const yz = d.yesterday_zt_count || 0;
  const yzPct = d.yesterday_zt_avg_pct || 0;
  const yl = d.yesterday_cont_count || 0;
  const ylPct = d.yesterday_cont_avg_pct || 0;
  const yzColor = yzPct >= 0 ? 'var(--success)' : 'var(--danger)';
  const ylColor = ylPct >= 0 ? 'var(--success)' : 'var(--danger)';
  const yzPctStr = (yzPct >= 0 ? '+' : '') + fmt(yzPct, 2);
  const ylPctStr = (ylPct >= 0 ? '+' : '') + fmt(ylPct, 2);
  const statsHtml = `
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:16px">
      <div style="padding:12px;text-align:center;background:var(--bg);border-radius:var(--radius-sm);border:1px solid var(--border)">
        <div style="font-size:28px;font-weight:800;color:var(--success);line-height:1">${zt}</div>
        <div style="font-size:12px;color:var(--gray-500);margin-top:4px">涨停</div>
      </div>
      <div style="padding:12px;text-align:center;background:var(--bg);border-radius:var(--radius-sm);border:1px solid var(--border)">
        <div style="font-size:28px;font-weight:800;color:var(--danger);line-height:1">${dt}</div>
        <div style="font-size:12px;color:var(--gray-500);margin-top:4px">跌停</div>
      </div>
      <div style="padding:12px;text-align:center;background:var(--bg);border-radius:var(--radius-sm);border:1px solid var(--border)">
        <div style="font-size:28px;font-weight:800;color:#f59e0b;line-height:1">${zb}</div>
        <div style="font-size:12px;color:var(--gray-500);margin-top:4px">炸板 ${zbRate}%</div>
      </div>
      <div style="padding:12px;text-align:center;background:var(--bg);border-radius:var(--radius-sm);border:1px solid var(--border)">
        <div style="font-size:28px;font-weight:800;color:var(--gray-400);line-height:1">${amt}<span style="font-size:14px">亿</span></div>
        <div style="font-size:12px;color:var(--gray-500);margin-top:4px">成交额</div>
      </div>
      <div style="padding:12px;text-align:center;background:var(--bg);border-radius:var(--radius-sm);border:1px solid var(--border)">
        <div style="font-size:28px;font-weight:800;color:var(--success);line-height:1">${up}</div>
        <div style="font-size:12px;color:var(--gray-500);margin-top:4px">上涨</div>
      </div>
      <div style="padding:12px;text-align:center;background:var(--bg);border-radius:var(--radius-sm);border:1px solid var(--border)">
        <div style="font-size:28px;font-weight:800;color:var(--danger);line-height:1">${down}</div>
        <div style="font-size:12px;color:var(--gray-500);margin-top:4px">下跌</div>
      </div>
      <div style="padding:12px;text-align:center;background:var(--bg);border-radius:var(--radius-sm);border:1px solid var(--border)">
        <div style="font-size:20px;font-weight:800;color:${yzColor};line-height:1">${yzPctStr}%</div>
        <div style="font-size:11px;color:var(--gray-500);margin-top:4px">昨日涨停 <b style="color:var(--gray-400)">${yz}</b>只</div>
      </div>
      <div style="padding:12px;text-align:center;background:var(--bg);border-radius:var(--radius-sm);border:1px solid var(--border)">
        <div style="font-size:20px;font-weight:800;color:${ylColor};line-height:1">${ylPctStr}%</div>
        <div style="font-size:11px;color:var(--gray-500);margin-top:4px">昨日连板 <b style="color:var(--gray-400)">${yl}</b>只</div>
      </div>
    </div>`;

  // 涨停详情（同花顺数据：涨停原因、封单金额、连板天数）
  let ztDetailHtml = '';
  const ztDetail = d.limit_up_detail || [];
  if (ztDetail.length > 0) {
    ztDetailHtml = '<div class="card" style="margin-bottom:16px"><div class="card-title">📋 涨停详情 <span style="font-size:12px;font-weight:400;color:var(--gray-500)">' + ztDetail.length + '只</span></div>';
    ztDetailHtml += '<div style="max-height:300px;overflow-y:auto"><table class="table" style="font-size:12px"><thead><tr><th>股票</th><th>涨幅</th><th>涨停时间</th><th>连板</th><th>封单(万)</th><th>涨停原因</th></tr></thead><tbody>';
    for (const s of ztDetail) {
      const sealWan = s.seal_money ? (s.seal_money / 10000).toFixed(0) : '-';
      const sealColor = s.seal_money > 500000000 ? 'var(--success)' : s.seal_money > 100000000 ? 'var(--gray-300)' : 'var(--gray-500)';
      const contText = s.continue_day_text || (s.continue_day_cnt > 1 ? s.continue_day_cnt + '板' : '首板');
      const contColor = s.continue_day_cnt >= 3 ? '#f59e0b' : s.continue_day_cnt >= 2 ? 'var(--primary)' : 'var(--gray-400)';
      const reason = s.limit_up_reason || '-';
      const timeStr = s.limit_up_time || '-';
      ztDetailHtml += '<tr>' +
        '<td style="font-weight:500">' + s.name + ' <span style="color:var(--gray-500);font-size:11px">' + s.code + '</span></td>' +
        '<td style="color:var(--success);font-weight:600">+' + fmt(s.pct, 1) + '%</td>' +
        '<td>' + timeStr + '</td>' +
        '<td style="color:' + contColor + ';font-weight:600">' + contText + '</td>' +
        '<td style="color:' + sealColor + ';font-weight:500">' + sealWan + '</td>' +
        '<td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + reason + '">' + reason + '</td>' +
        '</tr>';
    }
    ztDetailHtml += '</tbody></table></div></div>';
  }

  // 炸板详情（同花顺数据）
  let zbDetailHtml = '';
  const zbDetail = d.broken_detail || [];
  if (zbDetail.length > 0) {
    zbDetailHtml = '<div class="card" style="margin-bottom:16px"><div class="card-title">💥 炸板详情 <span style="font-size:12px;font-weight:400;color:var(--gray-500)">' + zbDetail.length + '只</span></div>';
    zbDetailHtml += '<div style="display:flex;flex-wrap:wrap;gap:6px">';
    for (const s of zbDetail) {
      const ot = s.open_times || 0;
      const otColor = ot >= 3 ? 'var(--danger)' : ot >= 2 ? '#f59e0b' : 'var(--gray-400)';
      zbDetailHtml += '<span style="padding:4px 8px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);font-size:12px">' + s.name + ' <span style="color:var(--success)">+' + fmt(s.pct, 1) + '%</span> <span style="color:' + otColor + ';font-size:11px">炸' + ot + '次</span></span>';
    }
    zbDetailHtml += '</div></div>';
  }

  // 情绪周期折线图
  const hist = d.sentiment_history || [];
  let chartHtml = '';
  if (hist.length >= 2) {
    const W = 580, H = 140, PAD_L = 35, PAD_R = 10, PAD_T = 15, PAD_B = 25;
    const cW = W - PAD_L - PAD_R, cH = H - PAD_T - PAD_B;
    // 参考线
    const refLines = [{v:80, c:'#dc2626', l:'过热'},{v:60, c:'#f59e0b', l:'偏暖'},{v:40, c:'var(--gray-500)', l:'中性'},{v:20, c:'#3b82f6', l:'冰点'}];
    let svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" style="width:100%;height:140px">';
    // 网格+参考线
    for (const r of refLines) {
      const y = PAD_T + cH * (1 - r.v / 100);
      svg += '<line x1="' + PAD_L + '" y1="' + y + '" x2="' + (W - PAD_R) + '" y2="' + y + '" stroke="' + r.c + '" stroke-opacity="0.2" stroke-dasharray="3,3"/>';
      svg += '<text x="' + (PAD_L - 4) + '" y="' + (y + 3) + '" text-anchor="end" fill="' + r.c + '" font-size="9" opacity="0.6">' + r.v + '</text>';
    }
    // 数据点
    const pts = hist.map((h, i) => {
      const x = PAD_L + (i / (hist.length - 1)) * cW;
      const y = PAD_T + cH * (1 - Math.max(0, Math.min(100, h.value)) / 100);
      return {x, y, v: h.value, t: h.time};
    });
    // 折线
    const pathD = pts.map((p, i) => (i === 0 ? 'M' : 'L') + p.x.toFixed(1) + ',' + p.y.toFixed(1)).join(' ');
    svg += '<path d="' + pathD + '" fill="none" stroke="var(--primary)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>';
    // 面积填充
    svg += '<path d="' + pathD + ' L' + pts[pts.length-1].x.toFixed(1) + ',' + (PAD_T + cH) + ' L' + pts[0].x.toFixed(1) + ',' + (PAD_T + cH) + ' Z" fill="var(--primary)" fill-opacity="0.08"/>';
    // 圆点+最新值标注
    const last = pts[pts.length - 1];
    svg += '<circle cx="' + last.x + '" cy="' + last.y + '" r="4" fill="var(--primary)" stroke="#fff" stroke-width="1.5"/>';
    svg += '<text x="' + last.x + '" y="' + (last.y - 8) + '" text-anchor="middle" fill="var(--primary)" font-size="12" font-weight="700">' + last.v.toFixed(0) + '</text>';
    // X轴时间标签（取首尾+中间）
    const showIdx = [0, Math.floor(pts.length/2), pts.length-1];
    for (const i of showIdx) {
      svg += '<text x="' + pts[i].x + '" y="' + (H - 4) + '" text-anchor="middle" fill="var(--gray-500)" font-size="9">' + pts[i].t + '</text>';
    }
    svg += '</svg>';
    chartHtml = '<div class="card" style="margin-bottom:16px"><div class="card-title">情绪周期</div>' + svg + '</div>';
  }

  // 信号
  let signalsHtml = '';
  const signals = [];
  if (d.reseal && d.reseal.signal) {
    for (const [t, msg] of d.reseal.signal) signals.push(msg);
  }
  if (d.chain_gap && d.chain_gap.signal) {
    for (const [t, msg] of d.chain_gap.signal) signals.push(msg);
  }
  if (d.capital_shift && d.capital_shift.signal) {
    for (const [t, msg] of d.capital_shift.signal) signals.push(msg);
  }
  if (d.cross_signals) {
    for (const s of d.cross_signals) signals.push(s);
  }
  // 新增：策略信号引擎的信号
  if (d.strategy_signals) {
    for (const sig of d.strategy_signals) {
      signals.push((sig.icon || '') + ' ' + sig.msg);
    }
  }
  if (signals.length > 0) {
    signalsHtml = '<div style="margin-bottom:16px;padding:12px;background:var(--bg);border-radius:var(--radius-sm)">' +
      '<div style="font-size:13px;font-weight:600;margin-bottom:8px">🔔 信号</div>' +
      signals.map(s => '<div style="font-size:13px;margin-bottom:4px">' + s + '</div>').join('') + '</div>';
  }

  // KPH板块TOP5（实时数据）
  let kphHtml = '';
  const kph = d.kph_sectors || [];
  if (kph.length > 0) {
    const kphDate = kph[0].date || '';
    const dateNote = kphDate ? ' (' + kphDate + ')' : '';
    kphHtml = '<div style="margin-bottom:8px"><div style="font-size:13px;font-weight:600;margin-bottom:8px">🏆 KPH板块TOP5' + dateNote + '</div>';
    kphHtml += '<table class="table" style="font-size:13px"><thead><tr><th>#</th><th>板块</th><th>涨跌</th><th>强度</th><th>净流入(亿)</th><th>龙头股</th></tr></thead><tbody>';
    for (const s of kph.slice(0, 5)) {
      const chg = s.change_pct || 0;
      const color = chg >= 0 ? 'var(--success)' : 'var(--danger)';
      const medal = ['🥇','🥈','🥉','4.','5.'][s.rank - 1] || '';
      const leaders = s.leaders || '';
      kphHtml += '<tr>' +
        '<td>' + medal + '</td>' +
        '<td style="font-weight:500">' + s.name + '</td>' +
        '<td style="color:' + color + ';font-weight:600">' + (chg >= 0 ? '+' : '') + fmt(chg, 2) + '%</td>' +
        '<td>' + fmt(s.amount, 1) + '</td>' +
        '<td>' + fmt(s.net_inflow, 2) + '</td>' +
        '<td style="font-size:12px">' + leaders + '</td>' +
        '</tr>';
    }
    kphHtml += '</tbody></table></div>';
  }

  // 连板梯队
  let ladderHtml = '';
  const ladder = d.zt_ladder || [];
  if (ladder.length > 0) {
    const highest = d.zt_highest || 0;
    const total = d.zt_total || 0;
    ladderHtml = '<div class="card" style="margin-bottom:16px"><div class="card-title">连板梯队 <span style="font-size:12px;font-weight:400;color:var(--gray-500)">涨停' + total + '只 | 最高' + highest + '板</span></div>';
    for (const tier of ladder) {
      const stocks = tier.stocks || [];
      const lvl = tier.level || 1;
      const bgColor = lvl >= 5 ? '#dc2626' : lvl >= 3 ? '#f59e0b' : lvl >= 2 ? '#3b82f6' : 'var(--gray-600)';
      const label = lvl >= 5 ? '妖板' : lvl >= 3 ? '高板' : lvl >= 2 ? '连板' : '首板';
      ladderHtml += '<div style="margin-bottom:8px">';
      ladderHtml += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">';
      ladderHtml += '<span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:700;color:#fff;background:' + bgColor + '">' + lvl + '板</span>';
      ladderHtml += '<span style="font-size:11px;color:var(--gray-500)">' + tier.count + '只 · ' + label + '</span>';
      ladderHtml += '</div>';
      ladderHtml += '<div style="display:flex;flex-wrap:wrap;gap:4px">';
      const showStocks = lvl === 1 ? stocks.slice(0, 5) : stocks;
      for (const s of showStocks) {
        const ot = s.open_times || 0;
        const otTag = ot > 0 ? ' <span style="color:var(--danger);font-size:10px">炸' + ot + '</span>' : '';
        const t = String(s.first_zt_time || '');
        let timeTag = '';
        if (t.length >= 5) {
          const padded = t.length === 5 ? '0' + t : t;
          timeTag = ' <span style="color:var(--gray-500);font-size:10px">' + padded.slice(0,2) + ':' + padded.slice(2,4) + ':' + padded.slice(4,6) + '</span>';
        }
        ladderHtml += '<span class="badge badge-gray" style="font-size:12px">' + s.name + ' <span style="color:var(--success)">' + (s.pct >= 0 ? '+' : '') + fmt(s.pct, 1) + '%</span>' + timeTag + otTag + '</span>';
      }
      if (lvl === 1 && stocks.length > 5) ladderHtml += '<span class="badge badge-gray" style="font-size:11px">+' + (stocks.length - 5) + '只</span>';
      ladderHtml += '</div></div>';
    }
    ladderHtml += '</div>';
  }

  // ── 实时预测 ──
  let predHtml = '';
  const rp = d.realtime_prediction;
  if (rp && rp.sentiment) {
    const dir = rp.sentiment.direction;
    const dirIcon = dir === 'up' ? '📈' : dir === 'down' ? '📉' : '➡️';
    const dirColor = dir === 'up' ? 'var(--success)' : dir === 'down' ? 'var(--danger)' : 'var(--gray-400)';
    const dirText = dir === 'up' ? '偏涨' : dir === 'down' ? '偏跌' : '持平';
    const er = rp.sentiment.expected_range || {};
    const rangeText = er.low !== undefined ? er.low + '-' + er.high : '';
    const fds = rp.factor_descs || {};

    predHtml = '<div class="card" style="margin-bottom:16px"><div class="card-title">🔮 实时预测</div>';
    // 方向+预期
    predHtml += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px">';
    predHtml += '<div style="padding:10px;background:var(--bg);border-radius:var(--radius-sm);text-align:center">';
    predHtml += '<div style="font-size:24px;font-weight:800;color:' + dirColor + '">' + dirIcon + ' ' + dirText + '</div>';
    predHtml += '<div style="font-size:11px;color:var(--gray-500);margin-top:3px">' + (rp.sentiment.confidence || 0) + '%置信 · ' + (rp.sentiment.rule || '') + '</div>';
    if (rangeText) predHtml += '<div style="font-size:12px;color:var(--gray-400);margin-top:2px;font-weight:500">预期 ' + rangeText + '</div>';
    predHtml += '<div style="font-size:11px;color:var(--gray-500);margin-top:2px">' + (rp.sentiment.reason || '') + '</div>';
    predHtml += '</div>';
    // 风格
    const st = rp.style || {};
    const stIcon = st.result === 'switch' ? '🔄' : '➡️';
    const stText = st.result === 'switch' ? '切换' : '延续';
    predHtml += '<div style="padding:10px;background:var(--bg);border-radius:var(--radius-sm);text-align:center">';
    predHtml += '<div style="font-size:24px;font-weight:800;color:var(--gray-300)">' + stIcon + ' ' + stText + '</div>';
    predHtml += '<div style="font-size:11px;color:var(--gray-500);margin-top:3px">' + (st.confidence || 50) + '%置信</div>';
    predHtml += '<div style="font-size:11px;color:var(--gray-500);margin-top:2px">' + (st.reason || '') + '</div>';
    predHtml += '</div>';
    predHtml += '</div>';
    // 仓位
    const pos = rp.position || 50;
    const posColor = pos >= 60 ? 'var(--success)' : pos >= 40 ? 'var(--gray-400)' : 'var(--danger)';
    predHtml += '<div style="padding:8px 12px;background:var(--bg);border-radius:var(--radius-sm);margin-bottom:10px;display:flex;align-items:center;gap:8px">';
    predHtml += '<span style="font-size:18px;font-weight:700;color:' + posColor + '">' + pos + '%</span>';
    predHtml += '<span style="font-size:12px;color:var(--gray-500)">建议仓位</span>';
    predHtml += '</div>';
    // 因子状态（带描述）
    const rf = rp.factors || {};
    predHtml += '<div style="margin-bottom:4px">';
    const fItems = [
      {n:'情绪', v:rf.composite, d:fds.composite, icon:rf.composite<25?'🥶':rf.composite>75?'🔥':''},
      {n:'量比', v:rf.vol_ratio, d:fds.vol_ratio, icon:rf.vol_ratio>1.2?'📈':rf.vol_ratio<0.8?'📉':'', f:function(x){return x.toFixed(2)}},
      {n:'集中', v:rf.concentration, d:fds.concentration, icon:rf.concentration>60?'🎯':rf.concentration<30?'🌫️':'', f:function(x){return x.toFixed(0)+'%'}},
      {n:'池结构', v:rf.pool_composite, d:fds.pool_composite},
      {n:'预期差', v:rf.exp_gap, d:fds.exp_gap, icon:rf.exp_gap>15?'📈':rf.exp_gap<-15?'📉':'', f:function(x){return(x>=0?'+':'')+x.toFixed(1)}},
    ];
    for (const fi of fItems) {
      var fv = fi.f ? fi.f(fi.v) : fi.v;
      predHtml += '<div style="font-size:12px;margin-bottom:2px;display:flex;align-items:center;gap:4px">';
      predHtml += '<span style="color:var(--gray-500);width:45px;flex-shrink:0">' + (fi.icon||'') + ' ' + fi.n + '</span>';
      predHtml += '<span style="font-weight:600;min-width:50px">' + fv + '</span>';
      predHtml += '<span style="color:var(--gray-400);font-size:11px">' + (fi.d||'') + '</span>';
      predHtml += '</div>';
    }
    predHtml += '</div></div>';
  }

  el.innerHTML = chartHtml + predHtml + scoreHtml + statsHtml + ztDetailHtml + zbDetailHtml + signalsHtml + kphHtml + ladderHtml;
  // 异步加载大盘量能对比
  loadMarketVolumeCompare();
}

async function loadMarketVolumeCompare() {
  console.log('[IPO] loadMarketVolumeCompare called');
  const el = $('#rt-analysis');
  if (!el) { console.log('[IPO] rt-analysis not found'); return; }
  try {
    const volData = await api('/api/realtime/market_volume_compare', 15000);
    console.log('[IPO] volData:', volData.today?.length, 'today pts,', volData.prev?.length, 'prev pts');
    const todayPts = volData.today || [];
    const prevPts = volData.prev || [];
    const prevDate = volData.prev_date || '';
    if (todayPts.length < 1) { console.log('[IPO] no today points, skip'); return; }

    // 前日累计序列（分钟升序）：取"同分钟及之前最后一点"做阶跃插值
    // （旧实现要求两天采样分钟完全重合，稀疏采样下必为空 → 卡片被静默跳过）
    const prevSorted = prevPts.slice().sort((a, b) => (a.minute < b.minute ? -1 : 1));
    const prevAt = (minute) => {
      let v = 0;
      for (const p of prevSorted) {
        if (p.minute > minute) break;
        v = p.amount;
      }
      return v;
    };

    // 按今日时间点计算百分比差值曲线（前日同刻插值做基准）
    const curvePoints = todayPts.map(p => {
      const prevAmt = prevAt(p.minute);
      return prevAmt > 0 ? { minute: p.minute, amount: p.amount, prevAmt, pct: (p.amount - prevAmt) / prevAmt * 100 } : null;
    }).filter(Boolean);

    // 降级：前日完全没有可比窗口时也显示卡片（只显示实际量能），不再静默消失
    if (curvePoints.length === 0) {
      const cum0 = todayPts[todayPts.length - 1].amount || 0;
      el.insertAdjacentHTML('beforeend', `<div class="card" style="margin-bottom:16px">
        <div style="font-size:13px;font-weight:600">📊 市场量能</div>
        <div style="font-size:14px;margin-top:4px">沪深京 | 实际量能 <b>${cum0.toFixed(0)}亿</b></div>
        <div style="font-size:12px;color:var(--gray-500)">前日分钟数据不足，量能预测暂不可用</div>
      </div>`);
      return;
    }

    // 统计信息
    const lastPt = curvePoints[curvePoints.length - 1];
    const todayCumAmt = lastPt.amount || 0;
    const prevTotalAmt = lastPt.prevAmt || 0;

    // 预测量能：今日累计/昨日同期累计 × 昨日全天总量
    // 这样自然包含上午>下午的量能分布规律
    // 昨日全天总量优先用后端 CSV 精确值（不受采样中断影响），否则退回最后一点
    const prevFullDay = volData.prev_full_day_yi || (prevPts.length > 0 ? prevPts[prevPts.length - 1].amount : 0);
    const predictAmt = prevTotalAmt > 0 && prevFullDay > 0
      ? (todayCumAmt / prevTotalAmt * prevFullDay)
      : todayCumAmt;

    const totalChangePct = prevFullDay > 0 ? ((predictAmt - prevFullDay) / prevFullDay * 100).toFixed(1) : '0';
    const shrinkAmt = prevFullDay - predictAmt;
    const isShrink = predictAmt < prevFullDay;
    const changeColor = isShrink ? '#22c55e' : '#ef4444';
    const changeText = isShrink ? `缩量${Math.abs(shrinkAmt).toFixed(0)}亿` : `放量${Math.abs(shrinkAmt).toFixed(0)}亿`;

    // SVG折线图
    const W = 600, H = 160, PAD_L = 50, PAD_R = 10, PAD_T = 10, PAD_B = 30;
    const plotW = W - PAD_L - PAD_R;
    const plotH = H - PAD_T - PAD_B;

    // Y轴范围：百分比差值
    const pcts = curvePoints.map(p => p.pct);
    const minPct = Math.min(...pcts, -5);
    const maxPct = Math.max(...pcts, 0.5);
    const pctRange = maxPct - minPct || 1;

    const toX = (i) => PAD_L + (i / Math.max(curvePoints.length - 1, 1)) * plotW;
    const toY = (pct) => PAD_T + (1 - (pct - minPct) / pctRange) * plotH;

    // 折线路径
    const linePath = curvePoints.map((p, i) => `${i === 0 ? 'M' : 'L'}${toX(i).toFixed(1)},${toY(p.pct).toFixed(1)}`).join(' ');

    // 填充区域（从折线到中线y=0）
    const zeroY = toY(0);
    const areaPath = linePath + ` L${toX(curvePoints.length - 1).toFixed(1)},${zeroY.toFixed(1)} L${toX(0).toFixed(1)},${zeroY.toFixed(1)} Z`;

    // Y轴刻度
    const yTicks = [];
    const step = Math.ceil(pctRange / 4 / 5) * 5 || 5;
    for (let v = Math.ceil(minPct / step) * step; v <= maxPct; v += step) {
      yTicks.push(v);
    }

    const yTickHtml = yTicks.map(v => {
      const y = toY(v);
      return `<line x1="${PAD_L}" y1="${y.toFixed(1)}" x2="${W - PAD_R}" y2="${y.toFixed(1)}" stroke="var(--border)" stroke-dasharray="3,3" />
        <text x="${PAD_L - 4}" y="${(y + 3).toFixed(1)}" text-anchor="end" fill="var(--gray-400)" font-size="10">${v.toFixed(0)}%</text>`;
    }).join('');

    // X轴刻度（每2小时一个标签）
    const xLabels = ['09:30', '10:30', '11:30', '14:00', '15:00'];
    const xLabelHtml = xLabels.map(label => {
      const idx = curvePoints.findIndex(p => p.minute === label);
      if (idx < 0) return '';
      const x = toX(idx);
      return `<text x="${x.toFixed(1)}" y="${(H - 4).toFixed(1)}" text-anchor="middle" fill="var(--gray-400)" font-size="10">${label}</text>`;
    }).join('');

    // 中线（0%基准线）
    const zeroLineHtml = `<line x1="${PAD_L}" y1="${zeroY.toFixed(1)}" x2="${W - PAD_R}" y2="${zeroY.toFixed(1)}" stroke="var(--gray-500)" stroke-width="1" stroke-dasharray="4,2" />`;

    // 当前值标注
    const lastX = toX(curvePoints.length - 1);
    const lastY = toY(lastPt.pct);
    const lineColor = isShrink ? '#22c55e' : '#ef4444';
    const dotHtml = `<circle cx="${lastX.toFixed(1)}" cy="${lastY.toFixed(1)}" r="3" fill="${lineColor}" />
      <text x="${(lastX - 4).toFixed(1)}" y="${(lastY - 6).toFixed(1)}" text-anchor="end" fill="${lineColor}" font-size="11" font-weight="600">${lastPt.pct.toFixed(1)}%</text>`;

    const svgHtml = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:${H}px;display:block">
      ${yTickHtml}
      ${xLabelHtml}
      ${zeroLineHtml}
      <path d="${areaPath}" fill="${isShrink ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)'}" />
      <path d="${linePath}" fill="none" stroke="${lineColor}" stroke-width="2" stroke-linejoin="round" />
      ${dotHtml}
    </svg>`;

    const todayDate = new Date();
    const todayStr = (todayDate.getMonth()+1).toString().padStart(2,'0') + '-' + todayDate.getDate().toString().padStart(2,'0');
    const mktVolHtml = `<div class="card" style="margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
        <span style="font-size:13px;font-weight:600">📊 市场量能 ${todayStr}</span>
      </div>
      <div style="font-size:14px;margin-bottom:2px">
        沪深京 | 实际量能 <b>${todayCumAmt.toFixed(0)}亿</b>
      </div>
      <div style="font-size:14px;margin-bottom:8px;color:${changeColor}">
        今日 | 预测量能 <b style="color:${changeColor}">${predictAmt.toFixed(0)}亿(${totalChangePct}%,${changeText})</b>
      </div>
      ${svgHtml}
      <div style="font-size:11px;color:var(--gray-500);margin-top:4px">
        <span style="color:#ef4444">■</span> 红色=放量增量，<span style="color:#22c55e">■</span> 绿色=缩量
      </div>
    </div>`;
    console.log('[IPO] inserting volume chart into rt-analysis');
    el.insertAdjacentHTML('beforeend', mktVolHtml);
    console.log('[IPO] volume chart inserted successfully');
  } catch (e) { console.log('[IPO] error:', e.message); }
}

/* ── 自选股盘口深度分析 ── */
let _depthTimer = null;
let _selectedStock = null;

async function toggleStockDetail(code, name) {
  const panel = $('#rt-depth-panel');
  if (!panel) return;

  // 如果点的是同一只，切换收起
  if (_selectedStock === code) {
    closeDepthPanel();
    return;
  }

  _selectedStock = code;
  panel.style.display = 'block';
  $('#depth-title').textContent = name + ' (' + code + ') 盘口深度';
  $('#depth-content').innerHTML = '<div class="loading">加载盘口数据...</div>';

  // 加载并显示
  await refreshDepthPanel();

  // 启动轮询
  if (_depthTimer) clearInterval(_depthTimer);
  _depthTimer = setInterval(async () => {
    if (!_selectedStock || $('#rt-depth-panel')?.style.display !== 'block') return;
    await refreshDepthPanel();
  }, 3000);
}

function closeDepthPanel() {
  _selectedStock = null;
  const panel = $('#rt-depth-panel');
  if (panel) panel.style.display = 'none';
  if (_depthTimer) { clearInterval(_depthTimer); _depthTimer = null; }
}

async function refreshDepthPanel() {
  const contentEl = $('#depth-content');
  if (!contentEl || !_selectedStock) return;
  try {
    const data = await api('/api/realtime/watchlist_detail', 60000);
    const stocks = data.stocks || [];
    const stock = stocks.find(s => s.code === _selectedStock);
    if (!stock) {
      contentEl.innerHTML = '<p style="color:var(--gray-400);font-size:13px">无盘口数据</p>';
      return;
    }
    renderDepthPanel(contentEl, stock);
  } catch (e) {
    contentEl.innerHTML = '<p style="color:var(--danger);font-size:13px">加载失败: ' + e.message + '</p>';
  }
}

function renderDepthPanel(el, s) {
  const chg = s.change_pct || 0;
  const chgColor = chg >= 0 ? 'var(--success)' : 'var(--danger)';
  const imbColor = s.order_imbalance > 10 ? 'var(--success)' : s.order_imbalance < -10 ? 'var(--danger)' : 'var(--gray-500)';
  const intColor = s.internal_ratio > 55 ? 'var(--success)' : s.internal_ratio < 45 ? 'var(--danger)' : 'var(--gray-500)';

  // 多空力量卡片
  const powerHtml = `
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:16px">
      <div style="padding:10px;text-align:center;background:var(--bg);border-radius:var(--radius-sm)">
        <div style="font-size:24px;font-weight:800;color:${imbColor}">${s.order_imbalance>0?'+':''}${fmt(s.order_imbalance,1)}</div>
        <div style="font-size:11px;color:var(--gray-500)">委比%</div>
      </div>
      <div style="padding:10px;text-align:center;background:var(--bg);border-radius:var(--radius-sm)">
        <div style="font-size:24px;font-weight:800;color:${intColor}">${fmt(s.internal_ratio,1)}</div>
        <div style="font-size:11px;color:var(--gray-500)">内盘比%</div>
      </div>
      <div style="padding:10px;text-align:center;background:var(--bg);border-radius:var(--radius-sm)">
        <div style="font-size:24px;font-weight:800;color:${s.power_score>=60?'var(--success)':s.power_score<=40?'var(--danger)':'var(--gray-500)'}">${s.power_score}</div>
        <div style="font-size:11px;color:var(--gray-500)">力量分</div>
      </div>
      <div style="padding:10px;text-align:center;background:var(--bg);border-radius:var(--radius-sm)">
        <div style="font-size:24px;font-weight:800;color:var(--gray-400)">${fmt(s.concentration,1)}</div>
        <div style="font-size:11px;color:var(--gray-500)">集中度%</div>
      </div>
    </div>`;

  // 主买/主卖对比条
  const bv = s.b_vol || 0;
  const sv = s.s_vol || 0;
  const bTotal = bv + sv;
  const bPct = bTotal > 0 ? bv / bTotal * 100 : 50;
  const barHtml = `
    <div style="margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px">
        <span style="color:var(--success)">主买 ${bv}手 (${bPct.toFixed(0)}%)</span>
        <span style="color:var(--danger)">主卖 ${sv}手 (${(100-bPct).toFixed(0)}%)</span>
      </div>
      <div style="height:8px;border-radius:4px;background:var(--danger);overflow:hidden;display:flex">
        <div style="width:${bPct}%;background:var(--success);transition:width 0.3s"></div>
      </div>
    </div>`;

  // 五档明细
  const depth = s.depth || {};
  const bids = depth.bid || [];
  const asks = (depth.ask || []).slice().reverse();
  const maxVol = Math.max(
    ...bids.map(b => b.vol || 0),
    ...asks.map(a => a.vol || 0),
    1
  );
  let depthRows = '';
  for (const a of asks) {
    const w = (a.vol / maxVol * 100).toFixed(0);
    depthRows += `<tr>
      <td style="text-align:right;color:var(--gray-500);font-size:12px">卖 ${a.price}</td>
      <td style="text-align:right;font-family:monospace;font-size:12px">${a.vol}手</td>
      <td style="width:40%"><div style="height:16px;background:var(--danger);opacity:0.3;border-radius:2px;width:${w}%"></div></td>
    </tr>`;
  }
  for (const b of bids) {
    const w = (b.vol / maxVol * 100).toFixed(0);
    depthRows += `<tr>
      <td style="text-align:right;color:var(--gray-500);font-size:12px">买 ${b.price}</td>
      <td style="text-align:right;font-family:monospace;font-size:12px">${b.vol}手</td>
      <td style="width:40%"><div style="height:16px;background:var(--success);opacity:0.3;border-radius:2px;width:${w}%"></div></td>
    </tr>`;
  }
  const depthTable = `
    <div style="margin-bottom:16px">
      <table style="width:100%;border-collapse:collapse;font-size:12px">${depthRows}</table>
    </div>`;

  // 异动列表
  let alertsHtml = '';
  const alerts = s.alerts || [];
  if (alerts.length > 0) {
    alertsHtml = '<div style="margin-bottom:8px"><div style="font-size:13px;font-weight:600;margin-bottom:6px">⚡ 最近异动</div>';
    for (const a of alerts) {
      const icon = a.level === 'warning' ? '⚠️' : '📌';
      alertsHtml += '<div style="font-size:12px;margin-bottom:3px;color:var(--gray-400)">' + icon + ' ' + a.time + ' ' + a.msg + '</div>';
    }
    alertsHtml += '</div>';
  }

  // 价格信息
  const priceHtml = `
    <div style="display:flex;gap:16px;align-items:center;margin-bottom:16px;padding:10px;background:var(--bg);border-radius:var(--radius-sm)">
      <span style="font-size:20px;font-weight:700;color:${chgColor}">${fmt(s.price, 2)}</span>
      <span style="font-size:13px;color:${chgColor}">${chg>=0?'+':''}${fmt(chg, 2)}%</span>
      <span style="font-size:11px;color:var(--gray-400)">买加权 ${(s.bid_wavg||0).toFixed(3)} | 卖加权 ${(s.ask_wavg||0).toFixed(3)}</span>
    </div>`;

  // 数据解读
  const imb = s.order_imbalance || 0;
  const ir = s.internal_ratio || 50;
  const ps = s.power_score || 50;
  const conc = s.concentration || 0;
  const tips = [];
  if (imb > 30) tips.push({c:'var(--success)', t:'委比+' + fmt(imb,0) + '%，买盘挂单积极，下方承接强'});
  else if (imb < -30) tips.push({c:'var(--danger)', t:'委比' + fmt(imb,0) + '%，卖压沉重，上方抛压大'});
  else tips.push({c:'var(--gray-400)', t:'委比' + fmt(imb,0) + '%，多空博弈中'});
  if (ir > 60) tips.push({c:'var(--success)', t:'内盘比' + fmt(ir,0) + '%，主动买入占优，资金在流入'});
  else if (ir < 40) tips.push({c:'var(--danger)', t:'内盘比' + fmt(ir,0) + '%，主动卖出占优，资金在流出'});
  else tips.push({c:'var(--gray-400)', t:'内盘比' + fmt(ir,0) + '%，买卖均衡'});
  if (ps >= 60) tips.push({c:'var(--success)', t:'力量分' + ps + '，整体偏多，短线偏强'});
  else if (ps <= 40) tips.push({c:'var(--danger)', t:'力量分' + ps + '，整体偏空，短线偏弱'});
  else tips.push({c:'var(--gray-400)', t:'力量分' + ps + '，多空均衡'});
  if (conc > 20) tips.push({c:'var(--gray-400)', t:'集中度' + fmt(conc,0) + '%，有大单压档，关注突破方向'});
  else if (conc > 10) tips.push({c:'var(--gray-400)', t:'集中度' + fmt(conc,0) + '%，挂单较分散'});
  const tipsHtml = tips.map(t => '<div style="font-size:12px;color:' + t.c + ';line-height:1.6">• ' + t.t + '</div>').join('');
  const interpHtml = '<div style="margin-top:12px;padding:10px;background:var(--bg);border-radius:var(--radius-sm)"><div style="font-size:12px;font-weight:600;margin-bottom:6px;color:var(--gray-300)">📊 数据解读</div>' + tipsHtml + '</div>';

  el.innerHTML = priceHtml + powerHtml + barHtml + depthTable + alertsHtml + interpHtml;
}


