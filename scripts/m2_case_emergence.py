"""M2 案例启动点画像 — 异动出现时的可观察特征（只用 P0 当日及之后数据，无未来视角）

维度：急跌/低位(启动前) | 起飞脚(形态) | 涨幅/速度 | 量价 | 均线收复 | 指标动作
用法: python3.11 scripts/m2_case_emergence.py
产出: reports/m2/case_study/emergence_profile.json + stdout 表
"""
import json
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "quant" / "m2"))
from dataset import DB  # noqa: E402

OUT_DIR = BASE / "reports" / "m2" / "case_study"

# (code, name, cls, P0=第一波起点)
CASES = [
    ("886069", "人形机器人", "N", "2025-01-06"),
    ("886042", "存储芯片", "N", "2025-01-13"),
    ("886050", "AI算力", "N", "2025-01-13"),
    ("886078", "商业航天", "N", "2025-01-10"),
    ("885966", "跨境支付", "N", "2025-01-10"),
    ("885530", "黄金", "N", "2025-01-10"),
    ("886033", "CPO", "坑", "2025-01-06"),
    ("885959", "PCB", "坑", "2025-01-06"),
]


def _ema(vals, n):
    k = 2 / (n + 1)
    out = [vals[0]]
    for x in vals[1:]:
        out.append(out[-1] * (1 - k) + x * k)
    return out


def _rsi(closes, n=14):
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    ag = al = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        ag += max(d, 0) / n
        al += max(-d, 0) / n
    out[n] = 100 - 100 / (1 + (ag / al if al else 1e9))
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
        out[i] = 100 - 100 / (1 + (ag / al if al else 1e9))
    return out


def load(code):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT replace(trade_date,'-',''), open, high, low, close, volume "
        "FROM concept_daily WHERE code=? AND replace(trade_date,'-','')>='20230101' ORDER BY 1",
        (code,)).fetchall()
    con.close()
    rows = [r for r in rows if all(x is not None for x in r[1:6])]
    d = {"dates": [r[0] for r in rows],
         "open": [r[1] for r in rows], "high": [r[2] for r in rows],
         "low": [r[3] for r in rows], "close": [r[4] for r in rows],
         "vol": [r[5] or 0.0 for r in rows]}
    c = d["close"]
    for n in (5, 10, 20):
        d[f"ma{n}"] = [None if i < n - 1 else sum(c[i - n + 1:i + 1]) / n for i in range(len(c))]
    trs = [d["high"][0] - d["low"][0]]
    for i in range(1, len(c)):
        trs.append(max(d["high"][i] - d["low"][i],
                       abs(d["high"][i] - c[i - 1]), abs(d["low"][i] - c[i - 1])))
    d["atr20"] = [None if i < 19 else sum(trs[i - 19:i + 1]) / 20 for i in range(len(c))]
    d["rsi"] = _rsi(c)
    e12, e26 = _ema(c, 12), _ema(c, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = _ema(dif, 9)
    d["macd_hist"] = [(a - b) * 2 for a, b in zip(dif, dea)]
    d["idx"] = {r: i for i, r in enumerate(d["dates"])}
    return d


def profile(code, name, cls, p0s):
    p0s = p0s.replace("-", "")
    d = load(code)
    i0 = d["idx"].get(p0s)
    if i0 is None:
        return {"name": name, "error": f"date not found {p0s}"}
    c, h, lo, v = d["close"], d["high"], d["low"], d["vol"]
    n = len(c)
    a0 = d["atr20"][i0]
    p = {"name": name, "code": code, "cls": cls, "p0": p0s}

    # ── 启动前：急跌 / 低位 / 破前低 ──
    p["pre20_pct"] = round((c[i0] / c[i0 - 20] - 1) * 100, 1)          # 前20日跌幅
    win250 = c[max(0, i0 - 250):i0 + 1]
    p["pos250_pct"] = round(sum(1 for x in win250 if x < c[i0]) / len(win250) * 100, 1)  # 250日分位
    p["break_prev_low"] = bool(c[i0] < min(win250[:-1]))
    p["below_ma20"] = round((c[i0] / d["ma20"][i0] - 1) * 100, 1)
    p["ma20_slope20"] = round((d["ma20"][i0] / d["ma20"][i0 - 20] - 1) * 100, 2)

    # ── 形态：P0 当日起飞脚 / 实体 ──
    p["foot_p0"] = round((c[i0] - lo[i0]) / lo[i0] * 100, 1)
    p["body_p0"] = round((c[i0] - d["open"][i0]) / d["open"][i0] * 100, 1)

    # ── 涨幅 / 速度（P0 收盘起算，实时可得口径）──
    for k in (3, 5, 10, 20):
        j = min(i0 + k, n - 1)
        p[f"ret{k}"] = round((c[j] / c[i0] - 1) * 100, 1)
    p["maxday10"] = round(max(c[i0 + j] / c[i0 + j - 1] - 1 for j in range(1, 11)) * 100, 1)
    p["speed10_atr"] = round(p["ret10"] / (a0 / c[i0] * 100), 1) if a0 else None  # 10日涨幅=几个日ATR

    # ── 量价 ──
    v0 = sum(v[i0 - 20:i0]) / 20
    p["vol5_ratio"] = round((sum(v[i0:i0 + 5]) / 5) / v0, 2) if v0 else None
    p["volpeak10_ratio"] = round(max(v[i0:i0 + 10]) / v0, 2) if v0 else None

    # ── 均线收复（P0 后第几个交易日首次站上，0=P0当日）──
    for n_ma in (5, 10, 20):
        day = None
        for k in range(0, 21):
            j = i0 + k
            if j >= n or d[f"ma{n_ma}"][j] is None:
                break
            if c[j] > d[f"ma{n_ma}"][j]:
                day = k
                break
        p[f"reclaim_ma{n_ma}_day"] = day

    # ── 指标动作 ──
    p["rsi_p0"] = round(d["rsi"][i0], 1)
    p["rsi_min_pre20"] = round(min(x for x in d["rsi"][i0 - 20:i0] if x is not None), 1)
    p["rsi_d5"] = round(d["rsi"][min(i0 + 5, n - 1)] - d["rsi"][i0], 1)     # 5日RSI抬升
    mh = d["macd_hist"]
    p["macd_p0"] = round(mh[i0], 1)
    up_day = pos_day = None
    for k in range(0, 21):
        j = i0 + k
        if j >= n:
            break
        if up_day is None and mh[j] > mh[j - 1]:
            up_day = k
        if pos_day is None and mh[j] > 0:
            pos_day = k
    p["macd_up_day"] = up_day      # 柱开始回升
    p["macd_pos_day"] = pos_day    # 柱翻红
    return p


def main():
    res = [profile(*case) for case in CASES]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "emergence_profile.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    hdr = (f"{'板块':<10}{'类':<3}{'前20日':>7}{'250分位':>8}{'破前低':>6}{'P20乖离':>8}"
           f"{'起飞脚':>7}{'ret3':>6}{'ret5':>6}{'ret10':>7}{'ret20':>7}{'速10ATR':>8}"
           f"{'量5倍':>7}{'峰量':>6}{'MA5日':>6}{'MA10日':>7}{'MA20日':>7}"
           f"{'RSI':>6}{'RSI5抬':>7}{'柱回升':>7}{'柱翻红':>7}")
    print(hdr)
    for r in res:
        if "error" in r:
            print(r)
            continue
        print(f"{r['name']:<10}{r['cls']:<3}{r['pre20_pct']:>7.1f}{r['pos250_pct']:>8.1f}"
              f"{str(r['break_prev_low']):>6}{r['below_ma20']:>8.1f}"
              f"{r['foot_p0']:>7.1f}{r['ret3']:>6.1f}{r['ret5']:>6.1f}{r['ret10']:>7.1f}{r['ret20']:>7.1f}"
              f"{r['speed10_atr']:>8.1f}{r['vol5_ratio']:>7.2f}{r['volpeak10_ratio']:>6.2f}"
              f"{str(r['reclaim_ma5_day']):>6}{str(r['reclaim_ma10_day']):>7}{str(r['reclaim_ma20_day']):>7}"
              f"{r['rsi_p0']:>6.1f}{r['rsi_d5']:>7.1f}{str(r['macd_up_day']):>7}{str(r['macd_pos_day']):>7}")
    print(f"\n[written] {OUT_DIR}/emergence_profile.json")


if __name__ == "__main__":
    main()
