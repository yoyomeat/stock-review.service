# -*- coding: utf-8 -*-
"""patch3: quant/realtime_service.py (A7 vol_ratio / A8 交易时间 / C2 快照节流 / D 原子写+冷却+涨跌幅)"""
import pathlib, re, sys

ROOT = pathlib.Path('/opt/stock-review')

def edit(relpath, pairs):
    p = ROOT / relpath
    s = p.read_text(encoding='utf-8')
    for old, new in pairs:
        n = s.count(old)
        if n != 1:
            print(f'!! [{relpath}] expect 1 occurrence, got {n}: {old[:70]!r}')
            sys.exit(1)
        s = s.replace(old, new)
        print(f'ok [{relpath}] {old[:55]!r}')
    p.write_text(s, encoding='utf-8')

REL = 'quant/realtime_service.py'

edit(REL, [
    # A8: 交易时间统一口径（含午休与节假日）
    ('''def _is_trade_time():
    now = datetime.now()
    if now.weekday() >= 5: return False
    t = now.hour * 100 + now.minute
    return 915 <= t <= 1500''',
     '''def _is_trade_time():
    """是否交易时段（统一口径：utils.is_trade_time_now，含午休与节假日判断）"""
    from utils import is_trade_time_now
    return is_trade_time_now()'''),

    # D: TDXRS 连接失败后 60s 冷却，避免每次调用重试 11 个节点
    ('''def _get_tdxrs_client():
    """获取或创建TDXRS连接（单例，复用连接）"""
    global _tdxrs_client
    with _tdxrs_lock:
        if _tdxrs_client is not None:
            return _tdxrs_client''',
     '''_tdxrs_fail_ts = 0.0


def _get_tdxrs_client():
    """获取或创建TDXRS连接（单例，复用连接；全部失败后 60s 冷却）"""
    global _tdxrs_client, _tdxrs_fail_ts
    with _tdxrs_lock:
        if _tdxrs_client is not None:
            return _tdxrs_client
    if _tdxrs_fail_ts and time.time() - _tdxrs_fail_ts < 60:
        return None'''),

    ('    logger.warning("TDXRS直连失败，所有服务器不可达")\n    return None',
     '    _tdxrs_fail_ts = time.time()\n    logger.warning("TDXRS直连失败，所有服务器不可达")\n    return None'),

    # D: 分时兜底无真实昨收，涨跌幅置 0（腾讯兜底成功后会重算），不再显示"现价vs均价"的假涨跌幅
    ('''                            "circ_market": round(circ_market, 0),
                            "change_pct": round((price - last_close) / last_close * 100, 2) if last_close else 0,''',
     '''                            "circ_market": round(circ_market, 0),
                            # 分时兜底无真实昨收（last_close 为均价占位），涨跌幅置 0 避免误导
                            "change_pct": 0,'''),

    # A7: 历史成交额缓冲字段名是 total_amt（旧代码取 amt_total → 恒空 → vol_ratio 恒 1.0）；只取今天之前的
    ('''    def _init_amt_buffer(self):
        """启动时从daily_sentiment_cache.json加载历史amt_total"""
        buffer = []
        try:
            cache_file = BASE_DIR / "data" / "daily_sentiment_cache.json"
            if cache_file.exists():
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                if isinstance(cache_data, list):
                    for entry in cache_data[-20:]:
                        amt = entry.get('amt_total', 0)
                        if amt > 0:
                            buffer.append(amt)
        except Exception:
            pass
        return buffer''',
     '''    def _init_amt_buffer(self):
        """启动时从daily_sentiment_cache.json加载历史全天成交额（元，按日期升序取最近20天）"""
        buffer = []
        _today = datetime.now().strftime("%Y%m%d")
        try:
            cache_file = BASE_DIR / "data" / "daily_sentiment_cache.json"
            if cache_file.exists():
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                if isinstance(cache_data, list):
                    entries = [e for e in cache_data if str(e.get('date', '')) < _today]
                    entries.sort(key=lambda e: str(e.get('date', '')))
                    for entry in entries[-20:]:
                        # 字段名为 total_amt（旧代码误取 amt_total，导致均量缓冲恒空）
                        amt = entry.get('total_amt') or entry.get('amt_total', 0)
                        if amt > 0:
                            buffer.append(float(amt))
        except Exception:
            pass
        return buffer'''),

    # A7: 每天只记一笔（收盘后），并按已交易分钟折算当日成交额
    ('''        # F2: vol_ratio（当日成交额 / 20日均量）
        total_amount = result.get('total_amount_yi', 0) * 1e8
        if self._amt_buffer:
            avg_20d = sum(self._amt_buffer[-20:]) / len(self._amt_buffer[-20:])
        else:
            avg_20d = total_amount
        vol_ratio = max(0.2, min(3.0, total_amount / avg_20d)) if avg_20d > 0 else 1.0

        # 更新缓冲（每轮追加当日成交额）
        if total_amount > 0:
            self._amt_buffer.append(total_amount)
            if len(self._amt_buffer) > 30:
                self._amt_buffer = self._amt_buffer[-25:]''',
     '''        # F2: vol_ratio（当日成交额 / 前20日全天均量；盘中按已交易分钟折算成全天口径）
        total_amount = result.get('total_amount_yi', 0) * 1e8
        _prev_amts = [a for a in self._amt_buffer if a > 0][-20:]
        avg_20d = sum(_prev_amts) / len(_prev_amts) if _prev_amts else 0
        from quant.realtime_signals import get_elapsed_minutes
        _elapsed = min(max(get_elapsed_minutes(), 30), 240)
        scaled_amount = total_amount * 240.0 / _elapsed
        vol_ratio = max(0.2, min(3.0, scaled_amount / avg_20d)) if avg_20d > 0 else 1.0

        # 更新缓冲：每天只在收盘后记一笔全天成交额（避免同日半日额反复入账污染均量）
        _today = datetime.now().strftime("%Y%m%d")
        if total_amount > 0 and datetime.now().hour >= 15 and self._amt_buffer_date != _today:
            self._amt_buffer.append(total_amount)
            self._amt_buffer_date = _today
            if len(self._amt_buffer) > 30:
                self._amt_buffer = self._amt_buffer[-25:]'''),

    ('        # vol_ratio缓冲：启动时从历史缓存加载20天amt_total\n        self._amt_buffer = self._init_amt_buffer()',
     '        # vol_ratio缓冲：启动时从历史缓存加载20天全天成交额（元）\n        self._amt_buffer = self._init_amt_buffer()\n        self._amt_buffer_date = ""  # 当天全天成交额入账日期（每天只记一笔）'),

    # C2: 请求端读缓存（行情刷新由轮询线程负责）；缓存过期/为空时才在请求路径拉取
    ('''    def get_snapshot(self):
        now = datetime.now()
        is_trade = _is_trade_time()
        if not is_trade and self._cache.get("timestamp"):
            return self._cache
        indices = self.fetch_indices()''',
     '''    def get_snapshot(self):
        now = datetime.now()
        is_trade = _is_trade_time()
        if not is_trade and self._cache.get("timestamp"):
            return self._cache
        # 请求端只读缓存（轮询线程负责刷新）；缓存超过 2×间隔 才在请求路径兜底拉取
        with self._lock:
            _interval = float(self._config.get("poll_interval", 5) or 5)
            _age = (time.time() - self._cache_ts) if self._cache_ts else 1e9
            if _age < max(_interval * 2, 10):
                return dict(self._cache)
        indices = self.fetch_indices()'''),

    ('''        with self._lock:
            self._cache = {"indices": indices, "sectors": sectors, "stocks": stocks,
                          "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"), "is_trade_time": is_trade}
            return dict(self._cache)''',
     '''        with self._lock:
            self._cache = {"indices": indices, "sectors": sectors, "stocks": stocks,
                          "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"), "is_trade_time": is_trade}
            self._cache_ts = time.time()
            return dict(self._cache)'''),

    # D: 原子写工具（避免并发读到半截 JSON）
    ('def _load_config():',
     '''def _atomic_write_text(path, text: str):
    """原子写文件（tmp+rename），避免并发读到半截 JSON"""
    _p = Path(str(path))
    _tmp = Path(str(path) + ".tmp")
    _tmp.write_text(text, encoding="utf-8")
    _tmp.replace(_p)


def _load_config():'''),

    ('''    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存配置失败: {e}")''',
     '''    try:
        _atomic_write_text(CONFIG_FILE, json.dumps(cfg, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.error(f"保存配置失败: {e}")'''),
])

# 需要 replace-all / regex 的两处
p = ROOT / REL
s = p.read_text(encoding='utf-8')

# cache 重置处同步重置 _cache_ts（保持缩进）— 5 处
pat = re.compile(r'(\n(\s*)self\._cache = \{"indices": \[\], "sectors": \[\], "stocks": \[\], "timestamp": None, "is_trade_time": False\})')
s, n = pat.subn(lambda m: m.group(1) + '\n' + m.group(2) + 'self._cache_ts = 0.0', s)
print(f'ok [{REL}] cache reset + _cache_ts x{n}')
if n != 5:
    print(f'!! expect 5 cache-reset sites, got {n}'); sys.exit(1)

# 市场缓存原子写（2 处相同文本）
old = '''                try:
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    cache_file.write_text(
                        json.dumps({"date": today, "data": quotes}, ensure_ascii=False),
                        encoding="utf-8"
                    )
                except Exception:
                    pass'''
new = '''                try:
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    _atomic_write_text(
                        cache_file,
                        json.dumps({"date": today, "data": quotes}, ensure_ascii=False),
                    )
                except Exception:
                    pass'''
n = s.count(old)
print(f'ok [{REL}] market cache atomic x{n}')
if n != 2:
    print(f'!! expect 2 market-cache writes, got {n}'); sys.exit(1)
s = s.replace(old, new)

old = '                AVG_VOL_CACHE.write_text(json.dumps({"date": today, "data": data}, ensure_ascii=False), encoding="utf-8")'
new = '                _atomic_write_text(AVG_VOL_CACHE, json.dumps({"date": today, "data": data}, ensure_ascii=False))'
assert s.count(old) == 1, 'AVG_VOL write not found'
s = s.replace(old, new)
print(f'ok [{REL}] avg_vol atomic')

old = '                FLOAT_SHARES_CACHE.write_text(json.dumps({"date": today, "data": data}, ensure_ascii=False), encoding="utf-8")'
new = '                _atomic_write_text(FLOAT_SHARES_CACHE, json.dumps({"date": today, "data": data}, ensure_ascii=False))'
assert s.count(old) == 1, 'FLOAT_SHARES write not found'
s = s.replace(old, new)
print(f'ok [{REL}] float_shares atomic')

p.write_text(s, encoding='utf-8')
print('patch3 done')
