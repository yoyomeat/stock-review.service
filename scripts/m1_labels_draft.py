"""M1 补充划段 — 深成/创业板/科创50 历史浪型草稿（对标上证锁定框架）

原则（2026-10-02 用户拍板）：已发生的直接确定划分。三大指数与上证共享宏观骨架，
以各自 zigzag(10%) 摆动点对齐上证框架锚点日期，生成 wave_labels 草稿，
confirmed=0，note 标记 auto-draft，待用户审核锁定。

用法: python3.11 scripts/m1_labels_draft.py
"""
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "data" / "wave_analysis.db"

CODES = [("sz399001", "深证成指"), ("sz399006", "创业板指"), ("sh000688", "科创50")]

# 索引级锚点覆盖（四指数浪型同宏观骨架但顶底日期不同，以各自 zigzag 摆动点为准）
ANCHOR_OVERRIDES = {
    "sz399001": {"周线3浪顶/4浪起": "20260622", "周线4浪底/5浪起": "20260730", "日线5-1顶/5-2起": "20260817"},
    "sz399006": {"周线3浪顶/4浪起": "20260625", "周线4浪底/5浪起": "20260730", "日线5-1顶/5-2起": "20260817"},
}

# 上证锁定框架锚点: (类型, 日期, 用途) — 日期为上证对应摆动点日期
ANCHORS = [
    ("bottom", "20240205", "周线1浪起"),
    ("top",    "20241008", "周线1浪顶/2浪起"),
    ("bottom", "20250407", "周线2浪底/3浪起"),
    ("top",    "20260514", "周线3浪顶/4浪起"),
    ("bottom", "20260720", "周线4浪底/5浪起"),
    ("top",    "20260901", "日线5-1顶/5-2起"),
]


def zigzag(closes, threshold=0.10):
    pivots = []
    n = len(closes)
    last_extreme, direction = 0, 0
    for i in range(1, n):
        if direction == 0:
            if closes[i] > closes[last_extreme] * (1 + threshold):
                pivots.append((last_extreme, closes[last_extreme], "bottom"))
                last_extreme, direction = i, 1
            elif closes[i] < closes[last_extreme] * (1 - threshold):
                pivots.append((last_extreme, closes[last_extreme], "top"))
                last_extreme, direction = i, -1
        elif direction == 1:
            if closes[i] > closes[last_extreme]:
                last_extreme = i
            elif closes[i] < closes[last_extreme] * (1 - threshold):
                pivots.append((last_extreme, closes[last_extreme], "top"))
                last_extreme, direction = i, -1
        else:
            if closes[i] < closes[last_extreme]:
                last_extreme = i
            elif closes[i] > closes[last_extreme] * (1 + threshold):
                pivots.append((last_extreme, closes[last_extreme], "bottom"))
                last_extreme, direction = i, 1
    return pivots


def nearest(pivots, dates, kind, target, max_dist=25):
    cands = [p for p in pivots if p[2] == kind]
    best, bd = None, 10 ** 9
    for p in cands:
        d = abs(dates.index(dates[p[0]]) - dates.index(target)) if target in dates else 10 ** 9
        # 用交易日距离（近似：比较日期字符串所在下标）
        di = None
        for i, dd in enumerate(dates):
            if dd == dates[p[0]]:
                di = i
        ti = None
        for i, dd in enumerate(dates):
            if dd == target:
                ti = i
        if di is None or ti is None:
            continue
        d = abs(di - ti)
        if d < bd:
            best, bd = p, d
    return (best, bd) if best and bd <= max_dist else (None, None)


def main():
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    for code, name in CODES:
        existing = con.execute("SELECT count(*) FROM wave_labels WHERE code=?", (code,)).fetchone()[0]
        if existing:
            print(f"[skip] {code} {name}: 已有 {existing} 条标注，不覆盖")
            continue
        rows = con.execute(
            "SELECT trade_date, close FROM index_daily WHERE code=? AND trade_date>='20220101' ORDER BY trade_date",
            (code,)).fetchall()
        dates = [r[0] for r in rows]
        closes = [float(r[1]) for r in rows]
        piv = zigzag(closes, 0.10)
        overrides = ANCHOR_OVERRIDES.get(code, {})
        pts = {}
        ok = True
        for kind, td, usage in ANCHORS:
            target = overrides.get(usage, td)
            p, dist = nearest(piv, dates, kind, target, max_dist=40)
            if p is None:
                print(f"[warn] {code} {name}: 未找到 {usage} 对应摆动点（{kind} ~ {target}）")
                ok = False
                pts[usage] = None
            else:
                pts[usage] = (dates[p[0]], p[1], dist)
        a = pts.get("周线1浪起")
        b = pts.get("周线1浪顶/2浪起")
        c = pts.get("周线2浪底/3浪起")
        d4 = pts.get("周线3浪顶/4浪起")
        e = pts.get("周线4浪底/5浪起")
        f = pts.get("日线5-1顶/5-2起")
        if not all([a, b, c, d4, e]):
            print(f"[fail] {code} {name}: 锚点不齐，跳过")
            continue
        note = "auto-draft: 对齐上证锁定框架,待用户锁定"
        weekly = [
            ("1", a[0], b[0], a[1], b[1], "completed", f"周线1浪：{a[1]:.0f}→{b[1]:.0f}（草稿）"),
            ("2", b[0], c[0], b[1], c[1], "completed", f"周线2浪：{b[1]:.0f}→{c[1]:.0f}（草稿）"),
            ("3", c[0], d4[0], c[1], d4[1], "completed", f"周线3浪：{c[1]:.0f}→{d4[1]:.0f}（草稿）"),
            ("4", d4[0], e[0], d4[1], e[1], "completed", f"周线4浪：{d4[1]:.0f}→{e[1]:.0f}（草稿）"),
            ("5", e[0], None, e[1], None, "active", f"周线5浪：{e[1]:.0f}起进行中（草稿）"),
        ]
        daily = []
        if f:
            daily.append(("5-1", e[0], f[0], e[1], f[1], "completed", f"5-1：{e[1]:.0f}→{f[1]:.0f}（草稿）"))
            daily.append(("5-2", f[0], None, f[1], None, "active", f"5-2 回调中（草稿）"))
        for wave_name, sd, ed, sp, ep, status, desc in weekly:
            con.execute(
                "INSERT INTO wave_labels (code,start_date,end_date,wave_name,level,status,note,start_price,end_price,confirmed,created_at)"
                " VALUES (?,?,?,?,'weekly',?,?,?,?,0,datetime('now'))",
                (code, sd, ed, wave_name, status, f"{note} | {desc}", sp, ep))
        for wave_name, sd, ed, sp, ep, status, desc in daily:
            con.execute(
                "INSERT INTO wave_labels (code,start_date,end_date,wave_name,level,status,note,start_price,end_price,confirmed,created_at)"
                " VALUES (?,?,?,?,'daily',?,?,?,?,0,datetime('now'))",
                (code, sd, ed, wave_name, status, f"{note} | {desc}", sp, ep))
        con.commit()
        print(f"[ok] {code} {name}: weekly×{len(weekly)} + daily×{len(daily)} 草稿已入库（confirmed=0）")
        for wave_name, sd, ed, sp, ep, status, desc in weekly + daily:
            print(f"     {wave_name:<4} {sd} ~ {ed or '至今'}  {desc}")
    con.close()


if __name__ == "__main__":
    main()
