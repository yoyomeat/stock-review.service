"""案例闸门尸检：9 标准案例在冻结漏斗每一关的死因定位（诊断用，非实验）"""
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

ml.DROP20_MIN, ml.VOL_PCT_MAX, ml.REBREAK_VOL_MULT = -0.08, 0.20, 1.0

CASES = [("886069", "人形机器人", "20250106"), ("886042", "存储芯片", "20250113"),
         ("886050", "AI算力", "20250113"), ("886078", "商业航天", "20250110"),
         ("885966", "跨境支付", "20250110"), ("885530", "黄金", "20250110"),
         ("886033", "CPO", "20250106"), ("885959", "PCB", "20250106"),
         ("886032", "固态电池", "20250409")]


def main():
    boards = load_boards(P.WARMUP_START, "ths_full")
    idx_dates, idx_close = load_index_close("sh000001", P.WARMUP_START)
    idx_map = {str(d).replace("-", ""): i for i, d in enumerate(idx_dates)}
    idx_list = [str(d).replace("-", "") for d in idx_dates]
    market = load_market_amount("ths881")
    sh_dates, sh_close = me.load_index("sh000001", "20220101")
    sh_pos = {str(d).replace("-", ""): i for i, d in enumerate(sh_dates)}
    sh_ret = {str(sh_dates[i]).replace("-", ""): sh_close[i] / sh_close[i - 1] - 1
              for i in range(1, len(sh_dates))}
    bmap = {bd.code: bd for bd in boards}

    for code, name, p0 in CASES:
        bd = bmap.get(code)
        if bd is None:
            print(f"--- {name} ({code}) 不在 universe ---")
            continue
        rows = []
        ml.scan_board(bd, idx_map, idx_list, idx_close, "20241201", rows)
        cands = [r for r in rows if "20241215" <= r["p0_date"] <= "20250515"]
        print(f"--- {name} ({code}) 期望P0={p0}: P0形态候选 {len(cands)} 个 ---")
        if not cands:
            if p0 in bd.dates:
                t = bd.dates.index(p0)
                d20 = bd.close[t] / bd.close[t - 20] - 1 if t >= 20 else None
                vwin = bd.volume[max(t - 59, 0):t + 1]
                vpct = (sum(1 for x in vwin if x < bd.volume[t]) / len(vwin)) if vwin else None
                print(f"    形态未触发。期望日: drop20={d20 if d20 is None else round(d20, 3)} (门槛-0.08)"
                      f" 量分位={vpct if vpct is None else round(vpct, 2)} (门槛0.20) "
                      f"收阴={bd.close[t] < bd.open[t]} 量[t+1]/量[t]按日看")
            continue
        for r in cands:
            t = bd.dates.index(r["p0_date"])
            w = slice(max(t - 19, 0), t + 1)
            mkt = [market.get(d) for d in bd.dates[w]]
            mkt = [x for x in mkt if x]
            share = sum(bd.amount[w]) / sum(mkt) * 100 if mkt and sum(mkt) > 0 else None
            amt20 = sum(bd.amount[w]) / (t + 1 - max(t - 19, 0)) / 1e8
            sp = sh_pos.get(r["p0_date"])
            f = me.features_at(sh_dates, sh_close, sp)
            nh = not (f["last_swing_high"] is not None and sh_close[sp] > f["last_swing_high"])
            pn = f["ret20"] is not None and f["ret20"] <= -0.03
            run = 0
            for k in (1, 2, 3):
                i = t + k
                if i >= len(bd.close) or i < 1:
                    break
                bret = bd.close[i] / bd.close[i - 1] - 1
                iret = sh_ret.get(bd.dates[i])
                if iret is not None and bret > iret and run == k - 1:
                    run = k
            fails = []
            if share is None or share < 1.3:
                fails.append(f"share={share:.2f}%<1.3")
            if amt20 < 100:
                fails.append(f"amt={amt20:.0f}亿<100")
            if (not nh) and (not pn):
                fails.append("闸B(创新高x非恐慌)")
            if run < 3:
                fails.append(f"run={run}<3")
            quad = ("非新高" if nh else "创新高") + "x" + ("恐慌" if pn else "非恐慌")
            verdict = "全过" if not fails else "死于: " + "; ".join(fails)
            print(f"    P0={r['p0_date']} share={share:.2f}% amt={amt20:.0f}亿 quad={quad} run={run} -> {verdict}")


if __name__ == "__main__":
    main()
