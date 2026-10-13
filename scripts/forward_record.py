"""2026Q4 前瞻封存验证 — 逐日前瞻记录（规则冻结 v2，见 FREEZE_20261007.md；2027-01 拆封）

机制：
  1. 规则冻结快照 = 本文件运行所依赖的全部规则文件 sha256 清单（FREEZE_20261007.md）
  2. 每交易日收盘后运行本脚本：按冻结口径重跑模拟（m3_trend_break3.py 配置 S_W1并集 =
     M3 v2 定稿：MA20 企稳阳低吸 + 周线 MA10 低吸并轨 / sdw 双周期破位出场 / C4），
     按日切片追加 forward_log.jsonl：M1 闸门 / 当日标记 / 当日入场 / 当日加仓 / 当日出场
  3. 拆封前禁止修改规则参数；任何修改 = 记录作废、重新起算
  4. 2027-01 拆封评估：forward_log.jsonl 全量 vs 预注册口径（FREEZE_20261007.md 第四节）

用法: python3.11 scripts/forward_record.py [YYYYMMDD]
产出: reports/m2/forward_log.jsonl（append-only，禁止编辑已有行）
"""
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "quant"))
import market_env as me  # noqa: E402

OUT = HERE.parent / "reports" / "m2"
RULESET = "M3v2"   # 企稳阳+W1 低吸 / sdw 出场 / C4（2026-10-07 定稿）


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime("%Y%m%d")
    print(f"[forward] 记录日 = {d}（规则集 {RULESET}）")

    # 重跑冻结口径模拟（配置 S_W1并集 = 定稿规则，全 PIT）→ m3_trend_break3_S_W1并集_trades.json
    subprocess.run([sys.executable, str(HERE / "m3_trend_break3.py"), "S_W1并集"],
                   check=True, cwd=str(HERE.parent))
    trades = json.load(open(OUT / "m3_trend_break3_S_W1并集_trades.json",
                            encoding="utf-8"))["S_W1并集"]

    marked = [{"code": t["code"], "p0": t["p0"], "tier": t["tier"], "leg": t["leg"],
               "entry": t["entry"], "anchor": t["anchor_dist"], "atr": t["atr_dist"]}
              for t in trades if t["p0"] == d]
    events = []
    for t in trades:
        for i, u in enumerate(t["units"]):
            if u["day"] == d:
                events.append({"type": "entry" if i == 0 else "add", "code": t["code"],
                               "p0": t["p0"], "leg": t["leg"], "px": u["px"], "units": u["u"]})
        if t["exit"] == d:
            events.append({"type": "exit", "code": t["code"], "p0": t["p0"],
                           "leg": t["leg"], "hold": t["hold"],
                           "pnl_units": t["pnl_units"], "max_units": t["max_units"]})

    rec = {"date": d, "ruleset": RULESET, "env_gate": me.env_gate(d), "marked": marked,
           "events": events, "n_trades_known": len(trades)}
    log = OUT / "forward_log.jsonl"
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[forward] 标记 {len(marked)} / 事件 {len(events)} → {log}")
    print(f"[forward] env_gate: tier={rec['env_gate'].get('tier')} "
          f"action={rec['env_gate'].get('action')}")


if __name__ == "__main__":
    main()
