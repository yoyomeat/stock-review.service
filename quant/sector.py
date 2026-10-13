#!/usr/bin/env python3
"""板块分析 — calc_sector_enhanced 及相关板块聚合/去重逻辑"""
import os
import json
from collections import defaultdict
from data_loader import _load_sector_hierarchy
from sentiment import _aggregate_all_sectors

def _get_parent_of_concept(name: str, concept_to_cat: dict) -> tuple | None:
    """统一的概念→父级映射。支持括号截断 + 模糊子串 fallback + 行业名匹配。
    返回 (lv1, lv2, lv3) 3元组 或 None。"""
    if not concept_to_cat:
        return None
    # 1. 去掉聚合后缀 "电子(含国防军工)" → "电子"
    base = name
    # 去掉 "含xxx" 后缀（聚合名）
    if '含' in base:
        base = base.split('含')[0].strip()
    cat = concept_to_cat.get(base)
    if cat:
        return cat
    # 2. 行业名反查（CSV的行业名 → 层级）
    _hier = _load_sector_hierarchy()
    _ntp = _hier.get('name_to_parent', {})
    if base in _ntp:
        return _ntp[base]
    # 3. 模糊子串: base 包含某概念名
    for k, v in concept_to_cat.items():
        if k in base:
            return v
    # 4. 反向: 某概念名包含 base（base 是行业名如 "电子"）
    if len(base) >= 2:
        for k, v in concept_to_cat.items():
            if len(k) >= len(base) and base in k:
                return v
    return None

def _score_all_sectors(sectors, min_stocks=3):
    """
    四维强度评分（满分 100）：
      A. 市值加权涨幅    0~35 分
      B. 资金强度        0~25 分
      C. 涨停联动强度    0~25 分
      D. 板块热度        0~15 分
    min_stocks: 板块最少个股数（低于此数不参与排名）
    """
    scored = {}

    for name, sd in sectors.items():
        n = len(sd['pcts'])
        if n < min_stocks:
            continue

        avg_pct = sum(sd['pcts']) / n
        total_amt = sum(sd['amts'])
        total_mcap = sum(sd['mkt_caps'])
        zt_count = sd['zt']
        up_ratio = sd['up'] / n
        avg_turnover = sum(sd['turnover']) / n

        # ── A. 市值加权涨幅 (0~35) ──
        if total_mcap > 0:
            wavg_pct = sum(p * m for p, m in zip(sd['pcts'], sd['mkt_caps'])) / total_mcap
        else:
            wavg_pct = avg_pct
        score_wavg = max(0, min((wavg_pct + 3) / 11 * 35, 35))

        # ── B. 资金强度 (0~25) ──
        amt_per_stock = total_amt / n  # 板内个股平均成交额
        if total_mcap > 0:
            capital_ratio = total_amt / total_mcap  # 成交额/流通市值
        else:
            capital_ratio = 0
        # 标准化：个股均成交 5 亿 + 换手率 5% → 满分
        score_cap = min((amt_per_stock / 5e8) * 12.5 + (capital_ratio * 1000) * 12.5 / 5, 25)

        # ── C. 涨停联动强度 (0~25) ──
        # 绝对涨停数 + 板内涨停占比
        zt_ratio = zt_count / n
        score_zt = min(zt_count * 3, 15) + min(zt_ratio * 100, 10)

        # ── D. 板块热度 (0~15) ──
        score_heat = up_ratio * 8 + min(avg_turnover / 8, 1) * 7

        total = round(score_wavg + score_cap + score_zt + score_heat, 2)

        scored[name] = {
            'avg_pct': round(avg_pct, 2),
            'wavg_pct': round(wavg_pct, 2),
            'zt_count': zt_count,
            'amount': round(total_amt / 1e8, 2),
            'stock_count': n,
            'up_ratio': round(up_ratio, 3),
            'avg_turnover': round(avg_turnover, 2),
            'is_concept': sd['is_concept'],
            'score': total,
            'codes': sd['codes'],
            'detail': {
                'score_wavg': round(score_wavg, 1),
                'score_cap': round(score_cap, 1),
                'score_zt': round(score_zt, 1),
                'score_heat': round(score_heat, 1),
            },
        }

    return scored


def _dedup_by_similarity(ranked_sectors, threshold=0.6):
    """
    相似性去重：Jaccard(成分股) > threshold 的板块只保留排名更高的。
    优化：预计算长度+小集合遍历+上界剪枝，避免创建新 set。
    """
    if not ranked_sectors:
        return ranked_sectors

    kept = []
    kept_codes = []  # 预计算 (codes_set, len) 避免重复

    for sec in ranked_sectors:
        codes = sec[1].get('codes')
        if not codes:
            kept.append(sec)
            continue

        len_codes = len(codes)
        if len_codes == 0:
            kept.append(sec)
            continue

        is_dup = False
        for kc, len_kc in kept_codes:
            # Jaccard 上界 = min(lenA, lenB) / max(lenA, lenB)
            # 如果上界 ≤ 阈值，实际 Jaccard 必然 ≤ 阈值，跳过
            if len_codes <= len_kc:
                min_len, max_len = len_codes, len_kc
            else:
                min_len, max_len = len_kc, len_codes

            if min_len <= threshold * max_len:
                continue

            # 交集：遍历较小集合，查较大集合
            if len_codes <= len_kc:
                inter = sum(1 for c in codes if c in kc)
            else:
                inter = sum(1 for c in kc if c in codes)

            # jaccard = inter / (lenA + lenB - inter) > threshold
            union = len_codes + len_kc - inter
            if union > 0 and inter > threshold * union:
                is_dup = True
                break

        if not is_dup:
            kept.append(sec)
            kept_codes.append((codes, len_codes))

    return kept



# 主题关键词组（匹配到任一关键词即归入该组，同组只保留排名最高的板块）
_THEME_GROUPS = [
    # ── 电池/锂电/储能链 ──
    ['电池', '锂电', '储能', '正极', '负极', '电解液', '隔膜', '钠电池', '固态电池', '锂矿'],
    # ── 光伏链 ──
    ['光伏', '太阳能', 'HJT', 'TOPCON', 'BC电池', '钙钛矿', '硅片', 'POE胶膜'],
    # ── 半导体/芯片链 ──
    ['芯片', '半导体', '集成电路', '晶圆', '封测', 'EDA', '光刻', 'Chiplet', 'HBM'],
    # ── AI链 ──
    ['AI', '人工智能', '大模型', '算力', '智算', 'AIGC', 'ChatGPT', 'DeepSeek', 'Sora', '多模态', 'AI应用', 'AI Agent'],
    # ── 汽车链 ──
    ['汽车', '新能源车', '整车', '充电桩', '无人驾驶', '智能驾驶', '一体化压铸', '线控底盘', '毫米波雷达', '激光雷达'],
    # ── 医药链 ──
    ['医药', '生物医药', '创新药', 'CRO', '疫苗', '基因', '细胞治疗', '医疗器械', '中药', '流感', '肝炎', '仿制药', '一致性评价', '减肥药', '幽门螺杆菌', '医美'],
    # ── 房地产/基建链 ──
    ['房地产', '基建', '城镇化', '建材', '水泥', '装修', '新型城镇化', '城中村'],
    # ── 军工链 ──
    ['军工', '航天', '导弹', '大飞机', '卫星', '北斗', '低空经济', '商业航天', '无人机'],
    # ── 消费链 ──
    ['消费', '食品', '白酒', '啤酒', '乳制品', '餐饮', '旅游', '免税', '预制菜'],
    # ── 金融链 ──
    ['银行', '券商', '保险', '金融', '信托', '期货', '多元金融', '数字货币'],
    # ── 通信/PCB/光模块链 ──
    ['通信', '5G', '光模块', '光纤', '光通信', 'CPO', '覆铜板', 'PCB', '6G', 'F5G', '铜缆高速连接', '电子布'],
    # ── 机器人链 ──
    ['机器人', '人形机器人', '减速器', '伺服', '电机', '传感器', '机器视觉', '灵巧手', '滚珠丝杠', '宇树', '小米'],
    # ── 有色/稀土链 ──
    ['稀土', '有色', '铜', '铝', '黄金', '贵金属', '锡', '钨', '钼', '锗'],
    # ── 化工链 ──
    ['化工', '有机硅', '甲醇', '丙烯', '聚氨酯', '钛白粉', '磷化工', '氟化工', '维生素'],
    # ── 短视频/传媒链 ──
    ['快手', '小红书', '抖音', '营销', '广告', '传媒', '短剧', '内容', '社交', 'MCN', '网红', '游戏'],
    # ── 数据要素/信创链 ──
    ['信创', '数据要素', '数据安全', '网络安全', '国产软件', '操作系统', '数据库', '政务'],
    # ── 新能源电力链 ──
    ['风电', '海上风电', '核电', '水电', '虚拟电厂', '智能电网', '特高压', '电力'],
    # ── 消费电子链 ──
    ['消费电子', '苹果', 'MR', 'VR', 'AR', '智能音箱', '折叠屏', 'TWS'],
    # ── 船舶/航运链 ──
    ['船舶', '航运', '港口', '集运', '散货'],
    # ── 算力基础设施链 ──
    ['数据中心', 'IDC', '液冷', '服务器', '存储', '云计算', '东数西算'],
]

def _get_theme(name):
    """返回板块名所属的主题索引，不在任何主题中返回 -1"""
    for i, keywords in enumerate(_THEME_GROUPS):
        for kw in keywords:
            if kw in name:
                return i
    return -1

def _dedup_by_theme(ranked_sectors):
    """
    语义分组去重：同主题板块只保留排名最高的。
    在 Jaccard 去重之后使用，不替换 Jaccard 去重。
    """
    kept = []
    seen_themes = set()
    for sec in ranked_sectors:
        name = sec[0]
        theme = _get_theme(name)
        if theme == -1:
            kept.append(sec)
        elif theme not in seen_themes:
            kept.append(sec)
            seen_themes.add(theme)
    return kept


def _aggregate_related_concepts(ranked_sectors, jaccard_threshold=0.25, min_stocks=15):
    """
    相关概念聚合：成分股高度相似或逻辑相关的板块合并为主板块。
    大板块为主名，小板块在括号补充。
    例: "PCB概念(含覆铜板,6G概念)"
    
    规则:
      1. 同_THEME_GROUPS 且 Jaccard > jaccard_threshold → 聚合
      2. 名称包含关系（覆铜板 ⊂ PCB） → 直接聚合
      3. 小概念(<min_stocks) 找不到大板块则剔除
    """
    if not ranked_sectors:
        return ranked_sectors

    # 预计算每个板块的 theme + codes
    sectors_info = []
    for name, sd in ranked_sectors:
        codes = sd.get('codes', set())
        stock_count = sd.get('stock_count', len(codes) if codes else 0)
        sectors_info.append({
            'name': name, 'sd': sd, 'codes': codes,
            'stock_count': stock_count,
            'theme': _get_theme(name),
            'score': sd.get('score', 0),
            'merged_subs': [],  # 被聚合进来的小板块名
        })

    # 主板块保留列表
    kept = []
    consumed = set()  # 已被聚合的小板块索引

    for i, si in enumerate(sectors_info):
        if i in consumed:
            continue

        # 寻找可以聚合到当前板块的小板块
        subs = []
        for j, sj in enumerate(sectors_info):
            if j <= i or j in consumed:
                continue
            # 判断是否相关
            related = False

            # 条件1: 同主题
            if si['theme'] >= 0 and si['theme'] == sj['theme']:
                related = True

            # 条件2: 名称包含关系（小板块名出现在大板块名中，或反之）
            if not related:
                kw_sj = sj['name'].replace('概念', '').replace('板块', '').strip()
                kw_si = si['name'].replace('概念', '').replace('板块', '').strip()
                if len(kw_sj) >= 2 and kw_sj in si['name']:
                    related = True
                elif len(kw_si) >= 2 and kw_si in sj['name']:
                    related = True

            # 条件3: Jaccard 成分股相似度
            if not related and si['codes'] and sj['codes']:
                len_a, len_b = len(si['codes']), len(sj['codes'])
                if len_a > 0 and len_b > 0:
                    # 快速剪枝
                    min_len, max_len = min(len_a, len_b), max(len_a, len_b)
                    if min_len > jaccard_threshold * max_len:
                        if len_a <= len_b:
                            inter = sum(1 for c in si['codes'] if c in sj['codes'])
                        else:
                            inter = sum(1 for c in sj['codes'] if c in si['codes'])
                        union = len_a + len_b - inter
                        if union > 0 and inter / union >= jaccard_threshold:
                            related = True

            if related:
                # 只聚合较小的板块到较大的
                if sj['stock_count'] < si['stock_count']:
                    subs.append(sj)
                    consumed.add(j)
                elif si['stock_count'] < sj['stock_count']:
                    # 当前板块更小，应该被大板块聚合（标记，后面跳过）
                    pass

        # 构建聚合后的板块
        if subs:
            # 合并成分股
            all_codes = set(si['codes'])
            sub_names = []
            for sub in subs:
                all_codes.update(sub['codes'])
                sub_names.append(sub['name'])

            # 更新主板块
            si['sd']['codes'] = all_codes
            si['sd']['stock_count'] = len(all_codes)
            si['merged_subs'] = sub_names

            # 修改板块名：附加聚合信息
            if sub_names:
                # 去重 + 截断（最多显示3个）
                unique_subs = list(dict.fromkeys(sub_names))[:3]
                suffix = '含' + ','.join(unique_subs)
                if len(sub_names) > 3:
                    suffix += f'等{len(sub_names)}个'
                si['display_name'] = f"{si['name']}({suffix})"
            else:
                si['display_name'] = si['name']
        else:
            si['display_name'] = si['name']

        kept.append((si['display_name'], si['sd']))

    return kept


def _calc_parent_concentration(top5, parent_sectors):
    """Calculate parent sector concentration for TOP5 concepts (lv1 + lv2)."""
    if not top5:
        return 0.5, [], 'no data'
    hierarchy_data = _load_sector_hierarchy()
    concept_to_cat = hierarchy_data.get('concept_to_category', {})
    if not concept_to_cat:
        return 0.5, [], 'no hierarchy data'

    lv1_count = defaultdict(int)
    lv2_count = defaultdict(int)
    for name, sd in top5:
        cat = _get_parent_of_concept(name, concept_to_cat)
        if cat:
            lv1_count[cat[0]] += 1
            if len(cat) >= 2 and cat[1]:
                lv2_count[cat[1]] += 1
        else:
            lv1_count['unmatched'] += 1

    n_lv1 = len([p for p in lv1_count if p != 'unmatched'])
    labels = sorted(set(p for p in lv1_count if p != 'unmatched'))

    # 如果lv1集中度不够，检查lv2是否在同一父级下的不同子级（仍然相关）
    if n_lv1 <= 1:
        # lv2 细分
        lv2_labels = sorted(set(p for p in lv2_count))
        if len(lv2_labels) <= 1:
            return 1.0, labels, 'TOP5 all in ' + (labels[0] if labels else 'unknown')
        else:
            return 0.9, labels, 'TOP5 in %s(%s)' % (labels[0] if labels else '', '/'.join(lv2_labels[:3]))
    elif n_lv1 <= 2:
        return 0.8, labels, 'TOP5 in ' + '/'.join(labels)
    elif n_lv1 <= 3:
        return 0.5, labels, 'TOP5 scattered in %d sectors(%s)' % (n_lv1, '/'.join(labels))
    else:
        return 0.2, labels, 'TOP5 highly scattered(%d sectors)' % n_lv1

def _build_parent_sectors(scored, ranked_topN):
    """构建父级行业聚合。v2层级: 按lv1聚合，lv2作为子分组。"""
    hierarchy_data = _load_sector_hierarchy()
    concept_to_cat = hierarchy_data.get('concept_to_category', {})
    if not concept_to_cat:
        return []

    is_v2 = hierarchy_data.get('version') == 'v2'

    # 按 lv1 聚合所有 scored 板块
    parent_children = defaultdict(list)  # lv1 -> [child_info]
    for concept_name, sd in scored.items():
        cat = concept_to_cat.get(concept_name)
        if cat:
            lv1 = cat[0]
            lv2 = cat[1] if len(cat) >= 2 else ''
            lv3 = cat[2] if len(cat) >= 3 else ''
            parent_children[lv1].append({
                'name': concept_name,
                'lv2': lv2,
                'lv3': lv3,
                'score': sd.get('score', 0),
                'avg_pct': sd.get('avg_pct', 0),
                'zt_count': sd.get('zt_count', 0),
                'stock_count': sd.get('stock_count', 0),
                'codes': sd.get('codes', set()),
            })

    parents = []
    for lv1, children in parent_children.items():
        if not children:
            continue
        children.sort(key=lambda x: -x['score'])
        top_children = children[:5]
        total_stock_count = len(set().union(*[c['codes'] for c in children]))
        max_score = max(c['score'] for c in children)
        total_zt = sum(c['zt_count'] for c in children)
        weighted_pct = sum(c['avg_pct'] * c['stock_count'] for c in top_children) / max(sum(c['stock_count'] for c in top_children), 1)

        child_list = [
            {'name': c['name'], 'score': round(c['score'], 1),
             'avg_pct': round(c['avg_pct'], 2), 'zt_count': c['zt_count'],
             'stock_count': c['stock_count']}
            for c in children[:6]
        ]

        entry = {
            'name': lv1,
            'score': round(max_score, 1),
            'avg_pct': round(weighted_pct, 2),
            'zt_count': total_zt,
            'stock_count': total_stock_count,
            'child_count': len(children),
            'children': child_list,
        }

        # v2: 添加 lv2 子分组
        if is_v2:
            lv2_groups = defaultdict(list)
            for c in children:
                lv2_groups[c['lv2']].append(c)
            entry['lv2_groups'] = []
            for lv2_name, lv2_children in sorted(lv2_groups.items(), key=lambda x: -max(c['score'] for c in x[1])):
                lv2_children.sort(key=lambda x: -x['score'])
                lv2_zt = sum(c['zt_count'] for c in lv2_children)
                lv2_stock_count = len(set().union(*[c['codes'] for c in lv2_children]))
                lv2_max_score = max(c['score'] for c in lv2_children)
                entry['lv2_groups'].append({
                    'name': lv2_name,
                    'score': round(lv2_max_score, 1),
                    'zt_count': lv2_zt,
                    'stock_count': lv2_stock_count,
                    'children': [
                        {'name': c['name'], 'score': round(c['score'], 1),
                         'avg_pct': round(c['avg_pct'], 2), 'zt_count': c['zt_count'],
                         'stock_count': c['stock_count']}
                        for c in lv2_children[:4]
                    ],
                })

        parents.append((lv1, entry))

    parents.sort(key=lambda x: -x[1]['score'])
    return parents

def _merge_small_sectors(ranked_sectors, min_stocks=20, merge_threshold=0.1):
    """
    小板块合并/过滤（概念+行业均适用）：
    - 板块 < min_stocks 只股票时，尝试合并到相似的大板块
    - 合并策略（优先级从高到低）：
      1. 行业子级匹配：行业板块名出现在 sector_hierarchy 二级名中 → 合并到同一大板块下最大的板块
      2. 同主题匹配（_THEME_GROUPS 同组 → 合并到同组最大的板块）
      3. Jaccard > merge_threshold（成分股相似度）
    - 找不到可合并的大板块则剔除
    """
    if not ranked_sectors:
        return ranked_sectors

    # 加载层级映射（用于行业子级匹配）
    hierarchy_data = _load_sector_hierarchy()
    hier = hierarchy_data.get('hierarchy', {})
    # 构建 二级名关键词 → 一级名 的反查表
    lv2_to_lv1 = {}
    for lv1, subs in hier.items():
        for lv2, concepts in subs.items():
            lv2_to_lv1[lv2] = lv1

    # 分离大小板块
    small_sectors = []  # (idx, sector) 小板块
    large_sectors = []   # 正常保留的板块

    for i, sec in enumerate(ranked_sectors):
        sd = sec[1]
        stock_count = sd.get('stock_count', len(sd.get('codes', set())))

        if stock_count < min_stocks:
            small_sectors.append((i, sec))
        else:
            large_sectors.append(sec)

    if not small_sectors:
        return ranked_sectors

    # 对每个小板块，尝试找相似的大板块合并
    merged_into = {}  # large_idx -> merged codes set
    skipped = []

    for _, small_sec in small_sectors:
        small_name = small_sec[0]
        small_codes = small_sec[1].get('codes', set())
        if not small_codes:
            skipped.append(small_name)
            continue

        # 策略0：行业子级匹配（小板块名在层级中 → 合并到同组最大的板块）
        best_target = None
        best_score = 0
        small_lv1 = lv2_to_lv1.get(small_name)
        if small_lv1:
            # 能源金属 → 有色（通过层级找到一级归属）
            # 收集同组下的所有概念名
            same_group_concepts = set()
            for lv2k, concepts in hier.get(small_lv1, {}).items():
                same_group_concepts.update(concepts)
            same_group_concepts.add(small_lv1)  # 也包含一级名本身
            for j, large_sec in enumerate(large_sectors):
                large_name = large_sec[0]
                # 大板块属于同一层级（同二级或同一级下的其他二级）
                if (lv2_to_lv1.get(large_name) == small_lv1
                    or large_name == small_lv1
                    or large_name in same_group_concepts):
                    large_size = large_sec[1].get('stock_count', 0)
                    if large_size > best_score:
                        best_score = large_size
                        best_target = j

        # 策略1：主题关键词匹配（同_THEME_GROUPS分组）
        if best_target is None:
            best_score = 0
            small_theme = _get_theme(small_name)

            if small_theme >= 0:
                # 找同主题的大板块（取最大的）
                for j, large_sec in enumerate(large_sectors):
                    large_name = large_sec[0]
                    if _get_theme(large_name) == small_theme:
                        large_size = large_sec[1].get('stock_count', 0)
                        if large_size > best_score:
                            best_score = large_size
                            best_target = j

        # 策略1.5：名称关键词包含匹配（小板块名的关键词出现在大板块名中）
        if best_target is None:
            # 提取小板块名中的关键部分（去掉概念等后缀）
            kw = small_name.replace('概念', '').replace('板块', '').strip()
            if len(kw) >= 2:
                for j, large_sec in enumerate(large_sectors):
                    large_name = large_sec[0]
                    large_codes = large_sec[1].get('codes', set())
                    # 关键词出现在大板块名中，且大板块有足够多股票
                    if kw in large_name and len(large_codes) >= min_stocks:
                        best_target = j
                        break
                    # 反向：大板块关键词出现在小板块名中
                    lk = large_name.replace('概念', '').replace('板块', '').strip()
                    if lk in small_name and len(large_codes) >= min_stocks:
                        best_target = j
                        break

        # 策略2：Jaccard 成分股相似度
        if best_target is None:
            best_jaccard = 0
            for j, large_sec in enumerate(large_sectors):
                large_codes = large_sec[1].get('codes', set())
                if not large_codes:
                    continue
                inter = sum(1 for c in small_codes if c in large_codes)
                union = len(small_codes) + len(large_codes) - inter
                if union > 0:
                    jacc = inter / union
                    if jacc > best_jaccard:
                        best_jaccard = jacc
                        best_target = j
            if best_target is not None and best_jaccard < merge_threshold:
                best_target = None

        if best_target is not None:
            # 合并到大板块
            if best_target not in merged_into:
                merged_into[best_target] = set()
            merged_into[best_target].update(small_codes)
        else:
            skipped.append(small_name)

    # 执行合并：将小板块的 codes 合并到大板块
    for target_idx, extra_codes in merged_into.items():
        target_sd = large_sectors[target_idx][1]
        target_sd['codes'] = target_sd.get('codes', set()) | extra_codes
        target_sd['stock_count'] = len(target_sd['codes'])

    return large_sectors




def _merge_by_parent(ranked_sectors):
    """
    同父级行业合并：将同一父级行业/主题下的多个细分板块合并为一个主板块。
    优先级：
      1. concept_to_category 的一级行业匹配
      2. _THEME_GROUPS 主题关键词匹配
      3. 一级行业股票池重叠（从 stock_industry_concept_map 的 lv1/lv2 数据）
    保留排名最高的作为主板块名，其余作为子板块显示在括号内。
    """
    if not ranked_sectors:
        return ranked_sectors

    hierarchy_data = _load_sector_hierarchy()
    c2c = hierarchy_data.get('concept_to_category', {})

    # 尝试加载行业→股票映射用于计算行业归属
    lv1_stock_sets = {}  # lv1_name -> set of stock codes
    lv2_stock_sets = {}  # lv2_name -> set of stock codes
    try:
        for path in [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stock_industry_concept_map.json'),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'stock_industry_concept_map.json'),
        ]:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    ind_data = json.load(f)
                for k, v in ind_data.get('lv1_to_stocks', {}).items():
                    lv1_stock_sets[k] = set(v) if isinstance(v, list) else set()
                for k, v in ind_data.get('lv2_to_stocks', {}).items():
                    lv2_stock_sets[k] = set(v) if isinstance(v, list) else set()
                break
    except Exception:
        pass

    # 为每个板块确定其父级分组key
    def _get_group_key(name, codes):
        """返回 (group_type, group_name) 用于分组。优先级：c2c > theme > lv1 overlap"""

        # 1. _THEME_GROUPS 主题匹配（优先级最高，语义更准确）
        theme = _get_theme(name)
        if theme >= 0:
            group_name = _THEME_GROUPS[theme][0]
            return ('theme', group_name)

        # 2. concept_to_category 一级行业
        parent = _get_parent_of_concept(name, c2c)
        if parent and parent[0]:
            return ('lv1', parent[0])

        # 3. lv1 行业股票重叠（如果板块有成分股且行业数据可用）
        if codes and lv1_stock_sets:
            best_lv1 = None
            best_overlap = 0
            for lv1, lv1_codes in lv1_stock_sets.items():
                if not lv1_codes:
                    continue
                overlap = len(codes & lv1_codes)
                # 重叠比例 > 30% 则认为属于该行业
                ratio = overlap / len(codes) if codes else 0
                if ratio > 0.3 and ratio > best_overlap:
                    best_overlap = ratio
                    best_lv1 = lv1
            if best_lv1:
                return ('lv1', best_lv1)

        return None

    # 按分组key分组
    groups = {}  # group_key -> [(idx, name, sd), ...]
    ungrouped = []

    for idx, (name, sd) in enumerate(ranked_sectors):
        codes = sd.get('codes', set())
        key = _get_group_key(name, codes)
        if key:
            groups.setdefault(key, []).append((idx, name, sd))
        else:
            ungrouped.append((idx, name, sd))

    # 构建结果：每组保留排名最高的作为主板块，其余合并
    result = []
    for key, members in groups.items():
        if len(members) <= 1:
            result.append(members[0])
            continue

        # 按原始排名排序
        members.sort(key=lambda x: x[0])
        main_idx, main_name, main_sd = members[0]
        sub_members = members[1:]

        # 合并所有成分股
        all_codes = set(main_sd.get('codes', set()))
        sub_names = []
        total_zt = main_sd.get('zt_count', 0)

        for _, sub_name, sub_sd in sub_members:
            all_codes.update(sub_sd.get('codes', set()))
            clean_name = sub_name.split('(')[0] if '(' in sub_name else sub_name
            sub_names.append(clean_name)
            total_zt += sub_sd.get('zt_count', 0)

        # 更新主板块数据
        merged_sd = dict(main_sd)
        merged_sd['codes'] = all_codes
        merged_sd['stock_count'] = len(all_codes)
        merged_sd['zt_count'] = total_zt

        # 重新计算加权平均涨幅
        all_pcts = []
        for _, _, sd in members:
            sc = sd.get('stock_count', 1)
            ap = sd.get('avg_pct', 0)
            all_pcts.extend([ap] * max(sc, 1))
        if all_pcts:
            merged_sd['avg_pct'] = sum(all_pcts) / len(all_pcts)

        # 重新计算加权涨幅
        all_wpcts = []
        for _, _, sd in members:
            sc = sd.get('stock_count', 1)
            wp = sd.get('weighted_pct', sd.get('avg_pct', 0))
            all_wpcts.extend([wp] * max(sc, 1))
        if all_wpcts:
            merged_sd['weighted_pct'] = sum(all_wpcts) / len(all_wpcts)

        # 构建显示名
        base_main = main_name.split('(')[0] if '(' in main_name else main_name
        if sub_names:
            unique_subs = list(dict.fromkeys(sub_names))[:3]
            suffix = '含' + ','.join(unique_subs)
            if len(sub_names) > 3:
                suffix += f'等{len(sub_names)}个'
            display_name = f'{base_main}({suffix})'
        else:
            display_name = base_main

        result.append((main_idx, display_name, merged_sd))

    # 添加未分组的板块
    for item in ungrouped:
        result.append(item)

    # 按原始排名排序
    result.sort(key=lambda x: x[0])

    return [(name, sd) for _, name, sd in result]



def _build_industry_ranking(scored, top_n=10):
    """
    按申万一级行业聚合排名。概念/三级行业不独立霸榜。

    一级行业得分 = 下属所有概念/三级行业的成交额加权得分
    二级行业得分 = 下属概念得分的成交额加权
    概念作为子项挂在二级行业下面

    返回: [(lv1_name, {score, avg_pct, zt_count, stock_count, lv2_groups: [{name, score, children: [...]}]})]
    """
    hierarchy_data = _load_sector_hierarchy()
    c2c = hierarchy_data.get('concept_to_category', {})
    ntp = hierarchy_data.get('name_to_parent', {})

    # 按 lv1 → lv2 → concept 三级组织
    lv1_tree = defaultdict(lambda: defaultdict(list))  # {lv1: {lv2: [concept_info]}}
    for sector_name, sd in scored.items():
        cat = c2c.get(sector_name)
        if not cat:
            # 尝试用 name_to_parent 匹配行业名（如 "电子"、"通信设备"）
            base = sector_name.split('(')[0] if '(' in sector_name else sector_name
            if '含' in base:
                base = base.split('含')[0].strip()
            cat = ntp.get(base)
        if not cat or not cat[0]:
            continue
        lv1, lv2 = cat[0], cat[1] if len(cat) >= 2 and cat[1] else cat[0]
        lv1_tree[lv1][lv2].append({
            'name': sector_name,
            'score': sd.get('score', 0),
            'avg_pct': sd.get('avg_pct', 0),
            'wavg_pct': sd.get('wavg_pct', 0),
            'zt_count': sd.get('zt_count', 0),
            'amount': sd.get('amount', 0),  # 亿
            'stock_count': sd.get('stock_count', 0),
            'up_ratio': sd.get('up_ratio', 0),
            'codes': sd.get('codes', set()),
        })

    # 计算一级行业聚合得分
    result = []
    for lv1, lv2_groups in lv1_tree.items():
        all_children = []
        for lv2, concepts in lv2_groups.items():
            all_children.extend(concepts)

        if not all_children:
            continue

        # 一级行业得分 = 成交额加权的概念得分
        total_amt = sum(c['amount'] for c in all_children)
        if total_amt > 0:
            lv1_score = sum(c['score'] * c['amount'] for c in all_children) / total_amt
        else:
            lv1_score = sum(c['score'] for c in all_children) / len(all_children)

        # 成交额加权涨幅
        if total_amt > 0:
            lv1_avg_pct = sum(c['avg_pct'] * c['amount'] for c in all_children) / total_amt
        else:
            lv1_avg_pct = sum(c['avg_pct'] for c in all_children) / len(all_children)

        total_zt = sum(c['zt_count'] for c in all_children)
        total_stocks = len(set().union(*[c['codes'] for c in all_children if c['codes']]))

        # 构建二级行业子分组
        lv2_list = []
        for lv2, concepts in lv2_groups.items():
            concepts.sort(key=lambda x: -x['score'])
            lv2_amt = sum(c['amount'] for c in concepts)
            if lv2_amt > 0:
                lv2_score = sum(c['score'] * c['amount'] for c in concepts) / lv2_amt
                lv2_avg_pct = sum(c['avg_pct'] * c['amount'] for c in concepts) / lv2_amt
            else:
                lv2_score = sum(c['score'] for c in concepts) / len(concepts)
                lv2_avg_pct = sum(c['avg_pct'] for c in concepts) / len(concepts)
            lv2_zt = sum(c['zt_count'] for c in concepts)
            lv2_stocks = len(set().union(*[c['codes'] for c in concepts if c['codes']]))

            lv2_list.append({
                'name': lv2,
                'score': round(lv2_score, 1),
                'avg_pct': round(lv2_avg_pct, 2),
                'zt_count': lv2_zt,
                'stock_count': lv2_stocks,
                'children': [
                    {'name': c['name'], 'score': round(c['score'], 1),
                     'avg_pct': round(c['avg_pct'], 2), 'zt_count': c['zt_count'],
                     'stock_count': c['stock_count']}
                    for c in concepts[:5]
                ],
            })

        lv2_list.sort(key=lambda x: -x['score'])

        result.append((lv1, {
            'name': lv1,
            'score': round(lv1_score, 1),
            'avg_pct': round(lv1_avg_pct, 2),
            'zt_count': total_zt,
            'stock_count': total_stocks,
            'amount': round(total_amt, 2),
            'lv2_count': len(lv2_list),
            'concept_count': len(all_children),
            'lv2_groups': lv2_list,
        }))

    result.sort(key=lambda x: -x[1]['score'])
    return result[:top_n]


def calc_sector_enhanced(rows_today: list[dict], pp: dict, pp_list: list[dict], csv_dir: str | None = None, prev_sec_top5: list | None = None) -> dict:
    """
    全板块强度分析（行业 + 概念，四维评分，相似性去重）。
    替代旧版 calc_sector。
    """
    from leaders import _load_known_codes, _get_parents_of_names, find_sector_leaders, calc_subsector_breakdown
    known_codes = _load_known_codes(csv_dir) if csv_dir else set()
    sectors = _aggregate_all_sectors(rows_today, known_codes)
    scored = _score_all_sectors(sectors)

    # 排名 + 相似性去重（全板块排序后取 TOP5）
    ranked = sorted(scored.items(), key=lambda x: x[1]['score'], reverse=True)
    deduped = _dedup_by_similarity(ranked)
    deduped = _aggregate_related_concepts(deduped)  # 相关概念聚合（含覆铜板等）
    deduped = _merge_small_sectors(deduped)  # 剩余小概念板块合并/过滤
    deduped = _merge_by_parent(deduped)  # 同父级行业合并（仿制药+医药电商+流感→医药生物）
    # 合并后需要重新排序（合并可能改变了成分股数量和分数）
    deduped = sorted(deduped, key=lambda x: x[1]['score'], reverse=True)
    top5 = deduped[:5]

    # ── 一超多强判定（已迁移至concentration信号，此处占位）──
    yc = ''  # 由 review_new.py 的 mainline_info['signal'] 覆盖

    # ── 涨停集中度 ──
    total_zt = sum(st['zt_count'] for st in scored.values())
    top3_zt = sum(top5[i][1]['zt_count'] for i in range(min(3, len(top5))))
    conc = top3_zt / max(total_zt, 1) * 100
    active = sum(1 for st in scored.values() if st['zt_count'] > 0)
    if conc >= 60:
        xt = '集中'
    elif conc >= 40:
        xt = '较集中'
    else:
        xt = f'散乱（涨停分散在{active}个板块）'

    # ── 主线持续性（含父级维度）──
    mainline_check = None
    parent_rotation = ''  # 父级散乱类型
    if pp_list:
        prev_top5_names = prev_sec_top5 or []
        if prev_top5_names and top5:
            prev_set = set(prev_top5_names)
            today_set = {s for s, _ in top5}
            overlap = prev_set & today_set
            
            # 父级维度检测
            h_data = _load_sector_hierarchy()
            c2c = h_data.get('concept_to_category', {})
            
            prev_parents = _get_parents_of_names(prev_top5_names, c2c)
            today_parents = _get_parents_of_names([s for s, _ in top5], c2c)
            parent_overlap = prev_parents & today_parents
            
            if len(overlap) >= 3:
                mainline_check = f'持续性: ✅ 概念级{len(overlap)}个持续 ({", ".join(list(overlap)[:3])})'
            elif len(overlap) >= 1:
                mainline_check = f'持续性: ⚠️ 概念级{len(overlap)}个持续 ({", ".join(list(overlap)[:2])})'
            else:
                mainline_check = '持续性: ❌ 概念级全部散乱'
            
            # 父级维度判断
            if len(parent_overlap) >= 2:
                if len(overlap) < 2:
                    parent_rotation = '父级内散乱（主线延续，子板块切换）'
                    mainline_check += f' | 但父级{"/".join(parent_overlap)}仍在，子板块切换'
                else:
                    parent_rotation = '父级+概念双持续（强主线）'
            elif len(parent_overlap) >= 1:
                parent_rotation = f'父级部分持续({"/".join(parent_overlap)})'
                mainline_check += f' | 父级部分持续({"/".join(parent_overlap)})'
            else:
                parent_rotation = '父级间散乱（主线切换）'
                mainline_check += f' | ⚠️ 父级全部切换({"/".join(prev_parents)}→{"/".join(today_parents)})'

    # ── TOP3 板块龙头 ──
    top3_leaders = {}
    for sec_name, sd in top5[:3]:
        codes = sd.get('codes', set())
        top3_leaders[sec_name] = find_sector_leaders(sec_name, rows_today, pp_list, sector_codes=codes)

    # ── 细分板块分析（TOP1 行业板块的概念拆分）──
    subsector = {}
    for sec_name, sd in top5[:3]:
        if not sd.get('is_concept'):
            breakdown = calc_subsector_breakdown(rows_today, sec_name)
            if breakdown:
                subsector[sec_name] = breakdown

    # 保存 top5 名称供次日持续性判断
    sec_top5_names = [s for s, _ in top5]

    # ── 散乱行情低吸推荐板块 ──
    # 找出前几日TOP5中今日仍在活跃且量级较高的板块（排除一日游）
    rotation_suggestions = []
    all_prev_top = set()
    if prev_sec_top5:
        all_prev_top.update(prev_sec_top5)
    if all_prev_top:
        # 前几日曾是TOP5，今日仍在全板块中且有涨停+正涨幅+资金强度高
        for sec_name in all_prev_top:
            sd = scored.get(sec_name)
            if not sd:
                continue
            if sd['zt_count'] <= 0 or sd['avg_pct'] <= 0:
                continue
            # 资金强度：从detail中获取
            detail = sd.get('detail', {})
            cap_score = detail.get('score_cap', 0)
            if cap_score < 10:  # 资金强度不够（满分25）
                continue
            rotation_suggestions.append((sec_name, {
                'avg_pct': round(sd['avg_pct'], 1),
                'zt_count': sd['zt_count'],
                'cap_score': round(cap_score, 1),
                'stock_count': sd.get('stock_count', len(sd.get('codes', set()))),
            }))
        rotation_suggestions.sort(key=lambda x: x[1]['avg_pct'], reverse=True)
        rotation_suggestions = rotation_suggestions[:5]

    parent_sectors = _build_parent_sectors(scored, top5)
    parent_conc, parent_labels, parent_conc_detail = _calc_parent_concentration(top5, parent_sectors)
    industry_top = _build_industry_ranking(scored, top_n=10)

    return {
        'yichao': yc,
        'mainline_check': mainline_check,
        'parent_rotation': parent_rotation,
        'xtype': xt,
        'concentration': conc,
        'top5': top5,
        'total_zt': total_zt,
        'top3_leaders': top3_leaders,
        'subsector': subsector,
        'total_sectors': len(scored),
        'sec_top5_names': sec_top5_names,
        'rotation_suggestions': rotation_suggestions,
        'parent_sectors': parent_sectors[:10],
        'parent_conc': parent_conc,
        'parent_labels': parent_labels,
        'parent_conc_detail': parent_conc_detail,
        'industry_top': industry_top,
    }


# ════════════════════════════════════════════════════════
# 数据预处理（一次性分类+聚合，避免重复遍历）
# ════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════
# 主线板块状态管理 v3.5
# ════════════════════════════════════════════════════════


