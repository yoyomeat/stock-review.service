"""修改 app.js — 加 wave 页面支持"""
fp = "/opt/stock-review/static/js/app.js"
with open(fp, encoding="utf-8") as f:
    js = f.read()

# 1. 更新 idx 映射
old_idx = """const idx = { dashboard: 0, review: 1, trend: 2, position: 3, backtest: 4, realtime: 5, ipo: 6 };"""
new_idx = """const idx = { dashboard: 0, review: 1, trend: 2, position: 3, backtest: 4, realtime: 5, ipo: 6, wave: 7 };"""
js = js.replace(old_idx, new_idx)

# 2. 加 wave 页面加载逻辑
old_ipo = "  if (name === 'ipo' && !window._ipoLoaded) loadIpoPage();"
new_ipo = old_ipo + "\n  if (name === 'wave' && !window._waveLoaded) loadWaveDbPage();"
js = js.replace(old_ipo, new_ipo)

with open(fp, "w", encoding="utf-8") as f:
    f.write(js)

print("app.js updated")
