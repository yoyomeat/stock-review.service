"""远端补丁：params.py 单源收口 + E1 等待参数（2026-09-30）"""
import re

BASE = "/opt/stock-review/"

# ── params.py ──
p = BASE + "quant/m2/params.py"
s = open(p, encoding="utf-8").read()

old1 = "TURNOVER_SHARE_20D_MIN = 0.01    # calibrate, 区间 [0.007, 0.015]"
new1 = ("TURNOVER_SHARE_20D_MIN = 0.005   # 2026-09-29 c+ 拍板 0.5%（1% 在细分口径下仅 21 板块通过）\n"
        "                                # calibrate, 区间 [0.003, 0.01]；调用点不再各自硬编码")
assert s.count(old1) == 1, "params share 锚点"
s = s.replace(old1, new1)

old2 = "EVENT_EXPIRY_DAYS = 20           # frozen, Q6"
new2 = ("EVENT_EXPIRY_DAYS = 20           # frozen, Q6\n"
        "E1_WAIT_MAX_DAYS = 60            # calibrate, 2026-09-30 新增：E1 等待上限，超时候选作废并记录（不静默）")
assert s.count(old2) == 1, "params E1 锚点"
s = s.replace(old2, new2)
open(p, "w", encoding="utf-8").write(s)
print("params.py OK")

# ── 调用点收口（share_min=0.005 字面量 → 参数默认值）──
for rel, n in (("quant/m2/pipeline.py", 2), ("quant/m2/k_calib.py", 1), ("quant/m2/rev_surgery.py", 2)):
    fp = BASE + rel
    s = open(fp, encoding="utf-8").read()
    c = s.count(", share_min=0.005") + s.count("share_min=0.005,")
    s = s.replace(", share_min=0.005", "").replace("share_min=0.005,", "")
    open(fp, "w", encoding="utf-8").write(s)
    print(rel, "removed", c, "literals (expected", n, ")")
