from utils import open_json_auto
#!/usr/bin/env python3
"""
v3.0 统一主题评分系统
替代原双轨（行业+概念+共振）评分，以主题为唯一评分单元。

双通道归类：
  ① 三级行业 → LV3_TO_THEME → 主题
  ② 同花顺概念 → CONCEPT_TO_THEME → 主题

4维度评分（满分100）：
  头部暴利强度(40) + 涨停力度(30) + 上涨宽度(20) + 资金强度(20) [v3.1: intensity上限40]
"""

import json
import os
import sys
from collections import defaultdict

from utils import sf, get_limit_threshold

# ──────────────────────────────────────────────────────────────
# 过滤集合
# ──────────────────────────────────────────────────────────────

_GENERIC_CONCEPTS = frozenset([
    '融资融券', '沪股通', '深股通', '国企改革', '证金持股', '央企改革',
    'MSCI概念', '标普道琼斯概念', '富时罗素概念', '转融券',
    '深股通专用', '沪股通专用', '北向资金', '两融标的',
])


def _is_sw_industry(name: str) -> bool:
    return name.endswith('Ⅱ') or name.endswith('Ⅲ')

# 连板加分上限（防止单一主题因超级连板股获得过高加分）
LIANBAN_BONUS_CAP = 15

# ──────────────────────────────────────────────────────────────
# 映射表加载
# ──────────────────────────────────────────────────────────────

_MAPPING_CACHE = None
_PLATE_STOCKS_CACHE = None
_STOCK_THEMES_CACHE = None
_STOCK_PLATES_CACHE = None


def _load_mapping(quant_dir: str = None) -> dict:
    """加载主题映射。优先 v2（plate_to_theme），回退旧版（concept_to_theme）。"""
    global _MAPPING_CACHE
    if _MAPPING_CACHE is not None:
        return _MAPPING_CACHE
    if quant_dir is None:
        quant_dir = os.path.dirname(os.path.abspath(__file__))
    # 优先 v2
    v2_path = os.path.join(quant_dir, '..', 'config', 'theme_mapping_v2.json')
    if os.path.isfile(v2_path):
        with open(v2_path, encoding='utf-8') as f:
            raw = json.load(f)
        _MAPPING_CACHE = {
            'plate_to_theme': raw.get('plate_to_theme', {}),
            'primary_themes': raw.get('primary_themes', []),
            'version': raw.get('version', 'v2'),
        }
        return _MAPPING_CACHE
    # 回退旧版
    path = os.path.join(quant_dir, 'theme_mapping.json')
    with open(path, encoding='utf-8') as f:
        _MAPPING_CACHE = json.load(f)
    return _MAPPING_CACHE



def _load_concept_map(data_dir: str) -> dict:
    path = os.path.join(data_dir, 'stock_concept_map.json')
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return data.get('stock_to_concepts', {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _load_plate_stocks(data_dir: str) -> dict:
    """从 KPH精选50 加载 {plate_name: set(code, ...)}"""
    global _PLATE_STOCKS_CACHE
    if _PLATE_STOCKS_CACHE is not None:
        return _PLATE_STOCKS_CACHE
    import glob
    kph_dir = os.path.join(data_dir, 'kph_sectors')
    if not os.path.isdir(kph_dir):
        _PLATE_STOCKS_CACHE = {}
        return _PLATE_STOCKS_CACHE
    result = {}
    for fp in glob.glob(os.path.join(kph_dir, '*.json')) + glob.glob(os.path.join(kph_dir, '*.json.gz')):
        try:
            with open_json_auto(fp[:-3] if fp.endswith('.gz') else fp, encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            continue
        for sector in data.get('sectors', []):
            pname = sector.get('plate_name', '')
            if not pname:
                continue
            codes = {s['code'] for s in sector.get('stocks', []) if s.get('code')}
            if not codes:
                continue
            if pname in result:
                result[pname] |= codes
            else:
                result[pname] = codes
    _PLATE_STOCKS_CACHE = result
    return result


def _load_stock_plates(data_dir: str) -> dict:
    """从 KPH精选50 构建 {code: set(plate_name)} 反向映射。"""
    global _STOCK_PLATES_CACHE
    if _STOCK_PLATES_CACHE is not None:
        return _STOCK_PLATES_CACHE
    plate_stocks = _load_plate_stocks(data_dir)
    result = defaultdict(set)
    for plate_name, codes in plate_stocks.items():
        for code in codes:
            result[code].add(plate_name)
    _STOCK_PLATES_CACHE = dict(result)
    return _STOCK_PLATES_CACHE


def _load_stock_to_themes(data_dir: str, quant_dir: str = None) -> dict:
    """从 KPH精选50 构建 {code: set(theme_name)} 映射。
    通过 KPH板块名 + stock.tags -> plate_to_theme -> 主题。
    """
    global _STOCK_THEMES_CACHE
    if _STOCK_THEMES_CACHE is not None:
        return _STOCK_THEMES_CACHE
    mapping = _load_mapping(quant_dir)
    plate_to_theme = mapping.get('plate_to_theme', {})
    import glob
    kph_dir = os.path.join(data_dir, 'kph_sectors')
    result = defaultdict(set)
    if os.path.isdir(kph_dir):
        for fp in glob.glob(os.path.join(kph_dir, '*.json')) + glob.glob(os.path.join(kph_dir, '*.json.gz')):
            try:
                with open_json_auto(fp[:-3] if fp.endswith('.gz') else fp, encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                continue
            for sector in data.get('sectors', []):
                plate_name = sector.get('plate_name', '')
                theme = plate_to_theme.get(plate_name, plate_name)
                for stock in sector.get('stocks', []):
                    code = stock.get('code', '')
                    if not code:
                        continue
                    if theme:
                        result[code].add(theme)
                    # 补充: stock.tags 字段映射到主题
                    for tag in stock.get('tags', '').split('、'):
                        tag = tag.strip()
                        if tag:
                            tag_theme = plate_to_theme.get(tag, tag)
                            result[code].add(tag_theme)
    _STOCK_THEMES_CACHE = dict(result)
    return _STOCK_THEMES_CACHE



def _safe_filename(name: str) -> str:
    return name.replace('/', '_').replace('\\', '_')

def _extract_lv3(sector_str: str) -> str:
    """从 'lv2/lv3/lv1' 格式提取三级行业"""
    parts = sector_str.split('/')
    if len(parts) >= 2:
        return parts[1].strip()
    return parts[0].strip() if parts else ''


# ──────────────────────────────────────────────────────────────
# K线排名加载
# ──────────────────────────────────────────────────────────────

def _load_prev_rankings(kline_dir: str, date_str: str) -> dict:
    if not kline_dir or not os.path.isdir(kline_dir):
        return {}
    prev_data = {}
    for fname in os.listdir(kline_dir):
        fpath = os.path.join(kline_dir, fname)
        try:
            with open(fpath, encoding='utf-8') as f:
                lines = f.readlines()
            for i in range(len(lines) - 1, 0, -1):
                parts = lines[i].strip().split(',')
                if len(parts) >= 7 and parts[0] < date_str:
                    name = fname.replace('.csv', '')
                    prev_data[name] = float(parts[5])
                    break
        except (IOError, ValueError, IndexError):
            continue
    sorted_names = sorted(prev_data.items(), key=lambda x: x[1], reverse=True)
    return {name: rank for rank, (name, _) in enumerate(sorted_names, 1)}


def _load_prev_rankings_at(kline_dir: str, target_date: str) -> dict:
    if not kline_dir or not os.path.isdir(kline_dir) or not target_date:
        return {}
    prev_data = {}
    for fname in os.listdir(kline_dir):
        fpath = os.path.join(kline_dir, fname)
        try:
            with open(fpath, encoding='utf-8') as f:
                lines = f.readlines()
            for i in range(len(lines) - 1, 0, -1):
                parts = lines[i].strip().split(',')
                if len(parts) >= 7 and parts[0] == target_date:
                    name = fname.replace('.csv', '')
                    prev_data[name] = float(parts[5])
                    break
        except (IOError, ValueError, IndexError):
            continue
    sorted_names = sorted(prev_data.items(), key=lambda x: x[1], reverse=True)
    return {name: rank for rank, (name, _) in enumerate(sorted_names, 1)}


def _find_prev_date(kline_dir: str, date_str: str) -> str | None:
    if not kline_dir or not os.path.isdir(kline_dir):
        return None
    for fname in os.listdir(kline_dir):
        fpath = os.path.join(kline_dir, fname)
        try:
            with open(fpath, encoding='utf-8') as f:
                lines = f.readlines()
            for i in range(len(lines) - 1, 0, -1):
                parts = lines[i].strip().split(',')
                if len(parts) >= 1 and parts[0] < date_str:
                    return parts[0]
        except (IOError, IndexError):
            continue
    return None


def _load_ranking_history(kline_dir: str, date_str: str, days: int = 3) -> dict:
    if not kline_dir or not os.path.isdir(kline_dir):
        return {}
    raw = {}
    for fname in os.listdir(kline_dir):
        fpath = os.path.join(kline_dir, fname)
        try:
            with open(fpath, encoding='utf-8') as f:
                lines = f.readlines()
            name = fname.replace('.csv', '')
            entries = []
            for i in range(len(lines) - 1, 0, -1):
                parts = lines[i].strip().split(',')
                if len(parts) >= 7 and parts[0] < date_str:
                    entries.append((parts[0], float(parts[5])))
                    if len(entries) >= days:
                        break
            if entries:
                entries.reverse()
                raw[name] = entries
        except (IOError, ValueError, IndexError):
            continue
    all_dates = sorted(set(d for entries in raw.values() for d, _ in entries))
    target_dates = all_dates[-days:] if len(all_dates) >= days else all_dates
    daily_ranks = {}
    for d in target_dates:
        day_scores = []
        for name, entries in raw.items():
            for ed, es in entries:
                if ed == d:
                    day_scores.append((name, es))
                    break
        day_scores.sort(key=lambda x: x[1], reverse=True)
        daily_ranks[d] = {name: rank for rank, (name, _) in enumerate(day_scores, 1)}
    result = {}
    for name in raw:
        ranks = [daily_ranks.get(d, {}).get(name, 999) for d in target_dates]
        result[name] = ranks
    return result


# ──────────────────────────────────────────────────────────────
# 聚合：股票 → 主题
# ──────────────────────────────────────────────────────────────

def aggregate_to_themes(
    rows: list[dict],
    data_dir: str = None,
    quant_dir: str = None,
) -> dict:
    mapping = _load_mapping(quant_dir)
    is_v2 = mapping.get('version') == 'v2'

    # v2: 通过板块映射构建 code->themes
    stock_themes = {}
    plate_to_theme = mapping.get('plate_to_theme', {})
    if is_v2 and data_dir:
        stock_themes = _load_stock_to_themes(data_dir, quant_dir)

    # fallback / sub-sector analysis for old version
    lv3_to_theme = mapping.get('lv3_to_theme', {})
    concept_to_theme = mapping.get('concept_to_theme', {})

    concept_map = {}
    if data_dir:
        concept_map = _load_concept_map(data_dir)

    # v2: load KPH stock->plates mapping for sub-sector ranking
    stock_plates = {}
    if is_v2 and data_dir:
        stock_plates = _load_stock_plates(data_dir)

    theme_config = mapping.get('theme_config', {})

    buckets = defaultdict(lambda: {
        'pcts': [], 'amts': [], 'codes': set(),
        'up': 0, 'zt': 0, 'zb': 0, 'n': 0,
        'leader_pct': -999, 'leader_code': '', '_leader_adjusted': -999,
        'industries': defaultdict(lambda: {'pcts': [], 'amts': [], 'codes': set(), 'up': 0, 'zt': 0, 'n': 0}),
        'concepts': defaultdict(lambda: {'pcts': [], 'amts': [], 'codes': set(), 'up': 0, 'zt': 0, 'n': 0}),
        'industry_vol': 0.0,
        'concept_vol': 0.0,
    })

    def _fill_bucket(b, code, pct, amt, is_zt, is_zb, is_ipo, cname=None, lv3=None):
        """将个股数据填入主题 bucket（不跨板块去重）"""
        if not is_ipo:
            b['pcts'].append(pct)
        b['amts'].append(amt)
        b['n'] += 1
        if pct > 0:
            b['up'] += 1
        if is_zt:
            b['zt'] += 1
        if is_zb:
            b['zb'] += 1
        b['codes'].add(code)
        if not is_ipo:
            is_10cm = not code.startswith(('300', '301', '688'))
            _zt_bonus = 15 if (is_10cm and is_zt) else (20 if is_zt else 0)
            _adj = pct + _zt_bonus
            if _adj > b['_leader_adjusted']:
                b['leader_pct'] = pct
                b['leader_code'] = code
                b['_leader_adjusted'] = _adj
        if lv3:
            ind = b['industries'][lv3]
            if code not in ind['codes']:
                ind['pcts'].append(pct)
                ind['amts'].append(amt)
                ind['n'] += 1
                if pct > 0:
                    ind['up'] += 1
                if is_zt:
                    ind['zt'] += 1
            ind['codes'].add(code)
            b['industry_vol'] += amt
        if cname:
            con = b['concepts'][cname]
            if code not in con['codes']:
                con['pcts'].append(pct)
                con['amts'].append(amt)
                con['n'] += 1
                if pct > 0:
                    con['up'] += 1
                if is_zt:
                    con['zt'] += 1
            con['codes'].add(code)
            b['concept_vol'] += amt

    for r in rows:
        code = r.get('股票代码', '').strip()
        if not code:
            continue
        pct = sf(r, '涨跌幅')
        amt = sf(r, '成交额')
        sector_str = r.get('所属板块', r.get('\ufeff所属板块', ''))
        limit = get_limit_threshold(code)
        prev_close = sf(r, '昨收价')

        is_zt = pct >= limit - 0.5
        is_zb = False
        if not is_zt and prev_close > 0:
            limit_price = prev_close * (1 + limit / 100)
            high = sf(r, '最高价')
            if high >= limit_price - 0.01:
                is_zb = True

        stock_name = r.get('股票名称', r.get('股票名称', '')).strip()
        is_ipo = stock_name.startswith('N') or stock_name.startswith('*N')
        lv3 = _extract_lv3(sector_str)

        # ── v2 主通道：KPH 板块映射 -> 主题 ──
        if is_v2 and code in stock_themes:
            for theme_name in stock_themes[code]:
                b = buckets[theme_name]
                _fill_bucket(b, code, pct, amt, is_zt, is_zb, is_ipo)
            # v2: use kaipanhong plate names as sub-sectors
            code_plates = stock_plates.get(code, set())
            for plate_name in code_plates:
                plate_theme = plate_to_theme.get(plate_name, '')
                if not plate_theme or plate_theme not in stock_themes.get(code, set()):
                    continue
                b = buckets[plate_theme]
                con = b['concepts'][plate_name]
                if code not in con['codes']:
                    con['pcts'].append(pct)
                    con['amts'].append(amt)
                    con['n'] += 1
                    if pct > 0:
                        con['up'] += 1
                    if is_zt:
                        con['zt'] += 1
                con['codes'].add(code)
                b['concept_vol'] += amt
            continue

        # ── 旧版通道1：三级行业 -> 主题 ──
        theme_from_lv3 = lv3_to_theme.get(lv3, '')
        lv3_themes = theme_from_lv3 if isinstance(theme_from_lv3, list) else ([theme_from_lv3] if theme_from_lv3 else [])
        for _theme_name in lv3_themes:
            b = buckets[_theme_name]
            _fill_bucket(b, code, pct, amt, is_zt, is_zb, is_ipo, lv3=lv3)

        # ── 旧版通道2：概念 -> 主题 ──
        stock_concepts = concept_map.get(code, {}).get('concepts', [])
        seen_themes = set()
        for cname in stock_concepts:
            if not cname or cname in _GENERIC_CONCEPTS or _is_sw_industry(cname):
                continue
            ctheme_raw = concept_to_theme.get(cname, '')
            ctheme_list = ctheme_raw if isinstance(ctheme_raw, list) else ([ctheme_raw] if ctheme_raw else [])
            for ctheme in ctheme_list:
                if not ctheme:
                    continue
                if ctheme in seen_themes:
                    continue
                tc = theme_config.get(ctheme, {})
                if tc:
                    high_set = set(tc.get('high_concepts', []))
                    core_set = set(tc.get('core_lv3', []))
                    if cname not in high_set:
                        if lv3 not in core_set and not any(sc in high_set for sc in stock_concepts):
                            continue
                if ctheme == '化工' and '盐湖提锂' in stock_concepts:
                    continue
                seen_themes.add(ctheme)
                b = buckets[ctheme]
                _fill_bucket(b, code, pct, amt, is_zt, is_zb, is_ipo, cname=cname)

    return dict(buckets)





# ──────────────────────────────────────────────────────────────
# v3.0 评分因子（4维度·满分100）
# ──────────────────────────────────────────────────────────────

def _score_intensity(leader_avg: float, high5_ratio: float) -> int:
    """头部暴利强度 — leader_avg × high5_ratio × 100, 线性映射到 0-40

    v3.1 优化 (2026-04-29):
    - 上限 30→40，避免头部主题扎堆满分
    - 线性映射 raw/160*40，满分线160（原公式 raw/2=30 → raw=60 即满分）
    - 基准: raw=60→15, raw=100→25, raw=160→40
    - 区分度: AI算力(68)→17, 锂电(189)→40, 差距 23 分 vs 原来 0 分
    """
    raw = leader_avg * high5_ratio * 100
    return int(min(40, raw * 40 / 160))

def _score_zt_share(zt_share: float, zt_rate: float, avg_pct: float = 0, up_ratio: float = 0) -> int:
    """涨停力度 — 涨停密度(0-22) + 涨停带动效应(0-8)

    v3.3 重构 (2026-05-11):
    - Alpha视角：不只看涨停数量，更看涨停质量
    - 密度(zt_rate)作为主信号，取代zt_share分档
    - 带动效应(avg_pct*up_ratio)衡量涨停是否带动主题普涨
    - 与其他维度零重叠：不用leader_avg/high5_ratio（头部暴利强度已用）
    """
    # 涨停密度 (0-22): zt_rate = 主题内涨停股占比
    if zt_rate >= 0.060: density = 22
    elif zt_rate >= 0.050: density = 20
    elif zt_rate >= 0.040: density = 18
    elif zt_rate >= 0.030: density = 15
    elif zt_rate >= 0.025: density = 13
    elif zt_rate >= 0.020: density = 11
    elif zt_rate >= 0.015: density = 9
    elif zt_rate >= 0.010: density = 7
    elif zt_rate >= 0.005: density = 5
    else: density = 3

    # 涨停带动效应 (0-8): 涨停是否带动主题普涨
    # avg_pct > 0 且 up_ratio 高 → 涨停有带动效应，是真正的强Alpha
    if avg_pct > 0:
        pull_effect = avg_pct * up_ratio * 100
        if pull_effect >= 100: quality = 8
        elif pull_effect >= 70: quality = 6
        elif pull_effect >= 45: quality = 4
        elif pull_effect >= 25: quality = 2
        else: quality = 1
    else:
        quality = 0

    return min(30, density + quality)

def _score_breadth_v2(pcts: list) -> int:
    """上涨宽度 (20分) — 加权涨幅比

    v5.0 重构 (2026-05-11):
    - 信号从二元 up_ratio 改为连续 weighted_breadth = sum(max(0,pct)) / n
    - 兼顾"涨的股票多不多"和"涨的幅度高不高"
    - 10档阈值，CV 91.8%，Gap=0 从 72.4% 降至 42.4%
    """
    n = len(pcts)
    if n == 0:
        return 0
    weighted_breadth = sum(max(0, p) for p in pcts) / n
    if weighted_breadth >= 3.0: return 20
    elif weighted_breadth >= 2.5: return 18
    elif weighted_breadth >= 2.0: return 16
    elif weighted_breadth >= 1.5: return 14
    elif weighted_breadth >= 1.2: return 12
    elif weighted_breadth >= 0.9: return 10
    elif weighted_breadth >= 0.6: return 8
    elif weighted_breadth >= 0.4: return 6
    elif weighted_breadth >= 0.2: return 4
    elif weighted_breadth > 0:    return 2
    return 0

def _score_capital_v2(amts: list) -> int:
    """资金强度 (20分) — 龙头资金集中度

    v5.0 重构 (2026-05-11):
    - 信号从 per_stock/market_avg 改为 top5_amt/total_amt（龙头集中度）
    - 衡量资金是否集中在前5只龙头，集中度高→龙头辨识度高→主线概率大
    - 7档阈值，CV 61.1%，与头部暴利强度零重叠（看涨幅 vs 看成交额）
    """
    n = len(amts)
    if n == 0:
        return 0
    amts_sorted = sorted(amts, reverse=True)
    total = sum(amts_sorted)
    if total <= 0:
        return 0
    capital_conc = sum(amts_sorted[:5]) / total
    if capital_conc >= 0.65: return 20
    elif capital_conc >= 0.55: return 17
    elif capital_conc >= 0.45: return 14
    elif capital_conc >= 0.35: return 11
    elif capital_conc >= 0.25: return 8
    elif capital_conc >= 0.15: return 5
    return 0


# ──────────────────────────────────────────────────────────────
# 子板块查找（兼容旧字段）
# ──────────────────────────────────────────────────────────────

def _score_sub_intensity(pcts: list) -> int:
    """子板块头部暴利强度（40分）— 前5均涨幅 × 涨幅≥5%占比

    v3.1: 同步主题评分优化，上限 30→40，线性映射(满分线160)
    """
    sorted_pcts = sorted(pcts, reverse=True)
    leaders = sorted_pcts[:5]
    leader_avg = sum(leaders) / len(leaders) if leaders else 0
    n = len(pcts)
    high5_count = sum(1 for p in pcts if p >= 5.0)
    high5_ratio = high5_count / n if n > 0 else 0
    raw = leader_avg * high5_ratio * 100
    return int(min(40, raw * 40 / 160))


def _score_sub_zt(zt_count: int, theme_zt: int, stock_count: int, avg_pct: float = 0, up_ratio: float = 0) -> int:
    """子板块涨停力度（30分）— 密度 + 带动效应

    v3.3: 同步主题评分重构，密度+带动效应
    """
    zt_rate = zt_count / max(stock_count, 1)
    # 涨停密度 (0-22)
    if zt_rate >= 0.060: density = 22
    elif zt_rate >= 0.050: density = 20
    elif zt_rate >= 0.040: density = 18
    elif zt_rate >= 0.030: density = 15
    elif zt_rate >= 0.025: density = 13
    elif zt_rate >= 0.020: density = 11
    elif zt_rate >= 0.015: density = 9
    elif zt_rate >= 0.010: density = 7
    elif zt_rate >= 0.005: density = 5
    else: density = 3
    # 涨停带动效应 (0-8)
    if avg_pct > 0:
        pull_effect = avg_pct * up_ratio * 100
        if pull_effect >= 100: quality = 8
        elif pull_effect >= 70: quality = 6
        elif pull_effect >= 45: quality = 4
        elif pull_effect >= 25: quality = 2
        else: quality = 1
    else:
        quality = 0
    return min(30, density + quality)


def _score_sub_breadth(pcts: list) -> int:
    """子板块上涨宽度（20分）— 加权涨幅比，与主题评分同步"""
    n = len(pcts)
    if n == 0:
        return 0
    weighted_breadth = sum(max(0, p) for p in pcts) / n
    if weighted_breadth >= 3.0: return 20
    elif weighted_breadth >= 2.5: return 18
    elif weighted_breadth >= 2.0: return 16
    elif weighted_breadth >= 1.5: return 14
    elif weighted_breadth >= 1.2: return 12
    elif weighted_breadth >= 0.9: return 10
    elif weighted_breadth >= 0.6: return 8
    elif weighted_breadth >= 0.4: return 6
    elif weighted_breadth >= 0.2: return 4
    elif weighted_breadth > 0:    return 2
    return 0


def _score_sub_capital(amts: list) -> int:
    """子板块资金强度（20分）— 龙头资金集中度，与主题评分同步"""
    n = len(amts)
    if n == 0:
        return 0
    amts_sorted = sorted(amts, reverse=True)
    total = sum(amts_sorted)
    if total <= 0:
        return 0
    capital_conc = sum(amts_sorted[:5]) / total
    if capital_conc >= 0.65: return 20
    elif capital_conc >= 0.55: return 17
    elif capital_conc >= 0.45: return 14
    elif capital_conc >= 0.35: return 11
    elif capital_conc >= 0.25: return 8
    elif capital_conc >= 0.15: return 5
    return 0


def _calc_sub_score(ind: dict, theme_zt: int, theme_vol: float) -> dict:
    """计算单个子板块的4维度评分及明细"""
    n = ind['n']
    pcts = ind['pcts']
    vol = sum(ind['amts'])
    up_count = ind['up']
    zt_count = ind['zt']
    avg_pct = sum(pcts) / n if n > 0 else 0
    up_ratio = up_count / max(n, 1)

    sc_intensity = _score_sub_intensity(pcts)
    sc_zt = _score_sub_zt(zt_count, theme_zt, n, avg_pct, up_ratio)
    sc_breadth = _score_sub_breadth(pcts)
    sc_capital = _score_sub_capital(ind['amts'])
    total = sc_intensity + sc_zt + sc_breadth + sc_capital

    return {
        'score': round(total, 1),
        'avg_pct': round(avg_pct, 2),
        'volume_share': round(vol / theme_vol, 3) if theme_vol > 0 else 0,
        'zt_count': zt_count,
        'stock_count': n,
        'up_ratio': round(up_ratio, 3),
        'detail': {
            'sc_intensity': sc_intensity,
            'sc_zt': sc_zt,
            'sc_breadth': sc_breadth,
            'sc_capital': sc_capital,
        },
    }


def _find_top_sub(b: dict, total_vol: float, theme_zt: int = 0, theme_name: str = "") -> dict:
    best = None
    best_score = -1
    for lv3, ind in b.get('industries', {}).items():
        if ind['n'] < 2:
            continue
        r = _calc_sub_score(ind, theme_zt, total_vol)
        r['type'] = 'industry'
        r['name'] = lv3
        r['codes'] = list(ind.get('codes', set()))
        if r['score'] > best_score:
            best_score = r['score']
            best = r
    for cname, con in b.get('concepts', {}).items():
        if con['n'] < 2:
            continue
        r = _calc_sub_score(con, theme_zt, total_vol)
        r['type'] = 'concept'
        r['name'] = cname
        r['codes'] = list(con.get('codes', set()))
        if r['score'] > best_score:
            best_score = r['score']
            best = r
    # filter out sub_sector with same name as parent theme
    if best and theme_name and best.get('name') == theme_name:
        best = None
    return best or {'type': '', 'name': '', 'score': 0, 'volume_share': 0, 'zt_count': 0, 'avg_pct': 0, 'stock_count': 0, 'up_ratio': 0, 'detail': {}, 'codes': []}


def _find_top_subs(b: dict, total_vol: float, top_n: int = 3, theme_zt: int = 0, theme_name: str = "") -> list:
    all_subs = []
    for lv3, ind in b.get('industries', {}).items():
        if ind['n'] < 2:
            continue
        r = _calc_sub_score(ind, theme_zt, total_vol)
        r['type'] = 'industry'
        r['name'] = lv3
        r['codes'] = list(ind.get('codes', set()))
        all_subs.append(r)
    for cname, con in b.get('concepts', {}).items():
        if con['n'] < 2:
            continue
        r = _calc_sub_score(con, theme_zt, total_vol)
        r['type'] = 'concept'
        r['name'] = cname
        r['codes'] = list(con.get('codes', set()))
        all_subs.append(r)
    # filter out sub_sectors with same name as parent theme
    if theme_name:
        all_subs = [s for s in all_subs if s['name'] != theme_name]
    all_subs.sort(key=lambda x: x['score'], reverse=True)
    return all_subs[:top_n]


# ──────────────────────────────────────────────────────────────
# 连板加分
# ──────────────────────────────────────────────────────────────

_LIANBAN_BASE = {2: 1, 3: 3, 4: 5}  # 5连板+ 按5算


def _calc_lianban_bonus(theme_buckets: dict, lianban_tiers: list, rows_map: dict) -> dict:
    """计算每个主题的连板加分。

    每只连板股加分 = 基础分 × 涨跌幅系数 × 流动市值系数
    """
    # 构建连板股映射：code -> board_level
    lianban_codes = {}
    for tier in lianban_tiers:
        level = tier.get('level', 0)
        if level < 2:
            continue
        for s in tier.get('stocks', []):
            lianban_codes[s['code']] = level

    if not lianban_codes:
        return {}

    bonuses = {}
    for theme_name, b in theme_buckets.items():
        total_bonus = 0.0
        for code in b.get('codes', set()):
            if code not in lianban_codes:
                continue
            level = lianban_codes[code]
            base = _LIANBAN_BASE.get(level, _LIANBAN_BASE[4])

            # 涨跌幅系数
            board_mult = 1.5 if code.startswith(('30', '688', '8', '4')) else 1.0

            # 流动市值系数
            row = rows_map.get(code, {})
            float_cap = sf(row, '流动市值') if row else 0
            if float_cap > 200e8:
                cap_mult = 1.5
            else:
                cap_mult = 1.0

            total_bonus += base * board_mult * cap_mult

        if total_bonus > 0:
            bonuses[theme_name] = round(total_bonus, 1)

    return bonuses


# ──────────────────────────────────────────────────────────────
# 主题评分 v3.0
# ──────────────────────────────────────────────────────────────

def score_themes(
    theme_buckets: dict,
    prev_theme_rankings: dict = None,
    prev_prev_theme_rankings: dict = None,
    market_zt_total: int = 0,
    lianban_tiers: list = None,
    rows_map: dict = None,
) -> list:
    """v3.0 评分：4维度·满分100 + 连板加分"""
    prev_theme_rankings = prev_theme_rankings or {}

    # 计算全市场总量
    total_market_amt = 0
    for b in theme_buckets.values():
        total_market_amt += sum(b['amts'])
    total_market_zt = market_zt_total if market_zt_total > 0 else sum(b['zt'] for b in theme_buckets.values())

    scored_pre = []
    for name, b in theme_buckets.items():
        n = b['n']
        if n < 5:
            continue
        total_amt = sum(b['amts'])
        scored_pre.append((name, b, total_amt))

    scored_pre.sort(key=lambda x: x[2], reverse=True)

    # 计算市场个股均额基准（用于资金攻击强度维度）

    result = []
    for rank_0, (name, b, total_amt) in enumerate(scored_pre):
        n = b['n']

        # ── 维度1：头部暴利强度 (40分) ──
        pcts_sorted = sorted(b['pcts'], reverse=True)
        leaders = pcts_sorted[:30]
        leader_avg = sum(leaders) / len(leaders) if leaders else 0
        high5_count = sum(1 for p in b['pcts'] if p >= 5.0)
        high5_ratio = high5_count / n if n > 0 else 0
        sc_intensity = _score_intensity(leader_avg, high5_ratio)

        # ── 维度2：涨停力度 (30分) ──
        zt_share = b['zt'] / max(total_market_zt, 1)
        zt_rate = b['zt'] / max(n, 1)
        up_ratio = b['up'] / max(n, 1)
        avg_pct_val = sum(b['pcts']) / n if n > 0 else 0
        sc_zt = _score_zt_share(zt_share, zt_rate, avg_pct_val, up_ratio)

        # ── 维度3：上涨宽度 (20分) ──
        sc_breadth = _score_breadth_v2(b['pcts'])

        # ── 维度4：资金攻击强度 (20分) ──
        sc_capital = _score_capital_v2(b['amts'])

        total = sc_intensity + sc_zt + sc_breadth + sc_capital
        # avg penalty: penalize themes with worse avg on down days
        avg_penalty = max(0, abs(min(0, avg_pct_val)) * 2)
        total = total - avg_penalty

        # 兼容旧字段
        top_sub = _find_top_sub(b, total_amt, theme_zt=b['zt'], theme_name=name)
        top_subs = _find_top_subs(b, total_amt, 3, theme_zt=b['zt'], theme_name=name)

        result.append({
            'theme': name,
            'score': round(total, 1),
            'avg_pct': round(sum(b['pcts']) / n, 2) if n > 0 else 0,
            'median_pct': round(sorted(b['pcts'])[n // 2], 2) if b['pcts'] else 0,
            'up_ratio': round(up_ratio, 3),
            'amount': round(total_amt / 1e8, 2),
            'stock_count': n,
            'zt_count': b['zt'],
            'zb_count': b['zb'],
            'amt_rank': rank_0 + 1,
            'prev_rank': prev_theme_rankings.get(name),
            'leader_pct': round(b['leader_pct'], 2),
            'leader_code': b['leader_code'],
            'leader_avg': round(leader_avg, 2),
            'high5_ratio': round(high5_ratio, 4),
            'top_sub_sector': top_sub,
            'sub_sectors': top_subs,
            'components': {
                'industries': list(b.get('industries', {}).keys()),
                'concepts': list(b.get('concepts', {}).keys()),
            },
            'industry_vol': round(b.get('industry_vol', 0) / 1e8, 2),
            'concept_vol': round(b.get('concept_vol', 0) / 1e8, 2),
            'codes': list(b['codes']),
            'detail': {
                'sc_intensity': sc_intensity,
                'sc_zt': sc_zt,
                'sc_breadth': sc_breadth,
                'sc_capital': sc_capital,
                'zt_share': round(zt_share, 4),
                'zt_rate': round(zt_rate, 4),
                'weighted_breadth': round(sum(max(0, p) for p in b['pcts']) / n, 3) if n > 0 else 0,
                'capital_conc': round(sum(sorted(b['amts'], reverse=True)[:5]) / max(total_amt, 1), 4),
                'high5_ratio': round(high5_ratio, 4),
                'leader_avg': round(leader_avg, 2),
            },
        })

    # ── 连板加分 ──
    lianban_bonuses = _calc_lianban_bonus(theme_buckets, lianban_tiers or [], rows_map or {})

    # ── 最高连板加分：连板≥3时，所有最高连板股所在主题各+4 ──
    _highest_level = 0
    _highest_codes = set()
    for tier in (lianban_tiers or []):
        lv = tier.get('level', 0)
        if lv >= 3:
            if lv > _highest_level:
                _highest_level = lv
                _highest_codes = {s.get('code', '') for s in tier.get('stocks', []) if s.get('code')}
            elif lv == _highest_level:
                _highest_codes |= {s.get('code', '') for s in tier.get('stocks', []) if s.get('code')}
    _highest_board_themes = set()
    if _highest_codes and _highest_level >= 3:
        for theme_name, b in theme_buckets.items():
            if b.get('codes', set()) & _highest_codes:
                _highest_board_themes.add(theme_name)

    for item in result:
        bonus = lianban_bonuses.get(item['theme'], 0)
        highest_bonus = 4 if item['theme'] in _highest_board_themes else 0
        total_bonus = bonus + highest_bonus
        total_bonus = min(total_bonus, LIANBAN_BONUS_CAP)
        if total_bonus > 0:
            item['lianban_bonus'] = total_bonus
            item['highest_board_bonus'] = highest_bonus
            item['score'] = round(item['score'] + total_bonus, 1)
        else:
            item['lianban_bonus'] = 0
            item['highest_board_bonus'] = 0
        if highest_bonus > 0:
            item['highest_board'] = f'{_highest_level}板'


    result.sort(key=lambda x: x['score'], reverse=True)
    for i, item in enumerate(result):
        item['rank'] = i + 1
    return result


# ──────────────────────────────────────────────────────────────
# 写入主题K线
# ──────────────────────────────────────────────────────────────

def write_theme_kline(theme_scores: list, data_dir: str, date_str: str):
    kline_dir = os.path.join(data_dir, 'theme_kline')
    os.makedirs(kline_dir, exist_ok=True)
    for t in theme_scores:
        name = t['theme']
        fpath = os.path.join(kline_dir, f'{_safe_filename(name)}.csv')
        is_new = not os.path.exists(fpath)
        with open(fpath, 'a', encoding='utf-8') as f:
            if is_new:
                f.write('日期,平均涨幅,上涨占比,成交额亿,涨停数,评分,排名\n')
            # 防重复: 已有该日期则跳过
            if not is_new:
                with open(fpath, "r", encoding="utf-8") as _ck:
                    if any(line.startswith(date_str + ",") for line in _ck):
                        continue
            f.write(f'{date_str},{t["avg_pct"]},{t["up_ratio"]},{t["amount"]},{t["zt_count"]},{t["score"]},{t["rank"]}\n')


# ──────────────────────────────────────────────────────────────
# 顶层入口
# ──────────────────────────────────────────────────────────────

def calc_sector_v5(
    rows_today: list,
    data_dir: str = None,
    quant_dir: str = None,
) -> dict:
    if data_dir is None:
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
    if quant_dir is None:
        quant_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)))

    date_str = ''
    if rows_today:
        r0 = rows_today[0]
        date_str = r0.get('交易日期', r0.get('\ufeff交易日期', ''))

    theme_kline_dir = os.path.join(data_dir, 'theme_kline')
    prev_theme_rankings = _load_prev_rankings(theme_kline_dir, date_str)
    prev_date = _find_prev_date(theme_kline_dir, date_str)
    prev_prev_theme_rankings = _load_prev_rankings_at(theme_kline_dir, prev_date) if prev_date else {}
    ranking_history = _load_ranking_history(theme_kline_dir, date_str, days=3)

    theme_buckets = aggregate_to_themes(rows_today, data_dir=data_dir, quant_dir=quant_dir)
    # 计算全市场真实涨停数（去重）
    _zt_codes = set()
    for _r in rows_today:
        _code = _r.get('\u80a1\u7968\u4ee3\u7801', '').strip()
        _pct = sf(_r, '\u6da8\u8dcc\u5e45')
        _limit = get_limit_threshold(_code)
        if _pct >= _limit - 0.5:
            _zt_codes.add(_code)
    market_zt_count = len(_zt_codes)

    # 计算连板梯队
    try:
        _parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _parent not in sys.path:
            sys.path.insert(0, _parent)
        from lianban import compute_lianban_tiers
        lianban_tiers = compute_lianban_tiers(date_str).get('tiers', [])
    except Exception as _lb_err:
        print(f"⚠️ 连板计算失败: {_lb_err}", file=sys.stderr)
        lianban_tiers = []

    # 构建 code -> row 映射（连板加分用流动市值）
    rows_map = {}
    for _r in rows_today:
        _code = _r.get('股票代码', '').strip()
        if _code:
            rows_map[_code] = _r

    theme_scores = score_themes(theme_buckets, prev_theme_rankings, prev_prev_theme_rankings, market_zt_total=market_zt_count, lianban_tiers=lianban_tiers, rows_map=rows_map)

    if date_str and theme_scores:
        write_theme_kline(theme_scores, data_dir, date_str)

    top3 = [t['theme'] for t in theme_scores[:3]]
    avg_top10 = sum(t['score'] for t in theme_scores[:10]) / max(len(theme_scores[:10]), 1)

    # 兼容旧字段
    resonance_compat = []
    for t in theme_scores[:20]:
        resonance_compat.append({
            'name': t['theme'],
            'type': 'theme',
            'resonance': t['score'],
            'avg_pct': t['avg_pct'],
            'up_ratio': t['up_ratio'],
            'amount': t['amount'],
            'stock_count': t['stock_count'],
            'zt_count': t['zt_count'],
            'zb_count': t['zb_count'],
            'amt_rank': t['amt_rank'],
            'prev_rank': t['prev_rank'],
            'leader_pct': t['leader_pct'],
            'leader_code': t['leader_code'],
            'deduct': 0,
            'deduct_reasons': [],
            'industry_score': t['score'],
            'concept_score': None,
            'best_concept': None,
            'codes': t['codes'],
            'related_concepts': [],
        })

    return {
        'theme_top': theme_scores,
        'ranking_history': ranking_history,
        'summary': {
            'theme_top3': top3,
            'avg_theme_score': round(avg_top10, 1),
            'total_themes': len(theme_scores),
            'industry_top3': top3,
            'concept_top3': top3,
            'avg_industry_score': round(avg_top10, 1),
            'avg_concept_score': round(avg_top10, 1),
            'total_industry': len(theme_scores),
            'total_concept': len(theme_scores),
        },
        'resonance_top': resonance_compat,
        'industry_top': [],
        'concept_top': [],
    }
