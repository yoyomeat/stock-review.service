"""诊断：V 反通道在 9 案例上的条件逐项核对（找 0/9 的原因）"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "quant" / "m2"))
from dataset import load_boards, load_index_close  # noqa: E402
import params as P  # noqa: E402

CASES = ["886069", "886042", "886050", "886078", "885966", "885530", "886033", "885959", "886032"]
WINDOWS = [("20250103", "20250120"), ("20250407", "20250430")]


def main():
    boards = {bd.code: bd for bd in load_boards(P.WARMUP_START, "ths_full")}
    for code in CASES:
        bd = boards[code]
        print(f"--- {bd.name} ({code}) ---")
        for lo, hi in WINDOWS:
            for t in range(250, len(bd.close)):
                d = bd.dates[t]
                if not (lo <= d <= hi):
                    continue
                d20 = bd.close[t] / bd.close[t - 20] - 1
                rev = (bd.close[t] - bd.low[t]) / bd.low[t] if bd.low[t] > 0 else 0
                v20 = sum(bd.volume[t - 19:t + 1]) / 20
                vr = bd.volume[t] / v20 if v20 > 0 else 0
                c1 = d20 <= -0.08
                c2 = bd.close[t] > bd.open[t] and bd.close[t] > bd.close[t - 1]
                c3 = rev >= 0.04
                c4 = vr >= 1.2
                flag = "V-FIRE" if (c1 and c2 and c3 and c4) else ""
                print(f"  {d} d20={d20:+.2f}{'✓' if c1 else '✗'} rev={rev:.2%}{'✓' if c3 else '✗'} "
                      f"量比={vr:.2f}{'✓' if c4 else '✗'} 收阳反转={'✓' if c2 else '✗'} {flag}")


if __name__ == "__main__":
    main()
