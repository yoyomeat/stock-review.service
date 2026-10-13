#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""趋势动量每日重算（新口径）：M1 闸门 + M2 标记 + M3 执行状态 → data/m2m3_signals.json
结论层（大盘阶段/周线阶段人话总结）→ data/m2m3_summary.json（纯展示，不参与规则）。
挂在 scripts/daily_quant_update.sh 第 5 步（16:20，复盘前完成数据准备）。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, "/opt/stock-review")

from quant import m2m3_engine as E  # noqa: E402
from quant import m2m3_summary as S  # noqa: E402

s = E.refresh()
print(f"[m2m3] asof={s['asof']} 信号={len(s['signals'])} tier={s['env'].get('tier')} "
      f"耗时={s['elapsed_s']}s → {E.CACHE}")
try:
    sm = S.build(s["asof"])
    print(f"[summary] 结论层生成：{len(sm['signals'])} 信号 / env={sm['env_summary']['headline']} "
          f"耗时={sm['elapsed_s']}s → {S.CACHE}")
except Exception as ex:
    print(f"[summary] 结论层生成失败（不影响主缓存）: {ex}")
