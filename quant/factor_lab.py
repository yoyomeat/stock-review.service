"""因子质量分析工具（消费层，只读）

分析 review JSON 中的因子预测力：
- IC（Rank相关系数）：因子值与未来收益的相关性
- ICIR：IC均值/IC标准差，衡量因子稳定性
- 换手率：TOP N 每日变化比例
- 衰减曲线：IC随持有天数的变化

数据来源：
- 因子值：reports/review_*.json
- 未来收益：data/csv/stock_daily_*.csv
"""
import os
import json
import numpy as np


def _load_review(date_str, review_dir='reports'):
    """加载单日 review JSON"""
    fp = os.path.join(review_dir, f'review_{date_str}.json')
    if not os.path.exists(fp):
        return None
    try:
        with open(fp, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _load_prices(date_str, csv_dir='data/csv'):
    """加载单日价格数据 {code: {open, close, ...}}"""
    fp = os.path.join(csv_dir, f'stock_daily_{date_str}.csv')
    if not os.path.exists(fp):
        return {}
    result = {}
    try:
        import csv
        with open(fp, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get('\u80a1\u7968\u4ee3\u7801', '').strip()
                if not code:
                    continue
                try:
                    result[code] = {
                        'open': float(row.get('\u5f00\u76d8\u4ef7', 0)),
                        'close': float(row.get('\u6700\u65b0\u4ef7', 0)),
                    }
                except (ValueError, TypeError):
                    pass
    except Exception:
        pass
    return result


def _get_available_dates(review_dir='reports'):
    """获取所有有 review JSON 的日期"""
    dates = []
    if not os.path.isdir(review_dir):
        return dates
    for fn in sorted(os.listdir(review_dir)):
        if fn.startswith('review_') and fn.endswith('.json'):
            date = fn[7:15]
            if len(date) == 8 and date.isdigit():
                dates.append(date)
    return dates


def _spearmanr(x, y):
    """Spearman rank correlation（纯 numpy 实现）

    Returns:
        (correlation, p_value) — p_value 用 t 近似
    """
    n = len(x)
    if n < 3:
        return 0.0, 1.0

    # 排名
    def _rank(arr):
        sorted_idx = np.argsort(arr)
        ranks = np.empty_like(sorted_idx, dtype=float)
        ranks[sorted_idx] = np.arange(1, len(arr) + 1)
        return ranks

    rx = _rank(np.array(x, dtype=float))
    ry = _rank(np.array(y, dtype=float))

    # Pearson of ranks
    mx, my = np.mean(rx), np.mean(ry)
    dx, dy = rx - mx, ry - my
    cov = np.sum(dx * dy)
    sx = np.sqrt(np.sum(dx ** 2))
    sy = np.sqrt(np.sum(dy ** 2))
    if sx == 0 or sy == 0:
        return 0.0, 1.0

    r = cov / (sx * sy)

    # t-test 近似 p-value（纯 numpy）
    if abs(r) >= 1.0:
        return r, 0.0
    t_stat = r * np.sqrt((n - 2) / (1 - r ** 2))
    # 双尾 p-value 近似（正态近似，n>30 时足够精确）
    z = abs(t_stat)
    # Abramowitz-Stegun 近似正态 CDF
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p_approx = 0.3275911
    sign = 1 if z >= 0 else -1
    x = z / np.sqrt(2)
    t_inner = 1.0 / (1.0 + p_approx * x)
    erf_val = 1.0 - (((((a5 * t_inner + a4) * t_inner) + a3) * t_inner + a2) * t_inner + a1) * t_inner * np.exp(-x * x)
    cdf = 0.5 * (1.0 + sign * erf_val)
    p = 2 * (1 - cdf)

    return float(r), float(p)


def _rank(arr):
    """排名（用于外部调用）"""
    sorted_idx = np.argsort(arr)
    ranks = np.empty_like(sorted_idx, dtype=float)
    ranks[sorted_idx] = np.arange(1, len(arr) + 1)
    return ranks


class FactorLab:
    """因子质量分析工具"""

    @staticmethod
    def calc_ic(factor_name, forward_days=1, review_dir='reports', csv_dir='data/csv'):
        """计算因子 IC（Rank 相关系数）

        自动区分全局因子和个股因子：
        - 全局因子（review级别，如 profit_score）：每天一个值，和次日组合收益做相关
        - 个股因子（pick级别）：每只股票一个值，和个股收益做相关

        Args:
            factor_name: review JSON 或 pick 中的字段名
            forward_days: 未来 N 天收益
            review_dir: review JSON 目录
            csv_dir: CSV 价格目录

        Returns:
            dict: ic_series, ic_mean, ic_std, icir, positive_rate, n_days
        """
        dates = _get_available_dates(review_dir)
        if not dates:
            return {'error': 'no review data'}

        # 预加载所有价格（避免重复IO）
        price_cache = {}

        def get_prices(date_str):
            if date_str not in price_cache:
                price_cache[date_str] = _load_prices(date_str, csv_dir)
            return price_cache[date_str]

        # 第一步：判断是全局因子还是个股因子
        # 检查前5个有 picks 的 review，看因子是否在 pick 中
        is_global = True
        check_count = 0
        for d in dates:
            review = _load_review(d, review_dir)
            if not review:
                continue
            picks = (review.get('trade_plan') or {}).get('picks', [])
            if not picks:
                continue
            # 检查因子是否在 review 级别
            if review.get(factor_name) is not None:
                is_global = True
            # 检查因子是否在 pick 级别
            if any(factor_name in p for p in picks):
                is_global = False
                break
            check_count += 1
            if check_count >= 5:
                break

        ic_series = []
        detail = []

        if is_global:
            # 全局因子：每天一个值，和次日组合收益做相关
            factor_vals = []
            portfolio_returns = []

            for i in range(len(dates) - forward_days):
                review = _load_review(dates[i], review_dir)
                if not review:
                    continue

                fv = review.get(factor_name)
                if fv is None:
                    continue

                picks = (review.get('trade_plan') or {}).get('picks', [])
                if not picks:
                    continue

                # 计算次日组合收益（picks 等权平均）
                d1_prices = get_prices(dates[i])
                fwd_prices = get_prices(dates[i + forward_days])

                rets = []
                for pick in picks:
                    code = pick.get('code', '')
                    if not code:
                        continue
                    d1_open = d1_prices.get(code, {}).get('open', 0)
                    fwd_close = fwd_prices.get(code, {}).get('close', 0)
                    if d1_open > 0 and fwd_close > 0:
                        rets.append((fwd_close / d1_open - 1) * 100)

                if rets:
                    factor_vals.append(float(fv))
                    portfolio_returns.append(float(np.mean(rets)))

            # 计算全局 IC（整个时间序列的 rank correlation）
            if len(factor_vals) >= 10:
                ic, pval = _spearmanr(factor_vals, portfolio_returns)
                ic_series = [ic]  # 全局因子只有一个 IC 值
                detail = [{
                    'type': 'global',
                    'ic': round(ic, 4),
                    'pval': round(pval, 4),
                    'n_days': len(factor_vals),
                    'interpretation': 'factor vs portfolio return (cross-section)',
                }]
            else:
                return {'error': f'insufficient data ({len(factor_vals)} days)', 'n_days': 0}

        else:
            # 个股因子：每只股票一个值，和个股收益做相关
            for i in range(len(dates) - forward_days):
                review = _load_review(dates[i], review_dir)
                if not review:
                    continue

                picks = (review.get('trade_plan') or {}).get('picks', [])
                if not picks:
                    continue

                d1_prices = get_prices(dates[i])
                fwd_prices = get_prices(dates[i + forward_days])

                returns = []
                factor_vals = []

                for pick in picks:
                    code = pick.get('code', '')
                    if not code:
                        continue

                    fv = pick.get(factor_name)
                    if fv is None:
                        continue

                    d1_open = d1_prices.get(code, {}).get('open', 0)
                    fwd_close = fwd_prices.get(code, {}).get('close', 0)
                    if d1_open <= 0 or fwd_close <= 0:
                        continue

                    fwd_ret = (fwd_close / d1_open - 1) * 100
                    returns.append(fwd_ret)
                    factor_vals.append(float(fv))

                if len(returns) >= 3:
                    ic, pval = _spearmanr(factor_vals, returns)
                    ic_series.append(ic)
                    detail.append({
                        'date': dates[i],
                        'ic': round(ic, 4),
                        'pval': round(pval, 4),
                        'n': len(returns),
                    })

        if not ic_series:
            return {'error': 'no valid IC computed', 'n_days': 0}

        ic_arr = np.array(ic_series)
        return {
            'factor': factor_name,
            'forward_days': forward_days,
            'ic_series': [round(x, 4) for x in ic_series],
            'ic_mean': round(float(np.mean(ic_arr)), 4),
            'ic_std': round(float(np.std(ic_arr)), 4),
            'icir': round(float(np.mean(ic_arr) / np.std(ic_arr)), 2) if np.std(ic_arr) > 0 else 0,
            'positive_rate': round(float(np.mean(ic_arr > 0)), 3),
            'n_days': len(ic_series),
            'detail': detail,
        }

    @staticmethod
    def calc_turnover(factor_name, top_n=20, review_dir='reports'):
        """因子换手率（仅适用于个股因子）

        Args:
            factor_name: 因子名（pick 级别）
            top_n: 取 TOP N 计算换手
            review_dir: review 目录

        Returns:
            dict: turnover_series, avg_turnover
        """
        dates = _get_available_dates(review_dir)
        prev_top = set()
        turnover_series = []

        for date in dates:
            review = _load_review(date, review_dir)
            if not review:
                continue

            picks = (review.get('trade_plan') or {}).get('picks', [])
            if not picks:
                continue

            # 按因子排序取 TOP N（仅 pick 级别因子）
            scored = []
            for p in picks:
                fv = p.get(factor_name)
                if fv is not None:
                    scored.append((p.get('code', ''), float(fv)))
            if not scored:
                continue
            scored.sort(key=lambda x: x[1], reverse=True)
            top_codes = set(c for c, _ in scored[:top_n])

            if prev_top:
                overlap = len(top_codes & prev_top)
                turnover = 1.0 - overlap / max(len(top_codes), 1)
                turnover_series.append(turnover)
            prev_top = top_codes

        if not turnover_series:
            return {'error': 'no turnover data (factor may be global, not pick-level)'}

        return {
            'factor': factor_name,
            'top_n': top_n,
            'turnover_series': [round(x, 3) for x in turnover_series],
            'avg_turnover': round(float(np.mean(turnover_series)), 3),
            'n_days': len(turnover_series),
        }

    @staticmethod
    def calc_decay(factor_name, max_lag=5, review_dir='reports', csv_dir='data/csv'):
        """因子衰减曲线

        Args:
            factor_name: 因子名
            max_lag: 最大持有天数
            review_dir: review 目录
            csv_dir: CSV 目录

        Returns:
            dict: {lag_1: IC, lag_2: IC, ..., optimal_lag: int}
        """
        results = {}
        for lag in range(1, max_lag + 1):
            r = FactorLab.calc_ic(factor_name, forward_days=lag,
                                  review_dir=review_dir, csv_dir=csv_dir)
            if 'error' not in r:
                results[f'lag_{lag}'] = r['ic_mean']
            else:
                results[f'lag_{lag}'] = None

        # 找最优 lag
        valid = {k: v for k, v in results.items() if v is not None}
        if valid:
            optimal = max(valid, key=valid.get)
            optimal_lag = int(optimal.split('_')[1])
        else:
            optimal_lag = None

        return {
            'factor': factor_name,
            'max_lag': max_lag,
            'decay': results,
            'optimal_lag': optimal_lag,
        }

    @staticmethod
    def report(factor_name, forward_days=None, review_dir='reports', csv_dir='data/csv'):
        """一键生成因子报告

        Args:
            factor_name: 因子名
            forward_days: 持有天数列表，默认 [1, 2, 3, 5]
        """
        if forward_days is None:
            forward_days = [1, 2, 3, 5]

        print(f"\n{'='*50}")
        print(f"因子报告: {factor_name}")
        print(f"{'='*50}")

        # IC 分析
        print(f"\n--- IC 分析 ---")
        first_ic = None
        for fd in forward_days:
            r = FactorLab.calc_ic(factor_name, forward_days=fd,
                                  review_dir=review_dir, csv_dir=csv_dir)
            if 'error' in r:
                print(f"  D+{fd}: {r['error']}")
            else:
                if first_ic is None:
                    first_ic = r
                    if r.get('detail') and r['detail'][0].get('type') == 'global':
                        print(f"  类型: 全局因子（{r['detail'][0].get('n_days', '?')}天截面相关）")
                    else:
                        print(f"  类型: 个股因子（日内rank相关）")
                sig = '***' if abs(r['ic_mean']) > 0.1 else '**' if abs(r['ic_mean']) > 0.05 else '*' if abs(r['ic_mean']) > 0.02 else ''
                if first_ic and first_ic.get('detail') and first_ic['detail'][0].get('type') == 'global':
                    # 全局因子：只有一个 IC，不显示 std/ICIR/胜率
                    print(f"  D+{fd}: IC={r['ic_mean']:+.4f}, n={r['detail'][0].get('n_days', '?')}天 {sig}")
                else:
                    print(f"  D+{fd}: IC={r['ic_mean']:+.4f} ± {r['ic_std']:.4f}, "
                          f"ICIR={r['icir']:+.2f}, 胜率={r['positive_rate']:.1%}, "
                          f"n={r['n_days']} {sig}")

        # 衰减曲线
        print(f"\n--- 衰减曲线 ---")
        decay = FactorLab.calc_decay(factor_name, max_lag=5,
                                     review_dir=review_dir, csv_dir=csv_dir)
        for k, v in decay['decay'].items():
            bar = '█' * int(abs(v or 0) * 100) if v else ''
            print(f"  {k}: {v:+.4f} {bar}" if v is not None else f"  {k}: N/A")
        if decay['optimal_lag']:
            print(f"  最优持有天数: D+{decay['optimal_lag']}")

        # 换手率
        print(f"\n--- 换手率 ---")
        to = FactorLab.calc_turnover(factor_name, review_dir=review_dir)
        if 'error' not in to:
            print(f"  平均换手率: {to['avg_turnover']:.1%} (TOP 20)")
        else:
            print(f"  {to['error']}")

        print(f"\n{'='*50}\n")


if __name__ == '__main__':
    import sys
    factor = sys.argv[1] if len(sys.argv) > 1 else 'profit_score'
    FactorLab.report(factor)
