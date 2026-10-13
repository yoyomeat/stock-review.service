/**
 * 板块数据 — 前端模块
 * 浏览 wave_analysis.db 中的所有表
 */

const WAVE_TABLES = [
  { key: 'index_daily',    label: '指数日K',   hasCode: true,  dateCol: 'trade_date' },
  { key: 'weekly_kline',   label: '周K线',     hasCode: true,  dateCol: 'period_start' },
  { key: 'monthly_kline',  label: '月K线',     hasCode: true,  dateCol: 'period_start' },
  { key: 'concept_names',  label: '名称映射',  hasCode: true,  dateCol: 'updated_at' },
  { key: 'concept_daily',  label: '概念日K',   hasCode: true,  dateCol: 'trade_date' },
  { key: 'trading_calendar', label: '交易日历', hasCode: false, dateCol: 'trade_date' },
  { key: 'zigzag_points',  label: 'Zigzag拐点', hasCode: true, dateCol: 'trade_date' },
  { key: 'wave_labels',    label: '波浪标注',  hasCode: true,  dateCol: 'start_date' },
  { key: 'wave_counts',    label: '波浪计数',  hasCode: true,  dateCol: 'created_at' },
  { key: 'signal_events',  label: '信号事件',  hasCode: true,  dateCol: 'event_date' },
  { key: 'alert_rules',    label: '告警规则',  hasCode: false, dateCol: 'created_at' },
  { key: 'alert_history',  label: '告警历史',  hasCode: true,  dateCol: 'alert_date' },
  { key: 'data_quality_log', label: '质量日志', hasCode: true, dateCol: 'created_at' },
];

let waveState = {
  currentTable: 'index_daily',
  page: 1,
  pageSize: 50,
  code: null,
  sortBy: null,
  sortOrder: 'desc',
  codes: [],
};

async function loadWaveDbPage() {
  window._waveLoaded = true;
  await loadWaveOverview();
  await loadWaveTable('index_daily');
}

async function loadWaveOverview() {
  try {
    const data = await waveApi('/wave/db/overview');
    const el = $('#wave-overview');
    if (!el) return;

    let html = '<div class="wave-overview-grid">';
    for (const t of data.tables) {
      const sizeClass = t.rows > 0 ? 'has-data' : 'empty';
      let detail = '';
      if (t.detail && t.detail.codes) {
        detail = `${t.detail.codes}个品种 · ${t.detail.min_date}~${t.detail.max_date}`;
      }
      html += `
        <div class="wave-stat-card ${sizeClass}" onclick="loadWaveTable('${t.table}')">
          <div class="wave-stat-label">${t.label}</div>
          <div class="wave-stat-value">${t.rows.toLocaleString()}</div>
          <div class="wave-stat-detail">${detail || '&nbsp;'}</div>
        </div>`;
    }
    html += '</div>';

    const dbMB = (data.db_size / 1024 / 1024).toFixed(1);
    html = `<div class="wave-db-info">数据库大小: ${dbMB} MB</div>` + html;
    el.innerHTML = html;
  } catch (e) {
    $('#wave-overview').innerHTML = `<div class="error">加载失败: ${e.message}</div>`;
  }
}

async function loadWaveTable(table, page) {
  waveState.currentTable = table;
  waveState.page = page || 1;

  // 高亮当前表
  $$('.wave-table-tab').forEach(b => b.classList.remove('active'));
  const btn = $(`.wave-table-tab[data-table="${table}"]`);
  if (btn) btn.classList.add('active');

  const content = $('#wave-table-content');
  content.innerHTML = '<div class="loading">加载中...</div>';

  try {
    let url = `/wave/db/browse/${table}?page=${waveState.page}&page_size=${waveState.pageSize}`;
    if (waveState.code) url += `&code=${encodeURIComponent(waveState.code)}`;
    if (waveState.sortBy) url += `&sort_by=${waveState.sortBy}&sort_order=${waveState.sortOrder}`;

    const data = await api(url);

    // 更新代码筛选
    if (data.rows.length > 0 && data.rows[0].code !== undefined) {
      await loadWaveCodeFilter(table);
    }

    // 渲染表格
    let html = '<div class="wave-table-wrap"><table class="wave-table"><thead><tr>';
    for (const col of data.columns) {
      const isSorted = waveState.sortBy === col;
      const arrow = isSorted ? (waveState.sortOrder === 'desc' ? ' ▼' : ' ▲') : '';
      html += `<th onclick="waveSort('${col}')" ${isSorted ? 'class="sorted"' : ''}>${col}${arrow}</th>`;
    }
    html += '</tr></thead><tbody>';

    for (const row of data.rows) {
      html += '<tr>';
      for (const col of data.columns) {
        let v = row[col];
        if (v === null || v === undefined) v = '<span class="null">NULL</span>';
        else if (typeof v === 'number') v = v.toLocaleString();
        html += `<td>${v}</td>`;
      }
      html += '</tr>';
    }
    html += '</tbody></table></div>';

    // 分页
    html += `<div class="wave-pagination">
      <button ${data.page <= 1 ? 'disabled' : ''} onclick="loadWaveTable('${table}', 1)">首页</button>
      <button ${data.page <= 1 ? 'disabled' : ''} onclick="loadWaveTable('${table}', ${data.page - 1})">上一页</button>
      <span class="page-info">${data.page} / ${data.total_pages} (${data.total.toLocaleString()} 行)</span>
      <button ${data.page >= data.total_pages ? 'disabled' : ''} onclick="loadWaveTable('${table}', ${data.page + 1})">下一页</button>
      <button ${data.page >= data.total_pages ? 'disabled' : ''} onclick="loadWaveTable('${table}', ${data.total_pages})">末页</button>
      <select onchange="waveChangePageSize(this.value)">
        ${[20, 50, 100, 200].map(s => `<option value="${s}" ${s === waveState.pageSize ? 'selected' : ''}>${s}行/页</option>`).join('')}
      </select>
    </div>`;

    content.innerHTML = html;
  } catch (e) {
    content.innerHTML = `<div class="error">加载失败: ${e.message}</div>`;
  }
}

async function loadWaveCodeFilter(table) {
  const sel = $('#wave-code-filter');
  if (!sel) return;

  const info = WAVE_TABLES.find(t => t.key === table);
  if (!info || !info.hasCode) {
    sel.innerHTML = '<option value="">全部</option>';
    sel.style.display = 'none';
    return;
  }

  try {
    let codes = [];
    if (table.startsWith('index') || table.startsWith('weekly') || table.startsWith('monthly')) {
      codes = await waveApi('/wave/db/indexes');
    } else if (table.startsWith('sector')) {
      codes = await waveApi('/wave/db/sectors');
    } else if (table.startsWith('concept')) {
      codes = await waveApi('/wave/db/concepts');
    } else {
      // 通用：从当前表获取 code 列表
      const data = await waveApi(`/wave/db/browse/${table}?page_size=1`);
      if (data.columns.includes('code')) {
        const res = await waveApi(`/wave/db/query`, 'POST', { sql: `SELECT DISTINCT code FROM ${table} ORDER BY code LIMIT 500` });
        if (res.rows) codes = res.rows.map(r => ({ code: r[0] }));
      }
    }

    let html = '<option value="">全部</option>';
    for (const c of codes) {
      const code = c.code;
      const label = c.code + (c.rows ? ` (${c.rows})` : '');
      html += `<option value="${code}" ${code === waveState.code ? 'selected' : ''}>${label}</option>`;
    }
    sel.innerHTML = html;
    sel.style.display = '';
  } catch (e) {
    sel.style.display = 'none';
  }
}

function waveFilterCode(code) {
  waveState.code = code || null;
  waveState.page = 1;
  loadWaveTable(waveState.currentTable);
}

function waveSort(col) {
  if (waveState.sortBy === col) {
    waveState.sortOrder = waveState.sortOrder === 'desc' ? 'asc' : 'desc';
  } else {
    waveState.sortBy = col;
    waveState.sortOrder = 'desc';
  }
  waveState.page = 1;
  loadWaveTable(waveState.currentTable);
}

function waveChangePageSize(size) {
  waveState.pageSize = parseInt(size);
  waveState.page = 1;
  loadWaveTable(waveState.currentTable);
}

async function waveQuery() {
  const sql = $('#wave-sql-input').value.trim();
  if (!sql) return;

  const result = $('#wave-query-result');
  result.innerHTML = '<div class="loading">查询中...</div>';

  try {
    const data = await waveApi('/wave/db/query', 'POST', { sql });
    if (data.error) {
      result.innerHTML = `<div class="error">${data.error}</div>`;
      return;
    }

    let html = `<div class="wave-query-info">${data.count} 行</div>`;
    html += '<div class="wave-table-wrap"><table class="wave-table"><thead><tr>';
    for (const col of data.columns) {
      html += `<th>${col}</th>`;
    }
    html += '</tr></thead><tbody>';
    for (const row of data.rows) {
      html += '<tr>';
      for (const v of row) {
        const display = v === null ? '<span class="null">NULL</span>' : v;
        html += `<td>${display}</td>`;
      }
      html += '</tr>';
    }
    html += '</tbody></table></div>';
    result.innerHTML = html;
  } catch (e) {
    result.innerHTML = `<div class="error">${e.message}</div>`;
  }
}

// POST helper (独立函数，不覆盖全局 api)
async function waveApi(path, method, body) {
  const opts = { headers: {} };
  if (method === 'POST' && body) {
    opts.method = 'POST';
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(API_BASE + path, opts);
  if (!r.ok) throw new Error(`API error: ${r.status}`);
  return r.json();
}
