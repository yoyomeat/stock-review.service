/**
 * K线图表模块 — 波浪分析可视化 v5
 * 完善悬停tooltip，确保时间轴显示
 */

const klineState = {
  currentCode: null,
  currentPeriod: 'daily',
  chart: null,
  candleSeries: null,
  volumeSeries: null,
  searchTimer: null,
  waveLines: [],
  priceLines: [],
  latestClose: null,
};

// 周期 → 波浪级别映射
const PERIOD_WAVE_LEVEL = {
  'daily': 'daily',
  'weekly': 'weekly',
  'monthly': 'monthly',
};

// 级别配置
const LEVEL_CONFIG = {
  'monthly': { color: '#ff9800', width: 3, name: '循环浪(月线)' },
  'weekly':  { color: '#2196f3', width: 2, name: '大浪(周线)' },
  'daily':   { color: '#4caf50', width: 1, name: '中浪(日线)' },
};

// ── 页面初始化 ──
async function loadKlinePage() {
  window._klineLoaded = true;

  const cats = await klineApi('/api/kline/categories');
  const catBar = $('#kline-cat-bar');
  if (catBar && cats.length) {
    catBar.innerHTML = `<button class="kline-cat-btn active" data-cat="" onclick="klineFilterCat('')">全部</button>` +
      cats.map(c => `<button class="kline-cat-btn" data-cat="${c.category}" onclick="klineFilterCat('${c.category}')">${_catLabel(c.category)} (${c.cnt})</button>`).join('');
  }

  klineLoadCode('sh000001');
}

function _catLabel(cat) {
  return { index: '指数', concept: '概念', industry: '行业', theme: '主题' }[cat] || cat;
}

// ── 搜索 ──
function klineSearchInput(val) {
  clearTimeout(klineState.searchTimer);
  klineState.searchTimer = setTimeout(() => klineDoSearch(val), 200);
}

async function klineDoSearch(q) {
  const dropdown = $('#kline-search-dropdown');
  if (!q || q.length < 1) {
    dropdown.style.display = 'none';
    return;
  }
  try {
    const results = await klineApi(`/api/kline/search?q=${encodeURIComponent(q)}&limit=30`);
    if (!results.length) {
      dropdown.innerHTML = '<div class="kline-dropdown-empty">无匹配结果</div>';
      dropdown.style.display = 'block';
      return;
    }
    dropdown.innerHTML = results.map(r =>
      `<div class="kline-dropdown-item" onclick="klineLoadCode('${r.code}')">
        <span class="kline-dd-code">${r.code}</span>
        <span class="kline-dd-name">${r.name || ''}</span>
        <span class="kline-dd-cat">${_catLabel(r.category)}</span>
      </div>`
    ).join('');
    dropdown.style.display = 'block';
  } catch (e) {
    dropdown.style.display = 'none';
  }
}

// ── 分类筛选 ──
let _currentCat = '';
function klineFilterCat(cat) {
  _currentCat = cat;
  $$('.kline-cat-btn').forEach(b => b.classList.toggle('active', b.dataset.cat === cat));
  const q = $('#kline-search-input')?.value || '';
  klineDoSearch(q || (cat ? ' ' : ''));
}

// ── 加载K线 ──
async function klineLoadCode(code) {
  klineState.currentCode = code;
  $('#kline-search-dropdown').style.display = 'none';
  $('#kline-search-input').value = '';

  const container = $('#kline-chart-container');
  container.innerHTML = '<div class="kline-loading">加载中...</div>';

  try {
    const limitMap = { 'daily': 1000, 'weekly': 2000, 'monthly': 2000 };
    const limit = limitMap[klineState.currentPeriod] || 1000;
    const data = await klineApi(`/api/kline/data?code=${code}&period=${klineState.currentPeriod}&limit=${limit}`);
    renderKlineChart(data);
    loadWaveAnnotations(code);
  } catch (e) {
    container.innerHTML = `<div class="kline-error">加载失败: ${e.message}</div>`;
  }
}

// ── 加载波浪分析标注 ──
async function loadWaveAnnotations(code) {
  try {
    const [zigzag, waveLabels, waveCounts] = await Promise.all([
      klineApi(`/api/kline/zigzag?code=${code}`),
      klineApi(`/api/kline/wave_labels?code=${code}`),
      klineApi(`/api/kline/wave_counts?code=${code}`),
    ]);
    renderWaveAnnotations(zigzag, waveLabels, waveCounts);
    renderWaveSummary(waveCounts);
  } catch (e) {
    console.warn('加载波浪标注失败:', e);
  }
}

// ── 渲染波浪标注 ──
function renderWaveAnnotations(zigzagPoints, waveLabels, waveCounts) {
  try {
    const chart = klineState.chart;
    if (!chart) return;

    klineState.waveLines.forEach(line => { try { chart.removeSeries(line); } catch(e){} });
    klineState.priceLines.forEach(line => { try { klineState.candleSeries.removePriceLine(line); } catch(e){} });
    klineState.waveLines = [];
    klineState.candleSeries.setMarkers([]);

    const currentLevel = PERIOD_WAVE_LEVEL[klineState.currentPeriod];
    const cfg = LEVEL_CONFIG[currentLevel] || LEVEL_CONFIG['daily'];

    const levelLabels = waveLabels.filter(w => w.level === currentLevel);
    
    if (levelLabels.length > 0) {
      const markers = [];
      
      levelLabels.forEach(label => {
        try {
          if (!label.start_date || !label.start_price) return;
          
          const isActive = label.status === 'active';
          const endDate = label.end_date || '20260915';
          const endPrice = label.end_price || klineState.latestClose || label.start_price;

          const lineData = [
            { time: _fmtDate(label.start_date), value: label.start_price },
            { time: _fmtDate(endDate), value: endPrice },
          ];

          const isUpWave = endPrice > label.start_price;
          
          const line = chart.addLineSeries({
            color: cfg.color,
            lineWidth: cfg.width,
            lineStyle: isActive ? LightweightCharts.LineStyle.Dashed : LightweightCharts.LineStyle.Solid,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
          });
          line.setData(lineData);
          klineState.waveLines.push(line);

          markers.push({
            time: _fmtDate(label.start_date),
            position: isUpWave ? 'belowBar' : 'aboveBar',
            color: cfg.color,
            shape: isUpWave ? 'arrowUp' : 'arrowDown',
            text: label.wave_name,
            size: 2,
          });
        } catch (e) {
          console.warn('波浪标注失败:', label.wave_name, e);
        }
      });

      if (markers.length > 0) {
        klineState.candleSeries.setMarkers(markers);
      }
    }

    // Zigzag拐点
    if (zigzagPoints && zigzagPoints.length > 0) {
      const thresholdMap = { 'daily': '5.0', 'weekly': '8.0', 'monthly': '10.0' };
      const targetTh = thresholdMap[klineState.currentPeriod] || '5.0';
      
      const pts = zigzagPoints.filter(p => String(p.threshold) === targetTh);
      if (pts.length >= 2) {
        const seen = new Set();
        const zigzagData = [];
        pts.forEach(p => {
          const t = _fmtDate(p.trade_date);
          if (seen.has(t)) return;
          seen.add(t);
          zigzagData.push({ time: t, value: p.price });
        });
        
        if (zigzagData.length >= 2) {
          const zigzagLine = chart.addLineSeries({
            color: '#ff9800',
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dotted,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
          });
          zigzagLine.setData(zigzagData);
          klineState.waveLines.push(zigzagLine);
        }
      }
    }

    // 失效条件水平线
    if (waveCounts && waveCounts.length > 0) {
      const periodDegreeMap = { 'daily': 'minor', 'weekly': 'intermediate', 'monthly': 'primary' };
      const targetDegree = periodDegreeMap[klineState.currentPeriod] || 'minor';
      
      const activeCounts = waveCounts.filter(c => c.degree === targetDegree);
      
      activeCounts.forEach(count => {
        try {
          if (!count.invalidation_price) return;
          const priceLine = klineState.candleSeries.createPriceLine({
            price: count.invalidation_price,
            color: '#f44336',
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            axisLabelVisible: true,
            title: `失效: ${count.current_wave}浪`,
          });
          klineState.priceLines.push(priceLine);
        } catch (e) {
          console.warn('失效线失败:', count, e);
        }
      });
    }

    renderWaveLegend(currentLevel);

  } catch (e) {
    console.error('渲染波浪标注失败:', e);
  }
}

// ── 浪型总结 ──
function renderWaveSummary(waveCounts) {
  let summaryEl = document.getElementById('kline-wave-summary');
  if (!summaryEl) {
    summaryEl = document.createElement('div');
    summaryEl.id = 'kline-wave-summary';
    summaryEl.style.cssText = 'margin:8px 0;padding:10px 14px;background:#f8f9fa;border-radius:6px;font-size:13px;line-height:1.6';
    const titleEl = document.getElementById('kline-chart-title');
    titleEl.parentNode.insertBefore(summaryEl, titleEl.nextSibling);
  }

  if (!waveCounts || waveCounts.length === 0) {
    summaryEl.innerHTML = '<span style="color:#999">无活跃波浪计数</span>';
    return;
  }

  let html = '<div style="font-weight:600;margin-bottom:6px">当前浪型结构：</div>';
  
  const degreeOrder = { 'primary': 0, 'intermediate': 1, 'minor': 2 };
  const sorted = [...waveCounts].sort((a, b) => (degreeOrder[a.degree] || 9) - (degreeOrder[b.degree] || 9));

  sorted.forEach(count => {
    const degreeName = { 'primary': '月线/循环浪', 'intermediate': '周线/大浪', 'minor': '日线/中浪' }[count.degree] || count.degree;
    const confidence = (count.confidence * 100).toFixed(0);
    
    html += `<div style="margin-bottom:4px">
      <span style="color:#333;font-weight:500">${degreeName}：</span>
      <span style="color:#666">${count.current_wave}浪中</span>
      <span style="color:#999;font-size:11px;margin-left:8px">置信度${confidence}%</span>
    </div>`;
    if (count.note) {
      html += `<div style="color:#888;font-size:12px;margin-left:8px;margin-bottom:6px">${count.note}</div>`;
    }
  });

  summaryEl.innerHTML = html;
}

// ── 波浪图例 ──
function renderWaveLegend(currentLevel) {
  let legend = document.getElementById('kline-legend');
  if (!legend) {
    legend = document.createElement('div');
    legend.id = 'kline-legend';
    legend.style.cssText = 'position:absolute;top:10px;left:10px;background:rgba(255,255,255,0.92);padding:8px 12px;border-radius:6px;font-size:11px;z-index:10;box-shadow:0 2px 8px rgba(0,0,0,0.1)';
    const container = document.getElementById('kline-chart-container');
    container.style.position = 'relative';
    container.appendChild(legend);
  }

  const cfg = LEVEL_CONFIG[currentLevel] || LEVEL_CONFIG['daily'];
  legend.innerHTML = `
    <div style="margin-bottom:4px">
      <span style="display:inline-block;width:20px;height:2px;background:${cfg.color};vertical-align:middle;margin-right:4px"></span>
      ${cfg.name}
    </div>
    <div style="margin-bottom:2px">
      <span style="color:${cfg.color};font-weight:bold">↑</span> 上升浪（起点在K线下方）
    </div>
    <div style="margin-bottom:2px">
      <span style="color:${cfg.color};font-weight:bold">↓</span> 下降浪（起点在K线上方）
    </div>
  `;
}

// ── 切换周期 ──
function klineSetPeriod(period) {
  klineState.currentPeriod = period;
  $$('.kline-period-btn').forEach(b => b.classList.toggle('active', b.dataset.period === period));
  if (klineState.currentCode) {
    klineLoadCode(klineState.currentCode);
  }
}

// ── 渲染K线图 ──
function renderKlineChart(data) {
  const container = $('#kline-chart-container');
  if (!data.bars || !data.bars.length) {
    container.innerHTML = '<div class="kline-error">无数据</div>';
    return;
  }

  const title = `${data.name} (${data.code})`;
  $('#kline-chart-title').textContent = title;

  container.innerHTML = '';

  const chart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: 550,
    layout: {
      background: { type: 'solid', color: '#ffffff' },
      textColor: '#333',
    },
    grid: {
      vertLines: { color: '#f0f0f0' },
      horzLines: { color: '#f0f0f0' },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
      vertLine: {
        color: 'rgba(0, 0, 0, 0.5)',
        labelBackgroundColor: '#2962ff',
      },
      horzLine: {
        color: 'rgba(0, 0, 0, 0.5)',
        labelBackgroundColor: '#2962ff',
      },
    },
    rightPriceScale: { borderColor: '#e0e0e0' },
    timeScale: {
      borderColor: '#e0e0e0',
      visible: true,
      timeVisible: false,
      rightOffset: 5,
      barSpacing: 10,
    },
  });

  const candleSeries = chart.addCandlestickSeries({
    upColor: '#ef5350',
    downColor: '#26a69a',
    borderUpColor: '#ef5350',
    borderDownColor: '#26a69a',
    wickUpColor: '#ef5350',
    wickDownColor: '#26a69a',
  });

  const candles = data.bars.map(b => ({
    time: _fmtDate(b.time),
    open: b.open,
    high: b.high,
    low: b.low,
    close: b.close,
  })).filter(b => b.open && b.high && b.low && b.close);

  candleSeries.setData(candles);

  klineState.latestClose = candles[candles.length - 1].close;

  _addMA(chart, candles, 5, '#ff9800');
  _addMA(chart, candles, 20, '#2196f3');
  _addMA(chart, candles, 60, '#9c27b0');

  const volumeSeries = chart.addHistogramSeries({
    color: '#26a69a',
    priceFormat: { type: 'volume' },
    priceScaleId: 'vol',
  });
  chart.priceScale('vol').applyOptions({
    scaleMargins: { top: 0.88, bottom: 0 },
  });

  const volumes = data.bars.map(b => ({
    time: _fmtDate(b.time),
    value: b.volume || 0,
    color: (b.close >= b.open) ? 'rgba(239,83,80,0.5)' : 'rgba(38,166,154,0.5)',
  })).filter(b => b.value > 0);
  volumeSeries.setData(volumes);

  chart.timeScale().fitContent();

  // 自定义悬停信息框
  const tooltipEl = document.createElement('div');
  tooltipEl.style.cssText = 'position:absolute;display:none;z-index:50;padding:8px 12px;background:rgba(255,255,255,0.95);border:1px solid #ddd;border-radius:4px;font-size:12px;box-shadow:0 2px 8px rgba(0,0,0,0.15);pointer-events:none';
  container.appendChild(tooltipEl);

  chart.subscribeCrosshairMove(function(param) {
    if (!param.time || param.point.x < 0 || param.point.x > container.clientWidth || param.point.y < 0 || param.point.y > container.clientHeight) {
      tooltipEl.style.display = 'none';
      return;
    }

    const candleData = param.seriesData.get(candleSeries);
    if (!candleData) {
      tooltipEl.style.display = 'none';
      return;
    }

    const volData = param.seriesData.get(volumeSeries);
    const dateStr = param.time;
    const volStr = volData ? (volData.value / 100000000).toFixed(2) + '亿' : '-';

    tooltipEl.innerHTML = `
      <div style="font-weight:600;margin-bottom:4px">${dateStr}</div>
      <div>开: ${candleData.open.toFixed(2)}</div>
      <div>高: ${candleData.high.toFixed(2)}</div>
      <div>低: ${candleData.low.toFixed(2)}</div>
      <div>收: ${candleData.close.toFixed(2)}</div>
      <div style="margin-top:4px;color:#666">量: ${volStr}</div>
    `;

    const x = Math.min(param.point.x + 15, container.clientWidth - 150);
    const y = Math.max(param.point.y - 10, 10);
    tooltipEl.style.left = x + 'px';
    tooltipEl.style.top = y + 'px';
    tooltipEl.style.display = 'block';
  });

  const resizeObserver = new ResizeObserver(() => {
    chart.applyOptions({ width: container.clientWidth });
  });
  resizeObserver.observe(container);

  klineState.chart = chart;
  klineState.candleSeries = candleSeries;
  klineState.volumeSeries = volumeSeries;
}

// ── MA 均线 ──
function _addMA(chart, data, period, color) {
  const maData = [];
  for (let i = period - 1; i < data.length; i++) {
    let sum = 0;
    for (let j = 0; j < period; j++) {
      sum += data[i - j].close;
    }
    maData.push({ time: data[i].time, value: sum / period });
  }
  const line = chart.addLineSeries({
    color: color,
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerVisible: false,
  });
  line.setData(maData);
}

// ── 日期格式化 ──
function _fmtDate(d) {
  if (!d) return '';
  if (d.length === 8) return d.slice(0, 4) + '-' + d.slice(4, 6) + '-' + d.slice(6, 8);
  return d;
}

// ── API helper ──
async function klineApi(path) {
  const r = await fetch(API_BASE + path);
  if (!r.ok) throw new Error(`API error: ${r.status}`);
  return r.json();
}
