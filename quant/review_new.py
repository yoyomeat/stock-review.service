#!/usr/bin/env python3
"""
情绪流复盘引擎 v3.6.0
入口模块 — 数据加载 + run_single + CLI

核心计算已拆分到独立模块：
  - cycle.py: 情绪/板块计算
  - position.py: 仓位/风格/抱团
  - plan.py: 交易计划/报告
  - mainline.py: 主线板块状态机
  - data_loader.py: 共享数据加载
"""

import sys
import os
import csv
import json
import ssl
import time
import urllib.request
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils import sf, is_zt, is_trading_day, get_prev_trading_day, get_prev_trading_days
try:
    from deviation import calc_deviation, build_known_codes
except ImportError:
    calc_deviation = None
    build_known_codes = None
try:
    from weight_trend import run as weight_trend_run
except ImportError:
    weight_trend_run = None

# 拆分模块
from anchor_monitor import build_mainline_info
import dataclasses
from quant.mainline_tracker import MainlineTracker, MainlineState, is_mainline
from anchor_monitor import (
    detect_concentration_signal, detect_all_signals, _load_kph_data,
    compute_strong_pool, check_leader_break, _build_code_to_plate,
    compute_pool_state, compute_composition, resolve_style, compute_prev_pool_state,
    ConcentrationState, verify_early_feedback, _get_plate_top_leader, compute_sub_tag,
    detect_signals, detect_trend_signal,
)
from action_router import STYLE_ACTION, ACTION_POS_MULT

# 别名映射
_cps = compute_pool_state
_cc = compute_composition
_rs = resolve_style
_cpps = compute_prev_pool_state

from sentiment import (
    preprocess, calc_emotion_vars, calc_sentiment, calc_profit,
    _clear_sorted_cache as _cycle_clear_sorted_cache,
)
from leaders import calc_sector, calc_leaders
from quant.position import (
    calc_leading_effect,
)
from cluster import calc_big_volume_cluster, calc_chain_cluster
from intraday_sentiment import save_daily_cache
from plan import (
    build_report, format_trade_plan_text,
    generate_trade_plan, save_report, build_meta,
    load_prev_meta, validate_yesterday, build_json_output,
)
from data_validator import validate_data_quality, get_quality_for_json


# ════════════════════════════════════════════════════════
# 配置
# ════════════════════════════════════════════════════════
VERSION = '情绪流复盘引擎 v3.6.0'
DATA_URL = "https://flashylife.cn/file/stocks/stock_daily_{date}.csv"
DEFAULT_DIR = '/opt/stock-review/data/csv'
DEFAULT_REPORT_DIR = '/opt/stock-review/reports'
CSV_PATTERN = "stock_daily_{date}.csv"
LOOKBACK_DAYS = 20  # 需要前几个交易日的数据（MA20需要至少20天）
DATA_START_DATE = '20250102'  # 本程序最早可用数据日期（之前的不用尝试）

# ════════════════════════════════════════════════════════
# 交易日历
# ════════════════════════════════════════════════════════
# 节假日从外部 JSON 加载（便于每年更新，无需改代码）
_HOLIDAYS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'holidays.json')
try:
    with open(_HOLIDAYS_PATH, 'r') as _hf:
        _HOLIDAYS = set(json.load(_hf))
except (FileNotFoundError, json.JSONDecodeError):
    _HOLIDAYS = set()
    print(f"⚠️ 节假日文件缺失: {_HOLIDAYS_PATH}，交易日历功能不可用", file=sys.stderr)
_CALENDAR_MAX_YEAR = max(int(d[:4]) for d in _HOLIDAYS) if _HOLIDAYS else 2026



def get_prev_date(date_str):
    """兼容旧接口"""
    return get_prev_trading_day(date_str)

# 全局SSL context（创建一次，复用）
_SSL_CTX = ssl.create_default_context()
# _SSL_CTX.check_hostname = False  # FIXED: re-enabled
# _SSL_CTX.verify_mode = ssl.CERT_NONE  # FIXED: re-enabled

# ════════════════════════════════════════════════════════
# 概念板块映射（同花顺数据，个股→概念 映射）
# ════════════════════════════════════════════════════════
_CONCEPT_MAP = None
_SECTOR_HIERARCHY = None

def download_csv(date_str: str, csv_dir: str) -> str | None:
    """下载指定日期的CSV，返回本地路径或None（失败自动重试1次）"""
    os.makedirs(csv_dir, exist_ok=True)
    local_path = os.path.join(csv_dir, CSV_PATTERN.format(date=date_str))

    if os.path.exists(local_path):
        print(f"  ✓ 已存在: {local_path}", file=sys.stderr)
        return local_path

    url = DATA_URL.format(date=date_str)
    for attempt in range(2):
        try:
            if attempt > 0:
                print(f"  ↻ 重试({attempt+1}/2): {url}", file=sys.stderr)
            else:
                print(f"  ↓ 下载: {url}", file=sys.stderr)
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=_SSL_CTX, timeout=30) as resp:
                data = resp.read()
            with open(local_path, 'wb') as f:
                f.write(data)
            if len(data) < 100:
                print(f"  ✗ 文件过小({len(data)}字节)，可能无数据: {date_str}", file=sys.stderr)
                os.remove(local_path)
                return None
            print(f"  ✓ 下载完成: {local_path} ({len(data)//1024}KB)", file=sys.stderr)
            return local_path
        except (IOError, OSError, TimeoutError, ValueError) as e:
            if attempt == 0:
                print(f"  ✗ 下载失败: {date_str} - {e}", file=sys.stderr)
                time.sleep(3)
    return None

_CSV_CACHE = {}
_MAX_CSV_CACHE = 80  # 最多缓存80份CSV（约2周数据）

# 排序结果缓存（同一次 run_single 内复用）
_SORTED_CACHE = {}

# 排序函数 _sorted_by_amt / _sorted_by_cap / _sorted_by_turnover
# 统一使用从 cycle.py 导入的版本（见文件顶部 import）

def _clear_sorted_cache():
    """清理排序缓存（统一清理所有模块的缓存）"""
    _cycle_clear_sorted_cache()
    from quant.position import _clear_sorted_cache as _pos_clear_sorted_cache
    _pos_clear_sorted_cache()


def load_csv(filepath: str) -> list[dict]:
    """加载CSV为字典列表（带内存缓存 + mtime 检查）"""
    try:
        current_mtime = os.path.getmtime(filepath)
    except OSError:
        return []
    cached = _CSV_CACHE.get(filepath)
    if cached is not None:
        cached_rows, cached_mtime = cached
        if cached_mtime >= current_mtime:
            return cached_rows
        # 文件已更新，淘汰旧缓存
    rows = []
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            rows.append(r)
    _CSV_CACHE[filepath] = (rows, current_mtime)
    # LRU eviction: 超过上限时删除最旧的条目
    while len(_CSV_CACHE) > _MAX_CSV_CACHE:
        _CSV_CACHE.pop(next(iter(_CSV_CACHE)))
    return rows

def prepare_data(target_date, csv_dir, skip_download=False):
    """准备目标日期及前N个交易日的数据（按交易日历精确查找）"""
    os.makedirs(csv_dir, exist_ok=True)

    existing = set()
    for f in os.listdir(csv_dir):
        if f.startswith('stock_daily_') and f.endswith('.csv'):
            d = f[12:20]  # "stock_daily_YYYYMMDD.csv"
            if len(d) == 8 and d.isdigit():
                existing.add(d)

    def _path(d):
        return os.path.join(csv_dir, CSV_PATTERN.format(date=d))

    prev_dates = [d for d in get_prev_trading_days(target_date, LOOKBACK_DAYS) if d >= DATA_START_DATE]
    skipped_before_start = len(get_prev_trading_days(target_date, LOOKBACK_DAYS)) - len(prev_dates)

    print(f"\n{'='*50}", file=sys.stderr)
    print(f"📥 数据准备: 目标日期 {target_date}", file=sys.stderr)
    print(f"   目录: {csv_dir}", file=sys.stderr)
    print(f"   本地已有: {len(existing)}份CSV", file=sys.stderr)
    print(f"   数据起点: {DATA_START_DATE}（{skipped_before_start}个前日早于起点，跳过）", file=sys.stderr)
    print(f"   需要前日: {', '.join(prev_dates) if prev_dates else '无'} (交易日历)", file=sys.stderr)
    print(f"{'='*50}", file=sys.stderr)

    # 并行下载今日 + 前N日（全部缺失的CSV）
    all_dates = [target_date] + prev_dates
    need_dl = [d for d in all_dates if d not in existing]
    cached = [d for d in all_dates if d in existing]

    skip_download = True  # 已有全量CSV，不再下载（flashylife URL已失效）

    for d in cached:
        p = _path(d)
        print(f"  ✓ 缓存命中 {d} ({os.path.getsize(p)//1024}KB)", file=sys.stderr)

    today_path = _path(target_date)
    if not os.path.exists(today_path):
        print(f"❌ 无法获取今日({target_date})数据", file=sys.stderr)
        sys.exit(1)

    prev_paths = [_path(td) for td in prev_dates if os.path.exists(_path(td))]

    print(f"\n✅ 数据就绪: 今日1份 + 前日{len(prev_paths)}份", file=sys.stderr)
    return today_path, prev_paths

# ════════════════════════════════════════════════════════
# 工具函数
# ════════════════════════════════════════════════════════



# _load_known_codes, _is_quality_first_board, _is_flat_spread: imported from cycle.py

def _compute_market_features(sty, rows_today, pp_today, pp_list, s_tot, chain_cluster):
    """calc_style() migration: compute market features for report_templates.py"""
    from utils import sf, is_zt
    from quant.position import _sorted_by_amt

    top20 = _sorted_by_amt(rows_today)[:20]
    top20_pct = [sf(r, '\u6da8\u8dcc\u5e45') for r in top20]
    top20_up = sum(1 for p in top20_pct if p > 0)
    top20_zt = sum(1 for r in top20 if is_zt(r))
    top20_avg = sum(top20_pct) / max(len(top20_pct), 1)

    if pp_list:
        prev_code_map = pp_list[-1]['code_map']
        multi_day = []
        for r in top20:
            code = r['\u80a1\u7968\u4ee3\u7801'].strip()
            if code in prev_code_map:
                prev_p = sf(prev_code_map[code], '\u6700\u65b0\u4ef7')
                curr_p = sf(r, '\u6700\u65b0\u4ef7')
                if prev_p > 0:
                    multi_day.append((curr_p - prev_p) / prev_p * 100)
            else:
                multi_day.append(sf(r, '\u6da8\u8dcc\u5e45'))
        top20_avg_2d = sum(multi_day) / max(len(multi_day), 1)
    else:
        top20_avg_2d = top20_avg

    sty['top20'] = {
        'up': top20_up, 'zt': top20_zt, 'total': len(top20),
        'avg_pct': top20_avg, 'avg_pct_2d': top20_avg_2d,
    }

    today_zt_codes = pp_today['zt_set']
    today_code_map = pp_today['code_map']
    chained_codes = set()
    prev_zt_total = 0
    if pp_list:
        prev_zt_codes = pp_list[-1]['zt_set']
        prev_zt_total = len(prev_zt_codes)
        chained_codes = today_zt_codes & prev_zt_codes
    chained_count = len(chained_codes)
    promote_rate = chained_count / max(prev_zt_total, 1) * 100 if pp_list else 0
    chained_rows = [today_code_map[c] for c in chained_codes if c in today_code_map]
    chained_avg_pct = sum(sf(r, '\u6da8\u8dcc\u5e45') for r in chained_rows) / max(len(chained_rows), 1) if chained_rows else 0

    sty['chained'] = {
        'count': chained_count, 'prev_zt': prev_zt_total,
        'promote_rate': promote_rate, 'avg_pct': chained_avg_pct,
    }

    trend_strength = top20_avg * 0.5 + top20_up * 2 + top20_zt * 3
    chain_strength = promote_rate * 0.3 + chained_count * 3 + chained_avg_pct * 0.5
    if promote_rate >= 20 and chained_count >= 5:
        base_style = '\u8fde\u677f'
    elif top20_avg >= 2 and top20_up >= 14:
        base_style = '\u8d8b\u52bf'
    elif chain_strength > trend_strength * 1.2:
        base_style = '\u8fde\u677f'
    elif trend_strength > chain_strength * 1.2:
        base_style = '\u8d8b\u52bf'
    else:
        base_style = '\u8d8b\u52bf' if trend_strength >= chain_strength else '\u8fde\u677f'
    sty['base_style'] = base_style
    sty['trend_strength'] = trend_strength
    sty['chain_strength'] = chain_strength

    all_profitable = [r for r in top20 if sf(r, '\u6da8\u8dcc\u5e45') > 0] + \
                     [r for r in chained_rows if sf(r, '\u6da8\u8dcc\u5e45') > 0]
    seen = set()
    unique_profitable = []
    for r in all_profitable:
        code = r['\u80a1\u7968\u4ee3\u7801'].strip()
        if code not in seen:
            seen.add(code)
            unique_profitable.append(r)
    c_20cm = sum(1 for r in unique_profitable
                 if r['\u80a1\u7968\u4ee3\u7801'].strip().startswith(('300', '301', '688')))
    c_10cm = len(unique_profitable) - c_20cm

    sty['c_20cm'] = c_20cm
    sty['c_10cm'] = c_10cm
    sty['profitable_total'] = len(unique_profitable)
    sty['sentiment_poor'] = s_tot < 40

    sty['sample_good'] = (top20_up >= 12 and top20_avg >= 1.0) or (promote_rate >= 15 and chained_count >= 3)
    sty['top3_conc'] = 0

def run_single(date_str, args):
    """执行单日复盘"""
    _clear_sorted_cache()
    # 交易日历年份检查
    if int(date_str[:4]) > _CALENDAR_MAX_YEAR:
        print(f"❌ 交易日历仅覆盖到{_CALENDAR_MAX_YEAR}年，请先更新_HOLIDAYS再运行", file=sys.stderr)
        sys.exit(1)

    # ── 第一步：数据准备 ──
    today_path, prev_paths = prepare_data(date_str, args.csv_dir, skip_download=getattr(args, 'skip_download', False))

    # 预计算交易日列表（避免后续重复 os.listdir）
    _trade_dates = None
    if args.csv_dir and os.path.isdir(args.csv_dir):
        _trade_dates = sorted([f[12:20] for f in os.listdir(args.csv_dir)
                               if f.startswith("stock_daily_") and f.endswith(".csv")])

    if args.download_only:
        print(f"\n✅ 数据下载完成，目录: {args.csv_dir}", file=sys.stderr)
        return

    # ── 第二步：加载 + 预处理 ──
    rows_today = load_csv(today_path)
    print(f"\n📊 开始计算... ({len(rows_today)} 只个股)", file=sys.stderr)

    pp_today = preprocess(rows_today)
    rows_prev_list = [load_csv(p) for p in prev_paths]
    pp_list = [preprocess(r) for r in rows_prev_list]

    # ── 第2.1步：大盘量能提取 ──
    amt_total_today = 0
    amt_avg_20d = 0
    try:
        if rows_today:
            _val = rows_today[0].get('盘面量能', '0')
            amt_total_today = float(_val) if _val else 0
            # 回退：CSV 无盘面量能列时，用所有个股成交额加总
            if amt_total_today == 0:
                try:
                    amt_total_today = sum(float(r.get('成交额', 0) or 0) for r in rows_today)
                except (ValueError, TypeError):
                    pass
        # 从历史CSV提取盘面量能，算20日均量
        _prev_amts = []
        for _rows in rows_prev_list:
            if _rows:
                _v = _rows[0].get('盘面量能', '0')
                try:
                    _a = float(_v) if _v else 0
                    # 回退：CSV 无盘面量能列时，用所有个股成交额加总
                    if _a == 0:
                        try:
                            _a = sum(float(r.get('成交额', 0) or 0) for r in _rows)
                        except (ValueError, TypeError):
                            pass
                    if _a > 0:
                        _prev_amts.append(_a)
                except (ValueError, TypeError):
                    pass
        # 取最近20天（含今日）
        _all_amts = ([amt_total_today] if amt_total_today > 0 else []) + _prev_amts
        _recent = _all_amts[:20]
        if _recent:
            amt_avg_20d = sum(_recent) / len(_recent)
        print(f"📊 量能: 今日{amt_total_today/1e8:.0f}亿, 20日均量{amt_avg_20d/1e8:.0f}亿, 比率{amt_total_today/amt_avg_20d:.2f}" if amt_avg_20d > 0 else "", file=sys.stderr)
    except Exception as _e:
        print(f"⚠️ 量能提取失败: {_e}", file=sys.stderr)
        amt_total_today, amt_avg_20d = 0, 0

    # ── 第2.5步：背离度计算（下降期抱团 #22 选股用）──
    if calc_deviation and build_known_codes:
        try:
            _known_codes = build_known_codes(args.csv_dir, min_days=10)
            dev_result = calc_deviation(rows_today, rows_prev_list, top_n=50, known_codes=_known_codes)
        except Exception as _e:
            dev_result = None
            print(f"⚠️ 背离度计算失败: {_e}", file=sys.stderr)
    else:
        dev_result = None

    prev_date_str = None
    if prev_paths:
        prev_date_str = os.path.basename(prev_paths[0]).replace('stock_daily_', '').replace('.csv', '')

    # ── 第三步：计算各维度（全部复用预处理结果）──
    s_tot, s_raw, vol_pen, vol_note, s_lv, s_det, vol_compare_amt = calc_sentiment(rows_today, pp_today, pp_list)
    # 加载前日板块TOP5供持续性检测
    _prev_date_for_sec = get_prev_trading_day(date_str)
    _prev_meta_for_sec = load_prev_meta(args.report_dir, _prev_date_for_sec)
    _prev_sec_top5 = []
    if _prev_meta_for_sec:
        if 'sec_top5_names' in _prev_meta_for_sec:
            _prev_sec_top5 = _prev_meta_for_sec['sec_top5_names']
        elif 'sector_top5' in _prev_meta_for_sec:
            _prev_sec_top5 = [s.get('name', '') for s in _prev_meta_for_sec['sector_top5'][:5]]
    sec = calc_sector(rows_today, pp_today, pp_list, csv_dir=args.csv_dir, prev_sec_top5=_prev_sec_top5)

    # ── v5板块评分已移除（纯报告展示，省22s）──

    p_tot, p_raw, pen, p_lv, p_det, zt_c, zb_c, zb_r = calc_profit(rows_today, pp_today, pp_list, len(pp_today['dt']))

    # ── 数据完整性检测（节假日后数据缺失防护）──
    # ── 数据质量验证（data_validator 模块）──
    _quality_report = validate_data_quality(
        date_str, rows_today, pp_today, zt_c, zb_c, zb_r, s_tot, p_tot,
        prev_meta=_prev_meta_for_sec,
    )
    _data_missing = not _quality_report["is_valid"]
    if _quality_report["anomalies"]:
        for _a in _quality_report["anomalies"]:
            print(f"  {'🔴' if _a['severity']=='critical' else '🟡' if _a['severity']=='warning' else 'ℹ️'} {_a['name']}: {_a['detail']}", file=sys.stderr)
    ldr = calc_leaders(rows_today, pp_today, sec, pp_list=pp_list, rows_prev_list=rows_prev_list)

    # ── 第3.5步：龙头带动性分析 ──
    leading_info = calc_leading_effect(date_str, ldr, rows_today, pp_today)
    if leading_info and ldr.get('candidates'):
        for cand in ldr['candidates']:
            code = cand['code']
            info = leading_info.get(code, {})
            bonus = info.get('leading_bonus', 0)
            if bonus > 0:
                cand['score'] += bonus
                cand['leading_bonus'] = bonus
                cand['leading_desc'] = info.get('leading_desc', '')
                # 重新评级
                sc = cand['score']
                cand['rating'] = '⭐ 绝对龙头' if sc >= 80 else ('🥈 强势龙头' if sc >= 60 else ('🥉 潜在龙头' if sc >= 40 else '❌ 无明确龙头'))
            else:
                cand['leading_bonus'] = 0
                cand['leading_desc'] = info.get('leading_desc', '')
        # 重新排序（带动加分后可能改变排名）
        ldr['candidates'].sort(key=lambda c: c.get('score', 0), reverse=True)

    # ── 第四步：加载昨日元数据 ──
    actual_prev_date = get_prev_trading_day(date_str)
    prev_meta = load_prev_meta(args.report_dir, actual_prev_date)
    prev_profit = prev_meta.get('profit_score') if prev_meta else None

    trend_confirmed = False
    if prev_meta and prev_profit is not None:
        prev2_date = get_prev_trading_day(prev_meta['date'])
        prev2_meta = load_prev_meta(args.report_dir, prev2_date)
        if prev2_meta and prev2_meta.get('profit_score') is not None:
            trend_confirmed = prev_profit > prev2_meta['profit_score']

    prev_sent_val = prev_meta['sentiment_score'] if prev_meta else None
    prev_cycle_state = {
        'label': prev_meta.get('cycle_label', ''),
        'day': prev_meta.get('cycle_day', 0),
        'streak': prev_meta.get('cycle_streak', 0),
        'was_big_cycle': prev_meta.get('was_big_cycle', False),
        '_tracker': prev_meta.get('mainline_tracker', {}),
        '_prev_day_style': prev_meta.get('invest_style', ''),
        '_breakout_observe': prev_meta.get('_breakout_observe', False),
        'f3_score': prev_meta.get('f3_score', 0),
        '_diverge_dims': prev_meta.get('_diverge_dims', {}),
    } if prev_meta else None
    prev_cycle_history = prev_meta.get('cycle_history', []) if prev_meta else []
    dt_count_today = len(pp_today.get('dt', []))

    # ── 第4.5步：计算情绪变量（v2 新增）──
    emotion_vars = calc_emotion_vars(rows_today, pp_today, pp_list, round(s_tot), p_tot, prev_meta)

    # v3.0.8: 动量衰竭标记（赚钱高位+动量衰减 → 强制降仓）
    s_acc = emotion_vars.get('sentiment_accel') or 0
    # 核心条件：赚钱效应≥60 但 情绪加速度≤-3（"最后狂欢"形态）
    emotion_vars['data_missing'] = _data_missing
    emotion_vars['data_quality'] = get_quality_for_json(_quality_report)
    emotion_vars['momentum_exhaustion'] = p_tot >= 60 and s_acc <= -3
    # 前兆条件：赚钱≥60但情绪<50且加速度<0（更敏感但可能误报）
    emotion_vars['momentum_pre_exhaustion'] = p_tot >= 60 and s_acc < 0 and round(s_tot) < 50
    # 综合标记（用于仓位约束）
    emotion_vars['is_exhaustion'] = emotion_vars['momentum_exhaustion'] or emotion_vars['momentum_pre_exhaustion']

    # v3.0.8: 体制内波动率检测
    # 从cycle_history检测近期是否有大幅波动（冰点↔上升交替）
    ch = emotion_vars.get('cycle_history', [])
    if prev_meta:
        ch = prev_meta.get('cycle_history', []) + [emotion_vars.get('cycle_label', '')]
    regime_volatility = False
    if len(ch) >= 3:
        swings = 0
        for i in range(1, len(ch)):
            prev_c = ch[i-1]
            curr_c = ch[i]
            # 检测大幅摆动：冰点→上升 / 上升→冰点 / 下降→上升 / 上升→下降
            is_prev_extreme = any(k in prev_c for k in ('冰点', '下降'))
            is_curr_extreme = any(k in curr_c for k in ('冰点', '下降'))
            is_prev_rise = '上升' in prev_c or '反弹' in prev_c
            is_curr_rise = '上升' in curr_c or '反弹' in curr_c
            if (is_prev_extreme and is_curr_rise) or (is_prev_rise and is_curr_extreme):
                swings += 1
        regime_volatility = swings >= 2
    emotion_vars['regime_volatility'] = regime_volatility

    # 计算gap_days（跨假期天数）
    gap_days = 0
    if prev_meta:
        prev_meta_date = prev_meta.get('date', '')
        if prev_meta_date:
            try:
                prev_dt = datetime.strptime(prev_meta_date, '%Y%m%d')
                curr_dt = datetime.strptime(date_str, '%Y%m%d')
                gap_days = (curr_dt - prev_dt).days - 1  # 日历天数差减1（排除交易日本身）
                gap_days = max(0, gap_days)
            except ValueError:
                gap_days = 0

    # 计算up_ratio（上涨比例）
    total_stocks = pp_today['up'] + pp_today['down']
    up_ratio = pp_today['up'] / max(total_stocks, 1)

    # ── 第4步：大成交权重抱团行情检测 + 风格检测（先于操作建议）──
    # 预计算bv_streak（权重抱团连续天数）
    _prelim_bv_streak = 0
    if prev_meta:
        prev_style = prev_meta.get('style', '')
        prev_ms = prev_meta.get('invest_style', '')
        prev_bs = prev_meta.get('baotuan_subtype', '')
        _prev_was_baotuan = ('权重抱团' in prev_style or '双重抱团' in prev_style or
                             prev_ms in ('抱团', '主升') or prev_bs in ('bigcap', 'mixed'))
        if _prev_was_baotuan:
            _prelim_bv_streak = prev_meta.get('bv_streak', 0) + 1

    big_vol_cluster = calc_big_volume_cluster(rows_today,
                       rows_prev_list[-1] if rows_prev_list else None,
                       rows_history=rows_prev_list if rows_prev_list else None,
                       bv_streak=_prelim_bv_streak,
                       date_str=date_str)

    # ── 连板抱团检测 ──
    chain_cluster = calc_chain_cluster(pp_today, pp_list, rows_today)

    _prev_s = prev_meta.get('sentiment_score') if prev_meta else None
    _prev_p = prev_meta.get('profit_score') if prev_meta else None
    _prev_dt = prev_meta.get('dt_count') if prev_meta else None
    _prev_cm = prev_meta.get('cm_style', '') if prev_meta else ''

    # sty dict: 旧calc_style已删除，由anchor_monitor构建
    # 此处初始化占位，divergence_buy逻辑下方会临时覆写
    sty = {'invest_style': '', 'baotuan_subtype': None, 'has_mainline': False, 'cm_style': ''}
    _compute_market_features(sty, rows_today, pp_today, pp_list, round(s_tot), chain_cluster)


    # ════════════════════════════════════════════════════════

    # Bug3 fix: f3_score EMA smoothing (reduce volatility impact on freeze detection)
    _f3_raw = s_det['f3']['score']
    _prev_f3_ema = prev_meta.get('f3_ema', prev_meta.get('f3_score', _f3_raw)) if prev_meta else _f3_raw
    _f3_ema = 0.5 * _f3_raw + 0.5 * _prev_f3_ema

    # 上升周期分歧日修正：沿用前日赚钱风格做分歧低吸
    # ════════════════════════════════════════════════════════
    # 用 prev_cycle_state 推算前日周期（op 还没计算）
    _cycle_label = prev_cycle_state.get('label', '') if prev_cycle_state else ''
    _is_uptrend = prev_cycle_state and '上升' in prev_cycle_state.get('label', '')
    _cycle_day = prev_cycle_state.get('day', 0) if prev_cycle_state else 0
    _uptrend_day2plus = _is_uptrend and _cycle_day >= 2
    _today_profit_weak = p_tot < 40
    _no_clear_regime = (sty.get('invest_style', '') in ('', '散乱', '低迷')) and sty.get('baotuan_subtype') in (None,)
    # 冰点预检：与 calc_op_v2 冻结判定条件一致
    core_sent_est = s_tot - _f3_ema
    _freeze_est = (
        (core_sent_est < 25 and p_tot < 25) or  # freeze_a
        core_sent_est < 15 or                     # freeze_b
        p_tot < 15                                # freeze_c
    )
    _not_freeze = not _freeze_est and not emotion_vars.get("is_exhaustion", False)

    if _uptrend_day2plus and _today_profit_weak and _no_clear_regime and _not_freeze and prev_meta:
        _prev_regime = prev_meta.get('invest_style', '') or prev_meta.get('baotuan_subtype', '')
        _prev_profit = prev_meta.get('profit_score', 0)
        _prev_sent = prev_meta.get('sentiment_score', 0)
        # 前日有赚钱体制且profit>45 → 上升分歧日，沿用前日风格
        _prev_has_regime = _prev_regime in ('bigcap', 'smallcap', 'mixed', '抱团', '主升')
        if _prev_has_regime and _prev_profit >= 45:
            _prev_invest = prev_meta.get('invest_style', '')
            _prev_cm = prev_meta.get('cm_style', '')
            sty['baotuan_subtype'] = prev_meta.get('baotuan_subtype', sty.get('baotuan_subtype'))
            if prev_meta.get('invest_style', ''):
                sty['invest_style'] = prev_meta['invest_style']
            sty['invest_style'] = _prev_invest or sty.get('invest_style', '')
            sty['cm_style'] = _prev_cm or sty.get('cm_style', '')
            sty['divergence_buy'] = True
            sty['divergence_note'] = f'上升分歧：前日{_prev_regime}赚钱(profit={_prev_profit})，今日弱回踩，沿用前日风格做分歧低吸'

    # ── 传递前日 signal_level，供 calc_op_v2 读取（EARLY 仓位 cap）──
    _prev_conc_for_signal = (_prev_meta_for_sec or {}).get('concentration', {})
    _prev_signal_level = _prev_conc_for_signal.get('signal_level', '') if isinstance(_prev_conc_for_signal, dict) else ''
    if _prev_signal_level:
        sec['_prev_signal_level'] = _prev_signal_level

    # ── 提前计算 invest_style（determine_cycle 依赖它判断反弹确认期）──
    # _conc_pool 只依赖 date_str + csv_dir，不依赖 calc_op_v2 输出
    _kph_data = _load_kph_data(date_str)
    _code_to_plate = _build_code_to_plate(_kph_data)  # always call, fallback to full plates
    _conc_pool = compute_strong_pool(date_str, args.csv_dir, code_to_plate=_code_to_plate)
    # pool_state: 用 D-1 强股池在 D 日的表现判断灵敏资金跑路
    _prev_strong_pool = prev_meta.get('strong_pool', []) if prev_meta else []
    if _prev_strong_pool:
        _pool_state, _pool_avg_pct = _cpps(_prev_strong_pool, date_str, args.csv_dir)
    else:
        _pool_state, _pool_avg_pct = _cps(_conc_pool)  # fallback: 无前日数据时用当日
    _composition = _cc(_conc_pool)

    # 用前日 CONC_ 信号 + 前日 cycle 做风格解析（当前 cycle 还没算）
    _prev_conc_raw_early = (_prev_meta_for_sec or {}).get('concentration', {})
    _prev_conc_signal = _prev_conc_raw_early.get('signal', '') if isinstance(_prev_conc_raw_early, dict) else ''
    _prev_cycle_for_style = prev_meta.get('cycle_label', '') if prev_meta else ''
    _prelim_signals = []
    if _prev_conc_signal:
        _prelim_signals.append(_prev_conc_signal)
    _prelim_style, _ = _rs(_prelim_signals, _prev_cycle_for_style, prev_cycle_phase=_prev_cycle_for_style)

    _STYLE_MAP_EARLY = {
        '上升健康': '主升', '赚钱抱团': '抱团', '冰点反转': '低迷',
        '共振确认': '主升', '恐慌陷阱': '低迷',
    }
    sty['invest_style'] = _STYLE_MAP_EARLY.get(_prelim_style, '散乱')
    sty['cm_style'] = _composition

    # 透传 pool_state 给 determine_cycle（通过 emotion_vars，不改函数签名）
    _prev_pool_state_val_early = prev_meta.get('pool_state', '') if prev_meta else ''
    emotion_vars['pool_state'] = _pool_state
    emotion_vars['prev_pool_state'] = _prev_pool_state_val_early

    from quant.position_v2 import calc_op_v2
    op = calc_op_v2(s_tot, p_tot, sec, ldr, prev_profit=prev_profit, trend_confirmed=trend_confirmed,
                    prev_sent=prev_sent_val, f3_score=_f3_ema,
                    prev_cycle_state=prev_cycle_state, zb_rate=zb_r, dt_count=dt_count_today,
                    cycle_history=prev_cycle_history, emotion_vars=emotion_vars,
                    gap_days=gap_days, up_ratio=up_ratio, vol_pen=vol_pen,
                    style=sty, big_vol_cluster=big_vol_cluster,
                    amt_total=amt_total_today, amt_avg_20d=amt_avg_20d)
    op['f3_ema'] = _f3_ema  # Bug3: persist smoothed f3 for next day

    # ── 数据异常时：沿用前日仓位状态，跳过本轮计算覆盖 ──
    if not _quality_report["is_valid"]:
        print(f"⚠️ 数据异常: {_quality_report['summary']}, 沿用前日仓位状态", file=sys.stderr)
        _carry_pos = prev_meta.get("position", 0) if prev_meta else 0
        _carry_label = prev_meta.get("position_label", "数据缺失") if prev_meta else "数据缺失"
        _carry_cycle = prev_meta.get("cycle_label", "数据缺失") if prev_meta else "数据缺失"
        _carry_cm = prev_meta.get("cycle_mult", 0) if prev_meta else 0
        _carry_freeze = prev_meta.get("freeze", False) if prev_meta else False
        _carry_trial = prev_meta.get("trial_pos", 0) if prev_meta else 0
        _carry_note = prev_meta.get("trial_note", "") if prev_meta else ""
        op["final_pos"] = _carry_pos
        op["base_label"] = _carry_label + "(数据缺失)"
        # BUG2_FIX: op["cycle_label"] = _carry_cycle
        # BUG2_FIX: op["cycle_mult"] = _carry_cm
        # BUG2_FIX: op["freeze"] = _carry_freeze
        op["consecutive_freeze"] = False
        op["trial_pos"] = _carry_trial
        op["trial_note"] = _carry_note



    # ── 主线板块状态更新（在 calc_op_v2 之后，因为需要cycle_label） ──
    # ── 主线板块状态（由集中度信号生成，替代旧的 mainline.py + mainline_tracker.py）──
    _prev_conc_raw = (_prev_meta_for_sec or {}).get('concentration', None)
    _prev_conc_state = None
    if _prev_conc_raw:
        _prev_conc_state = ConcentrationState(
            plate=_prev_conc_raw.get('plate', ''),
            ratio=_prev_conc_raw.get('ratio', 0),
            kph_rank=_prev_conc_raw.get('kph_rank', 999),
            lianban=_prev_conc_raw.get('lianban', 0),
            signal=_prev_conc_raw.get('signal', ''),
            watch_date=_prev_conc_raw.get('watch_date', ''),
            watch_ratio=_prev_conc_raw.get('watch_ratio', 0),
            plate_change=_prev_conc_raw.get('plate_change', 0),
            leader_pool=_prev_conc_raw.get('leader_pool', []),
        )

    # _conc_pool and _kph_data already computed above (before calc_op_v2)
    _conc_state = detect_concentration_signal(
        pool=_conc_pool,
        kph_data=_kph_data,
        cycle_phase=op.get('cycle_label', ''),
        sent=s_tot,
        prev_state=_prev_conc_state,
        today_date=date_str,
    )

    # ── D+1 龙头池反馈验证：前日EARLY → 今日验证 → 升级为EARLY_CONFIRMED ──
    # 必须在 detect_concentration_signal 之后，覆盖其输出
    if _prev_conc_state and _prev_conc_state.signal == 'CONC_EARLY' and _prev_conc_state.leader_pool:
        from config.strategy_rules import EARLY_CONFIRM_MED, EARLY_CONFIRM_AVG, EARLY_CONFIRM_MIN_N
        _d1_rets = {}
        for _row in rows_today:
            _code = _row.get('股票代码', _row.get('code', ''))
            _pct = _row.get('涨跌幅', _row.get('change_pct', 0))
            try:
                _d1_rets[_code] = float(_pct or 0)
            except (ValueError, TypeError):
                pass
        if verify_early_feedback(
            _prev_conc_state.leader_pool, _d1_rets,
            med_threshold=EARLY_CONFIRM_MED,
            avg_threshold=EARLY_CONFIRM_AVG,
            min_n=EARLY_CONFIRM_MIN_N,
        ):
            # 验证通过：直接覆盖conc_state为EARLY_CONFIRMED
            _conc_state.signal = 'CONC_EARLY_CONFIRMED'
            _conc_state.plate = _prev_conc_state.plate
            _conc_state.leader_pool = _prev_conc_state.leader_pool

    # ── D+1 KPH50 top1验证：前日EARLY → 今日top1 → 升级为EARLY_CONFIRMED ──
    if _prev_conc_state and _prev_conc_state.signal == 'CONC_EARLY' and _prev_conc_state.plate:
        if _kph_data:
            _sectors = _kph_data.get('sectors', [])
            if _sectors and _sectors[0].get('plate_name', '') == _prev_conc_state.plate:
                # 该板块是KPH50 top1 → 升级
                _conc_state.signal = 'CONC_EARLY_CONFIRMED'
                _conc_state.plate = _prev_conc_state.plate
                _conc_state.leader_pool = _prev_conc_state.leader_pool

    # 从集中度信号生成 mainline_info（替代旧的 _update_mainline_state + MainlineTracker）
    mainline_info = build_mainline_info(_conc_state, _kph_data, _prev_meta_for_sec, date_str)

    sec['mainline_info'] = mainline_info
    sec['yichao'] = mainline_info.get('signal', '')

    # 集中度信号存入 sec
    # Get current leader for the plate (for leader_break tracking)
    _plate_leader = None
    if _conc_state.plate and _kph_data:
        _plate_leader = _get_plate_top_leader(_kph_data, _conc_state.plate)

    sec['concentration'] = {
        'plate': _conc_state.plate,
        'ratio': round(_conc_state.ratio, 3),
        'kph_rank': _conc_state.kph_rank,
        'lianban': _conc_state.lianban,
        'signal': _conc_state.signal,
        'watch_date': _conc_state.watch_date,
        'watch_ratio': round(_conc_state.watch_ratio, 3),
        'plate_change': round(_conc_state.plate_change, 2),
        'leader': _plate_leader,
        'plate_stocks': _conc_state.plate_stocks,
        'leader_pool': _conc_state.leader_pool,
    }

    # 计算板块内最强次级tag
    if _conc_state.plate and _kph_data:
        sec['concentration']['sub_tag'] = compute_sub_tag(_conc_state.plate, _kph_data)
    else:
        sec['concentration']['sub_tag'] = ''

    # ── 多信号并存检测（active_signals）──
    _all_signals = detect_all_signals(
        pool=_conc_pool,
        kph_data=_kph_data,
        cycle_phase=op.get('cycle_label', ''),
        sent=s_tot,
        prev_state=_prev_conc_state,
        today_date=date_str,
    )

    # ── 同步 EARLY_CONFIRMED 到 _all_signals（修复信号传递断裂）──
    if _conc_state.signal == 'CONC_EARLY_CONFIRMED':
        for _sig in _all_signals:
            if _sig.plate == _conc_state.plate:
                _sig.signal = 'CONC_EARLY_CONFIRMED'
                _sig.leader_pool = _conc_state.leader_pool
                break
        else:
            # 主信号不在 _all_signals 中，手动添加
            _all_signals.insert(0, _conc_state)


    # MainlineTracker state machine
    _prev_ml_states_raw = (_prev_meta_for_sec or {}).get('mainline_tracker', {})
    _prev_ml_states = {}
    for _plate, _d in _prev_ml_states_raw.items():
        if isinstance(_d, dict):
            _valid = {f.name for f in dataclasses.fields(MainlineState)}
            _prev_ml_states[_plate] = MainlineState(**{k: v for k, v in _d.items() if k in _valid})

    # ── 趋势主线信号检测（CONC_TREND）──
    if _trade_dates:
        _recent_dates = [d for d in _trade_dates if d <= date_str][-7:]
        _kph_history = []
        for _rd in _recent_dates:
            _rd_data = _load_kph_data(_rd)
            if _rd_data:
                _kph_history.append({'date': _rd, 'sectors': _rd_data.get('sectors', [])})
        _prev_trend = {}
        for _p, _s in _prev_ml_states.items():
            if _s.signal_history and 'CONC_TREND' in _s.signal_history:
                _prev_trend[_p] = _s.last_signal_date
        _trend_signals = detect_trend_signal(_kph_history, date_str, _prev_trend)
        _all_signals.extend(_trend_signals)

    # Build code to KPH plate mapping from plate_stocks (KPH names match tracker plates)
    _code_to_kph = {}
    if _conc_state and _conc_state.plate_stocks:
        for _pl, _cls in _conc_state.plate_stocks.items():
            for _c in _cls:
                _code_to_kph[_c] = _pl
    sec['strong_pool'] = [{'code': s.code, 'ret5': s.ret5, 'sector': _code_to_kph.get(s.code, '') or getattr(s, 'sector', '') or (_conc_state.plate if _conc_state else '')} for s in _conc_pool]
    # Build today's close price map for pool avg ret calculation
    _today_prices = {r['股票代码']: float(r['最新价'] or 0) for r in rows_today if r.get('最新价')}
    _ml_states = MainlineTracker.update(
        prev_states=_prev_ml_states,
        today_signals=_all_signals,
        today_date=date_str,
        strong_pool=sec.get('strong_pool', []) if sec else [],
        trade_dates=_trade_dates,
        today_prices=_today_prices,
        csv_dir=args.csv_dir,
    )
    sec['mainline_tracker'] = {
        _p: {
            'plate': _s.plate, 'status': _s.status,
            'confirm_date': _s.confirm_date,
            'last_signal_date': _s.last_signal_date,
            'degraded_days': _s.degraded_days,
            'leader_pool': _s.leader_pool,
            'signal_history': _s.signal_history,
            'mainline_pool': _s.mainline_pool,
            'base_date': _s.base_date,
        }
        for _p, _s in _ml_states.items()
    }
    _active_ml_plate = MainlineTracker.get_active_plate(_ml_states)

    _signal_level_map = {
        'CONC_EARLY': 'early',
        'CONC_CONFIRM': 'confirm',
        'CONC_STRONG': 'confirm',
        'CONC_EARLY_CONFIRMED': 'confirm',
        'CONC_TREND': 'confirm',
    }
    sec['active_signals'] = [
        {
            'plate': s.plate,
            'signal': s.signal,
            'signal_level': _signal_level_map.get(s.signal, 'observe'),
            'ratio': round(s.ratio, 3),
            'lianban': s.lianban,
            'kph_rank': s.kph_rank,
        }
        for s in _all_signals if s.signal
    ]

    # ── Leader Break Exit Mechanism ──
    from config.strategy_rules import LEADER_BREAK_RULES
    _lb_state = check_leader_break(
        today_kph=_kph_data,
        prev_meta=_prev_meta_for_sec,
        prev_conc_state=_prev_conc_state,
        rules=LEADER_BREAK_RULES,
    )
    # Fill break_date if entering LEADER_BREAK for the first time
    if _lb_state['state'] == 'LEADER_BREAK' and not _lb_state.get('break_date'):
        _lb_state['break_date'] = date_str
    sec['leader_break'] = _lb_state
    # ── Anchor Signal System: compute new-style invest_style ──
    # _conc_pool, _pool_state, _composition already computed above (before calc_op_v2)

    _prev_pool_state_val = prev_meta.get('pool_state', '') if prev_meta else ''
    _anchor_signals = detect_signals(
        pool=_conc_pool,
        pool_state=_pool_state,
        pool_avg_pct=_pool_avg_pct,
        composition=_composition,
        cycle_phase=op.get('cycle_label', ''),
        prev_pool_state=_prev_pool_state_val,
    )
    # Append CONC_ signal for resolve_style
    if _conc_state.signal:
        _anchor_signals.append(_conc_state.signal)

    # Final resolve with full signals + actual cycle_phase
    _prev_cycle_label = prev_meta.get('cycle_label', '') if prev_meta else ''
    _anchor_style, _anchor_fallback = resolve_style(
        _anchor_signals, op.get('cycle_label', ''),
        prev_cycle_phase=_prev_cycle_label,
    )
    _anchor_action = STYLE_ACTION.get(_anchor_style, 'wait')
    _anchor_pos_mult = ACTION_POS_MULT.get(_anchor_action, 0.3)

    sec['anchor_result'] = {
        'invest_style': _anchor_style,
        'composition': _composition,
        'anchor_signals': _anchor_signals,
        'pool_state': _pool_state,
        'pool_avg_pct': _pool_avg_pct,
        'is_fallback': _anchor_fallback,
        'action': _anchor_action,
        'pos_mult': _anchor_pos_mult,
    }
    sec['pool_state'] = _pool_state
    sec['pool_avg_pct'] = _pool_avg_pct
    sec['_diverge_dims'] = {
        'sent': round(s_tot),
        'prof': p_tot,
        'pool_state': _pool_state,
        'deteriorate': '分歧' in op.get('cycle_label', ''),
    }

    # sty: 用anchor输出更新（替代旧calc_style）
    # 锚定风格→旧风格映射（兼容 report_templates.py / review_new.py 内部检查）
    _STYLE_MAP = {
        '上升健康': '主升', '赚钱抱团': '抱团', '冰点反转': '低迷',
        '共振确认': '主升', '恐慌陷阱': '低迷',
    }
    _old_style = _STYLE_MAP.get(_anchor_style, '散乱')
    sty['invest_style'] = _old_style
    sty['cm_style'] = _composition
    sty['overall'] = f'{_old_style}·{_composition}'


    # Use MainlineTracker state if available, fallback to leader_break
    _lb_state_val = sec.get('leader_break', {}).get('state', 'CONFIRMED')
    if _active_ml_plate:
        _active_ml_st = _ml_states[_active_ml_plate]
        _tracker_state = _active_ml_st.status
        _tracker_sector = _active_ml_plate
        _tracker_confirmed_days = len([h for h in _active_ml_st.signal_history if h in ('CONC_EARLY_CONFIRMED', 'CONC_CONFIRM', 'CONC_STRONG')])
        _tracker_days = _tracker_confirmed_days
    elif _lb_state_val in ('LEADER_BREAK', 'AIR_REFUEL'):
        _tracker_state = 'CONFIRMED'
        _tracker_sector = mainline_info.get('sector_name', '')
        _tracker_confirmed_days = mainline_info.get('consecutive_top5', 0)
        _tracker_days = _tracker_confirmed_days
    elif _lb_state_val == 'EXIT':
        _tracker_state = 'NONE'
        _tracker_sector = ''
        _tracker_confirmed_days = 0
        _tracker_days = 0
    elif mainline_info['status'] in ('confirmed', 'early'):
        _tracker_state = 'CONFIRMED'
        _tracker_sector = mainline_info.get('sector_name', '')
        _tracker_confirmed_days = mainline_info.get('consecutive_top5', 0)
        _tracker_days = _tracker_confirmed_days
    elif mainline_info['status'] == 'candidate':
        _tracker_state = 'CANDIDATE'
        _tracker_sector = mainline_info.get('sector_name', '')
        _tracker_confirmed_days = 0
        _tracker_days = 0
    else:
        _tracker_state = 'NONE'
        _tracker_sector = ''
        _tracker_confirmed_days = 0
        _tracker_days = 0

    sec['tracker_state'] = _tracker_state
    sec['tracker_sector'] = _tracker_sector
    sec['tracker_confirmed_days'] = _tracker_confirmed_days
    sec['tracker_days'] = _tracker_days
    sec['tracker_candidates'] = []
    sec['active_mainlines'] = []
    sec['active_mainline_count'] = 1 if is_mainline(_tracker_state) else 0

    # 注入 sty（has_mainline / tracker 相关字段）
    if sty:
        sty['has_mainline'] = is_mainline(_tracker_state)
        if is_mainline(_tracker_state) and _tracker_sector:
            sty['mainline_name'] = _tracker_sector
        sty['tracker_state'] = _tracker_state
        sty['tracker_sector'] = _tracker_sector
        sty['tracker_confirmed_days'] = _tracker_confirmed_days
        sty['tracker_days'] = _tracker_days
        sty['active_mainlines'] = []
        sty['active_mainline_count'] = 1 if is_mainline(_tracker_state) else 0
        sty['concentration'] = sec['concentration']


    # 同步 has_mainline 到 style（已由 tracker 信号注入覆盖，此处保留低迷回写逻辑）
    if sty:
        _old_ml = sty.get('has_mainline', False)
        _new_ml = sty.get('has_mainline', False)
        # 如果 has_mainline 从 False 变为 True（或反向），回写仓位修正
        if _old_ml != _new_ml and op:
            _ms = sty.get('invest_style', '散乱')
            if _ms == '低迷':
                if _new_ml:
                    # 低迷有主线：撤回之前的 -10%，改为 -5%
                    if op.get('corr', 0) <= -5:
                        _notes = op.get('corr_notes', [])
                        for i, n in enumerate(_notes):
                            if '低迷无主线' in n:
                                _notes[i] = '低迷有主线-5%'
                                break
                        op['corr'] = op.get('corr', 0) + 5
                        if not op.get('freeze'): op['final_pos'] = max(0, int((op.get('base_pos', 0) + op.get('corr', 0)) * op.get('cycle_mult', 1.0)))
                else:
                    # 变为无主线：加扣
                    if op.get('corr', 0) > -10:
                        op['corr'] = op.get('corr', 0) - 5
                        op.get('corr_notes', []).append('主线降级，额外-5%')
                        if not op.get('freeze'): op['final_pos'] = max(0, int((op.get('base_pos', 0) + op.get('corr', 0)) * op.get('cycle_mult', 1.0)))
    # 权重抱团连续天数检测（需要历史meta）
    bv_streak = 0
    if prev_meta:
        # 从历史meta中检测连续权重抱团天数
        # 简化：如果昨天也是权重抱团或双重抱团，streak+1
        prev_style = prev_meta.get('style', '')
        prev_ms = prev_meta.get('invest_style', '')
        prev_bs = prev_meta.get('baotuan_subtype', '')
        _prev_was_baotuan = ('权重抱团' in prev_style or '双重抱团' in prev_style or
                             prev_ms in ('抱团', '主升') or prev_bs in ('bigcap', 'mixed'))
        if _prev_was_baotuan:
            prev_streak = prev_meta.get('bv_streak', 0)
            _today_is_baotuan = sty.get('invest_style') in ('抱团', '主升') or sty.get('baotuan_subtype') in ('bigcap', 'mixed')
            if _today_is_baotuan:
                bv_streak = prev_streak + 1
            else:
                # 行情体制切换：保留昨日streak供瓦解预警使用，但不再累加
                bv_streak = 0
                sty['bv_streak_prev'] = prev_streak  # 保留昨日连续天数，供瓦解检测
        elif sty.get('invest_style') in ('抱团', '主升') or sty.get('baotuan_subtype') in ('bigcap', 'mixed'):
            bv_streak = 1
    elif sty.get('invest_style') in ('抱团', '主升') or sty.get('baotuan_subtype') in ('bigcap', 'mixed'):
        bv_streak = 1
    sty['bv_streak'] = bv_streak
    if big_vol_cluster:
        big_vol_cluster['bv_streak'] = bv_streak
        # 传递昨日连续天数供瓦解检测
        if 'bv_streak_prev' in sty:
            big_vol_cluster['bv_streak_prev'] = sty['bv_streak_prev']

    # 趋势对比数据（用精确meta替代粗略近似）
    prev_sent_actual = prev_meta['sentiment_score'] if prev_meta else None
    prev_meta_date = prev_meta['date'] if prev_meta else None
    if rows_prev_list:
        last_prev = rows_prev_list[-1]
        u = sum(1 for r in last_prev if sf(r, '涨跌幅') > 0)
        z = sum(1 for r in last_prev if is_zt(r))
        sent_val = round(prev_sent_actual) if prev_sent_actual is not None else (
            80 if u >= 3500 else (65 if u >= 3000 else (45 if u >= 2000 else (25 if u >= 1000 else 10)))
        )
        ps = {
            'sentiment_approx': sent_val, 'meta_date': prev_meta_date,
            'zt_count': z, 'amount': sum(sf(r, '成交额') for r in last_prev) / 1e8,
            'data_missing': _data_missing, 'data_quality': get_quality_for_json(_quality_report),
        }
    else:
        ps = None

    # ── 第五步：生成报告 ──
    report_text = build_report(
        date_str, s_tot, s_raw, vol_pen, vol_note, s_lv, s_det,
        p_tot, p_raw, pen, p_lv, p_det, zt_c, len(pp_today['dt']), zb_c, zb_r,
        sec, ldr, op, sty, ps, prev_date_str, prev_sent=prev_sent_val,
        emotion_vars=emotion_vars, vol_compare_amt=vol_compare_amt,
        big_vol_cluster=big_vol_cluster, chain_cluster=chain_cluster,
        rows_today=rows_today, dev_result=dev_result,
    )

    # ── 第六步：昨日策略验证 ──
    validation_text = None
    if prev_meta:
        validation_text = validate_yesterday(
            prev_meta, date_str, rows_today, pp_today, pp_list,
            round(s_tot), p_tot, sec, ldr,
            pp_today['up'], pp_today['down'], zt_c,
            sty, vol_pen, p_det,
        )

    # ── 第七步：输出 ──
    if args.json_output and not getattr(args, '_batch_json', False):
        json_out = build_json_output(
            date_str, s_tot, s_lv, s_det, vol_pen, vol_note,
            p_tot, p_lv, p_det, pen, zt_c, len(pp_today['dt']), zb_c, zb_r,
            sec, ldr, op, sty, prev_date_str, emotion_vars=emotion_vars,
            big_vol_cluster=big_vol_cluster,
        )
        print(json.dumps(json_out, ensure_ascii=False, indent=2))
    elif not args.json_output:
        full_output = report_text
        if validation_text:
            full_output = report_text + '\n' + validation_text
        try:
            print(full_output)
        except UnicodeEncodeError:
            pass  # report text may contain emoji, skip printing

    # ── 第八步：构建meta（一次）并保存 ──
    # ── 信号级别：CONC_EARLY→early, 其他confirmed→confirm ──
    # 必须在 build_meta 之前，否则 JSON 中没有 signal_level
    _conc_signal_pre = sec.get('concentration', {}).get('signal', '')
    _signal_level_map_pre = {
        'CONC_EARLY': 'early',
        'CONC_EARLY_CONFIRMED': 'confirm',
        'CONC_CONFIRM': 'confirm',
        'CONC_STRONG': 'confirm',
    }
    _signal_level_pre = _signal_level_map_pre.get(_conc_signal_pre, 'observe')
    if isinstance(sec.get('concentration'), dict):
        sec['concentration']['signal_level'] = _signal_level_pre

    meta = build_meta(date_str, s_tot, s_lv, p_tot, p_lv, op, ldr, sec, sty, zt_c,
                      pp_today['up'], pp_today['down'], s_det=s_det, p_det=p_det,
                      vol_pen=vol_pen, p_raw=p_raw, zb_c=zb_c, zb_r=zb_r, dt_count=dt_count_today,
                      emotion_vars=emotion_vars, big_vol_cluster=big_vol_cluster, dev_result=dev_result,
                      data_quality=get_quality_for_json(_quality_report))

    # ── 加载涨停池数据（theme_ranker 使用）──
    _all_zt = None
    try:
        import levistock as lk
        _all_zt = lk.stock_zt_pool_em(date=date_str)
    except Exception:
        pass

    # 信号级别已在 build_meta 前计算并写入 sec['concentration']['signal_level']
    _conc_signal = sec.get('concentration', {}).get('signal', '')
    _signal_level = sec.get('concentration', {}).get('signal_level', 'observe')

    # ── 信号仓位下限（取原始仓位和信号仓位的较大值）──
    if _signal_level in ('early', 'watch', 'confirm'):
        from config.strategy_rules import SIGNAL_POSITION
        _sig_floor = SIGNAL_POSITION.get(_signal_level, 0)
        _orig_pos = op.get('final_pos', 0)
        if _sig_floor > _orig_pos:
            op['corr_notes'] = op.get('corr_notes', [])
            op['corr_notes'].append(f'信号仓位下限{_sig_floor}%(原{_orig_pos}%)')
            op['final_pos'] = _sig_floor
            meta['position'] = _sig_floor
            meta['corr_notes'] = op['corr_notes']
        elif _orig_pos > _sig_floor:
            op['corr_notes'] = op.get('corr_notes', [])
            op['corr_notes'].append(f'原始仓位{_orig_pos}%>信号下限{_sig_floor}%,维持原始')

    # ── 生成结构化交易计划 ──
    try:
        meta['trade_plan'] = generate_trade_plan(
            date_str, rows_today, ldr, op, sty, sec,
            chain_cluster, pp_today,
            rows_prev_list=rows_prev_list, pp_list=pp_list,
            prev_meta=_prev_meta_for_sec, dev_result=dev_result,
            s_tot=s_tot,
            profit_score=p_tot,
            dt_count=dt_count_today,
            all_zt=_all_zt, signal_level=_signal_level,
            concentration_plate=_conc_state.plate if _conc_state else '',
        )
    except Exception as _e:
        meta['trade_plan'] = {'error': str(_e)}

    # ── 权重趋势检测（独立于主策略）──
    if weight_trend_run:
        try:
            _wt_result = weight_trend_run(date_str, base_position=s_tot)
            meta['weight_trend'] = _wt_result
        except Exception as _wt_e:
            meta['weight_trend'] = {'error': str(_wt_e)}
    else:
        meta['weight_trend'] = {'error': 'module not available'}

    if not args.no_save:
        full_output = report_text
        if validation_text:
            full_output = report_text + '\n' + validation_text
        # 追加结构化交易计划
        _tp_text = format_trade_plan_text(meta.get('trade_plan'))
        if _tp_text:
            full_output += '\n' + _tp_text
        save_report(args.report_dir, date_str, full_output, meta)

        # ── 保存盘中情绪分缓存（供 intraday_monitor 使用）──
        try:
            _sector_scores_cache = {}
            for _sname, _sdata in sec.get('top5', []):
                _sector_scores_cache[_sname] = {
                    'avg_pct': _sdata.get('avg_pct', 0),
                    'zt_count': _sdata.get('zt_count', 0),
                    'amount': _sdata.get('amount', 0),
                    'score': _sdata.get('score', 0),
                }
            save_daily_cache(
                date_str,
                pp_today['zt_set'],
                pp_today['up'],
                pp_today['down'],
                _sector_scores_cache,
                pp_today['total_amt'],
            )
            # 追加情绪分/赚钱效应等元数据到缓存条目（仅首次生成时写入，重跑时跳过）
            if not getattr(args, 'skip_download', False):
                _quant_dir = os.path.dirname(os.path.abspath(__file__))
                _data_dir = os.path.join(os.path.dirname(_quant_dir), 'data')
                _cache_path = os.path.join(_data_dir, 'daily_sentiment_cache.json')
                if os.path.exists(_cache_path):
                    with open(_cache_path, 'r', encoding='utf-8') as _f:
                        _cache_data = json.load(_f)
                    for _entry in _cache_data:
                        if _entry.get('date') == date_str:
                            _entry['sentiment_score'] = round(s_tot)
                            _entry['profit_score'] = p_tot
                            _entry['cycle_label'] = op.get('cycle_label', '')
                            _entry['cycle_day'] = op.get('cycle_day', 0)
                            _entry['cycle_history'] = op.get('cycle_history', [])
                            _entry['sector_top5'] = [{'name': n, 'score': d.get('score', 0)} for n, d in sec.get('top5', [])]
                            _entry['mainline'] = sec.get('mainline_info', {}).get('signal', '')
                            break
                    with open(_cache_path, 'w', encoding='utf-8') as _f:
                        json.dump(_cache_data, _f, ensure_ascii=False)
        except Exception as _e:
            print(f"⚠️ 保存盘中缓存失败: {_e}", file=sys.stderr)

    # ── 第九步：回测收益（--backtest 启用）──
    if getattr(args, 'backtest', False):
        try:
            from backtest import run_backtest, generate_backtest_summary
            # 回测区间：从 backtest_start 到当前日期
            bt_start = getattr(args, 'backtest_start', None)
            if bt_start:
                result = run_backtest(bt_start, date_str,
                                      capital=getattr(args, 'backtest_capital', 1000000),
                                      csv_dir=args.csv_dir, report_dir=args.report_dir)
                if result:
                    summary = generate_backtest_summary(result)
                    if summary:
                        print(summary)
                    # 追加到已保存的报告
                    if not args.no_save:
                        txt_path = os.path.join(args.report_dir, f"review_{date_str}.txt")
                        try:
                            with open(txt_path, 'a', encoding='utf-8') as f:
                                f.write('\n' + summary)
                        except IOError:
                            pass
        except (ImportError, Exception) as e:
            print(f"  ⚠️ 回测失败: {e}", file=sys.stderr)

    return meta


def expand_date_range(date_arg):
    """解析日期参数，支持单日/区间/最近N天"""
    # 区间模式: 20260401-20260407
    if '-' in date_arg and len(date_arg) == 17:
        start_str, end_str = date_arg.split('-')
        start = datetime.strptime(start_str, '%Y%m%d')
        end = datetime.strptime(end_str, '%Y%m%d')
        dates = []
        cur = start
        while cur <= end:
            d = cur.strftime('%Y%m%d')
            if is_trading_day(d):
                dates.append(d)
            cur += timedelta(days=1)
        return dates
    # 单日
    return [date_arg]


def get_last_trading_days(end_date, n):
    """获取最近n个交易日（含end_date如果是交易日，否则往前）"""
    dates = []
    cur = datetime.strptime(end_date, '%Y%m%d') if end_date else datetime.now()
    # 如果今天是交易日但未收盘（<15:05），跳过今天
    today_str = datetime.now().strftime('%Y%m%d')
    cur_str = cur.strftime('%Y%m%d')
    if cur_str == today_str and is_trading_day(today_str):
        now = datetime.now()
        if now.hour < 15 or (now.hour == 15 and now.minute < 5):
            cur = cur - timedelta(days=1)
    # 如果end_date不是交易日，往前找
    d = cur.strftime('%Y%m%d')
    if not is_trading_day(d):
        cur_dt = cur - timedelta(days=1)
        while not is_trading_day(cur_dt.strftime('%Y%m%d')):
            cur_dt -= timedelta(days=1)
        cur = cur_dt
    # 往前收集n个交易日
    for _ in range(n):
        d = cur.strftime('%Y%m%d')
        while not is_trading_day(d):
            cur -= timedelta(days=1)
            d = cur.strftime('%Y%m%d')
        dates.append(d)
        cur -= timedelta(days=1)
    return list(reversed(dates))



def print_summary(batch_metas):
    """输出区间复盘汇总表"""
    if not batch_metas:
        return

    lines = []
    lines.append("")
    lines.append("\u2550" * 90)
    lines.append("\U0001f4ca 区间复盘汇总")
    lines.append("\u2550" * 90)
    lines.append("")

    # -- 主表 --
    lines.append(f"  {'日期':>10} | {'情绪':>5} | {'赚钱':>5} | {'综合':>5} | {'周期':>14} | {'仓位':>4} | {'涨停':>4} | {'跌停':>4} | {'涨/跌':>9} | {'置信':>4} | 主线")
    lines.append("  " + "\u2500" * 88)

    for m in batch_metas:
        d = m.get('date', '')
        df = f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else d
        s = m.get('sentiment_score', 0)
        p = m.get('profit_score', 0)
        comp = m.get('composite', 0)
        cyc = m.get('cycle_label', '')
        pos = m.get('position', 0)
        zt = m.get('zt_count', 0)
        dt_c = m.get('dt_count', 0)
        for k in ('zb_count',):
            pass
        up = m.get('up_count', 0)
        dn = m.get('down_count', 0)
        conf = m.get('confidence', 0)
        ml = m.get('mainline', '')

        if '\u2705' in ml:   ml_s = 'Y'
        elif '\u26a0' in ml: ml_s = '?'
        elif '\u274c' in ml:  ml_s = 'N'
        else:                 ml_s = '-'

        if s >= 80:    se = 'F'
        elif s >= 60:  se = '+'
        elif s >= 40:  se = '~'
        elif s >= 20:  se = '-'
        else:          se = 'X'

        lines.append(f"  {df} | {se}{s:>3} | {p:>5} | {comp:>5.1f} | {cyc:>14} | {pos:>3}% | {zt:>4} | {dt_c:>4} | {up:>4}/{dn:<4} | {conf:>3}% | {ml_s}")

    lines.append("  " + "\u2500" * 88)

    # -- 趋势箭头 --
    lines.append("")
    lines.append("趋势变化:")
    for i in range(1, len(batch_metas)):
        prev, curr = batch_metas[i-1], batch_metas[i]
        dp = prev.get('date', '')
        dc = curr.get('date', '')
        label = f"{dp[4:6]}/{dp[6:]}->{dc[4:6]}/{dc[6:]}"
        def ar(v):
            if v > 5: return '\u2191'
            elif v < -5: return '\u2193'
            else: return '\u2192'
        sd = curr.get('sentiment_score',0) - prev.get('sentiment_score',0)
        pd = curr.get('profit_score',0) - prev.get('profit_score',0)
        zd = curr.get('zt_count',0) - prev.get('zt_count',0)
        lines.append(f"  {label}  情绪{ar(sd)}{sd:+d}  赚钱{ar(pd)}{pd:+d}  涨停{ar(zd)}{zd:+d}")

    # -- 情绪变量趋势 --
    has_ev = any(m.get('sentiment_accel') is not None for m in batch_metas)
    if has_ev:
        lines.append("")
        lines.append("情绪变量趋势:")
        lines.append(f"  {'日期':>10} | {'加速度':>6} | {'赚钱流':>6} | {'动量':>4} | {'首板率':>6} | {'首板溢':>7} | {'承接力':>5} | 判定")
        lines.append(f"  {'-'*10}-+-{'-'*6}-+-{'-'*6}-+-{'-'*4}-+-{'-'*6}-+-{'-'*7}-+-{'-'*5}-+------")
        for m in batch_metas:
            d = m.get('date','')
            df = f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d)==8 else d
            sa = m.get('sentiment_accel')
            pa = m.get('profit_accel')
            mom = m.get('sentiment_momentum', 0)
            fbr = m.get('first_board_promo_rate')
            fbp = m.get('first_board_premium')
            ins = m.get('intraday_support', 0)
            fbv = m.get('first_board_verdict','')
            sa_s = f"{sa:+.1f}" if sa is not None else "---"
            pa_s = f"{pa:+.1f}" if pa is not None else "---"
            fbr_s = f"{fbr:.1f}%" if fbr is not None else "---"
            fbp_s = f"{fbp:+.2f}" if fbp is not None else "---"
            v_map = {'strong':'S','selective':'E','fake':'F','forbidden':'X'}
            v_s = v_map.get(fbv, '-')
            lines.append(f"  {df} | {sa_s:>6} | {pa_s:>6} | {mom:>3}d | {fbr_s:>6} | {fbp_s:>7} | {ins:>4.0f}分 | {v_s} {fbv}")

    # -- 龙头追踪 --
    lines.append("")
    lines.append("龙头追踪:")
    for m in batch_metas:
        d = m.get('date','')
        df = f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d)==8 else d
        stocks = m.get('stocks',[])
        if stocks:
            top = stocks[0]
            lines.append(f"  {df}  {top['name']}({top['code']}) {top['score']}分 {top['rating']}  {top.get('pct',0):+.1f}%")
        else:
            lines.append(f"  {df}  无明确龙头")

    # -- 区间统计 --
    lines.append("")
    lines.append("区间统计:")
    sv = [m.get('sentiment_score',0) for m in batch_metas]
    pv = [m.get('profit_score',0) for m in batch_metas]
    zv = [m.get('zt_count',0) for m in batch_metas]
    ov = [m.get('position',0) for m in batch_metas]
    lines.append(f"  情绪: 均{sum(sv)/len(sv):.1f} 高{max(sv)} 低{min(sv)}")
    lines.append(f"  赚钱: 均{sum(pv)/len(pv):.1f} 高{max(pv)} 低{min(pv)}")
    lines.append(f"  涨停: 均{sum(zv)/len(zv):.0f} 高{max(zv)} 低{min(zv)}")
    lines.append(f"  仓位: 均{sum(ov)/len(ov):.1f}% 空仓{sum(1 for x in ov if x==0)}/{len(ov)}天")
    cycs = {}
    for m in batch_metas:
        c = m.get('cycle_label','?')
        cycs[c] = cycs.get(c,0) + 1
    lines.append(f"  周期: {' | '.join(f'{k}({v}d)' for k,v in sorted(cycs.items(),key=lambda x:-x[1]))}")

    # -- 板块持续榜（跨日追踪）--
    sector_days = {}  # sector_name -> {'count': N, 'top1_count': N, 'avg_scores': [...], 'days': [...]}
    for m in batch_metas:
        d = m.get('date', '')
        s5 = m.get('sector_top5', [])
        for item in s5:
            nm = item.get('name', '')
            if not nm:
                continue
            if nm not in sector_days:
                sector_days[nm] = {'count': 0, 'top1_count': 0, 'avg_scores': [], 'days': [], 'avg_pcts': [], 'zt_counts': []}
            sd = sector_days[nm]
            sd['count'] += 1
            if item.get('rank', 99) == 1:
                sd['top1_count'] += 1
            sd['avg_scores'].append(item.get('score', 0))
            sd['avg_pcts'].append(item.get('avg_pct', 0))
            sd['zt_counts'].append(item.get('zt_count', 0))
            sd['days'].append(f"{d[4:6]}/{d[6:]}")
    # 筛选出现>=2天的板块，按出现天数→平均分排序
    persistent = {k: v for k, v in sector_days.items() if v['count'] >= 2}
    if persistent:
        lines.append("")
        lines.append("板块持续榜（连续进入TOP5的板块）:")
        lines.append(f"  {'板块':<16} | {'上榜':>3}天 | {'TOP1':>4}次 | {'均分':>5} | {'均涨':>6} | {'均涨停':>5} | 上榜日期")
        lines.append(f"  {'-'*16}-+-{'-'*5}-+-{'-'*6}-+-{'-'*5}-+-{'-'*6}-+-{'-'*7}-+-{'-'*20}")
        for nm, sd in sorted(persistent.items(), key=lambda x: (-x[1]['count'], -sum(x[1]['avg_scores'])/len(x[1]['avg_scores']))):
            cnt = sd['count']
            t1 = sd['top1_count']
            avg_sc = sum(sd['avg_scores']) / len(sd['avg_scores'])
            avg_pct = sum(sd['avg_pcts']) / len(sd['avg_pcts'])
            avg_zt = sum(sd['zt_counts']) / len(sd['zt_counts'])
            days_str = ', '.join(sd['days'])
            lines.append(f"  {nm:<16} | {cnt:>3}天 | {t1:>4}次 | {avg_sc:>5.1f} | {avg_pct:>+5.1f}% | {avg_zt:>5.1f} | {days_str}")

    lines.append("")
    lines.append("\u2550" * 90)
    print('\n'.join(lines))


def main():
    import argparse
    parser = argparse.ArgumentParser(description=VERSION,
        epilog='示例:\n'
               '  review.py 20260403              单日复盘\n'
               '  review.py 20260401-20260407     区间复盘\n'
               '  review.py --last 5              最近5个交易日\n'
               '  review.py --last 5 --json       最近5天JSON输出',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--version', action='version', version=VERSION)
    parser.add_argument('date', nargs='?', default=None, help='复盘日期 YYYYMMDD 或 YYYYMMDD-YYYYMMDD')
    parser.add_argument('--last', type=int, metavar='N', help='最近N个交易日')
    parser.add_argument('--csv-dir', default=DEFAULT_DIR, help='CSV目录')
    parser.add_argument('--report-dir', default=DEFAULT_REPORT_DIR, help='报告保存目录')
    parser.add_argument('--download-only', action='store_true', help='仅下载数据')
    parser.add_argument('--skip-download', action='store_true', help='跳过CSV下载，仅使用本地已有数据')
    parser.add_argument('--no-save', action='store_true', help='不保存报告文件')
    parser.add_argument('--json', action='store_true', dest='json_output', help='输出JSON格式')
    parser.add_argument('--summary', action='store_true', help='区间复盘汇总表（搭配区间或--last使用）')
    parser.add_argument('--html', action='store_true', help='生成HTML图表报告')
    parser.add_argument('--force', action='store_true', help='强制重算（跳过meta缓存）')
    parser.add_argument('--backtest', action='store_true', help='启用回测收益计算')
    parser.add_argument('--backtest-start', default=None, help='回测起始日期 YYYYMMDD (默认从--backtest起)')
    parser.add_argument('--backtest-capital', type=float, default=1000000, help='回测初始本金 (默认100万)')
    args = parser.parse_args()

    # 解析日期列表
    if args.last:
        today_str = datetime.now().strftime('%Y%m%d')
        dates = get_last_trading_days(today_str, args.last)
    elif args.date:
        dates = expand_date_range(args.date)
    else:
        parser.error('需要指定日期或 --last N')

    # 过滤早于数据起点的日期（本程序只有20260401以来的数据）
    original_count = len(dates)
    dates = [d for d in dates if d >= DATA_START_DATE]
    skipped = original_count - len(dates)
    if skipped:
        print(f"⚠️  {skipped} 个日期早于数据起点 {DATA_START_DATE}，已跳过", file=sys.stderr)

    # ── 批量预下载CSV（并行）──
    if len(dates) > 1 and not getattr(args, 'skip_download', False):
        all_dl_dates = set()
        for d in dates:
            all_dl_dates.add(d)
            for prev_d in get_prev_trading_days(d, LOOKBACK_DAYS):
                all_dl_dates.add(prev_d)
        # 过滤早于数据起点的日期
        all_dl_dates = {d for d in all_dl_dates if d >= DATA_START_DATE}
        # 过滤已存在的
        need_dl = [d for d in sorted(all_dl_dates)
                   if not os.path.exists(os.path.join(args.csv_dir, CSV_PATTERN.format(date=d)))]
        if need_dl:
            print(f"📥 批量预下载 {len(need_dl)} 个CSV文件（并行）...", file=sys.stderr)
            def _dl_one(d):
                return d, download_csv(d, args.csv_dir)
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {executor.submit(_dl_one, d): d for d in need_dl}
                for f in as_completed(futures):
                    d, path = f.result()
            print("📥 预下载完成", file=sys.stderr)
    elif getattr(args, 'skip_download', False):
        print("📥 跳过下载模式，只处理已有CSV", file=sys.stderr)

    # --backtest 默认从第一个日期开始
    if getattr(args, 'backtest', False) and not args.backtest_start:
        args.backtest_start = dates[0]

    # --summary 模式：优先读取已有meta缓存，避免重复计算
    if getattr(args, 'summary', False) and not args.force:
        batch_metas = []
        need_run = []
        for date_str in dates:
            cached = load_prev_meta(args.report_dir, date_str)
            if cached and cached.get('date') == date_str:
                batch_metas.append(cached)
            else:
                need_run.append(date_str)
        if need_run:
            print(f"  📋 缓存命中 {len(batch_metas)}/{len(dates)} 天，需重算: {', '.join(need_run)}", file=sys.stderr)
            for date_str in need_run:
                meta = run_single(date_str, args)
                if meta:
                    batch_metas.append(meta)
            # 按日期排序
            batch_metas.sort(key=lambda m: m.get('date', ''))
        else:
            print(f"  📋 全部 {len(batch_metas)} 天命中缓存", file=sys.stderr)
        print_summary(batch_metas)
        return


    # 批量执行
    batch_metas = []
    batch_json = args.json_output and len(dates) > 1
    if batch_json:
        args._batch_json = True
    for i, date_str in enumerate(dates):
        if len(dates) > 1:
            print(f"\n{'='*60}", file=sys.stderr)
            print(f"📅 批量复盘 [{i+1}/{len(dates)}]: {date_str}", file=sys.stderr)
            print(f"{'='*60}", file=sys.stderr)
        meta = run_single(date_str, args)
        if meta:
            batch_metas.append(meta)

    # v2.8：批量JSON模式追加history序列
    if batch_json and batch_metas:
        history = []
        for m in batch_metas:
            history.append({
                'date': m.get('date'),
                'sentiment': m.get('sentiment_score'),
                'profit': m.get('profit_score'),
                'cycle': m.get('cycle_label'),
                'position': m.get('position'),
                'confidence': m.get('confidence', 0),
                'mainline': m.get('mainline', ''),
                'zt_count': m.get('zt_count', 0),
                'up_count': m.get('up_count', 0),
                'down_count': m.get('down_count', 0),
                'sentiment_accel': m.get('sentiment_accel'),
                'profit_accel': m.get('profit_accel'),
            })
        print(json.dumps({'history': history}, ensure_ascii=False, indent=2))

    # --summary 汇总表
    if getattr(args, 'summary', False) and batch_metas:
        print_summary(batch_metas)

    if len(dates) > 1:
        print(f"\n✅ 批量复盘完成，共 {len(dates)} 天", file=sys.stderr)

if __name__ == '__main__':
    main()






