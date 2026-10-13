#!/usr/bin/env python3
"""龙头/领导力分析 — calc_leaders / find_sector_leaders / calc_subsector_breakdown"""
import os
import csv
from collections import defaultdict
from utils import sf, is_zt, get_limit_threshold
from data_loader import _load_sector_hierarchy, _load_concept_map
from sector import calc_sector_enhanced

_HISTORY_DATA_CACHE = {}  # {(tuple of pp_list ids): (earliest_prev, zt_counts)}

def _build_history_data(rows_today, pp_list):
    """构建历史数据：最早前日价格映射 + 各日涨停次数统计（供板块龙头和龙头分析共用）。带缓存。"""
    # 用 pp_list 长度+今日行数作为粗略缓存键（同一次 run_single 内复用）
    cache_key = (len(rows_today), len(pp_list))
    if cache_key in _HISTORY_DATA_CACHE:
        return _HISTORY_DATA_CACHE[cache_key]

    earliest_prev = {}
    zt_counts = defaultdict(int)
    if pp_list:
        for code, r in pp_list[-1]['code_map'].items():
            p = sf(r, '最新价')
            if p > 0:
                earliest_prev[code] = p
        for pp_prev in pp_list:
            for code in pp_prev['zt_set']:
                zt_counts[code] += 1
    today_zt_codes = set(r['股票代码'].strip() for r in rows_today if is_zt(r))
    for code in today_zt_codes:
        zt_counts[code] += 1

    result = (earliest_prev, zt_counts)
    _HISTORY_DATA_CACHE[cache_key] = result
    return result

def find_sector_leaders(sector_name: str, rows_today: list[dict], pp_list: list[dict], top_n: int = 3, sector_codes: set | None = None) -> list[dict]:
    """
    查找板块龙头：近5日涨幅 + 涨停次数综合评分。
    sector_codes: 概念板块的成分股代码集合（传入时按代码过滤，不按所属板块）。
    """
    if sector_codes:
        code_set = set(sector_codes) if not isinstance(sector_codes, set) else sector_codes
        sector_rows = [r for r in rows_today if r['股票代码'].strip() in code_set]
    else:
        sector_rows = [r for r in rows_today
                       if r.get('所属板块', '').split('/')[0].strip() == sector_name]
    if not sector_rows:
        return []

    earliest_prev, zt_counts = _build_history_data(rows_today, pp_list)

    scored = []
    for r in sector_rows:
        code = r['股票代码'].strip()
        today_price = sf(r, '最新价')

        if code in earliest_prev and earliest_prev[code] > 0:
            multi_pct = (today_price - earliest_prev[code]) / earliest_prev[code] * 100
        else:
            multi_pct = sf(r, '涨跌幅')

        zt_n = zt_counts.get(code, 0)
        score = multi_pct * 0.5 + zt_n * 15

        scored.append({
            'name': r['股票名称'], 'code': code,
            'pct_today': sf(r, '涨跌幅'),
            'pct_multi': multi_pct,
            'zt_count': zt_n,
            'score': score,
            'amount': sf(r, '成交额'),
            'hs': sf(r, '换手率'),
        })

    scored.sort(key=lambda x: x['score'], reverse=True)
    return scored[:top_n]

def calc_sector(rows_today, pp, pp_list, csv_dir=None, prev_sec_top5=None):
    """
    全板块强度分析（v2.9 行业+概念板块，四维评分，相似性去重）。
    csv_dir 用于新股过滤（加载历史已知代码）。
    """
    return calc_sector_enhanced(rows_today, pp, pp_list, csv_dir=csv_dir, prev_sec_top5=prev_sec_top5)


def calc_subsector_breakdown(rows_today, sector_name):
    """
    细分板块分析：将一个行业板块下的个股按同花顺概念归属拆分，
    计算各概念子板块的平均涨幅，找出最强细分方向。

    返回：[(concept_name, avg_pct, stock_count, zt_count), ...] 按均涨幅降序
    """
    concept_map = _load_concept_map()
    if not concept_map:
        return []

    # 找出属于该行业板块的个股
    sector_rows = [r for r in rows_today
                   if r.get('所属板块', '').split('/')[0].strip() == sector_name]
    if not sector_rows:
        return []

    # 概念 → 个股涨幅列表
    concept_stocks = defaultdict(list)
    concept_zt = defaultdict(int)

    for r in sector_rows:
        code = r['股票代码'].strip()
        pct = sf(r, '涨跌幅')
        if code in concept_map:
            for concept in concept_map[code]['concepts']:
                concept_stocks[concept].append(pct)
                if is_zt(r):
                    concept_zt[concept] += 1

    if not concept_stocks:
        return []

    # 计算每个概念的均涨幅，至少3只股才有统计意义
    result = []
    for concept, pcts in concept_stocks.items():
        if len(pcts) >= 3:
            avg = sum(pcts) / len(pcts)
            result.append((concept, round(avg, 2), len(pcts), concept_zt.get(concept, 0)))

    result.sort(key=lambda x: x[1], reverse=True)
    return result[:8]  # 最多展示8个细分概念


# ════════════════════════════════════════════════════════
# 维度四：龙头分析
# ════════════════════════════════════════════════════════

def calc_leaders(rows_today, pp, sec, pp_list=None, rows_prev_list=None):
    """跨板块龙头分析：从 TOP3 板块各选最强龙头，按评分统一排序"""
    if not sec['top5']:
        return {'candidates': [], 'count': 0, 'sector': '', 'sector_candidates': {}}

    # 近5日数据：涨幅 + 涨停次数（全局一次）
    earliest_prev, zt_counts = _build_history_data(rows_today, pp_list)

    def rating(sc):
        return '⭐ 绝对龙头' if sc >= 80 else ('🥈 强势龙头' if sc >= 60 else ('🥉 潜在龙头' if sc >= 40 else '❌ 无明确龙头'))

    def _build_result(r, sc, multi_pct_map, sp_pct, sp_multi_pct, sp_zt_count, sector_name, sector_score):
        hp = sf(r, '最高价')
        cp = sf(r, '最新价')
        pct = sf(r, '涨跌幅')
        threshold = get_limit_threshold(r['股票代码'])
        prev_close = sf(r, '昨收价')
        limit_price = round(prev_close * (1 + threshold / 100), 2)

        if pct >= threshold - 0.5:
            if limit_price > 0:
                gap_pct = (limit_price - cp) / limit_price * 100
            else:
                gap_pct = 0
            fb_desc = '完美' if gap_pct < 0.01 else ('优秀' if gap_pct < 0.3 else ('良好' if gap_pct < 1 else '差'))
        elif hp > 0:
            gap_pct = (hp - cp) / hp * 100
            fb_desc = '完美' if gap_pct < 0.1 else ('优秀' if gap_pct < 0.5 else ('良好' if gap_pct < 1 else '差'))
        else:
            fb_desc, gap_pct = '差', 0

        code = r['股票代码'].strip()
        return {
            'name': r['股票名称'], 'code': code,
            'score': sc['total'], 'rating': rating(sc['total']),
            'pct': pct, 'hs': sf(r, '换手率'),
            'lb': sf(r, '量比'), 'amount': sf(r, '成交额'),
            'fb_diff': gap_pct, 'fb_desc': fb_desc, 'is_zt': pct >= threshold - 0.5,
            'pct5': multi_pct_map.get(code, pct), 'zt5_count': zt_counts.get(code, 0),
            'sector': sector_name, 'sector_score': sector_score,
        }

    # 预建排名索引：code → rank（避免 O(n) next() 查找）
    def _build_rank_index(sorted_list):
        """从排序列表构建 {code: rank} 索引"""
        return {r['股票代码']: i for i, r in enumerate(sorted_list)}

    def _rank_score(rk, thresholds):
        """通用排名评分：thresholds = [(max_rank, score), ...], 最后一个为默认"""
        for max_rk, sc in thresholds:
            if rk <= max_rk:
                return sc
        return thresholds[-1][1]

    def _score_leader_common(r, pct_rank, pct5_rank, zt_rank, multi_pct_map, is_20cm):
        """10cm/20cm 通用评分（仅阈值不同）"""
        s = {}
        code = r['股票代码']

        # 涨幅排名 10分（通用）
        s['pct'] = _rank_score(pct_rank, [(0, 10), (2, 8), (4, 5), (999, 3)])

        # 换手率 10分
        hs = sf(r, '换手率')
        if is_20cm:
            s['hs'] = 10 if 8 <= hs <= 25 else (7 if 25 < hs <= 35 else (5 if 3 <= hs < 8 else 3))
        else:
            s['hs'] = 10 if 5 <= hs <= 15 else (7 if 15 < hs <= 25 else 3)

        # 量比 10分
        lb = sf(r, '量比')
        if is_20cm:
            s['lb'] = 10 if 1.5 <= lb <= 4 else (7 if 4 < lb <= 8 else (5 if 1.0 <= lb < 1.5 else 3))
        else:
            s['lb'] = 10 if 2 <= lb <= 5 else (7 if 5 < lb <= 10 else 3)

        # 流通市值 10分
        mv = sf(r, '流动市值')
        if is_20cm:
            s['mv'] = 10 if mv >= 1.5e9 else (5 if mv >= 5e8 else 0)
        else:
            s['mv'] = 10 if mv >= 3e9 else 0

        # 市盈率 5分
        pe = sf(r, '市盈率动态')
        if is_20cm:
            s['pe'] = 5 if 0 < pe <= 80 else (3 if pe <= 150 else 1)
        else:
            s['pe'] = 5 if 0 < pe <= 50 else 2

        # 封板质量 15分
        cp, hp = sf(r, '最新价'), sf(r, '最高价')
        if hp > 0:
            d = (hp - cp) / hp * 100
            if is_20cm:
                s['fb'] = 15 if d < 0.3 else (12 if d < 1.0 else (8 if d < 2.0 else 3))
            else:
                s['fb'] = 15 if d < 0.1 else (12 if d < 0.5 else (8 if d < 1 else 3))
        else:
            s['fb'] = 3

        # 近5日涨幅排名 20分（通用）
        s['pct5'] = _rank_score(pct5_rank, [(0, 20), (2, 15), (4, 10), (999, 5)])

        # 近5日涨停次数 20分（趋势修正阈值不同）
        p5g = multi_pct_map.get(code, 0)
        trend_threshold = 35 if is_20cm else 20
        trend_mid = 25 if is_20cm else 15
        if p5g > trend_threshold:
            s['zt5'] = 20
        elif p5g > trend_mid:
            s['zt5'] = 10
        else:
            zt_n = zt_counts.get(code, 0)
            s['zt5'] = _rank_score(zt_rank, [(0, 20 if zt_n > 0 else 0)]) if zt_rank == 0 else (
                15 if zt_n >= 3 else (10 if zt_n >= 2 else (5 if zt_n >= 1 else 0)))

        s['total'] = sum(s.values())
        return s

    def _score_leader_in_sector(r, pct_rk_idx, pct5_rk_idx, zt_rk_idx, multi_pct_map):
        """自动按涨跌停幅度选择评分标准"""
        code = r['股票代码']
        is_20cm = get_limit_threshold(code) >= 20
        pct_rk = pct_rk_idx.get(code, 99)
        pct5_rk = pct5_rk_idx.get(code, 99)
        zt_rk = zt_rk_idx.get(code, 99)
        return _score_leader_common(r, pct_rk, pct5_rk, zt_rk, multi_pct_map, is_20cm)

    # ── 从 TOP3 板块各选最强龙头 ──
    sector_candidates = {}  # {sector_name: [result_dict, ...]}
    all_results = []
    seen_codes = set()

    for sec_idx in range(min(3, len(sec['top5']))):
        sn = sec['top5'][sec_idx][0]
        sd = sec['top5'][sec_idx][1]
        scodes = sd.get('codes', set())
        sec_score = sd.get('score', 0)

        # 支持概念板块：用 codes 集合过滤涨停股
        if scodes:
            sec_zt = [r for r in pp['zt'] if r['股票代码'].strip() in scodes]
        else:
            sec_zt = [r for r in pp['zt'] if r.get('所属板块', '').split('/')[0].strip() == sn]

        if not sec_zt:
            continue

        strict = [r for r in sec_zt
                  if sf(r, '换手率') >= 5 and sf(r, '量比') >= 1.0
                  and sf(r, '成交额') >= 2e8
                  and 5e9 <= sf(r, '流动市值') <= 2e11]
        cands = strict if strict else [r for r in sec_zt if sf(r, '成交额') >= 3e8]

        sp_pct = sorted(sec_zt, key=lambda x: sf(x, '涨跌幅'), reverse=True)
        multi_pct_map = {}
        for r in sec_zt:
            code = r['股票代码'].strip()
            today_price = sf(r, '最新价')
            if code in earliest_prev and earliest_prev[code] > 0:
                multi_pct_map[code] = (today_price - earliest_prev[code]) / earliest_prev[code] * 100
            else:
                multi_pct_map[code] = sf(r, '涨跌幅')
        sp_multi_pct = sorted(sec_zt, key=lambda x: multi_pct_map.get(x['股票代码'].strip(), 0), reverse=True)
        sp_zt_count = sorted(sec_zt, key=lambda x: zt_counts.get(x['股票代码'].strip(), 0), reverse=True)

        # 预建排名索引（O(n) 一次构建，替代每个候选 O(n) next() 查找）
        pct_rk_idx = _build_rank_index(sp_pct)
        pct5_rk_idx = _build_rank_index(sp_multi_pct)
        zt_rk_idx = _build_rank_index(sp_zt_count)

        scored = sorted([(r, _score_leader_in_sector(r, pct_rk_idx, pct5_rk_idx, zt_rk_idx, multi_pct_map))
                         for r in cands], key=lambda x: x[1]['total'], reverse=True)

        sec_results = []
        for r, sc in scored[:2]:  # 每板块取 TOP2
            code = r['股票代码'].strip()
            if code in seen_codes:
                continue
            seen_codes.add(code)
            res = _build_result(r, sc, multi_pct_map, sp_pct, sp_multi_pct, sp_zt_count, sn, sec_score)
            sec_results.append(res)
            all_results.append(res)

        sector_candidates[sn] = sec_results

    # 全局按评分排序
    all_results.sort(key=lambda x: x['score'], reverse=True)

    # 优化2：主线梯队加分——同一父级板块的龙头形成梯队，优先推荐
    from sector import _get_parent_of_concept
    hierarchy_data = _load_sector_hierarchy()
    concept_to_cat = hierarchy_data.get('concept_to_category', {})
    if concept_to_cat and all_results:
        # 统计各父级板块的候选数
        parent_leader_count = defaultdict(list)
        for r in all_results:
            sec_name = r.get('sector', '')
            cat = _get_parent_of_concept(sec_name, concept_to_cat)
            if cat:
                parent_leader_count[cat[0]].append(r)
        
        # 找到候选最多的父级（主线父级）
        if parent_leader_count:
            main_parent = max(parent_leader_count.items(), key=lambda x: len(x[1]))[0]
            main_parent_leaders = parent_leader_count[main_parent]
            
            # 如果主线父级有2+个候选，给这些候选加分（梯队效应）
            if len(main_parent_leaders) >= 2:
                for r in main_parent_leaders:
                    r['score'] = r.get('score', 0) + 5
                    r['mainline_parent'] = main_parent
                    r['mainline_tag'] = f'{main_parent}梯队'
                # 重新排序
                all_results.sort(key=lambda x: x['score'], reverse=True)

    # 主板块（评分最高者所属）
    ts = all_results[0]['sector'] if all_results else (sec['top5'][0][0] if sec['top5'] else '')

    return {
        'candidates': all_results[:6],  # 最多展示6个
        'count': len(all_results),
        'sector': ts,
        'sector_candidates': sector_candidates,
    }


# ════════════════════════════════════════════════════════
# 维度五：操作建议
# ════════════════════════════════════════════════════════
# 龙头带动性分析（tpdog 5分钟K对比）
# ════════════════════════════════════════════════════════





# ════════════════════════════════════════════════════════
# 从 review.py 迁移的辅助函数（cycle.py 内部使用）
# ════════════════════════════════════════════════════════
_NEW_STOCK_CACHE = {}


def _load_known_codes(csv_dir, lookback=60):
    """加载过去 N 个交易日的已知股票代码集合。不在其中的视为新股。"""
    target_key = csv_dir
    if target_key in _NEW_STOCK_CACHE:
        return _NEW_STOCK_CACHE[target_key]
    known = set()
    if not os.path.isdir(csv_dir):
        return known
    files = sorted([
        f for f in os.listdir(csv_dir)
        if f.startswith('stock_daily_') and f.endswith('.csv')
    ])
    for f in files[-lookback:]:
        try:
            with open(os.path.join(csv_dir, f), encoding='utf-8') as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    known.add(row['股票代码'].strip())
        except (IOError, csv.Error, KeyError):
            continue
    _NEW_STOCK_CACHE[target_key] = known
    return known


def _is_quality_first_board(code, code_map):
    """判断首板是否有效（过滤量化平铺假首板）"""
    if code not in code_map:
        return False
    r = code_map[code]
    amp = abs(sf(r, '振幅'))
    mkt_cap = sf(r, '流动市值')
    turn = sf(r, '换手率')
    amt = sf(r, '成交额')
    return (amp > 3 and mkt_cap > 2e9 and turn > 2 and amt > 1e8)


def _is_flat_spread(code, code_map):
    """判断是否量化平铺式首板特征：振幅<2%的一字板式封板"""
    if code not in code_map:
        return False
    r = code_map[code]
    amp = abs(sf(r, '振幅'))
    return amp < 2


def _get_parents_of_names(names, concept_to_cat):
    """批量获取一组概念名的父级(lv1)集合。"""
    from sector import _get_parent_of_concept
    parents = set()
    for n in names:
        cat = _get_parent_of_concept(n, concept_to_cat)
        if cat:
            parents.add(cat[0])
    return parents
