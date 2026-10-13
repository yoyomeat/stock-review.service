"""App JSON API 路由：仪表盘 / 单日复盘 / 对比"""

import csv, json, glob, os
from fastapi import Query

from data import get_available_dates, load_review, build_trend_data, build_summary_stats, load_date_sentiments, detect_regime_change
from lianban import compute_lianban_tiers

KPH_SECTORS_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'kph_sectors')
CSV_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'csv')


def _load_code_name_map(date_str: str) -> dict:
    fp = os.path.join(CSV_DIR, 'stock_daily_%s.csv' % date_str)
    if not os.path.exists(fp):
        return {}
    result = {}
    try:
        with open(fp, encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                code = row.get('股票代码', '').strip()
                name = row.get('股票名称', '').strip()
                if code and name:
                    result[code] = name
    except Exception:
        pass
    return result


def _load_latest_kph_sectors():
    files = sorted(glob.glob(os.path.join(KPH_SECTORS_DIR, '*.json')))
    if not files:
        return []
    try:
        with open(files[-1], encoding='utf-8') as f:
            data = json.load(f)
        return data.get('sectors', [])
    except Exception:
        return []




def register_app_api_routes(app):

    @app.get("/api/dashboard")
    def api_dashboard():
        """仪表盘汇总数据 JSON API"""
        all_dates = get_available_dates()
        dates = all_dates[-10:] if len(all_dates) > 10 else all_dates
        trend = build_trend_data(dates)
        stats = build_summary_stats(dates)
        latest = all_dates[-1] if all_dates else None
        latest_data = load_review(latest["date"]) if latest else None
        prev_data = None
        prev_date_str = None
        if latest_data and len(all_dates) >= 2:
            prev_data = load_review(all_dates[-2]["date"])
            prev_date_str = all_dates[-2]["date"]
        regime_change = detect_regime_change(latest_data, prev_data, prev_date_str)
        lianban = compute_lianban_tiers(latest["date"]) if latest else {"tiers": [], "total_zt": 0, "highest_board": 0}
        date_sentiments = load_date_sentiments(all_dates)

        # Strip heavy fields — dashboard只用21个字段+策略数据
        _dashboard_fields = {
            'date', 'composite', 'sentiment_score', 'sentiment_level',
            'profit_score', 'profit_level', 'cycle_label', 'position',
            'position_label', 'style', 'mainline', 'action',
            'up_count', 'down_count', 'zt_count', 'dt_count', 'zb_rate',
            'amt_total', 'strategy_text', 'stop_loss_text', 'take_profit_text',
            'confidence', 'sector_top5', 'mainline_tracker', 'trade_plan',
            'mainline_state',
        }
        if latest_data:
            latest_data = {k: v for k, v in latest_data.items() if k in _dashboard_fields}
        if prev_data:
            prev_data = None  # dashboard不需要前一天数据

        # 精简 kph_sectors：保留板块名、涨幅、龙头
        _kph_raw = _load_latest_kph_sectors()
        _kph_lite = []
        for ks in (_kph_raw or [])[:10]:
            _stocks_raw = ks.get('stocks', []) or []
            _leaders = [{'name': s.get('name', ''), 'rank_tag': s.get('rank_tag', '')} for s in _stocks_raw if s.get('rank_tag', '').startswith('\u9f99')]
            _kph_lite.append({
                'plate_name': ks.get('plate_name', ''),
                'change_pct': ks.get('change_pct', 0),
                'amount': ks.get('amount', 0),
                'leaders': _leaders[:3],
            })

        # 补全tracker中pool的股票名称
        if latest_data and latest_data.get('mainline_tracker') and latest_data.get('date'):
            code_name = _load_code_name_map(latest_data['date'])
            for sector, t in latest_data['mainline_tracker'].items():
                for s in t.get('mainline_pool', []):
                    if not s.get('name') and s.get('code') in code_name:
                        s['name'] = code_name[s['code']]

        return {
            "dates": all_dates,
            "trend": trend,
            "stats": stats,
            "latest": latest_data,
            "regime_change": regime_change,
            "lianban": lianban,
            "date_sentiments": date_sentiments,
            "kph_sectors": _kph_lite,
        }

    @app.get("/api/review/{date_str}/full")
    def api_review_full(date_str: str):
        """单日完整复盘数据 JSON API"""
        from backtest_engine import evaluate_regime_transition

        dates = get_available_dates()
        data = load_review(date_str)
        if not data:
            return {"error": f"未找到 {date_str} 的复盘数据"}

        date_list = [d["date"] for d in dates]
        idx = date_list.index(date_str) if date_str in date_list else -1

        prev_date = date_list[idx - 1] if idx > 0 else None
        next_date = date_list[idx + 1] if idx < len(date_list) - 1 else None

        regime_analysis = None
        if idx > 0:
            prev_data = load_review(date_list[idx - 1])
            if prev_data:
                action, reason, factor = evaluate_regime_transition(
                    prev_data, data, {}, {}, {}, idx
                )
                if reason:
                    regime_analysis = {
                        "action": action,
                        "reason": reason,
                        "factor": factor,
                        "prev_date": date_list[idx - 1],
                        "prev_sentiment": prev_data.get("sentiment_score", 0),
                        "curr_sentiment": data.get("sentiment_score", 0),
                        "sentiment_delta": data.get("sentiment_score", 0) - prev_data.get("sentiment_score", 0),
                        "prev_profit": prev_data.get("profit_score", 0),
                        "curr_profit": data.get("profit_score", 0),
                        "profit_delta": data.get("profit_score", 0) - prev_data.get("profit_score", 0),
                        "prev_position": prev_data.get("position", 0),
                        "curr_position": data.get("position", 0),
                        "position_delta": data.get("position", 0) - prev_data.get("position", 0),
                        "prev_dt": prev_data.get("dt_count", 0),
                        "curr_dt": data.get("dt_count", 0),
                    }

        return {
            "data": data,
            "prev_date": prev_date,
            "next_date": next_date,
            "regime_analysis": regime_analysis,
        }

    @app.get("/api/compare")
    def api_compare(a: str = Query(None), b: str = Query(None)):
        """两天对比数据 JSON API"""
        if not a or not b:
            return {"error": "请提供 a 和 b 两个日期参数"}

        data_a = load_review(a)
        data_b = load_review(b)
        if not data_a:
            return {"error": f"未找到 {a} 的复盘数据"}
        if not data_b:
            return {"error": f"未找到 {b} 的复盘数据"}

        metrics = [
            ("sentiment_score", "市场情绪"), ("profit_score", "赚钱效应"),
            ("position", "仓位"), ("composite", "综合得分"),
            ("confidence", "置信度"), ("zt_count", "涨停数"),
            ("dt_count", "跌停数"), ("zb_rate", "炸板率"),
            ("sentiment_accel", "情绪加速度"), ("profit_accel", "赚钱流向"),
            ("intraday_support", "日内承接力"), ("high_low_gap", "高低位温差"),
            ("first_board_promo_rate", "首板晋级率"),
        ]
        diff = []
        for key, label in metrics:
            va = data_a.get(key, 0) or 0
            vb = data_b.get(key, 0) or 0
            diff.append({
                "label": label, "key": key,
                "val_a": va, "val_b": vb, "delta": round(vb - va, 1),
            })

        return {
            "data_a": data_a,
            "data_b": data_b,
            "diff": diff,
        }


def register_quant_profile_routes(app):
    """量化行为画像路由"""

    @app.get("/api/quant_profile")
    async def api_quant_profile():
        """获取最新量化画像数据"""
        from quant.quant_profile import get_latest_profile
        result = get_latest_profile()
        if not result:
            return {"error": "暂无量化画像数据", "quant_stocks": []}
        return result

    @app.post("/api/quant_profile/run")
    async def api_quant_profile_run():
        """手动触发量化画像生成"""
        from quant.quant_profile import generate_daily_profile
        try:
            result = generate_daily_profile()
            return result or {"error": "画像生成失败"}
        except Exception as e:
            return {"error": str(e)}

    @app.get("/api/quant_profile/history")
    async def api_quant_profile_history(days: int = 10):
        """获取量化画像历史"""
        from quant.quant_profile import get_profile_history
        return {"history": get_profile_history(days)}

    @app.post("/api/quant_profile/feedback")
    async def api_quant_profile_feedback(code: str, label: str):
        """用户反馈：标记是否为量化股"""
        import sqlite3, json
        from config.quant_profile_rules import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        conn.execute('''INSERT INTO feedback (date, code, user_label, model_score, create_time)
                       VALUES (?, ?, ?, 0, ?)''',
                     (datetime.now().strftime('%Y%m%d'), code, label,
                      datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        conn.close()
        return {"status": "ok", "code": code, "label": label}


def register_prediction_routes(app):
    """中小周期预测引擎路由"""

    @app.get("/api/prediction")
    async def api_prediction():
        """获取最新预测结果"""
        from quant.prediction_engine import get_latest_prediction, get_win_rate_stats
        raw = get_latest_prediction()
        stats = get_win_rate_stats(30)
        # 扁平DB行 → 嵌套结构 + 补充新字段
        from quant.prediction_engine import _describe_factors, _estimate_composite_range
        pred = None
        if raw:
            factors = {
                'composite': raw.get('composite', 50),
                'vol_ratio': raw.get('vol_ratio', 1),
                'concentration': raw.get('concentration', 50),
                'pool_composite': raw.get('pool_composite', 50),
                'pool_divergence': raw.get('pool_divergence', 0.5),
                'exp_gap': raw.get('exp_gap', 0),
            }
            pred_dir = raw.get('pred_direction', 'flat')
            pred = {
                'date': raw.get('date'),
                'factors': factors,
                'sentiment': {
                    'direction': pred_dir,
                    'confidence': raw.get('pred_confidence'),
                    'rule': raw.get('pred_rule'),
                    'reason': '',
                    'expected_range': _estimate_composite_range(pred_dir, factors['composite'], factors['exp_gap']),
                },
                'style': {
                    'result': raw.get('pred_style'),
                    'confidence': 50,
                    'rule': '',
                    'reason': '',
                },
                'factor_descs': _describe_factors(factors),
                'position': raw.get('pred_position'),
                'quant_reference': None,
            }
        return {"prediction": pred, "win_rate": stats}

    @app.get("/api/prediction/history")
    async def api_prediction_history(days: int = 30):
        """获取预测历史"""
        from quant.prediction_engine import get_prediction_history
        return {"history": get_prediction_history(days)}

    @app.post("/api/prediction/generate")
    async def api_prediction_generate():
        """手动触发预测生成"""
        from data import get_available_dates, load_review
        from quant.prediction_engine import generate_prediction
        try:
            dates = get_available_dates()
            if len(dates) < 2:
                return {"error": "数据不足"}
            latest = load_review(dates[-1]["date"])
            prev = load_review(dates[-2]["date"])
            if not latest:
                return {"error": "无法加载最新review"}
            return generate_prediction(latest, prev)
        except Exception as e:
            return {"error": str(e)}

    @app.post("/api/prediction/verify")
    async def api_prediction_verify(date: str, actual_composite: float):
        """回填实际值并验证"""
        from quant.prediction_engine import verify_and_update
        verify_and_update(date, actual_composite)
        return {"status": "ok", "date": date, "actual_composite": actual_composite}


def register_ipo_score_routes(app):
    """新股评分路由（V2四维度评分）"""

    @app.get("/api/ipo_score")
    async def api_ipo_score(date: str = None):
        """获取今日新股评分（V2四维度，每次请求重新识别+评分）+ 新股情绪周期"""
        from quant.ipo_score_v2 import score_all_new_stocks_v2
        from quant.ipo_sentiment import calc_sentiment
        scores = score_all_new_stocks_v2(date)
        sentiment = calc_sentiment()
        return {
            "scores": scores,
            "date": date or __import__('datetime').datetime.now().strftime('%Y%m%d'),
            "sentiment": sentiment,
        }

    @app.get("/api/ipo_score/{code}")
    async def api_ipo_score_detail(code: str, date: str = None):
        """获取指定新股的详细评分（V2）"""
        from quant.ipo_score_v2 import calc_ipo_score_v2
        from quant.ipo_monitor import get_ipo_monitor
        result = calc_ipo_score_v2(code, date)
        # 附带分钟量能数据
        monitor = get_ipo_monitor()
        result['minute_volume'] = monitor.get_minute_volume_compare(code, date)
        return result
