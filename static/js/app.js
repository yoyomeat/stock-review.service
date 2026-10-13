const API_BASE = '';

async function api(path, timeout = 30000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  try {
    const r = await fetch(API_BASE + path, { signal: ctrl.signal, cache: 'no-store', headers: { 'X-API-Key': (window.APP_API_KEY || '') } });
    if (!r.ok) throw new Error(`API error: ${r.status}`);
    return r.json();
  } catch (e) {
    if (e.name === 'AbortError') throw new Error('请求超时，请稍后重试');
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

function showPage(name) {
  $$('.page').forEach(p => p.classList.remove('active'));
  $$('.nav-item').forEach(n => n.classList.remove('active'));
  const page = $(`#page-${name}`);
  if (page) page.classList.add('active');
  const navItems = $$('.nav-item');
  const idx = { dashboard: 0, review: 1, trend: 2, position: 3, backtest: 4, realtime: 5, ipo: 6 }[name];
  if (idx !== undefined && navItems[idx]) navItems[idx].classList.add('active');
  if (name === 'dashboard' && !window._dashboardLoaded) loadDashboard();
  if (name === 'review') initReviewDates();
  if (name === 'trend' && !window._trendLoaded) loadTrend();
  if (name === 'position' && !window._positionLoaded) loadPosition();
  if (name === 'backtest' && !window._backtestLoaded) loadBacktest();
  if (name === 'realtime' && !window._realtimeLoaded) loadRealtime();
  if (name === 'ipo' && !window._ipoLoaded) loadIpoPage();
  if (name === 'wave' && !window._waveLoaded) loadWaveDbPage();
  if (name === 'sentiment_review' && !window._srLoaded) loadSentimentReview();
}

function fmt(v, d) { return v != null ? Number(v).toFixed(d !== undefined ? d : 1) : '-'; }
function pct(v) { return v != null ? (v >= 0 ? '+' : '') + Number(v).toFixed(1) + '%' : '-'; }
function signalClass(v) { return v >= 50 ? 'up' : 'down'; }
function badgeClass(v) {
  if (v >= 70) return 'badge-green';
  if (v >= 40) return 'badge-yellow';
  return 'badge-red';
}
