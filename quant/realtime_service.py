"""实时行情服务 — 全部走 TDXRS 协议"""
import os, sys, json, time, subprocess, threading, logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("realtime")
BASE_DIR = Path(__file__).parent.parent
CONFIG_FILE = BASE_DIR / "realtime_config.json"
TDXRS_FETCH = BASE_DIR / "tdxrs_fetch.py"
TDXRS_BLOCK = BASE_DIR / "tdxrs_block.py"
TDXRS_PYTHON = "/usr/bin/python3.11"
TDXRS_DIRECT = BASE_DIR / "tdxrs_fetch_direct.py"
KPH_DIR = BASE_DIR / "data" / "kph_sectors"
THEME_MAP_FILE = BASE_DIR / "data" / "stock_theme_map.json"
FLOAT_SHARES_CACHE = BASE_DIR / "data" / "float_shares_cache.json"
AVG_VOL_CACHE = BASE_DIR / "data" / "avg_vol_cache.json"

def _sf(val, default=0):
    """Safe float conversion - handles str, None, '-'"""
    if val is None or val == '' or val == '-':
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

DEFAULT_INDICES = [
    {"market": 1, "code": "000001", "name": "上证指数"},
    {"market": 0, "code": "399001", "name": "深证成指"},
    {"market": 0, "code": "399006", "name": "创业板指"},
    {"market": 1, "code": "000688", "name": "科创50"},
    {"market": 2, "code": "899050", "name": "北证50"},
    {"market": 1, "code": "000016", "name": "上证50"},
]


# ── TDXRS 直连（主进程加载，避免subprocess开销）──
# TDXRS servers (override via realtime_config.json tdxrs_servers field)
_DEFAULT_TDXRS_SERVERS = [
    # 上证云行情服务器（快照+K线验证正常，2026-09-23）
    ("117.34.114.14", 7709), ("117.34.114.15", 7709), ("117.34.114.16", 7709),
    ("117.34.114.17", 7709), ("117.34.114.18", 7709), ("117.34.114.20", 7709),
    ("117.34.114.27", 7709),
    # 原行情服务器兜底（快照近期受限）
    ("218.75.126.9", 7709), ("115.238.56.198", 7709),
    ("60.191.117.167", 7709), ("180.153.18.170", 7709),
]

def _load_tdxrs_servers():
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            servers = cfg.get("tdxrs_servers", [])
            if servers:
                return [(s["host"], s["port"]) for s in servers if "host" in s and "port" in s]
    except Exception:
        pass
    return _DEFAULT_TDXRS_SERVERS

_TDXRS_SERVERS = _load_tdxrs_servers()
_tdxrs_client = None
_tdxrs_lock = threading.Lock()

_tdxrs_fail_ts = 0.0


def _get_tdxrs_client():
    """获取或创建TDXRS连接（单例，复用连接；全部失败后 60s 冷却）"""
    global _tdxrs_client, _tdxrs_fail_ts
    with _tdxrs_lock:
        if _tdxrs_client is not None:
            return _tdxrs_client
    if _tdxrs_fail_ts and time.time() - _tdxrs_fail_ts < 60:
        return None
    # 尝试import tdxrs
    try:
        from tdxrs import TdxHqClient
    except ImportError:
        # importlib fallback
        import importlib.util
        so_path = "/opt/tdxrs-venv/lib/python3.11/site-packages/tdxrs/_internal.cpython-311-x86_64-linux-gnu.so"
        constants_path = "/opt/tdxrs-venv/lib/python3.11/site-packages/tdxrs/constants.py"
        if not os.path.exists(so_path):
            return None
        spec = importlib.util.spec_from_file_location("tdxrs._internal", so_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["tdxrs._internal"] = mod
        spec.loader.exec_module(mod)
        cspec = importlib.util.spec_from_file_location("tdxrs.constants", constants_path)
        cmod = importlib.util.module_from_spec(cspec)
        cspec.loader.exec_module(cmod)
        sys.modules["tdxrs.constants"] = cmod
        tdxrs_mod = type(sys)('tdxrs')
        tdxrs_mod.TdxHqClient = mod.TdxHqClient
        tdxrs_mod.constants = cmod
        sys.modules["tdxrs"] = tdxrs_mod
        TdxHqClient = mod.TdxHqClient
    # 连接
    client = TdxHqClient()
    for h, p in _TDXRS_SERVERS:
        try:
            if client.connect(h, p):
                with _tdxrs_lock:
                    _tdxrs_client = client
                logger.info("TDXRS直连成功: %s:%d" % (h, p))
                return client
        except Exception:
            continue
    _tdxrs_fail_ts = time.time()
    logger.warning("TDXRS直连失败，所有服务器不可达")
    return None


def _tdxrs_quotes(stock_list):
    """通过TDXRS直连获取5档行情（无subprocess开销）"""
    client = _get_tdxrs_client()
    if not client:
        return []
    try:
        from tdxrs.constants import MARKET_SH, MARKET_SZ
    except Exception:
        MARKET_SH, MARKET_SZ = 1, 0
    codes = []
    for s in stock_list:
        code = s.get("code", "") if isinstance(s, dict) else str(s)
        market = s.get("market", MARKET_SH if str(code).startswith("6") else MARKET_SZ) if isinstance(s, dict) else (MARKET_SH if str(code).startswith("6") else MARKET_SZ)
        codes.append((market, code))
    try:
        quotes = client.get_security_quotes(codes)
        results = []
        if not quotes:
            # 备用方案：行情快照返回空时，用分时数据(get_minute_time_data)获取价格和成交量
            logger.info("TDXRS行情快照为空，启用分时数据备用方案")
            for s in stock_list:
                code = s.get("code", "") if isinstance(s, dict) else str(s)
                market = s.get("market", MARKET_SH if str(code).startswith("6") else MARKET_SZ) if isinstance(s, dict) else (MARKET_SH if str(code).startswith("6") else MARKET_SZ)
                try:
                    timeline = client.get_minute_time_data(market, code)
                    if timeline:
                        latest = timeline[0]
                        price = latest.get("price", 0)
                        open_price = timeline[-1].get("price", price) if len(timeline) > 1 else price
                        high_price = max(m.get("price", 0) for m in timeline)
                        low_price = min(m.get("price", 0) for m in timeline if m.get("price", 0) > 0)
                        total_vol = sum(m.get("vol", 0) for m in timeline)
                        avg_price = latest.get("avg_price", price)
                        amount = total_vol * avg_price * 100
                        last_close = avg_price if avg_price > 0 else 1
                        # 从预测数据库获取流通股本，计算流通市值
                        circ_market = 0
                        try:
                            import sqlite3 as _sqlite3
                            _conn = _sqlite3.connect('/opt/stock-review/data/ipo_research.db', timeout=10)
                            _cur = _conn.cursor()
                            _cur.execute("SELECT float_shares FROM ipo_predictions WHERE code=?", (code,))
                            _row = _cur.fetchone()
                            if _row and _row[0]:
                                # float_shares单位是万股，转换为股：*10000
                                # 流通市值(元) = 流通股数(股) * 价格(元/股)
                                _float_shares_wan = float(_row[0])
                                circ_market = _float_shares_wan * 10000 * price
                            _conn.close()
                        except Exception as _e:
                            logger.warning(f"获取流通股本失败({code}): {_e}")
                        results.append({
                            "code": code,
                            "name": s.get("name", "") if isinstance(s, dict) else "",
                            "price": round(price, 2),
                            "open": round(open_price, 2),
                            "high": round(high_price, 2),
                            "low": round(low_price, 2),
                            "last_close": round(last_close, 2),
                            "volume": total_vol,
                            "amount": round(amount, 0),
                            "circ_market": round(circ_market, 0),
                            # 分时兜底无真实昨收（last_close 为均价占位），涨跌幅置 0 避免误导
                            "change_pct": 0,
                            "bid1": 0, "bid1_vol": 0,
                            "bid2": 0, "bid2_vol": 0,
                            "bid3": 0, "bid3_vol": 0,
                            "bid4": 0, "bid4_vol": 0,
                            "bid5": 0, "bid5_vol": 0,
                            "ask1": 0, "ask1_vol": 0,
                            "ask2": 0, "ask2_vol": 0,
                            "ask3": 0, "ask3_vol": 0,
                            "ask4": 0, "ask4_vol": 0,
                            "ask5": 0, "ask5_vol": 0,
                            "b_vol": total_vol, "s_vol": 0,
                        })
                except Exception as e:
                    logger.warning("分时数据备用方案失败(%s): %s" % (code, e))
                    continue
            # 用腾讯财经接口补充五档盘口数据
            try:
                import urllib.request as _ur
                # 构造腾讯财经代码（sz000001, sh600000）
                tencent_codes = []
                code_to_idx = {}
                for i, r in enumerate(results):
                    code = r.get("code", "")
                    if code:
                        prefix = "sh" if code.startswith("6") else "sz"
                        tencent_codes.append(f"{prefix}{code}")
                        code_to_idx[code] = i
                if tencent_codes:
                    t_url = f"http://qt.gtimg.cn/q={','.join(tencent_codes)}"
                    t_req = _ur.Request(t_url, headers={"User-Agent": "Mozilla/5.0"})
                    with _ur.urlopen(t_req, timeout=8) as t_resp:
                        t_data = t_resp.read().decode("gbk", errors="ignore")
                    # 解析每只股票
                    for line in t_data.strip().split(";"):
                        if "=" not in line:
                            continue
                        parts = line.split("=", 1)
                        if len(parts) != 2:
                            continue
                        t_code = parts[0].replace("v_", "").strip()
                        # 提取纯代码
                        pure_code = t_code[2:] if len(t_code) > 2 else t_code
                        if pure_code not in code_to_idx:
                            continue
                        vals = parts[1].strip('"').split("~")
                        if len(vals) < 29:
                            continue
                        idx = code_to_idx[pure_code]
                        # 腾讯字段: 3=最新价,4=昨收,5=今开,6=成交量(股),
                        # 9=买一价,10=买一量,11=买二价,12=买二量...
                        # 19=卖一价,20=卖一量,21=卖二价,22=卖二量...
                        # 33=最高,34=最低
                        try:
                            # 更新基础行情数据（用腾讯财经的准确数据覆盖分时数据构造的）
                            if vals[4]:  # 昨收
                                results[idx]["last_close"] = float(vals[4])
                            if vals[5]:  # 开盘
                                results[idx]["open"] = float(vals[5])
                            if len(vals) > 33 and vals[33]:  # 最高
                                results[idx]["high"] = float(vals[33])
                            if len(vals) > 34 and vals[34]:  # 最低
                                results[idx]["low"] = float(vals[34])
                            # 重新计算涨跌幅
                            if results[idx].get("last_close", 0) > 0:
                                results[idx]["change_pct"] = round(
                                    (results[idx].get("price", 0) - results[idx]["last_close"]) / results[idx]["last_close"] * 100, 2)
                            # 更新成交量（腾讯财经字段6单位是股，转成手除以100）
                            if len(vals) > 6 and vals[6]:
                                results[idx]["volume"] = round(float(vals[6]) / 100, 0)
                            # 外盘/内盘（字段7=外盘主买，字段8=内盘主卖，单位：股）
                            if len(vals) > 7 and vals[7]:
                                results[idx]["b_vol"] = round(float(vals[7]) / 100, 0)  # 外盘转手
                            if len(vals) > 8 and vals[8]:
                                results[idx]["s_vol"] = round(float(vals[8]) / 100, 0)  # 内盘转手
                            results[idx]["bid1"] = float(vals[9]) if vals[9] else 0
                            results[idx]["bid1_vol"] = int(float(vals[10])) if vals[10] else 0
                            results[idx]["bid2"] = float(vals[11]) if vals[11] else 0
                            results[idx]["bid2_vol"] = int(float(vals[12])) if vals[12] else 0
                            results[idx]["bid3"] = float(vals[13]) if vals[13] else 0
                            results[idx]["bid3_vol"] = int(float(vals[14])) if vals[14] else 0
                            results[idx]["bid4"] = float(vals[15]) if vals[15] else 0
                            results[idx]["bid4_vol"] = int(float(vals[16])) if vals[16] else 0
                            results[idx]["bid5"] = float(vals[17]) if vals[17] else 0
                            results[idx]["bid5_vol"] = int(float(vals[18])) if vals[18] else 0
                            results[idx]["ask1"] = float(vals[19]) if vals[19] else 0
                            results[idx]["ask1_vol"] = int(float(vals[20])) if vals[20] else 0
                            results[idx]["ask2"] = float(vals[21]) if vals[21] else 0
                            results[idx]["ask2_vol"] = int(float(vals[22])) if vals[22] else 0
                            results[idx]["ask3"] = float(vals[23]) if vals[23] else 0
                            results[idx]["ask3_vol"] = int(float(vals[24])) if vals[24] else 0
                            results[idx]["ask4"] = float(vals[25]) if vals[25] else 0
                            results[idx]["ask4_vol"] = int(float(vals[26])) if vals[26] else 0
                            results[idx]["ask5"] = float(vals[27]) if vals[27] else 0
                            results[idx]["ask5_vol"] = int(float(vals[28])) if vals[28] else 0
                        except (ValueError, IndexError):
                            pass
                    logger.info(f"腾讯财经补充盘口数据: {len([r for r in results if r.get('bid1')>0])}/{len(results)}只股票有盘口")
            except Exception as e:
                logger.warning(f"腾讯财经盘口补充失败: {e}")
            # 备用方案结束后，跳过下面的quotes循环直接返回
            return results
        # TDX快照不返回name，用自选股配置中的名称兜底
        _cfg_names = {}
        for _s in stock_list:
            _c = _s.get("code", "") if isinstance(_s, dict) else str(_s)
            _cfg_names[_c] = _s.get("name", "") if isinstance(_s, dict) else ""
        for q in quotes:
            last_close = q.get("last_close", 1) or 1
            price = q.get("price", 0)
            results.append({
                "code": q.get("code", ""),
                "name": q.get("name", "") or _cfg_names.get(str(q.get("code", "")), ""),
                "price": round(price, 2),
                "open": round(q.get("open", 0), 2),
                "high": round(q.get("high", 0), 2),
                "low": round(q.get("low", 0), 2),
                "last_close": round(last_close, 2),
                "volume": q.get("vol", 0),
                "amount": q.get("amount", 0),
                "change_pct": round((price - last_close) / last_close * 100, 2) if last_close else 0,
                "bid1": round(q.get("bid1", 0), 2), "bid1_vol": q.get("bid1_vol", q.get("bid_vol1", 0)),
                "bid2": round(q.get("bid2", 0), 2), "bid2_vol": q.get("bid2_vol", q.get("bid_vol2", 0)),
                "bid3": round(q.get("bid3", 0), 2), "bid3_vol": q.get("bid3_vol", q.get("bid_vol3", 0)),
                "bid4": round(q.get("bid4", 0), 2), "bid4_vol": q.get("bid4_vol", q.get("bid_vol4", 0)),
                "bid5": round(q.get("bid5", 0), 2), "bid5_vol": q.get("bid5_vol", q.get("bid_vol5", 0)),
                "ask1": round(q.get("ask1", 0), 2), "ask1_vol": q.get("ask1_vol", q.get("ask_vol1", 0)),
                "ask2": round(q.get("ask2", 0), 2), "ask2_vol": q.get("ask2_vol", q.get("ask_vol2", 0)),
                "ask3": round(q.get("ask3", 0), 2), "ask3_vol": q.get("ask3_vol", q.get("ask_vol3", 0)),
                "ask4": round(q.get("ask4", 0), 2), "ask4_vol": q.get("ask4_vol", q.get("ask_vol4", 0)),
                "ask5": round(q.get("ask5", 0), 2), "ask5_vol": q.get("ask5_vol", q.get("ask_vol5", 0)),
                "b_vol": q.get("b_vol", 0), "s_vol": q.get("s_vol", 0),
            })


        return results
    except Exception as e:
        logger.warning("TDXRS直连获取失败: %s" % e)
        # 连接断了就重置，下次重连
        with _tdxrs_lock:
            global _tdxrs_client
            _tdxrs_client = None
        return []


def _atomic_write_text(path, text: str):
    """原子写文件（tmp+rename），避免并发读到半截 JSON"""
    _p = Path(str(path))
    _tmp = Path(str(path) + ".tmp")
    _tmp.write_text(text, encoding="utf-8")
    _tmp.replace(_p)


def _load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception: pass
    return {"indices": [i["code"] for i in DEFAULT_INDICES], "sectors": [], "stocks": [], "poll_interval": 5}


def _save_config(cfg):
    try:
        _atomic_write_text(CONFIG_FILE, json.dumps(cfg, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.error(f"保存配置失败: {e}")


def _is_trade_time():
    """是否交易时段（统一口径：utils.is_trade_time_now，含午休与节假日判断）"""
    from utils import is_trade_time_now
    return is_trade_time_now()


def _to_thscode(code: str) -> str:
    """6位代码 -> 同花顺代码（600519.SH / 000001.SZ / 830799.BJ）"""
    code = str(code or "").strip().split(".")[0]
    if code.startswith("6") or code.startswith("9"):
        mkt = "SH"
    elif code.startswith(("0", "3")):
        mkt = "SZ"
    else:
        mkt = "BJ"
    return code + "." + mkt


def _run_script(script, args=None, timeout=30):
    cmd = [TDXRS_PYTHON, str(script)]
    if args: cmd.extend(args)
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = "/opt/tdxrs-venv/lib/python3.11/site-packages"
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        if result.returncode != 0:
            logger.warning(f"{script.name} 失败: {result.stderr[:200]}")
            return []
        data = json.loads(result.stdout) if result.stdout.strip() else []
        if not data and result.stderr:
            logger.info(f"{script.name} 返回空数据 stderr={result.stderr[:100]}")
        return data
    except Exception as e:
        logger.error(f"{script.name} 异常: {e}")
        return []


# ── levistock 熔断：连续失败后指数退避冷却，避免风控期每轮都打必败请求 ──
_LV_LOCK = threading.Lock()
_LV_FAIL = {}          # name -> 连续失败次数
_LV_COOLDOWN_TS = {}   # name -> 冷却截止时间戳


def _lv_skip(name: str) -> bool:
    """True = 该源处于冷却期，应跳过并直接走兜底"""
    with _LV_LOCK:
        return time.time() < _LV_COOLDOWN_TS.get(name, 0)


class _LvCooldownSkip(Exception):
    """内部哨兵：levistock 熔断冷却中，跳过本次尝试"""


def _lv_report(name: str, ok: bool):
    with _LV_LOCK:
        if ok:
            if _LV_FAIL.get(name):
                logger.info(f"levistock[{name}] 恢复正常")
            _LV_FAIL[name] = 0
            _LV_COOLDOWN_TS[name] = 0
            return
        n = _LV_FAIL.get(name, 0) + 1
        _LV_FAIL[name] = n
        if n >= 3:
            cool = min(60 * (2 ** min(n - 3, 5)), 1800)  # 60s 起指数退避，上限 30min
            _LV_COOLDOWN_TS[name] = time.time() + cool
            logger.warning(f"levistock[{name}] 连续失败{n}次，进入熔断冷却 {cool:.0f}s")


class RealtimeService:
    def __init__(self):
        self._lock = threading.Lock()
        self._fetch_lock = threading.Lock()   # 序列化远程拉取，防并发重复请求
        self._refresh_lock = threading.Lock()  # refresh_async 单飞
        self._refreshing = False
        self._cache = {"indices": [], "sectors": [], "stocks": [], "timestamp": None, "is_trade_time": False}
        self._cache_ts = 0.0
        self._config = _load_config()
        self._block_name_cache = {}
        self._running = False
        self._thread = None
        # vol_ratio缓冲：启动时从历史缓存加载20天全天成交额（元）
        self._amt_buffer = self._init_amt_buffer()
        self._amt_buffer_date = ""  # 当天全天成交额入账日期（每天只记一笔）
        self._last_bar_minute = ""   # 分钟采样去重（每分钟一行）

    def _init_amt_buffer(self):
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
        return buffer

    def fetch_indices(self):
        """获取指数实时行情（levistock东方财富API）"""
        if not _lv_skip("idx"):
            try:
                import sys as _sys
                _sys.path.insert(0, '/opt/levistock')
                import levistock as lk
                raw = lk.market_index_em()
                if raw:
                    _lv_report("idx", True)
                    return raw
                _lv_report("idx", False)
                logger.warning("指数获取失败(levistock): 返回空，走TDXRS兜底")
            except Exception as e:
                _lv_report("idx", False)
                logger.warning(f"指数获取失败(levistock): {e}")
        # TDXRS 直连（自建通道，不受东财风控影响）
        try:
            tdx_idx = _run_script(TDXRS_FETCH, ["indices"], timeout=30)
            if tdx_idx:
                logger.info("TDXRS指数获取%d只" % len(tdx_idx))
                return tdx_idx
        except Exception as e2:
            logger.warning(f"指数获取失败(TDXRS): {e2}")
        # 回退：腾讯行情（东财被风控时）
        try:
            from quant.tencent_data import fetch_indices_tencent
            idx = fetch_indices_tencent()
            if idx:
                logger.info("腾讯指数获取%d只" % len(idx))
                return idx
        except Exception as e3:
            logger.warning(f"指数获取失败(腾讯): {e3}")
        return []

    def fetch_stocks(self, stock_list=None):
        """获取自选股实时行情（优先TDXRS直连，包含完整五档盘口；失败回退levistock）"""
        if stock_list is None: stock_list = self._config.get("stocks", [])
        if not stock_list: return []
        # 优先用TDXRS直连获取完整行情（包含五档盘口）
        try:
            tdxrs_result = _tdxrs_quotes(stock_list)
            if tdxrs_result and len(tdxrs_result) > 0:
                # 检查是否有盘口数据
                has_orderbook = any(r.get("bid1", 0) > 0 for r in tdxrs_result)
                if has_orderbook:
                    logger.info(f"TDXRS获取{len(tdxrs_result)}只自选股行情（含盘口）")
                    return tdxrs_result
                else:
                    logger.warning(f"TDXRS行情无盘口数据，回退levistock")
        except Exception as e:
            logger.warning(f"TDXRS自选股获取失败: {e}")
        # 回退：levistock东方财富API
        codes = [s["code"] if isinstance(s, dict) else s for s in stock_list]
        if not _lv_skip("stk"):
            try:
                import sys as _sys
                _sys.path.insert(0, '/opt/levistock')
                import levistock as lk
                raw = lk.stocks_em(codes)
                if raw:
                    _lv_report("stk", True)
                    # 字段映射: levistock -> 前端期望格式 (code/name)
                    return [
                        {
                            "code": s.get("stock_code", ""),
                            "name": s.get("stock_name", ""),
                            "price": _sf(s.get("price")),
                            "change_pct": _sf(s.get("change_pct")),
                            "amount": _sf(s.get("amount")),
                            "volume": _sf(s.get("volume")),
                            "bid1": 0, "bid1_vol": 0, "bid2": 0, "bid2_vol": 0, "bid3": 0, "bid3_vol": 0,
                            "bid4": 0, "bid4_vol": 0, "bid5": 0, "bid5_vol": 0,
                            "ask1": 0, "ask1_vol": 0, "ask2": 0, "ask2_vol": 0, "ask3": 0, "ask3_vol": 0,
                            "ask4": 0, "ask4_vol": 0, "ask5": 0, "ask5_vol": 0,
                        }
                        for s in raw
                    ]
                _lv_report("stk", False)
            except Exception as e:
                _lv_report("stk", False)
                logger.warning(f"自选股获取失败(levistock): {e}")
        # 最终兑底：TDXRS 脚本
        return _run_script(TDXRS_FETCH, ["stocks", json.dumps(stock_list, ensure_ascii=False)])

    def fetch_sectors(self, sector_codes=None):
        """获取板块实时行情（TDX）"""
        if sector_codes is None: sector_codes = self._config.get("sectors", [])
        if not sector_codes: return []

        # 用 quotes 模式获取实时数据
        raw = _run_script(TDXRS_BLOCK, ["quotes", ",".join(sector_codes)])
        if not raw: return []

        # 补充名称
        if not self._block_name_cache:
            self._block_name_cache = self._load_block_names()

        results = []
        for q in raw:
            code = q.get("code", "")
            name = self._block_name_cache.get(code, code)
            results.append({
                "name": name, "code": code,
                "change_pct": q.get("change_pct", 0),
                "amount": round(q.get("amount", 0) / 1e8, 2),
                "leader": "", "leader_pct": 0,
            })
        return results

    def _load_block_names(self):
        """从 KPH 本地数据获取板块名称映射"""
        name_map = {}
        if KPH_DIR.exists():
            for f in sorted(KPH_DIR.glob("*.json"), reverse=True):
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                    for s in data.get("sectors", []):
                        pid = s.get("plate_id", "")
                        name = s.get("plate_name", "")
                        if pid and name:
                            name_map[pid] = name
                    if name_map:
                        break
                except Exception: continue
        return name_map

    def search_sectors(self, keyword=""):
        """搜索板块（KPH 本地数据）"""
        if not keyword:
            return []
        if not self._block_name_cache:
            self._block_name_cache = self._load_block_names()
        results = []
        for code, name in self._block_name_cache.items():
            if keyword in name:
                results.append({"code": code, "name": name})
        return results[:20]

    def resolve_sector_name(self, code):
        if not self._block_name_cache:
            self._block_name_cache = self._load_block_names()
        return self._block_name_cache.get(code, "")

    def resolve_stock_name(self, code):
        try:
            sl_file = BASE_DIR / "data" / "stock_list.json"
            with open(sl_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get(code, {}).get("name", "")
        except Exception: return ""

    def _load_latest_review(self):
        """加载最新review JSON（用于收盘后读取sentiment/profit）"""
        reports_dir = BASE_DIR / "reports"
        if not reports_dir.exists():
            return None
        jsons = sorted(reports_dir.glob("review_*.json"), reverse=True)
        for jf in jsons[:1]:
            try:
                with open(jf, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def refresh_cache(self):
        """同步拉取并更新缓存（轮询线程/写操作后使用）；并发调用串行化"""
        with self._fetch_lock:
            indices = self.fetch_indices()
            stocks = self.fetch_stocks()
            sectors = self.fetch_sectors()
            now = datetime.now()
            is_trade = _is_trade_time()
            with self._lock:
                self._cache = {"indices": indices, "sectors": sectors, "stocks": stocks,
                              "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"), "is_trade_time": is_trade}
                self._cache_ts = time.time()
                return dict(self._cache)

    def refresh_async(self):
        """后台刷新（单飞）：请求路径永不等待远程拉取"""
        with self._refresh_lock:
            if self._refreshing:
                return
            self._refreshing = True

        def _bg():
            try:
                self.refresh_cache()
            except Exception as e:
                logger.warning(f"后台刷新失败: {e}")
            finally:
                with self._refresh_lock:
                    self._refreshing = False

        threading.Thread(target=_bg, daemon=True, name="rt-refresh").start()

    def get_snapshot(self):
        now = datetime.now()
        is_trade = _is_trade_time()
        if not is_trade and self._cache.get("timestamp"):
            return self._cache
        # 请求端只读缓存；缓存超过 2×间隔 时后台刷新并立即返回旧数据（不阻塞请求）
        with self._lock:
            _interval = float(self._config.get("poll_interval", 5) or 5)
            _age = (time.time() - self._cache_ts) if self._cache_ts else 1e9
            cached = dict(self._cache)
        if _age < max(_interval * 2, 10):
            return cached
        if cached.get("timestamp"):
            self.refresh_async()
            return cached
        # 冷启动：无任何缓存时同步拉一次
        return self.refresh_cache()

    def _save_minute_bar(self, force: bool = False):
        """每分钟落一行轻量盘中快照（不依赖页面是否打开）

        供量能对比曲线 / 盘中图表使用；同分钟去重；字段为完整快照的子集，读取方兼容。
        """
        try:
            now = datetime.now()
            if not force and not _is_trade_time():
                return
            minute = now.strftime("%H:%M")
            if self._last_bar_minute == minute:
                return
            quotes = self.fetch_full_market()
            if not quotes:
                return
            from utils import get_limit_threshold, _limit_price
            total_amount = 0.0
            up = down = flat = zt = 0
            for q in quotes:
                total_amount += q.get("amount", 0) or 0
                pct = q.get("change_pct", 0) or 0
                if pct > 0:
                    up += 1
                elif pct < 0:
                    down += 1
                else:
                    flat += 1
                code = str(q.get("code", ""))
                name = q.get("name", "")
                price = q.get("price", 0) or 0
                lc = q.get("last_close", 0) or 0
                if price > 0 and lc > 0 and price >= _limit_price(lc, get_limit_threshold(code, name)):
                    zt += 1
            bar = {
                "time": now.strftime("%H:%M:%S"),
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                "total_amount_yi": round(total_amount / 1e8, 1),
                "total_up": up,
                "total_down": down,
                "total_flat": flat,
                "total_stocks": len(quotes),
                "limit_up_count": zt,
                "minute_bar": True,
            }
            log_dir = BASE_DIR / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            fp = log_dir / ("intraday_%s.jsonl" % now.strftime("%Y%m%d"))
            with open(fp, "a", encoding="utf-8") as f:
                print(json.dumps(bar, ensure_ascii=False), file=f)
            self._last_bar_minute = minute
        except Exception as e:
            logger.warning("分钟快照落盘失败: %s" % e)

    def start_polling(self, interval=None):
        if self._running: return
        if interval is None: interval = self._config.get("poll_interval", 5)
        self._running = True
        def _poll_loop():
            logger.info(f"实时轮询启动，间隔 {interval}s")
            while self._running:
                try:
                    if _is_trade_time():
                        self.refresh_cache()
                        self._save_minute_bar()
                    else:
                        time.sleep(30)
                        continue
                except Exception as e:
                    logger.error("轮询异常: %s" % e)
                    time.sleep(5)
                    continue
                time.sleep(interval)
        self._thread = threading.Thread(target=_poll_loop, daemon=True, name="realtime-poll")
        self._thread.start()

        # 新股盘口监控由 crontab 管理的 screen 会话独立运行（避免数据库锁竞争）

    def stop_polling(self): self._running = False
    def get_config(self): return dict(self._config)

    def update_config(self, patch):
        with self._lock:
            for k in ["sectors", "stocks", "poll_interval"]:
                if k in patch: self._config[k] = patch[k]
            _save_config(self._config)
            return dict(self._config)

    def add_sector(self, code, name=""):
        with self._lock:
            if code not in self._config["sectors"]:
                self._config["sectors"].append(code)
                _save_config(self._config)
                self._cache = {"indices": [], "sectors": [], "stocks": [], "timestamp": None, "is_trade_time": False}
                self._cache_ts = 0.0
            return {"added": code, "name": name, "sectors": self._config["sectors"]}

    def remove_sector(self, code):
        with self._lock:
            if code in self._config["sectors"]:
                self._config["sectors"].remove(code)
                _save_config(self._config)
                self._cache = {"indices": [], "sectors": [], "stocks": [], "timestamp": None, "is_trade_time": False}
                self._cache_ts = 0.0
            return {"removed": code, "sectors": self._config["sectors"]}

    def add_stock(self, code, name, market):
        with self._lock:
            for s in self._config["stocks"]:
                if s["code"] == code: return {"error": f"{name}({code}) 已在监控中"}
            self._config["stocks"].append({"code": code, "name": name, "market": market})
            _save_config(self._config)
            self._cache = {"indices": [], "sectors": [], "stocks": [], "timestamp": None, "is_trade_time": False}
            self._cache_ts = 0.0
            return {"added": code, "stocks": self._config["stocks"]}

    def remove_stock(self, code):
        with self._lock:
            self._config["stocks"] = [s for s in self._config["stocks"] if s["code"] != code]
            _save_config(self._config)
            self._cache = {"indices": [], "sectors": [], "stocks": [], "timestamp": None, "is_trade_time": False}
            self._cache_ts = 0.0
            return {"removed": code, "stocks": self._config["stocks"]}

    # ══════════════════════════════════════════════════════════
    #  全市场分析（替代 intraday_monitor.py）
    # ══════════════════════════════════════════════════════════

    def fetch_full_market(self):
        """获取全市场A股行情（levistock东方财富API）

        交易时间: 每次实时获取（~3秒），不走缓存
        非交易时间: 使用日级缓存（避免重复请求）
        """
        today = datetime.now().strftime("%Y%m%d")
        cache_file = BASE_DIR / "data" / "realtime_market_cache.json"

        # 非交易时间读缓存
        if not _is_trade_time():
            if cache_file.exists():
                try:
                    cached = json.loads(cache_file.read_text(encoding="utf-8"))
                    if (cached.get("date") == today
                            and len(cached.get("data", [])) > 4000
                            and any(s.get("amount", 0) > 0 for s in cached["data"][:100])):
                        return cached["data"]
                except Exception:
                    pass

        # levistock获取全量A股（filter_st=False包含ST股）
        try:
            if _lv_skip("mkt"):
                raise _LvCooldownSkip()
            import sys as _sys
            _sys.path.insert(0, '/opt/levistock')
            import levistock as lk
            raw = lk.stocks_all_em(filter_st=False)
            if not raw:
                raise RuntimeError("levistock全市场返回空")

            # 字段映射: levistock -> 内部格式
            # levistock自带 pre_close/high/low/open，无需反算
            quotes = []
            for s in raw:
                code = s.get("stock_code", "")
                # A股过滤: code以0/3/6/8/9开头（包含北交所8xxxxx/920xxx）
                if not code or code[0] not in ('0', '3', '6', '8', '9'):
                    continue
                price = _sf(s.get("price"))
                if price <= 0:
                    continue
                quotes.append({
                    "code": code,
                    "name": s.get("stock_name", ""),
                    "price": price,
                    "last_close": _sf(s.get("pre_close")),
                    "high": _sf(s.get("high")),
                    "low": _sf(s.get("low")),
                    "open": _sf(s.get("open")),
                    "amount": _sf(s.get("amount")),
                    "volume": _sf(s.get("volume")),
                    "change_pct": _sf(s.get("change_pct")),
                })

            if quotes:
                logger.info("levistock获取%d只A股, 成交额%.0f亿" % (
                    len(quotes), sum(q["amount"] for q in quotes) / 1e8))

                # 补充北交所数据（levistock stocks_all_em不含北交所）
                try:
                    import requests as _req
                    bj_url = (
                        "http://push2delay.eastmoney.com/api/qt/clist/get"
                        "?pn=1&pz=500&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281"
                        "&fltt=2&invt=2&wbp2u=|0|0|0|web"
                        "&fid=f3&fs=m:0+t:81+s:2048"
                        "&fields=f2,f3,f4,f5,f6,f7,f12,f14,f15,f16,f17,f18,f20,f21"
                    )
                    resp = _req.get(bj_url, timeout=10)
                    bj_data = resp.json().get('data', {}).get('diff', []) or []
                    for s in bj_data:
                        code = str(s.get('f12', ''))
                        if not code:
                            continue
                        price = _sf(s.get('f2'))
                        last_close = _sf(s.get('f18'))
                        if price <= 0:
                            continue
                        quotes.append({
                            "code": code,
                            "name": str(s.get('f14', '')),
                            "price": price,
                            "last_close": last_close,
                            "high": _sf(s.get('f15')),
                            "low": _sf(s.get('f16')),
                            "open": _sf(s.get('f17')),
                            "amount": _sf(s.get('f6')),
                            "volume": _sf(s.get('f5')),
                            "change_pct": _sf(s.get('f3')),
                        })
                    if bj_data:
                        logger.info("补充北交所%d只, 总A股%d只, 总成交额%.0f亿" % (
                            len(bj_data), len(quotes), sum(q["amount"] for q in quotes) / 1e8))
                except Exception as e:
                    logger.warning("北交所数据获取失败: %s" % e)

                try:
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    _atomic_write_text(
                        cache_file,
                        json.dumps({"date": today, "data": quotes}, ensure_ascii=False),
                    )
                except Exception:
                    pass

            _lv_report("mkt", True)
            return quotes
        except _LvCooldownSkip:
            pass  # 熔断冷却中，直接走腾讯兑底
        except Exception as e:
            _lv_report("mkt", False)
            logger.warning(f"levistock全市场获取失败: {e}")
        # 回退：腾讯行情（东财被风控时）
        try:
            from quant.tencent_data import fetch_full_market_tencent
            quotes = fetch_full_market_tencent()
            if quotes:
                logger.info("腾讯全市场获取%d只, 成交额%.0f亿" % (
                    len(quotes), sum(q["amount"] for q in quotes) / 1e8))
                try:
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    _atomic_write_text(
                        cache_file,
                        json.dumps({"date": today, "data": quotes}, ensure_ascii=False),
                    )
                except Exception:
                    pass
                return quotes
        except Exception as e2:
            logger.warning(f"腾讯全市场获取失败: {e2}")
        return []

    def fetch_avg_volumes(self):
        """获取全市场5日均量（缓存到磁盘）"""
        today = datetime.now().strftime("%Y%m%d")
        if AVG_VOL_CACHE.exists():
            try:
                cached = json.loads(AVG_VOL_CACHE.read_text(encoding="utf-8"))
                if cached.get("date") == today and len(cached.get("data", {})) > 3000:
                    return cached["data"]
            except Exception:
                pass
        data = _run_script(TDXRS_FETCH, ["avg_volumes"], timeout=300)
        if data:
            try:
                AVG_VOL_CACHE.parent.mkdir(parents=True, exist_ok=True)
                _atomic_write_text(AVG_VOL_CACHE, json.dumps({"date": today, "data": data}, ensure_ascii=False))
            except Exception:
                pass
        return data

    def fetch_float_shares(self):
        """获取全市场流通股本（万股，缓存到磁盘）

        韧性策略：levistock -> 腾讯 -> 近7天磁盘缓存兜底（流通股本变化缓慢）
        """
        today = datetime.now().strftime("%Y%m%d")

        # 0) tdxrs 通达信后端缓存（最稳，盘前cron预热；当天优先，近7天兜底）
        try:
            _rs_fp = BASE_DIR / "data" / "float_shares_rs.json"
            if _rs_fp.exists():
                _rs = json.loads(_rs_fp.read_text(encoding="utf-8"))
                _rs_data = _rs.get("data") or {}
                if len(_rs_data) > 3000:
                    _rs_age = (datetime.now().date() -
                               datetime.strptime(str(_rs.get("date")), "%Y%m%d").date()).days
                    if 0 <= _rs_age <= 7:
                        logger.info("流通股本使用tdxrs缓存(%s,%d只)" % (_rs.get("date"), len(_rs_data)))
                        return _rs_data
        except Exception:
            pass

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

    def load_theme_map(self):
        """加载主题映射"""
        if THEME_MAP_FILE.exists():
            try:
                return json.loads(THEME_MAP_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def get_name_map(self):
        """从 stock_list.json 获取 code→name 映射"""
        sl_file = BASE_DIR / "data" / "stock_list.json"
        if sl_file.exists():
            try:
                data = json.loads(sl_file.read_text(encoding="utf-8"))
                return {code: info.get("name", "") for code, info in data.items()}
            except Exception:
                pass
        return {}

    def _fetch_kph_realtime(self):
        """获取KPH精选板块实时排行（通过levistock）"""
        try:
            import sys as _sys
            _sys.path.insert(0, '/opt/levistock')
            import levistock as lk
            sectors = lk.sector_ranking_kph(
                date=datetime.now().strftime("%Y-%m-%d"),
                zs_type=lk.SECTOR_SELECTED
            )
            if not sectors:
                return []
            results = []
            for i, s in enumerate(sectors[:10]):
                # 日净流入 = buy_amount + sell_amount（元→亿）
                buy = s.get("buy_amount", 0)
                sell = s.get("sell_amount", 0)
                daily_net = (buy + sell) / 1e8 if (buy or sell) else 0
                # 龙头股：从stocks中提取rank_tag
                leaders = []
                for st in s.get("stocks", []):
                    rt = st.get("rank_tag", "")
                    if rt and st.get("name"):
                        leaders.append("%s%s" % (rt, st["name"]))
                results.append({
                    "rank": i + 1,
                    "name": s.get("plate_name", ""),
                    "amount": s.get("amount", 0),
                    "change_pct": s.get("change_pct", 0),
                    "turnover_rate": s.get("turnover_rate", 0),
                    "net_inflow": round(daily_net, 2),
                    "leaders": " ".join(leaders[:3]),
                })
            return results
        except Exception as e:
            logger.warning(f"KPH实时数据获取失败: {e}")
            # fallback: 从本地KPH数据读取
            return self._load_kph_from_cache()

    def _load_kph_from_cache(self):
        """从本地KPH缓存读取（非交易时间fallback）"""
        results = []
        if KPH_DIR.exists():
            for f in sorted(KPH_DIR.glob("*.json"), reverse=True):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    for i, s in enumerate(data.get("sectors", [])[:10]):
                        buy = s.get("buy_amount", 0)
                        sell = s.get("sell_amount", 0)
                        daily_net = (buy + sell) / 1e8 if (buy or sell) else 0
                        leaders = []
                        for st in s.get("stocks", []):
                            rt = st.get("rank_tag", "")
                            if rt and st.get("name"):
                                leaders.append("%s%s" % (rt, st["name"]))
                        results.append({
                            "rank": i + 1,
                            "name": s.get("plate_name", ""),
                    "amount": s.get("amount", 0),
                            "change_pct": s.get("change_pct", 0),
                            "turnover_rate": s.get("turnover_rate", 0),
                            "net_inflow": round(daily_net, 2),
                            "leaders": " ".join(leaders[:3]),
                            "date": data.get("date", ""),
                        })
                    if results:
                        break
                except Exception:
                    continue
        return results

    def _fetch_zt_ladder(self):
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

    def _fetch_yesterday_zt(self, quotes=None):
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

    def run_analysis(self):
        """全市场分析：行情 + 信号检测 + KPH板块"""
        from quant.realtime_signals import (
            analyze_market, BrokenResealTracker, analyze_chain_gap,
            CapitalShiftTracker, check_cross_signals, load_prev_review, save_snapshot,
            is_trading_time,
        )
        from quant.intraday_sentiment import compute_intraday_scores

        t0 = time.time()
        name_map = self.get_name_map()
        theme_map = self.load_theme_map()

        # 获取全市场行情
        quotes = self.fetch_full_market()
        if not quotes:
            return {"error": "行情获取失败"}

        # 核心分析
        result = analyze_market(quotes, name_map, theme_map)

        # KPH板块实时排行（用缓存数据补全leaders）
        kph_sectors = self._fetch_kph_realtime()
        if kph_sectors:
            cached = self._load_kph_from_cache()
            cached_leaders = {s["name"]: s.get("leaders", "") for s in cached}
            for s in kph_sectors:
                if not s.get("leaders"):
                    s["leaders"] = cached_leaders.get(s["name"], "")
        result["kph_sectors"] = kph_sectors

        # 昨日涨停/连板（levistock东方财富API）
        yz_data = self._fetch_yesterday_zt(quotes)
        if yz_data is not None:
            result["yesterday_zt_count"] = yz_data["zt_count"]
            result["yesterday_zt_avg_pct"] = yz_data["zt_avg_pct"]
            result["yesterday_cont_count"] = yz_data["cont_count"]
            result["yesterday_cont_avg_pct"] = yz_data["cont_avg_pct"]

        # 连板梯队
        ladder_data = self._fetch_zt_ladder()
        if ladder_data is not None:
            result["zt_ladder"] = ladder_data["ladder"]
            result["zt_total"] = ladder_data["total_zt"]
            result["zt_highest"] = ladder_data["highest"]

        # 日级别情绪分 + 赚钱效应分（流通股本缺失时降级；赚钱效应不依赖流通股本）
        float_shares = self.fetch_float_shares() or {}
        scores = compute_intraday_scores(quotes, name_map, theme_map, float_shares)
        if scores:
            result.update({
                "sentiment_score": scores["sentiment_score"],
                "sentiment_raw": scores["sentiment_raw"],
                "sentiment_level": scores["sentiment_level"],
                "sentiment_details": scores["sentiment_details"],
                "vol_penalty": scores["vol_penalty"],
                "vol_note": scores["vol_note"],
                "profit_score": scores["profit_score"],
                "profit_raw": scores["profit_raw"],
                "profit_level": scores["profit_level"],
                "profit_details": scores["profit_details"],
                "mood": scores["sentiment_level"],
                "zt_count": scores["zt_count"],
                "zb_count": scores["zb_count"],
                "zb_rate": scores["zb_rate"],
                "dt_count": scores["dt_count"],
            })

        # 收盘后：从最新review覆盖sentiment/profit（review是权威数据源）
        if not is_trading_time():
            latest_review = self._load_latest_review()
            if latest_review:
                if latest_review.get("sentiment_score") is not None:
                    result["sentiment_score"] = latest_review["sentiment_score"]
                if latest_review.get("profit_score") is not None:
                    result["profit_score"] = latest_review["profit_score"]
                if latest_review.get("cycle_label"):
                    result["mood"] = latest_review.get("cycle_label", result.get("mood", ""))

        # 信号检测
        if not hasattr(self, '_reseal_tracker'):
            self._reseal_tracker = BrokenResealTracker()
        if not hasattr(self, '_capital_tracker'):
            self._capital_tracker = CapitalShiftTracker()

        reseal_result = self._reseal_tracker.detect(result)
        chain_gap = analyze_chain_gap(result)
        capital_shift = self._capital_tracker.detect(result)
        prev_review = load_prev_review()
        cross_signals = check_cross_signals(result, prev_review)

        # 盘中信号引擎（时间序列追踪+多维信号）
        from quant.realtime_signals import SignalEngine
        if not hasattr(self, '_signal_engine'):
            self._signal_engine = SignalEngine()
        strategy_signals = self._signal_engine.process(result, kph_sectors, None, prev_review)
        sentiment_history = self._signal_engine.get_sentiment_history()

        # ── 实时预测：5因子计算 ──
        realtime_prediction = self._compute_realtime_prediction(result, kph_sectors)

        # 组装输出
        result.update({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "is_trade_time": is_trading_time(),
            "elapsed": round(time.time() - t0, 1),
            "reseal": reseal_result,
            "chain_gap": chain_gap,
            "capital_shift": capital_shift,
            "cross_signals": cross_signals,
            "strategy_signals": strategy_signals,
            "sentiment_history": sentiment_history,
            "realtime_prediction": realtime_prediction,
        })

        # 保存快照
        save_snapshot(result)

        return result

    # ══════════════════════════════════════════════════════════
    #  实时预测：5因子计算
    # ══════════════════════════════════════════════════════════

    def _compute_realtime_prediction(self, result, kph_sectors):
        """从实时数据计算5因子并生成预测"""
        from quant.prediction_engine import (
            predict_sentiment_direction, predict_style_change,
            calc_target_position, _describe_factors, _estimate_composite_range
        )

        # F1: composite
        sentiment = result.get('sentiment_score', 50) or 50
        profit = result.get('profit_score', 50) or 50
        composite = sentiment * 0.4 + profit * 0.6

        # F2: vol_ratio（当日成交额 / 前20日全天均量；盘中按已交易分钟折算成全天口径）
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
                self._amt_buffer = self._amt_buffer[-25:]

        # F3: concentration（KPH板块强度占比）
        concentration = 50
        if kph_sectors and len(kph_sectors) >= 3:
            top1 = kph_sectors[0].get('amount', 0)
            total10 = sum(s.get('amount', 0) for s in kph_sectors[:10])
            concentration = (top1 / total10 * 100) if total10 > 0 else 50
        conc_valid = True
        # 极端场景标记
        zt_count = result.get('limit_up_count', 0)
        if zt_count < 15 and len(kph_sectors or []) < 3:
            conc_valid = False

        # F4: pool_composite（从KPH板块涨跌推算）
        pool_state = "中性"
        pool_divergence = 0.5
        if kph_sectors and len(kph_sectors) >= 3:
            top3_changes = [s.get('change_pct', 0) for s in kph_sectors[:3]]
            avg_change = sum(top3_changes) / 3
            all_changes = [s.get('change_pct', 0) for s in kph_sectors[:10]]
            if len(all_changes) > 1:
                mean_c = sum(all_changes) / len(all_changes)
                pool_divergence = min(1, max(0, (sum((c - mean_c)**2 for c in all_changes) / len(all_changes)) ** 0.5 / 5))

            if avg_change > 3: pool_state = "大涨"
            elif avg_change > 0: pool_state = "微涨"
            elif avg_change > -3: pool_state = "微跌"
            else: pool_state = "大跌"

        pool_state_map = {"大跌": 0, "微跌": 25, "微涨": 75, "大涨": 100}
        pool_score = pool_state_map.get(pool_state, 50)
        pool_composite = pool_score * 0.6 + (1 - pool_divergence) * 100 * 0.4

        # F5: exp_gap（预期差）
        exp_gap = 0
        yesterday_cycle = "中性"
        yesterday_composite = 50
        try:
            from data import load_review, get_available_dates
            dates = get_available_dates()
            if dates:
                prev = load_review(dates[-1]["date"])
                if prev:
                    yesterday_composite = prev.get('composite', 50)
                    cycle_label = prev.get('cycle_label', '')
                    for key in ["冰点", "过热", "偏冷", "偏暖", "反弹", "上升", "分歧", "下降"]:
                        if key in cycle_label:
                            yesterday_cycle = key
                            break
            from config.prediction_rules import EXPECTED_MAP
            expected_range = EXPECTED_MAP.get(yesterday_cycle, (45, 60))
            yesterday_expected = (expected_range[0] + expected_range[1]) / 2
            exp_gap = composite - yesterday_expected
        except Exception:
            pass

        # 构建因子字典
        factors = {
            'composite': composite,
            'vol_ratio': vol_ratio,
            'concentration': concentration,
            'pool_composite': pool_composite,
            'pool_divergence': pool_divergence,
            'exp_gap': exp_gap,
        }

        # 规则树预测
        pred_dir, pred_conf, pred_rule, pred_reason = predict_sentiment_direction(factors)
        pred_style, style_conf, style_rule, style_reason = predict_style_change(factors)
        factors['_pred_confidence'] = pred_conf
        pred_position = calc_target_position(pred_dir, pred_style, factors)
        factor_descs = _describe_factors(factors)
        expected_range = _estimate_composite_range(pred_dir, composite, exp_gap)

        return {
            'composite': round(composite, 1),
            'factors': {
                'composite': round(composite, 1),
                'vol_ratio': round(vol_ratio, 2),
                'concentration': round(concentration, 1),
                'pool_composite': round(pool_composite, 1),
                'pool_divergence': round(pool_divergence, 3),
                'exp_gap': round(exp_gap, 1),
            },
            'sentiment': {
                'direction': pred_dir,
                'confidence': pred_conf,
                'rule': pred_rule,
                'reason': pred_reason,
                'expected_range': expected_range,
            },
            'style': {
                'result': pred_style,
                'confidence': style_conf,
                'rule': style_rule,
                'reason': style_reason,
            },
            'factor_descs': factor_descs,
            'position': pred_position,
        }

    # ══════════════════════════════════════════════════════════
    #  自选股盘口深度分析
    # ══════════════════════════════════════════════════════════

    def fetch_watchlist_detail(self):
        """获取自选股行情数据（TDXRS直连 优先 → subprocess fallback → levistock fallback）"""
        stock_list = self._config.get("stocks", [])
        if not stock_list:
            return []
        # 优先：TDXRS直连（零subprocess开销）
        result = _tdxrs_quotes(stock_list)
        if result:
            return result
        # fallback: subprocess调用
        codes = [{"market": s.get("market", 0), "code": s["code"]} for s in stock_list if s.get("code")]
        result = _run_script(TDXRS_DIRECT, ["quotes_detail", json.dumps(codes)])
        if result:
            return result
        # fallback: levistock基础行情
        code_list = [s["code"] for s in stock_list if s.get("code")]
        try:
            import sys as _sys
            _sys.path.insert(0, '/opt/levistock')
            import levistock as lk
            raw = lk.stocks_em(code_list)
            if not raw:
                return []
            mapped = []
            for s in raw:
                entry = {
                    "code": s.get("stock_code", ""),
                    "name": s.get("stock_name", ""),
                    "price": _sf(s.get("price")),
                    "change_pct": _sf(s.get("change_pct")),
                    "volume": _sf(s.get("volume")),
                    "amount": _sf(s.get("amount")),
                    "b_vol": 0, "s_vol": 0,
                }
                for i in range(1, 6):
                    entry["bid%d" % i] = 0
                    entry["bid_vol%d" % i] = 0
                    entry["ask%d" % i] = 0
                    entry["ask_vol%d" % i] = 0
                mapped.append(entry)
            return mapped
        except Exception as e:
            logger.warning("levistock自选股行情获取失败: %s" % e)
            return []

    def get_watchlist_detail(self):
        """自选股盘口深度分析"""
        from quant.realtime_signals import WatchlistOrderTracker

        if not hasattr(self, '_order_tracker'):
            self._order_tracker = WatchlistOrderTracker()

        detail_quotes = self.fetch_watchlist_detail()
        if not detail_quotes:
            return {"stocks": [], "message": "无自选股数据"}

        analysis = self._order_tracker.analyze(detail_quotes)
        return {"stocks": list(analysis.values())}

_service = None
_service_lock = threading.Lock()

def get_service():
    global _service
    if _service is None:
        with _service_lock:
            if _service is None: _service = RealtimeService()
    return _service
