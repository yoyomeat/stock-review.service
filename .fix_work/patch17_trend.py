# -*- coding: utf-8 -*-
"""patch17: 趋势动量模块修复
F1 tmLoadOverview 未定义（initTrendMomentum 末尾 ReferenceError → 大盘环境/默认tab 空白）
F2 INDEX_LIST 缺深证成指 sz399001（DB/波浪模块/注释均为四指数）
F3 trend_sector_scores / trend_stock_picks 每日缓存无新鲜度校验（cron失败则长期喂昨日数据）
F4 突破信号卡片"距高点"错用 total_gain（累计涨幅）→ 拆分为两个字段
F5 calc_trend_score near_high 历史序列窗口不含当日 vs 当前值含当日 + clip 不一致
F6 get_all_index_scores 对 calc_trend_score 返回 None 无守卫
"""
import pathlib, sys

ROOT = pathlib.Path('/opt/stock-review')

def edit(relpath, pairs):
    p = ROOT / relpath
    s = p.read_text(encoding='utf-8')
    for old, new in pairs:
        n = s.count(old)
        if n != 1:
            print('!! [%s] expect 1, got %d: %r' % (relpath, n, old[:70]))
            sys.exit(1)
        s = s.replace(old, new)
        print('ok [%s] %r' % (relpath, old[:55]))
    p.write_text(s, encoding='utf-8')

# ══ 后端 trend_score.py ══
edit('quant/trend_score.py', [
    # F2: 补深证成指（波浪模块四指数口径）
    ('''INDEX_LIST = [
    {"code": "sh000001", "name": "上证指数"},
    {"code": "sz399006", "name": "创业板指"},
    {"code": "sh000688", "name": "科创50"},
]''',
     '''INDEX_LIST = [
    {"code": "sh000001", "name": "上证指数"},
    {"code": "sz399001", "name": "深证成指"},
    {"code": "sz399006", "name": "创业板指"},
    {"code": "sh000688", "name": "科创50"},
]'''),

    # F6: calc_trend_score 可能返回 None（清洗后不足60行）
    ('''            if len(df) < 60: continue
            s = calc_trend_score(df)
            s["name"] = idx["name"]; s["code"] = idx["code"]''',
     '''            if len(df) < 60: continue
            s = calc_trend_score(df)
            if not s: continue
            s["name"] = idx["name"]; s["code"] = idx["code"]'''),

    # F5: near_high 历史序列与当前值同窗口（含当日bar）同 clip
    ('''    near_high = np.clip(close[-1]/high_60, 0.7, 1.0)
    near_high_series = [close[end]/high[end-60:end].max() for end in range(60, n)]''',
     '''    near_high = np.clip(close[-1]/high_60, 0.7, 1.0)
    # 与当前值同口径：窗口含当日bar、同样 clip（原实现历史窗口不含当日且未 clip）
    near_high_series = [np.clip(close[end]/high[end-59:end+1].max(), 0.7, 1.0) for end in range(60, n)]'''),

    # F3: 每日缓存新鲜度工具
    ('''def _cs_pct(series, value):''',
     '''def _cache_fresh(path):
    """当日生成的缓存才可用（每日cron重算；cron失败时现算自愈，避免长期喂昨日数据）"""
    try:
        import os as _os
        return time.strftime('%Y%m%d', time.localtime(_os.path.getmtime(path))) == time.strftime('%Y%m%d')
    except Exception:
        return False


def _cs_pct(series, value):'''),

    # F3: 板块评分缓存加新鲜度校验
    ('''    cache_file = Path("/opt/stock-review/data") / "trend_sector_scores.json"
    # 尝试读缓存
    try:
        if cache_file.exists():''',
     '''    cache_file = Path("/opt/stock-review/data") / "trend_sector_scores.json"
    # 尝试读缓存（仅当日有效）
    try:
        if cache_file.exists() and _cache_fresh(cache_file):'''),

    # F3: 个股精选缓存加新鲜度校验
    ('''    cache_file = Path("/opt/stock-review/data") / "trend_stock_picks.json"
    try:
        if cache_file.exists():''',
     '''    cache_file = Path("/opt/stock-review/data") / "trend_stock_picks.json"
    try:
        if cache_file.exists() and _cache_fresh(cache_file):'''),
])

# ══ 前端 trend_momentum.js ══
edit('static/js/trend_momentum.js', [
    # F4: "距高点"错用 total_gain → 拆分为累计涨幅 + 距高点
    ('''      const gain = s.total_gain != null ? s.total_gain : s.drawdown_from_peak;
      const gainColor = gain >= 0 ? '#e74c3c' : '#27ae60';''',
     '''      const tg = s.total_gain;   // 累计涨幅（触发至今）
      const dd = s.drawdown_from_peak;  // 距高点回撤
      const tgColor = tg >= 0 ? '#e74c3c' : '#27ae60';'''),
    ('''            <span>距高点 <b style="color:${gainColor}">${gain != null ? gain.toFixed(2) : '-'}%</b></span>''',
     '''            <span>累计涨幅 <b style="color:${tgColor}">${tg != null ? tg.toFixed(2) : '-'}%</b></span>
            <span>距高点 <b>${dd != null ? dd.toFixed(2) : '-'}%</b></span>'''),

    # F1: 实现 tmLoadOverview（原只调用未定义 → initTrendMomentum 抛 ReferenceError 中断）
    ('''  tmLoadOverview();
}''',
     '''  tmLoadOverview();
}

// ── 大盘环境 + 指数趋势总览（原缺失实现，导致初始化中断/面板空白）──
async function tmLoadOverview() {
  try {
    const res = await fetch('/api/trend/overview');
    const json = await res.json();
    if (json.code === 0 && json.data) {
      const { indices, market_env } = json.data;
      const envEl = $('#tm-market-env');
      if (envEl && market_env && market_env.score != null) {
        envEl.innerHTML = `
          <div><span class="tm-env-label">大盘环境</span><br>
            <span class="tm-env-value" style="color:${tmColor(market_env.score)}">${market_env.score}</span>
            <span style="font-size:13px;color:var(--gray-500)"> · ${market_env.level || ''}</span>
          </div>
          <div><span class="tm-env-label">总仓位上限</span><br>
            <span class="tm-env-value">${Math.round((market_env.max_position || 1) * 100)}%</span>
          </div>
          <div><span class="tm-env-label">单只上限</span><br>
            <span class="tm-env-value">20%</span>
          </div>
          <div style="flex:1;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
            ${(indices || []).map(i => `
              <span style="background:${tmBgColor(i.score)};color:${tmColor(i.score)};padding:4px 10px;border-radius:8px;font-size:12px;font-weight:600">
                ${i.name} ${i.score} <span style="font-weight:400;opacity:.8">${i.action || ''}</span>
              </span>`).join('')}
          </div>
        `;
      }
    }
  } catch (e) { console.error('tmLoadOverview error', e); }
  // 默认 tab（突破信号）
  const content = $('#tm-content');
  if (content && !content.innerHTML.trim()) loadSectorSignals();
}'''),
])

edit('static/index.html', [
    ('<script src="/static/js/trend_momentum.js?v=2"></script>',
     '<script src="/static/js/trend_momentum.js?v=3"></script>'),
])

print('patch17 done')
