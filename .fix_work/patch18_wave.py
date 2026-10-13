# -*- coding: utf-8 -*-
"""patch18: market_wave_engine 全面升级
P0-1 概率→结构强度分 + 挂历史胜率（walk-forward 标定器 + wave_calib.json）
P0-2 诚实话术（路径B≠空仓、绝对买点区→回调区分批、主升处提示追高性价比）
P0-3 锚点治理：anchor_locked/anchor_suggest/reanchor_needed + set_wave5_anchor 写库锁定
P1-4 路径切换缓冲：连续2日收盘破位或单日深度破位(-2%)才切路径B
P1-5 find_wave1_high 取错高点（highs[-1]→highs[0]，注释与代码对齐）
P1-6 时间对称性参与判定（回调用时>上涨1.5倍降档）
P1-7 回撤分档改中性命名（去掉'黄金区/危险区'等未经验证的标签）
P2-8 框架生命周期：跌破失效位→需重标；5浪达1浪1倍投射→末段提示
P2-9 合成升级：共识度 + 权重/成长组背离提示
"""
import pathlib, re, sys

ROOT = pathlib.Path('/opt/stock-review')
REL = 'quant/market_wave_engine.py'
p = ROOT / REL
s = p.read_text(encoding='utf-8')

def sub_block(pattern, repl, tag):
    global s
    s, n = re.subn(pattern, lambda _m: repl, s, flags=re.S)
    print('block replaced: %s x%d' % (tag, n))
    if n != 1:
        sys.exit(1)

# ── P1-7: fib_zone 中性命名 ──
sub_block(r'def fib_zone\(retrace\):.*?(?=def load_daily\()',
'''def fib_zone(retrace):
    """回撤分区（中性命名；各区历史胜率见 action_note，不再用'黄金区/危险区'等未经验证的标签）"""
    if retrace <= 0.236:
        return "极浅回调(<23.6%)"
    if retrace <= 0.382:
        return "浅回调(23.6-38.2%)"
    if retrace <= 0.5:
        return "回调(38.2-50%)"
    if retrace <= 0.618:
        return "回调(50-61.8%)"
    if retrace <= 0.786:
        return "深回调(61.8-78.6%)"
    return "超深回调(>78.6%)"


''', 'fib_zone')

# ── P1-5: find_wave1_high 取起点后第一个摆动高点 ──
sub_block(r'def find_wave1_high\(dates, closes, start_idx\):.*?(?=def analyze_one\()',
'''def find_wave1_high(dates, closes, start_idx):
    """自动锚定：5浪起点之后的**第一个**明显高点（子1浪顶候选）

    修复：原实现取 highs[-1]（最后一个高点），与注释不符——
    5-1 顶定位错位导致回撤率基准错误。
    """
    segment = closes[start_idx:]
    piv = zigzag(segment, DAILY_THRESHOLD)
    if not piv:
        return None
    highs = [p for p in piv if p[2] == 'high']
    if not highs:
        return None
    h = highs[0]  # 起点后第一个摆动高点 = 子1浪顶候选
    return {"idx": start_idx + h[0], "price": h[1], "date": dates[start_idx + h[0]]}


''', 'find_wave1_high')

# ── analyze_one 整体重写（P0-2/3、P1-4/6、P2-8）──
NEW_ANALYZE = '''def analyze_one(conn, code, info, data=None, force_auto=False):
    """单指数两路径判定（周线框架锁定 + 日线子浪）。

    data / force_auto 供历史标定（walk-forward）使用：
      data=截断序列 (dates, closes)；force_auto=True 跳过锁定标注，避免未来信息。
    """
    data = data or load_daily(conn, code)
    if not data:
        return {"code": code, "name": info["name"], "error": "数据不足"}
    dates, closes = data
    cur_price = closes[-1]
    cur_date = dates[-1]

    res = {"code": code, "name": info["name"], "price": round(cur_price, 2),
           "date": cur_date, "note": info["note"]}

    # ── 周线5浪锁定标注（人工确认的锚点不随后续数据回移）──
    locked = None
    if not force_auto:
        try:
            conn2 = sqlite3.connect(DB_PATH)
            row = conn2.execute(
                "SELECT wave_name, start_date, end_date, start_price, status FROM wave_labels "
                "WHERE code=? AND level='weekly' AND wave_name='5' ORDER BY id DESC LIMIT 1", (code,)).fetchone()
            conn2.close()
            if row:
                locked = {"name": row[0], "start_date": row[1], "end_date": row[2],
                          "start_price": row[3], "status": row[4]}
        except Exception:
            locked = None

    wave5_start = None
    wave1_high = None
    if locked:
        wave5_start = {"price": float(locked["start_price"]), "date": locked["start_date"]}
        start_idx = 0
        for i, d in enumerate(dates):
            if d >= locked["start_date"]:
                start_idx = i
                break
        try:
            conn2 = sqlite3.connect(DB_PATH)
            sub_rows = conn2.execute(
                "SELECT wave_name, start_date, end_date, start_price, end_price, status FROM wave_labels "
                "WHERE code=? AND level='daily' AND wave_name IN ('5-1','5-2') ORDER BY id DESC LIMIT 2",
                (code,)).fetchall()
            conn2.close()
        except Exception:
            sub_rows = []
        for r in sub_rows:
            if r[0] == '5-1' and r[4]:
                wave1_high = {"price": float(r[4]), "date": r[2]}
        if wave1_high is None:
            w1h = find_wave1_high(dates, closes, start_idx)
            if w1h:
                wave1_high = {"price": w1h["price"], "date": w1h["date"]}
    else:
        ws = find_wave5_start(dates, closes)
        if ws:
            wave5_start = {"price": ws["price"], "date": ws["date"]}
            w1h = find_wave1_high(dates, closes, ws["idx"])
            if w1h:
                wave1_high = {"price": w1h["price"], "date": w1h["date"]}

    if not wave5_start:
        res["error"] = "无法锚定5浪起点"
        return res

    # P0-3：锚点溯源
    res["locked_framework"] = bool(locked)
    res["anchor_locked"] = bool(locked)
    res["anchor_suggest"] = (not locked)
    res["wave5_start"] = round(wave5_start["price"], 2)
    res["wave5_start_date"] = wave5_start["date"]

    confirm_price = info["confirm"] if info["confirm"] else (wave1_high["price"] if wave1_high else None)
    invalid_price = info["invalid"] if info["invalid"] else wave5_start["price"]
    fib_key = info["fib_key"]
    res["confirm_price"] = round(confirm_price, 2) if confirm_price else None
    res["invalid_price"] = round(invalid_price, 2) if invalid_price else None
    res["fib_key"] = fib_key

    wave5_amp = (wave1_high["price"] - wave5_start["price"]) if wave1_high else None

    # ── P1-4 路径切换缓冲：单日毛刺不翻转，连续2日收盘破位或单日深度破位(-2%)才切路径B ──
    below_streak = 0
    if invalid_price:
        for c in reversed(closes):
            if c < invalid_price:
                below_streak += 1
            else:
                break
    deep_break = bool(invalid_price) and cur_price < invalid_price * 0.98
    broke = deep_break or below_streak >= 2
    warned = (not broke) and below_streak >= 1

    # ── P1-6 时间对称性（参与判定）──
    time_ratio = None
    if wave1_high and wave1_high.get("date") and wave5_start.get("date"):
        try:
            d1 = datetime.strptime(wave5_start["date"], "%Y%m%d")
            d2 = datetime.strptime(wave1_high["date"], "%Y%m%d")
            up_days = (d2 - d1).days
            down_days = (datetime.strptime(cur_date, "%Y%m%d") - d2).days
            time_ratio = round(down_days / up_days, 2) if up_days > 0 else None
        except Exception:
            time_ratio = None

    prob = 80
    action = ""
    path = ""
    subwave_desc = ""

    if broke:
        if deep_break:
            subwave_desc = "深度跌破失效位（%.2f），五浪失效" % (invalid_price or 0)
        else:
            subwave_desc = "连续%d日收盘跌破失效位（%.2f），五浪失效" % (below_streak, invalid_price or 0)
        path = "路径B：大四浪调整——结构破坏"
        prob = 15
        action = "观望等右侧"
        res["reanchor_needed"] = True
        res["framework_status"] = "框架失效（跌破失效位），需重新锚定5浪起点"
    elif wave1_high and cur_price >= wave1_high["price"]:
        subwave_desc = "子3浪主升（已突破5-1顶）"
        path = "路径A：大五浪上升——主升进行中"
        prob = 95
        action = "持仓为主"
    elif cur_price > wave5_start["price"]:
        if wave1_high is None:
            gain = (cur_price / wave5_start["price"] - 1) * 100
            subwave_desc = "子1浪进行中（自起点上涨%.1f%%，5-1顶未确认）" % gain
            path = "路径A：大五浪上升——子1浪进行中"
            prob = 85
            action = "持有/回调加仓"
        else:
            retrace = (wave1_high["price"] - cur_price) / wave5_amp if wave5_amp else 0
            zone = fib_zone(retrace)
            if retrace <= 0.382:
                subwave_desc = "子2浪浅回调（回撤%d%%）" % round(retrace * 100)
            elif retrace <= 0.618:
                subwave_desc = "子2浪回调（回撤%d%%）" % round(retrace * 100)
            else:
                subwave_desc = "子2浪深回调（回撤%d%%），结构转弱" % round(retrace * 100)
            # 两路径强度：路径A成立 → 强度分反映价格在[失效位,确认位]区间的位置
            span = confirm_price - invalid_price if confirm_price and invalid_price else 0
            pos = min(max((cur_price - invalid_price) / span, 0), 1) if span > 0 else 0.5
            if fib_key and cur_price >= fib_key:
                prob = round(85 + 10 * pos)
            elif fib_key and cur_price < fib_key:
                prob = round(80 + 10 * pos)
            else:
                prob = round(78 + 15 * pos)
            if time_ratio and time_ratio > 1.5:
                prob = max(50, prob - 8)
                subwave_desc += "；回调用时已达上涨时段%.2f倍，结构存疑" % time_ratio
            action = "回调区分批"
            res["retrace"] = round(retrace, 2)
            res["fib_zone"] = zone
            res["time_ratio"] = time_ratio
            res["wave1_high"] = round(wave1_high["price"], 2)
            res["wave1_high_date"] = wave1_high["date"]
    else:
        # 兜底（正常情况下 broke 已覆盖）
        path = "路径B：大四浪调整——结构破坏"
        prob = 15
        action = "观望等右侧"
        subwave_desc = "跌破5浪起点，五浪失效"
        res["reanchor_needed"] = True

    if subwave_desc:
        res["subwave"] = subwave_desc

    # P1-4 警示态：单日破位观察中
    if warned:
        res["warning"] = "单日收盘跌破失效位，观察中（连续2日破位或单日-2%才切路径B）"
        prob = max(50, prob - 5)

    # P2-8 框架生命周期
    if not res.get("framework_status"):
        if wave1_high and wave5_amp and (cur_price - wave5_start["price"]) >= wave5_amp:
            res["framework_status"] = "5浪累计涨幅已达子1浪1倍投射，可能进入末段，建议复核周线框架"
        else:
            res["framework_status"] = ""

    res["path"] = path
    res["prob"] = prob
    res["action"] = action

    conds = []
    if confirm_price:
        conds.append("站稳%.2f → 子3浪主升确认，更积极" % confirm_price)
    if fib_key:
        conds.append("站上%.0f → 路径A强度提升" % fib_key)
    if invalid_price:
        conds.append("连续2日收盘跌破%.2f（或单日-2%%）→ 五浪失效，切路径B" % invalid_price)
    res["conditions"] = conds

    return res


'''
sub_block(r'def analyze_one\(conn, code, info\):.*?(?=def get_market_wave_status\(\):)', NEW_ANALYZE, 'analyze_one')

# ── 标定器 + 挂载胜率/话术 + 锚点锁定 + P2-9 合成 ──
NEW_TAIL = '''CALIB_PATH = os.path.join(BASE_DIR, "data", "wave_calib.json")
_CALIB = None
_CALIB_BUILDING = False


def _cat_of(path_text):
    p = path_text or ""
    if "路径B" in p:
        return "B"
    if "主升" in p:
        return "A_main"
    if "子1浪" in p:
        return "A_w1"
    return "A_w2"


def build_calibration():
    """walk-forward 历史标定（自动锚定模式）：各判定状态的未来20日表现 → wave_calib.json"""
    global _CALIB, _CALIB_BUILDING
    if _CALIB_BUILDING:
        return {}
    _CALIB_BUILDING = True
    try:
        buckets = {}
        for code, info in INDICES.items():
            conn = sqlite3.connect(DB_PATH)
            data = load_daily(conn, code)
            conn.close()
            if not data:
                continue
            dates, closes = data
            n = len(dates)
            info_auto = dict(info)
            info_auto["confirm"] = None
            info_auto["invalid"] = None
            info_auto["fib_key"] = None
            for cut in range(250, n - 20, 3):
                r = analyze_one(None, code, info_auto, data=(dates[:cut], closes[:cut]), force_auto=True)
                if r.get("error") or not r.get("path"):
                    continue
                f20 = (closes[cut - 1 + 20] / closes[cut - 1] - 1) * 100
                cat = _cat_of(r.get("path", ""))
                keys = [cat]
                if cat == "A_w2" and r.get("fib_zone"):
                    keys.append(cat + "|" + r["fib_zone"])
                for k in keys:
                    e = buckets.setdefault(k, {"n": 0, "win": 0, "vals": []})
                    e["n"] += 1
                    e["win"] += 1 if f20 > 0 else 0
                    e["vals"].append(f20)
        out = {}
        for k, e in buckets.items():
            vals = sorted(e["vals"])
            out[k] = {"n": e["n"], "win20": round(e["win"] / e["n"] * 100, 1),
                      "avg20": round(sum(vals) / len(vals), 2),
                      "med20": round(vals[len(vals) // 2], 2)}
        calib = {"built": datetime.now().strftime("%Y%m%d"), "fwd_bars": 20, "keys": out}
        try:
            with open(CALIB_PATH, "w", encoding="utf-8") as f:
                json.dump(calib, f, ensure_ascii=False, indent=1)
        except Exception:
            pass
        _CALIB = calib
        return calib
    finally:
        _CALIB_BUILDING = False


def load_calibration(refresh_days=30):
    global _CALIB
    if _CALIB:
        return _CALIB
    try:
        with open(CALIB_PATH, encoding="utf-8") as f:
            c = json.load(f)
        built = str(c.get("built", ""))
        age = (datetime.now() - datetime.strptime(built, "%Y%m%d")).days
        if 0 <= age <= refresh_days:
            _CALIB = c
            return c
    except Exception:
        pass
    return build_calibration()


def _annotate(res):
    """P0-1 挂历史胜率 + P0-2 诚实话术"""
    calib = load_calibration()
    cat = _cat_of(res.get("path", ""))
    keys = calib.get("keys", {})
    k = cat
    if cat == "A_w2" and res.get("fib_zone"):
        k2 = cat + "|" + res["fib_zone"]
        if k2 in keys:
            k = k2
    h = keys.get(k) or keys.get(cat) or {"n": 0, "win20": None, "avg20": None, "med20": None}
    res["hist"] = h
    res["hist"]["key"] = k
    res["category"] = cat
    hs = ("历史20日 %+.1f%% / 胜率%.0f%%（n=%d）" % (h["avg20"], h["win20"], h["n"])
          if h.get("n") else "历史样本不足")

    if cat == "B":
        res["action_note"] = ("趋势结构已破坏（跌破失效位）。但该位置 %s —— 多为超跌反弹区："
                              "忌恐慌割肉，也不宜左侧抄底，等重新站回确认位或锁定新锚点后再做多。" % hs)
    elif cat == "A_main":
        res["action_note"] = ("已突破子1浪顶、主升进行中。该状态 %s —— 突破后追高性价比有限，"
                              "回踩不破确认位加仓优于追涨。" % hs)
    elif cat == "A_w1":
        res["action_note"] = ("5浪起点上方、子1浪顶未确认。该状态 %s —— 持有为主，回调至失效位上方分批。" % hs)
    else:
        extra = ""
        if res.get("time_ratio") and res["time_ratio"] > 1.5:
            extra = "注意：回调用时已达上涨时段%.2f倍，结构存疑。" % res["time_ratio"]
        res["action_note"] = ("%s%s%s 站稳确认位%s加仓；连续2日跌破失效位%s离场。"
                              % (res.get("fib_zone", "回调中") + "，", hs, extra,
                                 ("%.2f" % res["confirm_price"]) if res.get("confirm_price") else "（未设）",
                                 ("%.2f" % res["invalid_price"]) if res.get("invalid_price") else "（未设）"))
    return res


def set_wave5_anchor(code, start_date, start_price):
    """P0-3 人工确认锚点：锁定周线5浪起点（写入 wave_labels，不再随后续数据回移）"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "UPDATE wave_labels SET status='completed', superseded_at=datetime('now') "
        "WHERE code=? AND level='weekly' AND wave_name='5' AND status='active'", (code,))
    cur.execute(
        "INSERT INTO wave_labels (code, wave_name, level, start_date, start_price, status, note, confirmed, confirmed_at) "
        "VALUES (?, '5', 'weekly', ?, ?, 'active', '用户锁定', 1, datetime('now'))",
        (code, start_date, float(start_price)))
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return {"locked": True, "id": rid, "code": code, "start_date": start_date,
            "start_price": float(start_price)}


def get_market_wave_status():
    """供API调用的入口"""
    conn = sqlite3.connect(DB_PATH)
    results = []
    for code, info in INDICES.items():
        r = analyze_one(conn, code, info)
        if not r.get("error"):
            _annotate(r)
        results.append(r)
    conn.close()

    # ── P2-9 多指数合成：共识度 + 权重/成长组背离 ──
    total = len(results)
    path_a_count = sum(1 for r in results if "路径A" in r.get("path", ""))
    consensus = round(abs(path_a_count - total / 2) / (total / 2), 2) if total else 1.0
    big_a = sum(1 for r in results if r["code"] in ("sh000001", "sz399001") and "路径A" in r.get("path", ""))
    gro_a = sum(1 for r in results if r["code"] in ("sz399006", "sh000688") and "路径A" in r.get("path", ""))
    divergence_note = ""
    if (big_a > 0) != (gro_a > 0):
        divergence_note = "权重组(上证/深成)与成长组(创业板/科创50)路径背离 → 历史多为震荡期，建议均衡分散、降低单边押注"

    if path_a_count == total:
        market_state = "四指数全部处于路径A（五浪上升）→ 全面做多"
    elif path_a_count >= 3:
        market_state = "%d/%d指数处于路径A → 结构性做多，仓位偏积极" % (path_a_count, total)
    elif path_a_count >= 2:
        market_state = "%d/%d指数处于路径A → 结构性行情，仓位中性" % (path_a_count, total)
    else:
        market_state = "%d/%d指数处于路径A → 谨慎，控制仓位" % (path_a_count, total)
    market_state += " · 共识度%d%%" % int(consensus * 100)

    return {
        "date": results[0]["date"] if results else "",
        "market_state": market_state,
        "consensus": consensus,
        "divergence_note": divergence_note,
        "calib_built": load_calibration().get("built", ""),
        "indices": results,
    }


'''
sub_block(r'def get_market_wave_status\(\):.*?(?=if __name__ ==)', NEW_TAIL, 'tail(calib+annotate+anchor+synthesis)')

p.write_text(s, encoding='utf-8')
print('patch18 done')
