#!/usr/bin/env python3
"""抱团检测 — calc_big_volume_cluster / calc_chain_cluster"""
import json
import os
from datetime import datetime
from utils import sf, get_limit_threshold

# 从 position 导入内部工具
from quant.position import _sorted_by_amt



def calc_big_volume_cluster(rows_today, rows_prev=None, rows_history=None, bv_streak=0, date_str=None):
    """
    检测当日成交额前十个股的平均涨幅，判断是否存在大成交权重抱团行情。
    v2.8.5: 智能推荐逻辑 — 趋势尽头是加速，优选低位大成交跟随股。
    v2.9.1: 趋势尽头判定升级为3因子积分制。
    v3.0.6: 三因子各降20分+新增月K高位因子+10交易日持续黑名单。
    v3.0.9: 大成交权重股专用——月K高位降权(33→17)，新增量价背离因子(16分)，总分阈值50→60。

    趋势尽头判定逻辑（3因子积分制，满分67，总分≥40排除）：
      因子1 量能异常    17分（今日vol/前3日平均vol）
      因子2 3日累计涨幅  33分（今日收盘价 vs 大前天收盘价）
      因子3 连续暴力拉升  17分（昨日涨幅 + 今日涨幅）
      持续机制：首次判定后，10个交易日内直接判定为趋势尽头

    选股规则：
      1. 趋势尽头排除：见上方逻辑
      2. 涨停 → 追高风险大，不推荐
      3. 涨幅为负 → 不买
      4. 量价配合评分：成交额排名(权重40%) + 涨幅适中2-6%(权重30%) + 换手适中(权重15%) + 未涨停(权重15%)
      5. 低位跟随：TOP30成交额中找量价配合分最高的2只
      6. 板块映射加分：与TOP10中涨幅最大股同板块的+10分

    参数：
        rows_today: 今日全量股票数据
        rows_prev: 前1日数据（兼容旧接口）
        rows_history: 前N日数据列表 [前1日, 前2日, 前3日, ...]，越远越靠后

    返回：
        dict: {
            'top10': [(name, code, amt, pct), ...],
            'avg_pct': float,
            'up_count': int,
            'down_count': int,
            'signal': str,
            'recommend': [(name, code, amt, pct, score, reason), ...],
            'exhausted': [(name, code, amt, pct), ...],  # 被排除的加速股
        }
    """
    # 按成交额降序取前10
    sorted_by_amt = _sorted_by_amt(rows_today)[:10]
    top10 = []
    for r in sorted_by_amt:
        name = r.get('股票名称', '').strip()
        code = r['股票代码'].strip()
        amt = sf(r, '成交额')
        pct = sf(r, '涨跌幅')
        top10.append((name, code, amt, pct))

    if not top10:
        return {'top10': [], 'avg_pct': 0, 'up_count': 0, 'down_count': 0,
                'signal': 'neutral', 'recommend': [], 'exhausted': []}

    pcts = [t[3] for t in top10]
    avg_pct = sum(pcts) / len(pcts)
    up_count = sum(1 for p in pcts if p > 0)
    down_count = sum(1 for p in pcts if p < 0)

    # ── 构建多日价格历史（用于趋势尽头判定）──
    # rows_history = [前1日rows, 前2日rows, 前3日rows, ...]
    # 最终 price_history[code] = [前N日价, ..., 前1日价, 今日价]
    today_price_map = {}
    rows_today_map = {}  # code → row dict
    for r in rows_today:
        code = r['股票代码'].strip()
        today_price_map[code] = sf(r, '最新价')
        rows_today_map[code] = r

    hist_price_maps = []  # [前1日价映射, 前2日价映射, ...]
    hist_vol_maps = []    # [前1日成交量映射, 前2日成交量映射, ...]
    if rows_history:
        for day_rows in rows_history:
            pm = {}
            vm = {}
            for r in day_rows:
                code = r['股票代码'].strip()
                pm[code] = sf(r, '最新价')
                vm[code] = sf(r, '成交量手')
            hist_price_maps.append(pm)
            hist_vol_maps.append(vm)
    elif rows_prev:
        # 兼容旧接口：仅有前1日
        pm = {}
        vm = {}
        for r in rows_prev:
            code = r['股票代码'].strip()
            pm[code] = sf(r, '最新价')
            vm[code] = sf(r, '成交量手')
        hist_price_maps.append(pm)
        hist_vol_maps.append(vm)

    # ── 趋势尽头10交易日持续黑名单 ──
    _EXHAUSTION_BLACKLIST_FILE = os.path.join(
        os.environ.get('CSV_DIR', os.path.expanduser('~/.openclaw/workspace/stock_data/csv')),
        '..', 'exhaustion_blacklist.json')
    _EXHAUSTION_PERSIST_DAYS = 10

    def _load_exhaustion_blacklist():
        """加载趋势尽头黑名单 {code: [date_str, ...]}"""
        if not os.path.exists(_EXHAUSTION_BLACKLIST_FILE):
            return {}
        try:
            with open(_EXHAUSTION_BLACKLIST_FILE, 'r') as f:
                data = json.load(f)
            # 清理超过10天的旧记录
            cleaned = {}
            for code, dates in data.items():
                recent = sorted(dates, reverse=True)[:_EXHAUSTION_PERSIST_DAYS]
                if recent:
                    cleaned[code] = recent
            return cleaned
        except (IOError, json.JSONDecodeError):
            return {}

    def _save_exhaustion_blacklist(bl):
        """保存趋势尽头黑名单"""
        os.makedirs(os.path.dirname(_EXHAUSTION_BLACKLIST_FILE), exist_ok=True)
        try:
            with open(_EXHAUSTION_BLACKLIST_FILE, 'w') as f:
                json.dump(bl, f, ensure_ascii=False)
        except IOError:
            pass

    def _check_exhaustion_persistent(code, bl, ref_date):
        """检查该股票是否在持续黑名单中（最近10个交易日内被标记过）"""
        if code not in bl:
            return False
        dates = bl[code]
        if not dates:
            return False
        # 检查最近标记日期是否在10个交易日内
        # 简化：按日期字符串排序，检查列表长度<10（每次调用时会新增当日日期）
        # 用日期差做更精确的判断
        latest_date = max(dates)
        try:
            latest_dt = datetime.strptime(latest_date, '%Y%m%d')
            ref_dt = datetime.strptime(ref_date, '%Y%m%d')
            days_diff = (ref_dt - latest_dt).days
            # 10个交易日内 ≈ 14个自然日内（宽松判断，避免漏判）
            return days_diff >= 0 and days_diff <= 14
        except ValueError:
            return False

    def _is_trend_exhaustion(code, today_pct, today_amt, bl, ref_date):
        """
        趋势尽头3因子积分制（v3.0.9，大成交权重股专用）。

        针对大盘权重股低波动特性重新校准阈值。

        因子              满分    说明
        ─────────────────────────────────────────────
        量能异常          17分   今日vol / 前3日平均vol
        3日累计涨幅        33分   今日收盘价 vs 大前天收盘价
        2日连续暴力拉升     17分   昨日涨幅 + 今日涨幅

        持续机制：首次判定后，10个交易日内直接判定为趋势尽头。
        总分≥40 → 趋势尽头，排除。
        """
        # ── 持续机制：先查黑名单 ──
        if _check_exhaustion_persistent(code, bl, ref_date):
            return True

        if not hist_price_maps or len(hist_price_maps) < 1:
            return False

        score = 0
        today_row = rows_today_map.get(code)
        if not today_row:
            return False

        today_vol = sf(today_row, '成交量手')
        today_price = today_price_map.get(code, 0)

        # ── 因子1：量能异常（17分）──
        prev_vols = []
        for vm in hist_vol_maps:
            if code in vm and vm[code] > 0:
                prev_vols.append(vm[code])
        if prev_vols and today_vol > 0:
            avg_vol = sum(prev_vols) / len(prev_vols)
            vol_ratio = today_vol / avg_vol
            if vol_ratio >= 2.5:
                score += 17
            elif vol_ratio >= 2.0:
                score += 14
            elif vol_ratio >= 1.5:
                score += 10
            elif vol_ratio >= 1.2:
                score += 5

        # ── 因子2：3日累计涨幅（33分）──
        if len(hist_price_maps) >= 3:
            base_price = hist_price_maps[2].get(code, 0)  # 大前天
            if base_price > 0 and today_price > 0:
                cum3d = (today_price - base_price) / base_price * 100
                if cum3d > 30:
                    score += 33
                elif cum3d > 25:
                    score += 26
                elif cum3d > 20:
                    score += 20
                elif cum3d > 15:
                    score += 13
                elif cum3d > 10:
                    score += 7
        # 降级：仅有2日历史
        elif len(hist_price_maps) >= 1:
            yest_price = hist_price_maps[0].get(code, 0)
            if yest_price > 0 and today_price > 0:
                cum2d = (today_price - yest_price) / yest_price * 100
                if cum2d > 25:
                    score += 30
                elif cum2d > 20:
                    score += 20
                elif cum2d > 15:
                    score += 13

        # ── 因子3：2日连续暴力拉升（17分）──
        yest_pct = 0
        if hist_price_maps and code in hist_price_maps[0]:
            yest_price = hist_price_maps[0].get(code, 0)
            if len(hist_price_maps) >= 2:
                day_before_price = hist_price_maps[1].get(code, 0)
            else:
                day_before_price = 0
            if yest_price > 0 and day_before_price > 0:
                yest_pct = (yest_price - day_before_price) / day_before_price * 100
        two_day_pct = yest_pct + today_pct
        if two_day_pct > 12:
            score += 17
        elif two_day_pct > 9:
            score += 12
        elif two_day_pct > 6:
            score += 9
        elif two_day_pct > 4:
            score += 5


        # ── 判定 ──
        is_exhausted = score >= 40
        if is_exhausted and ref_date:
            # 写入持续黑名单
            if code not in bl:
                bl[code] = []
            if ref_date not in bl[code]:
                bl[code].append(ref_date)
        return is_exhausted

    # 加载趋势尽头持续黑名单
    _exhaustion_bl = _load_exhaustion_blacklist()

    # 判断信号
    if up_count > down_count:
        signal = 'bull'
    elif down_count > up_count:
        signal = 'bear'
    else:
        signal = 'neutral'

    # ── 智能推荐逻辑 ──
    recommend = []
    exhausted = []
    
    # ── 取TOP30作为选股池（所有信号都跑，供趋势尽头检测）──
    sorted_top30 = _sorted_by_amt(rows_today)[:30]
    
    # ── 趋势尽头排除（3因子+10日持续黑名单，所有信号都检测）──
    for r in sorted_top30:
        name = r.get('股票名称', '').strip()
        code = r['股票代码'].strip()
        amt = sf(r, '成交额')
        pct = sf(r, '涨跌幅')
        if _is_trend_exhaustion(code, pct, amt, _exhaustion_bl, date_str or ''):
            exhausted.append((name, code, amt, pct))
    
    if signal == 'bull':
        # TOP10涨幅最大股的板块（用于板块映射）
        leader_sector = ''
        leader_code = ''
        if top10:
            leader = max(top10, key=lambda x: x[3])
            leader_code = leader[1]
            for r in rows_today:
                if r['股票代码'].strip() == leader_code:
                    leader_sector = r.get('所属板块', '').strip()
                    break
        
        scored_pool = []
        for r in sorted_top30:
            name = r.get('股票名称', '').strip()
            code = r['股票代码'].strip()
            amt = sf(r, '成交额')
            pct = sf(r, '涨跌幅')
            turnover = sf(r, '换手率')
            sector = r.get('所属板块', '').strip()
            limit = get_limit_threshold(code)
            
            # 跳过趋势尽头股
            if any(e[1] == code for e in exhausted):
                continue
            # 规则2: 涨停 → 追高风险大
            if pct >= limit - 1:
                continue
            # 规则3: 涨幅为负 → 不买
            if pct <= 0:
                continue
            
            # ── 量价配合评分 (0-100) ──
            score = 0
            
            # 维度1: 成交额排名分 (40分) — 成交额越大越好
            amt_rank = sorted_top30.index(r) + 1
            score += max(0, 40 - (amt_rank - 1) * 1.3)
            
            # 维度2: 涨幅适中分 (30分) — 最优区间 2%-6%
            if 2 <= pct <= 6:
                score += 30  # 完美区间
            elif 1 <= pct < 2:
                score += 20  # 偏弱但可接受
            elif 6 < pct <= 7:
                score += 15  # 偏高，加速前兆
            elif 0 < pct < 1:
                score += 10  # 太弱
            else:
                score += 5
            
            # 维度3: 换手率适中分 (15分) — 3%-15%最佳
            if 3 <= turnover <= 15:
                score += 15
            elif 1 <= turnover < 3:
                score += 8
            elif turnover > 15:
                score += 5  # 换手过高=投机
            else:
                score += 3
            
            # 维度4: 未涨停分 (15分) — 非涨停=还有空间
            pct_to_limit = limit - pct
            if pct_to_limit > 5:
                score += 15  # 距涨停远，空间大
            elif pct_to_limit > 3:
                score += 10
            else:
                score += 5  # 接近涨停
            
            # 维度5: 板块映射加分 (10分)
            if leader_sector and leader_sector in sector:
                score += 10
            
            scored_pool.append((name, code, amt, pct, round(score, 1)))
        
        # 按评分排序，取前2
        scored_pool.sort(key=lambda x: x[4], reverse=True)
        
        if len(scored_pool) >= 2:
            recommend = scored_pool[:2]
        elif scored_pool:
            recommend = scored_pool[:1]
        else:
            # 全被排除了，回退到原逻辑
            non_zt = [(n, c, a, p) for n, c, a, p in top10
                       if p > 0 and p < get_limit_threshold(c) - 1]
            if non_zt:
                recommend = [(n, c, a, p, 0) for n, c, a, p in 
                             sorted(non_zt, key=lambda x: x[3], reverse=True)[:2]]
    

    # ── 低位大成交爆量推荐（月线判定低位，所有信号都检测）──
    # 条件：从成交额TOP15中筛选
    #   1. 低位：用baostock月线判定，近12月区间下30%或近3月区间下25%
    #   2. 爆量：今日成交量/前5日均量≥2.0倍
    #   3. 今日涨幅为正且未涨停
    # 评分：放量倍数(40) + 月线低位度(30) + 涨幅适中(20) + 成交额排名(10)
    low_pos_surge = []
    if hist_vol_maps:
        sorted_top15 = _sorted_by_amt(rows_today)[:15]

        # 获取今日日期（用于月线查询）
        surge_date = ''
        try:
            _keys = list(rows_today[0].keys())
            surge_date = rows_today[0].get(_keys[0], '').strip()
            if not surge_date.isdigit():
                surge_date = date_str
        except (IndexError, KeyError):
            surge_date = date_str

        for r in sorted_top15:
            name = r.get('股票名称', '').strip()
            code = r['股票代码'].strip()
            amt = sf(r, '成交额')
            pct = sf(r, '涨跌幅')
            limit = get_limit_threshold(code)

            # 跳过涨停和下跌的
            if pct >= limit - 1 or pct <= 0:
                continue

            # 跳过小票（流通市值<100亿不算权重股）
            _mcap = sf(r, '流动市值')
            if _mcap and _mcap < 100e8:
                continue

            # ── 日线低位判定（用已有hist_price_maps，零额外I/O）──
            today_price = today_price_map.get(code, 0)
            if today_price <= 0:
                continue

            # 用20日价格区间判定低位
            prices_20d = [pm.get(code, 0) for pm in hist_price_maps[:20] if pm.get(code, 0) > 0]
            if today_price > 0 and prices_20d:
                p_high = max(prices_20d + [today_price])
                p_low = min(prices_20d + [today_price])
                if p_high > p_low:
                    drawdown = (p_high - today_price) / (p_high - p_low) * 100
                    is_low = drawdown >= 60  # 近20日区间下40%
                else:
                    is_low = False
                    drawdown = 0
            else:
                is_low = False
                drawdown = 0

            if not is_low:
                continue
            # ── 爆量判定（日线成交量对比）──
            today_vol = sf(r, '成交量手')
            prev_vols = []
            for vm in hist_vol_maps[:5]:  # 前5日
                if code in vm and vm[code] > 0:
                    prev_vols.append(vm[code])

            if not prev_vols or today_vol <= 0:
                continue

            avg_vol = sum(prev_vols) / len(prev_vols)
            vol_ratio = today_vol / avg_vol

            # 爆量条件：≥1.5倍（放宽以增加选股覆盖面）
            if vol_ratio < 1.5:
                continue

            # ── 评分 ──
            score = 0

            # 放量倍数 (40分)
            if vol_ratio >= 5.0:
                score += 40
            elif vol_ratio >= 4.0:
                score += 35
            elif vol_ratio >= 3.0:
                score += 30
            elif vol_ratio >= 2.5:
                score += 25
            elif vol_ratio >= 2.0:
                score += 20
            elif vol_ratio >= 1.5:
                score += 12

            # 月线低位程度 (30分) - drawdown来自月线区间
            if drawdown >= 90:
                score += 30  # 12月最底部
            elif drawdown >= 80:
                score += 25
            elif drawdown >= 70:
                score += 18
            elif drawdown >= 60:
                score += 12
            else:
                score += 5

            # 涨幅适中 (20分) 3-7%最佳
            if 3 <= pct <= 7:
                score += 20
            elif 2 <= pct < 3:
                score += 15
            elif 7 < pct <= 10:
                score += 10
            elif 1 <= pct < 2:
                score += 8
            else:
                score += 3

            # 成交额排名 (10分)
            amt_rank = sorted_top15.index(r) + 1
            score += max(0, 10 - (amt_rank - 1) * 0.7)

            low_pos_surge.append((name, code, amt, pct, round(score, 1),
                                  round(vol_ratio, 1), round(drawdown, 1)))

        # 按评分排序
        low_pos_surge.sort(key=lambda x: x[4], reverse=True)
        low_pos_surge = low_pos_surge[:3]  # 最多推荐3只

    # 保存趋势尽头持续黑名单
    if _exhaustion_bl:
        _save_exhaustion_blacklist(_exhaustion_bl)

    return {
        'top10': top10,
        'avg_pct': round(avg_pct, 2),
        'up_count': up_count,
        'down_count': down_count,
        'signal': signal,
        'recommend': recommend,
        'exhausted': exhausted,
        'low_pos_surge': low_pos_surge,
    }


def calc_chain_cluster(pp, pp_list, rows_today):
    """
    连板抱团行情检测。

    检测连板股的梯队结构和晋级率，判断是否存在连板抱团行情。
    参照大成交权重抱团模块的结构。

    返回：
        dict: {
            'signal': str,          # 'strong' 强连板抱团 / 'weak' 弱连板 / 'none' 无
            'total_chain': int,     # 昨日连板总数（2板+）
            'promoted': int,        # 晋级数
            'promo_rate': float,    # 晋级率%
            'ladder': dict,         # 各层级 {板数: {'count': N, 'codes': [...], 'names': [...]}}
            'max_board': int,       # 最高板
            'max_board_stock': str, # 最高板个股名
            'recommend': list,      # 推荐龙头 [(name, code, boards, pct, sector), ...]
            'detail': str,          # 描述文字
        }
    """
    if not pp_list or len(pp_list) < 1:
        return {'signal': 'none', 'total_chain': 0, 'promoted': 0, 'promo_rate': 0,
                'ladder': {}, 'max_board': 0, 'max_board_stock': '', 'recommend': [], 'detail': ''}

    today_zt = pp['zt_set']  # 今日涨停codes
    prev1_zt = pp_list[0]['zt_set']  # 昨日涨停codes
    code_map = pp.get('code_map', {})

    # 构建多日涨停集合（从近到远）
    all_zt_sets = [today_zt, prev1_zt]
    for i in range(1, min(len(pp_list), 10)):
        all_zt_sets.append(pp_list[i]['zt_set'])

    # ── 计算各层级连板 ──
    # 昨日连板（2板+）= 昨日涨停 ∩ 前前日涨停
    ladder = {}  # {board_count: {'codes': set, 'names': dict}}
    today_ladder = {}  # {board_count: {'codes': set, 'names': dict}} 今日各层级

    # 昨日的连板梯队（用于计算晋级率）
    # 从2板开始往上数
    yesterday_chain_all = set()  # 昨日所有连板股(2板+)
    for board_n in range(2, 15):
        # N板 = 连续N天涨停
        chain_set = all_zt_sets[1]  # 昨日涨停
        for k in range(2, board_n + 1):
            if k < len(all_zt_sets):
                chain_set = chain_set & all_zt_sets[k]
            else:
                chain_set = set()
                break
        if not chain_set:
            break
        names = {}
        for code in chain_set:
            row = code_map.get(code)
            names[code] = row.get('股票名称', code) if row else code
        ladder[board_n] = {'codes': chain_set, 'names': names}
        yesterday_chain_all |= chain_set

    # 今日的连板梯队（用于展示）
    today_chain_all = set()
    for board_n in range(2, 15):
        chain_set = today_zt
        for k in range(1, board_n):
            if k < len(all_zt_sets):
                chain_set = chain_set & all_zt_sets[k]
            else:
                chain_set = set()
                break
        if not chain_set:
            break
        names = {}
        for code in chain_set:
            row = code_map.get(code)
            names[code] = row.get('股票名称', code) if row else code
        today_ladder[board_n] = {'codes': chain_set, 'names': names}
        today_chain_all |= chain_set

    # ── 晋级率计算 ──
    total_chain = len(yesterday_chain_all)  # 昨日连板总数(2板+)
    if total_chain > 0:
        promoted_codes = yesterday_chain_all & today_zt
        promoted = len(promoted_codes)
        promo_rate = promoted / total_chain * 100
    else:
        promoted = 0
        promo_rate = 0
        promoted_codes = set()

    # ── 连板梯队完整度 ──
    max_board = max(today_ladder.keys()) if today_ladder else 0
    max_board_stock = ''
    if max_board >= 2 and max_board in today_ladder:
        best = max(today_ladder[max_board]['codes'])
        row = code_map.get(best)
        max_board_stock = row.get('股票名称', best) if row else best

    # ── 信号判定 ──
    # 强连板抱团：晋级率≥40% 且 连板总数≥8家
    # 弱连板抱团：晋级率≥30% 且 连板总数≥5家，或最高板≥5
    # 其他：无连板抱团
    if promo_rate >= 40 and total_chain >= 8:
        signal = 'strong'
    elif (promo_rate >= 30 and total_chain >= 5) or max_board >= 5:
        signal = 'weak'
    elif total_chain >= 3 and promo_rate >= 50:
        signal = 'weak'  # 连板少但晋级率高
    else:
        signal = 'none'

    # ── 推荐龙头 ──
    # 从今日连板梯队中，选各层级最高板+涨幅最大的
    recommend = []
    seen = set()

    # 优先推最高板
    for bn in sorted(today_ladder.keys(), reverse=True):
        for code in today_ladder[bn]['codes']:
            if code in seen:
                continue
            seen.add(code)
            row = code_map.get(code, {})
            name = row.get('股票名称', code)
            pct = float(row.get('涨跌幅', 0) or 0)
            sector = row.get('所属板块', '').split('/')[0].strip() if row.get('所属板块') else ''
            recommend.append((name, code, bn, pct, sector))
            if len(recommend) >= 3:
                break
        if len(recommend) >= 3:
            break

    # ── 描述文字 ──
    ladder_str = ' → '.join(f"{bn}板{len(info['codes'])}家"
                            for bn, info in sorted(today_ladder.items()))

    if signal == 'strong':
        detail = f"🔥 连板抱团确认：梯队[{ladder_str}]，晋级率{promo_rate:.0f}%，最高{max_board}板({max_board_stock})"
    elif signal == 'weak':
        detail = f"⚠️ 连板抱团候选：梯队[{ladder_str}]，晋级率{promo_rate:.0f}%，最高{max_board}板({max_board_stock})"
    else:
        detail = f"无连板抱团：梯队[{ladder_str}]，晋级率{promo_rate:.0f}%（{promoted}/{total_chain}）"

    return {
        'signal': signal,
        'total_chain': total_chain,
        'promoted': promoted,
        'promo_rate': round(promo_rate, 1),
        'ladder': {bn: {'count': len(info['codes']), 'names': list(info['names'].values())}
                   for bn, info in today_ladder.items()},
        'max_board': max_board,
        'max_board_stock': max_board_stock,
        'recommend': recommend,
        'detail': detail,
    }


# ════════════════════════════════════════════════════════
# 报告生成（模块化子函数）
# ════════════════════════════════════════════════════════



