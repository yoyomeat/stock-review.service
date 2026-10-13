# -*- coding: utf-8 -*-
"""patch12: 实时监控两处口径修复
A. 昨日涨停/昨日连板：改用本地 CSV 精确名单（utils.is_zt 口径）+ 今日实时行情涨幅
   （原实现调 ths limit-up-pool(date)，该接口无视 date 参数返回今日池 → 显示的是今日涨停股均涨幅）
B. 连板梯队：改用今日涨停池构建（自带 pct/涨停时间）；原 ths 梯队接口无 pct 字段 → 前端涨幅空白
"""
import pathlib, re, sys

ROOT = pathlib.Path('/opt/stock-review')
REL = 'quant/realtime_service.py'
p = ROOT / REL
s = p.read_text(encoding='utf-8')

NEW_LADDER = '''    def _fetch_zt_ladder(self):
        """获取今日连板梯队（数据源：同花顺今日涨停池，自带实时涨幅/涨停时间）

        返回: {ladder: [{level: N, count: M, stocks: [{code, name, pct, first_zt_time, open_times, board_num}]}],
               total_zt: N（全部涨停数，含首板）, highest: N}
        """
        from collections import defaultdict

        # ── 首选：今日涨停池构建（continue_day_cnt=连板数，price_change_ratio_pct=实时涨幅）──
        try:
            import sys as _sys
            _ths_path = os.path.dirname(os.path.abspath(__file__))
            if _ths_path not in _sys.path:
                _sys.path.insert(0, _ths_path)
            from ths_api import get_limit_up_pool
            pool = get_limit_up_pool()
            if pool:
                tiers = defaultdict(list)
                for s_ in pool:
                    level = int(s_.get("continue_day_cnt", 1) or 1)
                    tiers[level].append({
                        "code": s_.get("ticker", "") or str(s_.get("thscode", "")).split(".")[0],
                        "name": s_.get("name", ""),
                        "pct": round(_sf(s_.get("price_change_ratio_pct")), 2),
                        "first_zt_time": s_.get("limit_up_time", ""),
                        "open_times": 0,
                        "board_num": level,
                    })
                ladder = [{"level": lv, "count": len(stks), "stocks": stks}
                          for lv, stks in sorted(tiers.items(), reverse=True)]
                highest = max(tiers.keys()) if tiers else 0
                logger.info("连板梯队(涨停池)构建完成: 涨停%d只 最高%d板" % (len(pool), highest))
                return {"ladder": ladder, "total_zt": len(pool), "highest": highest}
        except Exception as e:
            logger.warning("同花顺涨停池构建梯队失败，回退levistock: %s" % e)

        # ── 兜底：levistock 东财涨停池（含 pct / first_zt_time / open_times）──
        try:
            import sys as _sys
            _sys.path.insert(0, '/opt/levistock')
            import levistock as lk
            raw = lk.stock_zt_pool_em()
            if not raw:
                return {"ladder": [], "total_zt": 0, "highest": 0}

            tiers = defaultdict(list)
            for s_ in raw:
                level = s_.get("continuous", 1)
                tiers[level].append({
                    "code": s_.get("stock_code", ""),
                    "name": s_.get("stock_name", ""),
                    "sector": s_.get("sector", ""),
                    "open_times": s_.get("open_times", 0),
                    "pct": round(_sf(s_.get("change_pct")), 2),
                    "first_zt_time": s_.get("first_zt_time", ""),
                    "board_num": level,
                })

            ladder = []
            for level in sorted(tiers.keys(), reverse=True):
                stocks = tiers[level]
                ladder.append({
                    "level": level,
                    "count": len(stocks),
                    "stocks": stocks,
                })

            highest = ladder[0]["level"] if ladder else 0
            return {"ladder": ladder, "total_zt": len(raw), "highest": highest}
        except Exception as e:
            logger.warning("连板梯队获取失败: %s" % e)
            return None

'''

NEW_YESTERDAY = '''    def _fetch_yesterday_zt(self, quotes=None):
        """昨日涨停 / 昨日连板 个股在**今日**的实时平均涨幅

        口径：
          - 昨日涨停股 = 昨日收盘涨停的全部个股（本地 CSV，utils.is_zt 统一口径，不依赖外部接口）
          - 昨日连板股 = 昨日涨停且连板数 >= 2 的个股
          - 涨幅 = 上述个股在今日的实时涨幅的算术平均（盘中为实时价，盘后为收盘价）
        """
        try:
            from utils import get_prev_trading_day
            from lianban import load_zt_stocks, compute_lianban_tiers

            today_str = datetime.now().strftime("%Y%m%d")
            yesterday_str = get_prev_trading_day(today_str)

            zt_map = load_zt_stocks(yesterday_str)  # {code: {name, pct}} 昨日涨停名单
            if not zt_map:
                return {"zt_count": 0, "zt_avg_pct": 0, "cont_count": 0, "cont_avg_pct": 0}

            # 昨日连板名单 = 昨日梯队中 level>=2
            tiers = compute_lianban_tiers(yesterday_str).get("tiers", [])
            cont_codes = {st["code"] for t in tiers if t.get("level", 0) >= 2
                          for st in t.get("stocks", [])}

            # 今日实时涨幅：优先用本次分析已抓取的全市场行情（code -> change_pct）
            pct_map = {}
            for q in (quotes or []):
                c = str(q.get("code", "")).strip()
                if c:
                    pct_map[c] = _sf(q.get("change_pct"))

            # 兜底：同花顺行情快照
            if not pct_map:
                try:
                    import sys as _sys
                    _ths_path = os.path.dirname(os.path.abspath(__file__))
                    if _ths_path not in _sys.path:
                        _sys.path.insert(0, _ths_path)
                    from ths_api import get_snapshot
                    codes = list(zt_map.keys())
                    ths_codes = [_to_thscode(c) for c in codes]
                    for i in range(0, len(ths_codes), 200):
                        for s_ in (get_snapshot(ths_codes[i:i + 200]) or []):
                            code = str(s_.get("ticker", "")).split(".")[0]
                            if code:
                                pct_map[code] = _sf(s_.get("price_change_ratio_pct"))
                except Exception as e:
                    logger.warning("昨日涨停今日快照兜底失败: %s" % e)

            zt_pcts = [pct_map[c] for c in zt_map if c in pct_map]
            cont_pcts = [pct_map[c] for c in cont_codes if c in pct_map]
            result = {
                "zt_count": len(zt_map),
                "zt_avg_pct": round(sum(zt_pcts) / len(zt_pcts), 2) if zt_pcts else 0,
                "cont_count": len(cont_codes),
                "cont_avg_pct": round(sum(cont_pcts) / len(cont_pcts), 2) if cont_pcts else 0,
            }
            logger.info("昨日表现(%s->今日): 涨停%d只均%.2f%% 连板%d只均%.2f%%" % (
                yesterday_str, result["zt_count"], result["zt_avg_pct"],
                result["cont_count"], result["cont_avg_pct"]))
            return result
        except Exception as e:
            logger.warning("昨日涨停表现计算失败: %s" % e)
            return {"zt_count": 0, "zt_avg_pct": 0, "cont_count": 0, "cont_avg_pct": 0}

'''

# ── 替换 _fetch_zt_ladder（原到 _fetch_yesterday_zt 之前）──
pat1 = re.compile(r'    def _fetch_zt_ladder\(self\):.*?(?=    def _fetch_yesterday_zt\(self\))', re.S)
s, n1 = pat1.subn(NEW_LADDER, s)
print('replaced _fetch_zt_ladder block x%d' % n1)
if n1 != 1:
    sys.exit(1)

# ── 替换 _fetch_yesterday_zt（原到 run_analysis 之前）──
pat2 = re.compile(r'    def _fetch_yesterday_zt\(self\):.*?(?=    def run_analysis\(self\):)', re.S)
s, n2 = pat2.subn(NEW_YESTERDAY, s)
print('replaced _fetch_yesterday_zt block x%d' % n2)
if n2 != 1:
    sys.exit(1)

# ── 调用处传入 quotes ──
old_call = '        yz_data = self._fetch_yesterday_zt()'
new_call = '        yz_data = self._fetch_yesterday_zt(quotes)'
if s.count(old_call) != 1:
    print('!! call site not found'); sys.exit(1)
s = s.replace(old_call, new_call)
print('call site updated')

# ── 新增 _to_thscode 工具函数（放在 _run_script 之前）──
anchor = 'def _run_script(script, args=None, timeout=30):'
helper = '''def _to_thscode(code: str) -> str:
    """6位代码 -> 同花顺代码（600519.SH / 000001.SZ / 830799.BJ）"""
    code = str(code or "").strip().split(".")[0]
    if code.startswith("6") or code.startswith("9"):
        mkt = "SH"
    elif code.startswith(("0", "3")):
        mkt = "SZ"
    else:
        mkt = "BJ"
    return code + "." + mkt


'''
if s.count(anchor) != 1:
    print('!! anchor for _to_thscode not found'); sys.exit(1)
s = s.replace(anchor, helper + anchor)
print('helper _to_thscode added')

p.write_text(s, encoding='utf-8')
print('patch12 done')
