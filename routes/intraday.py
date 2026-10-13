"""盘中监测仪表盘 — API + 实时页面"""
import json
import os
import glob
from datetime import datetime

from fastapi import Query
from fastapi.responses import HTMLResponse, JSONResponse

from config import BASE_DIR

LOG_DIR = BASE_DIR / 'logs'


def _get_today_log():
    today = datetime.now().strftime('%Y%m%d')
    return LOG_DIR / f'intraday_{today}.jsonl'


def _get_latest_log():
    """获取最近一天的日志文件"""
    files = sorted(glob.glob(str(LOG_DIR / 'intraday_*.jsonl')), reverse=True)
    return files[0] if files else None


def _read_fast_snapshots(n: int = 10) -> list:
    """读取最近 n 条自选股快速快照"""
    today = datetime.now().strftime('%Y%m%d')
    fast_file = LOG_DIR / f'fast_{today}.jsonl'
    if not fast_file.exists():
        return []
    snapshots = []
    try:
        with open(fast_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        snapshots.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except Exception:
        pass
    return snapshots[-n:] if len(snapshots) > n else snapshots


def _read_snapshots(n: int = 60) -> list:
    """读取最近 n 条快照"""
    log_file = _get_today_log()
    if not log_file.exists():
        log_file = _get_latest_log()
    if not log_file or not os.path.exists(log_file):
        return []

    snapshots = []
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        snapshots.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except Exception:
        pass

    return snapshots[-n:] if len(snapshots) > n else snapshots


_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>盘中监测 v2</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f1117; color: #e0e0e0; min-height: 100vh; }
.container { max-width: 960px; margin: 0 auto; padding: 16px; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
h1 { font-size: 20px; color: #fff; }
.status { font-size: 13px; padding: 4px 12px; border-radius: 12px; }
.status-live { background: #10b981; color: #fff; animation: pulse 2s infinite; }
.status-off { background: #555; color: #ccc; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 16px; }
.metric-card { background: #1a1d2e; border: 1px solid #2a2d3e; border-radius: 10px; padding: 14px; text-align: center; }
.metric-label { font-size: 12px; color: #888; margin-bottom: 4px; }
.metric-value { font-size: 28px; font-weight: 700; }
.metric-sub { font-size: 11px; color: #666; margin-top: 2px; }
.c-red { color: #ef4444; }
.c-green { color: #10b981; }
.c-yellow { color: #f59e0b; }
.c-blue { color: #3b82f6; }
.c-purple { color: #a855f7; }
.c-white { color: #fff; }
.section { background: #1a1d2e; border: 1px solid #2a2d3e; border-radius: 10px; padding: 16px; margin-bottom: 16px; }
.section-title { font-size: 15px; font-weight: 600; color: #fff; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
.signal-list { list-style: none; }
.signal-list li { padding: 8px 12px; border-bottom: 1px solid #252840; font-size: 13px; display: flex; align-items: center; gap: 8px; }
.signal-list li:last-child { border-bottom: none; }
.signal-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.dot-red { background: #ef4444; }
.dot-yellow { background: #f59e0b; }
.dot-green { background: #10b981; }
.dot-blue { background: #3b82f6; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; padding: 8px; color: #888; border-bottom: 1px solid #2a2d3e; font-weight: 500; }
td { padding: 8px; border-bottom: 1px solid #1e2130; }
tr:hover { background: #1e2130; }
.chart-container { height: 200px; position: relative; margin-top: 12px; }
canvas { width: 100% !important; height: 100% !important; }
.empty { text-align: center; color: #555; padding: 40px; font-size: 14px; }
.refresh-info { font-size: 11px; color: #555; text-align: right; margin-top: 8px; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>📡 盘中监测</h1>
    <span id="status" class="status status-off">离线</span>
  </div>

  <!-- 核心指标 -->
  <div class="grid" id="metrics">
    <div class="metric-card"><div class="metric-label">情绪分</div><div class="metric-value c-white" id="m-sentiment">--</div><div class="metric-sub" id="m-mood"></div></div>
    <div class="metric-card"><div class="metric-label">💰 赚钱效应</div><div class="metric-value c-white" id="m-profit">--</div><div class="metric-sub" id="m-profit-level"></div></div>
    <div class="metric-card"><div class="metric-label">涨跌比</div><div class="metric-value c-white" id="m-ratio">--</div><div class="metric-sub" id="m-updown"></div></div>
    <div class="metric-card"><div class="metric-label">涨停 / 跌停</div><div class="metric-value" id="m-zt">--</div><div class="metric-sub" id="m-zt-sub"></div></div>
    <div class="metric-card"><div class="metric-label">炸板率</div><div class="metric-value" id="m-zb">--</div><div class="metric-sub" id="m-zb-sub"></div></div>
    <div class="metric-card"><div class="metric-label">成交额</div><div class="metric-value c-blue" id="m-amount">--</div><div class="metric-sub" id="m-amount-sub"></div></div>
    <div class="metric-card"><div class="metric-label">更新时间</div><div class="metric-value c-white" id="m-time" style="font-size:18px">--:--</div><div class="metric-sub" id="m-date"></div></div>
  </div>

  <!-- 信号列表 -->
  <div class="section">
    <div class="section-title">🔔 实时信号</div>
    <ul class="signal-list" id="signals"><li class="empty">等待数据...</li></ul>
  </div>

  <!-- 情绪走势 -->
  <div class="section">
    <div class="section-title">📈 情绪 & 赚钱效应（今日）<span style="font-size:11px;font-weight:400;margin-left:12px"><span style="color:#3b82f6">● 情绪</span> <span style="color:#f59e0b;margin-left:8px">● 赚钱</span></span></div>
    <div class="chart-container"><canvas id="chart"></canvas></div>
  </div>

  <!-- 自选股实时 -->
  <div class="section">
    <div class="section-title">📋 自选股实时 <span style="font-size:11px;color:#10b981;margin-left:8px">5秒刷新</span></div>
    <div style="overflow-x:auto">
      <table id="wl-table"><thead><tr><th>代码</th><th>名称</th><th>价格</th><th>涨幅</th><th>最高</th><th>最低</th><th>时间</th></tr></thead><tbody><tr><td colspan="7" style="text-align:center;color:#555">等待数据...</td></tr></tbody></table>
    </div>
  </div>

  <div class="refresh-info">全市场 60 秒 · 自选股 5 秒自动刷新 · <a href="/api/intraday/snapshots" style="color:#3b82f6">原始数据</a></div>
</div>

<script>
let lastTime = '';
let sentimentHistory = [];

async function fetchData() {
  try {
    const r = await fetch('/api/intraday/latest');
    if (!r.ok) return;
    const d = await r.json();
    if (!d.time) return;
    if (d.time === lastTime) return; // 无新数据
    lastTime = d.time;
    updateUI(d);
  } catch(e) {}
}

function updateUI(d) {
  // 状态
  const st = document.getElementById('status');
  st.textContent = '实时';
  st.className = 'status status-live';

  // 指标
  document.getElementById('m-sentiment').textContent = d.sentiment_score ?? '--';
  const sentEl = document.getElementById('m-sentiment');
  sentEl.className = 'metric-value ' + (d.sentiment_score >= 60 ? 'c-green' : d.sentiment_score <= 30 ? 'c-red' : 'c-white');
  document.getElementById('m-mood').textContent = d.mood ?? '';
  // 赚钱效应
  document.getElementById('m-profit').textContent = d.profit_score ?? '--';
  const profEl = document.getElementById('m-profit');
  profEl.className = 'metric-value ' + (d.profit_score >= 60 ? 'c-green' : d.profit_score <= 30 ? 'c-red' : 'c-yellow');
  document.getElementById('m-profit-level').textContent = d.profit_level ?? '';
  document.getElementById('m-ratio').textContent = d.up_down_ratio?.toFixed(2) ?? '--';
  document.getElementById('m-updown').textContent = `${d.total_up||0} ↑ / ${d.total_down||0} ↓`;
  const zt = d.limit_up_count ?? 0;
  const dt = d.limit_down_count ?? 0;
  document.getElementById('m-zt').innerHTML = `<span class="c-red">${zt}</span> / <span class="c-green">${dt}</span>`;
  document.getElementById('m-zt-sub').textContent = `封板 ${zt} 炸板 ${d.broken_count||0}`;
  const zbRate = d.broken_rate ?? 0;
  document.getElementById('m-zb').className = 'metric-value ' + (zbRate > 40 ? 'c-red' : zbRate > 25 ? 'c-yellow' : 'c-green');
  document.getElementById('m-zb').textContent = zbRate.toFixed(1) + '%';
  document.getElementById('m-zb-sub').textContent = zbRate > 40 ? '⚠ 高炸板' : zbRate > 25 ? '偏高' : '正常';
  const amt = d.total_amount_yi ?? 0;
  document.getElementById('m-amount').textContent = (amt / 10000).toFixed(1) + '万亿';
  document.getElementById('m-amount-sub').textContent = amt.toFixed(0) + '亿';
  document.getElementById('m-time').textContent = d.time ?? '--';
  document.getElementById('m-date').textContent = new Date().toLocaleDateString('zh-CN');

  // 信号
  renderSignals(d);


  // 情绪走势
  sentimentHistory.push({ time: d.time, score: d.sentiment_score, profit: d.profit_score });
  if (sentimentHistory.length > 120) sentimentHistory.shift();
  drawChart();
}

function renderSignals(d) {
  const el = document.getElementById('signals');
  const signals = [];

  if (d.sentiment_score <= 25) signals.push({ color: 'red', text: `🧊 冰点预警：情绪 ${d.sentiment_score}` });
  if (d.broken_rate > 40) signals.push({ color: 'red', text: `💣 高炸板率：${d.broken_rate.toFixed(1)}%` });
  if (d.up_down_ratio > 2) signals.push({ color: 'green', text: `🟢 强势：涨跌比 ${d.up_down_ratio.toFixed(2)}` });
  if (d.up_down_ratio < 0.5) signals.push({ color: 'red', text: `🔴 弱势：涨跌比 ${d.up_down_ratio.toFixed(2)}` });
  if (d.limit_up_count > 80) signals.push({ color: 'green', text: `🔥 涨停潮：${d.limit_up_count} 只涨停` });
  if (d.limit_down_count > 20) signals.push({ color: 'red', text: `💀 跌停潮：${d.limit_down_count} 只跌停` });
  if (d.total_amount_yi > 30000) signals.push({ color: 'blue', text: `💰 放量：成交 ${d.total_amount_yi.toFixed(0)} 亿` });
  // 赚钱效应信号
  if (d.profit_score != null) {
    if (d.profit_score >= 70 && d.sentiment_score < 50) signals.push({ color: 'yellow', text: `⚠️ 赚钱效应强(${d.profit_score})但情绪弱(${d.sentiment_score})，结构性行情` });
    if (d.profit_score <= 30 && d.sentiment_score > 60) signals.push({ color: 'yellow', text: `⚠️ 情绪偏暖(${d.sentiment_score})但赚钱效应差(${d.profit_score})，指数虚涨` });
    if (d.profit_score >= 75) signals.push({ color: 'green', text: `💰 赚钱效应极强：${d.profit_score}分` });
    if (d.profit_score <= 20) signals.push({ color: 'red', text: `💸 赚钱效应极弱：${d.profit_score}分，亏钱明显` });
  }

  // 交叉信号
  if (d.cross_signals) {
    d.cross_signals.forEach(s => {
      if (s.includes('🔥') || s.includes('🧊')) signals.push({ color: 'red', text: s });
      else if (s.includes('⚠')) signals.push({ color: 'yellow', text: s });
      else signals.push({ color: 'blue', text: s });
    });
  }

  // 炸板回封
  if (d.reseal_result?.signals?.length) {
    d.reseal_result.signals.forEach(s => signals.push({ color: 'yellow', text: '🔄 ' + s }));
  }

  // 连板断层
  if (d.chain_gap?.signal) signals.push({ color: 'yellow', text: '🔗 ' + d.chain_gap.signal });

  // 资金异动
  if (d.capital_shift?.signal) signals.push({ color: 'blue', text: '💹 ' + d.capital_shift.signal });

  if (!signals.length) {
    el.innerHTML = '<li class="empty">暂无信号</li>';
    return;
  }
  el.innerHTML = signals.map(s =>
    `<li><span class="signal-dot dot-${s.color}"></span>${s.text}</li>`
  ).join('');
}

function drawChart() {
  const canvas = document.getElementById('chart');
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);
  const W = rect.width, H = rect.height;
  ctx.clearRect(0, 0, W, H);

  if (sentimentHistory.length < 2) {
    ctx.fillStyle = '#555';
    ctx.font = '14px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('等待更多数据...', W/2, H/2);
    return;
  }

  const pad = { top: 20, right: 20, bottom: 30, left: 40 };
  const cw = W - pad.left - pad.right;
  const ch = H - pad.top - pad.bottom;

  const allVals = sentimentHistory.flatMap(h => [h.score, h.profit].filter(v => v != null));
  const minV = Math.min(...allVals) - 5;
  const maxV = Math.max(...allVals) + 5;
  const range = maxV - minV || 1;

  // 网格
  ctx.strokeStyle = '#1e2130';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + ch * i / 4;
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(W - pad.right, y); ctx.stroke();
    ctx.fillStyle = '#555'; ctx.font = '11px sans-serif'; ctx.textAlign = 'right';
    ctx.fillText(Math.round(maxV - range * i / 4), pad.left - 8, y + 4);
  }

  // 情绪分线
  ctx.beginPath();
  ctx.strokeStyle = '#3b82f6';
  ctx.lineWidth = 2;
  sentimentHistory.forEach((h, i) => {
    const x = pad.left + cw * i / (sentimentHistory.length - 1);
    const y = pad.top + ch * (1 - (h.score - minV) / range);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();

  // 赚钱效应线（橙）
  const hasProfit = sentimentHistory.some(h => h.profit != null);
  if (hasProfit) {
    ctx.beginPath();
    ctx.strokeStyle = '#f59e0b';
    ctx.lineWidth = 2;
    let first = true;
    sentimentHistory.forEach((h, i) => {
      if (h.profit == null) return;
      const x = pad.left + cw * i / (sentimentHistory.length - 1);
      const y = pad.top + ch * (1 - (h.profit - minV) / range);
      if (first) { ctx.moveTo(x, y); first = false; } else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  // 关键线
  ctx.setLineDash([4, 4]);
  ctx.strokeStyle = '#ef444466';
  const iceY = pad.top + ch * (1 - (25 - minV) / range);
  ctx.beginPath(); ctx.moveTo(pad.left, iceY); ctx.lineTo(W - pad.right, iceY); ctx.stroke();
  ctx.fillStyle = '#ef444488'; ctx.font = '10px sans-serif'; ctx.textAlign = 'left';
  ctx.fillText('冰点 25', pad.left + 4, iceY - 4);

  ctx.strokeStyle = '#f59e0b66';
  const warnY = pad.top + ch * (1 - (40 - minV) / range);
  ctx.beginPath(); ctx.moveTo(pad.left, warnY); ctx.lineTo(W - pad.right, warnY); ctx.stroke();
  ctx.fillStyle = '#f59e0b88';
  ctx.fillText('偏冷 40', pad.left + 4, warnY - 4);
  ctx.setLineDash([]);

  // 时间轴
  ctx.fillStyle = '#555'; ctx.font = '10px sans-serif'; ctx.textAlign = 'center';
  const step = Math.max(1, Math.floor(sentimentHistory.length / 6));
  sentimentHistory.forEach((h, i) => {
    if (i % step === 0 || i === sentimentHistory.length - 1) {
      const x = pad.left + cw * i / (sentimentHistory.length - 1);
      ctx.fillText(h.time.slice(0, 5), x, H - 8);
    }
  });

  // 最新值标注 — 情绪
  const last = sentimentHistory[sentimentHistory.length - 1];
  const lx = pad.left + cw;
  const ly = pad.top + ch * (1 - (last.score - minV) / range);
  ctx.fillStyle = '#3b82f6';
  ctx.beginPath(); ctx.arc(lx, ly, 4, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = '#3b82f6'; ctx.font = 'bold 12px sans-serif'; ctx.textAlign = 'left';
  ctx.fillText('情绪 ' + last.score, lx + 8, ly - 4);

  // 最新值标注 — 赚钱效应
  if (last.profit != null) {
    const py = pad.top + ch * (1 - (last.profit - minV) / range);
    ctx.fillStyle = '#f59e0b';
    ctx.beginPath(); ctx.arc(lx, py, 4, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#f59e0b';
    ctx.fillText('赚钱 ' + last.profit, lx + 8, py + 14);
  }
}
fetchData();
setInterval(fetchData, 30000);

// 自选股快速刷新
let lastFastTime = '';
async function fetchFast() {
  try {
    const r = await fetch('/api/intraday/fast');
    if (!r.ok) return;
    const d = await r.json();
    if (!d.time || d.time === lastFastTime) return;
    lastFastTime = d.time;
    renderWatchlist(d.stocks || {});
  } catch(e) {}
}
function renderWatchlist(stocks) {
  const tbody = document.querySelector('#wl-table tbody');
  const codes = Object.keys(stocks);
  if (!codes.length) { tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#555">暂无自选股</td></tr>'; return; }
  tbody.innerHTML = codes.map(code => {
    const s = stocks[code];
    const pct = s.pct || 0;
    const cls = pct >= 9.9 ? 'c-red' : pct > 0 ? 'c-red' : pct < 0 ? 'c-green' : 'c-white';
    return '<tr><td>'+s.code+'</td><td>'+s.name+'</td><td>'+(s.price||0).toFixed(2)+'</td><td class="'+cls+'">'+(pct>=0?'+':'')+pct.toFixed(2)+'%</td><td>'+(s.high||0).toFixed(2)+'</td><td>'+(s.low||0).toFixed(2)+'</td><td>'+(s.time||'')+'</td></tr>';
  }).join('');
}
fetchFast();
setInterval(fetchFast, 5000);
window.addEventListener('resize', drawChart);
</script>
</body>
</html>"""


def register_intraday_routes(app):

    @app.get('/api/intraday/fast')
    def intraday_fast():
        """获取自选股最新快速快照（5秒刷新）"""
        snaps = _read_fast_snapshots(1)
        if not snaps:
            return JSONResponse(content={'status': 'offline', 'message': '无快速数据'})
        return snaps[-1]

    @app.get('/api/intraday/fast/history')
    def intraday_fast_history(n: int = Query(60, ge=1, le=500)):
        """获取自选股快速快照历史"""
        snaps = _read_fast_snapshots(n)
        return {'count': len(snaps), 'snapshots': snaps}

    @app.get('/intraday', response_class=HTMLResponse)
    def intraday_page():
        return HTMLResponse(content=_HTML, headers={'Cache-Control': 'no-cache, no-store, must-revalidate', 'Pragma': 'no-cache'})

    @app.get('/api/intraday/latest')
    def intraday_latest():
        """获取最新一条盘中快照"""
        snaps = _read_snapshots(1)
        if not snaps:
            return JSONResponse(content={'status': 'offline', 'message': '盘中监测未运行或无数据'})
        return snaps[-1]

    @app.get('/api/intraday/snapshots')
    def intraday_snapshots(n: int = Query(60, ge=1, le=500)):
        """获取最近 n 条盘中快照"""
        snaps = _read_snapshots(n)
        return {'count': len(snaps), 'snapshots': snaps}

    @app.get('/api/intraday/signals')
    def intraday_signals():
        """获取最新快照的信号摘要"""
        snaps = _read_snapshots(1)
        if not snaps:
            return {'signals': [], 'status': 'offline'}
        d = snaps[-1]
        signals = []

        sent = d.get('sentiment_score', 50)
        zb_rate = d.get('broken_rate', 0)
        ratio = d.get('up_down_ratio', 1)
        zt = d.get('limit_up_count', 0)
        dt = d.get('limit_down_count', 0)
        amt = d.get('total_amount_yi', 0)

        if sent <= 25:
            signals.append({'level': 'critical', 'text': f'🧊 冰点预警：情绪 {sent}'})
        if zb_rate > 40:
            signals.append({'level': 'critical', 'text': f'💣 高炸板率：{zb_rate:.1f}%'})
        if ratio > 2:
            signals.append({'level': 'info', 'text': f'🟢 强势：涨跌比 {ratio:.2f}'})
        if ratio < 0.5:
            signals.append({'level': 'critical', 'text': f'🔴 弱势：涨跌比 {ratio:.2f}'})
        if zt > 80:
            signals.append({'level': 'warning', 'text': f'🔥 涨停潮：{zt} 只涨停'})
        if dt > 20:
            signals.append({'level': 'critical', 'text': f'💀 跌停潮：{dt} 只跌停'})
        if amt > 30000:
            signals.append({'level': 'info', 'text': f'💰 放量：成交 {amt:.0f} 亿'})

        return {
            'time': d.get('time', ''),
            'sentiment': sent,
            'signals': signals,
            'status': 'live',
        }
