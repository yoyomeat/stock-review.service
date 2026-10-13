# -*- coding: utf-8 -*-
"""patch19: 模块一前端 + 锚点锁定 API
- loadMarketWave：强度分/历史胜率/诚实话术/警示/锚点锁定按钮/共识度/背离提示
- routes/trend.py：POST /api/trend/wave_anchor（人工确认锚点，P0-3）
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

# ── routes/trend.py：锚点锁定端点 ──
edit('routes/trend.py', [
    ('from fastapi import APIRouter, Query',
     'from fastapi import APIRouter, Query, Depends\nfrom routes.auth import check_api_key'),
    ('@router.get("/market_wave")',
     '''@router.post("/wave_anchor")
async def set_wave_anchor(code: str = Query(...), start_date: str = Query(..., description="YYYYMMDD"),
                          start_price: float = Query(...), _k: str = Depends(check_api_key)):
    """人工确认锚点：锁定某指数周线5浪起点（不再随后续数据回移）"""
    from quant.market_wave_engine import set_wave5_anchor
    return {"code": 0, "data": set_wave5_anchor(code, start_date, start_price)}


@router.get("/market_wave")'''),
])

# ── 前端 trend_momentum.js ──
edit('static/js/trend_momentum.js', [
    # 状态行：平均概率→平均强度（P0-1 语义）+ 共识度 + 背离提示（P2-9）
    ('        <div style="font-size:12px;color:var(--gray-500);margin-top:4px">${pathACount}/${indices.length} 指数处于路径A · 平均概率 ${avgProb}% · ${fmtDate(d.date)}</div>',
     '''        <div style="font-size:12px;color:var(--gray-500);margin-top:4px">${pathACount}/${indices.length} 指数处于路径A · 平均强度 ${avgProb} · 共识度 ${d.consensus != null ? Math.round(d.consensus * 100) : '-'}% · ${fmtDate(d.date)}</div>
        ${d.divergence_note ? `<div style="font-size:11px;color:#e67e22;margin-top:4px">⚠️ ${d.divergence_note}</div>` : ''}'''),

    # prob → 强度分 + 历史胜率（P0-1）
    ('            <span style="background:${cardColor}18;color:${cardColor};padding:3px 10px;border-radius:6px;font-size:13px;font-weight:700">${i.prob}%</span>',
     '''            <span style="background:${cardColor}18;color:${cardColor};padding:3px 10px;border-radius:6px;font-size:13px;font-weight:700">强度${i.prob}</span>
            <span style="background:var(--gray-50);padding:3px 10px;border-radius:6px;font-size:11px;color:var(--gray-600)">${i.hist && i.hist.win20 != null ? '历史胜率' + i.hist.win20 + '%(n=' + i.hist.n + ')' : '历史样本不足'}</span>'''),

    # 话术/警示/锚点锁定按钮（P0-2/3、P2-8）
    ('''          ${fib}
          <div style="margin-top:8px;border-top:1px dashed var(--border);padding-top:6px">${conds}</div>
        </div>''',
     '''          ${fib}
          <div style="margin-top:8px;border-top:1px dashed var(--border);padding-top:6px">${conds}</div>
          ${i.action_note ? `<div style="font-size:11px;color:var(--gray-600);margin-top:6px;line-height:1.5">💡 ${i.action_note}</div>` : ''}
          ${i.warning ? `<div style="font-size:11px;color:#e67e22;margin-top:4px">⚠️ ${i.warning}</div>` : ''}
          ${i.framework_status ? `<div style="font-size:11px;color:#e67e22;margin-top:4px">🧭 ${i.framework_status}</div>` : ''}
          ${!i.anchor_locked && i.wave5_start ? `<button onclick="tmLockAnchor('${i.code}','${i.wave5_start_date}',${i.wave5_start})" style="margin-top:6px;padding:3px 10px;font-size:11px;border:1px solid var(--primary);border-radius:6px;background:var(--card);color:var(--primary);cursor:pointer">🔒 锁定锚点 ${i.wave5_start}（${fmtDate(i.wave5_start_date)}）</button>` : ''}
        </div>'''),
])

# 追加 tmLockAnchor
p = ROOT / 'static/js/trend_momentum.js'
p.write_text(p.read_text(encoding='utf-8') + '''
// ── 锚点锁定（P0-3）：把自动锚定的5浪起点固化为人工确认锚点 ──
async function tmLockAnchor(code, startDate, startPrice) {
  if (!confirm('锁定 ' + code + ' 周线5浪起点 = ' + startPrice + '（' + startDate + '）？\\n锁定后不再随数据回移，直到跌破失效位提示重标。')) return;
  try {
    const res = await fetch(`/api/trend/wave_anchor?code=${code}&start_date=${startDate}&start_price=${startPrice}`, { method: 'POST' });
    const j = await res.json();
    if (j.code === 0) {
      loadMarketWave();
    } else {
      alert('锁定失败: ' + (j.msg || j.detail || '未知错误'));
    }
  } catch (e) {
    alert('锁定失败: ' + e.message);
  }
}
''', encoding='utf-8')
print('ok [trend_momentum.js] tmLockAnchor appended')

edit('static/index.html', [
    ('<script src="/static/js/trend_momentum.js?v=3"></script>',
     '<script src="/static/js/trend_momentum.js?v=4"></script>'),
])

print('patch19 done')
