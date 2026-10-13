"""回测页面 — 独立 HTML 渲染（真实交易数据 + 规则展示）"""
from fastapi.responses import HTMLResponse



from utils import calc_range_stats as _calc_range_stats


_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>📈 真实交易回测 — 情绪流复盘</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0d1117;--card:#161b22;--border:#30363d;--text:#e6edf3;
  --muted:#8b949e;--blue:#58a6ff;--red:#ff5c6c;--green:#3fb950;
  --amber:#d29922;--purple:#bc8cff;
}
body{background:var(--bg);color:var(--text);font:-webkit-small-control 14px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;padding:0 0 60px}
a{color:var(--blue);text-decoration:none}
.container{max-width:1100px;margin:0 auto;padding:16px}

/* 顶栏 */
.top-bar{display:flex;align-items:center;gap:12px;padding:12px 16px;border-bottom:1px solid var(--border);background:var(--card);position:sticky;top:0;z-index:100}
.top-bar h1{font-size:16px;font-weight:700;flex:1}
.top-bar a{font-size:13px;padding:4px 12px;border-radius:6px;background:#21262d;border:1px solid var(--border)}
.top-bar a:hover{background:#30363d}

/* 统计卡片 */
.stats-row{display:flex;gap:8px;overflow-x:auto;padding:16px 0 8px;scrollbar-width:none}
.stats-row::-webkit-scrollbar{display:none}
.stat-card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:10px 14px;min-width:120px;flex-shrink:0}
.stat-card .val{font-size:18px;font-weight:700}
.stat-card .lbl{font-size:11px;color:var(--muted);margin-top:2px}

/* 日期选择 */
.date-bar{display:flex;gap:6px;flex-wrap:wrap;align-items:center;padding:8px 0}
.date-btn{background:var(--card);border:1px solid var(--border);border-radius:6px;padding:5px 12px;font-size:12px;color:var(--muted);cursor:pointer;transition:.15s}
.date-btn:hover{border-color:var(--blue);color:var(--blue)}
.date-btn.active{background:rgba(88,166,255,.12);border-color:var(--blue);color:var(--blue);font-weight:600}
.date-info{font-size:11px;color:var(--muted);margin-left:8px}

/* Tab 栏 */
.tabs{display:flex;gap:8px;padding:8px 0}
.tab{background:var(--card);border:1px solid var(--border);border-radius:6px;padding:6px 14px;font-size:13px;color:var(--muted);cursor:pointer;transition:.15s}
.tab:hover{border-color:var(--blue)}
.tab.active{background:rgba(88,166,255,.12);border-color:var(--blue);color:var(--blue);font-weight:600}

/* 规则面板 */
.rules-panel{background:linear-gradient(135deg,#1a1f2e,#0d1117);border:1px solid var(--border);border-radius:10px;margin:8px 0;overflow:hidden}
.rules-header{display:flex;align-items:center;gap:8px;padding:10px 14px;cursor:pointer;user-select:none}
.rules-header .badge{background:rgba(63,185,80,.15);color:var(--green);font-size:10px;padding:2px 6px;border-radius:4px;font-weight:600}
.rules-header .title{font-size:13px;font-weight:700;flex:1}
.rules-header .arrow{color:var(--muted);transition:.2s}
.rules-header .arrow.open{transform:rotate(180deg)}
.rules-body{padding:0 14px 14px;display:none}
.rules-body.open{display:block}
.rules-body hr{border:none;border-top:1px solid var(--border);margin:12px 0}
.section-title{font-size:12px;font-weight:700;color:var(--blue);margin-bottom:6px}
.rule-row{display:flex;gap:4px;padding:3px 0;font-size:11px;line-height:1.4}
.rule-row .dot{color:var(--blue);flex-shrink:0}
.rule-row .label{width:72px;color:var(--muted);flex-shrink:0;font-weight:500}
.rule-row .value{color:var(--text)}
.rule-note{background:rgba(88,166,255,.08);padding:8px;border-radius:6px;font-size:10px;color:var(--muted);line-height:1.4;margin-top:8px}
.rule-note.green{background:rgba(63,185,80,.08);color:var(--green)}

/* 图表 */
.chart-wrap{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px;margin:8px 0}
.chart-wrap canvas{width:100%!important;max-height:400px}
.legend{display:flex;justify-content:center;gap:24px;padding-top:8px;font-size:12px;color:var(--muted)}
.legend i{display:inline-block;width:16px;height:3px;border-radius:2px;vertical-align:middle;margin-right:6px}

/* 明细表格 */
.detail-list{display:flex;flex-direction:column;gap:6px;padding:8px 0}
.detail-card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:10px 14px;cursor:pointer;transition:.15s}
.detail-card:hover{border-color:var(--blue)}
.detail-top{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.detail-date{font-weight:700;font-size:13px;min-width:48px}
.signal-tag{font-size:11px;padding:2px 6px;border-radius:4px;font-weight:500}
.signal-tag.boil{background:rgba(255,92,108,.12);color:var(--red)}
.signal-tag.ice{background:rgba(107,125,179,.12);color:#6b7db3}
.signal-tag.rebound{background:rgba(88,166,255,.12);color:var(--blue)}
.signal-tag.default{background:rgba(139,148,158,.12);color:var(--muted)}
.regime-tag{font-size:10px;padding:1px 5px;border-radius:3px;background:rgba(88,166,255,.08);color:var(--blue)}
.pos-info{font-size:11px;color:var(--muted)}
.detail-ret{font-weight:700;font-size:13px;margin-left:auto}
.detail-nav{font-size:12px;color:var(--muted)}
.detail-bottom{display:flex;gap:6px;margin-top:6px;flex-wrap:wrap}
.mini-tag{font-size:10px;padding:1px 5px;border-radius:3px;font-weight:500}

/* 个股卡片 */
.stock-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:10px}
.stock-header{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.stock-date{font-weight:700;font-size:15px}
.stock-action{font-size:12px;padding:3px 8px;border-radius:6px;background:rgba(88,166,255,.12);color:var(--blue);font-weight:500}
.stock-regime{font-size:11px;padding:2px 6px;border-radius:4px;font-weight:500}
.stock-regime.exit{background:rgba(255,92,108,.1);color:var(--red)}
.stock-regime.hold{background:rgba(63,185,80,.1);color:var(--green)}
.stock-industry{font-size:11px;color:var(--muted);margin-left:auto}
.stock-section-title{font-weight:600;font-size:13px;margin:10px 0 6px}
.stock-empty{font-size:12px;color:var(--muted)}

/* 持仓行 */
.pos-row{display:flex;align-items:center;gap:8px;background:#161b22;border-radius:6px;padding:8px 10px;margin-bottom:4px;flex-wrap:wrap}
.pos-name{font-weight:600;font-size:13px;min-width:80px}
.pos-code{font-size:11px;color:var(--muted)}
.pos-entry{font-size:11px;color:var(--muted)}
.pos-mark{font-size:11px;font-weight:500}
.pos-pnl{font-size:12px;font-weight:700;padding:2px 6px;border-radius:4px}
.pos-pnl.up{background:rgba(255,92,108,.1);color:var(--red)}
.pos-pnl.down{background:rgba(63,185,80,.1);color:var(--green)}
.pos-alloc{font-size:11px;color:var(--blue);font-weight:500;margin-left:auto}
.pos-days{font-size:10px;color:var(--muted)}
.pos-sl-tp{font-size:10px;color:var(--muted);width:100%;padding-left:80px;margin-top:2px}

/* 交易行 */
.trade-row{display:flex;align-items:center;gap:8px;background:#161b22;border-radius:6px;padding:6px 10px;margin-bottom:3px;font-size:12px;flex-wrap:wrap}
.trade-name{min-width:80px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.trade-price{color:var(--muted);font-size:11px}
.trade-pct{font-weight:700;font-size:11px}
.trade-alloc{color:var(--blue);font-size:11px}
.trade-reason{color:var(--muted);font-size:10px;margin-left:auto}

/* 弹窗 */
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:200;justify-content:center;align-items:flex-end}
.modal-overlay.show{display:flex}
.modal{background:var(--card);border-radius:16px 16px 0 0;width:100%;max-width:600px;max-height:80vh;overflow-y:auto;padding:20px}
.modal .handle{width:36px;height:4px;background:var(--border);border-radius:2px;margin:0 auto 16px}
.modal h3{font-size:18px;font-weight:700;margin-bottom:16px}
.modal .metrics{display:flex;flex-wrap:wrap;gap:10px}
.modal .metric{background:rgba(88,166,255,.08);border-radius:6px;padding:8px 12px;text-align:center;min-width:80px}
.modal .metric .v{font-size:16px;font-weight:700}
.modal .metric .l{font-size:10px;color:var(--muted);margin-top:2px}
.modal .info-box{background:var(--bg);border-radius:8px;padding:10px;margin-top:12px;font-size:12px;line-height:1.4;color:var(--muted)}
.modal .close-btn{width:100%;padding:12px;background:transparent;border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:14px;cursor:pointer;margin-top:20px}
.modal .close-btn:hover{background:#21262d}

/* 自定义日期 */
.custom-date-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:200;justify-content:center;align-items:flex-end}
.custom-date-overlay.show{display:flex}
.custom-date-panel{background:var(--card);border-radius:16px 16px 0 0;width:100%;max-width:500px;padding:20px}
.custom-date-panel .handle{width:36px;height:4px;background:var(--border);border-radius:2px;margin:0 auto 16px}
.custom-date-panel h3{font-size:16px;font-weight:700;margin-bottom:4px}
.custom-date-panel .sub{font-size:12px;color:var(--muted);margin-bottom:16px}
.quick-quarters{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px}
.qbtn{background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:6px 12px;font-size:12px;color:var(--text);cursor:pointer}
.qbtn:hover{border-color:var(--blue)}
.date-inputs{display:flex;gap:12px;align-items:flex-end;margin-bottom:20px}
.date-inputs label{font-size:12px;color:var(--muted);display:block;margin-bottom:4px}
.date-inputs input{background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-size:14px;color:var(--text);width:100%}
.date-inputs .arrow{color:var(--muted);padding-bottom:8px}
.panel-btns{display:flex;gap:12px}
.panel-btns button{flex:1;padding:10px;border-radius:8px;font-size:14px;cursor:pointer;border:none}
.panel-btns .cancel{background:transparent;border:1px solid var(--border);color:var(--text)}
.panel-btns .apply{background:var(--blue);color:#fff;font-weight:600}

/* loading */
.loading{text-align:center;padding:60px;color:var(--muted)}
.loading .spinner{width:32px;height:32px;border:3px solid var(--border);border-top-color:var(--blue);border-radius:50%;animation:spin .8s linear infinite;margin:0 auto 12px}
@keyframes spin{to{transform:rotate(360deg)}}

/* 响应式 */
@media(max-width:600px){
  .stats-row{gap:6px}
  .stat-card{min-width:100px;padding:8px 10px}
  .stat-card .val{font-size:15px}
  .pos-row{gap:6px}
  .pos-sl-tp{padding-left:0}
}
</style>
</head>
<body>

<div class="top-bar">
  <h1>📈 真实交易回测</h1>
  <a href="/">← 主仪表盘</a>
  <a href="/intraday">📡 盘中</a>
  <a href="/watchlist">📋 自选</a>
</div>

<div class="container">
  <!-- 统计卡片 -->
  <div class="stats-row" id="stats-row"></div>

  <!-- 真实交易规则 -->
  <div class="rules-panel">
    <div class="rules-header" onclick="toggleRules()">
      <span class="badge">已启用</span>
      <span class="title">📋 真实交易规则</span>
      <span class="arrow" id="rules-arrow">▼</span>
    </div>
    <div class="rules-body" id="rules-body">
      <div class="section-title">💰 费用模型（已内嵌于净值计算）</div>
      <div class="rule-row"><span class="dot">•</span><span class="label">佣金</span><span class="value">万2.5（最低5元/笔），买卖双向收取</span></div>
      <div class="rule-row"><span class="dot">•</span><span class="label">印花税</span><span class="value">千0.5，仅卖出收取</span></div>
      <div class="rule-row"><span class="dot">•</span><span class="label">过户费</span><span class="value">十万分之一，买卖双向收取</span></div>
      <div class="rule-row"><span class="dot">•</span><span class="label">滑点</span><span class="value">0.1%（10bps），买入价上移 / 卖出价下移</span></div>
      <div class="rule-note">💡 以10万元交易为例：买入费用≈30元（佣金25+过户1+滑点100），卖出费用≈80元（佣金25+印花税50+过户1+滑点100），合计≈110元（0.11%）</div>

      <hr>
      <div class="section-title">📏 A股交易规则</div>
      <div class="rule-row"><span class="dot">•</span><span class="label">交易制度</span><span class="value">T+1（当日买入次日方可卖出）</span></div>
      <div class="rule-row"><span class="dot">•</span><span class="label">最小单位</span><span class="value">100股整数倍（1手），科创板200股起</span></div>
      <div class="rule-row"><span class="dot">•</span><span class="label">涨跌停</span><span class="value">主板±10%，创业板/科创板±20%，ST股±5%</span></div>
      <div class="rule-row"><span class="dot">•</span><span class="label">交易时段</span><span class="value">09:30-11:30、13:00-15:00（集合竞价除外）</span></div>
      <div class="rule-row"><span class="dot">•</span><span class="label">交割</span><span class="value">T+1交割，卖出资金T+1可取</span></div>

      <hr>
      <div class="section-title">🎯 入场策略规则</div>
      <div class="rule-row"><span class="dot">•</span><span class="label">冰点低吸</span><span class="value">情绪分&lt;30时入场，胜率41.4%，均盈+4.21%，贡献80%利润</span></div>
      <div class="rule-row"><span class="dot">•</span><span class="label">低迷+冰点</span><span class="value">最优组合，25%胜率，累计+111%，适当放大仓位</span></div>
      <div class="rule-row"><span class="dot">•</span><span class="label">3板身位分流</span><span class="value">胜率57.1%（样本少），可参与但控制仓位</span></div>
      <div class="rule-row"><span class="dot">•</span><span class="label">主升期追涨</span><span class="value">效率低（胜率16.5%），仅133笔赚55%</span></div>
      <div class="rule-row"><span class="dot">•</span><span class="label">赚钱效应50-70</span><span class="value">唯一亏损区间（-26%），应观望不入场</span></div>
      <div class="rule-row"><span class="dot">•</span><span class="label">下降期减仓</span><span class="value">累计-42%，应真正观望不操作</span></div>

      <hr>
      <div class="section-title">🛡️ 风控规则</div>
      <div class="rule-row"><span class="dot">•</span><span class="label">止损</span><span class="value">普通止损；冰点期强化止损至-3%（几乎盈亏平衡）</span></div>
      <div class="rule-row"><span class="dot">•</span><span class="label">止损距离</span><span class="value">4-6%区间全部亏损，应收紧至&lt;4%或放宽至&gt;6%</span></div>
      <div class="rule-row"><span class="dot">•</span><span class="label">止盈</span><span class="value">无止盈贡献+619%；固定止盈6%+全部亏损</span></div>
      <div class="rule-row"><span class="dot">•</span><span class="label">替代方案</span><span class="value">减少固定止盈，改用跟踪止损让利润奔跑</span></div>
      <div class="rule-row"><span class="dot">•</span><span class="label">持仓天数</span><span class="value">5天+长持效果最好（36%胜率+8.64%均盈）</span></div>
      <div class="rule-row"><span class="dot">•</span><span class="label">到期处理</span><span class="value">计划持仓到期未触发止损止盈则平仓</span></div>
      <div class="rule-row"><span class="dot">•</span><span class="label">空仓日</span><span class="value">position=0时强制清理所有残余持仓</span></div>

      <hr>
      <div class="section-title">📊 仓位管理</div>
      <div class="rule-row"><span class="dot">•</span><span class="label">平均仓位</span><span class="value">27.8%（轻仓为主，分散风险）</span></div>
      <div class="rule-row"><span class="dot">•</span><span class="label">冰点试探</span><span class="value">冰点期首次建仓，仓位较小</span></div>
      <div class="rule-row"><span class="dot">•</span><span class="label">加仓条件</span><span class="value">行情确认后逐步加仓</span></div>
      <div class="rule-row"><span class="dot">•</span><span class="label">regime止损</span><span class="value">态势恶化时动态收紧止损（adjust_factor）</span></div>

      <div class="rule-note green">📌 回测基于320个交易日、318笔完整交易验证（2025-01-02 ~ 2026-04-30），所有收益均为扣除全部交易成本后的净收益</div>
    </div>
  </div>

  <!-- 日期选择 -->
  <div class="date-bar" id="date-bar">
    <span class="date-btn active" data-range="20">最近20日</span>
    <span class="date-btn" data-range="60">最近60日</span>
    <span class="date-btn" data-range="90">近3月</span>
    <span class="date-btn" data-range="180">近半年</span>
    <span class="date-btn" data-range="all">全部</span>
    <span class="date-btn" data-range="custom">自定义</span>
    <span class="date-info" id="date-info"></span>
  </div>

  <!-- Tab -->
  <div class="tabs">
    <span class="tab active" data-tab="0">净值曲线</span>
    <span class="tab" data-tab="1">每日明细</span>
    <span class="tab" data-tab="2">个股持仓</span>
  </div>

  <!-- 内容区 -->
  <div id="tab-content">
    <div class="loading"><div class="spinner"></div>加载中...</div>
  </div>
</div>

<!-- 详情弹窗 -->
<div class="modal-overlay" id="detail-modal" onclick="if(event.target===this)closeModal()">
  <div class="modal" id="detail-modal-content"></div>
</div>

<!-- 自定义日期弹窗 -->
<div class="custom-date-overlay" id="custom-date-modal" onclick="if(event.target===this)closeCustomDate()">
  <div class="custom-date-panel">
    <div class="handle"></div>
    <h3>自定义回测区间</h3>
    <div class="sub" id="custom-date-range"></div>
    <div class="quick-quarters" id="quick-quarters"></div>
    <div class="date-inputs">
      <div style="flex:1"><label>起始日期</label><input id="inp-start" placeholder="YYYYMMDD" type="number"></div>
      <span class="arrow">→</span>
      <div style="flex:1"><label>结束日期</label><input id="inp-end" placeholder="留空=最新" type="number"></div>
    </div>
    <div class="panel-btns">
      <button class="cancel" onclick="closeCustomDate()">取消</button>
      <button class="apply" onclick="applyCustomDate()">应用</button>
    </div>
  </div>
</div>

<script>
let DATA=null, CHART=null, currentTab=0, currentRange=20;
let allDates=[], minDate='', maxDate='';

// ── 规则面板 ──
function toggleRules(){
  const body=document.getElementById('rules-body');
  const arrow=document.getElementById('rules-arrow');
  body.classList.toggle('open');
  arrow.classList.toggle('open');
}

// ── 加载数据 ──
async function loadBacktest(start,end){
  const el=document.getElementById('tab-content');
  el.innerHTML='<div class="loading"><div class="spinner"></div>加载中...</div>';
  try{
    let url='/api/backtest';
    const params=[];
    if(start) params.push('start='+start);
    if(end) params.push('end='+end);
    if(params.length) url+='?'+params.join('&');
    const r=await fetch(url);
    DATA=await r.json();
    renderStats();
    renderTab();
  }catch(e){
    el.innerHTML='<div class="loading" style="color:var(--red)">加载失败: '+e.message+'</div>';
  }
}

// ── 统计卡片 ──
function renderStats(){
  const s=DATA.stats||{};
  const totalRet=s.total_ret||0;
  const benchRet=s.bench_ret||0;
  const maxDd=s.max_dd||0;
  const excess=totalRet-benchRet;
  const days=s.days||0;
  const items=[
    {v:(totalRet>=0?'+':'')+totalRet.toFixed(2)+'%', l:'区间收益', c:totalRet>=0?'var(--red)':'var(--green)'},
    {v:'-'+maxDd.toFixed(2)+'%', l:'最大回撤', c:'var(--green)'},
    {v:(excess>=0?'+':'')+excess.toFixed(2)+'%', l:'超额收益', c:excess>=0?'var(--red)':'var(--green)'},
    {v:(benchRet>=0?'+':'')+benchRet.toFixed(2)+'%', l:'基准', c:benchRet>=0?'var(--red)':'var(--green)'},
    {v:days+'', l:'交易天数', c:'var(--blue)'},
  ];
  document.getElementById('stats-row').innerHTML=items.map(i=>
    '<div class="stat-card"><div class="val" style="color:'+i.c+'">'+i.v+'</div><div class="lbl">'+i.l+'</div></div>'
  ).join('');
}

// ── Tab 渲染 ──
function renderTab(){
  if(currentTab===0) renderEquity();
  else if(currentTab===1) renderDetails();
  else renderStockDetails();
}

// ── 净值曲线 ──
function renderEquity(){
  const el=document.getElementById('tab-content');
  el.innerHTML='<div class="chart-wrap"><canvas id="equity-chart"></canvas><div class="legend"><span><i style="background:var(--blue)"></i>策略净值</span><span><i style="background:var(--muted)"></i>基准（全A等权）</span></div></div>';
  const ctx=document.getElementById('equity-chart').getContext('2d');
  const labels=DATA.labels||[];
  const equity=DATA.equity||[];
  const benchmark=DATA.benchmark||[];
  if(CHART) CHART.destroy();
  CHART=new Chart(ctx,{
    type:'line',
    data:{
      labels,
      datasets:[
        {label:'策略',data:equity,borderColor:'#58a6ff',backgroundColor:'rgba(88,166,255,.08)',fill:true,borderWidth:2.5,pointRadius:0,tension:.3},
        {label:'基准',data:benchmark,borderColor:'#8b949e',borderDash:[4,4],borderWidth:1.5,pointRadius:0,tension:.3,fill:false},
      ]
    },
    options:{
      responsive:true,maintainAspectRatio:false,
      interaction:{mode:'index',intersect:false},
      plugins:{legend:{display:false},tooltip:{backgroundColor:'#161b22',borderColor:'#30363d',borderWidth:1,titleColor:'#e6edf3',bodyColor:'#8b949e',padding:10,cornerRadius:8}},
      scales:{
        x:{ticks:{color:'#8b949e',font:{size:10},maxTicksLimit:8},grid:{color:'rgba(48,54,61,.5)'}},
        y:{ticks:{color:'#8b949e',font:{size:10},callback:v=>v.toFixed(2)},grid:{color:'rgba(48,54,61,.5)'}},
      }
    }
  });
}

// ── 每日明细 ──
function renderDetails(){
  const el=document.getElementById('tab-content');
  const details=(DATA.details||[]).slice().reverse();
  if(!details.length){el.innerHTML='<div class="loading">无明细数据</div>';return;}
  el.innerHTML='<div class="detail-list">'+details.map(d=>{
    const ret=d.daily_ret||0;
    const retColor=ret>=0?'var(--red)':'var(--green)';
    const cls=d.signal_cls||'default';
    const regime=d.regime||'';
    const sentiment=d.sentiment||0;
    const profit=d.profit||0;
    const pos=d.position||0;
    const strat=d.strategy||'';
    return '<div class="detail-card" onclick=\'showDetail('+JSON.stringify(d).replace(/'/g,"&#39;")+' )\'>'
      +'<div class="detail-top">'
      +'<span class="detail-date">'+(d.display||d.date)+'</span>'
      +'<span class="signal-tag '+cls+'">'+(d.signal||'')+'</span>'
      +(regime?'<span class="regime-tag">'+regime+'</span>':'')
      +(d.open_count?'<span class="pos-info">持'+d.open_count+'</span>':'')
      +(d.closed_count?'<span class="pos-info">平'+d.closed_count+'</span>':'')
      +'<span class="detail-ret" style="color:'+retColor+'">'+(ret>=0?'+':'')+ret.toFixed(2)+'%</span>'
      +'<span class="detail-nav">'+((d.nav||0).toFixed(2))+'</span>'
      +'</div>'
      +(strat||sentiment||profit?'<div class="detail-bottom">'
        +'<span class="mini-tag" style="background:rgba('+(sentiment<30?'107,125,179':'139,148,158')+',.12);color:'+(sentiment<30?'#6b7db3':'var(--muted)')+'">情绪'+sentiment+'</span>'
        +'<span class="mini-tag" style="background:rgba('+(profit<30?'107,125,179':profit>70?'255,92,108':'139,148,158')+',.12);color:'+(profit<30?'#6b7db3':profit>70?'var(--red)':'var(--muted)')+'">赚钱'+profit+'</span>'
        +'<span class="mini-tag" style="background:rgba(88,166,255,.08);color:var(--blue)">仓位'+pos+'%</span>'
        +'</div>':'')
      +'</div>';
  }).join('')}</div>';
}

// ── 详情弹窗 ──
function showDetail(d){
  const modal=document.getElementById('detail-modal');
  const content=document.getElementById('detail-modal-content');
  const ret=d.daily_ret||0;
  const retColor=ret>=0?'var(--red)':'var(--green)';
  const sentiment=d.sentiment||0;
  const profit=d.profit||0;
  const composite=d.composite||0;
  const pos=d.position||0;
  const zt=d.zt||0;
  const dt=d.dt||0;
  const regime=d.regime||'';
  const regimeAction=d.regime_action||'';
  const regimeReason=d.regime_reason||'';
  const strategy=d.strategy||'';

  let html='<div class="handle"></div>';
  html+='<div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">';
  html+='<span style="font-size:18px;font-weight:700">'+(d.display||d.date)+'</span>';
  html+='<span class="signal-tag '+(d.signal_cls||'default')+'" style="font-size:13px">'+(d.signal||'')+'</span>';
  html+='<span style="font-size:18px;font-weight:700;margin-left:auto;color:'+retColor+'">'+(ret>=0?'+':'')+ret.toFixed(2)+'%</span>';
  html+='</div>';

  html+='<div class="metrics">';
  html+='<div class="metric"><div class="v" style="color:'+sentimentColor(sentiment)+'">'+sentiment+'</div><div class="l">情绪分</div></div>';
  html+='<div class="metric"><div class="v" style="color:'+profitColor(profit)+'">'+profit+'</div><div class="l">赚钱效应</div></div>';
  html+='<div class="metric"><div class="v" style="color:var(--blue)">'+composite+'</div><div class="l">综合分</div></div>';
  html+='<div class="metric"><div class="v" style="color:var(--blue)">'+pos+'%</div><div class="l">建议仓位</div></div>';
  html+='<div class="metric"><div class="v" style="color:var(--red)">'+zt+'</div><div class="l">涨停</div></div>';
  html+='<div class="metric"><div class="v" style="color:var(--green)">'+dt+'</div><div class="l">跌停</div></div>';
  html+='<div class="metric"><div class="v" style="color:var(--muted)">'+(d.open_count||0)+'</div><div class="l">持仓</div></div>';
  html+='<div class="metric"><div class="v" style="color:var(--muted)">'+((d.nav||0).toFixed(2))+'</div><div class="l">净值</div></div>';
  html+='</div>';

  if(regime){
    html+='<div class="info-box">';
    html+='<div style="margin-bottom:4px"><b>行情体制:</b> '+regime;
    if(regimeAction) html+=' <span style="color:'+(regimeAction.includes('exit')?'var(--red)':'var(--green)')+';margin-left:8px">'+regimeAction+'</span>';
    html+='</div>';
    if(regimeReason) html+='<div style="color:var(--muted)">'+regimeReason+'</div>';
    html+='</div>';
  }

  if(strategy){
    html+='<div class="info-box"><div style="margin-bottom:4px;color:var(--muted)">策略</div>'+strategy+'</div>';
  }

  html+='<button class="close-btn" onclick="closeModal()">关闭</button>';
  content.innerHTML=html;
  modal.classList.add('show');
}

function closeModal(){document.getElementById('detail-modal').classList.remove('show');}

function sentimentColor(v){return v<30?'#6b7db3':v<50?'var(--blue)':v<70?'var(--muted)':'var(--red)';}
function profitColor(v){return v<30?'#6b7db3':v<50?'var(--blue)':'var(--red)';}

// ── 个股持仓 ──
function renderStockDetails(){
  const el=document.getElementById('tab-content');
  const list=(DATA.stock_details||[]).slice().reverse();
  if(!list.length){el.innerHTML='<div class="loading">无个股持仓数据</div>';return;}
  el.innerHTML='<div style="padding:8px 0">'+list.map(d=>{
    const action=d.action||'';
    const regimeAction=d.regime_action||'';
    const regimeReason=d.regime_reason||'';
    const summary=d.summary||'';
    const opens=d.open_positions||[];
    const closed=(d.closed_today||[]).filter(c=>c.exit);
    const newT=d.new_trades||[];
    const industry=(d.industry_top3||[]).join(' / ');

    let h='<div class="stock-card">';
    h+='<div class="stock-header">';
    h+='<span class="stock-date">'+(d.display||d.date)+'</span>';
    if(action) h+='<span class="stock-action">'+action+'</span>';
    if(regimeAction) h+='<span class="stock-regime '+(regimeAction.includes('exit')?'exit':'hold')+'">'+regimeAction+'</span>';
    if(industry) h+='<span class="stock-industry">'+industry+'</span>';
    h+='</div>';

    if(regimeReason) h+='<div style="margin:6px 0;padding:6px 8px;background:#161b22;border-radius:6px;font-size:11px;color:var(--muted)">📊 '+regimeReason+'</div>';
    if(summary) h+='<div style="margin:6px 0;font-size:12px;color:var(--muted)">'+summary+'</div>';

    if(opens.length){
      h+='<div class="stock-section-title">📋 当前持仓 <span style="color:var(--muted);font-weight:normal;font-size:11px">'+opens.length+'只</span></div>';
      h+=opens.map(p=>{
        const pnl=p.unreal_pct||0;
        const pnlCls=pnl>=0?'up':'down';
        let r='<div class="pos-row">';
        r+='<div><div class="pos-name">'+p.name+'</div><div class="pos-code">'+p.code+'</div></div>';
        r+='<div><div class="pos-entry">入 '+(p.entry||0).toFixed(2)+'</div><div class="pos-mark" style="color:'+(pnl>=0?'var(--red)':'var(--green)')+'">现 '+(p.mark||0).toFixed(2)+'</div></div>';
        r+='<span class="pos-pnl '+pnlCls+'">'+(pnl>=0?'+':'')+pnl.toFixed(1)+'%</span>';
        r+='<span class="pos-alloc">'+(p.alloc||0)+'%</span>';
        r+='<span class="pos-days">'+(p.held_days||0)+'d/'+(p.max_days||0)+'d</span>';
        if(p.stop_loss||p.take_profit){
          r+='<div class="pos-sl-tp">';
          if(p.stop_loss) r+='止损 '+(p.stop_loss).toFixed(2)+' ';
          if(p.take_profit) r+='止盈 '+(p.take_profit).toFixed(2);
          r+='</div>';
        }
        r+='</div>';
        return r;
      }).join('');
    }

    if(newT.length){
      h+='<div class="stock-section-title">🆕 今日建仓</div>';
      h+=newT.map(t=>tradeRow(t,true)).join('');
    }
    if(closed.length){
      h+='<div class="stock-section-title">🔴 今日平仓</div>';
      h+=closed.map(t=>tradeRow(t,false)).join('');
    }

    h+='</div>';
    return h;
  }).join('')}</div>';
}

function tradeRow(t,isNew){
  const pct=t.pct||0;
  const pctColor=pct>=0?'var(--red)':'var(--green)';
  let r='<div class="trade-row">';
  r+='<span class="trade-name">'+(t.name||t.code||'')+' '+(t.code||'')+'</span>';
  if(t.price) r+='<span class="trade-price">¥'+(t.price).toFixed(2)+'</span>';
  if(pct) r+='<span class="trade-pct" style="color:'+pctColor+'">'+(pct>=0?'+':'')+pct.toFixed(1)+'%</span>';
  if(t.alloc) r+='<span class="trade-alloc">'+t.alloc+'%</span>';
  const reason=t.reason||t.type||'';
  if(reason) r+='<span class="trade-reason">'+(reason.length>14?reason.slice(0,14)+'…':reason)+'</span>';
  r+='</div>';
  return r;
}

// ── 日期选择 ──
document.getElementById('date-bar').addEventListener('click',e=>{
  const btn=e.target.closest('.date-btn');
  if(!btn) return;
  const range=btn.dataset.range;
  document.querySelectorAll('.date-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  if(range==='custom'){showCustomDate();return;}
  currentRange=parseInt(range)||'all';
  applyRange();
});

function applyRange(){
  if(!allDates.length) return;
  const max=allDates[allDates.length-1];
  let start=null;
  if(currentRange==='all'){start=null;}
  else if(typeof currentRange==='number'){
    const idx=allDates.indexOf(max);
    const ti=Math.max(0,idx-currentRange);
    start=allDates[ti];
  }
  document.getElementById('date-info').textContent=
    start?(start+' → '+max):('全部数据 '+minDate+' → '+max);
  loadBacktest(start,null);
}

// ── 自定义日期 ──
function showCustomDate(){
  const modal=document.getElementById('custom-date-modal');
  document.getElementById('custom-date-range').textContent='数据范围: '+minDate+' ~ '+maxDate;
  // 快捷季度
  const max=maxDate;
  if(max){
    const y=parseInt(max.substring(0,4)),m=parseInt(max.substring(4,6));
    const quarters=[];
    for(let q=0;q<6;q++){
      const mi=m-q*3;
      const yy=y+Math.floor((mi-1)/12);
      const mmi=((mi-1)%12)+1;
      const qn=Math.floor((mmi-1)/3)+1;
      const qs=yy+String((qn-1)*3+1).padStart(2,'0')+'01';
      quarters.push({label:yy+'年Q'+qn,start:qs});
    }
    document.getElementById('quick-quarters').innerHTML=quarters.map(q=>
      '<span class="qbtn" onclick="document.getElementById(\'inp-start\').value=\''+q.start+'\';document.getElementById(\'inp-end\').value=\'\'">'+q.label+'</span>'
    ).join('');
  }
  modal.classList.add('show');
}
function closeCustomDate(){document.getElementById('custom-date-modal').classList.remove('show');}
function applyCustomDate(){
  const s=document.getElementById('inp-start').value.trim();
  const e=document.getElementById('inp-end').value.trim();
  closeCustomDate();
  document.querySelectorAll('.date-btn').forEach(b=>b.classList.remove('active'));
  document.querySelector('[data-range="custom"]').classList.add('active');
  document.getElementById('date-info').textContent=(s||minDate)+' → '+(e||maxDate);
  loadBacktest(s||null,e||null);
}

// ── Tab 切换 ──
document.querySelector('.tabs').addEventListener('click',e=>{
  const tab=e.target.closest('.tab');
  if(!tab) return;
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  tab.classList.add('active');
  currentTab=parseInt(tab.dataset.tab);
  renderTab();
});

// ── 初始化 ──
async function init(){
  try{
    const r=await fetch('/api/dates');
    const dates=await r.json();
    allDates=dates.map(d=>(d.date||'').replace(/\//g,'')).filter(s=>s.length===8).sort();
    if(allDates.length){minDate=allDates[0];maxDate=allDates[allDates.length-1];}
  }catch(_){}
  applyRange();
}
init();
</script>
</body>
</html>"""


def register_backtest_page_routes(app):

    @app.get('/backtest', response_class=HTMLResponse)
    async def backtest_page():
        return HTMLResponse(
            content=_HTML,
            headers={
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
            },
        )
