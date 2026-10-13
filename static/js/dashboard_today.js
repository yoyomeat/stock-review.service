/* ═══════════════════════════════════════════════════════════════
   仪表盘 · 今日作战面板 v2（2026-10-08 前端重构）
   目标：全项目结论连成一体 —— 每日操作一眼可读
     Hero   📌 今日作战结论（一句话）
     结论区  🧭 大盘环境 ｜ 📝 昨日复盘（各模块直观结论）
     动作区  🎯 今日动作 ｜ 💼 持仓警戒
     节奏区  ⏱ 今日数据流水线（时间线 + 状态灯）
     入口区  🧠 情绪复盘 / 各模块快捷入口
   数据源：/api/dashboard/summary（聚合）+ /api/m2m3/snapshot + /api/position_risk
   颜色语义：红=涨/紧急 橙=临近 紫=警戒 绿=安全/完成 蓝=信息
   ═══════════════════════════════════════════════════════════════ */

const DT_NEAR = 5;
const DT_ST = {
  done: { c: '#10B981', t: '✓' }, failed: { c: '#e74c3c', t: '✗' },
  missed: { c: '#e67e22', t: '!' }, pending: { c: '#cbd5e1', t: '○' },
  skip: { c: '#3b82f6', t: '—' }, paused: { c: '#9ca3af', t: '⏸' },
};

function dtBadge(text, color) {
  return `<span style="background:${color}22;color:${color};padding:2px 10px;border-radius:10px;font-size:12px;font-weight:600">${text}</span>`;
}

async function loadTodayModules(el) {
  let sum = null, snap = null, pos = null;
  try { sum = await (await fetch('/api/dashboard/summary', { cache: 'no-store' })).json(); sum = sum.data; } catch (e) { }
  try { snap = await (await fetch('/api/m2m3/snapshot', { cache: 'no-store' })).json(); snap = snap.data; } catch (e) { }
  try { pos = await (await fetch('/api/position_risk', { cache: 'no-store' })).json(); } catch (e) { }

  const tier = snap?.env?.tier || '-';
  const TIER_C = { '优先': '#e74c3c', '常规': '#e67e22', '禁止': '#6b7280' }[tier] || '#888';

  // ── Hero：今日作战结论 ──
  const hero = `
    <div class="card" style="margin-bottom:16px;background:linear-gradient(135deg,${TIER_C}0a,transparent);border-left:4px solid ${TIER_C}">
      <div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px">
        <div>
          <div style="font-size:12px;color:var(--gray-500)">📌 今日作战结论 · ${sum?.date ? sum.date.slice(4, 6) + '-' + sum.date.slice(6, 8) : ''} ${sum?.is_trading_day ? '' : dtBadge('非交易日', '#3b82f6')}</div>
          <div style="font-size:19px;font-weight:800;color:var(--gray-800);margin-top:4px">${sum?.headline || '汇总加载中…'}</div>
        </div>
        <div style="font-size:11px;color:var(--gray-400)">生成 ${sum?.generated_at || '-'}</div>
      </div>
    </div>`;

  // ── 结论区：大盘环境 + 昨日复盘 ──
  const env = sum?.env;
  const envCard = `
    <div class="card" style="border-left:4px solid ${TIER_C}">
      <div style="display:flex;gap:10px;align-items:baseline;flex-wrap:wrap">
        <b style="font-size:15px">🧭 大盘环境</b>
        ${dtBadge(env?.headline || `${tier}档`, env?.color || TIER_C)}
        <a onclick="showPage('trend_momentum');loadTrendMomentum()" style="margin-left:auto;font-size:12px;color:var(--primary);cursor:pointer">观察哨 →</a>
      </div>
      <div style="margin-top:8px;font-size:13px;line-height:1.8;color:var(--gray-700)">${env?.text || snap?.env?.action || '环境结论未生成（16:20 后可用）'}</div>
    </div>`;

  const rv = sum?.review;
  const rvCard = `
    <div class="card" style="border-left:4px solid #8b5cf6">
      <div style="display:flex;gap:10px;align-items:baseline;flex-wrap:wrap">
        <b style="font-size:15px">📝 昨日复盘结论</b>
        ${dtBadge(rv?.sentiment_level || '-', '#8b5cf6')}
        ${dtBadge(rv?.profit_level || '-', rv?.profit_score >= 60 ? '#e74c3c' : '#e67e22')}
        <span style="font-size:12px;color:var(--gray-500)">${rv?.date || ''} · ${rv?.cycle_label || ''}</span>
        <a onclick="showPage('review')" style="margin-left:auto;font-size:12px;color:var(--primary);cursor:pointer">复盘 →</a>
      </div>
      <div style="margin-top:8px;font-size:13px;line-height:1.8;color:var(--gray-700)">
        ${rv?.strategy_text ? `💡 ${rv.strategy_text}` : '复盘结论未生成'}
        ${(rv?.stop_loss_text || rv?.take_profit_text) ? `
        <div style="margin-top:4px;color:var(--gray-600);font-size:12.5px">
          ${rv.stop_loss_text ? `🛑 ${rv.stop_loss_text}` : ''} ${rv.take_profit_text ? `🎯 ${rv.take_profit_text}` : ''}
        </div>` : ''}
      </div>
    </div>`;

  // ── 动作区：今日动作 + 持仓警戒（沿用 P1 逻辑）──
  const acts = [];
  (snap?.signals || []).forEach(s => {
    (s.legs || []).filter(l => l.status === '持有').forEach(l => {
      const nearStop = l.stop_dist_pct != null && l.stop_dist_pct < DT_NEAR;
      const nearAdd = l.next_ladder && l.next_ladder.dist_pct < DT_NEAR;
      if (nearStop || nearAdd) acts.push({ s, l, nearStop, nearAdd });
    });
    if (s.k_today != null && s.k_today <= 2 && (s.legs || []).length) acts.push({ s, l: s.legs[0], isNew: true });
  });
  const actRows = acts.slice(0, 6).map(({ s, l, nearStop, nearAdd, isNew }) => {
    const tag = isNew ? dtBadge('新标记', '#8b5cf6') : nearStop ? dtBadge('距止损', '#8b5cf6') : dtBadge('准备加仓', '#e67e22');
    return `
      <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:8px 0;border-bottom:1px solid var(--border)">
        <b style="min-width:90px">${s.name}</b>
        ${tag}
        <span style="color:var(--gray-500);font-size:12px">${s.chan}·${s.tier} · ${l.leg}腿 ${l.units}份</span>
        <span style="margin-left:auto;font-size:13px">
          浮动 <b style="color:${l.pnl_pct >= 0 ? '#e74c3c' : '#10B981'}">${l.pnl_pct >= 0 ? '+' : ''}${l.pnl_pct}%</b>
          ${l.stop_dist_pct != null ? `· 距止损 <b style="color:${l.stop_dist_pct < 3 ? '#8b5cf6' : '#e67e22'}">${l.stop_dist_pct}%</b>` : ''}
          ${l.next_ladder ? `· 距${l.next_ladder.lvl} <b style="color:#e67e22">+${l.next_ladder.dist_pct}%</b>` : ''}
        </span>
      </div>`;
  }).join('');

  const positions = (pos?.positions || []);
  const urgent = positions.map(p => ({
    ...p,
    _urgency: (p.unreal_pct != null && p.unreal_pct <= -5 ? 2 : 0) +
      (p.max_days && p.held_days >= p.max_days ? 1 : 0)
  })).sort((a, b) => b._urgency - a._urgency || (a.unreal_pct ?? 0) - (b.unreal_pct ?? 0)).slice(0, 4);
  const posRows = urgent.map(p => {
    const over = p.max_days && p.held_days >= p.max_days;
    return `
      <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:8px 0;border-bottom:1px solid var(--border)">
        <b style="min-width:90px">${p.name || p.code}</b>
        ${p.unreal_pct <= -5 ? dtBadge('浮亏警戒', '#8b5cf6') : (over ? dtBadge('超时持有', '#e67e22') : '')}
        <span style="margin-left:auto;font-size:13px">
          浮动 <b style="color:${(p.unreal_pct ?? 0) >= 0 ? '#e74c3c' : '#10B981'}">${p.unreal_pct >= 0 ? '+' : ''}${p.unreal_pct}%</b>
          · 持有 <b>${p.held_days}/${p.max_days}天</b> · 配置 ${p.alloc}%
        </span>
      </div>`;
  }).join('');

  const actionCard = `
    <div class="card">
      <div style="display:flex;gap:10px;align-items:baseline">
        <b style="font-size:15px">🎯 今日动作</b>${dtBadge(String(acts.length), acts.length ? '#e67e22' : '#10B981')}
        <span style="font-size:11px;color:var(--gray-500)">距止损/距加仓 ${DT_NEAR}% 以内 · 新标记</span>
      </div>
      <div style="margin-top:6px">${actRows || '<div style="font-size:12px;color:var(--gray-400);padding:8px 0">暂无需动作的在场腿</div>'}</div>
      <div style="margin-top:12px;display:flex;gap:10px;align-items:baseline">
        <b style="font-size:15px">💼 持仓警戒</b>${dtBadge(String(positions.length), '#8b5cf6')}
      </div>
      <div style="margin-top:6px">${posRows || '<div style="font-size:12px;color:var(--gray-400);padding:8px 0">暂无持仓</div>'}</div>
    </div>`;

  // ── 节奏区：今日数据流水线时间线 ──
  const pipe = sum?.pipeline || [];
  const pipeWrap = `
    <div class="card">
      <div style="display:flex;gap:10px;align-items:baseline;flex-wrap:wrap">
        <b style="font-size:15px">⏱ 今日数据流水线</b>
        <span style="font-size:11px;color:var(--gray-500)">收盘后自动跑：16:20 数据 → 16:30 复盘 → 17:00 板块 → 17:05 快照</span>
      </div>
      <div style="display:flex;flex-wrap:wrap;gap:10px 18px;margin-top:12px">
        ${pipe.map(p => {
          const st = DT_ST[p.status] || DT_ST.pending;
          return `<div style="display:flex;align-items:center;gap:6px;font-size:12.5px">
            <span style="width:20px;height:20px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;background:${st.c}22;color:${st.c};font-weight:700">${st.t}</span>
            <span style="color:var(--gray-400);font-size:11px">${p.time}</span>
            <span style="color:var(--gray-700)">${p.name}${p.note ? `<span style="color:var(--gray-400);font-size:11px"> · ${p.note}</span>` : ''}</span>
          </div>`;
        }).join('')}
      </div>
    </div>`;

  // ── 入口区 ──
  const links = `
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px">
      ${[['📈 观察哨', "showPage('trend_momentum');loadTrendMomentum()"],
         ['📝 每日复盘', "showPage('review')"],
         ['🧠 情绪复盘', "showPage('sentiment_review');loadSentimentReview()"],
         ['⏱ 盘中', "showPage('realtime')"],
         ['💼 持仓', "showPage('position')"],
         ['🧪 回测', "showPage('backtest')"],
         ['🐉 连板/行情', "showPage('realtime')"],
         ['🆕 新股', "showPage('ipo')"]]
        .map(([t, fn]) => `<button onclick="${fn}" style="padding:8px 14px;border:1px solid var(--border);border-radius:8px;background:var(--card);cursor:pointer;font-size:13px">${t}</button>`).join('')}
    </div>`;

  el.insertAdjacentHTML('afterbegin', hero + envCard + rvCard + actionCard + pipeWrap + links);
}
