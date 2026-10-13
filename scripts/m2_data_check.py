"""M2 数据层质量审计 — ths884 / ths881 / ths_concept 三口径体检

检查项（每口径）:
  1. 板块数、日期范围、行数分布
  2. 交易日缺口（对照 index_daily 全日历，按板块首末日之间计缺失）
  3. 停更板块（末日 < 全局最新交易日）
  4. 重复 (code,date)、空值/零额行
  5. 成分覆盖（有成分的板块数、成分数中位）
  6. warmup 深度：事件期 20250102 前是否有 >=250 个交易日（250日窗需求）
  7. 全市场成交额层（ths881）日覆盖

产出: reports/m2/m2_data_check.json + stdout 摘要
"""
import json
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "quant" / "m2"))

from dataset import DB, UNIVERSES, _load_members, _norm_date  # noqa: E402

OUT = BASE / "reports" / "m2" / "m2_data_check.json"
EVENT_START = "20250102"
MIN_WARMUP_DAYS = 250


def _q(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def main():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ref_days = [_norm_date(r[0]) for r in con.execute(
        "SELECT trade_date FROM index_daily WHERE code='sh000001' ORDER BY 1")]
    ref_set = set(ref_days)
    ref_max = ref_days[-1]
    warmup_ref = [d for d in ref_days if d < EVENT_START]  # 事件期前的交易日

    report = {"ref_calendar_days": len(ref_days), "ref_max_date": ref_max,
              "event_start": EVENT_START, "universes": {}}

    for uni, (table, prefix, member_src) in UNIVERSES.items():
        if uni == "eastmoney":
            continue  # 旧口径仅供历史对比，不审计
        members = _load_members(member_src)
        where = f"code LIKE '{prefix}%'" if prefix else "category='industry'"
        rows = con.execute(
            f"SELECT code, replace(trade_date,'-',''), amount FROM {table} WHERE {where}").fetchall()
        per = {}
        dup = 0
        seen = set()
        bad_amount = 0
        for code, d, amt in rows:
            d = _norm_date(d)
            key = (code, d)
            if key in seen:
                dup += 1
            seen.add(key)
            if amt is None or amt <= 0:
                bad_amount += 1
            per.setdefault(code, []).append(d)

        rows_cnt, gaps, stale, warmup_ok = [], [], 0, 0
        first_last = {}
        for code, ds in per.items():
            ds = sorted(set(ds))
            first_last[code] = (ds[0], ds[-1])
            rows_cnt.append(len(ds))
            ds_set = set(ds)
            missing = sum(1 for d in ref_days if ds[0] <= d <= ds[-1] and d not in ds_set)
            gaps.append(missing)
            if ds[-1] < ref_max:
                stale += 1
            # warmup: 板块在事件期前的可用交易日数（含自身起点约束）
            avail = sum(1 for d in warmup_ref if d >= ds[0])
            if avail >= MIN_WARMUP_DAYS:
                warmup_ok += 1

        mem_cnt = [len(members.get(c, [])) for c in per]
        with_mem = sum(1 for x in mem_cnt if x > 0)
        report["universes"][uni] = {
            "table": table,
            "n_boards": len(per),
            "date_range": [min(v[0] for v in first_last.values()),
                           max(v[1] for v in first_last.values())],
            "rows_per_board": {"p10": _q(rows_cnt, .1), "p50": _q(rows_cnt, .5),
                               "p90": _q(rows_cnt, .9), "min": min(rows_cnt), "max": max(rows_cnt)},
            "gaps_missing_days": {"total": sum(gaps), "boards_with_gap": sum(1 for g in gaps if g > 0),
                                  "p50": _q(gaps, .5), "p90": _q(gaps, .9), "max": max(gaps)},
            "stale_boards": stale,
            "dup_rows": dup,
            "bad_amount_rows": bad_amount,
            "members": {"boards_with_members": with_mem, "p50_count": _q(mem_cnt, .5)},
            "warmup_ready_250d_before_event_start": warmup_ok,
        }

    # 合并口径摘要（2026-10-01 拍板主口径 ths_full = 概念+行业全量）
    merged = [u for u in ("ths_concept", "ths884", "ths881") if u in report["universes"]]
    report["merged_universe"] = {
        "name": "ths_full",
        "groups": {u: report["universes"][u]["n_boards"] for u in merged},
        "n_boards": sum(report["universes"][u]["n_boards"] for u in merged),
        "warmup_ready": sum(report["universes"][u]["warmup_ready_250d_before_event_start"] for u in merged),
        "note": "881 一级与 884 三级同分类不同粒度（覆盖重叠），相关性由下游聚类 SE 处理",
    }

    # 全市场成交额层覆盖
    amt_days = set(_norm_date(r[0]) for r in con.execute(
        "SELECT trade_date FROM ths_industry_daily WHERE code LIKE '881%'"))
    report["market_amount_layer"] = {
        "days": len(amt_days),
        "missing_vs_calendar": sum(1 for d in ref_days if d not in amt_days),
    }
    con.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
