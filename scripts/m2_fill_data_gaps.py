"""M2 数据层补缺 — 同花顺 API 补齐两处缺漏（2026-09-30）

补缺项:
  1. 概念成分刷新: get_ths_index_constituents 逐板块拉取 390 个 THS 概念，
     更新 data/stock_concept_map.json（合并式：仅更新拉到的概念，其余保留；
     stock_to_concepts 全量重建去重）。备份原文件 .bak_20260930。
  2. K 线缺口回补: 对照 index_daily 交易日历，找出 ths_industry_daily /
     concept_daily 的板块内部缺日 + 坏行（amount<=0 或空），按缺口窗口
     get_ths_index_historical 回补（INSERT OR REPLACE，纯补空位）。

严格低频: 沿用 ths_api 内部 0.5s 限流 + 本脚本 0.8s 间隔 ≈ 1.3s/请求。
"""
import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path("/opt/stock-review")
sys.path.insert(0, str(BASE / "quant"))
import ths_api  # noqa: E402

DB = BASE / "data" / "wave_analysis.db"
MAP_JSON = BASE / "data" / "stock_concept_map.json"
EXTRA_SLEEP = 0.8

DAILY_TABLES = {"industry": "ths_industry_daily", "concept": "concept_daily"}


def norm_date(ms):
    return datetime.fromtimestamp(ms / 1000).strftime("%Y%m%d")


# ══════════════ 1. 概念成分刷新 ══════════════
def refresh_concept_members():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    names = dict(con.execute("SELECT code, name FROM concept_names WHERE code LIKE '885%' OR code LIKE '886%'"))
    con.close()
    # 只刷 concept_daily 里实际有K线的概念
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    have = set(r[0] for r in con.execute("SELECT DISTINCT code FROM concept_daily"))
    con.close()
    targets = [(c, n) for c, n in sorted(names.items()) if c in have]
    print(f"[成分] 目标概念 {len(targets)} 个")

    backup = MAP_JSON.with_suffix(".json.bak_20260930")
    if not backup.exists():
        backup.write_bytes(MAP_JSON.read_bytes())
        print(f"[成分] 原文件已备份 → {backup.name}")
    m = json.loads(MAP_JSON.read_text(encoding="utf-8"))
    c2s = m.setdefault("concept_to_stocks", {})

    ok = fail = 0
    for i, (code, name) in enumerate(targets):
        time.sleep(EXTRA_SLEEP)
        try:
            cons = ths_api.get_ths_index_constituents(code + ".TI")
        except Exception as e:
            print(f"[成分] {code} {name} 异常: {e}")
            fail += 1
            continue
        if not cons:
            print(f"[成分] {code} {name} 空/失败")
            fail += 1
            continue
        c2s[name] = [{"code": x.get("ticker") or (x.get("thscode") or "").split(".")[0],
                      "name": x.get("name", "")} for x in cons]
        ok += 1
        if (i + 1) % 30 == 0:
            print(f"[成分] {i + 1}/{len(targets)} 完成（成功 {ok} 失败 {fail}）")

    # 全量重建 stock_to_concepts（去重）
    s2c = {}
    for cname, stocks in c2s.items():
        for s in stocks:
            t = s["code"] if isinstance(s, dict) else str(s)
            sname = s.get("name", "") if isinstance(s, dict) else ""
            e = s2c.setdefault(t, {"name": sname, "concepts": []})
            if cname not in e["concepts"]:
                e["concepts"].append(cname)
            if sname and not e["name"]:
                e["name"] = sname
    m["stock_to_concepts"] = s2c
    total_links = sum(len(v) for v in c2s.values())
    m["meta"] = {
        "source": "同花顺 THS",
        "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stock_count": len(s2c),
        "stock_with_concepts": len(s2c),
        "concept_count": len(c2s),
        "total_links": total_links,
        "error_count": fail,
    }
    MAP_JSON.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    print(f"[成分] 完成: 成功 {ok} 失败 {fail}，概念 {len(c2s)} 个股 {len(s2c)} 关联 {total_links}")
    return ok, fail


# ══════════════ 2. K 线缺口回补 ══════════════
def backfill_gaps():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cal = [r[0].replace("-", "")[:8] for r in con.execute(
        "SELECT trade_date FROM index_daily WHERE code='sh000001' ORDER BY 1")]
    cal_set = set(cal)
    con.close()

    wr = sqlite3.connect(DB)
    total_fixed = 0
    for kind, table in DAILY_TABLES.items():
        rows = wr.execute(f"SELECT code, replace(trade_date,'-',''), amount FROM {table}").fetchall()
        per = {}
        bad = []
        for code, d, amt in rows:
            d = d.replace("-", "")[:8]
            per.setdefault(code, set()).add(d)
            if amt is None or amt <= 0:
                bad.append((code, d))
        # 内部缺口（首末日之间缺交易日）+ 坏行日
        need = {}
        for code, ds in per.items():
            ds_list = sorted(ds)
            miss = [d for d in cal if ds_list[0] <= d <= ds_list[-1] and d not in ds]
            for d in miss:
                need.setdefault(code, set()).add(d)
        for code, d in bad:
            need.setdefault(code, set()).add(d)
        n_days = sum(len(v) for v in need.values())
        print(f"[K线] {kind}: {len(need)} 个板块共 {n_days} 个待补日（含 {len(bad)} 个坏行日）")

        for code, days in sorted(need.items()):
            ds = sorted(days)
            # 合并连续窗口
            win_s, win_e, wins = ds[0], ds[0], []
            for d in ds[1:]:
                if cal.index(d) - cal.index(win_e) <= 3:   # 3 个交易日内的空档并窗
                    win_e = d
                else:
                    wins.append((win_s, win_e))
                    win_s = win_e = d
            wins.append((win_s, win_e))
            for s, e in wins:
                time.sleep(EXTRA_SLEEP)
                s_dt = datetime.strptime(s, "%Y%m%d") - timedelta(days=2)
                e_dt = datetime.strptime(e, "%Y%m%d") + timedelta(days=2)
                hist = ths_api.get_ths_index_historical(
                    code + ".TI", int(s_dt.timestamp() * 1000), int(e_dt.timestamp() * 1000))
                if not hist:
                    print(f"[K线] {code} 窗口 {s}~{e} 拉取失败")
                    continue
                prev_close = None
                n_ins = 0
                for it in sorted(hist, key=lambda x: x["date_ms"]):
                    d = norm_date(it["date_ms"])
                    if d not in cal_set:
                        continue
                    c = it.get("close_price")
                    o = it.get("open_price")
                    if c is None or o is None:
                        continue
                    pct = round((c - prev_close) / prev_close * 100, 2) if prev_close else 0.0
                    prev_close = c
                    wr.execute(f"INSERT OR REPLACE INTO {table} VALUES (?,?,?,?,?,?,?,?,?)",
                               (code, d, o, it.get("high_price"), it.get("low_price"), c,
                                pct, it.get("volume", 0), it.get("turnover", 0)))
                    n_ins += 1
                wr.commit()
                total_fixed += n_ins
                print(f"[K线] {code} {s}~{e} 补 {n_ins} 行")
    wr.close()
    print(f"[K线] 合计补/修 {total_fixed} 行")
    return total_fixed


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("all", "members"):
        refresh_concept_members()
    if mode in ("all", "gaps"):
        backfill_gaps()
