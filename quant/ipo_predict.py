"""新股预测引擎 — 上市前预测 + 优质/炒作指数 + 风险分区

数据源: 东财F10 (CompanySurvey发行信息 + OperationsRequired财务/题材/板块)
输出: ipo_research.db 的 ipo_predictions 表
"""
import os, sys, json, time, logging, requests
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("ipo_predict")

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from config.ipo_predict_rules import *
from quant.ipo_research_db import init_db, upsert_prediction, get_prediction

REQUEST_TIMEOUT = 15


# ═══════════════════════════════════════════════════
# 数据抓取层
# ═══════════════════════════════════════════════════

def _fetch_json(url, retries=2):
    for i in range(retries + 1):
        try:
            r = requests.get(url, headers=F10_HEADERS, timeout=REQUEST_TIMEOUT)
            return r.json()
        except Exception as e:
            if i < retries:
                time.sleep(1)
            else:
                logger.warning("fetch failed %s: %s" % (url[:80], e))
                return None


def fetch_company_survey(code):
    """F10公司概况 → 基本资料(jbzl) + 发行相关(fxxg)"""
    prefix = code_to_em_prefix(code)
    url = f"{F10_BASE}/CompanySurvey/PageAjax?code={prefix}"
    d = _fetch_json(url)
    if not d:
        return None, None
    jbzl = d.get('jbzl', [])
    fxxg = d.get('fxxg', [])
    return (jbzl[0] if jbzl else None), (fxxg[0] if fxxg else None)


def fetch_operations_required(code):
    """F10经营分析 → 财务指标(zxzb) + 所属板块(ssbk) + 核心题材(hxtc) + 业绩预测(yctj)"""
    prefix = code_to_em_prefix(code)
    url = f"{F10_BASE}/OperationsRequired/PageAjax?code={prefix}"
    d = _fetch_json(url)
    if not d:
        return {}
    return {
        'zxzb': d.get('zxzb', []),
        'zxzbOther': d.get('zxzbOther', []) or (d.get('zxzbOther')[0] if isinstance(d.get('zxzbOther'), list) and d.get('zxzbOther') else {}),
        'ssbk': d.get('ssbk', []),
        'hxtc': d.get('hxtc', []),
        'yctj_chart': d.get('yctj_chart', []),
        'zxzbhq': d.get('zxzbhq', {}),
    }


def fetch_upcoming_ipos(days_ahead=10):
    """获取即将上市的新股列表 (优先akshare同花顺, fallback东财datacenter)

    Returns: list of {'code', 'name', 'list_date', 'issue_price', 'issue_pe', 'industry_pe'}
    """
    results = []
    today = datetime.now().date()
    cutoff = today + timedelta(days=days_ahead)

    # 方案1: akshare同花顺新股数据 (优先)
    try:
        import akshare as ak
        df = ak.stock_ipo_ths()
        if df is not None and len(df) > 0:
            for _, row in df.iterrows():
                code = str(row.get('股票代码', '')).strip()
                name = str(row.get('股票简称', '')).strip()
                list_date_str = str(row.get('上市日期', '')).strip() if row.get('上市日期') else ''
                if not code or not list_date_str or list_date_str == '-':
                    continue
                try:
                    if len(list_date_str) <= 5:  # MM-DD格式
                        ld = datetime.strptime('2026-' + list_date_str, '%Y-%m-%d').date()
                    else:
                        ld = datetime.strptime(list_date_str[:10], '%Y-%m-%d').date()
                except Exception:
                    continue
                if today <= ld <= cutoff:
                    issue_price = row.get('发行价格', 0)
                    issue_pe = row.get('发行市盈率', 0)
                    industry_pe = row.get('行业市盈率', 0)
                    try:
                        issue_price = float(issue_price) if issue_price and issue_price != '-' else 0
                    except Exception:
                        issue_price = 0
                    try:
                        issue_pe = float(issue_pe) if issue_pe and issue_pe != '-' else 0
                    except Exception:
                        issue_pe = 0
                    try:
                        industry_pe = float(industry_pe) if industry_pe and industry_pe != '-' else 0
                    except Exception:
                        industry_pe = 0
                    results.append({
                        'code': code, 'name': name, 'list_date': ld.strftime('%Y-%m-%d'),
                        'issue_price': issue_price, 'issue_pe': issue_pe, 'industry_pe': industry_pe
                    })
            if results:
                logger.info("从akshare同花顺获取到 %d 只即将上市新股" % len(results))
    except Exception as e:
        logger.warning("akshare获取新股列表失败: %s" % str(e)[:100])

    # 方案2: 东财datacenter (fallback)
    if not results:
        report_names = [
            'RPT_WEB_IPO_XGSG_LSB', 'RPTA_WEB_IPO_XGSG_LSB',
            'RPT_WEB_IPO_NQSG_LSB', 'RPTA_WEB_IPO_NQSG_LSB', 'RPT_WEB_IPO_LIST',
        ]
        for rn in report_names:
            url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
                   "?reportName=%s&columns=SECURITY_CODE,SECURITY_NAME_ABBR,LISTING_DATE,ISSUE_PRICE"
                   "&pageSize=50&sortColumns=LISTING_DATE&sortTypes=-1&source=WEB&client=WEB" % rn)
            d = _fetch_json(url)
            if d and d.get('success') and d.get('result', {}).get('data'):
                for item in d['result']['data']:
                    code = str(item.get('SECURITY_CODE', ''))
                    name = item.get('SECURITY_NAME_ABBR', '')
                    list_date_str = item.get('LISTING_DATE', '')
                    if not code or not list_date_str:
                        continue
                    try:
                        ld = datetime.strptime(list_date_str[:10], '%Y-%m-%d').date()
                    except Exception:
                        continue
                    if today <= ld <= cutoff:
                        results.append({'code': code, 'name': name, 'list_date': list_date_str[:10],
                                       'issue_price': 0, 'issue_pe': 0, 'industry_pe': 0})
                if results:
                    logger.info("从东财 %s 获取到 %d 只即将上市新股" % (rn, len(results)))
                    break

    if not results:
        logger.warning("未能自动获取新股列表, 需手动指定code")

    # 去重
    seen = set()
    unique = []
    for r in results:
        if r['code'] not in seen:
            seen.add(r['code'])
            unique.append(r)
    return unique


# ═══════════════════════════════════════════════════
# 数据解析层
# ═══════════════════════════════════════════════════

def _safe_float(v, default=0.0):
    try:
        if v is None or v == '' or v == '--':
            return default
        return float(v)
    except (ValueError, TypeError):
        return default


def parse_issue_data(jbzl, fxxg):
    """解析发行数据 → 标准化字典"""
    if not fxxg:
        return {}
    result = {}
    result['name'] = (jbzl or {}).get('SECURITY_NAME_ABBR', '')
    result['security_type'] = (jbzl or {}).get('SECURITY_TYPE', '')
    result['industry_em'] = (jbzl or {}).get('EM2016', '')  # 东财行业
    result['industry_csrc'] = (jbzl or {}).get('INDUSTRYCSRC1', '')  # 证监会行业
    result['org_profile'] = (jbzl or {}).get('ORG_PROFILE', '') or ''
    result['org_name'] = (jbzl or {}).get('ORG_NAME', '') or ''
    result['business_scope'] = (jbzl or {}).get('BUSINESS_SCOPE', '') or ''

    # 注册资本(万元) → 总股本(股) = REG_CAPITAL * 10000 (面值1元)
    # F10的注册资本通常已更新为IPO后总股本(含发行股数), 直接使用
    reg_capital = _safe_float((jbzl or {}).get('REG_CAPITAL'), 0)
    result['total_shares'] = reg_capital * 10000  # 股
    result['total_shares_yi'] = result['total_shares'] / 1e8  # 亿股

    result['list_date'] = str(fxxg.get('LISTING_DATE', ''))[:10]
    result['issue_price'] = _safe_float(fxxg.get('ISSUE_PRICE'))
    result['issue_pe'] = _safe_float(fxxg.get('AFTER_ISSUE_PE'))
    result['total_issue_num'] = _safe_float(fxxg.get('TOTAL_ISSUE_NUM'))  # 股
    result['total_funds'] = _safe_float(fxxg.get('TOTAL_FUNDS'))  # 元, 实际募资总额
    result['net_raise_funds'] = _safe_float(fxxg.get('NET_RAISE_FUNDS'))  # 元, 净募资
    result['issue_fee'] = _safe_float(fxxg.get('DEC_SUMISSUEFEE'))  # 发行费用
    result['online_lwr'] = _safe_float(fxxg.get('ONLINE_ISSUE_LWR'))  # 网上中签率
    result['offline_vap_ratio'] = _safe_float(fxxg.get('OFFLINE_VAP_RATIO'))  # 网下配售比例
    result['issue_way'] = fxxg.get('ISSUE_WAY', '')

    return result


def parse_financials(zxzb_list, yctj_list=None):
    """解析财务数据

    zxzb: 最新一期主要指标 (只有1条, 如2026半年报)
    yctj_chart: 年度业绩数据 (年报实际/预测, 字段名带下划线)
    """
    financials = {}

    # ── 1. 最新一期 (zxzb[0], 如2026H1) ──
    if zxzb_list:
        latest = zxzb_list[0]
        rd = str(latest.get('REPORT_DATE', ''))[:10]
        financials['latest_report_date'] = rd
        financials['latest_report_type'] = str(latest.get('REPORT_TYPE', ''))

        # 营收
        financials['latest_revenue'] = _safe_float(latest.get('TOTAL_OPERATEINCOME'))
        financials['latest_revenue_last'] = _safe_float(latest.get('TOTAL_OPERATEINCOME_LAST'))
        # 营收同比增速 (优先用_TZ字段, 否则计算)
        rev_tz = _safe_float(latest.get('TOTALOPERATEREVETZ'))
        if rev_tz > 0 and financials['latest_revenue_last'] > 0:
            financials['latest_revenue_growth'] = rev_tz
        elif financials['latest_revenue_last'] > 0:
            financials['latest_revenue_growth'] = round(
                (financials['latest_revenue'] - financials['latest_revenue_last']) / financials['latest_revenue_last'] * 100, 2)

        # 归母净利
        financials['latest_profit'] = _safe_float(latest.get('PARENT_NETPROFIT'))
        financials['latest_profit_last'] = _safe_float(latest.get('PARENT_NETPROFIT_LAST'))
        profit_tz = _safe_float(latest.get('PARENTNETPROFITTZ'))
        if profit_tz > 0 and financials['latest_profit_last'] > 0:
            financials['latest_profit_growth'] = profit_tz
        elif financials['latest_profit_last'] > 0:
            financials['latest_profit_growth'] = round(
                (financials['latest_profit'] - financials['latest_profit_last']) / financials['latest_profit_last'] * 100, 2)

        # 盈利能力
        financials['latest_gross_margin'] = _safe_float(latest.get('XSMLL'))
        financials['latest_roe'] = _safe_float(latest.get('ROEJQ'))

        # 精确股本 (东财F10直接给)
        financials['total_shares_exact'] = _safe_float(latest.get('TOTAL_SHARE'))
        financials['free_shares_exact'] = _safe_float(latest.get('FREE_SHARE'))

    # ── 2. 年度数据 (yctj_chart, 字段名带下划线) ──
    annual = {}
    for item in (yctj_list or []):
        year = str(item.get('YEAR', ''))
        if year and year.isdigit() and int(year) >= 2020:
            annual[year] = item

    for year in ['2023', '2024', '2025']:
        if year in annual:
            item = annual[year]
            financials[f'revenue_{year}'] = _safe_float(item.get('TOTAL_OPERATE_INCOME'))
            financials[f'profit_{year}'] = _safe_float(item.get('PARENT_NETPROFIT'))
            financials[f'eps_{year}'] = _safe_float(item.get('EPS'))
            financials[f'roe_{year}'] = _safe_float(item.get('ROE'))
            financials[f'pe_{year}'] = _safe_float(item.get('PE'))
            # 营收增速
            rev_ratio = _safe_float(item.get('TOTAL_OPERATE_INCOME_RATIO'))
            if rev_ratio:
                financials[f'revenue_growth_{year}'] = rev_ratio
            profit_ratio = _safe_float(item.get('PARENT_NETPROFIT_RATIO'))
            if profit_ratio:
                financials[f'profit_growth_{year}'] = profit_ratio

    # ── 3. 2025年报兜底 (如果yctj没有, 用最新一期推算) ──
    if financials.get('profit_2025', 0) <= 0 and financials.get('latest_profit', 0) > 0:
        rd = financials.get('latest_report_date', '')
        lp = financials['latest_profit']
        if '06-30' in rd:
            financials['profit_2025'] = lp * 1.8  # H1占全年约55%
        elif '09-30' in rd:
            financials['profit_2025'] = lp / 0.78
        elif '03-31' in rd:
            financials['profit_2025'] = lp / 0.25
        else:
            financials['profit_2025'] = lp

    # ── 4. 2026E净利预测 ──
    # 修正: 单期增速(如H1同比)不能直接全年化, 取年度增速与最新增速较低者再打8折, 封顶50%
    profit_2025 = financials.get('profit_2025', 0)
    growth = financials.get('latest_profit_growth', 0) or 0
    annual_growth = financials.get('profit_growth_2025', 0) or 0
    candidates = [g for g in (growth, annual_growth) if g and g > 0]
    if candidates:
        growth_rate = min(candidates) * 0.8 / 100
        growth_rate = min(growth_rate, 0.50)
        growth_rate = max(growth_rate, 0.05)
    else:
        growth_rate = 0.10
    if profit_2025 > 0:
        financials['profit_2026e'] = round(profit_2025 * (1 + growth_rate), 0)
    else:
        financials['profit_2026e'] = 0

    return financials


def parse_themes(ssbk, hxtc, org_profile):
    """解析题材概念 → 板块列表 + 关键词 + 热度评分"""
    boards = []
    for item in (ssbk or []):
        bn = item.get('BOARD_NAME', '')
        if bn:
            boards.append(bn)

    keywords = []
    for item in (hxtc or []):
        kw = item.get('KEYWORD', '')
        mp = item.get('MAINPOINT', '')
        if kw:
            keywords.append(str(kw))
        if mp:
            keywords.append(str(mp))

    # 题材关键词只从所属板块(ssbk)和核心题材(hxtc KEYWORD)匹配
    # 不从org_profile匹配，避免"黄金机遇期"、"半导体应用"等成语/上下文误判
    theme_text = ' '.join(str(b) for b in boards) + ' ' + ' '.join(str(k) for k in keywords)
    all_text = theme_text + ' ' + (org_profile or '')  # all_text保留完整文本供其他用途

    # 易误判词排除规则：这些词在特定上下文中不算题材
    EXCLUDE_PATTERNS = {
        '黄金': ['黄金机遇', '黄金时代', '黄金十年', '黄金期', '黄金时间', '黄金档', '黄金周', '黄金分割', '黄金比例'],
        '半导体': [],  # 半导体本身是 valid 题材，但如果只在"应用于半导体"上下文出现需排除
    }

    # 匹配热门题材关键词
    hot_hits = []
    for kw in THEME_HOT_KEYWORDS:
        if kw.lower() in theme_text.lower():
            # 检查排除规则
            excluded = False
            if kw in EXCLUDE_PATTERNS:
                for pattern in EXCLUDE_PATTERNS[kw]:
                    if pattern in theme_text:
                        excluded = True
                        break
            if not excluded:
                hot_hits.append(kw)

    # 从org_profile补充强信号题材词 (公司简介明确写出的核心赛道, 如AI散热/光模块)
    org_text = org_profile or ''
    for kw in ORG_PROFILE_THEME_KEYWORDS:
        if kw.lower() in org_text.lower() and kw not in hot_hits:
            hot_hits.append(kw)

    return {
        'boards': boards,
        'keywords': keywords,
        'hot_hits': hot_hits,
        'all_text': all_text,
        'theme_text': theme_text,
    }


# ═══════════════════════════════════════════════════
# 评分引擎
# ═══════════════════════════════════════════════════

def _clamp_score(s, lo=0.5, hi=5.0):
    return max(lo, min(hi, s))


def compute_quality_index(issue, financials, themes):
    """优质指数 (0-5): 业绩增速30% + 盈利能力25% + 行业地位20% + 客户质量15% + 可持续性10%"""
    detail = {}

    # 1. 业绩增速 (30%)
    growth_2025 = financials.get('revenue_growth_2025', financials.get('revenue_growth_2024', 0))
    latest_growth = financials.get('latest_revenue_growth', 0)
    avg_growth = (growth_2025 + latest_growth) / 2 if (growth_2025 or latest_growth) else 0
    if avg_growth >= 30:
        growth_score = 5.0
    elif avg_growth >= 20:
        growth_score = 4.5
    elif avg_growth >= 10:
        growth_score = 3.5
    elif avg_growth >= 0:
        growth_score = 2.5
    else:
        growth_score = 1.5
    detail['growth'] = {'score': growth_score, 'growth_2025': growth_2025, 'latest_growth': latest_growth}

    # 2. 盈利能力 (25%) - 优先用最新一期, fallback年报
    gross_margin = financials.get('latest_gross_margin', financials.get('gross_margin_2025', 0))
    roe = financials.get('latest_roe', financials.get('roe_2025', 0))
    net_margin = 0
    if financials.get('latest_revenue', 0) > 0:
        net_margin = financials.get('latest_profit', 0) / financials['latest_revenue'] * 100
    profit_score = 2.5
    if gross_margin >= 50 or roe >= 20:
        profit_score = 5.0
    elif gross_margin >= 35 or roe >= 15:
        profit_score = 4.0
    elif gross_margin >= 25 or roe >= 10:
        profit_score = 3.0
    elif gross_margin >= 15 or roe >= 5:
        profit_score = 2.0
    detail['profitability'] = {'score': profit_score, 'gross_margin': gross_margin, 'roe': roe, 'net_margin': net_margin}

    # 3. 行业地位 (20%)
    all_text = themes.get('all_text', '')
    leader_hits = [kw for kw in INDUSTRY_LEADER_KEYWORDS if kw in all_text]
    if len(leader_hits) >= 2:
        position_score = 5.0
    elif len(leader_hits) == 1:
        position_score = 3.5
    else:
        position_score = 2.0
    detail['industry_position'] = {'score': position_score, 'hits': leader_hits}

    # 4. 客户质量 (15%)
    customer_hits = [kw for kw in QUALITY_CUSTOMER_KEYWORDS if kw in all_text]
    # 外销比例
    export_ratio = 0
    if '外销' in all_text or '出口' in all_text or '海外' in all_text:
        export_ratio = 1
    if len(customer_hits) >= 2 or (len(customer_hits) >= 1 and export_ratio):
        customer_score = 4.5
    elif len(customer_hits) == 1:
        customer_score = 3.5
    elif export_ratio:
        customer_score = 3.0
    else:
        customer_score = 2.0
    detail['customer_quality'] = {'score': customer_score, 'hits': customer_hits, 'export': bool(export_ratio)}

    # 5. 增速可持续性 (10%)
    sustain_score = 2.5
    if latest_growth > 0 and financials.get('profit_2026e', 0) > financials.get('profit_2025', 0):
        sustain_score = 4.0
    elif latest_growth > 0:
        sustain_score = 3.0
    detail['sustainability'] = {'score': sustain_score, 'latest_growth': latest_growth}

    # 加权汇总
    w = QUALITY_WEIGHTS
    total = (growth_score * w['growth'] + profit_score * w['profitability'] +
             position_score * w['industry_position'] + customer_score * w['customer_quality'] +
             sustain_score * w['sustainability'])
    total = _clamp_score(round(total, 1))
    detail['total'] = total
    return total, detail


def compute_hype_index(issue, themes, board, float_mcap_yi):
    """炒作指数 (0-5): 题材热度40% + 板块情绪25% + 流通盘大小20% + 市场情绪15%"""
    detail = {}

    # 1. 题材热度 (40%)
    hot_hits = themes.get('hot_hits', [])
    num_boards = len(themes.get('boards', []))
    if len(hot_hits) >= 3 or num_boards >= 8:
        theme_score = 5.0
    elif len(hot_hits) >= 2 or num_boards >= 5:
        theme_score = 4.0
    elif len(hot_hits) >= 1 or num_boards >= 3:
        theme_score = 3.0
    else:
        theme_score = 2.0
    detail['theme_heat'] = {'score': theme_score, 'hot_hits': hot_hits, 'num_boards': num_boards}

    # 2. 板块情绪 (25%) - P0用板块+行业热度估算, P1可接入实时板块数据
    sector_score = 3.0
    industry = issue.get('industry_em', '')
    # 北交所近期情绪强
    if board == 'bj':
        sector_score = 4.0
    # 热门行业加分
    hot_industries = ['半导体', '电子', 'AI', '人工智能', '军工', '航天', '新能源', '创新药', '机器人', '钛', '有色金属']
    if any(hi in industry for hi in hot_industries):
        sector_score = max(sector_score, 3.5)
    # 传统行业减分
    cold_industries = ['化工', '纺织', '建材', '钢铁', '煤炭', '银行', '房地产']
    if any(ci in industry for ci in cold_industries) and board != 'bj':
        sector_score = min(sector_score, 2.5)
    detail['sector_sentiment'] = {'score': sector_score, 'industry': industry, 'board': board}

    # 3. 流通盘大小 (20%) - 越小越易炒作
    if float_mcap_yi <= 0:
        float_score = 3.0
    elif float_mcap_yi < 5:
        float_score = 5.0
    elif float_mcap_yi < 10:
        float_score = 4.5
    elif float_mcap_yi < 20:
        float_score = 4.0
    elif float_mcap_yi < 40:
        float_score = 3.0
    elif float_mcap_yi < 60:
        float_score = 2.0
    else:
        float_score = 1.0
    detail['float_size'] = {'score': float_score, 'float_mcap_yi': round(float_mcap_yi, 2)}

    # 4. 市场情绪 (15%) - P0默认中性, P1可接入大盘/新股赚钱效应
    market_score = 3.0
    detail['market_sentiment'] = {'score': market_score, 'note': 'P0默认中性, 待接入实时情绪'}

    # 加权汇总
    w = HYPE_WEIGHTS
    total = (theme_score * w['theme_heat'] + sector_score * w['sector_sentiment'] +
             float_score * w['float_size'] + market_score * w['market_sentiment'])
    total = _clamp_score(round(total, 1))
    detail['total'] = total
    return total, detail


# ═══════════════════════════════════════════════════
# 估值与风险分区
# ═══════════════════════════════════════════════════

def compute_prediction_zones(issue, financials, quality_index, hype_index, board,
                             industry_pe_override=None, issue_pe_override=None, sentiment=None):
    """计算合理市值、预测开盘价、风险分区、中长线目标

    industry_pe_override: 外部真实行业PE(akshare同花顺), 优先于静态字典
    issue_pe_override: 外部真实发行PE
    sentiment: 情绪模块 {score, coef, label}, 用于预测开盘价情绪校准
    """
    issue_price = issue.get('issue_price', 0)
    total_shares = issue.get('total_shares', 0)  # 股
    total_shares_yi = total_shares / 1e8

    # 可比PE: 优先外部真实行业PE → 静态字典 → 发行PE×1.5兜底
    industry = issue.get('industry_em', '')
    industry_pe = 0
    if industry_pe_override and industry_pe_override > 0:
        industry_pe = industry_pe_override
    else:
        for ind_name, pe in INDUSTRY_PE_BASELINE.items():
            if ind_name in industry:
                industry_pe = pe
                break
    if industry_pe == 0:
        industry_pe = 25  # 默认
    issue_pe = issue_pe_override if (issue_pe_override and issue_pe_override > 0) else issue.get('issue_pe', 0)
    if industry_pe <= 0:
        # 行业PE获取失败时，用发行PE×1.5兜底（新股上市通常有估值溢价）
        industry_pe = issue_pe * 1.5 if issue_pe > 0 else 25
    # 静态字典PE偏低时，用发行PE×1.3兜底（避免低PE行业被低估）
    if issue_pe > 0 and industry_pe < issue_pe * 1.2:
        industry_pe = issue_pe * 1.3
    # 行业PE合理性校验: 行业PE异常高于发行PE(>2.5倍)时压缩到2.5倍
    # (如电子行业均值被AI龙头拉高到70+, 但公司本质是材料/配套, 不可线性套用)
    if issue_pe > 0 and industry_pe > issue_pe * 2.5:
        industry_pe = issue_pe * 2.5

    # 板块PE折价：北交所流动性差，行业PE×0.75（沪深高估值公司拉高了行业平均）
    if board == 'bj':
        industry_pe = industry_pe * 0.75
    # 真正传统行业PE上限（只对低附加值传统行业，不对机械设备/仪器仪表/汽车等高端制造）
    true_traditional_kw = ['纺织', '服装', '家具', '造纸', '印刷', '包装', '食品加工',
                            '零售', '百货', '超市', '餐饮', '酒店', '旅游', '地产', '建筑',
                            '建材', '钢铁', '煤炭', '化工原料', '塑料', '橡胶', '玻璃', '水泥',
                            '种植业', '渔业', '畜牧业', '林业']
    industry_text = (issue.get('industry_em') or '') + ' ' + (issue.get('org_profile') or '')
    if any(kw in industry_text for kw in true_traditional_kw):
        industry_pe = min(industry_pe, 25)  # 低附加值传统行业PE不超过25倍

    # 题材可比PE: 热门题材用题材PE替代表面行业PE（学习博主：天博汽配表面PE22倍，AI液冷可比PE50倍）
    theme_text = (issue.get('theme_concept') or '') + ' ' + (issue.get('name') or '')
    theme_pe = 0
    theme_hit = ''
    for theme, pe in THEME_PE_MAP.items():
        if theme.lower() in theme_text.lower():
            if pe > theme_pe:
                theme_pe = pe
                theme_hit = theme
    # 题材可比PE: 行业PE为主，题材PE只取15%溢价（题材只能给加分，不能主导定价）
    # 下游应用领域不算核心题材，最多给15%溢价
    if theme_pe > 0 and theme_pe > industry_pe:
        comp_pe = industry_pe + (theme_pe - industry_pe) * 0.15
    else:
        comp_pe = industry_pe

    # 2026E归母净利
    profit_2026e = financials.get('profit_2026e', 0)
    profit_2025 = financials.get('profit_2025', 0)
    if profit_2026e <= 0 and profit_2025 > 0:
        profit_2026e = profit_2025 * 1.1

    # 流通盘估算：优先用发行数量（issue_shares），其次用总股本×板块流通比例
    float_mcap_yi = issue.get('float_mcap_yi', 0)
    if float_mcap_yi <= 0 and issue_price > 0:
        issue_shares = issue.get('issue_shares', 0) or issue.get('online_issue', 0)
        if issue_shares > 0:
            # 用发行数量估算流通市值（科创板/创业板新股上市首日实际流通盘≈发行数量）
            float_mcap_yi = issue_shares * issue_price / 1e8
        elif total_shares > 0:
            from config.ipo_predict_rules import FLOAT_SHARES_RATIO
            float_ratio = FLOAT_SHARES_RATIO.get(board, 0.75)
            float_shares_est = total_shares * float_ratio
            float_mcap_yi = float_shares_est * issue_price / 1e8

    # 估值方法判断：亏损股自动切换PS估值
    valuation_method = 'PE'
    industry_ps = 0
    if profit_2026e <= 0 and profit_2025 <= 0:
        valuation_method = 'PS'
        # 用PS估值：合理市值 = 行业PS × 营收
        revenue_2025 = financials.get('revenue_2025', 0)
        latest_revenue = financials.get('latest_revenue', 0)
        revenue = revenue_2025 if revenue_2025 > 0 else latest_revenue
        if revenue <= 0:
            revenue = issue_price * total_shares / 10  # 兜底：用发行市值/10估算营收
        industry_text = (issue.get('industry_em') or '') + ' ' + (issue.get('org_profile') or '') + ' ' + (issue.get('theme_concept') or '')
        industry_ps = get_industry_ps(industry_text)
        # 题材PS溢价分级：顶级题材+80%，热门+40%，一般+20%
        theme_text = (issue.get('theme_concept') or '') + ' ' + (issue.get('org_profile') or '') + ' ' + (issue.get('name') or '')
        ps_premium = get_theme_ps_premium(theme_text)
        # 营收增速溢价：高增速公司PS更高
        revenue_growth = financials.get('revenue_growth_2025', 0) or financials.get('latest_revenue_growth', 0)
        growth_premium = 0
        if revenue_growth > 50:
            growth_premium = 0.20
        elif revenue_growth > 30:
            growth_premium = 0.10
        # 稀缺性溢价：AI芯片/人形机器人/商业航天等稀缺标的
        scarcity_premium = 0
        scarcity_keywords = ['AI芯片', '云端AI', '大模型芯片', 'GPU', '人形机器人', '商业航天',
                              '低空经济', 'eVTOL', '可控核聚变', '量子计算', '脑机接口', '6G']
        if any(kw in industry_text for kw in scarcity_keywords):
            scarcity_premium = 0.80  # 稀缺标的+80%（AI芯片等顶级稀缺赛道）
        # 发展前景溢价：高景气行业
        prospect_premium = 0
        prospect_keywords = ['人工智能', 'AI', '半导体', '芯片', '集成电路', '新能源', '储能',
                              '创新药', '生物医药', '机器人', '航天', '低空经济']
        if any(kw in industry_text for kw in prospect_keywords):
            prospect_premium = 0.30  # 高景气行业+30%
        # 行业地位溢价：龙头/第一梯队/领军企业
        position_premium = 0
        org_profile = issue.get('org_profile', '') or ''
        position_keywords = ['龙头', '领军', '第一梯队', '领先企业', '头部企业', '核心供应商',
                              '唯一', '首家', '打破垄断', '国产替代', '四小龙']
        if any(kw in org_profile for kw in position_keywords):
            position_premium = 0.20  # 行业地位高+20%
        # 小流通盘溢价：流通市值小容易炒作（亏损科技股小流通盘溢价更高）
        float_premium = 0
        if float_mcap_yi > 0:
            if float_mcap_yi < 30:
                float_premium = 0.60  # 极小流通盘+60%
            elif float_mcap_yi < 50:
                float_premium = 0.50  # 小流通盘+50%
            elif float_mcap_yi < 100:
                float_premium = 0.30  # 中小流通盘+30%
            elif float_mcap_yi < 200:
                float_premium = 0.15  # 中等流通盘+15%
        total_ps_premium = ps_premium + growth_premium + scarcity_premium + prospect_premium + position_premium + float_premium
        reasonable_mcap = industry_ps * revenue * (1 + total_ps_premium)  # 元
        reasonable_mcap_yi = reasonable_mcap / 1e8  # 亿元
        reasonable_price = reasonable_mcap / total_shares if total_shares > 0 else issue_price
        comp_pe = 0  # 亏损股PE无意义
    else:
        # 合理市值 = 可比PE × 2026E净利
        reasonable_mcap = comp_pe * profit_2026e  # 元
        reasonable_mcap_yi = reasonable_mcap / 1e8  # 亿元
        reasonable_price = reasonable_mcap / total_shares if total_shares > 0 else issue_price

    # 溢价 = 优质溢价 + 炒作溢价
    q_prem = quality_premium(quality_index)
    h_prem = hype_premium(hype_index)
    total_premium = q_prem + h_prem

    bj_discount = 0  # 非北交所默认无折价
    # 北交所流动性折价: 直接在合理价上乘0.75~0.80（北交所流动性远不如沪深）
    if board == 'bj':
        bj_discount = -0.22  # 基准折价22%
        if float_mcap_yi > 0 and float_mcap_yi < 5:
            bj_discount = -0.18  # 小流通盘易炒，折价少一点
        elif float_mcap_yi > 10:
            bj_discount = -0.28  # 大流通盘，折价多一点
        total_premium += bj_discount

    # 情绪校准: 冰点打折 / 亢奋加价 (用情绪系数乘预测开盘价)
    senti_coef = 1.0
    senti_label = ''
    if sentiment and sentiment.get('coef'):
        senti_coef = sentiment['coef']
        senti_label = sentiment.get('label', '')

    # 预测开盘价 = 合理价格 × (1 + 总溢价) × 情绪系数
    # 总溢价 = 优质溢价(加分) + 炒作溢价(加分) + 北交所折价(减分)
    pred_open_price = round(reasonable_price * (1 + total_premium) * senti_coef, 2)
    # 下限保护：盈利股不低于发行价×0.85（新股极少破发）
    # 亏损股不设下限（一级市场高定价的亏损股可能大幅破发）
    if valuation_method == 'PE' and profit_2026e > 0:
        min_open_price = issue_price * 0.85
        if pred_open_price < min_open_price:
            pred_open_price = round(min_open_price, 2)

    # 中长线目标: 去题材溢价，用行业PE/PS计算（题材炒作退潮后回归基本面）
    if valuation_method == 'PS':
        revenue_2025 = financials.get('revenue_2025', 0)
        latest_revenue = financials.get('latest_revenue', 0)
        revenue = revenue_2025 if revenue_2025 > 0 else latest_revenue
        if revenue <= 0:
            revenue = issue_price * total_shares / 10
        midlong_mcap = industry_ps * revenue  # 去题材溢价
    else:
        midlong_mcap = industry_pe * profit_2026e
    midlong_price = midlong_mcap / total_shares if total_shares > 0 else reasonable_price * 0.75

    # 风险分区（收窄：学习博主区间更紧凑，围绕合理价±5-10%）
    low_zone = round(reasonable_price * 0.92, 2)       # 低风险：合理价-8%
    game_low = round(reasonable_price * 0.97, 2)        # 博弈下限：合理价-3%
    game_high = round(reasonable_price * 1.05, 2)       # 博弈上限：合理价+5%
    high_zone = round(reasonable_price * 1.10, 2)       # 高风险：合理价+10%
    midlong_target = round(midlong_price, 2)             # 中长线：去题材溢价

    return {
        'comp_pe': comp_pe,
        'industry_pe': industry_pe,
        'theme_pe': theme_pe,
        'theme_hit': theme_hit,
        'profit_2026e': profit_2026e,
        'valuation_method': valuation_method,
        'industry_ps': industry_ps,
        'reasonable_mcap_yi': round(reasonable_mcap_yi, 2),
        'reasonable_price': round(reasonable_price, 2),
        'quality_premium': q_prem,
        'hype_premium': h_prem,
        'total_premium': total_premium,
        'pred_open_price': pred_open_price,
        'low_zone': low_zone,
        'game_low': game_low,
        'game_high': game_high,
        'high_zone': high_zone,
        'midlong_target': midlong_target,
        'sentiment_coef': senti_coef,
        'sentiment_label': senti_label,
        'bj_discount': bj_discount,
    }


# ═══════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════



# ============================================================
# 基本面四维度评分（上市前定值）
# ============================================================

HOT_INDUSTRY_KEYWORDS = [
    '人工智能', 'AI', '大模型', '算力', '液冷', '服务器', '芯片', '半导体',
    '集成电路', '航天', '火箭', '卫星', '低空经济', 'eVTOL', '无人机',
    '新能源', '储能', '光伏', '风电', '氢能', '动力电池', '固态电池',
    '生物医药', '创新药', '医疗器械', '基因', '细胞治疗', '脑机',
    '机器人', '人形机器人', '工业母机', '高端制造', '精密仪器',
    '量子', '6G', '光模块', 'CPO', '数据中心', '东数西算',
]

SCARCITY_KEYWORDS = [
    '唯一', '独家', '首家', '稀缺', '垄断', '龙头', '第一',
    '铀', '稀土', '黄金', '锂矿', '钴', '镍', '稀有金属',
    '军工', '国防', '导弹', '雷达', '航母', '核潜艇',
    '中字头', '央企', '国资',
]

# 热门题材→可比PE倍数（学习博主：用题材可比PE而非表面行业PE）
THEME_PE_MAP = {
    '液冷': 55, 'AI服务器': 50, '算力': 50, '人工智能': 45, 'AI': 45, '大模型': 50,
    '芯片': 50, '半导体': 45, '集成电路': 45, '光模块': 55, 'CPO': 55,
    '航天': 60, '火箭': 65, '卫星': 55, '低空经济': 50, 'eVTOL': 55, '无人机': 45,
    '机器人': 50, '人形机器人': 55, '工业母机': 45, '高端制造': 40,
    '储能': 40, '新能源': 35, '光伏': 35, '风电': 35, '氢能': 45, '动力电池': 40,
    '生物医药': 45, '创新药': 55, '医疗器械': 40, '基因': 50, '细胞治疗': 55,
    '量子': 60, '6G': 50, '数据中心': 45, '脑机': 60,
    '军工': 50, '国防': 50, '导弹': 55, '雷达': 50,
    '铀': 45, '稀土': 45, '稀有金属': 40,
}

# ── 从org_profile补充的强信号题材词 (公司简介明确写出的核心赛道) ──
ORG_PROFILE_THEME_KEYWORDS = [
    '光模块', 'CPO', '液冷', '散热', '热管理', 'AI芯片', '云端AI', '大模型',
    '算力', '人形机器人', '商业航天', '低空经济', 'eVTOL', '可控核聚变',
    '量子计算', '脑机接口', '6G', '创新药', '减肥药', '固态电池', '数据要素',
    '信创', '国产替代', '军工', '卫星', '半导体设备', '存储', '光刻',
]

LOW_INDUSTRY_KEYWORDS = [
    '纺织', '服装', '家具', '造纸', '印刷', '包装', '食品', '饮料',
    '零售', '百货', '超市', '餐饮', '酒店', '旅游', '地产', '建筑',
    '建材', '钢铁', '煤炭', '化工', '塑料', '橡胶', '玻璃', '水泥',
    '汽车零部件', '汽配', '传统制造', '代工', 'OEM',
]


def compute_fundamental_score(pred):
    """基本面四维度评分（上市前定值，0-100分）
    1. 行业景气度(30%): 十五五重点行业→高分
    2. 营收利润增速(25%): 近2年CAGR或最新增速
    3. 稀缺性(25%): A股独一无二→高分
    4. 控股股东/配售(20%): 国资+机构配售高→高分
    """
    import json as _json
    import re as _re

    theme = (pred.get('theme_concept') or '') + ' ' + (pred.get('name') or '')
    theme_lower = theme.lower()

    # 1. 行业景气度(30%)
    hot_hits = [k for k in HOT_INDUSTRY_KEYWORDS if k.lower() in theme_lower]
    low_hits = [k for k in LOW_INDUSTRY_KEYWORDS if k.lower() in theme_lower]
    if len(hot_hits) >= 3:
        industry_score = 90
    elif len(hot_hits) >= 2:
        industry_score = 80
    elif len(hot_hits) >= 1:
        industry_score = 65
    elif len(low_hits) >= 1:
        industry_score = 35
    else:
        industry_score = 50

    # 2. 营收利润增速(25%)——优先用yctj的同比增速字段，再用绝对值计算
    rev_2024 = pred.get('revenue_2024') or 0
    rev_2025 = pred.get('revenue_2025') or 0
    rev_2026e = pred.get('revenue_2026e') or 0
    prof_2024 = pred.get('profit_2024') or 0
    prof_2025 = pred.get('profit_2025') or 0
    prof_2026e = pred.get('profit_2026e') or 0
    # yctj解析的同比增速字段（parse_financials已存入，但pred里可能没带，从financials_detail取）
    rev_growth_2025 = pred.get('revenue_growth_2025', 0) or 0
    prof_growth_2025 = pred.get('profit_growth_2025', 0) or 0

    avg_growth = 0
    growth_detail = '数据不足'
    if rev_growth_2025 > 0 or prof_growth_2025 > 0:
        # 优先用yctj的同比增速（最可靠）
        rg = rev_growth_2025 if rev_growth_2025 > 0 else (prof_growth_2025 * 0.8 if prof_growth_2025 > 0 else 0)
        pg = prof_growth_2025 if prof_growth_2025 > 0 else (rev_growth_2025 * 0.8 if rev_growth_2025 > 0 else 0)
        avg_growth = (rg + pg) / 2
        growth_detail = f'2025营收+{rg:.1f}% 利润+{pg:.1f}%(yctj)'
    elif rev_2024 and rev_2025 and rev_2024 > 0:
        rev_growth = (rev_2025 - rev_2024) / rev_2024 * 100
        prof_growth = (prof_2025 - prof_2024) / prof_2024 * 100 if prof_2024 and prof_2024 > 0 else rev_growth * 0.8
        avg_growth = (rev_growth + prof_growth) / 2
        growth_detail = f'营收+{rev_growth:.1f}% 利润+{prof_growth:.1f}%'
    elif rev_2025 and rev_2026e and rev_2025 > 0:
        rev_growth = (rev_2026e - rev_2025) / rev_2025 * 100
        prof_growth = (prof_2026e - prof_2025) / prof_2025 * 100 if prof_2025 and prof_2025 > 0 else rev_growth * 0.8
        avg_growth = (rev_growth + prof_growth) / 2
        growth_detail = f'2026E营收+{rev_growth:.1f}% 利润+{prof_growth:.1f}%'

    if avg_growth >= 50:
        growth_score = 90
    elif avg_growth >= 30:
        growth_score = 80
    elif avg_growth >= 15:
        growth_score = 70
    elif avg_growth >= 5:
        growth_score = 60
    elif avg_growth >= -10:
        growth_score = 45
    else:
        growth_score = 30

    # 3. 稀缺性(25%)
    scarcity_hits = [k for k in SCARCITY_KEYWORDS if k.lower() in theme_lower]
    over_raising = (pred.get('over_raising') or '')
    over_raised = '超募' in over_raising or '实际募资' in over_raising
    if len(scarcity_hits) >= 3:
        scarcity_score = 90
    elif len(scarcity_hits) >= 2:
        scarcity_score = 78
    elif len(scarcity_hits) >= 1:
        scarcity_score = 62
    elif over_raised:
        scarcity_score = 55
    else:
        scarcity_score = 40

    # 4. 控股股东/配售(20%)
    demand = (pred.get('demand_heat') or '')
    offline_match = _re.search(r'网下配售比例[：:]?\s*([\d.]+)%', demand)
    offline_ratio = float(offline_match.group(1)) if offline_match else 0
    name = pred.get('name') or ''
    org_name = pred.get('org_name', '') or ''
    org_profile = pred.get('org_profile', '') or ''
    # 国资识别：股票名称关键词 + 公司全称 + 公司简介文本
    state_name_kw = ('中','国','航天','兵器','电子','电科','华润','保利','招商',
                      '中冶','中铁','中建','中交','中粮','中化','中远','中海','中航',
                      '中核','中兵','中船','中车','中电','中邮','中储','中钨','中色',
                      '中盐','中煤')
    state_text_kw = ('国有资产监督管理委员会','国资委','国有独资','国有控股',
                      '地方国有','人民政府','财政厅','财政局','国有资本','国企')
    _cities = ('北京','上海','天津','重庆','广州','深圳','杭州','南京','成都',
               '武汉','西安','济南','青岛','大连','宁波','厦门','苏州','无锡',
               '常州','洛阳','郑州','长沙','合肥','福州','南昌','昆明','贵阳',
               '南宁','兰州','太原','石家庄','沈阳','长春','哈尔滨','呼和浩特')
    is_state = (any(k in name for k in state_name_kw) or
                any(k in org_name for k in state_text_kw) or
                any(k in org_profile for k in state_text_kw) or
                ('集团' in org_name and any(c in org_name for c in _cities)))

    if is_state and offline_ratio >= 0.5:
        controller_score = 85
    elif is_state:
        controller_score = 72
    elif offline_ratio >= 0.8:
        controller_score = 70
    elif offline_ratio >= 0.5:
        controller_score = 60
    elif offline_ratio >= 0.3:
        controller_score = 50
    else:
        controller_score = 40

    # 加权汇总
    total = (industry_score * 0.30 + growth_score * 0.25 +
             scarcity_score * 0.25 + controller_score * 0.20)

    detail = {
        'industry_prosperity': {'score': industry_score, 'weight': 0.30,
            'detail': f'热门赛道{len(hot_hits)}个: {",".join(hot_hits[:3])}; 传统{len(low_hits)}个'},
        'growth': {'score': growth_score, 'weight': 0.25, 'detail': growth_detail},
        'scarcity': {'score': scarcity_score, 'weight': 0.25,
            'detail': f'稀缺关键词{len(scarcity_hits)}个: {",".join(scarcity_hits[:3])}; 超募={over_raised}'},
        'controller_allocation': {'score': controller_score, 'weight': 0.20,
            'detail': f'国资={is_state} 网下配售={offline_ratio}%'},
    }
    return round(total, 1), _json.dumps(detail, ensure_ascii=False)


def generate_prediction(code, list_date_override=None, plan_raise_funds=None,
                         industry_pe_override=None, issue_pe_override=None, sentiment=None):
    """对单只新股生成完整预测 → 存入数据库

    Args:
        code: 股票代码
        list_date_override: 强制指定上市日期 (F10数据缺失时用)
        plan_raise_funds: 计划募资额(元), 用于计算超募比例
    """
    logger.info("开始生成预测: %s" % code)

    # 1. 抓取F10数据
    jbzl, fxxg = fetch_company_survey(code)
    ops = fetch_operations_required(code)

    if not jbzl and not fxxg:
        logger.error("无法获取 %s 的F10数据" % code)
        return None

    # 2. 解析发行数据
    issue = parse_issue_data(jbzl, fxxg)
    if list_date_override:
        issue['list_date'] = list_date_override

    board = code_to_board(code)
    issue['board'] = board

    # 3. 解析财务数据 (zxzb最新一期 + yctj年度数据)
    financials = parse_financials(ops.get('zxzb', []), ops.get('yctj_chart', []))

    # 4. 解析题材
    themes = parse_themes(ops.get('ssbk', []), ops.get('hxtc', []), issue.get('org_profile', ''))

    # 5. 首日流通股 (优先用F10精确值, 否则按板块比例估算)
    total_issue = issue.get('total_issue_num', 0)
    free_shares_exact = financials.get('free_shares_exact', 0)
    if free_shares_exact > 0:
        float_shares = free_shares_exact  # 股, F10给的精确流通股
    else:
        float_ratio = FLOAT_SHARES_RATIO.get(board, 0.75)
        float_shares = total_issue * float_ratio  # 股
    float_shares_wan = float_shares / 1e4  # 万股
    issue_price = issue.get('issue_price', 0)
    issue_pe = issue.get('issue_pe', 0)
    float_mcap = float_shares * issue_price  # 元
    float_mcap_yi = float_mcap / 1e8  # 亿元
    # 总股本 (优先用注册资本推算的IPO后总股本, zxzb的TOTAL_SHARE可能是IPO前)
    total_shares = issue.get('total_shares', 0)
    if total_shares <= 0:
        total_shares = financials.get('total_shares_exact', 0)
        if total_shares > 0:
            issue['total_shares'] = total_shares
            issue['total_shares_yi'] = total_shares / 1e8
    total_mcap_yi = total_shares * issue_price / 1e8

    # 6. 计算优质指数
    quality_index, quality_detail = compute_quality_index(issue, financials, themes)

    # 7. 计算炒作指数
    hype_index, hype_detail = compute_hype_index(issue, themes, board, float_mcap_yi)

    # 8. 计算估值与风险分区 (传入真实行业PE/发行PE/情绪校准)
    issue['float_mcap_yi'] = float_mcap_yi  # 供北交所折价分级
    # 注入题材概念（供题材可比PE使用）——与859行组装逻辑一致
    if isinstance(themes, dict):
        _hot = themes.get('hot_hits', []) or []
        _boards = themes.get('boards', []) or []
        issue['theme_concept'] = ', '.join(_hot[:5]) if _hot else (', '.join(_boards[:3]) if _boards else '')
    elif isinstance(themes, (list, tuple)):
        issue['theme_concept'] = ', '.join([str(t) for t in themes[:5]])
    elif isinstance(themes, str):
        issue['theme_concept'] = themes
    zones = compute_prediction_zones(issue, financials, quality_index, hype_index, board,
                                     industry_pe_override=industry_pe_override,
                                     issue_pe_override=issue_pe_override,
                                     sentiment=sentiment)

    bj_discount = zones.get('bj_discount', 0)

    # 9. 超募情况
    total_funds = issue.get('total_funds', 0)
    over_raising_text = ''
    if plan_raise_funds and plan_raise_funds > 0:
        over_ratio = (total_funds - plan_raise_funds) / plan_raise_funds * 100
        over_raising_text = "实际募资%.2f亿, 计划%.2f亿, 超募%+.1f%%" % (
            total_funds / 1e8, plan_raise_funds / 1e8, over_ratio)
    elif total_funds > 0:
        over_raising_text = "实际募资%.2f亿(计划募资额待补充)" % (total_funds / 1e8)

    # 10. 需求热度
    online_lwr = issue.get('online_lwr', 0)
    demand_text = ''
    if online_lwr > 0:
        demand_text = "网上中签率%.4f%%" % (online_lwr * 100)
    if issue.get('offline_vap_ratio', 0) > 0:
        demand_text += ", 网下配售比例%.4f%%" % (issue['offline_vap_ratio'] * 100)
    if not demand_text:
        demand_text = '待补充'

    # 11. 题材概念
    theme_text = ', '.join(themes.get('hot_hits', [])[:5])
    if not theme_text:
        theme_text = ', '.join(themes.get('boards', [])[:3])
    if not theme_text:
        theme_text = issue.get('industry_em', '')

    # 12. 组装预测记录
    pred = {
        'code': code,
        'name': issue.get('name', ''),
        'list_date': issue.get('list_date', ''),
        'board': board_to_cn(board),
        'issue_price': issue_price,
        'issue_pe': issue.get('issue_pe', 0),
        'industry_pe': zones.get('comp_pe', 0),
        'comp_pe': zones.get('comp_pe', 0),
        'total_shares': round(issue.get('total_shares_yi', 0), 4),
        'float_shares': round(float_shares_wan, 0),
        'float_mcap': round(float_mcap_yi, 2),
        'total_mcap': round(total_mcap_yi, 2),
        'revenue_2023': round(financials.get('revenue_2023', 0) / 1e8, 2),
        'revenue_2024': round(financials.get('revenue_2024', 0) / 1e8, 2),
        'revenue_2025': round(financials.get('revenue_2025', 0) / 1e8, 2),
        'revenue_2026e': round(financials.get('revenue_2026e', 0) / 1e8, 2),
        'profit_2023': round(financials.get('profit_2023', 0) / 1e8, 2),
        'profit_2024': round(financials.get('profit_2024', 0) / 1e8, 2),
        'profit_2025': round(financials.get('profit_2025', 0) / 1e8, 2),
        'profit_2026e': round(zones.get('profit_2026e', 0) / 1e8, 2),
        'quality_index': quality_index,
        'hype_index': hype_index,
        'over_raising': over_raising_text,
        'demand_heat': demand_text,
        'theme_concept': theme_text,
        'org_name': issue.get('org_name', ''),
        'org_profile': issue.get('org_profile', ''),
        'revenue_growth_2025': financials.get('revenue_growth_2025', 0),
        'profit_growth_2025': financials.get('profit_growth_2025', 0),
        'latest_revenue_growth': financials.get('latest_revenue_growth', 0),
        'latest_profit_growth': financials.get('latest_profit_growth', 0),
        'latest_gross_margin': financials.get('latest_gross_margin', 0),
        'latest_roe': financials.get('latest_roe', 0),
        'pred_open_price': zones.get('pred_open_price', 0),
        'pred_reasonable_mcap': zones.get('reasonable_mcap_yi', 0),
        'pred_low_zone': zones.get('low_zone', 0),
        'pred_game_low': zones.get('game_low', 0),
        'pred_game_high': zones.get('game_high', 0),
        'pred_high_zone': zones.get('high_zone', 0),
        'pred_midlong_target': zones.get('midlong_target', 0),
        'quality_detail': quality_detail,
        'hype_detail': hype_detail,
        # 基本面四维度评分（上市前定值）
        'fundamental_score': 0,
        'fundamental_detail': '',
        'prediction_note': "行业PE%d倍(实发PE %.1f), 合理价%.2f元, 溢价%.0f%%(优质%.0f%%+炒作%.0f%%)%s%s" % (
            zones['comp_pe'], issue_pe, zones['reasonable_price'], zones['total_premium'] * 100,
            zones['quality_premium'] * 100, zones['hype_premium'] * 100,
            ', 北交所折价%.0f%%' % (bj_discount * 100) if board == 'bj' else '',
            ' | 情绪%s(%.0f分)校准x%.2f' % (zones.get('sentiment_label',''), sentiment.get('score',0), zones.get('sentiment_coef',1.0)) if sentiment else ''),
    }

    # 12.5 计算基本面四维度评分（定值）
    try:
        _fs, _fd = compute_fundamental_score(pred)
        pred['fundamental_score'] = _fs
        pred['fundamental_detail'] = _fd
    except Exception as _e:
        logger.warning("基本面评分计算失败: %s" % _e)

    # 13. 存库
    upsert_prediction(pred)
    logger.info("预测已保存: %s %s, 优质%.1f 炒作%.1f, 预测开盘%.2f" % (
        code, pred['name'], quality_index, hype_index, pred['pred_open_price']))
    return pred


def run_all(codes=None, days_ahead=10):
    """生成所有即将上市新股的预测

    Args:
        codes: 手动指定股票代码列表 (为None时自动获取即将上市的新股)
        days_ahead: 自动获取时, 未来多少天内上市的新股
    """
    init_db()

    upcoming = fetch_upcoming_ipos(days_ahead)
    if codes is None:
        codes = [s['code'] for s in upcoming]
        logger.info("自动获取到 %d 只即将上市新股: %s" % (len(codes), codes))
    else:
        logger.info("手动指定 %d 只新股, 同时从akshare补充行业PE信息" % len(codes))

    if not codes:
        logger.warning("没有待预测的新股")
        return []

    # 新股情绪校准（全部预测共享当前市场情绪）
    try:
        from quant.ipo_sentiment import calc_sentiment
        sentiment = calc_sentiment()
        if sentiment:
            logger.info("新股情绪: %.1f分(%s), 校准系数x%.2f" % (
                sentiment['score'], sentiment['label'], sentiment['coef']))
        else:
            sentiment = None
    except Exception as e:
        logger.warning("情绪计算失败(跳过情绪校准): %s" % e)
        sentiment = None

    # upcoming信息索引(含真实行业PE/发行PE)
    upcoming_map = {}
    for s in upcoming:
        if isinstance(s, dict):
            upcoming_map[str(s.get('code', ''))] = s

    results = []
    for code in codes:
        try:
            info = upcoming_map.get(str(code), {}) or {}
            pred = generate_prediction(
                code,
                industry_pe_override=info.get('industry_pe') if info else None,
                issue_pe_override=info.get('issue_pe') if info else None,
                sentiment=sentiment)
            if pred:
                results.append(pred)
            time.sleep(0.5)  # 避免请求过快
        except Exception as e:
            logger.error("生成 %s 预测失败: %s" % (code, e), exc_info=True)

    logger.info("完成 %d/%d 只新股预测" % (len(results), len(codes)))
    return results


# ═══════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════

if __name__ == '__main__':
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(description='新股预测引擎')
    parser.add_argument('--codes', nargs='+', help='手动指定股票代码列表')
    parser.add_argument('--days', type=int, default=10, help='自动获取未来N天内上市的新股')
    parser.add_argument('--init-db', action='store_true', help='仅初始化数据库')
    args = parser.parse_args()

    if args.init_db:
        init_db()
        print("DB initialized")
    else:
        results = run_all(codes=args.codes, days_ahead=args.days)
        print("\n=== 预测结果 ===")
        for r in results:
            print("%s %s (%s) 上市:%s | 发行价:%.2f 优质:%.1f 炒作:%.1f | 预测开盘:%.2f 合理市值:%.1f亿 | 低风险:%.2f 博弈:%.2f-%.2f 高风险:%.2f+ 中长线:%.2f" % (
                r['code'], r['name'], r['board'], r['list_date'],
                r['issue_price'], r['quality_index'], r['hype_index'],
                r['pred_open_price'], r['pred_reasonable_mcap'],
                r['pred_low_zone'], r['pred_game_low'], r['pred_game_high'],
                r['pred_high_zone'], r['pred_midlong_target']))
