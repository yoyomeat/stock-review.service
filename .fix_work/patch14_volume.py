# -*- coding: utf-8 -*-
"""patch14: 量能预测卡片不显示修复
根因：前端要求今昨两天同一分钟都有采样点才保留（稀疏采样下重合=0）→ curvePoints 空
      → lastPt.amount 抛异常被静默 catch → 卡片永不渲染；
      且"昨日全天总量"取昨日最后采样点（数据中断时基数错误）。
修复：前值阶跃插值匹配 + 空数据降级渲染 + CSV 全天量能 + 时间格式兼容。"""
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

# ── 后端：_read_amounts 兼容两种时间格式 + 按分钟去重；响应加 prev_full_day_yi（CSV 精确全天量能）──
edit('routes/realtime.py', [
    ('''        def _read_amounts(date_str):
            fpath = _os.path.join(log_dir, "intraday_%s.jsonl" % date_str)
            if not _os.path.exists(fpath):
                return []
            result = []
            with open(fpath, encoding="utf-8") as _fh:
                _lines = list(_fh)
            for line in _lines:
                try:
                    d = _json.loads(line)
                    ts = d.get("timestamp", "")
                    amt = d.get("total_amount_yi", 0)
                    if ts and amt > 0:
                        minute = ts[11:16]  # "HH:MM"
                        result.append({"minute": minute, "amount": amt})
                except Exception:
                    pass
            return result

        today_data = _read_amounts(today)
        prev_data = _read_amounts(prev_date)

        return {"today": today_data, "prev_date": prev_date, "prev": prev_data}''',
     '''        def _read_amounts(date_str):
            fpath = _os.path.join(log_dir, "intraday_%s.jsonl" % date_str)
            if not _os.path.exists(fpath):
                return []
            by_min = {}
            with open(fpath, encoding="utf-8") as _fh:
                for line in _fh:
                    try:
                        d = _json.loads(line)
                        # 兼容 "2026-09-23 11:12:31"(timestamp) 与 "11:12:28"(time) 两种格式
                        ts = d.get("timestamp") or d.get("time") or ""
                        amt = d.get("total_amount_yi", 0)
                        if not ts or amt <= 0:
                            continue
                        minute = ts[11:16] if len(ts) >= 16 else ts[:5]
                        if len(minute) == 5 and minute[2] == ":":
                            by_min[minute] = amt
                    except Exception:
                        pass
            return [{"minute": m, "amount": by_min[m]} for m in sorted(by_min)]

        def _full_day_amount(date_str):
            """当日全市场成交额（亿元）：CSV 个股成交额求和，精确全天值"""
            try:
                import csv as _csv
                fp = _os.path.join(str(Path(__file__).parent.parent / "data" / "csv"),
                                   "stock_daily_%s.csv" % date_str)
                if not _os.path.exists(fp):
                    return 0
                total = 0.0
                with open(fp, encoding="utf-8-sig") as _fh:
                    for r in _csv.DictReader(_fh):
                        try:
                            total += float(str(r.get("成交额", 0) or 0).replace(",", ""))
                        except (ValueError, TypeError):
                            pass
                return round(total / 1e8, 1) if total > 0 else 0
            except Exception:
                return 0

        today_data = _read_amounts(today)
        prev_data = _read_amounts(prev_date)
        prev_full = _full_day_amount(prev_date) or (prev_data[-1]["amount"] if prev_data else 0)

        return {"today": today_data, "prev_date": prev_date, "prev": prev_data,
                "prev_full_day_yi": prev_full}'''),
])

# ── 前端：阶跃插值匹配 + 空数据降级 + 全天基数 ──
edit('static/js/realtime.js', [
    ('''    const todayPts = volData.today || [];
    const prevPts = volData.prev || [];
    const prevDate = volData.prev_date || '';
    if (todayPts.length < 2) { console.log('[IPO] too few points, skip'); return; }

    // 构建时间-金额映射
    const todayMap = {};
    todayPts.forEach(p => todayMap[p.minute] = p.amount);
    const prevMap = {};
    prevPts.forEach(p => prevMap[p.minute] = p.amount);

    // 按今日时间点计算百分比差值曲线（累计值对比，仅取前日有数据的点）
    const curvePoints = todayPts.filter(p => (prevMap[p.minute] || 0) > 0).map(p => {
      const prevAmt = prevMap[p.minute] || 0;
      const pct = prevAmt > 0 ? ((p.amount - prevAmt) / prevAmt * 100) : 0;
      return { minute: p.minute, amount: p.amount, prevAmt, pct };
    });''',
     '''    const todayPts = volData.today || [];
    const prevPts = volData.prev || [];
    const prevDate = volData.prev_date || '';
    if (todayPts.length < 1) { console.log('[IPO] no today points, skip'); return; }

    // 前日累计序列（分钟升序）：取"同分钟及之前最后一点"做阶跃插值
    // （旧实现要求两天采样分钟完全重合，稀疏采样下必为空 → 卡片被静默跳过）
    const prevSorted = prevPts.slice().sort((a, b) => (a.minute < b.minute ? -1 : 1));
    const prevAt = (minute) => {
      let v = 0;
      for (const p of prevSorted) {
        if (p.minute > minute) break;
        v = p.amount;
      }
      return v;
    };

    // 按今日时间点计算百分比差值曲线（前日同刻插值做基准）
    const curvePoints = todayPts.map(p => {
      const prevAmt = prevAt(p.minute);
      return prevAmt > 0 ? { minute: p.minute, amount: p.amount, prevAmt, pct: (p.amount - prevAmt) / prevAmt * 100 } : null;
    }).filter(Boolean);

    // 降级：前日完全没有可比窗口时也显示卡片（只显示实际量能），不再静默消失
    if (curvePoints.length === 0) {
      const cum0 = todayPts[todayPts.length - 1].amount || 0;
      el.insertAdjacentHTML('beforeend', `<div class="card" style="margin-bottom:16px">
        <div style="font-size:13px;font-weight:600">📊 市场量能</div>
        <div style="font-size:14px;margin-top:4px">沪深京 | 实际量能 <b>${cum0.toFixed(0)}亿</b></div>
        <div style="font-size:12px;color:var(--gray-500)">前日分钟数据不足，量能预测暂不可用</div>
      </div>`);
      return;
    }'''),

    ('''    // 预测量能：今日累计/昨日同期累计 × 昨日全天总量
    // 这样自然包含上午>下午的量能分布规律
    const prevFullDay = prevPts.length > 0 ? prevPts[prevPts.length - 1].amount : 0;''',
     '''    // 预测量能：今日累计/昨日同期累计 × 昨日全天总量
    // 这样自然包含上午>下午的量能分布规律
    // 昨日全天总量优先用后端 CSV 精确值（不受采样中断影响），否则退回最后一点
    const prevFullDay = volData.prev_full_day_yi || (prevPts.length > 0 ? prevPts[prevPts.length - 1].amount : 0);'''),
])

# ── 静态资源版本号递增 ──
edit('static/index.html', [
    ('<script src="/static/js/realtime.js?v=4"></script>',
     '<script src="/static/js/realtime.js?v=5"></script>'),
])

print('patch14 done')
