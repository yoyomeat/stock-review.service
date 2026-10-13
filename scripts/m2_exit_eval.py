"""实验 #19 — 交易口径评估：止损出场 + 持有 20/40/60 日让利润跑（对齐用户风格）

用户口径（2026-10-02）：只追求高确定性；持仓至少 20 个交易日以上（中期趋势）。
出场规则 v0：收盘破 P0 低点（止损锚）→ 次日开盘离场；否则持有至 H 日收盘。
对照：固定持有 20 日无止损（旧口径）。
集合：份额≥1.3% × 市场闸 B（排除创新高×非恐慌）× run≥2（P0 后连续 2 日强于指数，T+3 开盘入场）
     vs 仅闸 B（T+2 开盘入场）。
用法: python3.11 scripts/m2_exit_eval.py
产出: reports/m2/m2_exit_eval.json + stdout
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "quant" / "m2"))
sys.path.insert(0, str(HERE.parent / "quant"))
import m2_launch_test as ml  # noqa: E402
import params as P  # noqa: E402
import market_env as me  # noqa: E402
from dataset import load_boards, load_index_close, load_market_amount  # noqa: E402

OUT = HERE.parent / "reports" / "m2" / "m2_exit_eval.json"
HORIZONS = (20, 40, 60)


def trade(bd, t, e, H, use_stop=True):
    """入场 e（开仓用 open[e]），止损=收盘 < low[t]（P0 低点）次日开盘出，否则持有至 e+H-1 收盘。
    返回 (收益率, 持有天数, 是否止损)。"""
    n = len(bd.close)
    entry = bd.open[e]
    if entry is None or entry <= 0:
        return None
    stop = bd.low[t]
    i = e
    end = min(e + H - 1, n - 1)
    while i <= end:
        if use_stop and i > e and bd.close[i] < stop:
            ex = min(i + 1, n - 1)
            return (round(bd.open[ex] / entry - 1, 4), ex - e + 1, True)
        i += 1
    return (round(bd.close[end] / entry - 1, 4), end - e + 1, False)


def _report(trades):
    if not trades:
        return {"n": 0}
    rets = [x[0] for x in trades]
    wins = [x for x in rets if x > 0]
    losses = [x for x in rets if x <= 0]
    s = sorted(rets)
    n = len(s)
    return {
        "n": n,
        "win": round(len(wins) / n, 3),
        "mean": round(sum(rets) / n, 4),
        "median": round(s[n // 2], 4),
        "avg_win": round(sum(wins) / len(wins), 4) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 4) if losses else None,
        "pl_ratio": round(abs(sum(wins) / len(wins)) / abs(sum(losses) / len(losses)), 2) if wins and losses else None,
        "expectancy": round(sum(rets) / n, 4),
        "stop_rate": round(sum(1 for x in trades if x[2]) / n, 3),
        "avg_hold": round(sum(x[1] for x in trades) / n, 1),
    }


def main():
    ml.REBREAK_VOL_MULT = 1.0
    boards = load_boards(P.WARMUP_START, "ths_full")
    idx_dates, idx_close = load_index_close("sh000001", P.WARMUP_START)
    idx_map = {str(d).replace("-", ""): i for i, d in enumerate(idx_dates)}
    idx_list = [str(d).replace("-", "") for d in idx_dates]
    market = load_market_amount("ths881")
    sh_dates, sh_close = me.load_index("sh000001", "20220101")
    sh_pos = {str(d).replace("-", ""): i for i, d in enumerate(sh_dates)}
    sh_ret = {str(sh_dates[i]).replace("-", ""): sh_close[i] / sh_close[i - 1] - 1
              for i in range(1, len(sh_dates))}

    rows = []
    for bd in boards:
        ml.scan_board(bd, idx_map, idx_list, idx_close, P.EVENT_START, rows)
    rows = [r for r in rows if r.get("v1_ret20") is not None]
    bmap = {bd.code: bd for bd in boards}

    for r in rows:
        bd = bmap[r["code"]]
        t = bd.dates.index(r["p0_date"])
        w = slice(max(t - 19, 0), t + 1)
        mkt = [market.get(d) for d in bd.dates[w]]
        mkt = [x for x in mkt if x]
        r["share"] = sum(bd.amount[w]) / sum(mkt) * 100 if mkt and sum(mkt) > 0 else None
        sp = sh_pos.get(r["p0_date"])
        f = me.features_at(sh_dates, sh_close, sp)
        nh = not (f["last_swing_high"] is not None and sh_close[sp] > f["last_swing_high"])
        pn = f["ret20"] is not None and f["ret20"] <= -0.03
        r["gateB"] = not ((not nh) and (not pn))
        run = 0
        for k in (1, 2, 3):
            i = t + k
            if i >= len(bd.close) or i < 1:
                break
            bret = bd.close[i] / bd.close[i - 1] - 1
            iret = sh_ret.get(bd.dates[i])
            if iret is not None and bret > iret and run == k - 1:
                run = k
        r["run"] = run
        r["_bd"] = bd
        r["_t"] = t

    def eval_set(name, sel, entry_off):
        print(f"\n########## {name} (n_signals={len(sel)}) ##########")
        out = {}
        for H in HORIZONS:
            for use_stop in (False, True):
                trades = []
                for r in sel:
                    bd, t = r["_bd"], r["_t"]
                    tr = trade(bd, t, t + entry_off, H, use_stop)
                    if tr:
                        trades.append(tr)
                rep = _report(trades)
                tag = f"H{H}_{'止损' if use_stop else '不止损'}"
                out[tag] = rep
                print(f"  {tag:<12} n={rep['n']:<4} win={rep.get('win')} mean={rep.get('mean')} med={rep.get('median')} "
                      f"盈亏比={rep.get('pl_ratio')} 止损率={rep.get('stop_rate')} 平均持仓={rep.get('avg_hold')}天")
        return out

    result = {}
    base = [r for r in rows if r["share"] is not None and r["share"] >= 1.3 and r["gateB"]]
    result["gateB_only_T2"] = eval_set("闸B 全信号（T+2 开盘入场）", base, 2)
    sel2 = [r for r in base if r["run"] >= 2]
    result["gateB_run2_T3"] = eval_set("闸B + run≥2（T+3 开盘入场，高确定性版）", sel2, 3)

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
