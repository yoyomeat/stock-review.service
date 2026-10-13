"""P0 前后逐日成交量画像 — 量能共性只看均值会被抹平，逐日摊开检验
用法: python3.11 scripts/m2_case_vol.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m2_case_emergence import load, CASES  # noqa: E402

def main():
    print(f"{'板块':<10}{'类':<3}" + "".join(f"{k:>6}" for k in range(-10, 11))
          + f"{'峰日':>5}{'峰值':>6}{'P0分位':>7}{'恐慌段':>7}{'后段':>6}")
    for code, name, cls, p0s in CASES:
        p0s = p0s.replace("-", "")
        d = load(code)
        i0 = d["idx"][p0s]
        v = d["vol"]
        base = sum(v[i0 - 60:i0 - 20]) / 40          # 正常基准：P0 前 60~20 日均量
        ratios = {k: v[i0 + k] / base for k in range(-10, 11)}
        peak_k = max(range(-15, 16), key=lambda k: v[i0 + k])
        peak_r = v[i0 + peak_k] / base
        win = v[i0 - 60:i0 + 6]
        p0_pct = sum(1 for x in win if x < v[i0]) / len(win) * 100
        panic = sum(v[i0 - 5:i0 + 1]) / 6 / base     # 恐慌末段（P0 前5日~P0当日）
        post = sum(v[i0 + 6:i0 + 11]) / 5 / base     # 启动后段（P0+6~+10）
        row = f"{name:<10}{cls:<3}" + "".join(f"{ratios[k]:>6.2f}" for k in range(-10, 11))
        print(row + f"{peak_k:>5}{peak_r:>6.2f}{p0_pct:>7.0f}{panic:>7.2f}{post:>6.2f}")


if __name__ == "__main__":
    main()
