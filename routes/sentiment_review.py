# -*- coding: utf-8 -*-
"""情绪复盘系统 API — T1客观盘面聚合 + T2~T5人工层CRUD + 序列视图 + 相似日检索"""
import re
import sqlite3, json, logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

BASE_DIR = Path('/opt/stock-review')
DB = BASE_DIR / 'data' / 'sentiment_review.db'
logger = logging.getLogger('sentiment_review')

# ─────────────────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────────────────
def _conn():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _today():
    return datetime.now().strftime('%Y%m%d')


def _fmt(d):
    return d.replace('-', '') if d and '-' in str(d) else d


def _sf(val, default=0):
    """浮点安全转换"""
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────
# T1 客观盘面聚合（自动采集）
# ─────────────────────────────────────────────────────────
def collect_market_snapshot(date_str: str = None) -> dict:
    """聚合 T1 全字段落库。复用 ths_api + realtime 缓存。"""
    date_str = _fmt(date_str) if date_str else _today()
    result = {'trade_date': date_str, 'source_status': 'ok', 'metrics_version': 'v2.0'}
    # 交易日守卫：周末/节假日不采集不写库（2026-10-08，假期假数据根治）
    try:
        from datetime import datetime as _dt
        from utils import _load_holidays
        _d = _dt.strptime(date_str, '%Y%m%d')
        if _d.weekday() >= 5 or date_str in set(_load_holidays()):
            return {'trade_date': date_str, 'source_status': 'holiday', 'skipped': True,
                    'message': '非交易日，跳过采集'}
    except Exception as _we:
        logger.warning('交易日检查失败(继续采集): %s', _we)

    try:
        from quant.ths_api import get_market_breadth, get_zt_ladder, get_ths_index_snapshot
    except Exception as e:
        logger.warning('ths_api 导入失败: %s', e)
        return {'trade_date': date_str, 'source_status': 'fail', 'error': str(e)}

    # 1. 涨跌停/炸板
    try:
        br = get_market_breadth(date_str)
        if br:
            result['limit_up_count'] = br.get('limit_up_count', 0)
            result['limit_down_count'] = br.get('limit_down_count', 0)
            result['break_count'] = br.get('broken_count', 0)
            result['break_rate'] = br.get('broken_rate', 0)
            result['_limit_up_pool'] = br.get('limit_up', [])
    except Exception as e:
        logger.warning('breadth失败: %s', e)

    # 2. 连板梯队
    try:
        ladder = get_zt_ladder(date_str)
        if ladder:
            tiers = ladder.get('ladder', [])
            result['max_board'] = ladder.get('highest', 0)
            b2 = sum(t['count'] for t in tiers if t['level'] >= 2)
            b3 = sum(t['count'] for t in tiers if t['level'] >= 3)
            result['board2plus_count'] = b2
            result['board3plus_count'] = b3
    except Exception as e:
        logger.warning('ladder失败: %s', e)

    # 3. 昨日涨停溢价 + 大面家数（realtime 已有 _fetch_yesterday_zt，大面家数自己算）
    try:
        from quant.realtime_service import RealtimeService
        svc = RealtimeService()
        prem = svc._fetch_yesterday_zt()
        if prem:
            result['ly_premium'] = prem.get('zt_avg_pct')
            result['ly_premium_cont'] = prem.get('cont_avg_pct')
            # 大面家数：昨日涨停且今日跌幅<=-5%
            try:
                from utils import get_prev_trading_day
                from lianban import load_zt_stocks
                today_s = date_str
                yesterday_s = get_prev_trading_day(today_s)
                zt_map = load_zt_stocks(yesterday_s)
                if zt_map:
                    # 用 ths 快照取今日涨幅
                    from quant.ths_api import get_snapshot
                    codes = list(zt_map.keys())
                    ths_codes = [c + ('.SH' if c.startswith(('6', '9')) else '.SZ') for c in codes]
                    pct_map = {}
                    for i in range(0, len(ths_codes), 200):
                        for s_ in (get_snapshot(ths_codes[i:i + 200]) or []):
                            code = str(s_.get('ticker', '')).split('.')[0]
                            if code:
                                pct_map[code] = _sf(s_.get('price_change_ratio_pct'))
                    big_loss = sum(1 for c in zt_map if c in pct_map and pct_map[c] <= -5)
                    result['big_loss_count'] = big_loss
            except Exception as e2:
                logger.warning('大面家数计算失败: %s', e2)
                result['big_loss_count'] = 0
    except Exception as e:
        logger.warning('昨日涨停溢价失败: %s', e)

    # 4. 指数涨跌幅
    try:
        snaps = get_ths_index_snapshot(['000001.SH', '399006.SZ'])
        for s in snaps or []:
            code = str(s.get('thscode', s.get('code', '')))
            pct = s.get('change_pct', s.get('price_change_ratio_pct'))
            if '000001' in code:
                result['sh_pct'] = pct
            elif '399006' in code:
                result['cyb_pct'] = pct
    except Exception as e:
        logger.warning('指数快照失败: %s', e)

    # 5. 涨跌家数 + 成交额（实时监控口径 run_analysis，2026-09-29 用户定稿）
    try:
        from quant.realtime_service import get_service as _get_rt
        ana = _get_rt().run_analysis()
        if ana and not ana.get('error') and ana.get('total_amount_yi'):
            result['up_count'] = ana.get('total_up')
            result['down_count'] = ana.get('total_down')
            result['turnover_yi'] = ana.get('total_amount_yi')
            result['turnover_source'] = 'realtime_analysis'
            logger.info('实时监控口径: %d只 上涨%d 下跌%d 成交%.1f亿',
                        ana.get('total_stocks') or 0, result['up_count'] or 0,
                        result['down_count'] or 0, result['turnover_yi'])
    except Exception as e:
        logger.warning('实时监控口径失败: %s', e)

    # 5b. 兜底：全市场快照求和（346只缺额会偏小，仅实时口径失败时启用）
    if result.get('turnover_yi') is None:
        try:
            cache_path = BASE_DIR / 'data' / 'realtime_market_cache.json'
            if cache_path.exists():
                with open(cache_path, encoding='utf-8') as f:
                    mc = json.load(f)
                cache_date = str(mc.get('date', ''))
                quotes = mc.get('data', []) or []
                if cache_date == date_str and quotes:
                    up = sum(1 for q in quotes if _sf(q.get('change_pct')) > 0)
                    down = sum(1 for q in quotes if _sf(q.get('change_pct')) < 0)
                    total_amt = sum(_sf(q.get('amount')) for q in quotes)
                    result['up_count'] = result.get('up_count') or up
                    result['down_count'] = result.get('down_count') or down
                    result['turnover_yi'] = round(total_amt / 1e8, 1)
                    logger.info('兜底全市场快照: %d只 成交%.0f亿', len(quotes), total_amt / 1e8)
                else:
                    logger.warning('快照日期%s与目标%s不一致', cache_date, date_str)
        except Exception as e:
            logger.warning('全市场快照统计失败: %s', e)

    # 5c. 本地 CSV 口径覆盖（与历史回填完全同口径，2026-09-30 定稿）：
    #     涨停/跌停 = 精确判定（涨停剔除 ST/新股N/C开头）；溢价/大面 = 昨日涨停名单×今日收盘涨跌幅
    try:
        import csv as _csv
        from decimal import Decimal as _Dec, ROUND_HALF_UP as _RHU
        from utils import is_zt as _is_zt, get_limit_threshold as _glt, get_prev_trading_day as _gpd
        from lianban import compute_lianban_tiers as _ctiers, load_zt_stocks as _lzt
        _csv_path = BASE_DIR / 'data' / 'csv' / ('stock_daily_%s.csv' % date_str)
        if _csv_path.exists():
            with open(_csv_path, encoding='utf-8-sig') as _f:
                _rows = list(_csv.DictReader(_f))
            _pct_map, _zt_n, _dt_n = {}, 0, 0
            for _row in _rows:
                _code = (_row.get('\u80a1\u7968\u4ee3\u7801') or '').strip()
                _name = (_row.get('\u80a1\u7968\u540d\u79f0') or '').strip()
                try:
                    _pct_map[_code] = float(_row.get('\u6da8\u8dcc\u5e45') or 0)
                except (TypeError, ValueError):
                    _pct_map[_code] = 0.0
                if _is_zt(_row) and ('ST' not in _name) and not _name.startswith(('N', 'C')):
                    _zt_n += 1
                try:
                    _price = float(_row.get('\u6700\u65b0\u4ef7') or 0)
                    _lc = float(_row.get('\u6628\u6536\u4ef7') or 0)
                    if _lc > 0 and ('ST' not in _name) and not _name.startswith(('N', 'C')):
                        _thr = _glt(_code, _name) / 100.0
                        _down = (_Dec(str(_lc)) * (_Dec(1) - _Dec(str(_thr)))).quantize(_Dec('0.01'), _RHU)
                        if _Dec(str(_price)) <= _down:
                            _dt_n += 1
                except (TypeError, ValueError):
                    pass
            result['limit_up_count'] = _zt_n
            result['limit_down_count'] = _dt_n
            try:
                _tiers = _ctiers(date_str).get('tiers', [])
                result['max_board'] = max([t.get('level', 0) for t in _tiers] or [0])
                result['board2plus_count'] = sum(t.get('count', len(t.get('stocks', []))) for t in _tiers if t.get('level', 0) >= 2)
                result['board3plus_count'] = sum(t.get('count', len(t.get('stocks', []))) for t in _tiers if t.get('level', 0) >= 3)
            except Exception as _e2:
                logger.warning('CSV连板梯队失败: %s', _e2)
            _prev = _gpd(date_str)
            _zt_map = _lzt(_prev) or {}
            _zt_pcts = [_pct_map[c] for c in _zt_map if c in _pct_map]
            if _zt_pcts:
                result['ly_premium'] = round(sum(_zt_pcts) / len(_zt_pcts), 2)
                result['big_loss_count'] = sum(1 for p in _zt_pcts if p <= -5)
            _ptiers = _ctiers(_prev).get('tiers', [])
            _cont_codes = {st.get('code') for t in _ptiers if t.get('level', 0) >= 2 for st in t.get('stocks', [])}
            _cont_pcts = [_pct_map[c] for c in _cont_codes if c in _pct_map]
            if _cont_pcts:
                result['ly_premium_cont'] = round(sum(_cont_pcts) / len(_cont_pcts), 2)
            result['breadth_source'] = 'local_csv'
            logger.info('CSV口径: 涨停%d 跌停%d 溢价%s 连板溢价%s',
                        _zt_n, _dt_n, result.get('ly_premium'), result.get('ly_premium_cont'))
    except Exception as e:
        logger.warning('CSV口径覆盖失败: %s', e)

    # 兜底：收盘后从 daily_sentiment_cache.json 读取（仅当日期匹配）
    if result.get('up_count') is None:
        try:
            import glob
            cache_files = sorted(glob.glob(str(BASE_DIR / 'data' / 'daily_sentiment_cache.json')))
            if cache_files:
                with open(cache_files[-1], encoding='utf-8') as f:
                    cache = json.load(f)
                if isinstance(cache, list) and cache:
                    cache = cache[-1]
                cache_date = str(cache.get('date', ''))
                if cache_date == date_str:
                    result['up_count'] = cache.get('up')
                    result['down_count'] = cache.get('down')
                    total_amt = cache.get('total_amt')
                    if total_amt:
                        result['turnover_yi'] = round(total_amt / 1e8, 1)
                else:
                    logger.warning('cache日期%s与目标%s不一致，放弃兜底', cache_date, date_str)
        except Exception as e:
            logger.warning('daily_sentiment_cache兜底失败: %s', e)

    # 6. 客观情绪分（v2.0 用户定稿 2026-09-29：每日复盘情绪分×0.4 + 赚钱效应分×0.6）
    sent = prof = None
    try:
        rp = BASE_DIR / 'reports' / ('review_%s.json' % date_str)
        if rp.exists():
            with open(rp, encoding='utf-8') as f:
                rd = json.load(f)
            sent, prof = rd.get('sentiment_score'), rd.get('profit_score')
            if sent is not None and prof is not None:
                result['score_source'] = 'review_json'
    except Exception as e:
        logger.warning('读取复盘情绪分失败: %s', e)
    if sent is None or prof is None:
        try:
            sent, prof = ana.get('sentiment_score'), ana.get('profit_score')
            if sent is not None and prof is not None:
                result['score_source'] = 'realtime_analysis'
        except Exception:
            sent = prof = None
    if sent is not None and prof is not None:
        result['sentiment_score_obj'] = round(max(0, min(100, sent * 0.4 + prof * 0.6)), 1)
    else:
        # 兜底：v1.0 客观合成（复盘情绪分缺失时启用）
        br = result.get('break_rate', 0) or 0
        prem = result.get('ly_premium', 0) or 0
        mb = result.get('max_board', 0) or 0
        up = result.get('up_count', 0) or 0
        down = result.get('down_count', 0) or 0
        up_ratio = up / (up + down) if (up + down) > 0 else 0.5
        score = (0.30 * (100 - br) +
                 0.25 * max(-5, min(5, prem)) / 5 * 100 +
                 0.25 * min(mb, 10) / 10 * 100 +
                 0.20 * up_ratio * 100)
        result['sentiment_score_obj'] = round(max(0, min(100, score)), 1)
        result['score_source'] = 'v1_fallback'

    # 完整性检查
    required = ['limit_up_count', 'limit_down_count', 'break_count', 'max_board',
                'ly_premium', 'up_count', 'down_count', 'sh_pct']
    missing = [k for k in required if result.get(k) is None]
    if missing:
        result['source_status'] = 'partial'
        result['missing_fields'] = missing

    # 落库
    try:
        conn = _conn()
        conn.execute("""
            INSERT OR REPLACE INTO market_snapshot
            (trade_date, sh_pct, cyb_pct, turnover_yi, up_count, down_count,
             limit_up_count, limit_down_count, break_count, break_rate,
             max_board, board2plus_count, board3plus_count,
             ly_premium, ly_premium_cont, big_loss_count,
             sentiment_score_obj, source_status, raw_json, metrics_version, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            date_str, result.get('sh_pct'), result.get('cyb_pct'), result.get('turnover_yi'),
            result.get('up_count'), result.get('down_count'),
            result.get('limit_up_count'), result.get('limit_down_count'),
            result.get('break_count'), result.get('break_rate'),
            result.get('max_board'), result.get('board2plus_count'), result.get('board3plus_count'),
            result.get('ly_premium'), result.get('ly_premium_cont'), result.get('big_loss_count'),
            result.get('sentiment_score_obj'), result.get('source_status'),
            json.dumps(result, ensure_ascii=False), 'v2.0', _now(),
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning('T1落库失败: %s', e)
        result['source_status'] = 'fail'

    return result


# ─────────────────────────────────────────────────────────
# T2 主观复盘
# ─────────────────────────────────────────────────────────
def save_daily_review(data: dict) -> dict:
    trade_date = _fmt(data.get('trade_date') or _today())
    conn = _conn()
    conn.execute("""
        INSERT OR REPLACE INTO daily_review
        (trade_date, cycle_phase, phase_confidence, money_effect, loss_effect,
         money_effect_where, loss_effect_where,
         self_state, today_insight, unexpected, subjective_score, divergence_note,
         created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        trade_date, data.get('cycle_phase'), data.get('phase_confidence'),
        data.get('money_effect'), data.get('loss_effect'),
        data.get('money_effect_where'), data.get('loss_effect_where'),
        data.get('self_state'), data.get('today_insight'), data.get('unexpected'),
        data.get('subjective_score'), data.get('divergence_note'),
        _now(), _now(),
    ))
    conn.commit()
    conn.close()
    return {'ok': True, 'trade_date': trade_date}


def get_daily_review(trade_date: str) -> dict:
    conn = _conn()
    row = conn.execute("SELECT * FROM daily_review WHERE trade_date=?", (_fmt(trade_date),)).fetchone()
    conn.close()
    return dict(row) if row else {}


# ─────────────────────────────────────────────────────────
# T3 情绪载体
# ─────────────────────────────────────────────────────────
def save_carrier(data: dict) -> dict:
    trade_date = _fmt(data.get('trade_date') or _today())
    conn = _conn()
    # 若设为锚点，先清掉当日其他锚点
    if data.get('is_anchor'):
        conn.execute("UPDATE emotion_carrier SET is_anchor=0 WHERE trade_date=?", (trade_date,))
    cur = conn.execute("""
        INSERT INTO emotion_carrier
        (trade_date, code, name, carrier_role, board_height, carrier_status, is_anchor, note, created_at)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        trade_date, data.get('code'), data.get('name'), data.get('carrier_role'),
        data.get('board_height'), data.get('carrier_status'),
        1 if data.get('is_anchor') else 0, data.get('note'), _now(),
    ))
    conn.commit()
    cid = cur.lastrowid
    conn.close()
    # 同步加入实时监测重点关注（2026-10-09 用户需求：载体当日自动进实时监测，盘中异动提醒）
    try:
        import threading as _th
        from quant.realtime_service import get_service as _gs
        _code = str(data.get('code') or '')
        _name = str(data.get('name') or _code)
        _market = 1 if _code.startswith('6') else 0

        def _sync():
            try:
                svc = _gs()
                svc.add_stock(_code, _name, _market)
                svc.refresh_cache()
            except Exception:
                pass
        _th.Thread(target=_sync, daemon=True).start()
    except Exception:
        pass
    return {'ok': True, 'id': cid}


def list_carriers(trade_date: str) -> list:
    conn = _conn()
    rows = conn.execute("SELECT * FROM emotion_carrier WHERE trade_date=? ORDER BY is_anchor DESC, id ASC",
                        (_fmt(trade_date),)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_carrier(carrier_id: int) -> dict:
    conn = _conn()
    conn.execute("DELETE FROM emotion_carrier WHERE id=?", (carrier_id,))
    conn.commit()
    conn.close()
    return {'ok': True}


# ─────────────────────────────────────────────────────────
# T4 预案
# ─────────────────────────────────────────────────────────
def save_plan(data: dict) -> dict:
    """保存预案。falsify_condition 必填。"""
    falsify = (data.get('falsify_condition') or '').strip()
    if not falsify:
        return {'ok': False, 'error': '证伪条件(falsify_condition)必填，预案拒绝保存'}
    base = _fmt(data.get('base_date') or _today())
    tgt = _fmt(data.get('target_date') or '')
    conn = _conn()
    # 防重复：同一 (base,target) 只保留一条，以最后提交内容为准（覆盖式更新）
    ex = [r[0] for r in conn.execute(
        "SELECT plan_id FROM plan WHERE base_date=? AND target_date=? ORDER BY plan_id", (base, tgt))]
    if ex:
        keep = ex[-1]
        drop = ex[:-1]
        if drop:
            ph = ','.join('?' * len(drop))
            conn.execute(f"DELETE FROM verification WHERE plan_id IN ({ph})", drop)
            conn.execute(f"DELETE FROM plan WHERE plan_id IN ({ph})", drop)
        conn.execute("""
            UPDATE plan SET plan_direction=?, position_level=?, operation_style=?,
             must_do=?, must_not=?, plan_text=?, falsify_condition=?, scenarios=?, confidence=?,
             linked_carrier_ids=?, updated_at=?
            WHERE plan_id=?
        """, (
            data.get('plan_direction'), data.get('position_level'), data.get('operation_style'),
            data.get('must_do'), data.get('must_not'), data.get('plan_text'), falsify,
            json.dumps(data.get('scenarios') or [], ensure_ascii=False),
            data.get('confidence'),
            json.dumps(data.get('linked_carrier_ids') or [], ensure_ascii=False),
            _now(), keep,
        ))
        conn.commit()
        conn.close()
        return {'ok': True, 'plan_id': keep, 'updated': True}
    cur = conn.execute("""
        INSERT INTO plan
        (base_date, target_date, plan_direction, position_level, operation_style,
         must_do, must_not, plan_text, falsify_condition, scenarios, confidence,
         linked_carrier_ids, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        base, tgt,
        data.get('plan_direction'), data.get('position_level'), data.get('operation_style'),
        data.get('must_do'), data.get('must_not'), data.get('plan_text'), falsify,
        json.dumps(data.get('scenarios') or [], ensure_ascii=False),
        data.get('confidence'),
        json.dumps(data.get('linked_carrier_ids') or [], ensure_ascii=False),
        _now(), _now(),
    ))
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return {'ok': True, 'plan_id': pid}


def list_plans(base_date: str = None) -> list:
    conn = _conn()
    if base_date:
        rows = conn.execute("SELECT * FROM plan WHERE base_date=? ORDER BY plan_id DESC", (_fmt(base_date),)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM plan ORDER BY plan_id DESC LIMIT 30").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────
# T5 结果回填
# ─────────────────────────────────────────────────────────
def save_verification(data: dict) -> dict:
    conn = _conn()
    cur = conn.execute("""
        INSERT INTO verification
        (plan_id, verify_date, actual_phase, plan_result, falsify_triggered,
         score, error_type, lesson, plan_review, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        data.get('plan_id'), _fmt(data.get('verify_date') or _today()),
        data.get('actual_phase'), data.get('plan_result'),
        1 if data.get('falsify_triggered') else 0,
        data.get('score'), data.get('error_type'), data.get('lesson'),
        data.get('plan_review'), _now(),
    ))
    conn.commit()
    vid = cur.lastrowid
    conn.close()
    # 回填后自动沉淀规则（lesson 非空且样本够时）
    _maybe_archive_rule(data)
    return {'ok': True, 'verify_id': vid}


def list_verifications(plan_id: int = None) -> list:
    conn = _conn()
    if plan_id:
        rows = conn.execute("SELECT * FROM verification WHERE plan_id=? ORDER BY verify_id DESC", (plan_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM verification ORDER BY verify_id DESC LIMIT 30").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _maybe_archive_rule(data: dict):
    """T5 回填 → T6 规则沉淀（简化版：lesson非空即入库待验证）"""
    lesson = (data.get('lesson') or '').strip()
    error_type = data.get('error_type') or ''
    if not lesson:
        return
    conn = _conn()
    conn.execute("""
        INSERT INTO rule_library
        (rule_text, trigger_condition, sample_count, hit_count, status, era_tag, source_note, created_at)
        VALUES (?,?,?,?,?,?,?,?)
    """, (
        lesson,
        json.dumps({'error_type': error_type}, ensure_ascii=False),
        0, 0, '待验证', '2026H2',
        '来自T5回填 plan_id=%s' % data.get('plan_id'),
        _now(),
    ))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────
# 序列视图 + 相似日检索
# ─────────────────────────────────────────────────────────
def get_sequence(days: int = 30) -> dict:
    """情绪周期序列：T1客观分 + T2主观阶段 + 载体锚点"""
    conn = _conn()
    rows = conn.execute("""
        SELECT s.trade_date, s.sentiment_score_obj, s.break_rate, s.ly_premium,
               s.ly_premium_cont, s.max_board, s.source_status,
               s.limit_up_count, s.limit_down_count, s.break_count,
               s.board2plus_count, s.board3plus_count, s.big_loss_count,
               s.turnover_yi, s.up_count, s.down_count, s.sh_pct, s.cyb_pct,
               r.cycle_phase, r.subjective_score, r.money_effect, r.loss_effect
        FROM market_snapshot s
        LEFT JOIN daily_review r ON s.trade_date = r.trade_date
        ORDER BY s.trade_date DESC LIMIT ?
    """, (days,)).fetchall()
    conn.close()
    seq = [dict(r) for r in rows]
    seq.reverse()  # 时间升序
    return {'days': seq, 'count': len(seq)}


def find_similar_days(target_date: str, top_n: int = 5) -> dict:
    """相似日检索：按 break_rate/ly_premium/max_board/up_ratio 向量找历史最相似"""
    conn = _conn()
    target = conn.execute("SELECT * FROM market_snapshot WHERE trade_date=?",
                          (_fmt(target_date),)).fetchone()
    if not target:
        conn.close()
        return {'target': None, 'similar': []}

    target = dict(target)
    t_break = target.get('break_rate') or 0
    t_prem = target.get('ly_premium') or 0
    t_mb = target.get('max_board') or 0
    t_up = target.get('up_count') or 0
    t_down = target.get('down_count') or 0
    t_ratio = t_up / (t_up + t_down) if (t_up + t_down) > 0 else 0.5

    rows = conn.execute("""
        SELECT s.*, r.cycle_phase, r.today_insight, r.subjective_score
        FROM market_snapshot s LEFT JOIN daily_review r ON s.trade_date = r.trade_date
        WHERE s.trade_date != ? AND s.sentiment_score_obj IS NOT NULL
        ORDER BY s.trade_date DESC LIMIT 300
    """, (_fmt(target_date),)).fetchall()
    conn.close()

    scored = []
    for r in rows:
        d = dict(r)
        br = d.get('break_rate') or 0
        prem = d.get('ly_premium') or 0
        mb = d.get('max_board') or 0
        up = d.get('up_count') or 0
        down = d.get('down_count') or 0
        ratio = up / (up + down) if (up + down) > 0 else 0.5
        # 归一化欧氏距离（各指标量纲近似）
        dist = ((br - t_break) ** 2 + (prem - t_prem) ** 2 * 10 +
                (mb - t_mb) ** 2 * 20 + (ratio - t_ratio) ** 2 * 100) ** 0.5
        scored.append((dist, d))

    scored.sort(key=lambda x: x[0])
    similar = [d for _, d in scored[:top_n]]
    return {'target': target, 'similar': similar}



# ─────────────────────────────────────────────────────────
# T6 规则库 / T0 口径字典（只读）
# ─────────────────────────────────────────────────────────
def list_rules(status: str = None) -> list:
    conn = _conn()
    if status:
        rows = conn.execute("SELECT * FROM rule_library WHERE status=? ORDER BY rule_id DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM rule_library ORDER BY rule_id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_metric_dict() -> list:
    conn = _conn()
    rows = conn.execute("SELECT * FROM metric_dict ORDER BY metric_name").fetchall()
    conn.close()
    return [dict(r) for r in rows]



def get_market_snapshot(date_str: str) -> dict:
    """纯读库：返回某交易日 T1 记录（不含 raw_json 大字段）"""
    conn = _conn()
    row = conn.execute("SELECT * FROM market_snapshot WHERE trade_date=?", (_fmt(date_str),)).fetchone()
    conn.close()
    if not row:
        return {'trade_date': _fmt(date_str), 'source_status': 'missing'}
    d = dict(row)
    d.pop('raw_json', None)
    return d


# ─────────────────────────────────────────────────────────
# 交易日时间口径（T2/T4 归属日）
# ─────────────────────────────────────────────────────────
def get_time_context(base_date: str = None) -> dict:
    """归属交易日：下一交易日开盘(9:30)前填写均归属最近交易日；开盘后翻页。"""
    from datetime import datetime, timedelta
    from utils import _load_holidays, get_prev_trading_day
    now = datetime.now()
    today = now.strftime('%Y%m%d')
    hol = set(_load_holidays())

    def _is_td(d):
        dt = datetime.strptime(d, '%Y%m%d')
        return dt.weekday() < 5 and d not in hol

    if base_date:
        eff = _fmt(base_date)
    elif _is_td(today) and (now.hour * 60 + now.minute) >= 9 * 60 + 30:
        eff = today
    else:
        eff = get_prev_trading_day(today)

    dt = datetime.strptime(eff, '%Y%m%d') + timedelta(days=1)
    while not _is_td(dt.strftime('%Y%m%d')):
        dt += timedelta(days=1)
    nxt = dt.strftime('%Y%m%d')

    return {
        'now': now.strftime('%Y-%m-%d %H:%M:%S'),
        'effective_trade_date': eff,
        'next_trade_date': nxt,
        'is_preopen_window': eff != today,
    }


# ─────────────────────────────────────────────────────────
# 路由注册
# ─────────────────────────────────────────────────────────
def register_sentiment_review_routes(app):
    @app.get('/api/sentiment/snapshot')
    def api_snapshot(date: str = None):
        """纯读库：默认读归属交易日的 T1 记录（采集走 POST）"""
        d = date or get_time_context()['effective_trade_date']
        return get_market_snapshot(d)

    @app.post('/api/sentiment/snapshot/collect')
    def api_collect_snapshot(date: str = None):
        """仅支持采集自然日当天；历史数据由回填脚本负责"""
        d = _fmt(date) if date else _today()
        if d != _today():
            return {'ok': False, 'error': '仅支持采集当日数据（历史数据由回填脚本负责），请求日期=%s' % d}
        from datetime import datetime as _dt
        if _dt.now().hour < 15:
            return {'ok': False, 'error': '盘前/盘中数据不完整，15:00 收盘后再采集（17:05 自动采集）'}
        return collect_market_snapshot(d)

    # T2
    @app.post('/api/sentiment/review')
    def api_save_review(data: dict):
        return save_daily_review(data)

    @app.get('/api/sentiment/review/{trade_date}')
    def api_get_review(trade_date: str):
        return get_daily_review(trade_date)

    # T3
    @app.post('/api/sentiment/carrier')
    def api_save_carrier(data: dict):
        return save_carrier(data)

    @app.get('/api/sentiment/carriers/{trade_date}')
    def api_list_carriers(trade_date: str):
        return list_carriers(trade_date)

    @app.delete('/api/sentiment/carrier/{carrier_id}')
    def api_delete_carrier(carrier_id: int):
        return delete_carrier(carrier_id)

    # T4
    @app.post('/api/sentiment/plan')
    def api_save_plan(data: dict):
        return save_plan(data)

    @app.get('/api/sentiment/plans')
    def api_list_plans(base_date: str = None):
        return list_plans(base_date)

    # T5
    @app.post('/api/sentiment/verify')
    def api_save_verify(data: dict):
        return save_verification(data)

    @app.get('/api/sentiment/verifications')
    def api_list_verifications(plan_id: int = None):
        return list_verifications(plan_id)

    # 序列 + 相似日
    @app.get('/api/sentiment/sequence')
    def api_sequence(days: int = 30):
        return get_sequence(days)

    @app.get('/api/sentiment/similar/{trade_date}')
    def api_similar(trade_date: str, top_n: int = 5):
        return find_similar_days(trade_date, top_n)

    # T6 / T0 只读
    # ── 闭环一：历史规则参谋（写预案时匹配）──
    @app.get('/api/sentiment/rules/suggest')
    def api_rules_suggest(phase: str = '', direction: str = '', text: str = '', top: int = 5):
        return suggest_rules(phase, direction, text, top)

    # ── 闭环三：周期×载体一致性校准（背离=校准信号）──
    @app.get('/api/sentiment/consistency')
    def api_consistency(days: int = 60):
        return consistency_report(days)

    @app.get('/api/sentiment/rules')
    def api_list_rules(status: str = None):
        return list_rules(status)

    @app.get('/api/sentiment/metrics')
    def api_list_metrics():
        return list_metric_dict()

    # 时间口径（T2/T4 归属交易日）
    @app.get('/api/sentiment/time_context')
    def api_time_context(base_date: str = None):
        return get_time_context(base_date)

    @app.get('/api/sentiment/trade_calendar')
    def api_trade_calendar(days_back: int = 150, days_fwd: int = 45):
        """真实交易日列表（YYYYMMDD，已滤周末+节假日）——供前端日期推算/回填计数"""
        from datetime import datetime, timedelta
        from utils import _load_holidays
        hol = set(_load_holidays())
        now = datetime.now()
        out = []
        d = now - timedelta(days=days_back)
        end = now + timedelta(days=days_fwd)
        while d <= end:
            ds = d.strftime('%Y%m%d')
            if d.weekday() < 5 and ds not in hol:
                out.append(ds)
            d += timedelta(days=1)
        return {'dates': out}

    logger.info('情绪复盘路由已注册: /api/sentiment/*')


# ═══════════════════════════════════════════════════════════
# 闭环一：历史规则参谋（2026-10-10）
# ═══════════════════════════════════════════════════════════
_PHASE_WORDS = ['冰点', '上升', '下降', '分歧', '退潮', '修复', '发酵', '高潮', '主升']
_DIR_WORDS = ['看修复', '看延续', '看分歧', '看退潮', '修复', '延续', '分歧', '退潮']


def _bigrams(t):
    t = re.sub(r"[\s，。；、,.!?！？()（）\[\]【】\"']", '', t or '')
    return set(t[i:i + 2] for i in range(len(t) - 1))


def suggest_rules(phase='', direction='', text='', top=5):
    """按 周期阶段 + 预案方向 + 文本二元组重叠 给历史规则打分，返回参谋清单"""
    conn = _conn()
    rows = conn.execute(
        "SELECT rule_id, rule_text, trigger_condition, sample_count, hit_count, status, era_tag, created_at "
        "FROM rule_library ORDER BY rule_id DESC LIMIT 200").fetchall()
    conn.close()
    tb = _bigrams(text)
    out = []
    for r in rows:
        d = dict(r)
        rt = d.get('rule_text') or ''
        tc = d.get('trigger_condition') or ''
        score = 0.0
        if phase and (phase in rt or phase in tc):
            score += 2.0
        for w in _PHASE_WORDS:
            if phase and w.startswith(phase[:2]) and (w in rt or w in tc):
                score += 0.5
        if direction:
            core = direction.replace('看', '')
            if core and (core in rt or core in tc):
                score += 1.0
        if tb:
            ov = len(tb & _bigrams(rt))
            score += min(2.0, ov * 0.3)
        n = (d.get('sample_count') or 0)
        hit = (d.get('hit_count') or 0)
        d['hit_rate'] = round(hit / n, 2) if n else None
        d['match_score'] = round(score, 2)
        if score > 0:
            out.append(d)
    out.sort(key=lambda x: -x['match_score'])
    return out[:top]


# ═══════════════════════════════════════════════════════════
# 闭环三：周期×载体一致性校准（2026-10-10）
# 周期判断与载体反馈互为对照器：背离 = 要么周期判断错、要么载体错 → T+1 大盘裁定
# ═══════════════════════════════════════════════════════════
PHASE_SIGN = {'上升': 1, '上升分歧': 1, '下降': -1, '下降中继': -1, '冰点': -1}
STATUS_W = {'涨停': 1.0, '大涨': 0.7, '炸板': -0.3, '断板': -0.5, '大面': -1.0, '核按钮': -1.3}


def _ensure_consistency_table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS consistency_log ("
                 "trade_date TEXT PRIMARY KEY, cycle_phase TEXT, phase_sign INTEGER,"
                 "feedback_score REAL, feedback_sign INTEGER, consistent INTEGER,"
                 "divergence_type TEXT, next_day_market_pct REAL, verdict TEXT,"
                 "created_at TEXT, updated_at TEXT)")


def consistency_report(days=60):
    conn = _conn()
    _ensure_consistency_table(conn)
    # 近 N 交易日的复盘 + 载体
    revs = conn.execute(
        "SELECT trade_date, cycle_phase FROM daily_review ORDER BY trade_date DESC LIMIT ?",
        (days,)).fetchall()
    rows_out = []
    for d, phase in revs:
        crows = conn.execute(
            "SELECT carrier_role, carrier_status, is_anchor FROM emotion_carrier WHERE trade_date=?",
            (d,)).fetchall()
        if not crows or not phase or phase not in PHASE_SIGN:
            continue
        ws, tot = 0.0, 0.0
        for role, st, anchor in crows:
            w = 2.0 if anchor else 1.0
            w *= 1.5 if role in ('情绪先锋', '权重龙头', '总龙头') else 1.0
            ws += w * STATUS_W.get(st, 0.0)
            tot += w
        fb = round(ws / tot, 2) if tot else 0.0
        ps = PHASE_SIGN[phase]
        fs = 1 if fb > 0.15 else (-1 if fb < -0.15 else 0)
        consistent = 1 if fs == 0 or fs == ps else 0
        div_type = '' if consistent else ('周期判断存疑' if ps > 0 else '载体存疑（冰点强载体=转机信号）')
        # T+1 大盘裁定（market_snapshot.sh_pct 次日）
        nx = conn.execute(
            "SELECT sh_pct FROM market_snapshot WHERE trade_date > ? ORDER BY trade_date LIMIT 1",
            (d,)).fetchone()
        nx_pct = nx[0] if nx else None
        verdict = ''
        if not consistent and nx_pct is not None:
            if nx_pct > 0.2:
                verdict = '周期判断对→载体错' if ps > 0 else '周期判断错→载体对'
            elif nx_pct < -0.2:
                verdict = '周期判断错→载体对' if ps > 0 else '周期判断对→载体错'
            else:
                verdict = '震荡·无法裁定'
        conn.execute(
            "INSERT OR REPLACE INTO consistency_log"
            "(trade_date, cycle_phase, phase_sign, feedback_score, feedback_sign, consistent,"
            " divergence_type, next_day_market_pct, verdict, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (d, phase, ps, fb, fs, consistent, div_type, nx_pct, verdict, _now(), _now()))
        rows_out.append({'date': d, 'cycle_phase': phase, 'feedback_score': fb,
                         'consistent': bool(consistent), 'divergence_type': div_type,
                         'next_day_market_pct': nx_pct, 'verdict': verdict})
    conn.commit()
    conn.close()
    divs = [r for r in rows_out if not r['consistent']]
    done = [r for r in divs if r['verdict'] and '无法' not in r['verdict']]
    cyc_right = sum(1 for r in done if '周期判断对' in r['verdict'])
    car_right = sum(1 for r in done if '载体对' in r['verdict'])
    stats = {'days': len(rows_out), 'divergences': len(divs), 'adjudicated': len(done),
             'cycle_right': cyc_right, 'carrier_right': car_right}
    return {'rows': rows_out[:30], 'stats': stats}
