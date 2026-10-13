"""三问验证（只用 T 日及之前数据）:
  1) 案例中普遍最先出现的三个信号是哪三个（按触发天数聚合 + 进入最早3名次数）
  2) 三个信号都亮的那天（=第三个信号日），价格位置是否相对低位
  3) 站上55日线 / MA5金叉MA13 / 强于指数 —— 三个指标的触发天数与有效性
用法: python3.11 scripts/m2_case_signals2.py
产出: reports/m2/case_study/launch_signals2.json + stdout
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m2_case_emergence import load, CASES  # noqa: E402
from m2_case_signals import signal_days  # noqa: E402
from dataset import load_index_close  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "reports" / "m2" / "case_study"
IDX = "sh000001"        # 上证指数（强于指数对照）
WINDOW = 15


def trailing_pos(c, i, m):
    win = c[max(0, i - m + 1): i + 1]
    lo, hi = min(win), max(win)
    return (c[i] - lo) / (hi - lo) * 100 if hi > lo else 50.0


def main():
    idx_dates, idx_close = load_index_close(IDX, "20230101")
    idx_dates = [str(x).replace("-", "") for x in idx_dates]
    idx_pos = {d: i for i, d in enumerate(idx_dates)}

    def idx_ref_pos(d):
        """板指日期 d 对应的指数 bar 位置（≤d 的最近一根）"""
        i = idx_pos.get(d)
        if i is not None:
            return i
        lo = 0
        for k, dd in enumerate(idx_dates):
            if dd <= d:
                lo = k
            else:
                break
        return lo

    # ── 逐案例信号 ──
    cases = []
    for code, name, cls, p0s in CASES:
        p0s = p0s.replace("-", "")
        d = load(code)
        i0 = d["idx"][p0s]
        fire = signal_days(code, name, cls, p0s)["fire"]
        cases.append({"code": code, "name": name, "cls": cls, "p0": p0s, "i0": i0, "d": d, "fire": fire})

    # ── 问1：最先出现的三个信号 ──
    sig_names = list(cases[0]["fire"].keys())
    agg = {}
    for s in sig_names:
        days = [c["fire"][s] for c in cases]
        fired = [x for x in days if x is not None]
        agg[s] = {"mean": round(sum(fired) / len(fired), 2) if fired else None,
                  "median": sorted(fired)[len(fired) // 2] if fired else None,
                  "cover": f"{len(fired)}/{len(days)}", "_days": days}
    # 每个案例取最早3个信号，统计"进入最早3名"次数
    top3_cnt = {s: 0 for s in sig_names}
    for c in cases:
        order = sorted([s for s in sig_names if c["fire"][s] is not None], key=lambda s: c["fire"][s])
        for s in order[:3]:
            top3_cnt[s] += 1
    for s in sig_names:
        agg[s]["top3"] = top3_cnt[s]

    ranked = sorted(sig_names, key=lambda s: (agg[s]["mean"] if agg[s]["mean"] is not None else 99))
    print("== 问1 信号触发速度排行（mean/median = P0 后第几日，top3 = 进入该案例最早3名的次数）==")
    for s in ranked:
        a = agg[s]
        print(f"  {s:<26} mean={a['mean']:<5} median={a['median']:<4} cover={a['cover']:<5} top3={a['top3']}/8  days={a['_days']}")

    trio = sorted(sig_names,
                  key=lambda s: (-(top3_cnt[s]), agg[s]["mean"] if agg[s]["mean"] is not None else 99))[:3]
    print(f"\n== 普遍最先的三个信号: {trio}")

    # ── 问2 + 问3 ──
    rows = []
    for c in cases:
        d, i0 = c["d"], c["i0"]
        n = len(d["close"])
        fire = c["fire"]
        fired_sorted = sorted([(v, s) for s, v in fire.items() if v is not None])
        trio_case = [s for _, s in fired_sorted[:3]]
        day3 = fired_sorted[2][0] if len(fired_sorted) >= 3 else None
        i3 = i0 + day3 if day3 is not None else None

        # 问3 三个指标
        ma55 = [None if i < 54 else sum(d["close"][i - 54:i + 1]) / 55 for i in range(n)]
        ma5, ma13 = d["ma5"], [None if i < 12 else sum(d["close"][i - 12:i + 1]) / 13 for i in range(n)]

        def first(cond):
            for k in range(0, WINDOW + 1):
                i = i0 + k
                if i >= n or i < 1 or ma55[i] is None:
                    break
                if cond(i):
                    return k
            return None

        f55 = first(lambda i: d["close"][i] > ma55[i] and d["close"][i - 1] <= ma55[i - 1])
        f_x = first(lambda i: ma5[i] > ma13[i] and ma5[i - 1] <= ma13[i - 1])

        def rel20(i):
            p = idx_ref_pos(d["dates"][i])
            if p < 20 or i < 20:
                return None
            b = d["close"][i] / d["close"][i - 20] - 1
            x = idx_close[p] / idx_close[p - 20] - 1
            return b - x

        f_rel = first(lambda i: rel20(i) is not None and rel20(i) > 0)
        # RS(板/指) 创20日新高
        rs = []
        for i in range(n):
            p = idx_ref_pos(d["dates"][i])
            rs.append(d["close"][i] / idx_close[p])
        f_rs = first(lambda i: rs[i] > max(rs[i - 20:i]))

        row = {
            "name": c["name"], "cls": c["cls"],
            "trio_case": trio_case,
            "day3": day3,
        }
        if i3 is not None:
            c3 = d["close"][i3]
            row.update({
                "pos250_at3": round(trailing_pos(d["close"], i3, 250), 1),
                "pos60_at3": round(trailing_pos(d["close"], i3, 60), 1),
                "ret_from_p0": round((c3 / d["close"][i0] - 1) * 100, 1),
                "dev_ma20": round((c3 / (sum(d["close"][i3 - 19:i3 + 1]) / 20) - 1) * 100, 1),
                "dev_ma55": round((c3 / ma55[i3] - 1) * 100, 1),
                "rel20_at3": round(rel20(i3) * 100, 1) if rel20(i3) is not None else None,
            })
        row.update({"fire_ma55": f55, "fire_ma5x13": f_x, "fire_rel20": f_rel, "fire_rs20high": f_rs})
        rows.append(row)

    print("\n== 问2 第三个信号日的价格位置 + 问3 三指标触发天数 ==")
    hdr = (f"{'板块':<10}{'类':<3}{'第3信号日':>9}{'250分位':>8}{'60分位':>7}{'距P0':>7}"
           f"{'MA20偏离':>9}{'MA55偏离':>9}{'强指20':>7}"
           f"{'上55日线':>9}{'5叉13':>7}{'强于指数':>9}{'RS新高':>7}")
    print(hdr)
    for r in rows:
        def g(k, w=8, fmt="{:.1f}"):
            v = r.get(k)
            return (fmt.format(v) if isinstance(v, (int, float)) else str(v)).rjust(w)
        print(f"{r['name']:<10}{r['cls']:<3}{str(r['day3']):>9}"
              f"{g('pos250_at3')}{g('pos60_at3',7)}{g('ret_from_p0',7)}"
              f"{g('dev_ma20',9)}{g('dev_ma55',9)}{g('rel20_at3',7)}"
              f"{str(r['fire_ma55']):>9}{str(r['fire_ma5x13']):>7}{str(r['fire_rel20']):>9}{str(r['fire_rs20high']):>7}")
    print("\n各案例自身最早触发的三个信号（问2 的‘第三个信号’即取自这些）:")
    for r in rows:
        print(f"  {r['name']:<10} {r['trio_case']}")

    (OUT / "launch_signals2.json").write_text(
        json.dumps({"agg": {k: {kk: vv for kk, vv in v.items() if kk != "_days"} for k, v in agg.items()},
                    "trio": trio, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[written] {OUT}/launch_signals2.json")


if __name__ == "__main__":
    main()
