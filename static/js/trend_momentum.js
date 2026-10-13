/* ═══════════════════════════════════════════════════════════════
   趋势动量 · M1/M2/M3 观察哨（v2 旅程条版，2026-10-07）
   口径（冻结 v2，docs/FREEZE_20261007.md）：
     M1 闸门  tier 优先/常规/禁止
     M2 标记  A 地量反转底(T+3确认/T+4入) · B 放量V反底(T+1入) · 早入=优先∧R3
     M3 v2    加仓=MA20±2%企稳阳低吸 ∪ 周线MA10±2%低吸（冷却5日≤3份）
              出场=sdw双周期破位（日线摆动低点∧周线破位）· C4砍腿 · 硬止损-8% · 250日帽
              风险预算3%/单位止损距(≤20%) · 并发≤3 · 确认层v3=观察哨
   结论层：大盘阶段 + 板块周线阶段（P0 起）人话总结（quant/m2m3_summary.py，纯展示）
   设计：结论条 + 核心4数（浮动/距止损/距加仓/份数）+ 价格旅程条 + 时间尺 + 状态分区
   ═══════════════════════════════════════════════════════════════ */

const TM_TIER_COLOR = { '优先': '#e74c3c', '常规': '#e67e22', '禁止': '#6b7280' };
const TM_NEAR = 5;   // 今日动作阈值：距止损/距加仓线 < 5%

async function tmFetch(path, opts) {
  const r = await fetch(path, {
    cache: 'no-store',
    headers: { 'X-API-Key': (window.APP_API_KEY || ''), 'Content-Type': 'application/json' },
    ...(opts || {})
  });
  return r.json();
}

function fmtDate(d) {
  return d && d.length === 8 ? `${d.slice(4, 6)}-${d.slice(6, 8)}` : (d || '-');
}

function tmBadge(text, color) {
  return `<span style="background:${color}22;color:${color};padding:2px 10px;border-radius:10px;font-size:12px;font-weight:600">${text}</span>`;
}

function tmStyles() {
  if ($('#tm-style')) return;
  const style = document.createElement('style');
  style.id = 'tm-style';
  style.textContent = `
    .tm-bar { position:relative; height:44px; margin:14px 0 4px; }
    .tm-track { position:absolute; left:0; right:0; top:16px; height:6px; background:var(--gray-200); border-radius:3px; }
    .tm-seg { position:absolute; top:16px; height:6px; border-radius:3px; }
    .tm-pin { position:absolute; top:8px; width:2px; height:22px; transform:translateX(-1px); }
    .tm-dot { position:absolute; top:9px; width:20px; height:20px; border-radius:50%; transform:translateX(-10px);
              border:3px solid #fff; box-shadow:0 1px 4px rgba(0,0,0,.25); }
    .tm-lbl { position:absolute; top:32px; font-size:10.5px; color:var(--gray-500); transform:translateX(-50%); white-space:nowrap; }
    .tm-lbl-top { position:absolute; top:-4px; font-size:10.5px; transform:translateX(-50%); white-space:nowrap; font-weight:600; }
    .tm-num { font-size:23px; font-weight:700; line-height:1.1; }
    .tm-sub { font-size:12px; color:var(--gray-600); }
    .tm-rule { height:1px; background:var(--border); margin:12px 0; }
  `;
  document.head.appendChild(style);
}

async function loadTrendMomentum() {
  const el = $('#page-trend_momentum');
  if (!el) return;
  el.innerHTML = `
    <div class="page-header"><div class="page-title">📈 趋势动量 · M1/M2/M3 观察哨</div></div>
    <div id="tm-root"><div class="card">加载中...</div></div>`;
  const root = $('#tm-root');
  let json;
  try {
    json = await tmFetch('/api/m2m3/snapshot');
  } catch (e) {
    root.innerHTML = `<div class="card">加载失败: ${e.message}</div>`;
    return;
  }
  if (!json.data) {
    root.innerHTML = `
      <div class="card">
        <p>${json.msg || '暂无数据'}</p>
        <button onclick="tmRefresh()" style="margin-top:10px;padding:8px 18px;border:none;border-radius:8px;background:var(--primary);color:#fff;cursor:pointer">立即生成（1~3 分钟）</button>
      </div>`;
    return;
  }
  tmRender(root, json.data);
}

async function tmRefresh() {
  const root = $('#tm-root');
  if (root) root.innerHTML = '<div class="card">重算中（1~3 分钟），完成后自动刷新...</div>';
  try {
    const r = await tmFetch('/api/m2m3/refresh', { method: 'POST' });
    if (r.code !== 0) throw new Error(r.msg || r.detail || '重算失败');
  } catch (e) {
    if (root) root.innerHTML = `<div class="card">重算失败: ${e.message}</div>`;
    return;
  }
  loadTrendMomentum();
}

/* ── 价格旅程条 ── */
function tmPriceBar(L) {
  const entry = L.entry_px, cur = L.cur_px, stop = L.stop_line ?? L.hard_stop_px;
  const nxt = L.next_ladder ? L.next_ladder.trig_px : null;
  const hit = (L.add_log || []).map(x => ({ lvl: '低吸', trig_px: x.px }));
  const vals = [entry, cur, stop, nxt, ...hit.map(x => x.trig_px)].filter(x => x != null);
  const lo = Math.min(...vals) * 0.985, hi = Math.max(...vals) * 1.015;
  const X = v => ((v - lo) / (hi - lo) * 100).toFixed(1) + '%';

  const segs = `
    <div class="tm-seg" style="left:${X(stop)};width:calc(${X(entry)} - ${X(stop)});background:#8b5cf622"></div>
    <div class="tm-seg" style="left:${X(entry)};width:calc(${X(cur > entry ? cur : entry)} - ${X(entry)});background:#2563eb18"></div>`;
  const pins = [
    `<div class="tm-pin" style="left:${X(stop)};background:#8b5cf6"></div>
     <div class="tm-lbl" style="left:${X(stop)}">🛑 ${stop}</div>`,
    `<div class="tm-pin" style="left:${X(entry)};background:#6b7280"></div>
     <div class="tm-lbl" style="left:${X(entry)}">入 ${entry}</div>`,
    ...hit.map(x => `
     <div class="tm-pin" style="left:${X(x.trig_px)};background:#2563eb"></div>
     <div class="tm-lbl" style="left:${X(x.trig_px)}">✓${x.lvl}</div>`),
  ];
  if (nxt) pins.push(`
     <div class="tm-pin" style="left:${X(nxt)};background:#e67e22"></div>
     <div class="tm-lbl" style="left:${X(nxt)}">🎯 ${nxt}</div>`);
  return `
    <div class="tm-bar">
      <div class="tm-track"></div>${segs}${pins.join('')}
      <div class="tm-dot" style="left:${X(cur)};background:#2563eb"></div>
      <div class="tm-lbl-top" style="left:${X(cur)};color:#2563eb">${cur}</div>
    </div>`;
}

/* ── 时间尺（完整版：里程碑 + 检查点状态 + 当前 + 时间帽）── */
function tmTimeBar(s, L) {
  const capK = (L.entry_k ?? 0) + 250;
  const hi = Math.max(s.k_today * 1.15, 45);
  const X = k => (Math.min(k, hi) / hi * 100).toFixed(1) + '%';
  const marks = [{ k: 5, lbl: 'T+5判定', c: '#8b5cf6' }];
  marks.push({ k: L.entry_k, lbl: `T+${L.entry_k}入场`, c: '#6b7280' });
  (s.cps || []).forEach(cp => {
    const state = cp.over ? '过阈' : (cp.score != null ? '未过' : '待');
    marks.push({ k: cp.k, lbl: `T+${cp.k}${state}`, c: cp.score == null ? '#cbd5e1' : (cp.over ? '#27ae60' : '#9ca3af') });
  });
  marks.push({ k: s.k_today, lbl: `T+${s.k_today}今天`, c: '#2563eb' });
  const pins = marks.map(m => `
    <div class="tm-pin" style="left:${X(m.k)};background:${m.c};height:${m.k === s.k_today ? 28 : 18}px;top:${m.k === s.k_today ? 6 : 8}px"></div>
    <div class="tm-lbl" style="left:${X(m.k)};color:${m.k === s.k_today ? '#2563eb' : 'var(--gray-500)'};font-weight:${m.k === s.k_today ? 700 : 400}">${m.lbl}</div>`).join('');
  return `
    <div class="tm-bar" style="height:38px">
      <div class="tm-track" style="top:14px"></div>
      <div class="tm-seg" style="left:0;width:${X(s.k_today)};top:14px;background:#2563eb22"></div>
      ${pins}
      <div class="tm-lbl" style="left:${(Math.min(capK, hi) / hi * 100).toFixed(1)}%;top:26px;color:#9ca3af">⋯ T+${capK} 时间帽 →</div>
    </div>`;
}

/* ── 腿卡 ── */
function tmLegCard(s, L) {
  const dist = L.next_ladder ? L.next_ladder.dist_pct : null;
  const stopD = L.stop_dist_pct;
  const stopColor = stopD == null ? '#9ca3af' : (stopD < 3 ? '#8b5cf6' : stopD < TM_NEAR ? '#e67e22' : '#6b7280');
  const addColor = dist == null ? '#9ca3af' : (dist < 3 ? '#e67e22' : dist < TM_NEAR ? '#f59e0b' : '#6b7280');
  const pnlColor = L.pnl_pct >= 0 ? '#e74c3c' : '#27ae60';
  const exited = L.status === '已出场';

  const detailRows = `
    <details style="margin-top:8px">
      <summary style="cursor:pointer;font-size:12px;color:var(--gray-500)">详情 ▸ 研究字段/规则状态</summary>
      <div style="display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--gray-600);margin-top:8px">
        <span>入场 <b>${L.entry_date} @${L.entry_px}</b>（T+${L.entry_k}）</span>
        <span>硬止损 ${L.hard_stop_px}</span>
        <span>P0锚 ${L.p0_anchor_px}</span>
        <span>止损类型 <b>${L.stop_kind}</b></span>
        <span>周线破位 <b style="color:${L.sw_break ? '#e74c3c' : '#27ae60'}">${L.sw_break ? '⚠️ 是' : '否'}</b></span>
        <span>加仓规则 MA20/周MA10 低吸（±2% 企稳阳）</span>
        <span>每份风险仓位 <b>${L.risk_unit_pct}%</b></span>
        <span>份额 ${s.share ?? '-'}% / 均额 ${s.amt20 ?? '-'}亿</span>
        <span>20日跌幅 ${s.drop20 != null ? (s.drop20 * 100).toFixed(1) + '%' : '-'}</span>
        <span>三日累计超额 ${s.cum_ex != null ? (s.cum_ex * 100).toFixed(2) + '%' : '-'}</span>
        <span>R3 ${s.r3 == null ? '待判定' : (s.r3 ? '✓' : '✗')}</span>
        <span>v3 检查点 ${(s.cps || []).map(c => `T+${c.k}:${c.score ?? '-'}`).join(' / ') || '观察中'}</span>
      </div>
    </details>`;

  const addLog = L.add_log || [];
  const ladderRow = [
    ...addLog.map(x => `<span style="color:#2563eb;font-weight:600">✓低吸已加仓（${x.date} @${x.px}）</span>`),
    ...(L.next_ladder ? [`<span style="color:var(--gray-500)">○${L.next_ladder.lvl} 待触 ${L.next_ladder.trig_px}</span>`] : []),
  ].join('<span style="color:var(--gray-300)"> · </span>');

  return `
    <div style="margin-top:10px;padding:12px 14px;background:var(--card-bg);border:1px solid var(--border);border-radius:10px">
      <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px;align-items:flex-start">
        <div>
          <b style="font-size:14px">${L.leg}腿</b>
          ${exited
            ? '<span style="background:#6b728022;color:#6b7280;padding:2px 8px;border-radius:8px;font-size:11px;margin-left:6px">已出场</span>'
            : `<span style="background:#e74c3c18;color:#e74c3c;padding:2px 8px;border-radius:8px;font-size:11px;margin-left:6px">持有 ${L.units} 份</span>`}
          <div class="tm-sub" style="margin-top:4px">
            ${exited
              ? `出场 <b>${L.exit.date}</b> ${L.exit.reason} @${L.exit.px}（${L.exit.pnl_pct >= 0 ? '+' : ''}${L.exit.pnl_pct}%）`
              : `入场 ${L.entry_date} @${L.entry_px}`}
          </div>
        </div>
        <div style="display:flex;gap:22px;align-items:flex-start">
          <div>
            <div class="tm-num" style="color:${pnlColor}">${L.pnl_pct >= 0 ? '+' : ''}${L.pnl_pct}%</div>
            <div class="tm-sub">浮动${exited ? '（出场时）' : ''}${L.mfe_pct != null ? ` · MFE +${L.mfe_pct}%` : ''}</div>
          </div>
          ${exited ? '' : `
          <div>
            <div class="tm-num" style="color:${stopColor}">${stopD != null ? stopD + '%' : '-'}</div>
            <div class="tm-sub">距止损</div>
          </div>
          <div>
            <div class="tm-num" style="color:${addColor}">${dist != null ? '+' + dist + '%' : '满配'}</div>
            <div class="tm-sub">${dist != null ? `距${L.next_ladder.lvl}加仓` : '3/3 份'}</div>
          </div>`}
        </div>
      </div>
      ${exited ? '' : tmPriceBar(L) + tmTimeBar(s, L)}
      ${exited ? '' : `<div style="font-size:12px;margin-top:2px">${ladderRow}</div>`}
      ${detailRows}
    </div>`;
}

/* ── 信号卡 ── */
function tmSigCard(s) {
  return `
    <div class="card" style="margin-bottom:12px">
      <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;align-items:center">
        <div>
          <b style="font-size:17px">${s.name}</b>
          <span style="color:var(--gray-400);font-size:12px;margin-left:6px">${s.code}</span>
          ${tmBadge(s.tier || '-', TM_TIER_COLOR[s.tier] || '#888')}
          <span style="background:#3b82f618;color:#3b82f6;padding:2px 8px;border-radius:8px;font-size:11px;margin-left:4px">${s.chan === 'A' ? 'A·地量反转' : 'B·V反底'}</span>
        </div>
        <div style="font-size:14px;font-weight:600">
          P0 ${fmtDate(s.p0)} · <span style="color:#2563eb">今天 T+${s.k_today}</span>
          <span style="font-size:11px;font-weight:400;color:var(--gray-500);margin-left:8px">${s.quadrant || ''} ${s.wave_phase || ''}</span>
        </div>
      </div>
      ${s._sm ? `
      <div style="margin-top:10px;padding:9px 12px;background:${s._sm.color}10;border-left:3px solid ${s._sm.color};border-radius:8px;font-size:13px;line-height:1.7">
        <b style="color:${s._sm.color}">${s._sm.stage_label}</b>
        <span style="color:var(--gray-600);margin-left:8px">${s._sm.stage_text}</span>
        <div style="color:var(--gray-700);margin-top:2px">→ ${s._sm.action_text}</div>
      </div>` : ''}
      ${(s.legs || []).map(L => tmLegCard(s, L)).join('') || '<div style="margin-top:8px;font-size:12px;color:var(--gray-400)">入场腿生成中（未到入场日）</div>'}
    </div>`;
}

function tmRender(root, snap) {
  tmStyles();
  const env = snap.env || {};
  const tier = env.tier || '-';
  const signals = snap.signals || [];
  const smap = {};
  ((snap.summary && snap.summary.signals) || []).forEach(x => { smap[x.code] = x; });
  signals.forEach(s => { s._sm = smap[s.code]; });

  const gateCard = `
    <div class="card" style="border-left:4px solid ${TM_TIER_COLOR[tier] || '#888'};margin-bottom:16px;padding:14px 18px">
      <div style="display:flex;gap:14px;align-items:baseline;flex-wrap:wrap">
        <span style="font-size:13px;color:var(--gray-500)">M1 闸门 · ${snap.asof}</span>
        <span style="font-size:22px;font-weight:800;color:${TM_TIER_COLOR[tier] || '#888'}">${tier}</span>
        <span style="font-size:15px;font-weight:600;color:var(--gray-700)">${env.action || ''}</span>
        <span style="font-size:13px;color:var(--gray-600)">${env.quadrant || ''} · ${(env.wave_phase && env.wave_phase.phase) || '-'}</span>
      </div>
      ${snap.summary && snap.summary.env_summary ? `
      <div style="margin-top:10px;padding:10px 12px;background:${snap.summary.env_summary.color}12;border-left:3px solid ${snap.summary.env_summary.color};border-radius:8px;font-size:13.5px;line-height:1.9;color:var(--gray-700)">
        <b style="color:${snap.summary.env_summary.color};font-size:14px">🧭 ${snap.summary.env_summary.headline}</b><br>
        ${snap.summary.env_summary.text}
      </div>` : ''}
      <details style="margin-top:6px">
        <summary style="cursor:pointer;font-size:12px;color:var(--gray-500)">闸门详情 ▸</summary>
        <div style="font-size:12px;color:var(--gray-600);margin-top:6px">
          趋势强 ${env.attack ? '是' : '否'} · 趋势龄 ${env.trend_age ?? '-'} · MA120上方 ${env.above_ma120 ? '是' : '否'}
          · 回撤 r ${env.wave_phase ? env.wave_phase.r : '-'} / 时长比 tr ${env.wave_phase ? env.wave_phase.tr : '-'}
          ${env.wave_phase && env.wave_phase.fresh_panic ? ' · 恐慌新鲜低' : ''}
          <div style="margin-top:4px">优先 = 重仓资格（早入+标准腿）｜常规 = 仅标准腿小仓｜禁止 = 不开新仓</div>
        </div>
      </details>
    </div>`;

  // ── 分区：今日动作 / 持有中 / 已出场 ──
  const today = [], holding = [], exited = [];
  signals.forEach(s => {
    const acts = (s.legs || []).filter(l => l.status === '持有');
    if (!acts.length) { exited.push(s); return; }
    const near = acts.some(l =>
      (l.stop_dist_pct != null && l.stop_dist_pct < TM_NEAR) ||
      (l.next_ladder && l.next_ladder.dist_pct < TM_NEAR));
    if (near || (s.k_today != null && s.k_today <= 2)) today.push(s);
    else holding.push(s);
  });
  const byNear = (a, b) => {
    const f = s => Math.min(...(s.legs || []).filter(l => l.status === '持有')
      .map(l => l.next_ladder ? l.next_ladder.dist_pct : 999), 999);
    return f(a) - f(b);
  };
  holding.sort(byNear);

  const sec = (title, arr, note) => arr.length ? `
    <div style="margin:18px 0 10px;font-size:15px;font-weight:700">${title}
      <span style="font-size:12px;font-weight:400;color:var(--gray-500);margin-left:8px">${note || ''}</span>
    </div>${arr.map(tmSigCard).join('')}` : '';

  const exitWrap = exited.length ? `
    <details style="margin:18px 0">
      <summary style="cursor:pointer;font-size:15px;font-weight:700">📦 近 30 天出场（${exited.length}）▸</summary>
      <div style="margin-top:10px">${exited.map(tmSigCard).join('')}</div>
    </details>` : '';

  const rules = snap.rules || {};
  const ruleCard = `
    <div class="card" style="margin-top:16px;font-size:12.5px;color:var(--gray-600)">
      <b style="color:var(--gray-700)">📌 口径（冻结）</b>
      <div style="margin-top:6px">M2 ${rules.M2 || ''}</div>
      <div>M3 ${rules.M3 || ''}</div>
      <div>${rules['仓位'] || ''}</div>
      <div style="margin-top:8px;color:var(--gray-500)">
        人工聚焦 1-3 板块由用户按产业趋势决定——系统全列表只是池子与观察哨，不驱动仓位。
        今日动作 = 距止损或距加仓线 &lt;${TM_NEAR}%。生成 ${snap.generated_at}（每日 16:20 自动重算）
      </div>
    </div>`;

  root.innerHTML = gateCard
    + sec('🎯 今日动作', today, `距止损或距加仓线 ${TM_NEAR}% 以内 / 新标记`)
    + sec('👀 持有中', holding, '按距加仓线远近排序')
    + exitWrap
    + ruleCard;
}
