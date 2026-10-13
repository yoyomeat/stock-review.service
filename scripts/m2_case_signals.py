"""启动确认信号面板 — 启动期(P0 后 15 日内)各维度技术信号的触发天数与覆盖率

信号全部为 T 日收盘可算的实时事件（上穿/金叉/突破/新高），无未来视角。
用法: python3.11 scripts/m2_case_signals.py
产出: reports/m2/case_study/launch_signals.json + stdout 矩阵
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m2_case_emergence import load, CASES, _ema  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "reports" / "m2" / "case_study"
WINDOW = 15


def first_fire(cond, i0, n):
    """返回窗口 [i0, i0+WINDOW] 内条件首次成立的相对天数，未触发返回 None。"""
    for k in range(0, WINDOW + 1):
        i = i0 + k
        if i >= n or i < 1:
            break
        if cond(i):
            return k
    return None


def signal_days(code, name, cls, p0s):
    p0s = p0s.replace("-", "")
    d = load(code)
    i0 = d["idx"].get(p0s)
    if i0 is None:
        return {"name": name, "error": f"date not found {p0s}"}
    c, o, v = d["close"], d["open"], d["vol"]
    n = len(c)
    ma5, ma10, ma20 = d["ma5"], d["ma10"], d["ma20"]
    e12, e26 = _ema(c, 12), _ema(c, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = _ema(dif, 9)
    hist = [(a - b) * 2 for a, b in zip(dif, dea)]
    rsi = d["rsi"]
    # KDJ
    k_v = d_v = 50.0
    ks, ds = [], []
    for i in range(n):
        lo_ = min(d["low"][max(0, i - 8):i + 1])
        hi_ = max(d["high"][max(0, i - 8):i + 1])
        rsv = (c[i] - lo_) / (hi_ - lo_) * 100 if hi_ > lo_ else 50.0
        k_v = 2 / 3 * k_v + 1 / 3 * rsv
        d_v = 2 / 3 * d_v + 1 / 3 * k_v
        ks.append(k_v)
        ds.append(d_v)

    def pvol(i, m):
        return sum(v[i - m:i]) / m if i - m >= 0 else None

    def pmax(i, m):
        return max(c[i - m:i]) if i - m >= 0 else None

    sigs = {
        # 涨幅/空间
        "涨幅·创20日收盘新高": lambda i: pmax(i, 20) is not None and c[i] > pmax(i, 20),
        "涨幅·5日涨幅≥5%": lambda i: i >= 5 and c[i] / c[i - 5] - 1 >= 0.05,
        "空间·收盘上穿MA20": lambda i: c[i] > ma20[i] and c[i - 1] <= ma20[i - 1],
        # 均线
        "均线·MA5上穿MA20": lambda i: ma5[i] > ma20[i] and ma5[i - 1] <= ma20[i - 1],
        "均线·MA20连续回升3日": lambda i: ma20[i] > ma20[i - 1] > ma20[i - 2] > ma20[i - 3],
        "均线·多头排列(MA5>10>20)": lambda i: ma5[i] > ma10[i] > ma20[i] and not (ma5[i - 1] > ma10[i - 1] > ma20[i - 1]),
        # 技术指标
        "指标·MACD金叉(DIF上穿DEA)": lambda i: dif[i] > dea[i] and dif[i - 1] <= dea[i - 1],
        "指标·MACD柱连续回升3日": lambda i: hist[i] > hist[i - 1] > hist[i - 2] > hist[i - 3],
        "指标·RSI14上穿50": lambda i: rsi[i] > 50 and rsi[i - 1] <= 50,
        "指标·KDJ金叉(K上穿D)": lambda i: ks[i] > ds[i] and ks[i - 1] <= ds[i - 1],
        # 量价
        "量价·放量阳线(量比≥1.2)": lambda i: (c[i] > o[i] and pvol(i, 5) and v[i] >= 1.2 * pvol(i, 5)),
        "量价·单日量>20日均量": lambda i: pvol(i, 20) is not None and v[i] > pvol(i, 20),
        # 形态
        "形态·连续3根阳线": lambda i: all(c[i - j] > o[i - j] for j in range(3)),
    }

    out = {"name": name, "code": code, "cls": cls, "p0": p0s, "fire": {}}
    for sname, cond in sigs.items():
        out["fire"][sname] = first_fire(cond, i0, n)
    return out


def main():
    res = [signal_days(*case) for case in CASES]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "launch_signals.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    names = [r["name"] for r in res]
    sig_names = list(res[0]["fire"].keys())
    hdr = f"{'信号':<28}" + "".join(f"{nm:>8}" for nm in names) + f"{'覆盖':>7}{'中位':>5}"
    print(hdr)
    for s in sig_names:
        days = [r["fire"].get(s) for r in res]
        fired = [x for x in days if x is not None]
        med = sorted(fired)[len(fired) // 2] if fired else "-"
        row = f"{s:<28}" + "".join(f"{('·' if x is None else x):>8}" for x in days)
        print(row + f"{f'{len(fired)}/{len(days)}':>7}{med:>5}")
    print(f"\n[written] {OUT}/launch_signals.json")


if __name__ == "__main__":
    main()
