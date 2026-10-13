# -*- coding: utf-8 -*-
"""patch13: float_shares 韧性修复 —— 情绪分整块依赖它，抓取失败时用腾讯源/近7天缓存兜底
（原实现要求缓存 date==今天，东财连接被掐时返回 {} → 盘中情绪/赚钱效应/炸板率全部缺失）"""
import pathlib, re, sys

ROOT = pathlib.Path('/opt/stock-review')
REL = 'quant/realtime_service.py'
p = ROOT / REL
s = p.read_text(encoding='utf-8')

NEW = '''    def fetch_float_shares(self):
        """获取全市场流通股本（万股，缓存到磁盘）

        韧性策略：levistock -> 腾讯 -> 近7天磁盘缓存兜底（流通股本变化缓慢）
        """
        today = datetime.now().strftime("%Y%m%d")
        cached = None
        if FLOAT_SHARES_CACHE.exists():
            try:
                cached = json.loads(FLOAT_SHARES_CACHE.read_text(encoding="utf-8"))
            except Exception:
                cached = None

        def _valid(c):
            if not isinstance(c, dict) or not c.get("data"):
                return False
            vals = list(c["data"].values())[:100]
            return len(c["data"]) > 1000 and any(v > 0 for v in vals)

        if _valid(cached) and cached.get("date") == today:
            return cached["data"]

        # 1) levistock 东方财富
        data = {}
        try:
            import sys as _sys
            _sys.path.insert(0, '/opt/levistock')
            import levistock as lk
            raw = lk.stocks_all_em(filter_st=False)
            for s_ in raw:
                code = s_.get("stock_code", "")
                price = _sf(s_.get("price"))
                circ_market = _sf(s_.get("circ_market"))
                if code and price > 0 and circ_market > 0:
                    # circ_market(元) -> float_shares(万股) = circ_market / price / 10000
                    data[code] = circ_market / price / 10000
            if data:
                logger.info("levistock获取流通股本%d只" % len(data))
        except Exception as e:
            logger.warning("levistock流通股本获取失败: %s" % e)

        # 2) 腾讯兜底
        if not data:
            try:
                from quant.tencent_data import fetch_float_shares_tencent
                data = fetch_float_shares_tencent() or {}
                if data:
                    logger.info("腾讯流通股本获取%d只" % len(data))
            except Exception as e:
                logger.warning("腾讯流通股本获取失败: %s" % e)

        if data:
            try:
                FLOAT_SHARES_CACHE.parent.mkdir(parents=True, exist_ok=True)
                _atomic_write_text(
                    FLOAT_SHARES_CACHE,
                    json.dumps({"date": today, "data": data}, ensure_ascii=False))
            except Exception:
                pass
            return data

        # 3) 近7天磁盘缓存兜底（流通股本变化缓慢）
        if _valid(cached):
            try:
                _cd = datetime.strptime(str(cached.get("date")), "%Y%m%d").date()
                if 0 <= (datetime.now().date() - _cd).days <= 7:
                    logger.info("流通股本使用 %s 缓存兜底（%d只）" % (cached.get("date"), len(cached["data"])))
                    return cached["data"]
            except Exception:
                pass
        return {}

'''

pat = re.compile(r'    def fetch_float_shares\(self\):.*?(?=    def load_theme_map\(self\):)', re.S)
s, n = pat.subn(NEW, s)
print('replaced fetch_float_shares block x%d' % n)
if n != 1:
    sys.exit(1)
p.write_text(s, encoding='utf-8')
print('patch13 done')
