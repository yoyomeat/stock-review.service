"""修改 index.html — 加板块数据侧边栏和页面"""
import re

fp = "/opt/stock-review/static/index.html"
with open(fp, encoding="utf-8") as f:
    html = f.read()

# 1. 在 IPO 侧边栏后面加板块数据
ipo_nav = '''    <a class="nav-item" onclick="showPage('ipo')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
      新股评分
    </a>'''

wave_nav = ipo_nav + '''
    <a class="nav-item" onclick="showPage('wave')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/></svg>
      板块数据
    </a>'''

html = html.replace(ipo_nav, wave_nav)

# 2. 在 IPO page div 后面加板块数据页面
ipo_page_end = '''    </div>
  </main>
</div>'''

wave_page = '''    </div>

    <!-- Wave Analysis DB -->
    <div id="page-wave" class="page">
      <div class="page-header">
        <div class="page-title">板块数据</div>
        <div class="page-subtitle">波浪分析数据库 · 指数/板块/概念K线浏览</div>
      </div>
      <div id="wave-overview"></div>
      <div class="wave-toolbar">
        <div class="wave-table-tabs">
          <button class="wave-table-tab active" data-table="index_daily" onclick="loadWaveTable('index_daily')">指数日K</button>
          <button class="wave-table-tab" data-table="weekly_kline" onclick="loadWaveTable('weekly_kline')">周K线</button>
          <button class="wave-table-tab" data-table="monthly_kline" onclick="loadWaveTable('monthly_kline')">月K线</button>
          <button class="wave-table-tab" data-table="sector_daily" onclick="loadWaveTable('sector_daily')">板块日K</button>
          <button class="wave-table-tab" data-table="concept_daily" onclick="loadWaveTable('concept_daily')">概念日K</button>
          <button class="wave-table-tab" data-table="trading_calendar" onclick="loadWaveTable('trading_calendar')">交易日历</button>
          <button class="wave-table-tab" data-table="zigzag_points" onclick="loadWaveTable('zigzag_points')">Zigzag</button>
          <button class="wave-table-tab" data-table="wave_labels" onclick="loadWaveTable('wave_labels')">波浪标注</button>
          <button class="wave-table-tab" data-table="wave_counts" onclick="loadWaveTable('wave_counts')">波浪计数</button>
          <button class="wave-table-tab" data-table="signal_events" onclick="loadWaveTable('signal_events')">信号事件</button>
        </div>
        <div class="wave-filter">
          <select id="wave-code-filter" onchange="waveFilterCode(this.value)" style="display:none">
            <option value="">全部</option>
          </select>
        </div>
      </div>
      <div id="wave-table-content"></div>
      <div class="wave-sql-section">
        <div class="wave-sql-title">SQL 查询</div>
        <div class="wave-sql-row">
          <input id="wave-sql-input" type="text" placeholder="SELECT * FROM index_daily WHERE code='sh000001' ORDER BY trade_date DESC LIMIT 20"
                 onkeydown="if(event.key==='Enter')waveQuery()">
          <button onclick="waveQuery()">执行</button>
        </div>
        <div id="wave-query-result"></div>
      </div>
    </div>
  </main>
</div>'''

html = html.replace(ipo_page_end, wave_page)

# 3. 加 JS 引用
html = html.replace(
    '<script src="/static/js/ipo.js?v=1"></script>',
    '<script src="/static/js/ipo.js?v=1"></script>\n<script src="/static/js/wave_db.js?v=1"></script>'
)

with open(fp, "w", encoding="utf-8") as f:
    f.write(html)

print("index.html updated")
